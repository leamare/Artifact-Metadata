#!/usr/bin/env python3
"""Regenerate the metadata repository from the game files and source repos.

    python3 tools/generate.py                     # commons/ and reborn/
    python3 tools/generate.py --only reborn       # one part: commons or reborn
    python3 tools/gen_classic.py                  # classic/ and images/classic.json
    python3 tools/gen_foundry.py                  # foundry/

Source locations come from .env (copy .env.example, which has the usual Linux/Steam paths):
  ARTIFACT_CLASSIC, ARTIFACT_FOUNDRY  the game installs (localization, pak01_dir.vpk)
  DOTA2                               Dota 2's install (regions.txt; optional)
  ORIGINAL_META                       Valve's card API dumps and the community card database
  REBORN_CLIENT                       artifact-reborn-client (content/cards.yaml, localization, chat wheel)
  REBORN_GC                           artifact-reborn-gc (gauntlets, community card ids)
  REPLAY_PARSER                       replay-parser (trace tables and protos)

This script writes the commons and Reborn (the community patch, read on top of Classic's
cards); classic/ and foundry/ are written only by tools/gen_classic.py and tools/gen_foundry.py.
commons/clusters.json is maintained data (not generated).
"""
from __future__ import annotations

import argparse
import collections
import re

from common import (RARITY_BITS, ROOT, Paths, _card_tokens, by_id, card_items, card_sets, items_game, keyword_table,
                    load_json, load_yaml, report, traces, write, write_game)
from gen_classic import chat_wheel_classic, classic_set_of, load_classic, registry_game
from sources import Vpk, kv_dict, kv_get, load_tokens, parse_kv, read_text


def reborn_localization(P: Paths):
    """The same structure, from artifact-reborn-client's content/localization YAML (the
    patch's own text) plus the community cards' localization."""
    families = collections.defaultdict(dict)
    for base in (P.reborn_client / 'content/localization', P.reborn_client / 'docs/content/examples/localization'):
        for f in sorted(base.glob('*/*.yaml')):
            families[f.parent.name].setdefault(f.stem, {}).update(load_yaml(f) or {})
    english = families.get('english', {})
    out = {}
    for lang, fams in families.items():
        if 'cards' not in fams:
            continue
        tokens = {}
        for name in ('cards', 'dcg_lore_set_00', 'dcg_lore_set_01'):
            # The examples' other languages fall back to English (see their headers).
            tokens.update(english.get(name, {}) if lang != 'english' and name.startswith('dcg_lore') else {})
            tokens.update(fams.get(name, {}))
        cards = collections.defaultdict(dict)
        _card_tokens({k: str(v) for k, v in tokens.items()}, cards)
        common = {**fams.get('dcg', {}), **fams.get('dcg_common', {}), **fams.get('items', {})}
        vo = {**english.get('dcg_vo_set_01', {}), **fams.get('dcg_vo_set_01', {})}
        out[lang] = {'cards': dict(cards), 'glossary': fams.get('dcg_glossary', {}),
                     'common': {k: str(v) for k, v in common.items()},
                     'vo': {k: str(v) for k, v in vo.items() if k.startswith('DCG_VO_')}}
    return out




# --- Reborn (community patch) --------------------------------------------------------------

def build_reborn(P: Paths, classic_cards):
    """The game as the community patch ships it: artifact-reborn-client's content/cards.yaml
    (the full card list) plus the community cards the server defines, with the patch's own
    localization."""
    dump = {c['id']: c for c in load_yaml(P.reborn_client / 'content/cards.yaml')}
    gc_dir = P.reborn_gc / 'internal/gc'
    gc_defs = {int(m[1]) - 100000 for m in re.finditer(r'\b(1\d{5}),', read_text(gc_dir / 'cards.go'))}
    examples = {c['id']: c for c in load_yaml(P.reborn_client / 'docs/content/examples/cards.yaml')}
    # The coordinator's community cards and everything they include are what the server ships
    # (build_editions.ps1 -CustomCards); the examples' other ids are documentation samples.
    shipped = {cid for cid in examples if cid in gc_defs}
    for cid in list(shipped):
        c = examples[cid]
        shipped |= set(c.get('includes', [])) | {a['id'] for a in c.get('abilities', [])}
    dump.update({cid: examples[cid] for cid in shipped})
    loc = reborn_localization(P)
    vpk = Vpk(P.classic / 'game/dcg/pak01_dir.vpk')
    ig = items_game(vpk)
    citems = card_items(ig)
    for cid in gc_defs:
        if cid >= 20000:
            citems.setdefault(cid, {'item_def': 100000 + cid, 'set': cid // 10000,
                                    'rarity': RARITY_BITS.get((examples.get(cid) or {}).get('rarity_code'))})
    set_of = classic_set_of(P.classic)
    cards = registry_game(P, dump, loc, citems, set_of, prefer_dump=True)
    # Community heroes the coordinator lists without a descriptor here (their data lives in
    # the game server's cards.yaml): name, colour, rarity from the coordinator's tables.
    catalog = read_text(gc_dir / 'catalog.go')
    colours = dict(re.findall(r'\{(2\d{4}), (\w+), \d+\}', read_text(gc_dir / 'carddata.go')))
    for m in re.finditer(r'\{(2\d{4}), Rarity(\w+), "([^"]+)"\}', catalog):
        cid = int(m[1])
        if cid not in cards:
            cards[cid] = {'id': cid, 'name': m[3], 'type': 'Hero', 'set': cid // 10000, 'collectible': True,
                          'rarity': m[2], 'color': colours.get(m[1]), 'item_def': 100000 + cid}
    chat = dict(chat_wheel_classic(P))
    for cid, c in dump.items():
        if c.get('chat_wheel'):
            chat[cid] = [t.lstrip('#').removeprefix('DCG_VO_') for t in c['chat_wheel']]
    extra = {'keywords': keyword_table(loc['english']),
             'sets': card_sets(vpk, cards, set_of, loc),
             'gauntlets': reborn_gauntlets(gc_dir, load_tokens(P.classic / 'game/dcg/panorama/localization/dcg_english.txt'))}
    write_game('reborn', cards, loc, chat, extra)
    return cards


