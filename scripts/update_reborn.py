#!/usr/bin/env python3
"""Update reborn/ from the community patch repositories.

    python3 scripts/update_reborn.py            # regenerate reborn/ from the local checkouts
    python3 scripts/update_reborn.py --pull     # git pull artifact-reborn-client and -gc first

The repositories are the ones .env names (REBORN_CLIENT, REBORN_GC; see .env.example).

Prints which cards the patch adds or changes compared with Classic (reborn/changes.json
keeps the list, which scripts/render_cards.py uses to render only those cards).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
from common import TYPE_FILES, Paths  # noqa: E402

COMPARED = ('type', 'is_passive', 'set', 'rarity', 'color', 'mana_cost', 'gold_cost', 'attack', 'armor',
            'health', 'bounty', 'charges', 'crosslane', 'quick', 'item_subtype', 'equip', 'signature',
            'abilities', 'artwork')


def load_game(folder):
    out = {}
    for f in (ROOT / folder).glob('*.json'):
        data = json.loads(f.read_text())
        if f.stem in TYPE_FILES.values():
            out.update(data)
    texts = json.loads((ROOT / folder / 'cards_text.json').read_text())
    return out, texts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pull', action='store_true', help='git pull the reborn repositories first')
    args = ap.parse_args()
    if args.pull:   # the checkouts named in .env (REBORN_CLIENT, REBORN_GC)
        P = Paths()
        P.need('reborn_client', 'reborn_gc')
        for repo in (P.reborn_client, P.reborn_gc):
            subprocess.run(['git', '-C', str(repo), 'pull', '--ff-only'], check=True)
    subprocess.run([sys.executable, str(ROOT / 'tools/generate.py'), '--only', 'reborn'], check=True)

    classic, classic_text = load_game('classic')
    reborn, reborn_text = load_game('reborn')
    added = sorted((int(k) for k in reborn if k not in classic))
    changed = {}
    for k, card in reborn.items():
        if k not in classic:
            continue
        diff = [f for f in COMPARED if card.get(f) != classic[k].get(f)]
        if reborn_text.get(k, {}).get('text') != classic_text.get(k, {}).get('text'):
            diff.append('text')
        if diff:
            changed[int(k)] = diff
    (ROOT / 'reborn/changes.json').write_text(json.dumps(
        {'added': added, 'changed': {str(k): v for k, v in sorted(changed.items())}}, indent=2) + '\n')
    names = {**{k: v['name'] for k, v in classic.items()}, **{k: v.get('name') for k, v in reborn.items()}}
    print(f'{len(added)} new cards:', ', '.join(f'{i} {names.get(str(i))}' for i in added))
    print(f'{len(changed)} changed cards:')
    for i, fields in sorted(changed.items()):
        print(f'  {i} {names.get(str(i))}: {", ".join(fields)}')


if __name__ == '__main__':
    main()
