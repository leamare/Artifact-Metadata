"""Readers for the raw game files: VPK archives, Valve KeyValues, localization."""
from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path


class Vpk:
    """Read-only VPK v1/v2 directory archive."""

    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        signature, version, tree_size = struct.unpack_from('<III', self.data)
        if signature != 0x55AA1234 or version not in (1, 2):
            raise ValueError(f'{path}: not a VPK')
        offset = 28 if version == 2 else 12
        self.tree_end = offset + tree_size
        self.entries = {}

        def string():
            nonlocal offset
            end = self.data.index(b'\0', offset, self.tree_end)
            value = self.data[offset:end].decode('utf-8')
            offset = end + 1
            return value

        while (extension := string()):
            while (directory := string()):
                while (name := string()):
                    crc, preload_size, archive, start, size, _ = struct.unpack_from('<IHHIIH', self.data, offset)
                    offset += 18
                    preload = self.data[offset:offset + preload_size]
                    offset += preload_size
                    key = ('' if directory == ' ' else directory + '/') + name
                    key += '' if extension == ' ' else '.' + extension
                    self.entries[key] = (crc, archive, start, size, preload)

    def __contains__(self, key):
        return key in self.entries

    def read(self, key) -> bytes:
        crc, archive, start, size, preload = self.entries[key]
        if archive == 0x7FFF:
            payload = self.data[self.tree_end + start:self.tree_end + start + size]
        else:
            prefix = self.path.name.removesuffix('_dir.vpk')
            with self.path.with_name(f'{prefix}_{archive:03d}.vpk').open('rb') as stream:
                stream.seek(start)
                payload = stream.read(size)
        result = preload + payload
        if zlib.crc32(result) & 0xFFFFFFFF != crc:
            raise ValueError(f'CRC mismatch: {key}')
        return result

    def text(self, key) -> str:
        return decode_text(self.read(key))


def decode_text(raw: bytes) -> str:
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return raw.decode('utf-16')
    return raw.decode('utf-8-sig', errors='replace')


def read_text(path) -> str:
    return decode_text(Path(path).read_bytes())


# --- KeyValues (KV1) ---------------------------------------------------------
# A node is a list of (key, value) pairs; value is a str or a node. Lists keep
# duplicate keys (loot lists repeat them) and order.

_ESCAPES = {'n': '\n', 't': '\t', '"': '"', '\\': '\\'}


def _tokens(text):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in ' \t\r\n':
            i += 1
        elif c == '/' and text.startswith('//', i):
            i = text.find('\n', i)
            i = n if i < 0 else i
        elif c in '{}':
            yield c
            i += 1
        elif c == '[':  # platform conditional like [$WIN32]
            i = text.find(']', i) + 1 or n
        elif c == '"':
            i += 1
            out = []
            while i < n and text[i] != '"':
                if text[i] == '\\' and i + 1 < n:
                    out.append(_ESCAPES.get(text[i + 1], text[i + 1]))
                    i += 2
                else:
                    out.append(text[i])
                    i += 1
            i += 1
            yield ('s', ''.join(out))
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n{}"':
                j += 1
            yield ('s', text[i:j])
            i = j


def parse_kv(text):
    tokens = list(_tokens(text))
    pos = 0

    def block():
        nonlocal pos
        node = []
        while pos < len(tokens):
            tok = tokens[pos]
            if tok == '}':
                pos += 1
                return node
            if tok == '{':  # stray brace
                pos += 1
                continue
            key = tok[1]
            pos += 1
            if pos >= len(tokens):
                break
            nxt = tokens[pos]
            if nxt == '{':
                pos += 1
                node.append((key, block()))
            elif nxt == '}':
                node.append((key, ''))
            else:
                pos += 1
                node.append((key, nxt[1]))
        return node

    return block()


def kv_get(node, key, default=None):
    for k, v in node:
        if k.lower() == key.lower():
            return v
    return default


def kv_dict(node):
    """Convert a node to nested dicts (last duplicate wins)."""
    if isinstance(node, str):
        return node
    return {k: kv_dict(v) for k, v in node}


def kv_leaves(node):
    """All (key, str) pairs below a node, depth first."""
    for k, v in node:
        if isinstance(v, str):
            yield k, v
        else:
            yield from kv_leaves(v)


def load_tokens(path_or_text, is_text=False):
    """Localization file -> {token: text}. Handles both the "lang"/"Tokens"
    layout and flat panorama files."""
    text = path_or_text if is_text else read_text(path_or_text)
    return dict(kv_leaves(parse_kv(text)))


def languages_of(directory: Path, prefix: str):
    """Languages for which <prefix>_<lang>.txt exists in directory."""
    out = []
    for p in sorted(directory.glob(f'{prefix}_*.txt')):
        m = re.fullmatch(re.escape(prefix) + r'_([a-z]+)\.txt', p.name)
        if m:
            out.append(m.group(1))
    return out
