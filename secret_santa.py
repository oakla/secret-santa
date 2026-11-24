"""Draw Secret Santa names and email everyone their assignment.

  python secret_santa.py draw   write one email per person to output/
  python secret_santa.py send   send them over SMTP (or open each .eml and send it yourself)

Assignments only ever appear inside the email attachments: never in subjects,
email bodies, file names or terminal output. See README.md for setup.
"""
import argparse
import csv
import getpass
import os
import random
import re
import smtplib
import ssl
import sys
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formataddr, formatdate, make_msgid, parseaddr
from pathlib import Path

PARTICIPANTS = Path('participants.csv')
OUTDIR = Path('output')
SENTDIR = OUTDIR / 'sent'

SUBJECT = 'Your Secret Santa assignment'
BODY = """\
Hi {giver},

Your Secret Santa assignment is in the attached file. Open it when nobody
else can see your screen.
"""
ATTACHMENT_NAME = 'secret-santa.txt'
# The blank lines keep the name out of attachment previews and thumbnails.
ATTACHMENT = """\
Hello {giver}!

Make sure nobody else can see your screen, then scroll down for your
Secret Santa assignment.
{blank_lines}
You have been assigned to give a gift to {receiver}.
"""
BLANK_LINES = 100


def read_participants(path):
    """Return {name: email} from a CSV file with name and email columns."""
    try:
        with open(path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            reader.fieldnames = [h.strip().lower() for h in reader.fieldnames or []]
            if not {'name', 'email'} <= set(reader.fieldnames):
                sys.exit(f'{path} needs a header row: name,email')
            rows = [((row['name'] or '').strip(), (row['email'] or '').strip()) for row in reader]
    except FileNotFoundError:
        sys.exit(f'{path} not found. Copy participants.example.csv to {path} and fill it in.')

    people = {}
    for name, email in rows:
        if not (name or email):
            continue
        if not name or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
            sys.exit(f'{path}: every row needs a name and a valid email address, got {name!r}, {email!r}')
        for other, other_email in people.items():
            if eml_name(other).casefold() == eml_name(name).casefold():
                sys.exit(f'{path}: {other!r} and {name!r} need more distinct names')
            if other_email.casefold() == email.casefold():
                sys.exit(f"{path}: {other} and {name} share an email address, so they would see each other's assignment")
        people[name] = email
    if len(people) < 3:
        sys.exit(f'{path}: Secret Santa needs at least 3 people')
    return people


def eml_name(name):
    """File name for someone's email, e.g. 'Mary Jane' -> 'Mary_Jane.eml'."""
    return re.sub(r'[^\w-]+', '_', name).strip('_') + '.eml'


def draw(names):
    """Put everyone in one random circle; each person gives to the next."""
    circle = random.sample(names, len(names))
    return dict(zip(circle, circle[1:] + circle[:1]))


def build_email(giver, email, receiver):
    msg = EmailMessage(policy=policy.SMTP.clone(cte_type='7bit'))
    msg['To'] = formataddr((giver, email))
    msg['Subject'] = SUBJECT
    msg['X-Unsent'] = '1'  # makes Outlook open the .eml as a draft
    msg.set_content(BODY.format(giver=giver))
    text = ATTACHMENT.format(giver=giver, receiver=receiver, blank_lines='\n' * BLANK_LINES)
    # base64 keeps the name unreadable if the .eml is opened in a text editor
    msg.add_attachment(text, filename=ATTACHMENT_NAME, cte='base64')
    return msg


def cmd_draw(args):
    people = read_participants(PARTICIPANTS)
    if any(OUTDIR.glob('*.eml')) or any(SENTDIR.glob('*.eml')):
        sys.exit(f'{OUTDIR}/ already holds a draw. Delete it if you really want to draw again.')
    pairs = draw(list(people))
    OUTDIR.mkdir(exist_ok=True)
    # Write in participant order: writing in circle order would leak the
    # assignments through file timestamps.
    for giver, email in people.items():
        (OUTDIR / eml_name(giver)).write_bytes(build_email(giver, email, pairs[giver]).as_bytes())
    print(f'Wrote emails for {len(people)} people to {OUTDIR}/. Open each .eml in your mail app\n'
          'and send it, or see: python secret_santa.py send --help')


def find_emails(names):
    """Unsent emails, or the named people's emails whether sent or not."""
    unsent = sorted(OUTDIR.glob('*.eml'))
    sent = sorted(SENTDIR.glob('*.eml'))
    if not (unsent or sent):
        sys.exit(f'No emails in {OUTDIR}/. Run draw first.')
    if not names:
        if not unsent:
            sys.exit('Every email has been sent. To resend one, name the person: send NAME')
        return unsent
    by_name = {path.name.casefold(): path for path in sent + unsent}
    picked = {}
    for name in names:
        path = by_name.get(eml_name(name).casefold())
        if path is None:
            choices = ', '.join(sorted(path.stem for path in by_name.values()))
            sys.exit(f'No email for {name!r}. Choose from: {choices}')
        picked[path] = None
    return list(picked)


def connect(host, port, user, password):
    context = ssl.create_default_context()
    if port == 465:
        smtp = smtplib.SMTP_SSL(host, port, context=context, timeout=60)
    else:
        smtp = smtplib.SMTP(host, port, timeout=60)
        smtp.starttls(context=context)
    smtp.login(user, password)
    return smtp


def cmd_send(args):
    paths = find_emails(args.names)
    if not (args.host and args.user):
        sys.exit('send needs --host and --user (or SMTP_HOST and SMTP_USER). See send --help.')
    messages = []
    for path in paths:
        with open(path, 'rb') as f:
            messages.append((path, BytesParser(policy=policy.default).parse(f)))
    sender = args.sender or args.user
    print(f'From {sender} via {args.host}:{args.port} to:')
    for _, msg in messages:
        print(f'  {msg["To"]}')
    if input(f'Send {len(messages)} email(s)? [y/N] ').strip().lower() not in ('y', 'yes'):
        sys.exit('Nothing sent.')
    password = os.environ.get('SMTP_PASSWORD') or getpass.getpass(f'Password for {args.user}: ')

    SENTDIR.mkdir(parents=True, exist_ok=True)
    domain = parseaddr(sender)[1].rpartition('@')[2] or None
    done = 0
    try:
        with connect(args.host, args.port, args.user, password) as smtp:
            for path, msg in messages:
                del msg['X-Unsent']
                for header, value in [('From', sender), ('Date', formatdate(localtime=True)),
                                      ('Message-ID', make_msgid(domain=domain))]:
                    del msg[header]
                    msg[header] = value
                smtp.send_message(msg)
                if path.parent != SENTDIR:
                    path.replace(SENTDIR / path.name)
                done += 1
                print(f'Sent to {msg["To"]}')
    except smtplib.SMTPAuthenticationError as e:
        sys.exit(f'Login failed: {e}\nGmail needs an app password, see README.md.')
    except (smtplib.SMTPException, OSError) as e:
        sys.exit(f'Stopped after sending {done} of {len(messages)}: {e}\n'
                 'Fix the problem and run the same command again.')


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('draw', help=f'draw names from {PARTICIPANTS} and write the emails')
    send = commands.add_parser(
        'send', help='send the emails over SMTP',
        description='Send the emails in output/ over SMTP, moving each to output/sent/ once sent. '
                    'The password comes from SMTP_PASSWORD or a prompt.')
    send.add_argument('names', nargs='*', help="only send (or resend) these people's emails")
    send.add_argument('--host', default=os.environ.get('SMTP_HOST'),
                      help='SMTP server, e.g. smtp.gmail.com (env SMTP_HOST)')
    send.add_argument('--port', type=int, default=int(os.environ.get('SMTP_PORT', 587)),
                      help='587 for STARTTLS or 465 for SSL (env SMTP_PORT, default 587)')
    send.add_argument('--user', default=os.environ.get('SMTP_USER'),
                      help='SMTP login, usually your email address (env SMTP_USER)')
    send.add_argument('--from', dest='sender', default=os.environ.get('SMTP_FROM'),
                      help='From address, if not the --user address (env SMTP_FROM)')
    args = parser.parse_args()
    {'draw': cmd_draw, 'send': cmd_send}[args.command](args)


if __name__ == '__main__':
    main()
