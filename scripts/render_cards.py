#!/usr/bin/env python3
"""Render card images with ui/render (Valve's 526x890 card face) into images/<game>/<language>/,
and the small square preview (like Valve's 267x267 "mini") into images/<game>/preview/.

    python3 scripts/render_cards.py foundry                 # every Foundry card that has a face
    python3 scripts/render_cards.py reborn --changed        # Reborn cards new or changed vs Classic
    python3 scripts/render_cards.py classic 10001 10002     # given cards
    python3 scripts/render_cards.py foundry --lang russian
    python3 scripts/render_cards.py classic --scale 2           # 1052x1780 into images/classic/english@2x/

Alternate artworks are rendered too, as <id>_<artwork id>.png.

Needs ui/assets/ (scripts/extract_assets.py). Cards with a face are heroes, creeps, spells,
improvements, items, strongholds, path cards and abilities; a card with only a mini icon (most
abilities) is drawn with its icon framed in the art area.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from cdp import Browser  # noqa: E402
from compare_render import serve  # noqa: E402

FACE_TYPES = {2, 3, 4, 5, 6, 7, 8, 9}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('game', choices=['classic', 'foundry', 'reborn'])
    ap.add_argument('ids', nargs='*')
    ap.add_argument('--lang', default='english')
    ap.add_argument('--changed', action='store_true', help='reborn: only cards in reborn/changes.json')
    ap.add_argument('--force', action='store_true', help='render even if the image exists')
    ap.add_argument('--no-alternates', action='store_true',
                    help='skip alternate artworks (rendered by default as <id>_<artwork id>.png)')
    ap.add_argument('--scale', type=float, default=1.0,
                    help='resolution scale: 2 = 1052x1780, 0.5 = 263x445 (default 1 = 526x890)')
    ap.add_argument('--no-mini', action='store_true', help='skip the small square previews')
    args = ap.parse_args()
    cards = json.loads((ROOT / args.game / 'cards.json').read_text())
    if args.ids:
        ids = args.ids
    elif args.changed:
        changes = json.loads((ROOT / 'reborn/changes.json').read_text())
        ids = [str(i) for i in changes['added']] + list(changes['changed'])
        ids = [i for i in ids if cards.get(i, {}).get('type') in FACE_TYPES]
    else:
        ids = [i for i, c in cards.items() if c['type'] in FACE_TYPES]
    # Skip cards without art (e.g. a community card whose data and art live elsewhere).
    details = {}
    for f in ('heroes', 'creeps', 'spells', 'improvements', 'items', 'default', 'abilities'):
        p = ROOT / args.game / f'{f}.json'
        if p.exists():
            details.update(json.loads(p.read_text()))

    def art_file(kind, art):
        return any((ROOT / 'ui/assets' / g / 'art' / kind / f'{art}.png').exists() for g in (args.game, 'classic'))

    def has_art(cid):
        art = details.get(cid, {}).get('artwork', {}).get('artwork_id', cid)
        return any(art_file(kind, a) for kind in ('full_art', 'mini_icons') for a in (art, cid))
    missing = [i for i in ids if not has_art(i)]
    if missing:
        print(f'skipped (no art): {", ".join(missing)}')
    ids = [i for i in ids if i not in missing]
    suffix = '' if args.scale == 1 else f'@{args.scale:g}x'
    out = ROOT / 'images' / args.game / f'{args.lang}{suffix}'
    mini_out = ROOT / 'images' / args.game / f'preview{suffix}'
    server = serve()
    port = server.server_address[1]
    done = 0
    jobs = [(cid, None) for cid in ids]
    if not args.no_alternates:
        jobs += [(cid, art) for cid in ids for art in details.get(cid, {}).get('artwork', {}).get('alternate_artwork_ids', [])
                 if art_file('full_art', art) or art_file('mini_icons', art)]
    kinds = [('face', out, 526, 890)] + ([] if args.no_mini else [('mini', mini_out, 267, 267)])
    with Browser() as b:
        for kind, folder, w, h in kinds:
            folder.mkdir(parents=True, exist_ok=True)
            for cid, art in jobs:
                target = folder / (f'{cid}_{art}.png' if art else f'{cid}.png')
                if target.exists() and not args.force:
                    continue
                url = f'http://127.0.0.1:{port}/ui/render/render.html?game={args.game}&id={cid}&lang={args.lang}'
                url += (f'&art={art}' if art else '') + ('&kind=mini' if kind == 'mini' else '')
                png = b.screenshot(url, w, h, scale=args.scale)
                Image.open(io.BytesIO(png)).save(target, optimize=True)
                done += 1
    print(f'{done} rendered into {out.relative_to(ROOT)}' + ('' if args.no_mini else f' and {mini_out.relative_to(ROOT)}')
          + f' ({len(jobs)} cards and artworks)')


if __name__ == '__main__':
    main()
