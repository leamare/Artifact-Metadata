"""Artifact card-text markup.

The localization files write card text in a small bracket language:

    [g:2[towers]]                 glossary keyword 2, shown as "towers"
    [color:play_effect[...]]      coloured span (play_effect, death_effect, ability, ...)
    [abilityname[Pack Leadership]] ability title (a line of its own)
    [activatedability[...]]       body of an active ability
    [[Town Portal Scroll]]        link to another card
    {s:thisCardName}              this card's name; {s:parentCardName} the owner's
    &#9635; &#9636; &#9637;       attack / armor / health glyphs (Foundry)
    &#9632;                       cooldown marker in "Active &#9632;4:" (dropped)
    <br>, <BR/>                   line breaks

parse() turns text into a tree, plain() into readable text.
"""
from __future__ import annotations

import html
import re

GLYPHS = {
    '&#9635;': 'Attack', '&#9636;': 'Armor', '&#9637;': 'Health',
    '&#9632;': '', '&#9633;': '', '&#9634;': '', '&#9640;': '',
}


def parse(text):
    """-> list of nodes: str, or (tag, children). tag '' = card link."""
    pos = 0
    n = len(text)

    def seq(stop_at_close):
        nonlocal pos
        out, buf = [], []
        while pos < n:
            c = text[pos]
            if c == ']' and stop_at_close:
                break
            if c == '[':
                m = re.match(r'\[([a-z_]*(?::[A-Za-z0-9_]+)?)\[', text[pos:])
                if m:
                    if buf:
                        out.append(''.join(buf))
                        buf = []
                    tag = m.group(1)
                    pos += m.end()
                    children = seq(True)
                    # consume "]]"
                    if text.startswith(']]', pos):
                        pos += 2
                    elif pos < n and text[pos] == ']':
                        pos += 1
                    out.append((tag, children))
                    continue
            buf.append(c)
            pos += 1
        if buf:
            out.append(''.join(buf))
        return out

    return seq(False)


def walk(nodes):
    for node in nodes:
        yield node
        if isinstance(node, tuple):
            yield from walk(node[1])


def keyword_ids(text):
    """Glossary ids referenced by [g:N[...]] -> {id: shown word}."""
    out = {}
    for node in walk(parse(text or '')):
        if isinstance(node, tuple) and node[0].startswith('g:'):
            out.setdefault(int(node[0][2:]), plain_nodes(node[1]))
    return out


def card_links(text):
    """Names linked with [[Name]]."""
    return [plain_nodes(node[1]) for node in walk(parse(text or ''))
            if isinstance(node, tuple) and node[0] == '']


def ability_names(text):
    return [plain_nodes(node[1]) for node in walk(parse(text or ''))
            if isinstance(node, tuple) and node[0] == 'abilityname']


def plain_nodes(nodes, names=None, block_newline=True):
    names = names or {}
    out = []
    for node in nodes:
        if isinstance(node, str):
            out.append(node)
            continue
        tag, children = node
        inner = plain_nodes(children, names, block_newline)
        if tag == 'abilityname':
            out.append(inner + ('\n' if block_newline else ': '))
        else:
            out.append(inner)
    return ''.join(out)


def plain(text, this_name=None, parent_name=None):
    """Readable text: markup removed, names substituted, breaks as newlines."""
    if not text:
        return ''
    t = text
    for glyph, word in GLYPHS.items():
        t = t.replace(glyph, (' ' + word) if word else '')
    t = plain_nodes(parse(t))
    if this_name:
        t = t.replace('{s:thisCardName}', this_name)
    if parent_name:
        t = t.replace('{s:parentCardName}', parent_name)
    t = re.sub(r'<br\s*/?>', '\n', t, flags=re.I)
    t = re.sub(r'<[^>]+>', '', t)
    t = html.unescape(t)
    t = re.sub(r'\(\s*\)', '', t)
    t = re.sub(r'[ \t]+', ' ', t)
    t = re.sub(r' *\n *', '\n', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    t = re.sub(r' +([.,:;])', r'\1', t)
    return t.strip()


# --- Artifact deck codes ("ADC...") ------------------------------------------

import base64


def decode_deck(code):
    """Valve's deck code format (ArtifactDeckCode) -> {heroes, cards, name}."""
    if not code.startswith('ADC'):
        raise ValueError('not a deck code')
    s = code[3:].replace('-', '/').replace('_', '=')
    data = base64.b64decode(s + '=' * (-len(s) % 4))
    pos = 0

    def chunk(value, bits, shift, out):
        cont = 1 << bits
        out[0] |= (value & (cont - 1)) << shift
        return (value & cont) != 0

    def varint(base, base_bits, end):
        nonlocal pos
        out = [0]
        shift = 0
        if base_bits == 0 or chunk(base, base_bits, shift, out):
            shift += base_bits
            while True:
                if pos > end:
                    raise ValueError('truncated deck')
                b = data[pos]
                pos += 1
                if not chunk(b, 7, shift, out):
                    break
                shift += 7
        return out[0]

    def card(end, prev):
        nonlocal pos
        header = data[pos]
        pos += 1
        extended = (header >> 6) == 3
        delta = varint(header, 5, end)
        cid = prev + delta
        count = varint(0, 0, end) if extended else (header >> 6) + 1
        return cid, count

    version_heroes = data[pos]
    pos += 1
    version = version_heroes >> 4
    if version not in (1, 2):
        raise ValueError(f'deck version {version}')
    checksum = data[pos]
    pos += 1
    name_len = 0
    if version > 1:
        name_len = data[pos]
        pos += 1
    total_card_bytes = len(data) - name_len
    if sum(data[pos:total_card_bytes]) & 0xFF != checksum:
        raise ValueError('deck checksum mismatch')
    nheroes = varint(version_heroes, 3, total_card_bytes - 1)
    heroes, prev = [], 0
    for _ in range(nheroes):
        cid, turn = card(total_card_bytes - 1, prev)
        prev = cid
        heroes.append({'card_id': cid, 'turn': turn})
    cards, prev = [], 0
    while pos < total_card_bytes:
        cid, count = card(len(data) - 1, prev)
        prev = cid
        cards.append({'card_id': cid, 'count': count})
    name = data[total_card_bytes:].decode('utf-8', errors='replace') if name_len else ''
    return {'name': re.sub(r'<[^>]+>', '', name), 'heroes': heroes, 'cards': cards}
