"""GameCube memory card images (Dolphin's .raw cards, MemoryCardA.USA.raw and the like): the saves on them read out as
.gci files, and a save's data replaced by one of the same size in a copy of the card (replace).

The card is 8 KB blocks: 0 the card's header (its size in megabits at 0x22), 1 and 2 the directory and its backup,
3 and 4 the block table and its backup (the copy with the higher update counter is the one in use: the directory's at
0x1FFA, the table's at 4). The directory holds 127 entries of 64 bytes (all 0xFF when empty): game code, maker,
file name at 8, first block at 0x36, block count at 0x38. The table's map from 0xA gives, for block 5 on, the next
block of the file (0xFFFF at its last). A .gci is a file's directory entry followed by its blocks in order; the
blocks hold no checksum of the card's own, so replacing a file's data leaves the directory and the table as they
were.
"""
import struct

BLOCK = 0x2000
ENTRY = 64
FIRST_DATA = 5


class GcCardError(Exception):
    pass


def is_card(data):
    """Whether data looks like a GameCube memory card image (its header's size matches its length)."""
    if len(data) < BLOCK * FIRST_DATA or len(data) % BLOCK:
        return False
    mbits = struct.unpack_from(">H", data, 0x22)[0]
    return mbits in (4, 8, 16, 32, 64, 128) and mbits * 0x20000 == len(data)


class Card:
    def __init__(self, data):
        if not is_card(data):
            raise GcCardError("not a GameCube memory card image (a Dolphin .raw card)")
        self.data = bytes(data)
        self.blocks = len(data) // BLOCK
        d1, d2 = self._block(1), self._block(2)
        self.dir_block = 1 if struct.unpack_from(">H", d1, 0x1FFA)[0] >= struct.unpack_from(">H", d2, 0x1FFA)[0] else 2
        b1, b2 = self._block(3), self._block(4)
        self.bat_block = 3 if struct.unpack_from(">H", b1, 4)[0] >= struct.unpack_from(">H", b2, 4)[0] else 4

    def _block(self, n):
        return self.data[n * BLOCK:(n + 1) * BLOCK]

    def entries(self):
        """[(entry bytes)] of the files on the card."""
        d = self._block(self.dir_block)
        out = []
        for i in range(127):
            e = d[i * ENTRY:(i + 1) * ENTRY]
            if e[:4] != b"\xff\xff\xff\xff":
                out.append(e)
        return out

    def chain(self, entry):
        first, count = struct.unpack_from(">HH", entry, 0x36)
        bat = self._block(self.bat_block)
        out, b = [], first
        while True:
            if not FIRST_DATA <= b < self.blocks or b in out:
                raise GcCardError("the card's block table is damaged")
            out.append(b)
            if len(out) == count:
                return out
            b = struct.unpack_from(">H", bat, 0xA + 2 * (b - FIRST_DATA))[0]
            if b == 0xFFFF:
                raise GcCardError("a file on the card is cut short")

    @staticmethod
    def name(entry):
        return entry[8:0x28].split(b"\0")[0].decode("ascii", "replace")

    def files(self, game=b"GV4E"):
        """{file name: .gci bytes} of the card's saves of that game (MVP Baseball 2005's by default)."""
        out = {}
        for e in self.entries():
            if game is None or e[:4] == game:
                out[self.name(e)] = e + b"".join(self._block(b) for b in self.chain(e))
        return out

    def replace(self, name, gci):
        """A copy of the card with the file named name's blocks replaced by those of gci (a .gci of the same number
        of blocks; the card's directory entry for it is kept)."""
        for e in self.entries():
            if e[:4] == gci[:4] and self.name(e) == name:
                break
        else:
            raise GcCardError(f"{name} isn't on the card")
        blocks = self.chain(e)
        body = gci[ENTRY:]
        if len(body) != len(blocks) * BLOCK:
            raise GcCardError(f"{name} on the card is {len(blocks)} blocks, the new save {len(body) / BLOCK:g}")
        out = bytearray(self.data)
        for k, b in enumerate(blocks):
            out[b * BLOCK:(b + 1) * BLOCK] = body[k * BLOCK:(k + 1) * BLOCK]
        if Card(bytes(out)).files(gci[:4]).get(name, b"")[ENTRY:] != body:
            raise GcCardError("the save didn't read back from the card")
        return bytes(out)
