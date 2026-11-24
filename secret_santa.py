r"""Secret santa draw.

List everyone in participants.csv (copy participants.example.csv), check the
settings below, then run:

    python secret_santa.py

Each run writes one file per person to a new folder inside OUTPUT_DIR, such
as 2026\11.24-15.30\Alex.txt. To use another folder for one run:

    python secret_santa.py --output "D:\Somewhere else"

Then email everyone their file as an attachment, either as drafts you open
and send from your mail app, or sent straight from here:

    python secret_santa.py drafts 2026/11.24-15.30
    python secret_santa.py send 2026/11.24-15.30

Nobody draws themselves, no two people draw each other, and the script
never prints who has whom.
"""
import argparse
import csv
import getpass
import itertools
import math
import random
import re
import smtplib
import ssl
import sys
from datetime import datetime
from email import policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

# Everyone taking part: a CSV file with a header row of name,email and a row
# per person. A relative path means next to this script. Only drafts and
# send need the email addresses, and they look them up when they run.
PARTICIPANTS_FILE = 'participants.csv'

# Pairs who must not draw each other, either way round (e.g. partners).
EXCLUDED_PAIRS = [
    # ('Alex', 'Debbie'),
    ('Chris', 'Debbie'),
    ('Glen', 'Jess'),
]

# Where each run's folder goes. --output overrides it for one run. If the
# folder can't be found (e.g. Google Drive isn't running), the script asks.
OUTPUT_DIR = r'G:\My Drive\Secret-Santa'

# The last draw you sent, so nobody gets the same person again: its folder
# inside the output folder, such as '2025/12.01-19.30', or a full path such
# as 'D:/Old/2025/12.01-19.30'. Use forward slashes. Each run prints the
# value to use next time. None to skip.
PREVIOUS_DRAW = Path(r'G:\My Drive\Secret-Santa\2025')

# read_draw() finds the receiver in old files by "give a gift to <name>." at
# the end of a line, so keep that if you change the message (put anything
# else on a line of its own).
MESSAGE = 'Hello {giver}!\n\nYou have been assigned to give a gift to {receiver}.\n'

# The email that drafts and send attach each person's file to.
SUBJECT = 'Your Secret Santa assignment'
BODY = """\
Hi {giver},

Your Secret Santa assignment is in the attached file. Open it when nobody
else can see your screen.
"""
ATTACHMENT_NAME = 'secret-santa.txt'

# The outgoing mail server for send, which asks for your address and
# password. Gmail needs an app password: https://myaccount.google.com/apppasswords
# Port 587 uses STARTTLS and 465 uses SSL.
SMTP_HOST = 'smtp.gmail.com'
SMTP_PORT = 587

# Up to this many candidate draws (9 people), all are checked: the pick is
# exact and the script can say how many draws were possible. With more people
# it makes random draws until one fits, up to MAX_TRIES times.
MAX_CANDIDATES_TO_CHECK = 500_000
MAX_TRIES = 100_000

# Warn when this few draws (or fewer) fit the exclusions.
FEW_DRAWS = 5


class DrawError(Exception):
    pass


def allowed(draw, banned):
    """Nobody draws themselves, no two people draw each other, and no banned
    (giver, receiver) pair is used."""
    return all(receiver != giver and draw[receiver] != giver
               and (giver, receiver) not in banned
               for giver, receiver in draw.items())


def make_draw(people, banned, rng=random):
    """Pick at random, all equally likely, one of the allowed draws.

    Returns (draw, count): draw is {giver: receiver}, and count is how many
    draws were possible, or None if there were too many to check. Raises
    DrawError if none fit.
    """
    if math.factorial(len(people)) <= MAX_CANDIDATES_TO_CHECK:
        chosen, count = None, 0
        for receivers in itertools.permutations(people):
            draw = dict(zip(people, receivers))
            if allowed(draw, banned):
                count += 1
                if rng.randrange(count) == 0:  # keeps each with chance 1/count
                    chosen = draw
        if chosen is None:
            raise DrawError('No draw fits these exclusions. Remove some and try again.')
        return chosen, count
    receivers = list(people)
    for _ in range(MAX_TRIES):
        rng.shuffle(receivers)
        draw = dict(zip(people, receivers))
        if allowed(draw, banned):
            return draw, None
    raise DrawError("Couldn't find a draw that fits these exclusions. Try removing some.")


