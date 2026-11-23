"""Draw the maskable app icons: a white "U" inside the safe middle of an indigo square.

Standard library only (no image package). Run once: `python scripts/make_icons.py`.
Phones may cut the outer fifth of a maskable icon, so the letter stays in the middle 60 %.
"""

import struct
import zlib
from pathlib import Path

INDIGO = (0x3B, 0x3B, 0x98)
WHITE = (255, 255, 255)


def draw(size):
    rows = []
    # The letter: two bars and a bottom, inside the middle 60 % of the square.
    left, right = size * 0.30, size * 0.70
    top, bottom = size * 0.30, size * 0.70
    bar = size * 0.10
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            inside = left <= x < right and top <= y < bottom
            in_u = inside and (x < left + bar or x >= right - bar or y >= bottom - bar)
            row.extend(WHITE if in_u else INDIGO)
        rows.append(bytes(row))
    return b"".join(rows)


def png(size):
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    pixels = zlib.compress(draw(size), 9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")


if __name__ == "__main__":
    folder = Path(__file__).resolve().parent.parent / "static" / "icons"
    for size in (192, 512):
        (folder / f"icon-maskable-{size}.png").write_bytes(png(size))
