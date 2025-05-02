# GCal

## Description
Access your Google Calendar from the command line.
Use the gcal command to maintain a database of email contacts for people who have expressed an interest in helping Patrick and family during his treatments.

## Usage
```
usage: gcal [-h] [--attachments] [--debug] [--end YYYY-MM-DD] [--list]
            [--location] [--max N] [--notes] [--start YYYY-MM-DD]
            [CALENDAR ...]

positional arguments:
  CALENDAR            The name(s) of one or more calendars to be searched. By
                      default, all calendars are searched.

options:
  -h, --help          show this help message and exit
  --attachments       Show attachments for each event that has at least one.
  --debug             Turn on debugging output.
  --end YYYY-MM-DD    Latest date to search for calendar entries. (default:
                      2025-07-25)
  --list              List the calendars available to the current user. Then
                      quit.
  --location          Show the location for each event that has a location.
  --max N             If given, this is the maximum number of entries to find.
  --notes             Show notes for each event that has notes.
  --start YYYY-MM-DD  Earliest date to search for calendar entries. (default:
                      2025-04-26)
```

## Installation
If you don't have pipx installed either run `pip3 install pipx`, or if that gives you an "externally-managed-environment" complaint, use whatever package manager is right for your operating system.

* [Debian](https://www.debian.org/doc/manuals/debian-faq/pkgtools.en.html): `apt-get install pipx`
* [Red Hat](https://www.redhat.com/en/blog/how-manage-packages): `yum install pipx`
* [HomeBrew](https://brew.sh): `brew install pipx`

Once pipx is installed, run `pipx install gcal` to install it to your `~/.local` directory. (Or run `pipx --global install gcal` to install it for all users on your system.)

<large>This code requires</large> some setup on [Google Cloud Console](https://cloud.google.com).

1. Create a "gcal" project in Google Cloud Console. You'll have to make
   it an "external" project.
2. Create a Credentials JSON file, download it, and rename it to
   credentials.json. Store it in your ~/.local/gcal directory.
3. Enable the Google Calendar API for the gcal project.

I'm using OAuth 2, but if you prefer (against all sound advice) to use an API key, the steps above will be different (and you'll have to modify the code at `service=...`).
