#!/usr/bin/env python3
"""Artifact Foundry (foundry/): the community database's Foundry cards and abilities
(original-meta, with balance history) mapped to the game's card ids, with the Foundry
client's localization, card sets and chat wheel lines. Builds on Classic (names, types,
chat wheel) for cards the community data leaves out.

    python3 tools/gen_foundry.py
"""
from __future__ import annotations

import collections
import re

from common import (COLOUR_LETTERS, DECK_TYPES, Paths, card_sets, clean, community_markup, fold, history_of,
                    keyword_table, link_reverse, link_text, load_json, localization, ref_id, ref_ids,
                    report, traces, write, write_game)
from markup import ability_names
from sources import Vpk
from gen_classic import chat_wheel_classic, classic_set_of, load_classic


# --- Foundry ----------------------------------------------------------------------------------

def chat_wheel_foundry(P, cards, classic_chat, classic_cards):
    """Foundry's chat wheel tokens (#DCG_VO_<line> strings in its client) assigned to cards:
    a line Classic gives to a card stays with that card; other lines go to the card whose
    Classic lines share their prefix, else to the card named like the prefix."""
    lib = P.foundry / 'game/dcg/bin/linuxsteamrt64/libclient.so'
    if not lib.exists():
        return {}
    raw = lib.read_bytes()
    lines = list(dict.fromkeys(m.decode() for m in re.findall(rb'#DCG_VO_([a-z0-9_]+_\d\d)\x00', raw)))
    owner = {l: cid for cid, ls in classic_chat.items() for l in ls}
    prefix_owner = {}
    for cid, ls in classic_chat.items():
        for l in ls:
            prefix_owner.setdefault(re.sub(r'_(angry|arrogant|concerned|enigmatic|pleased|unique|cast_spell|kill_rival|'
                                           r'potential_\w+|permanent_\w+|taunt_\w+|equip_\w+|single_target_\w+|'
                                           r'multi_damage_\w+|healed|ancient_\w+|summon|hiss|pain)_\d\d$', '', l), cid)
    by_name = {re.sub(r'[^a-z]+', '_', (c.get('name') or '').lower()).strip('_'): cid for cid, c in cards.items()
               if c['type'] in ('Hero', 'Creep', 'Summon')}
    table = collections.defaultdict(list)
    for l in lines:
        cid = owner.get(l)
        if cid is None:
            prefix = re.sub(r'_[a-z_]+?_\d\d$', '', l)
            cid = next((prefix_owner[p] for p in prefix_owner if l.startswith(p + '_')), None) or by_name.get(prefix)
        if cid is not None and cid in cards:
            table[cid].append(l)
    # keep Classic's order for the lines both games have
    for cid, ls in table.items():
        order = {l: i for i, l in enumerate(classic_chat.get(cid, []))}
        ls.sort(key=lambda l: order.get(l, len(order) + lines.index(l)))
    return dict(table)


