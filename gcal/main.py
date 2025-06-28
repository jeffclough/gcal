"""
This code requires some setup on Google Cloud Console.
https://cloud.google.com

1. Create a "gcal" project in Google Cloud Console. You'll have to make
   it an "external" project.
2. Create a Credentials JSON file, download it, and rename it to
   credentials.json. Store it in your ~/.local/gcal directory.
3. Enable the Google Calendar API for the gcal project.
"""

import csv,io,json,os,re,sys,zoneinfo
import datetime as dt
from argparse import ArgumentParser
from pprint import pprint
from time import time as epoch_time
from zoneinfo import ZoneInfo

from debug import DebugChannel
from handy import prog,die,gripe,positive_int,CaselessString

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

dc=DebugChannel(label='D')

# Get fixed values for the local day and time.
now=dt.datetime.now().astimezone()
today=now-dt.timedelta(
    hours=now.hour,
    minutes=now.minute,
    seconds=now.second,
    microseconds=now.microsecond
)

# Get local timezone.
tz_local=now.tzinfo

# Our default timezone is updated after we connect to Google's Calendar
# API, but we'll use the local timezone as a starting value.
tz_cal=tz_local

# Set the default number of days ahead to search.
DEFAULT_CALENDAR_WINDOW=90

# For adding one day to a date or datetime.
ONE_DAY=dt.timedelta(days=1)

# Remove this prefix from auto-generated events' notes.
AUTOGEN_WARNING='To see detailed information for automatically created events like this one, use the official Google Calendar app. https://g.co/calendar\n\n'

# If modifying these scopes, delete the token.json file.
# Use 'https://www.googleapis.com/auth/calendar' for write access
SCOPES=['https://www.googleapis.com/auth/calendar.readonly']

#
# Make sure our application directory exists. Our Google API credentials
# are stored here, so make it a private directory. We'll also store a
# JSON cache for each calendar we access here.
#
app_dir=os.path.expanduser(f"~/.local/{prog.name}")
os.makedirs(app_dir,0o700,exist_ok=True)
fn_credentials=os.path.join(app_dir,'credentials.json')
fn_auth_token=os.path.join(app_dir,'token.json')
cal_cache_dir=os.path.join(app_dir,'cal_cache')
os.makedirs(cal_cache_dir,0o700,exist_ok=True)
cal_cache_ttl=5*3600 # Cache files are only good for 5 minutes.

def list_from_csv(s):
    """Given a CSV row as a string, return the colums from that row as
    a list."""

    with io.StringIO(s) as s:
        r=csv.reader(s,quoting=csv.QUOTE_MINIMAL,skipinitialspace=True)
        l=[c.rstrip() for c in next(r)] # Strip trailing whitespace.
        return [c for c in l if c] # Return only non-blank columns.

def set_from_csv(s):
    """Given a CSV row as a string, return the colums from that row as
    a set."""

    return set(list_from_csv(s))

@dc
def date_validator(s):
    """Given a date string, return a datetime.datetime instance (or
    raise an ValueError exception."""

    m=re.match(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})$',s)
    dc(f"{m=}")
    if not m:
        raise ValueError(f"Invalid date format: {s!r}")
    dc(f"{m.groups()=}")
    y,m,d=(int(x) for x in m.groups())
    d=dt.datetime(y,m,d,0,0,0)
    dc(f"{d=}")
    return d

#
# See what's on our command line.
#
ap=ArgumentParser(
    epilog='''The "free" and "busy" values of --show are just two ways to say you want to see whether each calendar event is marked as free or busy. Use --free-days to get a list of non-busy days.'''
)
ap.add_argument('--debug',action='store_true',help="Turn on debugging output.")
ap.add_argument('--start',metavar='YYYY-MM-DD',action='store',default=today,help="Earliest date to search for calendar entries. (default: %(default).10s)")
ap.add_argument('--end',metavar='YYYY-MM-DD',action='store',default=today+dt.timedelta(days=DEFAULT_CALENDAR_WINDOW),help="Latest date to search for calendar entries. (default: %(default).10s)")
ap.add_argument('--list',action='store_true',help="List the calendars available to the current user. Then quit.")
ap.add_argument('--free-days',action='store_true',help="Report dates that contain no events.")
ap.add_argument('--max',metavar='N',action='store',type=positive_int,default=None,help="If given, this is the maximum number of entries to find.")
ap.add_argument('--not',metavar="CALENDAR[,...]",dest='no',action='store',type=set_from_csv,default=set(),help="One or more calendars NOT to report events for. Separate multiple caldar names with commas.")
ap.add_argument('--show',action='store',type=set_from_csv,default=set(),help="Set extra event attributes to be shown. Choices are attachments, busy, day, free, location, and notes. These maybe be combined in a single value of comma-separated items.")
ap.add_argument('--location',action='store_true',help="Show the location for each event that has a location.")
ap.add_argument('--notes',action='store_true',help="Show notes for each event that has notes.")
ap.add_argument('calendars',metavar='CALENDAR',type=CaselessString,nargs='*',action='store',help="The name(s) of one or more calendars to be searched. By default, all calendars are searched.")
opt=ap.parse_args()

