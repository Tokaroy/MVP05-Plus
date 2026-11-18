"""Made-up memory card images for the tests (no real card is committed)."""
import random
import struct

import gccard as GCC


def gc_card(gcis):
    """A made-up 16 MB Dolphin card holding the .gci files, their blocks out of order (a real card's layout)."""
    B = GCC.BLOCK
    card = bytearray(2048 * B)
    struct.pack_into(">H", card, 0x22, 128)
    free = list(range(5, 2048))
    random.Random(1).shuffle(free)
    dirb, bat = bytearray(b"\xff" * B), bytearray(B)
    for i, g in enumerate(gcis):
        n = struct.unpack_from(">H", g, 0x38)[0]
        bl = [free.pop() for _ in range(n)]
        e = bytearray(g[:64])
        struct.pack_into(">H", e, 0x36, bl[0])
        dirb[64 * i:64 * i + 64] = e
        for k, b in enumerate(bl):
            card[b * B:(b + 1) * B] = g[64 + k * B:64 + (k + 1) * B]
            struct.pack_into(">H", bat, 0xA + 2 * (b - 5), bl[k + 1] if k + 1 < n else 0xFFFF)
    struct.pack_into(">H", dirb, 0x1FFA, 7)
    struct.pack_into(">H", bat, 4, 7)
    struct.pack_into(">HH", dirb, 0x1FFC, *GCC.checksums(dirb, 0, 0x1FFC))  # (as Dolphin writes them)
    struct.pack_into(">HH", bat, 0, *GCC.checksums(bat, 4, B))
    card[2 * B:3 * B], card[3 * B:4 * B] = dirb, bat  # the newer directory in the backup's place, the table first
    return bytes(card)
