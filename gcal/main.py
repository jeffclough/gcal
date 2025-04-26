"""
This code requires some setup on Google Cloud Console.
https://cloud.google.com

1. Create a "gcal" project in Google Cloud Console. You'll have to make
   it an "external" project.
2. Create a Credentials JSON file, download it, and rename it to
   credentials.json. Store it in your ~/.local/gcal directory.
3. Enable the Google Calendar API for the gcal project.
"""

import datetime as dt,os,re,sys
from argparse import ArgumentParser
from zoneinfo import ZoneInfo

from debug import DebugChannel
from handy import prog,die,gripe,positive_int,CaselessString

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

dc=DebugChannel(label='D')

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
DEFAULT_CALENDAR_WINDOW=30

# Our default timezone is updated after we connect to Google's
# Calendar API.
TZ=ZoneInfo('America/New_York')

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
RECORD_RESPONSES=False
RESPONSES_FILE=os.path.join(app_dir,'api-responses')
if RECORD_RESPONSES and os.path.exists(RESPONSES_FILE):
    # Remove our responses file because we append responses to it.
    os.path.unlink(RESPONSES_FILE)

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
ap.add_argument('--debug',action='store_true',help="Turn on debugging output.")
ap.add_argument('--before',metavar='YYYY-MM-DD',action='store',type=dt.datetime.fromisoformat,default=today+dt.timedelta(days=DEFAULT_CALENDAR_WINDOW),help="Latest date to search for calendar entries. (default: %(default)s)")
ap.add_argument('--max',metavar='N',action='store',type=positive_int,default=None,help="If given, this is the maximum number of entries to find.")
ap.add_argument('--since',metavar='YYYY-MM-DD',action='store',type=dt.date.fromisoformat,default=today,help="Earliest date to search for calendar entries. (default: %(default)s)")
ap.add_argument('calendars',metavar='CALENDAR',type=CaselessString,nargs='*',action='store',help="The name(s) of one or more calendars to be searched. By default, all calendars are searched.")
opt=ap.parse_args()
dc.enable(opt.debug)
if dc:
    dc(f"{opt.before=}")
    dc(f"{opt.max=}")
    dc(f"{opt.since=}")
    dc(f"{opt.calendars=}")

 # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

class CalendarEvent():
    def __init__(self,event_dict):
        """
        Set our start, end, calendar, and name properties based on the
        event dectionary returned by the Google Calendar API. Raise
        ValueError if this dictionary doesn't look like a calendar
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

    def __str__(self):
        if self.allday:
            s=f"{str(self.start):.10}: {self.name} ({self.calendar})"
        else:
            s=f"{self.start} - {self.end}: {self.name} ({self.calendar})"
        return s

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
        from pprint import pprint
        with open(RESPONSES_FILE,'a') as f:
            print('\n---- service ----',file=f)
            pprint(service.__dict__,stream=f,width=200)

    return service

def get_calendar_entries(service,calendar_id):
    """
    Given an active Calendar API service and the ID of a calendar,
    return a list of CalendarEvent instances from that calendar.
    """

    res=service.events().list(calendarId=calendar_id,
                              timeMin=opt.since.isoformat()+'Z',
                              timeMax=opt.before.isoformat()+'Z',
                              maxResults=30,singleEvents=True,
                              orderBy='startTime'
                         ).execute()
    # For diagnostic and exploratory purposes, it is helpful to be able
    # to see the raw response dictionary the API returns.
    if RECORD_RESPONSES:
        from pprint import pprint
        with open(RESPONSES_FILE,'a') as f:
            print('\n---- service ----',file=f)
            pprint(res,stream=f,width=200)

    # Remember this calendar's default timezone.
    TZ=res.get('timeZone')
    if TZ is None:
        die(f"Google's Calendar API reports no default timezone for your account.")
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
        # Convert this list of tuples to a dictionary, filtering as we go.
        calendars={
            cname:cid
            for cname,cid in calendars
                if not cid.endswith('@group.v.calendar.google.com')
                    and (opt.calendars and cname in opt.calendars)
                #if opt.calendars and c.get('summary') in opt.calendars
        }
        dc(f"Calendars found: {len(calendars)}")

        # Get entries from our list of calendars.
        entries=[]
        for cname,cid in calendars.items():
            dc(f"{cname} (id={cid})").indent()
            events=get_calendar_entries(service,cid)
            entries.extend(events)
            dc.undent()

        # Sort our CalenderEvent objects by start time.
        entries.sort(key=lambda e:e.start)

        # Show the user what we've found.
        for e in entries:
            #start=e['start'].get('dateTime',e['start'].get('date'))
            #print(start,e['summary'])
            print(e)

    except HttpError as error:
        raise
        #die(f'An error occurred: {error}')

if __name__ == '__main__':
    main()
