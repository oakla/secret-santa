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

    def test_banned_pairs(self):
        banned = ss.banned_pairs(PEOPLE, [('Alex', 'Debbie')], {'Glen': 'Jess'})
        self.assertEqual(banned, {('Alex', 'Debbie'), ('Debbie', 'Alex'), ('Glen', 'Jess')})


class FileTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_reads_last_years_files(self):
        # Exactly what last year's script wrote.
        for giver, receiver in [('Alex', 'Chris'), ('Chris', 'J. Smith')]:
            with open(os.path.join(self.tmp, f'{giver}.txt'), 'w') as f:
                f.write(f'Hello {giver}!\n\nYou have been assigned to give a gift to {receiver}.\n')
        self.assertEqual(ss.read_draw(self.tmp), {'Alex': 'Chris', 'Chris': 'J. Smith'})

    def test_missing_previous_draw(self):
        with self.assertRaises(ss.DrawError):
            ss.read_draw(self.tmp / 'nope')

    def test_new_folder_every_run(self):
        folders = {ss.make_run_folder(self.tmp) for _ in range(3)}
        self.assertEqual(len(folders), 3)

    def run_main(self, **settings):
        with mock.patch.multiple(ss, OUTPUT_DIR=self.tmp, **settings), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            ss.main()
        return out.getvalue()

    def test_main_never_repeats_previous_draw(self):
        self.run_main()
        [first] = self.tmp.iterdir()
        previous = ss.read_draw(first)
        self.assertEqual(sorted(previous), sorted(ss.PARTICIPANTS))
        for _ in range(10):
            self.run_main(PREVIOUS_DRAW=first)
        for folder in self.tmp.iterdir():
            if folder != first:
                draw = ss.read_draw(folder)
                self.assertFalse(set(draw.items()) & set(previous.items()))
        self.assertEqual(len(list(self.tmp.iterdir())), 11)

    def test_main_reports_impossible(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_main(EXCLUDED_PAIRS=[('Alex', p) for p in PEOPLE[1:]])
        self.assertIn('No draw fits', str(caught.exception))
        self.assertEqual(list(self.tmp.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
