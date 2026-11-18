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


def checksums(block, start, end):
    """The card's two checksums over block[start:end] (16-bit words: their sum, and the sum of their inverses; 0xFFFF
    stored as 0), as Dolphin and the GameCube make them"""
    a = b = 0
    for (w,) in struct.iter_unpack(">H", block[start:end]):
        a = (a + w) & 0xFFFF
        b = (b + (w ^ 0xFFFF)) & 0xFFFF
    return (0 if a == 0xFFFF else a), (0 if b == 0xFFFF else b)


def _dir_ok(block):
    return checksums(block, 0, 0x1FFC) == struct.unpack_from(">HH", block, 0x1FFC)


def _bat_ok(block):
    return checksums(block, 4, BLOCK) == struct.unpack_from(">HH", block, 0)


def is_card(data):
    """Whether data looks like a GameCube memory card image: its header's size matches its length, or (a card whose
    header says otherwise, or one cut or padded) a directory and a block table whose checksums hold."""
    if len(data) < BLOCK * FIRST_DATA or len(data) % BLOCK:
        return False
    mbits = struct.unpack_from(">H", data, 0x22)[0]
    if mbits in (4, 8, 16, 32, 64, 128) and mbits * 0x20000 == len(data):
        return True
    blk = lambda n: data[n * BLOCK:(n + 1) * BLOCK]
    return (_dir_ok(blk(1)) or _dir_ok(blk(2))) and (_bat_ok(blk(3)) or _bat_ok(blk(4)))


def describe(data):
    """A line on what a file that isn't a card this reads looks like (for the error and the log)"""
    if len(data) < BLOCK * FIRST_DATA:
        return f"{len(data):,} bytes, too small for a memory card"
    mbits = struct.unpack_from(">H", data, 0x22)[0]
    return (f"{len(data):,} bytes, its header says {mbits} Mbit ({mbits * 0x20000:,} bytes); directory checksums "
            f"{'ok' if _dir_ok(data[BLOCK:2 * BLOCK]) or _dir_ok(data[2 * BLOCK:3 * BLOCK]) else 'wrong'}, "
            f"block table {'ok' if _bat_ok(data[3 * BLOCK:4 * BLOCK]) or _bat_ok(data[4 * BLOCK:5 * BLOCK]) else 'wrong'}")


class Card:
    def __init__(self, data):
        if not is_card(data):
            raise GcCardError("not a GameCube memory card image (a Dolphin .raw card)")
        self.data = bytes(data)
        self.blocks = len(data) // BLOCK
        d1, d2 = self._block(1), self._block(2)
        self.dir_block = self._newer(1, 2, _dir_ok(d1), _dir_ok(d2), struct.unpack_from(">h", d1, 0x1FFA)[0],
                                     struct.unpack_from(">h", d2, 0x1FFA)[0])
        b1, b2 = self._block(3), self._block(4)
        self.bat_block = self._newer(3, 4, _bat_ok(b1), _bat_ok(b2), struct.unpack_from(">h", b1, 4)[0],
                                     struct.unpack_from(">h", b2, 4)[0])

    @staticmethod
    def _newer(n1, n2, ok1, ok2, c1, c2):
        """The copy in use: the one whose checksums hold, else the higher update counter (they count up and wrap)"""
        if ok1 != ok2:
            return n1 if ok1 else n2
        return n1 if ((c1 - c2) & 0xFFFF) < 0x8000 else n2

    def games(self):
        """{game code: [file names]} of every save on the card"""
        out = {}
        for e in self.entries():
            out.setdefault(e[:4].decode("ascii", "replace"), []).append(self.name(e))
        return out

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