def read_draw(folder):
    """Read a draw back from its files, as {giver: receiver}."""
    pattern = re.compile(r'give a gift to (.+)\.$', re.MULTILINE)
    draw = {}
    for path in Path(folder).glob('*.txt'):
        match = pattern.search(path.read_text(encoding='utf-8'))
        if match:
            draw[path.stem] = match.group(1)
    if not draw:
        raise DrawError(f'No previous draw found in {folder}')
    # Everyone who received a gift also gave one, so has a file too.
    missing = set(draw.values()) - set(draw)
    if missing:
        raise DrawError(f'The previous draw in {folder} has no file for: '
                        + ', '.join(sorted(missing)))
    return draw


def banned_pairs(people, excluded_pairs, previous):
    """Return the (giver, receiver) pairs the draw must avoid."""
    if len(people) < 3:
        raise DrawError('Need at least three participants: two could only draw each other.')
    if len(set(people)) != len(people):
        raise DrawError('Each participant needs a different name.')
    for pair in excluded_pairs:
        if isinstance(pair, str) or len(pair) != 2:
            raise DrawError("Each EXCLUDED_PAIRS entry should be two names, "
                            f"like ('Alex', 'Debbie'), not {pair!r}")
    unknown = {name for pair in excluded_pairs for name in pair} - set(people)
    if unknown:
        raise DrawError('EXCLUDED_PAIRS has names that are not in the participants file: '
                        + ', '.join(sorted(unknown)))
    banned = set(previous.items())
    for a, b in excluded_pairs:
        banned |= {(a, b), (b, a)}
    return banned


def message(giver, receiver, people):
    """The giver's message, padded with trailing spaces to the same size
    whoever they drew, so file sizes don't hint at who has whom."""
    def size(text):
        return len(text.encode('utf-8'))
    text = MESSAGE.format(giver=giver, receiver=receiver)
    width = max(size(MESSAGE.format(giver=giver, receiver=other)) for other in people)
    return text + ' ' * (width - size(text))


def choose_output(folder):
    """Return folder if it exists, otherwise ask where to save instead."""
    while not folder.is_dir():
        print(f"Can't find the folder {folder}")
        try:
            answer = input('Where should the files go? Type a folder, or press Enter to quit: ')
        except (EOFError, KeyboardInterrupt):
            answer = ''
        answer = answer.strip().strip('"')  # Explorer's "Copy as path" adds quotes
        if not answer:
            raise DrawError('No output folder chosen.')
        folder = Path(answer).expanduser()
        if not folder.exists() and folder.parent.is_dir():
            folder.mkdir()
    return folder


def make_run_folder(parent):
    """Make a new folder for this run, such as parent/2026/11.24-15.30."""
    now = datetime.now()
    year, stamp = parent / now.strftime('%Y'), now.strftime('%m.%d-%H.%M')
    folder, n = year / stamp, 2
    while folder.exists():  # another run in the same minute
        folder, n = year / f'{stamp}_{n}', n + 1
    folder.mkdir(parents=True)
    return folder


def participants_path():
    return Path(__file__).parent / PARTICIPANTS_FILE


