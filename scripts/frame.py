#!/usr/bin/env python3
"""The card frame (header, spell strip, stat bar) as Valve's renders show it.

Valve rendered the card faces from the 3D card model: the frame is the material
models/card/card_title_bg_<colour> (colour map, scratch map `card_title_bg_refl`, and for
items a metal environment map) under the render's lighting. This module bakes that look
into flat images from the game's textures, with per-colour and per-region coefficients
fitted once on Valve's renders:

    python3 scripts/frame.py fit     # needs images/classic/large/english/ and ui/assets/
                                     # (writes scripts/data/frame.json)

scripts/extract_assets.py calls bake() to write ui/assets/classic/ui/frame/<tone>_<region>.png,
which ui/render/card.css lays over the frame. A pixel is
    sum(k * feature) per channel, features = 1, colour map, scratches, [environment],
    x, y, x*x, y*y, x*y (x, y in 0..1 across the region: the lighting gradient)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'scripts/data/frame.json'
TEXTURE = {'red': 'red', 'green': 'green', 'blue': 'blue', 'black': 'black', 'none': 'coloreless', 'item': 'item'}

# Each region as card.css places it: (top in the 526x890 render, height, texture rows per
# render row, texture row at the region's top), the texture scaled to 519x260 (x0.507),
# all fitted on Valve's renders. The strip and the bar start 25px above their edge for the
# half circle under the emblem; the strip maps the texture from its first notched line, the
# bar from the second.
REGIONS = {
    'header': (2, 86, 0.94, 0.5),
    'strip': (831, 55, 0.95, 79.3),
    'bar': (744, 142, 1 / 1.18, 138.0),
}
WIDTH = 519
# texture row of the strip's / bar's lit edge (its notched line), used for the half circle
BUMP_ROW = {'strip': 105.5, 'bar': 161.3}


def textures(models: Path, tone: str):
    name = TEXTURE[tone]
    load = lambda f: np.asarray(Image.open(models / f).convert('RGB').resize((WIDTH, 260), Image.BILINEAR),
                                dtype=np.float32)
    tex = {'color': load(f'card_title_bg_{name}_color.png')}
    if tone == 'item':
        tex['refl'] = load('card_title_bg_item_refl.png')[..., 0]
        tex['env'] = load('card_title_bg_item_env.png')
    else:
        tex['refl'] = load('card_title_bg_refl.png')[..., 0]
    return tex


def features(tex, region, rows, ch):
    """Feature matrix (len(rows) * WIDTH, n) for render rows `rows` (relative to the region)."""
    top, height, step, start = REGIONS[region]
    tr = rows * step + start
    if region in BUMP_ROW:   # the half circle above the edge: the lit edge itself, not the texture above it
        tr = np.where(rows < 25, BUMP_ROW[region], tr)
    r0 = np.clip(np.floor(tr).astype(int), 0, 259)
    r1 = np.clip(r0 + 1, 0, 259)
    f = np.clip(tr - np.floor(tr), 0, 1)[:, None]
    cols_idx = np.arange(WIDTH)
    bump = (rows < 25)[:, None] if region in BUMP_ROW else np.zeros((len(rows), 1), bool)
    # in the half circle, take the edge from beside the texture's own notch (drawn at x 234-284)
    cix = np.where(bump & (cols_idx >= 200) & (cols_idx <= 320), 190, np.broadcast_to(cols_idx, (len(rows), WIDTH)))
    sample = lambda a: (a[r0[:, None], cix] * (1 - f) + a[r1[:, None], cix] * f).ravel()
    x = (cix / (WIDTH - 1)).ravel() if region in BUMP_ROW else np.tile(np.arange(WIDTH) / (WIDTH - 1), len(rows))
    y = np.repeat((np.where(rows < 25, 27.5, rows) if region in BUMP_ROW else rows) / (height - 1), WIDTH)
    cols = [np.ones_like(x), sample(tex['color'][..., ch]), sample(tex['refl'])]
    if 'env' in tex:
        cols.append(sample(tex['env'][..., ch]))
    cols += [x, y, x * x, y * y, x * y]
    return np.stack(cols, 1)


# The spell text box: ui/card/card_background (744px square from (-2, 0) of the box, which
# is 519x376 at (4, 479) in the render) under the same kind of lighting.
TEXTBOX = (479, 376)


def textbox_features(card_background: Path, ch):
    tex = Image.open(card_background).convert('RGB').resize((744, 744), Image.BILINEAR)
    tex = np.asarray(tex, dtype=np.float32)[:TEXTBOX[1], 2:2 + WIDTH, ch].ravel()
    h = TEXTBOX[1]
    x = np.tile(np.arange(WIDTH) / (WIDTH - 1), h)
    y = np.repeat(np.arange(h) / (h - 1), WIDTH)
    return np.stack([np.ones_like(x), tex, x, y, x * x, y * y, x * y], 1)


def bake(models: Path, out: Path, coeffs=None):
    coeffs = coeffs or json.loads(DATA.read_text())
    out.mkdir(parents=True, exist_ok=True)
    k = coeffs.pop('textbox', None)
    if k:
        bg = models.parent / 'card/card_background.png'
        img = np.stack([textbox_features(bg, ch) @ np.array(k[ch]) for ch in range(3)], 1)
        img = np.clip(img.reshape(TEXTBOX[1], WIDTH, 3), 0, 255).round().astype(np.uint8)
        Image.fromarray(img).save(out / 'textbox.png')
    for tone, regions in coeffs.items():
        tex = textures(models, tone)
        for region, k in regions.items():
            height = REGIONS[region][1]
            rows = np.arange(height, dtype=np.float32)
            img = np.stack([features(tex, region, rows, ch) @ np.array(k[ch]) for ch in range(3)], 1)
            img = np.clip(img.reshape(height, WIDTH, 3), 0, 255).round().astype(np.uint8)
            Image.fromarray(img).save(out / f'{tone}_{region}.png')


def fit():
    renders = ROOT / 'images/classic/large/english'
    models = ROOT / 'ui/assets/classic/ui/models'
    cards = {}
    for f in ('heroes', 'creeps', 'spells', 'improvements', 'items'):
        cards.update(json.loads((ROOT / f'classic/{f}.json').read_text()))
    groups = {}
    for cid, c in cards.items():
        if not (renders / f'{cid}.png').exists():
            continue
        tone = 'item' if c['type'] == 5 else (c.get('color') or 'none').lower()
        unit = c['type'] in (4, 6)
        for region in ('header', 'bar' if unit else 'strip'):
            groups.setdefault((tone, region), []).append(cid)
    coeffs = {}
    for (tone, region), ids in sorted(groups.items()):
        top, height, _, _ = REGIONS[region]
        stack = np.stack([np.asarray(Image.open(renders / f'{cid}.png').convert('RGB'), dtype=np.float32)
                          [top:top + height, 4:4 + WIDTH] for cid in ids])
        ref = np.median(stack, 0)   # the frame is the same on every card: the median drops the text
        # pixels to fit: off the title / stats / emblem and the rounded corners
        m = np.ones((height, WIDTH), bool)
        m[:, :24] = m[:, -24:] = False
        if region == 'header':
            m[14:74, :480] = False
        else:
            m[:, 200:320] = False   # emblem
            m[:27, :] = False       # above the edge (art) and the edge itself
            if region == 'bar':
                m[60:110, 50:470] = False   # stats
        if len(ids) < 3:   # too few cards for the median to clear the text: keep the margins only
            m[:, 40:480] = False
        rows = np.arange(height, dtype=np.float32)
        tex = textures(models, tone)
        k, err = [], []
        for ch in range(3):
            A = features(tex, region, rows, ch)[m.ravel()]
            b = ref[..., ch][m]
            # a little ridge so the gradient terms do not run away where nothing was sampled
            reg = np.diag(np.diag(A.T @ A)) * 1e-4
            reg[0, 0] = 0
            kk = np.linalg.solve(A.T @ A + reg, A.T @ b)
            k.append([round(float(v), 4) for v in kk])
            err.append(np.abs(A @ kk - b).mean())
        coeffs.setdefault(tone, {})[region] = k
        print(f'{tone:6} {region:6} cards={len(ids):3} err={np.mean(err):.1f}')
    coeffs.setdefault('none', {}).setdefault('strip', coeffs['none'].get('bar'))
    # text box: the median over the spells, improvements and items clears their text
    ids = [cid for cid, c in cards.items() if c['type'] in (5, 7, 9) and (renders / f'{cid}.png').exists()]
    top, h = TEXTBOX
    ref = np.median(np.stack([np.asarray(Image.open(renders / f'{cid}.png').convert('RGB'), dtype=np.float32)
                              [top:top + h, 4:4 + WIDTH] for cid in ids]), 0)
    m = np.ones((h, WIDTH), bool)
    m[:, :8] = m[:, -8:] = False
    m[:70, 180:340] = False   # the improvement ring
    k, err = [], []
    for ch in range(3):
        A = textbox_features(models.parent / 'card/card_background.png', ch)[m.ravel()]
        b = ref[..., ch][m]
        kk = np.linalg.lstsq(A, b, rcond=None)[0]
        k.append([round(float(v), 4) for v in kk])
        err.append(np.abs(A @ kk - b).mean())
    coeffs['textbox'] = k
    print(f'textbox cards={len(ids)} err={np.mean(err):.1f}')
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(coeffs, indent=1) + '\n')
    bake(models, ROOT / 'ui/assets/classic/ui/frame', dict(coeffs))


if __name__ == '__main__':
    if sys.argv[1:] == ['fit']:
        fit()
    else:
        print(__doc__)
