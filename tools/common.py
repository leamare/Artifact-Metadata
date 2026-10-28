"""Shared parts of the generators: source paths (.env), card type tables, localization,
items_game / card sets, the community database's version history, card text links and the
game folder writer. tools/generate.py runs the generators; tools/gen_classic.py and
tools/gen_foundry.py build Classic and Foundry from the game files and community repos.
"""
from __future__ import annotations

import collections
import json
import os
import re
import shutil
from pathlib import Path

from markup import keyword_ids, plain
from sources import Vpk, kv_dict, kv_get, load_tokens, parse_kv, read_text

ROOT = Path(__file__).resolve().parent.parent


def _env():
    """KEY=value lines of .env (else .env.example) at the repository root; ~ and $VARS expand."""
    for name in ('.env', '.env.example'):
        path = ROOT / name
        if path.exists():
            out = {}
            for line in path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    out[key.strip()] = os.path.expanduser(os.path.expandvars(value.strip().strip('"\'')))
            return out
    return {}


class Paths:
    """Source locations, from .env (copy .env.example and edit). The environment wins over the file."""
    _keys = {'classic': 'ARTIFACT_CLASSIC', 'foundry': 'ARTIFACT_FOUNDRY', 'dota': 'DOTA2',
             'original_meta': 'ORIGINAL_META', 'reborn_client': 'REBORN_CLIENT', 'reborn_gc': 'REBORN_GC',
             'replay_parser': 'REPLAY_PARSER'}

    def __init__(self):
        env = _env()
        for attr, key in self._keys.items():
            value = os.environ.get(key) or env.get(key)
            setattr(self, attr, Path(value) if value else None)

    def need(self, *attrs):
        missing = [self._keys[a] for a in attrs if not getattr(self, a) or not getattr(self, a).exists()]
        if missing:
            raise SystemExit(f'set {", ".join(missing)} in .env (see .env.example): not found')


def load_yaml(path):
    try:
        import yaml
    except ImportError:
        raise SystemExit('PyYAML is needed: pip install -r requirements.txt') from None
    return yaml.safe_load(Path(path).read_text())


# Card types are commons/card_types.json ids. Passive abilities are abilities with
# is_passive; Foundry's summons (tokens) are creeps with is_summon.
CARD_TYPES = {v: int(k) for k, v in json.loads((ROOT / 'commons/card_types.json').read_text()).items()}
TYPE_ALIASES = {'Passive Ability': ('Ability', 'is_passive'), 'Summon': ('Creep', 'is_summon'),
                'Tower': ('Stronghold', None), 'Path': ('Pathing', None), 'Type_10': ('Mutation', None),
                'Passive': ('Ability', 'is_passive')}
TYPE_FILES = {6: 'heroes', 4: 'creeps', 7: 'spells', 9: 'improvements', 5: 'items', 8: 'abilities',
              1: 'mutations', 2: 'default', 3: 'default', 0: 'other'}
DECK_TYPES = {'Hero', 'Creep', 'Spell', 'Improvement', 'Item'}
RARITY_BITS = {2: 'Common', 4: 'Uncommon', 8: 'Rare'}
COLOUR_LETTERS = {'R': 'Red', 'G': 'Green', 'U': 'Blue', 'B': 'Black', 'C': None}
TEXT_FIELDS = ('text', 'text_plain', 'keyword_ids', 'lore')
# UI strings a card face needs (ui/render): the charges line under the text.
UI_TOKENS = ('DCG_CardText_Charges',)


def report(name, cards):
    types = collections.Counter(c['type'] for c in cards.values())
    print(f'{name}: {len(cards)} cards', dict(types.most_common()))


# --- output helpers -----------------------------------------------------------

