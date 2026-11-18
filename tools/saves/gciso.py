"""MVP Baseball 2005 (GameCube, US: GV4E) ISO patches, written into a copy of your ISO's game executable (Start.dol,
found from the disc header). Each patch checks the instructions it replaces first, so a different build of the game is
left alone. For a real GameCube (Swiss, etc.) or Dolphin: no Gecko codes needed.

  season_length(games): the big-league season is that many games long, so a short season goes on to the playoffs
    by itself (no Short Season Advancer). The game asks one function how long a season is (162 for the majors, 144
    AAA, 142 AA, 140 A); its majors' answer, li r3,162 at 0x80084514, becomes li r3,<games>. (The Xbox game's is
    0x19D190, which MVP05-Plus hooks the same way.)
  five_man(): pitchers get half their stamina back a day (MVP05-Plus's "Five-man rotation" pitchers' rest), so a
    starter is ready again after about four days. The game's daily recovery (0x8055A73C; the Xbox game's 0x44A4E0)
    gives back 10 + 15% of the pitcher's stamina rating + a random bonus (up to (X - 70) / 30 * 5), at most the
    rating; the 10 (addi at 0x8055A82C) becomes 5, and its constants 0.15 and 5.0 (0x805FF6C4, 0x805FF6C0, used
    nowhere else) become 0.075 and 2.5. The game's guess at a starter's stamina tomorrow (picking who starts) uses
    the same function, so it plans with the slower recovery too."""
import struct

GAME_ID = b"GV4E"
SEASON_AT = 0x80084514  # li r3,162 ; blr
LI_R3 = 0x38600000


class IsoError(Exception):
    pass


def _dol_sections(dol):
    offs = struct.unpack_from(">18I", dol, 0)
    addrs = struct.unpack_from(">18I", dol, 0x48)
    sizes = struct.unpack_from(">18I", dol, 0x90)
    return [(o, a, s) for o, a, s in zip(offs, addrs, sizes) if s]


def _file_offset(dol_head, addr):
    for o, a, s in _dol_sections(dol_head):
        if a <= addr < a + s:
            return o + addr - a
    raise IsoError(f"{addr:#x} isn't in the game's code")


FIVE_MAN = [(0x8055A82C, 0x3803000A, 0x38030005, "pitchers' rest: 5 a day instead of 10"),
            (0x805FF6C4, 0x3E19999A, 0x3D99999A, "pitchers' rest: 7.5% of the rating instead of 15%"),
            (0x805FF6C0, 0x40A00000, 0x40200000, "pitchers' rest: half the random bonus")]


def patches(games=None, five_man=False):
    """[(address, expected word, new word, what)] for the chosen fixes (games None: the season left as it is)"""
    out = []
    if games is not None:
        if not 2 <= games <= 162:
            raise IsoError("a season is 2 to 162 games")
        out.append((SEASON_AT, LI_R3 | 162, LI_R3 | games, f"the season is {games} games (it ends by itself)"))
    if five_man:
        out += FIVE_MAN
    return out


def _patch(f, base, head, todo_list):
    done, todo = [], []
    for addr, want, new, what in todo_list:
        at = base + _file_offset(head, addr)
        f.seek(at)
        now = struct.unpack(">I", f.read(4))[0]
        if now == new:
            done.append(what + " (already)")
        elif now == want or (addr == SEASON_AT and now & 0xFFFF0000 == LI_R3):
            todo.append((at, new, what))
        else:
            raise IsoError(f"this game code isn't the one these patches are for ({addr:#x}: {now:#010x}); "
                           "nothing was changed")
    for at, new, what in todo:
        f.seek(at)
        f.write(struct.pack(">I", new))
        done.append(what)
    return done


def apply_dol(path, games=None, five_man=False):
    """The same patches on a Start.dol taken out of the ISO (to put back with an ISO tool), in place"""
    with open(path, "r+b") as f:
        head = f.read(0x100)
        if len(head) < 0x100:
            raise IsoError("that isn't a GameCube executable")
        return _patch(f, 0, head, patches(games, five_man))


def check(f):
    """(the executable's offset in the ISO, its header) after checking it's MVP 2005 for the GameCube (US)"""
    f.seek(0)
    head = f.read(0x440)
    if len(head) < 0x440 or head[:4] != GAME_ID:
        raise IsoError("that isn't an MVP Baseball 2005 GameCube ISO (US, GV4E)"
                       + (f": its id is {head[:6].decode('ascii', 'replace')}" if len(head) >= 6 else ""))
    dol_at = struct.unpack_from(">I", head, 0x420)[0]
    f.seek(dol_at)
    dol_head = f.read(0x100)
    if len(dol_head) < 0x100:
        raise IsoError("the ISO is cut short")
    return dol_at, dol_head


def apply(path, games=None, five_man=False):
    """Patches the ISO at path in place (call it on a copy). [what was done, ...]; nothing is written unless every
    patch finds the instructions it expects (or its own, already patched)."""
    with open(path, "r+b") as f:
        dol_at, dol_head = check(f)
        return _patch(f, dol_at, dol_head, patches(games, five_man))
