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
    the same function, so it plans with the slower recovery too.
  With season_length, the dynasty goals that count over the season or the contract are sized for it too (as
    MVP05-Plus scales them on PC): in the code, the win-percentage goal's check (wins against X * 486, three
    162-game seasons: the float at 0x805BD03C) and its progress figure (finished seasons x 162, mulli at 0x8054DB74)
    use the season's length, and 40/40 (home runs and steals over 39, 0x8054D274 and 0x8054D27C) becomes the same
    share of the season; the counting targets themselves (wins, home and road wins, team home runs, X home runs by
    Y players, X wins by Y pitchers) are in the game's tuning, datafile.big's datafile.txt (gol tiers 1 to 6):
    goals_datafile() scales those."""
import struct

GAME_ID = b"GV4E"
SEASON_AT = 0x80084514  # li r3,162 ; blr
SAME_OP = {SEASON_AT, 0x8054DB74, 0x8054D274, 0x8054D27C}  # (their immediate is the season's: a re-patch may change it)
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
        if games != 162:
            ff = max(1, round(40 * games / 162))
            out += [(0x805BD03C, 0x43F30000, struct.unpack(">I", struct.pack(">f", 3.0 * games))[0],
                     f"win-percentage goal: checked over 3 x {games} games"),
                    (0x8054DB74, 0x1FCB00A2, 0x1FCB0000 | games, f"win-percentage goal's progress: {games} a season"),
                    (0x8054D274, 0x2C1D0027, 0x2C1D0000 | (ff - 1), f"40/40 goal: {ff} home runs"),
                    (0x8054D27C, 0x2C030027, 0x2C030000 | (ff - 1), f"40/40 goal: {ff} steals")]
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
        elif now == want or (addr in SAME_OP and now & 0xFFFF0000 == want & 0xFFFF0000) or (
                addr == 0x805BD03C and 0x40000000 <= now <= 0x44000000):  # (an earlier length's patch)
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


GOAL_TARGETS = ("WinX@HomeX", "WinX@AwayX", "XHRsforTeamX", "WinXX", "XHRsYplayersX", "XWinsbyYPX")


def goals_text(text, games):
    """datafile.txt with the goal tiers' counting targets sized for a season of that many games (from 162). The
    tiers' line of fields names them; each tier's record keeps every other value."""
    import re
    lines = text.split("\n")
    names = {}
    for ln in lines:
        if ln.startswith("0x6bc2dedf "):  # the gol group's field names (index name;...)
            for part in ln.split(";")[1:]:
                if " " in part:
                    i, n = part.split(" ", 1)
                    names[n] = i
            break
    want = {names[n] for n in GOAL_TARGETS if n in names}
    if len(want) != len(GOAL_TARGETS):
        raise IsoError("the game's tuning doesn't have the dynasty goals where expected")
    changed = 0
    for k, ln in enumerate(lines):
        if not re.match(r"0x[0-9a-f]+ \d+<tier\d+>;", ln):
            continue
        parts = ln.split(";")
        for j, part in enumerate(parts):
            if " " in part and part.split(" ", 1)[0] in want:
                i, v = part.split(" ", 1)
                if v.strip().isdigit() and int(v) > 0:
                    parts[j] = f"{i} {max(1, round(int(v) * games / 162))}"
                    changed += 1
        lines[k] = ";".join(parts)
    if not changed:
        raise IsoError("no dynasty goal tiers in the game's tuning")
    return "\n".join(lines), changed


def goals_datafile(big, games):
    """A datafile.big (the game's own, from the ISO) with its dynasty goals sized for the season: (bytes, targets
    changed). datafile.txt stays compressed as the game had it."""
    import os
    import sys
    inst = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "installer")
    if inst not in sys.path:
        sys.path.insert(0, inst)
    import schedules as S
    entries = S.read_big(big)
    out, n = [], 0
    for name, data in entries:
        if name.lower() == "datafile.txt":
            text = S.unpacked(data).decode("latin-1")
            new, n = goals_text(text, games)
            raw = new.encode("latin-1")
            data = S.refpack(raw) if data[1:2] == b"\xfb" else raw
        out.append((name, data))
    if not n:
        raise IsoError("that datafile.big has no datafile.txt")
    return S.write_big(out), n
