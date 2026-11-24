r"""Secret santa draw.

Edit the settings below, then run:

    python secret_santa.py

Each run writes one file per person to a new folder inside OUTPUT_DIR, such
as 2026-11-24_153012\Alex.txt, for you to send on. To use another folder
for one run:

    python secret_santa.py --output "D:\Somewhere else"

Nobody draws themselves, no two people draw each other, and the script
never prints who has whom.
"""
import argparse
import itertools
import math
import random
import re
import sys
from datetime import datetime
from pathlib import Path

PARTICIPANTS = [
    'Alex',
    'Chris',
    'Debbie',
    'Glen',
    'Jess',
]

# Pairs who must not draw each other, either way round (e.g. partners).
EXCLUDED_PAIRS = [
    # ('Alex', 'Debbie'),
]

# Where each run's folder goes. --output overrides it for one run.
OUTPUT_DIR = r'G:\My Drive\Secret-Santa'

# The last draw you sent, so nobody gets the same person again: a folder in
# the output folder, or a full path. Each run prints the value to use next
# time. For last year's draw, put its files in a folder called 2025 in the
# output folder. None to skip.
PREVIOUS_DRAW = None  # e.g. '2025'

# read_draw() finds the receiver in old files by "give a gift to <name>." at
# the end of a line, so keep that if you change the message (put anything
# else on a line of its own).
MESSAGE = 'Hello {giver}!\n\nYou have been assigned to give a gift to {receiver}.\n'

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
        raise DrawError('EXCLUDED_PAIRS has names that are not in PARTICIPANTS: '
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


def make_run_folder(parent):
    stamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    folder, n = parent / stamp, 2
    while folder.exists():
        folder, n = parent / f'{stamp}_{n}', n + 1
    folder.mkdir(parents=True)
    return folder


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Secret santa draw. The other settings are at the top of this file.')
    parser.add_argument('--output', metavar='FOLDER', default=OUTPUT_DIR,
                        help='folder to put this run in (default: %(default)s)')
    output = Path(parser.parse_args(argv).output)
    previous_folder = output / PREVIOUS_DRAW if PREVIOUS_DRAW else None
    try:
        if not output.is_dir():
            raise DrawError(f"Can't find the output folder {output}. "
                            'Create it, or choose another with --output FOLDER.')
        previous = read_draw(previous_folder) if previous_folder else {}
        banned = banned_pairs(PARTICIPANTS, EXCLUDED_PAIRS, previous)
        draw, count = make_draw(PARTICIPANTS, banned)
    except DrawError as error:
        sys.exit(str(error))

    if previous:
        print(f'Avoiding repeats of the draw in {previous_folder}')
        gone = set(previous) - set(PARTICIPANTS)
        new = set(PARTICIPANTS) - set(previous)
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
    for giver in PARTICIPANTS:
        text = message(giver, draw[giver], PARTICIPANTS)
        (folder / f'{giver}.txt').write_text(text, encoding='utf-8')
    print(f'Wrote {len(draw)} files to {folder}')
    print(f"Next time, set PREVIOUS_DRAW = '{folder.name}'")


if __name__ == '__main__':
    main()
