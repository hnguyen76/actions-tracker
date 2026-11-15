"""Draw the home-screen icons (gradient square with a white "A") as PNG without any image library.

Usage: python scripts/make_icons.py   -> src/actions_tracker/templates/static/icon-180.png, icon-512.png
"""

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "src" / "actions_tracker" / "templates" / "static"
C1, C2 = (0x4C, 0x8D, 0xFF), (0x7C, 0x5C, 0xFF)  # same gradient as the logo on the page


def _inside(px: float, py: float, poly: list[tuple[float, float]]) -> bool:
    hit = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def _letter_a(u: float, v: float) -> bool:
    """A bold "A" in the unit square (u, v in 0..1, v downwards)."""
    outer = [(0.5, 0.18), (0.80, 0.80), (0.66, 0.80), (0.60, 0.66), (0.40, 0.66), (0.34, 0.80), (0.20, 0.80)]
    hole = [(0.5, 0.36), (0.565, 0.53), (0.435, 0.53)]
    return _inside(u, v, outer) and not _inside(u, v, hole)


def png(size: int) -> bytes:
    rows = []
    ss = 3  # supersampling for smooth edges
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            t = (x + y) / (2 * size)
            bg = [round(C1[k] + (C2[k] - C1[k]) * t) for k in range(3)]
            cover = sum(_letter_a((x + (i + .5) / ss) / size, (y + (j + .5) / ss) / size)
                        for i in range(ss) for j in range(ss)) / (ss * ss)
            row += bytes(round(bg[k] + (255 - bg[k]) * cover) for k in range(3))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (180, 512):
        (OUT / f"icon-{size}.png").write_bytes(png(size))
    print("ok", OUT)
