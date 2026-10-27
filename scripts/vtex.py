"""Decode Source 2 panorama textures (.vtex_c) to PNG.

Covers the formats Artifact's UI and card art use: DXT1, DXT5 (plain or YCoCg-scaled,
as card art is compiled), BC7, RGBA8888/BGRA8888 and embedded PNG/JPEG. Mips are stored
smallest first; only the largest is decoded.
"""
from __future__ import annotations

import io
import struct

from PIL import Image

FORMATS = {1: 'DXT1', 2: 'DXT5', 4: 'RGBA8888', 15: 'JPEG', 16: 'PNG', 17: 'JPEG', 18: 'PNG',
           20: 'BC7', 28: 'BGRA8888'}
BLOCK = {'DXT1': 8, 'DXT5': 16, 'BC7': 16}


def _blocks(data):
    size, _, _, offset, count = struct.unpack_from('<IHHII', data, 0)
    out = {}
    for i in range(count):
        at = 8 + offset + i * 12
        rel, length = struct.unpack_from('<II', data, at + 4)
        out[data[at:at + 4]] = (at + 4 + rel, length)
    return size, out


def _dds(fourcc, payload, w, h):
    if fourcc == 'BC7':
        header = (b'DDS ' + struct.pack('<7I', 124, 0x81007, h, w, len(payload), 0, 1) + b'\0' * 44 +
                  struct.pack('<2I4s5I', 32, 4, b'DX10', 0, 0, 0, 0, 0) + struct.pack('<5I', 0x1000, 0, 0, 0, 0) +
                  struct.pack('<5I', 98, 3, 0, 1, 0))  # DXGI_FORMAT_BC7_UNORM, 2D
    else:
        header = (b'DDS ' + struct.pack('<7I', 124, 0x81007, h, w, len(payload), 0, 1) + b'\0' * 44 +
                  struct.pack('<2I4s5I', 32, 4, fourcc.encode(), 0, 0, 0, 0, 0) + struct.pack('<5I', 0x1000, 0, 0, 0, 0))
    return Image.open(io.BytesIO(header + payload)).convert('RGBA')


def _ycocg(image):
    """Undo YCoCg-DXT5: A=Y, R=Co*s+128, G=Cg*s+128, B=(s-1)*8."""
    import numpy as np
    a = np.asarray(image).astype(np.float32)
    scale = a[..., 2] / 8.0 + 1.0
    co = (a[..., 0] - 128.0) / scale
    cg = (a[..., 1] - 128.0) / scale
    y = a[..., 3]
    r, g, b = y + co - cg, y + cg, y - co - cg
    rgb = np.clip(np.stack([r, g, b, np.full_like(y, 255.0)], -1), 0, 255).astype(np.uint8)
    return Image.fromarray(rgb, 'RGBA')


def decode(data: bytes) -> Image.Image:
    size, blocks = _blocks(data)
    start, _ = blocks[b'DATA']
    w, h, depth, fmt, mips = struct.unpack_from('<HHHBB', data, start + 20)
    kind = FORMATS.get(fmt)
    if kind is None:
        raise ValueError(f'unsupported texture format {fmt}')
    pixels = data[size:]
    if kind in ('PNG', 'JPEG'):
        return Image.open(io.BytesIO(pixels)).convert('RGBA')
    if kind in ('RGBA8888', 'BGRA8888'):
        smaller = sum(max(1, w >> i) * max(1, h >> i) * 4 for i in range(1, mips))
        img = Image.frombytes('RGBA', (w, h), pixels[smaller:smaller + w * h * 4])
        if kind == 'BGRA8888':
            b, g, r, a = img.split()
            img = Image.merge('RGBA', (r, g, b, a))
        return img
    bs = BLOCK[kind]
    smaller = sum(max(1, ((w >> i) + 3) // 4) * max(1, ((h >> i) + 3) // 4) * bs for i in range(1, mips))
    payload = pixels[smaller:smaller + ((w + 3) // 4) * ((h + 3) // 4) * bs]
    img = _dds(kind, payload, w, h)
    if kind == 'DXT5' and b'YCoCg' in data[:size]:
        img = _ycocg(img)
    return img


if __name__ == '__main__':
    import sys
    decode(open(sys.argv[1], 'rb').read()).save(sys.argv[2])
