"""
This code requires some setup on Google Cloud Console.
https://cloud.google.com

1. Create a "gcal" project in Google Cloud Console. You'll have to make
   it an "external" project.
2. Create a Credentials JSON file, download it, and rename it to
   credentials.json. Store it in your ~/.local/gcal directory.
3. Enable the Google Calendar API for the gcal project.
"""

import datetime as dt,json,os,re,sys,zoneinfo
from argparse import ArgumentParser
from pprint import pprint
from zoneinfo import ZoneInfo

from debug import DebugChannel
from handy import prog,die,gripe,positive_int,CaselessString

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

dc=DebugChannel(label='D')

tz_local=dt.timezone(dt.timedelta(days=-1, seconds=68400), 'CDT')

# Consider adding mkdirs to the "handy" package.
def mkdirs(path,mode=0o777):
    """
    This is very similar to os.mkpath(), but any missing parent
    directories will be created (if possible), and if path already
    exists, no exception is raised (so long as the thing that exists
    is a directory).

    If a conflicting non-directory item is found while creating path or
    any of its parent directories, a FileExistsError error is raised.
    """

    @dc # Add debugging to this function.
    def _mkdirs(path,mode):
        # Maybe the directory already exists.
        if os.path.exists(path):
            if os.path.isdir(path):
                return # All is well.
            else:
                raise FileExistsError(f"{path!r} already exists as something other than a directory.")
        # Try to create this directory.
        parent=None
        try:
            os.mkdir(path,mode)
        except FileNotFoundError as e:
            # Record the name of the parent directory to be created.
            parent=os.path.dirname(path)
            if parent=='/':
                raise e
        if parent:
            # Create the parent directory (and any parents thereof).
            _mkdirs(parent,mode)
            # Create the directory our caller requested.
            os.mkdir(path,mode)

    path=os.path.abspath(path)
    _mkdirs(path,mode)

# Set the default number of days ahead to search.
DEFAULT_CALENDAR_WINDOW=90

# For adding one day to a date or datetime.
ONE_DAY=dt.timedelta(days=1)

# Our default timezone is updated after we connect to Google's
# Calendar API.
TZ=ZoneInfo('America/New_York')

# Remove this prefix from auto-generated events' notes.
AUTOGEN_WARNING='To see detailed information for automatically created events like this one, use the official Google Calendar app. https://g.co/calendar\n\n'

# If modifying these scopes, delete the token.json file.
# Use 'https://www.googleapis.com/auth/calendar' for write access
SCOPES=['https://www.googleapis.com/auth/calendar.readonly']

#
# Make sure our application directory exists. Our Google API credentials
# are stored here, so make it a private directory.
#
app_dir=os.path.expanduser(f"~/.local/{prog.name}")
mkdirs(app_dir,0o700) 
fn_auth_tokens=os.path.join(app_dir,'token.json')
fn_credentials=os.path.join(app_dir,'credentials.json')
calendar_name='PRC Driving'

# Whether and where to record API responses.
RECORD_RESPONSES=True
RESPONSES_FILE=os.path.join(app_dir,'api-responses')
if RECORD_RESPONSES and os.path.exists(RESPONSES_FILE):
    # Remove our responses file because we append responses to it.
    os.unlink(RESPONSES_FILE)

#
# See what's on our command line.
#
now=dt.datetime.now()
today=now-dt.timedelta(
    hours=now.hour,
    minutes=now.minute,
    seconds=now.second,
    microseconds=now.microsecond
)
ap=ArgumentParser()
ap.add_argument('--attachments',action='store_true',help="Show attachments for each event that has at least one.")
ap.add_argument('--debug',action='store_true',help="Turn on debugging output.")
ap.add_argument('--end',metavar='YYYY-MM-DD',action='store',type=dt.datetime.fromisoformat,default=today+dt.timedelta(days=DEFAULT_CALENDAR_WINDOW),help="Latest date to search for calendar entries. (default: %(default).10s)")
ap.add_argument('--list',action='store_true',help="List the calendars available to the current user. Then quit.")
ap.add_argument('--location',action='store_true',help="Show the location for each event that has a location.")
ap.add_argument('--max',metavar='N',action='store',type=positive_int,default=None,help="If given, this is the maximum number of entries to find.")
ap.add_argument('--notes',action='store_true',help="Show notes for each event that has notes.")
ap.add_argument('--start',metavar='YYYY-MM-DD',action='store',type=dt.datetime.fromisoformat,default=today,help="Earliest date to search for calendar entries. (default: %(default).10s)")
ap.add_argument('calendars',metavar='CALENDAR',type=CaselessString,nargs='*',action='store',help="The name(s) of one or more calendars to be searched. By default, all calendars are searched.")
opt=ap.parse_args()
dc.enable(opt.debug)
if dc:
    dc(f"{opt.end=}")
    dc(f"{opt.list=}")
    dc(f"{opt.location=}")
    dc(f"{opt.max=}")
    dc(f"{opt.notes=}")
    dc(f"{opt.start=}")
    dc(f"{opt.calendars=}")

