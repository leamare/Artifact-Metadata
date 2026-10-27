#!/usr/bin/env python3
"""Extract the game assets the card renderer uses into ui/assets/ (git-ignored: they are
Valve's files, so they stay out of the repository).

    python3 scripts/extract_assets.py                 # Classic + Foundry, all art
    python3 scripts/extract_assets.py --no-art        # UI textures and fonts only

Writes
  ui/assets/fonts/*.otf                        Radiance (the cards' typeface)
  ui/assets/<game>/ui/<dir>/<name>.png         card frame pieces, type badges, stat icons,
                                               set/rarity emblems, faction banners, pack art
  ui/assets/<game>/art/<kind>/<artwork id>.png full_art (1024x1024), mini_icons, hero_icons
  ui/assets/classic/ui/models/<name>.png       the card model's materials (models/card, models/cards)
  ui/assets/classic/ui/frame/*.png             the frame and text box as lit in Valve's renders,
                                               baked from those materials (scripts/frame.py)
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'scripts'))
from common import Paths  # noqa: E402
from sources import Vpk  # noqa: E402
import frame  # noqa: E402
import vtex  # noqa: E402

UI_DIRS = ('panorama/images/card/', 'panorama/images/card_elements/', 'panorama/images/set_icons/',
           'panorama/images/factions/', 'panorama/images/packs/', 'panorama/images/textures/')
MODELS = ('materials/models/card/', 'materials/models/cards/')
ART = re.compile(r'panorama/images/card_art/set\d\d/(full_art|mini_icons|hero_icons)/(\d+)_(?:psd|png)\.vtex_c$')

_vpk = None


def _init(path):
    global _vpk
    _vpk = Vpk(path)


def _decode(job):
    key, out = job
    try:
        out = Path(out)
        if out.exists():
            return None
        out.parent.mkdir(parents=True, exist_ok=True)
        vtex.decode(_vpk.read(key)).save(out, optimize=False)
        return None
    except Exception as e:  # keep going; report at the end
        return f'{key}: {e}'


def extract(game, game_dir, dest, art):
    vpk_path = game_dir / 'game/dcg/pak01_dir.vpk'
    vpk = Vpk(vpk_path)
    jobs = {}
    for key in vpk.entries:
        if not key.endswith('.vtex_c'):
            continue
        if key.startswith(UI_DIRS):
            name = re.sub(r'_(psd|png)(_[0-9a-f]{6,8})?\.vtex_c$', '', key[len('panorama/images/'):])
            out = dest / game / 'ui' / f'{name}.png'
            # a few images exist as both _png (small) and _psd (the full art): keep the _psd
            if out not in jobs or '_psd' in key:
                jobs[out] = key
        elif key.startswith(MODELS):
            name = re.sub(r'_(psd|png|tga|vmat)(_[a-z0-9_]+)?\.vtex_c$', '', key.rsplit('/', 1)[1])
            jobs[dest / game / 'ui/models' / f'{name}.png'] = key
        elif art and (m := ART.match(key)):
            jobs[dest / game / 'art' / m[1] / f'{m[2]}.png'] = key
    with ProcessPoolExecutor(os.cpu_count(), initializer=_init, initargs=(str(vpk_path),)) as pool:
        errors = [e for e in pool.map(_decode, [(k, str(o)) for o, k in jobs.items()], chunksize=8) if e]
    print(f'{game}: {len(jobs)} textures', f'({len(errors)} failed)' if errors else '')
    for e in errors[:10]:
        print('  ', e)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    paths = Paths()   # .env (see .env.example)
    ap.add_argument('--classic', type=Path, default=paths.classic)
    ap.add_argument('--foundry', type=Path, default=paths.foundry)
    ap.add_argument('--reborn-client', type=Path, default=paths.reborn_client)
    ap.add_argument('--dest', type=Path, default=ROOT / 'ui/assets')
    ap.add_argument('--no-art', action='store_true')
    args = ap.parse_args()
    fonts = args.dest / 'fonts'
    fonts.mkdir(parents=True, exist_ok=True)
    for game_dir in (d for d in (args.classic, args.foundry) if d):
        for f in (game_dir / 'game/dcg/panorama/fonts').glob('radiance*.otf'):
            shutil.copy2(f, fonts / f.name)
    for game, game_dir in (('classic', args.classic), ('foundry', args.foundry)):
        if game_dir and (game_dir / 'game/dcg/pak01_dir.vpk').exists():
            extract(game, game_dir, args.dest, not args.no_art)
    models = args.dest / 'classic/ui/models'
    if (models / 'card_title_bg_red_color.png').exists():
        frame.bake(models, args.dest / 'classic/ui/frame')
    # Reborn's community cards: their art is in artifact-reborn-client (card_art/<id>/<kind>.png).
    copied = 0
    bases = (args.reborn_client / 'content/card_art', args.reborn_client / 'docs/content/examples/card_art') if args.reborn_client else ()
    for base in bases:
        for f in base.glob('*/*.png'):
            if f.parent.name.isdigit():
                out = args.dest / 'reborn' / 'art' / f.stem / f'{f.parent.name}.png'
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, out)
                copied += 1
    print(f'reborn: {copied} community art files')


if __name__ == '__main__':
    main()
