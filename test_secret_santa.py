"""Run with: python -m unittest"""
import contextlib
import io
import os
import random
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

import secret_santa as ss

PEOPLE = ['Alex', 'Chris', 'Debbie', 'Glen', 'Jess']
LAST_YEAR = set(zip(PEOPLE, PEOPLE[1:] + PEOPLE[:1]))


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


class FileTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

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

    def run_main(self, *args, **settings):
        # Don't depend on whatever the real settings are this year.
        settings = {'PARTICIPANTS': PEOPLE, 'EXCLUDED_PAIRS': [], 'PREVIOUS_DRAW': None,
                    'OUTPUT_DIR': str(self.tmp), **settings}
        with mock.patch.multiple(ss, **settings), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            ss.main(list(args))
        return out.getvalue()

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


if __name__ == '__main__':
    unittest.main()