# Delete our token.json file if this token has expired. This will lead the
# API to re-authenticate and create a new token good for an hour.
if os.path.exists(fn_auth_tokens):
    dc(f"Token file ({fn_auth_tokens}) exists.")
    with open(fn_auth_tokens) as f:
        t=json.load(f)
    x=dt.datetime.fromisoformat(t['expiry']).astimezone(tz_local)
    dc(f"Token expires {x}")
    if x<dt.datetime.now().replace(tzinfo=tz_local):
        dc(f"Deleting expired token file ({fn_auth_tokens}). (Will re-authenticate.)")
        os.unlink(fn_auth_tokens)
else:
    dc(f"Token file ({fn_auth_tokens}) not found. (Will re-authenticate.)")

 # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

class CalendarEvent():
    def __init__(self,event_dict):
        """
        Set these properties based on the given calendar dictionary
        returned by the Google Calendar API:

            start (datetime)
            end (datetime)
            allday (boolean)
            calendar (str)
            name (str)
            location (str)
            notes (str)
            attachments (list)

        Raise ValueError if this dictionary doesn't look like a calendar
        event.
        """

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
            self.start=self.start.replace(tzinfo=TZ)

        # The end value might be a dateTime or a date.
        t=ed.get('end',mt)
        self.end=t.get('dateTime',t.get('date'))
        if self.end:
            if 'T' not in self.end:
                self.end+='T00:00:00'
            self.end=dt.datetime.fromisoformat(self.end)
        if self.end.tzinfo is None:
            self.end=self.end.replace(tzinfo=TZ)

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

    def __str__(self):
        if self.allday:
            when=f"{str(self.start):.10}:               "
            s=[f"{self.name} ({self.calendar})"]
        else:
            if self.start.date()==self.end.date():
                when=f"{str(self.start):.16} - {str(self.end)[11:16]}: "
            else:
                when=f"{str(self.start):.16} - {str(self.end):.16}: "
            s=[f"{self.name} ({self.calendar})"]
        if opt.attachments and self.attachments:
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
        if opt.location and self.location:
            s.append(f"Location: {self.location}")
        if opt.notes and self.notes:
            s.extend(self.notes.split('\n')) # self.notes might contain its own newlines.
        dc(s)
        return when+(('\n'+' '*26)).join(s)

def authenticate():
    """
    Return the authenticated API service.
    """

    #
    # Set up an authenticated Google Calendar API service.
    #
    creds=None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists(fn_auth_tokens):
        creds=Credentials.from_authorized_user_file(fn_auth_tokens,SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow=InstalledAppFlow.from_client_secrets_file(fn_credentials,SCOPES) 
            creds=flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(fn_auth_tokens,'w') as token:
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

def get_calendar_events(service,calendar_id):
    """
    Given an active Calendar API service and the ID of a calendar,
    return a list of CalendarEvent instances from that calendar.
    """

    global TZ

    # Set up timezones for opt.start and opt.end if they have none.
    if opt.start.tzinfo is None:
        opt.start=opt.start.replace(tzinfo=ZoneInfo(str(TZ)))
        opt.end=opt.end.replace(tzinfo=ZoneInfo(str(TZ)))

    res=service.events().list(calendarId=calendar_id,
                              #timeMin=opt.start.isoformat()+'Z',
                              #timeMax=opt.end.isoformat()+'Z',
                              timeMin=opt.start.isoformat(),
                              timeMax=(opt.end+ONE_DAY).isoformat(),
                              maxResults=1000,singleEvents=True,
                              orderBy='startTime'
                         ).execute()
    # For diagnostic and exploratory purposes, it is helpful to be able
    # to see the raw response dictionary the API returns.
    if RECORD_RESPONSES:
        with open(RESPONSES_FILE,'a') as f:
            print('\n---- calendar ----',file=f)
            pprint(res,stream=f,width=200)

    # Remember this calendar's default timezone.
    TZ=res.get('timeZone')
    if TZ is None:
        die(f"Google's Calendar API reports no default timezone for the {calendar_id} calendar.")
    dc(f"Setting default timezone to {TZ} ...")
    TZ=ZoneInfo(TZ)

    # Get our list of event dictionaries from the API's response.
    # Convert them to CalendarEvent instances for easier handling.
    events=res.get('items',[])
    return [CalendarEvent(e) for e in events]
            
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
        dc(f"Calendars found: {len(calendars)}")
        dc(f"Subtracting Google's group calendars (Weather, etc.) and any calendars not given on the command line ...")
        # Convert this list of tuples to a {name:id) dictionary, filtering
        # as we go.
        calendars={
            cname:cid
            for cname,cid in calendars
                if not cid.endswith('@group.v.calendar.google.com')
                    and (not opt.calendars or cname in opt.calendars)
        }

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
            events.extend(get_calendar_events(service,cid))
            dc.undent()

        # Sort our CalenderEvent objects by start time.
        events.sort(key=lambda e:e.start)

        if opt.max and opt.max<len(events):
            del events[opt.max:]

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
