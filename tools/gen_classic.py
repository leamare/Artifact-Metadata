#!/usr/bin/env python3
"""Artifact Classic (classic/): every descriptor of the retail client's card registry
(artifact-reborn-client's content/cards.yaml), merged with Valve's public card API and the
community database (original-meta) and the game's localization, items_game and card sets.
Also images/classic.json, Valve's image URLs.

    python3 tools/gen_classic.py
"""
from __future__ import annotations

import collections
import re

from common import (DECK_TYPES, RARITY_BITS, Paths, by_id, card_items, card_sets, classic_convert, clean, fold,
                    history_of, items_game, keyword_table, link_reverse, link_text, load_json, load_yaml,
                    localization, report, traces, write, write_game)
from sources import Vpk, load_tokens


# --- registry-based games (Classic, Reborn) --------------------------------------------------

def api_cards(P):
    api, set_of = {}, {}
    for s in (0, 1):
        for c in load_json(P.original_meta / f'card_set_{s}.json')['card_set']['card_list']:
            api[c['card_id']] = c
            set_of[c['card_id']] = s
    return api, set_of


def registry_game(P, dump, loc, citems, set_of, prefer_dump):
    """Cards from a client card-registry dump (content/cards.yaml format) merged with
    Valve's card API and the community database. prefer_dump: the dump's values win
    (Reborn, whose cards.yaml carries the patch's balance), else the API's (Classic)."""
    en = loc['english']
    api, api_sets = api_cards(P)
    for cid, s in api_sets.items():
        set_of.setdefault(cid, s)
    community = {c['card_id']: c for c in load_json(P.original_meta / 'CardsClassic.json')}
    comm_abilities = {c['card_id']: c for c in load_json(P.original_meta / 'AbilitiesClassic.json')}
    # Classic: every card the client, the API or the localization knows. Reborn: the cards
    # the patch ships (its localization also carries the documentation-only examples).
    ids = sorted(set(dump) if prefer_dump else set(dump) | set(api) | {c for c, l in en['cards'].items() if l.get('name')})
    cards = {}
    for cid in ids:
        a, d = api.get(cid, {}), dump.get(cid, {})

        def pick(api_key, dump_key):
            av, dv = a.get(api_key), d.get(dump_key)
            if prefer_dump and dump_key in d:
                return dv
            return av if av is not None else dv
        ctype = (DUMP_NAME.get(d.get('type'), d.get('type')) if prefer_dump and d else None) \
            or a.get('card_type') or DUMP_NAME.get(d.get('type'), d.get('type')) or 'Unknown'
        colors = [c for c in ('Red', 'Green', 'Blue', 'Black') if a.get(f'is_{c.lower()}')]
        color = d.get('color') if prefer_dump and d else (colors[0] if colors else d.get('color'))
        rarity = (RARITY_BITS.get(d.get('rarity_code')) if prefer_dump else None) or a.get('rarity') \
            or citems.get(cid, {}).get('rarity') or RARITY_BITS.get(d.get('rarity_code'))
        if d.get('set_id') is not None:
            set_of[cid] = d['set_id']
        elif cid >= 20000 and cid not in set_of:
            set_of[cid] = cid // 10000
        dev = 6000 <= cid < 7000
        if not rarity and set_of.get(cid) == 0 and ctype in DECK_TYPES and not dev:
            rarity = 'Basic'
        card = {
            'id': cid,
            'name': en['cards'].get(cid, {}).get('name') or (a.get('card_name') or {}).get('english') or d.get('name'),
            'type': ctype,
            'set': set_of.get(cid),
            'base_card_id': a.get('base_card_id') if a.get('base_card_id') not in (None, cid) else None,
            'dev': True if dev else None,
            'collectible': cid in citems,
            'rarity': rarity,
            'color': color,
            'mana_cost': pick('mana_cost', 'mana_cost'),
            'gold_cost': pick('gold_cost', 'gold_cost'),
            'attack': pick('attack', 'attack'),
            'armor': pick('armor', 'armor'),
            'health': pick('hit_points', 'health'),
            'bounty': d.get('bounty'),
            'charges': pick('charges', 'charges'),
            'crosslane': True if a.get('is_crosslane') else None,
            'quick': True if (d.get('quick') if prefer_dump and d else (a.get('is_quick') or d.get('quick'))) else None,
            'item_subtype': (d.get('item_subtype') if prefer_dump else None) or a.get('sub_type') or d.get('item_subtype'),
            'equip': clean({'attack': d.get('equip_attack'), 'armor': d.get('equip_armor'),
                            'health': d.get('equip_health'), 'keywords': d.get('equip_keywords')}),
            'illustrator': (d.get('illustrator') if prefer_dump else None) or a.get('illustrator') or d.get('illustrator'),
            'item_def': a.get('item_def') or citems.get(cid, {}).get('item_def'),
            'artwork': clean({
                'artwork_id': d.get('artwork_id'),
                'alternate_artwork_ids': sorted(set(citems.get(cid, {}).get('alternate_artwork_ids', []))
                                                | ({d['alternate_art_id']} if d.get('alternate_art_id') else set())),
                'variants': d.get('art_variants'),
            }),
        }
        refs = [] if (prefer_dump and cid not in api) else a.get('references', [])
        sig = collections.Counter()
        for r in refs:
            if r['ref_type'] == 'includes':
                sig[r['card_id']] += r.get('count', 1)
        if (prefer_dump or not refs) and d.get('includes'):
            sig = collections.Counter(d['includes'])
        if sig:
            card['signature'] = [{'card_id': k, 'count': v} for k, v in sig.items()]
        abil = [r['card_id'] for r in refs if r['ref_type'] in ('active_ability', 'passive_ability')]
        if (prefer_dump or not abil) and d.get('abilities'):
            abil = [x['id'] for x in d['abilities']]
            for x in d['abilities']:
                if x.get('cooldown'):
                    card.setdefault('_cooldowns', {})[x['id']] = x['cooldown']
        if abil:
            card['abilities'] = abil
        others = [r['card_id'] for r in refs if r['ref_type'] == 'references']
        if others:
            card['references'] = others
        engine = {k: d[k] for k in ('play_rules', 'target_rules', 'ability_rules', 'lane_rules', 'keywords',
                                     'has_triggers', 'trigger_count', 'has_modifiers', 'has_charges',
                                     'data_effect', 'cast_sound', 'precast_sound', 'item_kind',
                                     'path_direction', 'basic') if k in d}
        if engine:
            card['engine'] = engine
        comm = community.get(cid) or comm_abilities.get(cid)
        if comm:
            card['release_date'] = comm['versions'][0].get('release_date')
            if comm.get('hide_from_card_list'):
                card['hidden_reason'] = comm['hide_from_card_list']
            if len(comm['versions']) > 1:
                card['history'] = history_of(comm['versions'], classic_convert)
            if comm['versions'][0].get('improvement_type'):
                card['improvement_type'] = comm['versions'][0]['improvement_type']
            if cid in comm_abilities:
                card['cooldown'] = fold(comm['versions']).get('cooldown') or None
        cards[cid] = clean(card)

    for cid, c in cards.items():
        for ab, cd in c.pop('_cooldowns', {}).items():
            if ab in cards:
                cards[ab]['cooldown'] = cd
    link_reverse(cards)
    for cid, c in cards.items():
        if c['type'] in ('Ability', 'Passive Ability') and 'cooldown' not in c:
            m = re.search(r'Active (?:&#9632;)?\s*(\d+)', en['cards'].get(cid, {}).get('text', '') or '')
            if not m:
                for owner in c.get('ability_of', []):
                    owner_text = en['cards'].get(owner, {}).get('text', '') or ''
                    m = re.search(re.escape(f'[abilityname[{c["name"]}]]') +
                                  r'\[activatedability\[\[color:ability\[Active (?:&#9632;)?\s*(\d+)', owner_text)
                    if m:
                        break
            if m:
                c['cooldown'] = int(m[1])
    link_text(cards, en)
    return cards


