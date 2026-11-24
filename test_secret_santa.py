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


def loop_length(draw):
    seen, person = set(), next(iter(draw))
    while person not in seen:
        seen.add(person)
        person = draw[person]
    return len(seen)


class DrawTests(unittest.TestCase):
    def assertValid(self, draw, banned, single_loop):
        self.assertEqual(sorted(draw), sorted(PEOPLE))
        self.assertEqual(sorted(draw.values()), sorted(PEOPLE))
        for giver, receiver in draw.items():
            self.assertNotEqual(giver, receiver)
            self.assertNotIn((giver, receiver), banned)
        if single_loop:
            self.assertEqual(loop_length(draw), len(PEOPLE))

    def test_counts(self):
        for banned, loops, any_shape in [(set(), 24, 44), (LAST_YEAR, 8, 13)]:
            self.assertEqual(ss.make_draw(PEOPLE, banned, True)[1], loops)
            self.assertEqual(ss.make_draw(PEOPLE, banned, False)[1], any_shape)

    def test_valid_and_evenly_spread(self):
        banned = LAST_YEAR | {('Alex', 'Debbie'), ('Debbie', 'Alex')}
        for single_loop in (True, False):
            possible = ss.make_draw(PEOPLE, banned, single_loop)[1]
            # 0 forces the random-retry path used for big groups
            for limit in (ss.MAX_CANDIDATES_TO_CHECK, 0):
                with self.subTest(single_loop=single_loop, limit=limit), \
                        mock.patch.object(ss, 'MAX_CANDIDATES_TO_CHECK', limit):
                    rng = random.Random(1)
                    runs = 1000 * possible
                    seen = Counter()
                    for _ in range(runs):
                        draw, _ = ss.make_draw(PEOPLE, banned, single_loop, rng)
                        self.assertValid(draw, banned, single_loop)
                        seen[tuple(sorted(draw.items()))] += 1
                    self.assertEqual(len(seen), possible)
                    for times in seen.values():
                        self.assertAlmostEqual(times / runs, 1 / possible, delta=0.3 / possible)

    def test_impossible(self):
        banned = {(person, 'Alex') for person in PEOPLE}
        for single_loop in (True, False):
            for limit in (ss.MAX_CANDIDATES_TO_CHECK, 0):
                with self.subTest(single_loop=single_loop, limit=limit), \
                        mock.patch.object(ss, 'MAX_CANDIDATES_TO_CHECK', limit), \
                        mock.patch.object(ss, 'MAX_TRIES', 1000):
                    with self.assertRaises(ss.DrawError):
                        ss.make_draw(PEOPLE, banned, single_loop)

    def test_big_group(self):
        people = [f'P{i}' for i in range(30)]
        for single_loop in (True, False):
            draw, count = ss.make_draw(people, set(), single_loop)
            self.assertIsNone(count)
            self.assertEqual(sorted(draw.values()), sorted(people))
            self.assertTrue(all(giver != receiver for giver, receiver in draw.items()))

    def test_bad_names(self):
        with self.assertRaises(ss.DrawError):
            ss.banned_pairs(['Alex', 'Alex', 'Chris'], [], {})
        with self.assertRaises(ss.DrawError):
            ss.banned_pairs(['Alex'], [], {})
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

    def run_main(self, **settings):
        # Don't depend on whatever the real settings are this year.
        settings = {'PARTICIPANTS': PEOPLE, 'EXCLUDED_PAIRS': [], 'PREVIOUS_DRAW': None,
                    'SINGLE_LOOP': False, 'OUTPUT_DIR': self.tmp, **settings}
        with mock.patch.multiple(ss, **settings), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            ss.main()
        return out.getvalue()

    def test_main_never_repeats_previous_draw(self):
        self.run_main()
        [first] = self.tmp.iterdir()
        previous = ss.read_draw(first)
        self.assertEqual(sorted(previous), sorted(PEOPLE))
        for _ in range(10):
            out = self.run_main(PREVIOUS_DRAW=first)
            self.assertIn('Avoiding repeats', out)
        for folder in self.tmp.iterdir():
            if folder != first:
                draw = ss.read_draw(folder)
                self.assertFalse(set(draw.items()) & set(previous.items()))
        self.assertEqual(len(list(self.tmp.iterdir())), 11)

    def test_files_written_in_list_order(self):
        written = []
        write_text = Path.write_text

        def record(path, *args, **kwargs):
            written.append(path.stem)
            return write_text(path, *args, **kwargs)

        with mock.patch.object(Path, 'write_text', record):
            self.run_main(SINGLE_LOOP=True)
        self.assertEqual(written, PEOPLE)

    def test_warns_when_few_draws(self):
        out = self.run_main(SINGLE_LOOP=True, FEW_DRAWS=100)
        self.assertIn('very few', out)
        self.assertIn('SINGLE_LOOP = False', out)
        self.assertNotIn('very few', self.run_main())

    def test_main_reports_impossible(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_main(EXCLUDED_PAIRS=[('Alex', p) for p in PEOPLE[1:]])
        self.assertIn('No draw fits', str(caught.exception))
        self.assertEqual(list(self.tmp.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