def read_participants(path):
    """Read the participants file into {name: email address}, in file order.
    Addresses can be blank: only drafts and send need them."""
    try:
        with open(path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            reader.fieldnames = [h.strip().lower() for h in reader.fieldnames or []]
            if not {'name', 'email'} <= set(reader.fieldnames):
                raise DrawError(f'{path} needs a header row: name,email')
            people, seen = {}, {}
            for row in reader:
                name, address = (row['name'] or '').strip(), (row['email'] or '').strip()
                if not name:
                    if address:
                        raise DrawError(f'{path} has an email address with no name: {address}')
                    continue
                if name.casefold() in seen:
                    raise DrawError(f'{path} has {seen[name.casefold()]!r} and {name!r}. '
                                    'Give everyone a different name.')
                seen[name.casefold()] = name
                people[name] = address
    except FileNotFoundError:
        raise DrawError(f"Can't find {path}. Make it by copying participants.example.csv.") from None
    except UnicodeDecodeError:
        raise DrawError(f'Save {path} as UTF-8 (in Excel, choose CSV UTF-8).') from None
    return people


def draw_names(output):
    """Make a draw and save it as one file per person in a new run folder."""
    previous_name = str(PREVIOUS_DRAW) if PREVIOUS_DRAW else None
    if previous_name and not previous_name.isprintable():
        # Backslashes in a normal string can turn into other characters:
        # in '2025\12.01', \12 becomes a newline.
        raise DrawError('Write PREVIOUS_DRAW with forward slashes, '
                        "like '2025/12.01-19.30'.")
    people = list(read_participants(participants_path()))
    output = choose_output(output)
    previous_folder = output / previous_name if previous_name else None
    previous = read_draw(previous_folder) if previous_folder else {}
    banned = banned_pairs(people, EXCLUDED_PAIRS, previous)
    draw, count = make_draw(people, banned)

    if previous:
        print(f'Avoiding repeats of the draw in {previous_folder}')
        gone = set(previous) - set(people)
        new = set(people) - set(previous)
        if gone:
            print('In that draw but not this one: ' + ', '.join(sorted(gone)))
        if new:
            print('Not in that draw: ' + ', '.join(sorted(new))
                  + " (if that's a new spelling, use the old one)")

    if count is not None:
        print(f'Picked at random from {count} possible draws.')
        if count <= FEW_DRAWS:
            print('That is very few: people may be able to work out who has whom. '
                  'Fewer exclusions would help.')

    folder = make_run_folder(output)
    # Write in list order, not draw order: file times would otherwise give
    # away the chain of who has whom.
    for giver in people:
        text = message(giver, draw[giver], people)
        (folder / f'{giver}.txt').write_text(text, encoding='utf-8')
    print(f'Wrote {len(draw)} files to {folder}')
    # The short form only works if next time's files go to the same place.
    hint = folder.relative_to(output) if output == Path(OUTPUT_DIR) else folder.resolve()
    print(f"Next time, set PREVIOUS_DRAW = '{hint.as_posix()}'")
    print(f'Email everyone their file:  python secret_santa.py send "{hint.as_posix()}"\n'
          f'or make drafts to send yourself:  python secret_santa.py drafts "{hint.as_posix()}"')


def read_files(folder):
    """A saved draw's files, as {giver: file contents}."""
    if not folder.is_dir():
        raise DrawError(f"Can't find the folder {folder}")
    files = {path.stem: path.read_bytes() for path in sorted(folder.glob('*.txt'))}
    if not files:
        raise DrawError(f'No draw files (.txt) in {folder}')
    return files


def addresses(givers):
    """Look up each giver's email address in the participants file."""
    path = participants_path()
    people = read_participants(path)
    problems, owners = [], {}
    for giver in givers:
        address = people.get(giver)
        if address is None:
            problems.append(f'{giver} is not in {path}')
        elif not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', address):
            problems.append(f'{giver} needs a valid email address in {path}')
        elif address.casefold() in owners:
            problems.append(f'{owners[address.casefold()]} and {giver} have the same email '
                            "address, so they would see each other's file")
        else:
            owners[address.casefold()] = giver
    if problems:
        raise DrawError('\n'.join(problems))
    return {giver: people[giver] for giver in givers}


def build_email(giver, address, attachment):
    """An email to giver with their draw file attached, exactly as saved."""
    email = EmailMessage(policy=policy.SMTP.clone(cte_type='7bit'))
    email['To'] = formataddr((giver, address))
    email['Subject'] = SUBJECT
    email.set_content(BODY.format(giver=giver))
    # base64 keeps the name unreadable if the email is opened as plain text
    email.add_attachment(attachment, maintype='text', subtype='plain',
                         filename=ATTACHMENT_NAME, params={'charset': 'utf-8'})
    return email


def make_drafts(folder):
    """Write an email per person to folder/drafts, for sending by hand."""
    files = read_files(folder)
    to = addresses(files)
    drafts = folder / 'drafts'
    drafts.mkdir(exist_ok=True)
    for giver, attachment in files.items():
        email = build_email(giver, to[giver], attachment)
        email['X-Unsent'] = '1'  # makes Outlook open it as a draft, ready to send
        (drafts / f'{giver}.eml').write_bytes(email.as_bytes())
    print(f'Wrote {len(files)} emails to {drafts}\n'
          'Open each one in your mail app and send it.')


def ask(prompt):
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return ''


def connect(host, port, user, password):
    context = ssl.create_default_context()
    if port == 465:
        smtp = smtplib.SMTP_SSL(host, port, context=context, timeout=60)
    else:
        smtp = smtplib.SMTP(host, port, timeout=60)
        smtp.starttls(context=context)
    smtp.login(user, password)
    return smtp


def send_emails(folder, names):
    """Email people their file: everyone not yet sent theirs, or just names.
    A copy of each sent email goes in folder/sent."""
    files = read_files(folder)
    sent = folder / 'sent'
    if names:
        by_name = {giver.casefold(): giver for giver in files}
        unknown = [name for name in names if name.casefold() not in by_name]
        if unknown:
            raise DrawError(f'No file in {folder} for: ' + ', '.join(unknown))
        givers = list(dict.fromkeys(by_name[name.casefold()] for name in names))
    else:
        givers = [giver for giver in files if not (sent / f'{giver}.eml').exists()]
        if not givers:
            raise DrawError(f'Everyone in {folder} has been emailed. To email '
                            'someone again, put their name after the folder.')
    to = addresses(givers)
    user = ask('Your email address: ')
    if not user:
        raise DrawError('Nothing sent.')
    print(f'From {user} via {SMTP_HOST}, to:')
    for giver in givers:
        print(f'  {giver} <{to[giver]}>')
    if ask(f'Send {len(givers)} email(s)? [y/N] ').lower() not in ('y', 'yes'):
        raise DrawError('Nothing sent.')
    password = getpass.getpass(f'Password for {user}: ')

    sent.mkdir(exist_ok=True)
    done = 0
    try:
        with connect(SMTP_HOST, SMTP_PORT, user, password) as smtp:
            for giver in givers:
                email = build_email(giver, to[giver], files[giver])
                email['From'] = user
                email['Date'] = formatdate(localtime=True)
                email['Message-ID'] = make_msgid(domain=user.rpartition('@')[2] or None)
                smtp.send_message(email)
                (sent / f'{giver}.eml').write_bytes(email.as_bytes())
                done += 1
                print(f'Sent to {giver}')
    except smtplib.SMTPAuthenticationError as error:
        raise DrawError(f'Login failed: {error}\nGmail needs an app password, from '
                        'https://myaccount.google.com/apppasswords') from None
    except (smtplib.SMTPException, OSError) as error:
        raise DrawError(f'Stopped after sending {done} of {len(givers)}: {error}\n'
                        'Fix the problem and run the same command again.') from None


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Secret santa draw. The other settings are at the top of this file.')
    parser.add_argument('--output', metavar='FOLDER', default=OUTPUT_DIR,
                        help='folder to put draws in (default: %(default)s)')
    commands = parser.add_subparsers(dest='command', title='after a draw',
                                     metavar='{drafts,send}')
    folder_help = ("the draw's folder: inside the output folder, such as "
                   '2026/11.24-15.30, or a full path')
    drafts = commands.add_parser(
        'drafts', help='write an email per person, with their file attached, for you to send')
    drafts.add_argument('folder', help=folder_help)
    send = commands.add_parser(
        'send', help=f'email everyone their file through {SMTP_HOST}')
    send.add_argument('folder', help=folder_help)
    send.add_argument('names', nargs='*', help='only email these people (again)')
    args = parser.parse_args(argv)
    output = Path(args.output)
    try:
        if args.command == 'drafts':
            make_drafts(output / args.folder)
        elif args.command == 'send':
            send_emails(output / args.folder, args.names)
        else:
            draw_names(output)
    except DrawError as error:
        sys.exit(str(error))


if __name__ == '__main__':
    main()
