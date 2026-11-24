"""Run with: python -m unittest"""
import contextlib
import io
import os
import random
import smtplib
import tempfile
import unittest
from collections import Counter
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest import mock

import secret_santa as ss

PEOPLE = ['Alex', 'Chris', 'Debbie', 'Glen', 'Jess']
LAST_YEAR = set(zip(PEOPLE, PEOPLE[1:] + PEOPLE[:1]))


def write_participants(path, rows):
    path.write_text('name,email\n' + ''.join(f'{name},{address}\n' for name, address in rows),
                    encoding='utf-8')


def address(name):
    return f'{name.lower()}@example.com'


class DrawTests(unittest.TestCase):
    def assertValid(self, draw, people, banned=()):
        self.assertEqual(sorted(draw), sorted(people))
        self.assertEqual(sorted(draw.values()), sorted(people))
        for giver, receiver in draw.items():
            self.assertNotEqual(giver, receiver)
            self.assertNotEqual(draw[receiver], giver)  # nobody swaps
            self.assertNotIn((giver, receiver), banned)

    def test_counts(self):
        # With 5 people the only shape without swaps is one big loop.
        self.assertEqual(ss.make_draw(PEOPLE, set())[1], 24)
        self.assertEqual(ss.make_draw(PEOPLE, LAST_YEAR)[1], 8)
        # With 6, two loops of 3 work too: 120 big loops + 40 pairs of loops.
        self.assertEqual(ss.make_draw(PEOPLE + ['Sam'], set())[1], 160)

    def test_valid_and_evenly_spread(self):
        banned = LAST_YEAR | {('Alex', 'Debbie'), ('Debbie', 'Alex')}
        possible = ss.make_draw(PEOPLE, banned)[1]
        # 0 forces the random-retry path used for big groups
        for limit in (ss.MAX_CANDIDATES_TO_CHECK, 0):
            with self.subTest(limit=limit), \
                    mock.patch.object(ss, 'MAX_CANDIDATES_TO_CHECK', limit):
                rng = random.Random(1)
                runs = 1000 * possible
                seen = Counter()
                for _ in range(runs):
                    draw, _ = ss.make_draw(PEOPLE, banned, rng)
                    self.assertValid(draw, PEOPLE, banned)
                    seen[tuple(sorted(draw.items()))] += 1
                self.assertEqual(len(seen), possible)
                for times in seen.values():
                    self.assertAlmostEqual(times / runs, 1 / possible, delta=0.3 / possible)

    def test_six_people_random_path(self):
        people = PEOPLE + ['Sam']
        rng = random.Random(2)
        shapes = Counter()
        with mock.patch.object(ss, 'MAX_CANDIDATES_TO_CHECK', 0):
            for _ in range(800):
                draw, _ = ss.make_draw(people, set(), rng)
                self.assertValid(draw, people)
                person, length = 'Alex', 0
                while True:
                    person, length = draw[person], length + 1
                    if person == 'Alex':
                        break
                shapes[length] += 1
        self.assertEqual(set(shapes), {3, 6})  # loops of 3 happen, swaps never

    def test_impossible(self):
        banned = {(person, 'Alex') for person in PEOPLE}
        for limit in (ss.MAX_CANDIDATES_TO_CHECK, 0):
            with self.subTest(limit=limit), \
                    mock.patch.object(ss, 'MAX_CANDIDATES_TO_CHECK', limit), \
                    mock.patch.object(ss, 'MAX_TRIES', 1000):
                with self.assertRaises(ss.DrawError):
                    ss.make_draw(PEOPLE, banned)

    def test_big_group(self):
        people = [f'P{i}' for i in range(30)]
        draw, count = ss.make_draw(people, set())
        self.assertIsNone(count)
        self.assertValid(draw, people)

    def test_bad_names(self):
        for people in (['Alex', 'Alex', 'Chris'], ['Alex', 'Chris']):
            with self.assertRaises(ss.DrawError):
                ss.banned_pairs(people, [], {})
        with self.assertRaises(ss.DrawError):
            ss.banned_pairs(PEOPLE, [('Alex', 'Debby')], {})
        # a pair without the outer list, a missing comma, and a group of three
        for entry in ['Alex', 'AlexDebbie', ('Alex', 'Chris', 'Debbie')]:
            with self.assertRaises(ss.DrawError):
                ss.banned_pairs(PEOPLE, [entry], {})

    def test_banned_pairs(self):
        banned = ss.banned_pairs(PEOPLE, [('Alex', 'Debbie')], {'Glen': 'Jess'})
        self.assertEqual(banned, {('Alex', 'Debbie'), ('Debbie', 'Alex'), ('Glen', 'Jess')})

    def test_same_size_whoever_is_drawn(self):
        people = PEOPLE + ['Zoë']
        for giver in people:
            sizes = {len(ss.message(giver, receiver, people).encode('utf-8'))
                     for receiver in people}
            self.assertEqual(len(sizes), 1)


class ParticipantsFileTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'participants.csv'

    def read(self, text):
        self.path.write_text(text, encoding='utf-8')
        return ss.read_participants(self.path)

    def test_reads_names_and_addresses(self):
        # Excel's byte order mark, loose headers, blank rows and cells, quoting
        people = self.read('\ufeff Name , EMAIL \nAlex, alex@example.com\n\n"Smith, Zoë",\n,\n')
        self.assertEqual(people, {'Alex': 'alex@example.com', 'Smith, Zoë': ''})

    def test_problems(self):
        for text in ['', 'name\nAlex\n', 'name,email\nAlex,a@x.com\nalex,b@x.com\n',
                     'name,email\n,a@x.com\n']:
            with self.subTest(text=text), self.assertRaises(ss.DrawError):
                self.read(text)

    def test_missing_file(self):
        with self.assertRaisesRegex(ss.DrawError, 'participants.example.csv'):
            ss.read_participants(self.path)

    def test_not_utf8(self):
        # what Excel's plain "CSV" format saves on Windows
        self.path.write_bytes('name,email\nZoë,zoe@example.com\n'.encode('cp1252'))
        with self.assertRaisesRegex(ss.DrawError, 'UTF-8'):
            ss.read_participants(self.path)


class TempFolderTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        # Kept out of self.tmp, which some tests expect to hold only draws.
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        self.participants = Path(other.name) / 'participants.csv'
        write_participants(self.participants, [(name, address(name)) for name in PEOPLE])

    def run_main(self, *args, **settings):
        # Don't depend on whatever the real settings are this year.
        settings = {'PARTICIPANTS_FILE': str(self.participants), 'EXCLUDED_PAIRS': [],
                    'PREVIOUS_DRAW': None, 'OUTPUT_DIR': str(self.tmp),
                    'SMTP_HOST': 'smtp.example.com', 'SMTP_PORT': 587, **settings}
        with mock.patch.multiple(ss, **settings), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            ss.main(list(args))
        return out.getvalue()