# Cook a few of our options' values a bit.
dc.enable(opt.debug)
# Use the local timezone for start and end if no TZ is given.
if isinstance(opt.start,str):
    opt.start=date_validator(opt.start)
if isinstance(opt.end,str):
    opt.end=date_validator(opt.end)
if opt.start.tzinfo is None:
    opt.start=opt.start.astimezone()
if opt.end.tzinfo is None:
    opt.end=opt.end.astimezone()

# Whether and where to record API responses.
RECORD_RESPONSES=bool(dc) # Tie this to whether we're writing debug messsages.
RESPONSES_FILE=os.path.join(app_dir,'api-responses')
if RECORD_RESPONSES and os.path.exists(RESPONSES_FILE):
    # Remove our responses file because we append responses to it, and we
    # want only responses from the current run.
    os.unlink(RESPONSES_FILE)

if dc:
    dc(f"{opt.start=}")
    dc(f"{opt.end=}")
    dc(f"{opt.list=}")
    dc(f"{opt.max=}")
    dc(opt.no,'opt.no')
    dc(f"{opt.show=}")
    dc(opt.calendars,'opt.calendars')
    dc(f"{RECORD_RESPONSES=}")
    dc(f"{RESPONSES_FILE=}")

 # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

def day_range(start,end,inc=ONE_DAY):
    """This generator function yields each day included in the given
    start and end datetime values."""

    d=dt.date(start.year,start.month,start.day)
    end_day=dt.date(end.year,end.month,end.day)
    while d<end_day or (d==end_day and (end.hour or end.minute or end.second)):
        yield d
        d+=inc

