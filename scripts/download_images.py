#!/usr/bin/env python3
"""Download Valve's Classic card images listed in images/classic.json into images/classic/
(git-ignored).

    python3 scripts/download_images.py                          # every kind, every language
    python3 scripts/download_images.py --kind large --lang english

Layout: images/classic/mini/<id>.png, ingame/<id>.png, large/<language>/<id>.png
("default" in the list is English).
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def jobs(kinds, langs):
    data = json.loads((ROOT / 'images/classic.json').read_text())
    for cid, entry in data.items():
        for kind in kinds:
            if kind in ('mini', 'ingame') and entry.get(kind):
                yield entry[kind], ROOT / f'images/classic/{kind}/{cid}.png'
            elif kind == 'large':
                for lang, url in (entry.get('large') or {}).items():
                    lang = 'english' if lang == 'default' else lang
                    if not langs or lang in langs:
                        yield url, ROOT / f'images/classic/large/{lang}/{cid}.png'


def fetch(job):
    url, out = job
    if out.exists():
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={'User-Agent': 'artifact-metadata'})
    for attempt in range(4):   # the CDN drops connections now and then
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            out.write_bytes(data)
            return 1
        except OSError as e:
            if attempt == 3:
                print(f'failed: {url}: {e}')
                return 0
            time.sleep(2 * (attempt + 1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--kind', action='append', choices=['mini', 'ingame', 'large'])
    ap.add_argument('--lang', action='append', help='large images: only these languages (english = default)')
    args = ap.parse_args()
    todo = list(jobs(args.kind or ['mini', 'ingame', 'large'], set(args.lang or [])))
    with ThreadPoolExecutor(16) as pool:
        done = sum(pool.map(fetch, todo))
    print(f'{done} downloaded, {len(todo) - done} already present')


if __name__ == '__main__':
    main()
