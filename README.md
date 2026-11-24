# Secret Santa

Draws names, saves one file per person saying who they're buying for, then emails each person their file as an attachment. Nobody draws themselves, no two people draw each other, and the script never prints who has whom.

## Setup

Copy `participants.example.csv` to `participants.csv` and fill in everyone's name and email address. Git ignores `participants.csv`. The other settings (exclusions, output folder, previous draw, email wording and mail server) are at the top of `secret_santa.py`.

## 1. Draw names

```bash
python secret_santa.py
```

This saves one file per person in a new folder inside `OUTPUT_DIR`, such as `2026/11.24-15.30/Alex.txt`, and prints the commands for the next step.

## 2. Email everyone their file

Either make emails to send from your own mail app:

```bash
python secret_santa.py drafts 2026/11.24-15.30
```

This writes one email per person to the draw's `drafts` folder. Classic Outlook for Windows opens them ready to send. In Thunderbird use Edit as New Message, and in Apple Mail use Message > Send Again. Webmail can't open these files.

Or send them from the script:

```bash
python secret_santa.py send 2026/11.24-15.30
```

It asks for your email address, shows who will get an email, asks you to confirm, then asks for your password. It's set up for Gmail, which needs an [app password](https://myaccount.google.com/apppasswords) (2-Step Verification has to be on). For another provider, change `SMTP_HOST` and `SMTP_PORT`. Microsoft accounts (Outlook.com, Hotmail, and Microsoft 365 work or school accounts) usually block this, so use drafts with those.

A copy of each sent email goes in the draw's `sent` folder, and running `send` again only emails people who haven't had theirs yet. To email someone again, or to try it on yourself first, add their name: `python secret_santa.py send 2026/11.24-15.30 Alex`.

Both commands take the draw's folder inside `OUTPUT_DIR`, as above, or a full path. They look up email addresses in `participants.csv` when they run, so you can fix a wrong address without drawing again.
