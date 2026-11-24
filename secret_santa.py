import random
import os
from datetime import datetime

# each run gets its own folder, e.g. output/2026-11-24_153012/
OUTDIR = os.path.join('output', datetime.now().strftime('%Y-%m-%d_%H%M%S'))
os.makedirs(OUTDIR)

participants = [
    'Alex',
    'Chris',
    'Debbie',
    'Glen',
    'Jess'
]

pairs = {}

# choose random first partipant
first = random.choice(participants)
participants.remove(first)

current = first

while participants:
    # choose random second participant
    second = random.choice(participants)
    participants.remove(second)

    # assign pair
    pairs[current] = second
    current = second

# complete the circle
pairs[current] = first

for giver, receiver in pairs.items():
    with open(os.path.join(OUTDIR, f'{giver}.txt'), 'w') as f:
        f.write(f'Hello {giver}!\n\nYou have been assigned to give a gift to {receiver}.\n')