class FileTests(TempFolderTest):

    def test_reads_last_years_files(self):
        # Exactly what last year's script wrote.
        draw = {'Alex': 'J. Smith', 'J. Smith': 'Chris', 'Chris': 'Alex'}
        for giver, receiver in draw.items():
            with open(os.path.join(self.tmp, f'{giver}.txt'), 'w') as f:
                f.write(f'Hello {giver}!\n\nYou have been assigned to give a gift to {receiver}.\n')
        self.assertEqual(ss.read_draw(self.tmp), draw)

    def test_missing_previous_draw(self):
        with self.assertRaises(ss.DrawError):
            ss.read_draw(self.tmp / 'nope')

    def test_previous_draw_missing_a_file(self):
        (self.tmp / 'Alex.txt').write_text(ss.message('Alex', 'Chris', PEOPLE))
        with self.assertRaises(ss.DrawError):
            ss.read_draw(self.tmp)

    def test_new_folder_every_run(self):
        folders = {ss.make_run_folder(self.tmp) for _ in range(3)}
        self.assertEqual(len(folders), 3)
        for folder in folders:  # e.g. 2026/11.24-15.30, then _2 and _3
            self.assertRegex(folder.relative_to(self.tmp).as_posix(),
                             r'^\d{4}/\d\d\.\d\d-\d\d\.\d\d(_\d)?$')

    def test_main_never_repeats_previous_draw(self):
        out = self.run_main()
        [first] = self.tmp.glob('*/*')
        name = first.relative_to(self.tmp).as_posix()
        self.assertIn(f"PREVIOUS_DRAW = '{name}'", out)
        previous = ss.read_draw(first)
        self.assertEqual(sorted(previous), sorted(PEOPLE))
        for _ in range(10):
            out = self.run_main(PREVIOUS_DRAW=name)
            self.assertIn('Avoiding repeats', out)
        for folder in self.tmp.glob('*/*'):
            if folder != first:
                draw = ss.read_draw(folder)
                self.assertFalse(set(draw.items()) & set(previous.items()))
        self.assertEqual(len(list(self.tmp.glob('*/*'))), 11)

    def test_previous_draw_with_backslashes(self):
        # What Python makes of '2025\12.01-19.30' and of
        # 'G:\My Drive\Secret-Santa\2025' typed with single backslashes
        for mangled in ['2025\n.01-19.30', 'G:\\My Drive\\Secret-Santa\x825']:
            with self.subTest(mangled=mangled), self.assertRaises(SystemExit) as caught:
                self.run_main(PREVIOUS_DRAW=mangled)
            self.assertIn('forward slashes', str(caught.exception))

    def test_previous_draw_as_a_number(self):
        (self.tmp / '2025').mkdir()
        for giver, receiver in zip(PEOPLE, PEOPLE[1:] + PEOPLE[:1]):
            (self.tmp / '2025' / f'{giver}.txt').write_text(ss.message(giver, receiver, PEOPLE))
        self.assertIn('Avoiding repeats', self.run_main(PREVIOUS_DRAW=2025))

    def test_hint_works_after_saving_elsewhere(self):
        other = self.tmp / 'other'
        other.mkdir()
        out = self.run_main('--output', str(other))
        hint = out.split("PREVIOUS_DRAW = '")[1].split("'")[0]
        self.assertTrue(Path(hint).is_absolute())
        self.assertIn('Avoiding repeats', self.run_main(PREVIOUS_DRAW=hint))

    def test_output_option(self):
        other = self.tmp / 'other'
        other.mkdir()
        self.run_main('--output', str(other))
        self.assertEqual(list(self.tmp.iterdir()), [other])
        [folder] = other.glob('*/*')
        self.assertEqual(sorted(ss.read_draw(folder)), sorted(PEOPLE))

    def test_missing_output_folder_asks(self):
        missing = str(self.tmp / 'no-drive' / 'Secret-Santa')
        new = self.tmp / 'new'
        # a folder that can't be made, then a new one (with quotes, as
        # Explorer's "Copy as path" gives)
        with mock.patch('builtins.input', side_effect=[missing, f'"{new}"']) as ask:
            out = self.run_main(OUTPUT_DIR=missing)
        self.assertEqual(ask.call_count, 2)
        self.assertIn(f"PREVIOUS_DRAW = '", out)
        self.assertEqual(len(list(new.glob('*/*/*.txt'))), len(PEOPLE))
        self.assertEqual(list(self.tmp.iterdir()), [new])

    def test_missing_output_folder_quit(self):
        for answers in ([''], EOFError):
            with self.subTest(answers=answers), \
                    mock.patch('builtins.input', side_effect=answers), \
                    self.assertRaises(SystemExit) as caught:
                self.run_main(OUTPUT_DIR=str(self.tmp / 'nope'))
            self.assertIn('No output folder chosen', str(caught.exception))
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_files_written_in_list_order(self):
        written = []
        write_text = Path.write_text

        def record(path, *args, **kwargs):
            written.append(path.stem)
            return write_text(path, *args, **kwargs)

        with mock.patch.object(Path, 'write_text', record):
            self.run_main()
        self.assertEqual(written, PEOPLE)

    def test_warns_when_few_draws(self):
        self.assertIn('very few', self.run_main(FEW_DRAWS=100))
        self.assertNotIn('very few', self.run_main())

    def test_main_reports_impossible(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_main(EXCLUDED_PAIRS=[('Alex', p) for p in PEOPLE[1:]])
        self.assertIn('No draw fits', str(caught.exception))
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_participants_file_problem_stops_the_draw(self):
        write_participants(self.participants, [('Alex', ''), ('alex', '')])
        with self.assertRaises(SystemExit) as caught:
            self.run_main()
        self.assertIn('different name', str(caught.exception))
        self.assertEqual(list(self.tmp.iterdir()), [])


class FakeSMTP:
    """Stands in for smtplib.SMTP and SMTP_SSL, keeping what would be sent."""
    sent, refuse = [], set()

    def __init__(self, host, port, context=None, timeout=None):
        pass

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        if password != 'app password':
            raise smtplib.SMTPAuthenticationError(535, b'Username and Password not accepted')

    def send_message(self, email):
        to = email['To'].addresses[0].addr_spec
        if to in self.refuse:
            raise smtplib.SMTPRecipientsRefused({to: (550, b'No such user')})
        self.sent.append(email)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


class EmailTests(TempFolderTest):
    def setUp(self):
        super().setUp()
        self.draw_output = self.run_main()
        [self.folder] = self.tmp.glob('*/*')
        self.name = self.folder.relative_to(self.tmp).as_posix()
        FakeSMTP.sent, FakeSMTP.refuse = [], set()

    def send(self, *names, answers=('me@example.com', 'y'), password='app password', **settings):
        with mock.patch.object(ss.smtplib, 'SMTP', FakeSMTP), \
                mock.patch.object(ss.smtplib, 'SMTP_SSL', FakeSMTP), \
                mock.patch('builtins.input', side_effect=answers) as ask, \
                mock.patch.object(ss.getpass, 'getpass', return_value=password):
            out = self.run_main('send', self.name, *names, **settings)
        return out, ask

    def sent_to(self):
        return [email['To'].addresses[0].display_name for email in FakeSMTP.sent]

    def check_email(self, raw, giver):
        """raw is an email to giver, with their file attached exactly as saved,
        and nobody else's name in it."""
        email = BytesParser(policy=policy.default).parsebytes(raw)
        self.assertEqual(email['To'].addresses[0].addr_spec, address(giver))
        self.assertEqual(email['Subject'], ss.SUBJECT)
        body, attachment = email.iter_parts()
        self.assertEqual(body.get_content().replace('\r\n', '\n'), ss.BODY.format(giver=giver))
        self.assertEqual(attachment.get_content_disposition(), 'attachment')
        self.assertEqual(attachment.get_filename(), ss.ATTACHMENT_NAME)
        self.assertEqual(attachment.get_payload(decode=True),
                         (self.folder / f'{giver}.txt').read_bytes())
        for other in set(PEOPLE) - {giver}:
            self.assertNotIn(other.encode(), raw)
        return email

    def test_draw_says_how_to_email(self):
        self.assertIn(f'python secret_santa.py send "{self.name}"', self.draw_output)
        self.assertIn(f'python secret_santa.py drafts "{self.name}"', self.draw_output)

    def test_drafts(self):
        self.run_main('drafts', self.name)
        drafts = sorted((self.folder / 'drafts').iterdir())
        self.assertEqual([path.stem for path in drafts], sorted(PEOPLE))
        for path in drafts:
            email = self.check_email(path.read_bytes(), path.stem)
            self.assertEqual(email['X-Unsent'], '1')
            self.assertIsNone(email['From'])
        # the draw itself is untouched, so it still works as PREVIOUS_DRAW
        self.assertEqual(sorted(ss.read_draw(self.folder)), sorted(PEOPLE))

    def test_drafts_from_a_full_path_and_last_years_files(self):
        old = self.tmp / 'old'
        old.mkdir()
        for giver, receiver in zip(PEOPLE, PEOPLE[1:] + PEOPLE[:1]):
            with open(old / f'{giver}.txt', 'w') as f:
                f.write(f'Hello {giver}!\n\nYou have been assigned to give a gift to {receiver}.\n')
        self.run_main('drafts', str(old))
        self.assertEqual(len(list((old / 'drafts').glob('*.eml'))), len(PEOPLE))

    def test_missing_or_shared_addresses(self):
        write_participants(self.participants, [
            ('Alex', address('Alex')), ('Chris', 'shared@example.com'),
            ('Debbie', 'Shared@example.com'), ('Glen', ''), ('Jess', 'jess at example.com')])
        for command in (['drafts', self.name], ['send', self.name]):
            with self.subTest(command=command), self.assertRaises(SystemExit) as caught, \
                    mock.patch('builtins.input') as ask:
                self.run_main(*command)
            problems = str(caught.exception)
            self.assertIn('Chris and Debbie have the same email address', problems)
            self.assertIn('Glen needs a valid email address', problems)
            self.assertIn('Jess needs a valid email address', problems)
            ask.assert_not_called()
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()),
                         sorted(f'{name}.txt' for name in PEOPLE))

    def test_send(self):
        out, ask = self.send()
        self.assertEqual(self.sent_to(), sorted(PEOPLE))
        self.assertIn(f'Alex <{address("Alex")}>', out)
        for email in FakeSMTP.sent:
            giver = email['To'].addresses[0].display_name
            self.assertEqual(email['From'], 'me@example.com')
            self.assertTrue(email['Date'] and email['Message-ID'].endswith('@example.com>'))
            saved = (self.folder / 'sent' / f'{giver}.eml').read_bytes()
            self.assertEqual(saved, email.as_bytes())
            self.check_email(saved, giver)
        self.assertEqual(sorted(ss.read_draw(self.folder)), sorted(PEOPLE))

    def test_send_over_ssl(self):
        self.send(SMTP_PORT=465)
        self.assertEqual(self.sent_to(), sorted(PEOPLE))

    def test_send_picks_up_where_it_stopped(self):
        FakeSMTP.refuse = {address('Debbie')}
        with self.assertRaises(SystemExit) as caught:
            self.send()
        self.assertIn('Stopped after sending 2 of 5', str(caught.exception))
        self.assertEqual(sorted(path.stem for path in (self.folder / 'sent').iterdir()),
                         ['Alex', 'Chris'])
        FakeSMTP.refuse = set()
        self.send()
        self.assertEqual(self.sent_to(), ['Alex', 'Chris', 'Debbie', 'Glen', 'Jess'])
        with self.assertRaises(SystemExit) as caught:
            self.send()
        self.assertIn('has been emailed', str(caught.exception))
        self.assertEqual(len(FakeSMTP.sent), 5)

    def test_send_to_named_people_again(self):
        self.send()
        self.send('glen', 'Glen')
        self.assertEqual(self.sent_to(), sorted(PEOPLE) + ['Glen'])
        with self.assertRaises(SystemExit) as caught:
            self.send('Nobody')
        self.assertIn('No file', str(caught.exception))

    def test_send_cancelled_or_login_failed(self):
        for kwargs, expected in [({'answers': ('me@example.com', 'n')}, 'Nothing sent'),
                                 ({'answers': ('', 'y')}, 'Nothing sent'),
                                 ({'password': 'wrong'}, 'app password')]:
            with self.subTest(expected=expected), self.assertRaises(SystemExit) as caught:
                self.send(**kwargs)
            self.assertIn(expected, str(caught.exception))
        self.assertEqual(FakeSMTP.sent, [])
        self.assertFalse(any((self.folder / 'sent').glob('*')))


if __name__ == '__main__':
    unittest.main()
