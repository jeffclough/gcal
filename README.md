# GCal

## Description
Access your Google Calendar from the command line.
Use the gcal command to maintain a database of email contacts for people who have expressed an interest in helping Patrick and family during his treatments.

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
