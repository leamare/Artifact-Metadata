#!/usr/bin/env python3
"""Render Classic cards with ui/render and compare them with Valve's renders.

    python3 scripts/compare_render.py 10001 10002 10206      # given cards
    python3 scripts/compare_render.py --all                  # every card with a render

Needs images/classic/large/english/ (scripts/download_images.py --kind large --lang english)
and ui/assets/ (scripts/extract_assets.py). Writes images/compare/<id>.png
(Valve | ours | difference) and prints the mean absolute error per card (0-255, over the
card's opaque area).
"""
from __future__ import annotations

import argparse
import functools
import http.server
import io
import sys
import threading
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from cdp import Browser  # noqa: E402


def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=str(ROOT))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def error(ref, ours):
    a = np.asarray(ref.convert('RGBA')).astype(np.float32)
    b = np.asarray(ours.convert('RGBA')).astype(np.float32)
    mask = a[..., 3] > 128
    diff = np.abs(a[..., :3] - b[..., :3]).mean(-1)
    return float(diff[mask].mean()), diff


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('ids', nargs='*')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--no-images', action='store_true', help='only print errors')
    args = ap.parse_args()
    refs = ROOT / 'images/classic/large/english'
    ids = sorted((p.stem for p in refs.glob('*.png')), key=int) if args.all else args.ids
    out = ROOT / 'images/compare'
    out.mkdir(parents=True, exist_ok=True)
    server = serve()
    port = server.server_address[1]
    results = []
    with Browser() as b:
        for cid in ids:
            png = b.screenshot(f'http://127.0.0.1:{port}/ui/render/render.html?game=classic&id={cid}')
            ours = Image.open(io.BytesIO(png)).convert('RGBA')
            ref = Image.open(refs / f'{cid}.png').convert('RGBA')
            err, diff = error(ref, ours)
            results.append((err, cid))
            print(f'{cid}: {err:.1f}')
            if not args.no_images:
                heat = Image.fromarray(np.clip(diff * 3, 0, 255).astype(np.uint8)).convert('RGBA')
                sheet = Image.new('RGBA', (526 * 3 + 20, 890), (40, 40, 40, 255))
                for i, im in enumerate((ref, ours, heat)):
                    bg = Image.new('RGBA', (526, 890), (40, 40, 40, 255))
                    bg.alpha_composite(im)
                    sheet.paste(bg, (i * 536, 0))
                sheet.convert('RGB').save(out / f'{cid}.png')
    if len(results) > 1:
        results.sort()
        print(f'mean {sum(e for e, _ in results) / len(results):.1f}; worst:',
              ', '.join(f'{c} {e:.1f}' for e, c in results[-8:]))


if __name__ == '__main__':
    main()