DUMP_NAME = {'Tower': 'Stronghold', 'Path': 'Pathing', 'Type_10': 'Mutation', 'Passive': 'Passive Ability'}


def classic_set_of(game_dir):
    set_of = {}
    for p in sorted((game_dir / 'game/dcg/resource').glob('card_set_*_english.txt')):
        s = int(re.search(r'card_set_(\d+)_', p.name)[1])
        for k in load_tokens(p):
            if m := re.fullmatch(r'CardName_(\d+)', k):
                set_of.setdefault(int(m[1]), s)
    return set_of


def chat_wheel_classic(P):
    """card id -> chat wheel lines, from the client.dll table the reborn repo extracted
    (docs/content/chat_wheel.md). A line is the sound event; DCG_VO_<line> its subtitle."""
    table = {}
    doc = P.reborn_client / 'docs/content/chat_wheel.md'
    for m in re.finditer(r'^\| (\d+) \| [^|]+ \| \w+ \| (.+) \|$', doc.read_text(), re.M):
        table[int(m[1])] = re.findall(r'`([a-z0-9_]+)`', m[2])
    return table


def build_classic(P: Paths):
    vpk = Vpk(P.classic / 'game/dcg/pak01_dir.vpk')
    loc = localization(P.classic, vpk=vpk)
    dump = {c['id']: c for c in load_yaml(P.reborn_client / 'content/cards.yaml')}
    ig = items_game(vpk)
    citems = card_items(ig)
    set_of = classic_set_of(P.classic)
    cards = registry_game(P, dump, loc, citems, set_of, prefer_dump=False)
    chat = chat_wheel_classic(P)
    extra = {'keywords': keyword_table(loc['english']), 'sets': card_sets(vpk, cards, set_of, loc)}
    write_game('classic', cards, loc, chat, extra)
    return cards




# --- Classic image list -------------------------------------------------------------------------

def build_image_list(P: Paths):
    """URLs of Valve's Classic card images (images/classic.json): the icon (mini), the
    board crop (ingame) and the full card render in every language (large)."""
    api, _ = api_cards(P)
    out = {}
    for cid, c in sorted(api.items()):
        entry = {'mini': (c.get('mini_image') or {}).get('default'),
                 'ingame': (c.get('ingame_image') or {}).get('default'),
                 'large': c.get('large_image')}
        out[cid] = clean(entry)
    write('images/classic.json', by_id(out))


def load_classic(P: Paths):
    """Classic's cards without writing them (Foundry and Reborn build on them)."""
    vpk = Vpk(P.classic / 'game/dcg/pak01_dir.vpk')
    loc = localization(P.classic, vpk=vpk)
    dump = {c['id']: c for c in load_yaml(P.reborn_client / 'content/cards.yaml')}
    return registry_game(P, dump, loc, card_items(items_game(vpk)), classic_set_of(P.classic), False)


def main():
    P = Paths()
    P.need('classic', 'original_meta', 'reborn_client', 'replay_parser')
    report('classic', build_classic(P))
    write('classic/traces.json', traces(P)[0]['classic'])
    build_image_list(P)


if __name__ == '__main__':
    main()