class CalendarEvent():
    # Used for storing and parsing cached datetime values.
    aware_time_fmt="%Y-%m-%dT%H:%M:%S%z"
    naive_time_fmt="%Y-%m-%dT%H:%M:%S"

    class JSONEncoder(json.JSONEncoder):
        """A JSON encoder that handles datetime objects by converting
        them to strings."""

        def default(self,o):
            """If o is a datetime value, return the string form of that
            value. Otherwise, let the superclass do its thing."""

            if isinstance(o,datetime.datetime):
                # Convert timezone-aware datetime to string
                return o.strftime(CalendarEvent.a_time_fmt)
            # Let the base class default method raise the TypeError for other types
            return super().default(self,o)

    class JSONDecoder(json.JSONDecoder):
        """A JSON decoder that recognizes datetime strings and parses
        them to datetime values."""

        _naive_pat=re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$')
        _aware_pat=re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[-+]\d4$')

        def default(self,s):
            """If the given string is that of a formatted datetime
            value, parse that back to a datetime value and return that.
            Both timezone-aware and -naive values are handled.
            Otherwise, let the superclass do its thing."""

            if _aware_pat.match(s):
                return dt.datetime.strptime(s,aware_time_fmt)
            if _naive_pat.match(s):
                return dt.datetime.strptime(s,naive_time_fmt)
            return super().default(self,s)

   #class JSONDecoder(json.JSONDecoder):
   #    """Custom JSONDecoder that handles datetime strings by
   #    converting them back to datetime.datetime objects in specific
   #    dictionary fields."""
   #
   #    def __init__(self, *args, **kwargs):
   #        super().__init__(object_hook=self.object_hook, *args, **kwargs)
   #
   #    def object_hook(self, obj):
   #        # Check for specific keys that are known to contain datetime strings
   #        if 'start_time' in obj and 'end_time' in obj:
   #            try:
   #                obj['start_time'] = datetime.datetime.strptime(obj['start_time'], DATETIME_FORMAT)
   #                obj['end_time'] = datetime.datetime.strptime(obj['end_time'], DATETIME_FORMAT)
   #            except ValueError:
   #                print(f"Warning: Could not parse datetime in object_hook: {obj}")
   #                pass # Keep as string if parsing fails
   #        return obj

    def to_dict(self):
        """Return this CalendarEvent as a dictionary."""

        return dict(
            start=self.start,
            end=self.end,
            allday=self.allday,
            busy=self.busy,
            calendar=self.calendar,
            name=self.name,
            location=self.location,
            notes=self.notes,
            attachments=self.attachments
        )

    @classmethod
    def from_dict(cls,d):
        """Create and return a new CalendarEvent instance from the given
        dictionary."""

        e=CalendarEvent(None)
        e.start=d['start']
        e.end=d['end']
        e.allday=d['allday']
        e.busy=d['busy']
        e.calendar=d['calendar']
        e.name=d['name']
        e.location=d['location']
        e.notes=d['notes']
        e.attachments=d['attachments']
        return e
    
    def __init__(self,event_dict):
        """
        Set these properties based on the given calendar dictionary
        returned by the Google Calendar API:

            start (datetime)
            end (datetime)
            allday (boolean)
            busy (boolean)
            calendar (str)
            name (str)
            location (str)
            notes (str)
            attachments (list)

        Raise ValueError if this dictionary doesn't look like a calendar
        event.
        """

        if not event_dict:
            # We're just initializing an empty event.
            self.start=None
            self.end=None
            self.allday=None
            self.busy=None
            self.calendar=None
            self.name=None
            self.location=None
            self.notes=None
            self.attachments=None
            return

        ed=event_dict
        mt={}
        if ed.get('kind')!='calendar#event':
            raise ValueError(f"Dictionary is not a calendar event: {ed!r}")

        # The start value might be a dateTime or a date.
        self.allday=False
        t=ed.get('start',mt)
        if 'dateTime' in t:
            self.start=dt.datetime.fromisoformat(t['dateTime'])
        elif  'date' in t:
            self.start=dt.datetime.fromisoformat(t['date']+'T00:00:00')
            self.allday=True
        if self.start.tzinfo is None:
            self.start=self.start.replace(tzinfo=tz_cal)

        # Get he free/busy status of this event.
        self.busy=ed.get('transparency','opaque')=='opaque'

        # The end value might be a dateTime or a date.
        t=ed.get('end',mt)
        self.end=t.get('dateTime',t.get('date'))
        if self.end:
            if 'T' not in self.end:
                self.end+='T00:00:00'
            self.end=dt.datetime.fromisoformat(self.end)
        if self.end.tzinfo is None:
            self.end=self.end.replace(tzinfo=tz_cal)

        ## Ensure one-day events begin and end on the same day.
        #if self.allday:
        #    self.end-=ONE_DAY

        # The calendar name might be a displayName or an email address.
        org=ed.get('organizer',mt)
        self.calendar=org.get('displayName',org.get('email','UNKNOWN'))

        # The name is comparatively straight-forward.
        self.name=ed.get('summary','UNKNOWN')

        # Location
        self.location=ed.get('location','')

        # Notes
        self.notes=ed.get('description','')
        if self.notes.startswith(AUTOGEN_WARNING):
            if 'htmlLink' in ed:
                link=ed['htmlLink']
                self.notes=f"See {link} for these notes auto-generated from email."
            else:
                self.notes=self.notes[len(AUTOGEN_WARNING):]

        # If attachments are available, they'll be available in our attachments
        # property as a list of anonymous objects, a, where a.title and
        # a.fileURL hold the English description and URL of the attachment,
        # respectively. If there are no attachments, self.attachments will be
        # an empty list.

        self.attachments=[
            type('',(),({
                    k:v
                        for k,v in a.items()
                            if k in ('fileUrl','title')
                }))
                    for a in ed.get('attachments',[])
        ]

        # So, e.g., you can iterate through attachments of CalendarEvent e like this:
        #
        # for a in e.attachments:
        #     print(f"{a.title}: {a.fileUrl}")

    def occurs_on(self,day):
        """Return True if this event occurs on the givne day."""

        return day in day_range(self.start,self.end)

    def __str__(self):
        # Set default start and end formats and corresponding widths.
        sdfmt=edfmt='%m-%d'
        sw=ew=5
        # Add to strftime format as called for.
        if 'year' in opt.show:
            sdfmt='%Y-'+sdfmt
            sw+=5
        if 'day' in opt.show:
            sdfmt='%a '+sdfmt
            sw+=4
            edfmt='%a '+edfmt
            ew+=4
        if 'busy' in opt.show:
            sdfmt=('busy ' if self.busy else 'free ')+sdfmt
            sw+=5
        if self.allday:
            end=self.end-ONE_DAY
            if self.start==end:
                when=f"{self.start.strftime(sdfmt)}: "+(' '*ew)
               #when=f"{str(self.start):.10}:               "
            else:
                when=f"{self.start.strftime(sdfmt)} - {self.end.strftime(edfmt)}: "
               #when=f"{str(self.start):.10} - {str(end):.10}:  "
            s=[f"{self.name} ({self.calendar})"]
        else:
            sdfmt+=' %H:%M'
            sw+=6
            if self.start.date()==self.end.date():
                edfmt=' %H:%M'
                ew=6
                when=f"{self.start.strftime(sdfmt)} - {self.end.strftime(edfmt)}: "
            else:
                edfmt=' %H:%M'
                ew+=6
                when=f"{self.start.strftime(sdfmt)} - {self.end.strftime(edfmt)}: "
            s=[f"{self.name} ({self.calendar})"]
        if 'attachments' in opt.show and self.attachments:
            if len(self.attachments)==1:
                s.extend([
                    f"Attachment:",
                    f"  {self.attachments[0].title}: {self.attachments[0].fileUrl}"
                ])
            else:
                s.append("Attachments:")
                s.extend(
                    f"  {i+1}. {a.title}: {a.fileUrl}"
                        for i,a in enumerate(self.attachments)
                )
        if 'location' in opt.show and self.location:
            s.append(f"Location: {self.location}")
        if 'notes' in opt.show and self.notes:
            s.extend(self.notes.split('\n')) # self.notes might contain its own newlines.
        #dc(s)
        return when+(('\n'+' '*26)).join(s)

