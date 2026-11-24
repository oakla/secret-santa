"""Secret santa draw.

Edit the settings below, then run:

    python secret_santa.py

Each run writes one file per person to a new folder, such as
output/2026-11-24_153012/Alex.txt, for you to send on. It never prints
who has whom.
"""
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

# Folder of the last draw you sent, so nobody gets the same person again.
# Each run prints the value to use next time. Last year's script wrote its
# files straight into output/: move them into output/2025 and use that.
# None to skip.
PREVIOUS_DRAW = None  # e.g. 'output/2025'

# True: everyone is in one big loop, so no two people give to each other.
# False: smaller loops are allowed too. Two people may then give to each
# other, but there are more possible draws, which matters once you add
# exclusions: with too few, people can work out who has whom.
SINGLE_LOOP = False

OUTPUT_DIR = 'output'

# read_draw() finds the receiver in old files by "give a gift to <name>." at
# the end of a line, so keep that if you change the message (put anything
# else on a line of its own).
MESSAGE = 'Hello {giver}!\n\nYou have been assigned to give a gift to {receiver}.\n'

# Up to this many candidate draws, all are checked: the pick is exact and the
# script can say how many draws were possible. Above it (about 10 people), it
# makes random draws until one fits, up to MAX_TRIES times.
MAX_CANDIDATES_TO_CHECK = 500_000
MAX_TRIES = 100_000

# Warn when this few draws (or fewer) fit the exclusions.
FEW_DRAWS = 5


class DrawError(Exception):
    pass


def allowed(draw, banned):
    return all(giver != receiver and (giver, receiver) not in banned
               for giver, receiver in draw.items())


def candidate_draws(people, single_loop):
    """Yield every possible draw, as {giver: receiver}."""
    if single_loop:
        first, *rest = people
        for order in itertools.permutations(rest):
            loop = (first, *order)
            yield dict(zip(loop, loop[1:] + loop[:1]))
    else:
        for receivers in itertools.permutations(people):
            yield dict(zip(people, receivers))


def random_candidate(people, single_loop, rng):
    order = list(people)
    rng.shuffle(order)
    if single_loop:
        return dict(zip(order, order[1:] + order[:1]))
    return dict(zip(people, order))


def make_draw(people, banned, single_loop, rng=random):
    """Pick at random, all equally likely, one of the draws that avoid the
    banned (giver, receiver) pairs.

    Returns (draw, count), where count is how many draws were possible, or
    None if there were too many to check. Raises DrawError if none fit.
    """
    candidates = math.factorial(len(people) - 1 if single_loop else len(people))
    if candidates <= MAX_CANDIDATES_TO_CHECK:
        chosen, count = None, 0
        for draw in candidate_draws(people, single_loop):
            if allowed(draw, banned):
                count += 1
                if rng.randrange(count) == 0:  # keeps each with chance 1/count
                    chosen = draw
        if chosen is None:
            raise DrawError('No draw fits these exclusions. Remove some and try again.')
        return chosen, count
    for _ in range(MAX_TRIES):
        draw = random_candidate(people, single_loop, rng)
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
    if len(people) < 2:
        raise DrawError('Need at least two participants.')
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


def main():
    try:
        previous = read_draw(PREVIOUS_DRAW) if PREVIOUS_DRAW else {}
        banned = banned_pairs(PARTICIPANTS, EXCLUDED_PAIRS, previous)
        draw, count = make_draw(PARTICIPANTS, banned, SINGLE_LOOP)
    except DrawError as error:
        sys.exit(str(error))

    if previous:
        print(f'Avoiding repeats of the draw in {PREVIOUS_DRAW}')
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
            tip = ('Setting SINGLE_LOOP = False or removing exclusions would help.'
                   if SINGLE_LOOP else 'Fewer exclusions would help.')
            print(f'That is very few: people may be able to work out who has whom. {tip}')

    folder = make_run_folder(Path(OUTPUT_DIR))
    # Write in list order, not draw order: file times would otherwise give
    # away the chain of who has whom.
    for giver in PARTICIPANTS:
        text = message(giver, draw[giver], PARTICIPANTS)
        (folder / f'{giver}.txt').write_text(text, encoding='utf-8')
    print(f'Wrote {len(draw)} files to {folder}')
    print(f"Next time, set PREVIOUS_DRAW = '{folder.as_posix()}'")


if __name__ == '__main__':
    main()