def clean(value):
    """Drop None / empty containers recursively (False and 0 are kept)."""
    if isinstance(value, dict):
        out = {k: clean(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v is not None and v != {} and v != [] and v != ''}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def by_id(mapping):
    """Sort a {id: value} mapping numerically and stringify keys."""
    def key(k):
        try:
            return (0, int(k))
        except (TypeError, ValueError):
            return (1, str(k))
    return {str(k): mapping[k] for k in sorted(mapping, key=key)}


def write(path, data):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(data), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


# --- localization ---------------------------------------------------------------

def _card_tokens(tokens, cards):
    for k, v in tokens.items():
        if m := re.fullmatch(r'CardName_(\d+)', k):
            cards[int(m[1])]['name'] = v
        elif m := re.fullmatch(r'CardText_(\d+)', k):
            cards[int(m[1])]['text'] = v
        elif m := re.fullmatch(r'CardLore_(\d+)', k):
            cards[int(m[1])]['lore'] = v
        elif m := re.fullmatch(r'Card(Effect|Modification)_(\d+)_(\d+)', k):
            key = 'effects' if m[1] == 'Effect' else 'modifications'
            cards[int(m[2])].setdefault(key, {})[m[3]] = v


def localization(game_dir: Path, vpk=None):
    """{lang: {cards: {id: {name, text, lore, effects, modifications}}, glossary, common, vo}}
    from the loose localization files of one install."""
    res = game_dir / 'game/dcg/resource'
    pano = game_dir / 'game/dcg/panorama/localization'
    langs = sorted({p.name[len('card_set_00_'):-4] for p in res.glob('card_set_00_*.txt')})
    out = {}
    for lang in langs:
        tokens = {}
        for p in sorted(res.glob(f'card_set_*_{lang}.txt')):
            tokens.update(load_tokens(p))
        for p in sorted(pano.glob(f'dcg_lore_set_*_{lang}.txt')):
            tokens.update(load_tokens(p))
        cards = collections.defaultdict(dict)
        _card_tokens(tokens, cards)
        glossary = load_tokens(pano / f'dcg_glossary_{lang}.txt') if (pano / f'dcg_glossary_{lang}.txt').exists() else {}
        common = {}
        for p in (pano / f'dcg_{lang}.txt', res / f'dcg_common_{lang}.txt'):
            if p.exists():
                common.update(load_tokens(p))
        if vpk is not None and f'resource/localization/items_{lang}.txt' in vpk:
            common.update(load_tokens(vpk.text(f'resource/localization/items_{lang}.txt'), is_text=True))
        vo = {}
        for p in sorted(pano.glob(f'dcg_vo_set_*_{lang}.txt')):
            vo.update({k: v for k, v in load_tokens(p).items() if k.startswith('DCG_VO_')})
        out[lang] = {'cards': dict(cards), 'glossary': glossary, 'common': common, 'vo': vo}
    return out




def keyword_table(loc_en):
    """Glossary keyword ids ([g:N[...]] in card text) -> name, words used, and the
    matching glossary entry (title + description), from English localization."""
    words = collections.defaultdict(collections.Counter)
    examples = collections.defaultdict(list)
    for cid, c in sorted(loc_en['cards'].items()):
        for gid, word in keyword_ids(c.get('text', '')).items():
            word = plain(word)
            if word:
                words[gid][word] += 1
            if len(examples[gid]) < 5:
                examples[gid].append(cid)
    gl = loc_en['glossary']
    titles = {}
    for k, v in gl.items():
        if m := re.fullmatch(r'DCG_Glossary_(.+)_Title', k):
            titles[re.sub(r'[^a-z]', '', str(v).lower())] = m[1]
    table = {}
    for gid in sorted(words):
        name = words[gid].most_common(1)[0][0]
        entry = None
        for candidate in [w for w, _ in words[gid].most_common()]:
            norm = re.sub(r'[^a-z]', '', candidate.lower())
            for variant in (norm, norm.rstrip('s'), norm + 's', re.sub(r'(ed|ing)$', '', norm)):
                if variant in titles:
                    entry = titles[variant]
                    break
            if entry:
                break
        item = {'name': name[:1].upper() + name[1:], 'words': sorted(words[gid])}
        if entry:
            item['glossary_key'] = f'DCG_Glossary_{entry}'
            item['title'] = gl.get(f'DCG_Glossary_{entry}_Title')
            item['description'] = plain(str(gl.get(f'DCG_Glossary_{entry}', '')))
        item['example_cards'] = examples[gid]
        table[gid] = item
    glossary = {}
    for k, v in gl.items():
        if m := re.fullmatch(r'DCG_Glossary_(.+)_Title', k):
            glossary[m[1]] = {'title': v, 'description': plain(str(gl.get(f'DCG_Glossary_{m[1]}', '')))}
    return {'keywords': by_id(table), 'glossary': glossary}


# --- items_game / packs -------------------------------------------------------------

def items_game(vpk: Vpk):
    return parse_kv(vpk.text('scripts/items/items_game.txt'))


def card_items(ig):
    """Card item definitions: card_id -> {item_def, rarity, set, type, artwork}."""
    items = kv_get(kv_get(ig, 'items_game') or ig, 'items')
    out = {}
    for def_index, node in items or []:
        if not def_index.isdigit() or isinstance(node, str):
            continue
        info = kv_get(node, 'card_info')
        if not info:
            continue
        d = kv_dict(info)
        prefab = kv_get(node, 'prefab', '')
        out[int(d['card_id'])] = clean({
            'item_def': int(def_index),
            'rarity': prefab.replace('card_', '').capitalize() if prefab.startswith('card_') else None,
            'set': int(d['set_id']) if d.get('set_id') else None,
            'type': d.get('card_type'),
            'alternate_artwork_ids': [int(v) for k, v in d.items() if k.startswith('altArtworkID')],
        })
    return out


def card_sets(vpk: Vpk, cards, set_of, loc):
    """Card sets: names per language and member cards."""
    sets_kv = kv_dict(kv_get(parse_kv(vpk.text('scripts/card_sets.txt')), 'card_sets'))
    sets = {}
    for sid in sorted({int(s) for s in sets_kv} | {s for s in set_of.values() if s is not None}):
        s = sets_kv.get(str(sid), {})
        members = sorted(c for c, si in set_of.items() if si == sid)
        token = s.get('display_name') or f'DCG_SetName_{sid:02d}'
        names = {lang: d['common'].get(token) for lang, d in loc.items()}
        sets[sid] = {
            'name': names.get('english') or s.get('name'),
            'internal_name': s.get('name'),
            'state': s.get('state'),
            'pack_item_def': int(s['pack_item_def']) if s.get('pack_item_def') else None,
            'names': {k: v for k, v in names.items() if v},
            'cards': members,
        }
        sets[sid] = {k: v for k, v in sets[sid].items() if v is not None}
    return by_id(sets)


# --- community database helpers --------------------------------------------------------

COMMUNITY_FIELDS = {
    'card_type': 'type', 'card_name': 'name', 'set': 'set', 'rarity': 'rarity', 'colour': 'color',
    'cost': 'cost', 'gcost': 'gold_cost', 'attack': 'attack', 'armour': 'armor', 'hp': 'health',
    'text': 'text', 'abilities': 'abilities', 'signature': 'signature', 'is_signature': 'is_signature',
    'related_cards': 'related_cards', 'crosslane': 'crosslane', 'quick': 'quick',
    'card_subtype': 'item_subtype', 'improvement_type': 'improvement_type', 'lore': 'lore',
    'faction': 'faction', 'ability_type': 'ability_type', 'ability_name': 'name', 'cooldown': 'cooldown',
}


def fold(versions):
    state = {}
    for v in versions:
        state.update(v)
    return state


def ref_id(ref):
    """Community reference "10491_0" -> 10491 (None for placeholders like "PH")."""
    head = str(ref).split('_')[0]
    return int(head) if head.isdigit() else None


def ref_ids(refs):
    return [i for i in (ref_id(r) for r in refs) if i is not None]


def history_of(versions, convert=lambda k, v: v):
    """Balance history. The first entry holds the release values of every field that
    changed later; each later entry holds only what changed that day."""
    norm = []
    for v in versions:
        entry = {}
        for k, val in v.items():
            name = COMMUNITY_FIELDS.get(k)
            if not name:
                continue
            if isinstance(val, dict) and 'english' in val:
                val = val['english']
            entry[name] = convert(name, val)
        norm.append((v.get('release_date'), entry))
    state, changes = {}, []
    for i, (date, entry) in enumerate(norm):
        diff = {k: val for k, val in entry.items() if i == 0 or state.get(k) != val}
        state.update(entry)
        if i and diff:
            changes.append({'release_date': date, **diff})
    if not changes:
        return []
    changed = {k for c in changes for k in c if k != 'release_date'}
    first_date, first = norm[0]
    return [{'release_date': first_date, **{k: v for k, v in first.items() if k in changed}}] + changes


def classic_convert(k, v):
    if k == 'color':
        return COLOUR_LETTERS.get(v, v)
    if k in ('abilities', 'signature', 'related_cards'):
        return ref_ids(v)
    return v


# --- text, links, output ------------------------------------------------------------------

def link_reverse(cards):
    for cid, c in cards.items():
        for s in c.get('signature', []):
            if s['card_id'] in cards:
                cards[s['card_id']].setdefault('signature_of', []).append(cid)
        for ab in c.get('abilities', []):
            if ab in cards and cid not in cards[ab].get('ability_of', []):
                cards[ab].setdefault('ability_of', []).append(cid)
        for r in c.get('references', []):
            if r in cards:
                cards[r].setdefault('referenced_by', []).append(cid)


def parent_of(cards, cid):
    c = cards[cid]
    ref = (c.get('ability_of') or c.get('signature_of') or [None])[0]
    return cards.get(ref, {}).get('name') if ref else None


def community_markup(text):
    """The community database's own text markup -> the game's ([AR] glyphs, [TG]..[ET]
    ability labels, /n breaks, links)."""
    text = text.strip()
    text = re.sub(r'\s*/n\s*', '<br>', text)
    text = re.sub(r'(\d+)\[AC\]', r'&#9632;\1', text)
    text = text.replace('[AT]', '&#9635;').replace('[AR]', '&#9636;').replace('[HP]', '&#9637;')
    text = re.sub(r'\[TG\](.*?)\[ET\]', r'[color:ability[\1]]', text)
    return re.sub(r'<a [^>]*>(.*?)</a>', r'[[\1]]', text)


def link_text(cards, loc_en):
    """English text fields (moved to cards_text.json on output)."""
    for cid, card in cards.items():
        l = loc_en['cards'].get(cid, {})
        raw = l.get('text') or card.pop('community_text', None)
        if raw:
            card['text'] = raw
            card['text_plain'] = plain(raw, card.get('name'), parent_of(cards, cid))
            kws = keyword_ids(raw)
            if kws:
                card['keyword_ids'] = sorted(kws)
        lore = l.get('lore') or card.pop('community_lore', None)
        if lore:
            card['lore'] = plain(lore)
        card.pop('community_text', None)
        card.pop('community_lore', None)


def localized(cards, loc, chat_wheel):
    """Per-language files: card text, plus the subtitles of the chat wheel lines."""
    out = {}
    lines = {l for ls in chat_wheel.values() for l in ls}
    for lang, data in loc.items():
        names = {cid: c.get('name') for cid, c in data['cards'].items()}
        entries = {}
        for cid, card in cards.items():
            c = data['cards'].get(cid)
            if not c:
                continue
            ref = (card.get('ability_of') or card.get('signature_of') or [None])[0]
            entry = {'name': c.get('name')}
            if c.get('text'):
                entry['text'] = c['text']
                entry['text_plain'] = plain(c['text'], c.get('name'), names.get(ref))
            if c.get('lore'):
                entry['lore'] = plain(c['lore'])
            for key in ('effects', 'modifications'):
                if c.get(key):
                    entry[key] = [c[key][k] for k in sorted(c[key], key=int)]
            entries[cid] = entry
        vo = {l: data['vo'][f'DCG_VO_{l}'] for l in sorted(lines) if f'DCG_VO_{l}' in data.get('vo', {})}
        ui = {k: data['common'][k] for k in UI_TOKENS if k in data['common']}
        out[lang] = {'language': lang, 'cards': by_id(entries), 'voice_lines': vo, 'ui': ui}
    return out


def finalize(card):
    """Internal card -> output record: type name -> commons/card_types id (+ flags)."""
    out = dict(card)
    name = out['type']
    base, flag = TYPE_ALIASES.get(name, (name, None))
    out['type'] = CARD_TYPES.get(base, 0)
    if flag:
        out[flag] = True
    for k in TEXT_FIELDS + ('history',):
        out.pop(k, None)
    return clean(out)


def type_file(record):
    if record['type'] == 0 and record['id'] < 2000:
        return 'default'  # Foundry's board placeholders (slots, random heroes, ...)
    return TYPE_FILES.get(record['type'], 'other')


def write_game(folder, cards, loc, chat_wheel, extra):
    records = {cid: finalize(c) for cid, c in cards.items()}
    write(f'{folder}/cards.json', by_id({cid: {'name': r.get('name'), 'type': r['type']} for cid, r in records.items()}))
    groups = collections.defaultdict(dict)
    for cid, r in records.items():
        groups[type_file(r)][cid] = r
    for name in sorted(set(TYPE_FILES.values()) | {'summons', 'decks', 'strongholds', 'pathing', 'packs'}):
        path = ROOT / folder / f'{name}.json'
        if groups.get(name):
            write(f'{folder}/{name}.json', by_id(groups[name]))
        elif path.exists():
            path.unlink()
    write(f'{folder}/cards_text.json', by_id({cid: {k: c[k] for k in TEXT_FIELDS if k in c}
                                              for cid, c in cards.items() if any(k in c for k in TEXT_FIELDS)}))
    write(f'{folder}/history.json', by_id({cid: c['history'] for cid, c in cards.items() if c.get('history')}))
    write(f'{folder}/chat_wheel.json', by_id({cid: lines for cid, lines in chat_wheel.items() if cid in cards}))
    loc_dir = ROOT / folder / 'localization'
    if loc_dir.exists():
        shutil.rmtree(loc_dir)
    for lang, data in localized(cards, loc, chat_wheel).items():
        write(f'{folder}/localization/{lang}.json', data)
    for name, data in extra.items():
        write(f'{folder}/{name}.json', data)


# --- replay traces --------------------------------------------------------------------------

def traces(P: Paths):
    """Trace tables of the replay parser: ({build: trace type id -> name}, the shared tables)."""
    rp = P.replay_parser
    src = read_text(rp / 'internal/dcg/traces.go')
    data_src = read_text(rp / 'internal/dcg/traces_data.go')
    msgs = read_text(rp / 'internal/dcg/messages.go')

    def go_map(text, var):
        start = text.index(f'var {var} = map[')
        body = text[start:text.index('\n}\n', start)]
        return {int(k): v for k, v in re.findall(r'(\d+):\s*"([^"]+)"', body)}

    classic = go_map(src, 'classicTypeIDs')
    foundry = go_map(src, 'knownTraceTypeIDs2')
    # The parser documents 76 as CardPlayed in Classic and DamageAttempted in Foundry.
    foundry.setdefault(76, 'DamageAttempted')
    # The builds share the numbering except where they disagree (76 and 108); an id one
    # build's table lacks is taken from the other's.
    ids = {build: by_id({i: (own.get(i) or other.get(i)) for i in sorted(set(classic) | set(foundry))})
           for build, own, other in (('classic', classic, foundry), ('foundry', foundry, classic))}
    fields = {}
    for name, body in re.findall(r'"(\w+)":\s*\{([^}]*)\}', data_src[data_src.index('var traceFieldNames'):]):
        fields[name] = {k: v for k, v in re.findall(r'(\d+):\s*"(\w+)"', body)}
    enums = {}
    for build in ('artifact', 'artifact2'):
        proto = rp / 'protos' / build / 'dcg_gamemessages.proto'
        if proto.exists():
            enums['classic' if build == 'artifact' else 'foundry'] = {
                m[1]: {v: k for k, v in re.findall(r'(\w+)\s*=\s*(-?\d+);', m[2])}
                for m in re.finditer(r'enum (\w+) \{([^}]*)\}', proto.read_text())}
    trace_msgs = {}
    proto = rp / 'protos/artifact2/dcg_gamemessages.proto'
    if proto.exists():
        for m in re.finditer(r'message CTraceMsg_(\w+) \{([^}]*)\}', proto.read_text()):
            trace_msgs[m[1]] = {num: f'{typ} {name}' for typ, name, num in
                                re.findall(r'(?:optional|repeated|required)\s+([\w.]+)\s+(\w+)\s*=\s*(\d+)', m[2])}
    return ids, {
        'fields': dict(sorted(fields.items())),
        'messages': dict(sorted(trace_msgs.items())),
        'script_block_types': by_id(go_map(msgs, 'scriptBlockNames')),
        'enums': enums,
    }