class Calendar(list):
    """A specialized list to hold CalendarEntry items and support
    caching."""

    @dc
    def __init__(self,name,calendar_id,events=None):
        self.name=name
        self.id=calendar_id
        super().__init__(events if events else [])

    @staticmethod
    def get_cache_filename(calendar_name):
        """Compose and return the full pathname to this Calendar's
        cache file."""

        return os.path.join(cal_cache_dir,f"{calendar_name}.json")

    def to_cache(self):
        """Write the given list of events to the cache for the named
        file."""

        filename=Calendar.get_cache_filename(self.name)
        dc(f"{filename=}")
        with open(filename,'w',encoding='utf-8') as f:
            d=dict(
                type=self.__class__.__name__,
                written=dt.datetime.now().astimezone(),
                name=self.name,
                calendar_id=self.id,
                data=self
            )
            dc(d)
            json.dump(d,f,indent=2,cls=CalandarEntry.JSONEncode)

    @classmethod
    def from_cache(cls,calendar_name):
        """Read and return a list of cached events from the named file. If
        the cache file isn't there, or if it's more than 5 minutes old,
        return None."""

       #if not os.path.isfile(filename)
       #   or os.path.getmtime(filename)<epoch_time()-cal_cache_ttl:
       #    return None

        filename=Calendar.get_cache_filename(calendar_name)
        dc(f"{filename=}")
        with open(filename,'r',encoding='utf-8') as f:
            cache=json.load(f,cls=CalendarEntry.JSONDecode)
            dc(cache,'cache')
            cache=type('',(),cache)
            if d.written<now-cal_cache_ttl:
                return None
            assert cache.type==cls.__name__,f"Wrong data type found in cache file {filename}."
            assert cache.name==calendar_name,f"Wrong calendar found in cache file {filename}."
            return Calendar(cache.name,cache.data)

    def get_events(self,calendar_service,calendar_id):
        """
        Given an active Calendar API service and the ID of a calendar,
        return a list of CalendarEvent instances from that calendar.
        """

        global tz_cal

        # Set up timezones for opt.start and opt.end if they have none.
        if opt.start.tzinfo is None:
            opt.start=opt.start.replace(tzinfo=ZoneInfo(str(tz_cal)))
        if opt.end.tzinfo is None:
            opt.end=opt.end.replace(tzinfo=ZoneInfo(str(tz_cal)))

        res=calendar_service.events().list(
            calendarId=calendar_id,
            timeMin=opt.start.isoformat(),
            timeMax=(opt.end+ONE_DAY).isoformat(),
            maxResults=250,singleEvents=True,
            orderBy='startTime'
        ).execute()
        # For diagnostic and exploratory purposes, it is helpful to be able
        # to see the raw response dictionary the API returns.
        if RECORD_RESPONSES:
            with open(RESPONSES_FILE,'a') as f:
                print('\n---- calendar ----',file=f)
                pprint(res,stream=f,width=200)

        # Remember this calendar's default timezone.
        tz_cal=res.get('timeZone')
        if tz_cal is None:
            die(f"Google's Calendar API reports no default timezone for the {calendar_id} calendar.")
        dc(f"Setting default timezone to {tz_cal} ...")
        tz_cal=ZoneInfo(tz_cal)

        # Get our list of event dictionaries from the API's response.
        # Convert them to CalendarEvent instances for easier handling.
        events=res.get('items',[])
        return [CalendarEvent(e) for e in events]
            
