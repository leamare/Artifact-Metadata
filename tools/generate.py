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
  REBORN_CONTENT                      artifact-reborn-content (cards_index definitions and
                                      localization; card art; chat wheel lines)
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

from common import (RARITY_BITS, ROOT, Paths, _card_tokens, by_id, card_items, card_sets, content_card_folders,
                    content_dump, items_game, keyword_table, load_json, load_yaml, report, traces, write, write_game)
from gen_classic import chat_wheel_classic, classic_set_of, load_classic, registry_game
from sources import Vpk, kv_dict, kv_get, load_tokens, parse_kv, read_text


def reborn_localization(P: Paths):
    """Patch text from the content workspace: shared localization YAML, then each card
    folder's localization.yaml over it."""
    families = collections.defaultdict(dict)
    base = P.reborn_content / 'content/localization'
    for f in sorted(base.glob('*/*.yaml')):
        families[f.parent.name].setdefault(f.stem, {}).update(load_yaml(f) or {})
    card_text = collections.defaultdict(dict)
    card_voice = collections.defaultdict(dict)
    for cid, folder in content_card_folders(P.reborn_content).items():
        path = folder / 'localization.yaml'
        if not path.is_file():
            continue
        for lang, entry in (load_yaml(path) or {}).items():
            if not isinstance(entry, dict):
                continue
            loc = {}
            for key in ('name', 'text', 'lore'):
                if entry.get(key):
                    loc[key] = str(entry[key])
            for key in ('effects', 'modifications'):
                if isinstance(entry.get(key), dict) and entry[key]:
                    loc[key] = {str(k): str(v) for k, v in entry[key].items()}
            if loc:
                card_text[lang][cid] = loc
            voice = entry.get('voice')
            if isinstance(voice, dict):
                for key, text in voice.items():
                    token = key if str(key).startswith('DCG_VO_') else f'DCG_VO_{key}'
                    card_voice[lang][token] = str(text)
    english = families.get('english', {})
    out = {}
    langs = set(families) | set(card_text) | set(card_voice)
    for lang in langs:
        fams = families.get(lang, {})
        tokens = {}
        for name in ('cards', 'dcg_lore_set_00', 'dcg_lore_set_01'):
            tokens.update(english.get(name, {}) if lang != 'english' and name.startswith('dcg_lore') else {})
            tokens.update(fams.get(name, {}))
        cards = collections.defaultdict(dict)
        _card_tokens({k: str(v) for k, v in tokens.items()}, cards)
        for cid, loc in card_text.get(lang, {}).items():
            cards[cid].update(loc)
        common = {**fams.get('dcg', {}), **fams.get('dcg_common', {}), **fams.get('items', {})}
        vo = {**english.get('dcg_vo_set_01', {}), **fams.get('dcg_vo_set_01', {}), **card_voice.get(lang, {})}
        if not cards and not fams:
            continue
        out[lang] = {'cards': dict(cards), 'glossary': fams.get('dcg_glossary', {}),
                     'common': {k: str(v) for k, v in common.items()},
                     'vo': {k: str(v) for k, v in vo.items() if str(k).startswith('DCG_VO_')}}
    return out




# --- Reborn (community patch) --------------------------------------------------------------

def build_reborn(P: Paths, classic_cards):
    """The game as the community patch ships it: the content workspace's card index
    (every card the SDK authors) and its localization."""
    dump = content_dump(P.reborn_content)
    gc_dir = P.reborn_gc / 'internal/gc'
    gc_defs = {int(m[1]) - 100000 for m in re.finditer(r'\b(1\d{5}),', read_text(gc_dir / 'cards.go'))}
    loc = reborn_localization(P)
    vpk = Vpk(P.classic / 'game/dcg/pak01_dir.vpk')
    ig = items_game(vpk)
    citems = card_items(ig)
    for cid in gc_defs:
        if cid >= 20000:
            citems.setdefault(cid, {'item_def': 100000 + cid, 'set': cid // 10000,
                                    'rarity': RARITY_BITS.get((dump.get(cid) or {}).get('rarity_code'))})
    # Collectible community cards are listed in community_cards_gen.go, not cards.go.
    for m in re.finditer(r'\{ID: (\d+), Name: "[^"]*", CardType: \w+, Colour: \w+, Cost: \d+, Rarity: Rarity(\w+)\}',
                         read_text(gc_dir / 'community_cards_gen.go')):
        cid = int(m[1])
        citems.setdefault(cid, {'item_def': 100000 + cid, 'set': (dump.get(cid) or {}).get('set_id', cid // 10000),
                                'rarity': RARITY_BITS.get((dump.get(cid) or {}).get('rarity_code')) or m[2]})
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
            'reborn': ('classic', 'original_meta', 'reborn_content', 'reborn_gc', 'replay_parser')}
    P.need(*sorted({a for p in parts for a in need[p]}))
    if 'commons' in parts:
        build_commons(P)
    if 'reborn' in parts:   # on Classic's cards, read but not written
        report('reborn', build_reborn(P, load_classic(P)))
        write('reborn/traces.json', traces(P)[0]['classic'])   # Reborn runs Classic's client


if __name__ == '__main__':
    main()
