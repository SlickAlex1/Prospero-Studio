#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 SlickAlex (https://github.com/SlickAlex1) - Prospero Studio (unofficial companion for github.com/boykopovar/AnyPS5)
"""Draw prospero/icon.ico: a blue-violet rounded square with a white play symbol.

Pure Python (no image libraries): each size is rendered with 4x4 supersampling and stored
as a PNG entry in the .ico. Run again after changing the design:  python scripts/make_icon.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIZES = (16, 24, 32, 48, 64, 128, 256)
TOP_LEFT, BOTTOM_RIGHT = (37, 99, 235), (124, 58, 237)  # blue-600 -> violet-600


def inside_rounded_square(x: float, y: float, radius: float) -> bool:
    cx = min(max(x, radius), 1 - radius)
    cy = min(max(y, radius), 1 - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2 and 0 <= x <= 1 and 0 <= y <= 1


def inside_play(x: float, y: float) -> bool:
    # Triangle pointing right, optically centred.
    ax, ay, bx, by, cx, cy = 0.38, 0.27, 0.38, 0.73, 0.76, 0.50
    def side(px, py, qx, qy, rx, ry):
        return (px - rx) * (qy - ry) - (qx - rx) * (py - ry)
    d1, d2, d3 = side(x, y, ax, ay, bx, by), side(x, y, bx, by, cx, cy), side(x, y, cx, cy, ax, ay)
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def render(size: int, samples: int = 4) -> bytes:
    rows = []
    step = 1 / (size * samples)
    for py in range(size):
        row = bytearray([0])  # PNG filter type 0
        for px in range(size):
            r = g = b = a = 0.0
            for sy in range(samples):
                for sx in range(samples):
                    x = (px * samples + sx + 0.5) * step
                    y = (py * samples + sy + 0.5) * step
                    if not inside_rounded_square(x, y, 0.22):
                        continue
                    if inside_play(x, y):
                        cr, cg, cb = 255, 255, 255
                    else:
                        t = (x + y) / 2
                        cr = TOP_LEFT[0] + (BOTTOM_RIGHT[0] - TOP_LEFT[0]) * t
                        cg = TOP_LEFT[1] + (BOTTOM_RIGHT[1] - TOP_LEFT[1]) * t
                        cb = TOP_LEFT[2] + (BOTTOM_RIGHT[2] - TOP_LEFT[2]) * t
                    r, g, b, a = r + cr, g + cg, b + cb, a + 1
            n = samples * samples
            if a:
                row += bytes((round(r / a), round(g / a), round(b / a), round(255 * a / n)))
            else:
                row += b"\0\0\0\0"
        rows.append(bytes(row))
    return png(size, b"".join(rows))


def png(size: int, raw: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def ico(images: list[tuple[int, bytes]]) -> bytes:
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, data = b"", b""
    for size, image in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(image), offset + len(data))
        data += image
    return out + entries + data


def main() -> int:
    images = [(size, render(size)) for size in SIZES]
    target = ROOT / "prospero" / "icon.ico"
    target.write_bytes(ico(images))
    (ROOT / "prospero" / "icon.png").write_bytes(images[-1][1])  # for the window icon and README
    print(f"wrote {target} ({target.stat().st_size} bytes, sizes {', '.join(map(str, SIZES))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
