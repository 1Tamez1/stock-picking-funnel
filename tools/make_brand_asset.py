from __future__ import annotations

import struct
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "static" / "assets" / "market-snapshot.png"
WIDTH = 320
HEIGHT = 320


def rgb_at(x: int, y: int) -> tuple[int, int, int]:
    base = 245 - int(32 * (y / HEIGHT))
    green = 126 + int(72 * (x / WIDTH))
    red = 28 + int(34 * (y / HEIGHT))
    blue = 44 + int(22 * (x / WIDTH))

    grid = x % 40 == 0 or y % 40 == 0
    if grid:
        return (210, 222, 216)

    points = [(28, 230), (75, 196), (118, 210), (164, 142), (212, 164), (262, 84), (300, 96)]
    for index in range(len(points) - 1):
        x1, y1 = points[index]
        x2, y2 = points[index + 1]
        if min(x1, x2) - 3 <= x <= max(x1, x2) + 3:
            if x2 != x1:
                target_y = y1 + (y2 - y1) * ((x - x1) / (x2 - x1))
                if abs(y - target_y) <= 4:
                    return (10, 143, 103)

    if 46 <= x <= 72 and 166 <= y <= 248:
        return (20, 125, 138)
    if 104 <= x <= 130 and 132 <= y <= 248:
        return (216, 79, 95)
    if 162 <= x <= 188 and 98 <= y <= 248:
        return (10, 143, 103)
    if 220 <= x <= 246 and 72 <= y <= 248:
        return (185, 133, 5)

    return (base, min(255, base + green // 10), min(255, base + blue // 8))


def chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for y in range(HEIGHT):
        row = bytearray([0])
        for x in range(WIDTH):
            row.extend(rgb_at(x, y))
        rows.append(bytes(row))

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )
    OUT.write_bytes(png)
    print(OUT)


if __name__ == "__main__":
    main()

