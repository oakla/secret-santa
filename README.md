# Secret Santa

Draws names so everyone gives one gift and gets one, then emails each person their assignment. The assignment only appears inside an attached text file, so it won't show up in subject lines, inbox previews, file names or terminal output.

## Setup

Copy `participants.example.csv` to `participants.csv` and fill in everyone's name and email address. Git ignores `participants.csv` and `output/`.

## 1. Draw names

```bash
python secret_santa.py draw
```

This writes one email per person to `output/`, e.g. `output/Alex.eml`. It refuses to run again while `output/` holds a draw, so nobody can end up with an assignment from an old draw. Keep `output/` until the gift exchange in case someone needs their email again.

## 2. Send the emails

**Option A: send them yourself.** Open each `.eml` file in a desktop mail app and send it. Classic Outlook for Windows opens them as ready-to-send drafts. In Thunderbird use Edit as New Message, and in Apple Mail use Message > Send Again. Webmail can't open these files.

**Option B: let the script send them** over SMTP:

```bash
python secret_santa.py send --host smtp.gmail.com --user you@gmail.com
```

It lists who will get an email, asks you to confirm, then asks for your password. For Gmail, use an [app password](https://myaccount.google.com/apppasswords) (needs 2-Step Verification), not your normal password. Microsoft accounts (Outlook.com, Hotmail, and Microsoft 365 work or school accounts) usually block this, so use option A with those.

Sent emails move to `output/sent/`. If sending stops partway, fix the problem and run `send` again to send the rest. To resend someone's email, add their name, e.g. `python secret_santa.py send Alex --host ...`. Settings can also come from `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_FROM` and `SMTP_PASSWORD`, see `python secret_santa.py send --help`.

## Changing the wording

Edit `SUBJECT`, `BODY` and `ATTACHMENT` at the top of `secret_santa.py`.