def build_foundry(P: Paths, classic_cards):
    vpk = Vpk(P.foundry / 'game/dcg/pak01_dir.vpk')
    loc = localization(P.foundry, vpk=vpk)
    en = loc['english']
    community = {c['card_id']: c for c in load_json(P.original_meta / 'CardsFoundry.json')}
    comm_abil = {c['card_id']: c for c in load_json(P.original_meta / 'AbilitiesFoundry.json')}
    # Ids with a CardName are Foundry cards; others are stray effect strings of Classic
    # cards Foundry removed.
    loc_ids = {cid for cid, c in en['cards'].items() if c.get('name')}
    set_of = classic_set_of(P.foundry)

    # Community ability ids (2100xx) are synthetic: map each to the in-game card with the
    # same English name (preferring ids its images point at).
    name_to_ids = collections.defaultdict(list)
    for cid, c in sorted(en['cards'].items()):
        if c.get('name'):
            name_to_ids[c['name'].strip().lower()].append(cid)
    ability_map = {}
    for aid, a in sorted(comm_abil.items()):
        name = (fold(a['versions']).get('ability_name') or {}).get('english', '').strip().lower()
        images = set(ref_ids(v['image'] for v in a['versions'] if v.get('image')))
        cands = [i for i in name_to_ids.get(name, []) if i not in community and i not in ability_map.values()]
        best = next((i for i in cands if i in images), cands[0] if cands else None)
        if best is not None:
            ability_map[aid] = best
    ids = sorted(loc_ids | set(community) | {ability_map.get(a, a) for a in comm_abil})
    ability_ids = {ability_map.get(a, a): a for a in comm_abil}
    named_abilities = collections.defaultdict(list)
    for cid, c in en['cards'].items():
        for n in ability_names(c.get('text', '')):
            named_abilities[n.strip().lower()].append(cid)

    def convert(name, val):
        if name == 'abilities':
            return [ability_map.get(r, r) for r in ref_ids(val)]
        if name in ('signature', 'related_cards'):
            return ref_ids(val)
        if name == 'color':
            return COLOUR_LETTERS.get(val, val)
        return val

    cards = {}
    for cid in ids:
        l = en['cards'].get(cid, {})
        comm = community.get(cid)
        aid = ability_ids.get(cid)
        if aid is not None:
            versions = comm_abil[aid]['versions']
            state = fold(versions)
            ctype = 'Passive Ability' if state.get('ability_type') == 'Passive' else 'Ability'
        elif comm:
            versions = comm['versions']
            state = fold(versions)
            ctype = state.get('card_type') or 'Unknown'
        else:
            versions, state = [], {}
            cl = classic_cards.get(cid)
            name = (l.get('name') or '').strip().lower()
            if cl and cl.get('name', '').strip().lower() == name:
                ctype = cl['type']
            elif named_abilities.get(name) or '{s:parentCardName}' in (l.get('text') or ''):
                ctype = 'Ability'
            else:
                ctype = 'Unknown'
        type_source = 'community' if (comm or aid is not None) else (
            'classic' if ctype != 'Unknown' and classic_cards.get(cid, {}).get('type') == ctype
            and not named_abilities.get((l.get('name') or '').strip().lower()) else
            ('inferred' if ctype != 'Unknown' else None))
        colour = state.get('colour')
        card = {
            'id': cid,
            'community_id': aid if aid is not None and aid != cid else None,
            'name': l.get('name') or (state.get('card_name') or state.get('ability_name') or {}).get('english'),
            'type': ctype,
            'type_source': type_source,
            'set': set_of.get(cid, state.get('set')),
            'collectible': (not comm.get('hide_from_card_list')) if comm and ctype in DECK_TYPES else None,
            'hidden_reason': comm.get('hide_from_card_list') if comm else None,
            'color': COLOUR_LETTERS.get(colour, colour) if colour else None,
            'rarity': state.get('rarity'),
            'faction': state.get('faction') or state.get('Faction'),
            'mana_cost': state.get('cost') if ctype != 'Item' and aid is None else None,
            'gold_cost': state.get('gcost') if ctype == 'Item' else None,
            'attack': state.get('attack'),
            'armor': state.get('armour'),
            'health': state.get('hp'),
            'cooldown': state.get('cooldown') if aid is not None else None,
            'ability_cost': state.get('cost') if aid is not None else None,
            'crosslane': True if state.get('crosslane') else None,
            'quick': True if state.get('quick') else None,
            'item_subtype': state.get('card_subtype'),
            'improvement_type': state.get('improvement_type'),
            # The community database names ability art after its own 2100xx ids: use the card id.
            'artwork': clean({'artwork_id': (ability_map.get(ref_id(state['image']), ref_id(state['image']))
                                             if state.get('image') else None)}),
            'release_date': versions[0].get('release_date') if versions else None,
            'search_terms': comm.get('searchterm') if comm else None,
        }
        if state.get('signature'):
            card['signature'] = [{'card_id': r, 'count': 3} for r in ref_ids(state['signature'])]
        if state.get('abilities'):
            card['abilities'] = [ability_map.get(r, r) for r in ref_ids(state['abilities'])]
        if state.get('related_cards'):
            card['related_cards'] = sorted(set(ref_ids(state['related_cards'])))
        if len(versions) > 1:
            card['history'] = history_of(versions, convert)
        if (state.get('text') or {}).get('english'):
            card['community_text'] = community_markup(state['text']['english'])
        if state.get('lore'):
            card['community_lore'] = state['lore'].get('english') if isinstance(state['lore'], dict) else state['lore']
        cards[cid] = clean(card)

    # Cards known only from Foundry's localization that are the same card as in Classic
    # (type_source "classic") take Classic's stats where Foundry's sources have none.
    for cid, c in cards.items():
        if c.get('type_source') == 'classic':
            for k in ('mana_cost', 'gold_cost', 'attack', 'armor', 'health', 'item_subtype', 'charges',
                      'crosslane', 'quick', 'color', 'artwork'):
                if k not in c and k in classic_cards.get(cid, {}):
                    c[k] = classic_cards[cid][k]
    link_reverse(cards)
    for name, owners in named_abilities.items():
        for target in name_to_ids.get(name, []):
            c = cards.get(target)
            if c and c['type'] in ('Ability', 'Passive Ability'):
                for o in owners:
                    if o != target and o not in c.get('ability_of', []):
                        c.setdefault('ability_of', []).append(o)
    for cid, c in cards.items():
        if c['type'] == 'Ability' and c.get('type_source') == 'inferred' and c.get('ability_of'):
            text = en['cards'].get(c['ability_of'][0], {}).get('text', '') or ''
            if f'[abilityname[{c["name"]}]]' in text and f'[abilityname[{c["name"]}]][activatedability' not in text:
                c['type'] = 'Passive Ability'
        if c['type'] in ('Ability', 'Passive Ability'):
            for o in c.get('ability_of', []):
                if o in cards and cid not in cards[o].get('abilities', []):
                    cards[o].setdefault('abilities', []).append(cid)
    link_text(cards, en)
    chat = chat_wheel_foundry(P, cards, chat_wheel_classic(P), classic_cards)
    keywords = keyword_table(en)
    keywords['community_keywords'] = load_json(P.original_meta / 'Keywords.json')
    extra = {'keywords': keywords, 'sets': card_sets(vpk, cards, set_of, loc)}
    write_game('foundry', cards, loc, chat, extra)
    return cards


def main():
    P = Paths()
    P.need('classic', 'foundry', 'original_meta', 'reborn_client', 'replay_parser')
    report('foundry', build_foundry(P, load_classic(P)))   # Classic's cards are read, not written
    write('foundry/traces.json', traces(P)[0]['foundry'])


if __name__ == '__main__':
    main()
