"""
This code requires some setup on Google Cloud Console.
https://cloud.google.com

1. Create a "gcal" project in Google Cloud Console. You'll have to make
   it an "external" project.
2. Create a Credentials JSON file, download it, and rename it to
   credentials.json. Store it in your ~/.local/gcal directory.
3. Enable the Google Calendar API for the gcal project.
"""

import datetime,os,re,sys

from debug import DebugChannel
from handy import prog,die,gripe

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

dc=DebugChannel(label='D')
#dc.enable()

# If modifying these scopes, delete the token.json file.
# Use 'https://www.googleapis.com/auth/calendar' for write access
SCOPES=['https://www.googleapis.com/auth/calendar.readonly']

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
            

def main():
    #
    # Make sure our application directory exists.
    #
    app_dir=os.path.expanduser(f"~/.local/{prog.name}")
    mkdirs(app_dir,0o750)
    fn_auth_tokens=os.path.join(app_dir,'token.json')
    fn_credentials=os.path.join(app_dir,'credentials.json')
    calendar_name='PRC Driving'

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
            flow = InstalledAppFlow.from_client_secrets_file(
                fn_credentials, SCOPES)  # Replace with the actual path
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(fn_auth_tokens, 'w') as token:
            token.write(creds.to_json())

    try:
        service = build('calendar', 'v3', credentials=creds)
        dc('Successfully authenticated and built the Google Calendar API service.')
        # You can now use the 'service' object to interact with your calendar.
        # Get the ID of the calendar we're interested in.
        calendar_list = service.calendarList().list().execute()
        calendars = calendar_list.get('items', [])
        for calendar in calendars:
            dc(f"Summary: {calendar.get('summary')}, ID: {calendar.get('id')}")
            if calendar.get('summary')==calendar_name:
                # List this calendar's upcoming events:
                now = datetime.datetime.utcnow().isoformat() + 'Z'
                events_result = service.events().list(calendarId='0c3a561627cb58fbe2e44dbb70dc6628e4b22b3cecb27573aa15cce4fa84dc7a@group.calendar.google.com', timeMin=now,
                                                      maxResults=30, singleEvents=True,
                                                      orderBy='startTime').execute()
                events = events_result.get('items', [])

                if not events:
                    print('No upcoming events found.')
                    break

                print('Upcoming events:')
                for event in events:
                    start = event['start'].get('dateTime',event['start'].get('date'))
                    print(start, event['summary'])

    except HttpError as error:
        die(f'An error occurred: {error}')

if __name__ == '__main__':
    main()