def authenticate():
    """
    Return the authenticated API service.
    """

    #
    # Set up an authenticated Google Calendar API service.
    #
    creds=None
    # The file token.json stores the user's access and refresh token, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists(fn_auth_token):
        creds=Credentials.from_authorized_user_file(fn_auth_token,SCOPES)
        if dc:
            dc(f"Token data from {fn_auth_token} ...")
            dc(json.loads(creds.to_json()))
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                dc("Received exception {e} while refreshing token.")
                flow=InstalledAppFlow.from_client_secrets_file(fn_credentials,SCOPES)
                creds=flow.run_local_server(port=0,access_type='offline')
        else:
            flow=InstalledAppFlow.from_client_secrets_file(fn_credentials,SCOPES) 
            #creds=flow.run_local_server(port=0)
            creds=flow.run_local_server(port=0,access_type='offline')
        # Save the credentials for the next run
        with open(fn_auth_token,'w') as token:
            token.write(creds.to_json())

    service=build('calendar','v3',credentials=creds)
    dc("Successfully authenticated and built the Google Calendar API service.")
    # You can now use the 'service' object to interact with your calendar.

    # For diagnostic and exploratory purposes, it is helpful to be able
    # to see the raw response dictionary the API returns.
    if RECORD_RESPONSES:
        with open(RESPONSES_FILE,'a') as f:
            print('\n---- service ----',file=f)
            pprint(service.__dict__,stream=f,width=200)

    return service

def main():
    try:
        # Authenticate and connect to the Google Calendar API service.
        service=authenticate()

        # Get the ID of each calendar we're interested in.
        calendar_list=service.calendarList().list().execute()
        calendars=[
            (c.get('summary'),c.get('id'))
                for c in calendar_list.get('items',list())
        ]
        dc(f"Subtracting Google's group calendars (Weather, etc.) and any calendars not given on the command line ...")
        # Convert this list of tuples to a {name:id) dictionary, filtering
        # as we go.
        calendars={
            cname:cid
            for cname,cid in calendars
                if not cid.endswith('@group.v.calendar.google.com')
                    and cname not in opt.no
                    and (not opt.calendars or cname in opt.calendars)
        }
        dc(list(calendars.keys()),'calendars.keys()')

        if opt.list:
            # Show available calendars, and quit.
            l=[CaselessString(s) for s in calendars.keys()]
            l.sort()
            print('\n'.join(l))
            sys.exit(0)

        # Get CalendarEvent items from our list of calendars.
        dc(f"Calendars found: {len(calendars)}")
        events=[]
        for cname,cid in calendars.items():
            dc(f"Calendar {cname} (id={cid})").indent()
            cal=Calendar(cname,cid)
            l=cal.get_events(service,cid)
            events.extend(l)
            dc.undent()

        # Sort our CalenderEvent objects by start time.
        events.sort(key=lambda e:e.start)

        if opt.max and opt.max<len(events):
            del events[opt.max:]

        if opt.free_days:
            # Assume they're all free.
            free_days=set(list(day_range(opt.start,opt.end)))
            # Remove busy days.
            for e in events:
                if e.busy:
                    for d in day_range(e.start,e.end):
                        if d in free_days:
                            free_days.remove(d)
            # Show the user the free days we're left with.
            free_days=sorted(list(free_days))
            for d in free_days:
                print(d.strftime('%Y-%m-%d %a'))
            sys.exit(0)

        # Show the user what we've found.
        while events:
            e=events.pop(0)
            print(e)
            if events:
                print(25*'-')

    except HttpError as error:
        raise
        #die(f'An error occurred: {error}')

if __name__ == '__main__':
    main()