def reborn_gauntlets(gc_dir, ui):
    src = read_text(gc_dir / 'gauntlet.go')
    consts = {}
    for f in sorted(gc_dir.glob('*.go')):
        consts.update({m[1]: m[2] for m in re.finditer(r'(\w+)\s+(?:uint32\s+)?=\s+(\d+)\b', read_text(f))})
    block = src[src.index('var gauntletConfiguredGauntlets'):]
    block = block[:block.index('\n}\n')]
    out = {}
    comment, cur = [], None
    for line in block.splitlines():
        if m := re.match(r'\s*// ?(.*)', line):
            comment.append(m[1])
            continue
        if m := re.search(r'id:\s+(\w+)', line):
            gid = int(m[1]) if m[1].isdigit() else int(consts[m[1]])
            cur = out[gid] = {'description': re.sub(r'^\d+ ', '', ' '.join(comment))}
            comment = []
        elif cur is not None and (m := re.search(r'(\w+):\s+([\w.]+),', line)):
            val = m[2]
            if val.isdigit():
                val = int(val)
            elif val in consts:
                val = int(consts[val])
            elif val in ('true', 'false'):
                val = val == 'true'
            cur[re.sub(r'(?<=[a-z])([A-Z]+)', lambda x: '_' + x[1].lower(), m[1])] = val
        elif line.strip() == '},':
            cur = None
    names = load_json(ROOT / 'commons/gauntlet_types.json')
    pack = read_text(gc_dir.parent.parent / 'content/default.toml')
    for gid, g in out.items():
        m = re.search(r'"#DCG_Gauntlet_Name_%d"\s*=\s*"((?:[^"\\]|\\.)*)"' % gid, pack)
        retail = re.sub(r'<[^>]+>', '', ui.get(f'DCG_Gauntlet_Name_{gid}') or names.get(str(gid)) or '') or None
        g['name'] = re.sub(r'<[^>]+>', '', m[1].replace('\\"', '"')) if m else retail
        if retail and retail != g['name']:
            g['retail_name'] = retail
    return by_id(out)


# --- Commons --------------------------------------------------------------------------------

def build_commons(P: Paths):
    data = ROOT / 'tools/data'
    names = load_json(data / 'region_names.json')
    regions = {}
    if P.dota and (P.dota / 'game/dota/pak01_dir.vpk').exists():
        dvpk = Vpk(P.dota / 'game/dota/pak01_dir.vpk')
        for key, node in kv_get(parse_kv(dvpk.text('scripts/regions.txt')), 'regions') or []:
            d = kv_dict(node)
            rid = int(d.get('region', 0))
            regions[rid] = {'name': names.get(str(rid), key), 'key': key, 'code': d.get('code'),
                            'latitude': float(d['latitude']) if d.get('latitude') else None,
                            'longitude': float(d['longitude']) if d.get('longitude') else None}
    avpk = Vpk(P.classic / 'game/dcg/pak01_dir.vpk')
    for key, node in kv_get(parse_kv(avpk.text('scripts/regions.txt')), 'regions') or []:
        d = kv_dict(node)
        rid = int(d.get('region', 0))
        r = regions.setdefault(rid, {'name': names.get(str(rid), key), 'key': key})
        r['artifact'] = True
        if d.get('code') != r.get('code'):
            r['artifact_code'] = d.get('code')
    for rid, name in names.items():
        regions.setdefault(int(rid), {'name': name})
    write('commons/regions.json', by_id(regions))
    write('commons/rarity.json', {
        'classic': {'0': 'Basic', '1': 'Common', '2': 'Uncommon', '3': 'Rare'},
        'client_rarity_bits': {'2': 'Common', '4': 'Uncommon', '8': 'Rare'},
        'colors': {'Common': '#b0c3d9', 'Uncommon': '#5e98d9', 'Rare': '#4b69ff'},
    })
    write('commons/traces_data.json', traces(P)[1])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--only', action='append', choices=['commons', 'reborn'])
    args = ap.parse_args()
    P = Paths()
    parts = set(args.only or ['commons', 'reborn'])
    need = {'commons': ('classic', 'replay_parser'),
            'reborn': ('classic', 'original_meta', 'reborn_client', 'reborn_gc', 'replay_parser')}
    P.need(*sorted({a for p in parts for a in need[p]}))
    if 'commons' in parts:
        build_commons(P)
    if 'reborn' in parts:   # on Classic's cards, read but not written
        report('reborn', build_reborn(P, load_classic(P)))
        write('reborn/traces.json', traces(P)[0]['classic'])   # Reborn runs Classic's client


if __name__ == '__main__':
    main()
