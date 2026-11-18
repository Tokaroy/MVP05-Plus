"""League News: a dynasty or owner mode save read as a newspaper, written as one HTML page for the browser.

What it reads (FORMAT_NOTES 3.2, 3.4, 3.5):
  the save     standings (post-roster table 0: [W][L] and [W][L] again per team, the record the sum of the two;
               checked against the schedule's results), the MLB schedule (date, both teams, runs, hits; the 5-bit
               field is the last inning's number, from 0, once a game is played), the last 30 trades, 60 roster
               moves and 32 injuries, the user's team (marker 4)
  your game    assets/data/database/database.big (as the Player of the Day reads it): names (the save's player keys
               are the database's ids; players the dynasty made itself have none there), each player's star power
               (0-4), salary (in $100,000s) and top prospect flag; team.dat's cities, names, leagues and divisions;
               org.dat's franchises and their farm teams

Nothing is written to the save. The headlines are ranked by a score: how big the players are x how much the teams'
places in the standings make it matter x what kind of news it is x how recent (WEIGHTS, to tune).
"""
import collections
import datetime
import html
import math
import os
import re
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
MARKER = b"\x0d\xf0\xef\xbe"
POST_ROSTER_KEY = b"\x6a\xbc\x3d\x69"
SCHED_CAPS = (2442, 2172, 2140, 2112)
DAY0 = datetime.date(1948, 1, 1)
DIVISIONS = ("AL West", "AL Central", "AL East", "NL West", "NL Central", "NL East")

# how much each kind of news weighs before the players, teams and days are counted in
WEIGHTS = dict(
    milestone=1.6,      # a career mark passed since the last edition, x its size
    series_won=4.0,     # a playoff series won (the World Series x1.5)
    trade=1.0,          # x the players on both sides
    trade_minors=0.25,  # a trade between two farm teams
    injury=0.8,         # x the player
    callup=0.45,        # a player sent up to a big-league club, x the player
    senddown=0.3,       # sent to a farm team
    no_hitter=2.2,
    long_game=0.6,      # 13 innings or more
    blowout=0.45,       # won by 10 or more
    streak=0.5,         # + 0.08 a game past 5
    first_place=0.9,    # a new division leader since the last day of games
    your_team=1.6,      # x anything about your team
    fade_days=14.0,     # news loses about two thirds of its weight in this many days
)


class NewsError(Exception):
    pass


LOC = ("assets", "data", "feeng.loc")
LOGOS = ("assets", "data", "frontend", "logos.big")  # l000.xsh ... : a team's 7 pictures, in the franchises' order


def _dxt3(data, w, h):
    """RGBA bytes from DXT3 blocks (SHPX picture kind 0x61): 8 bytes of 4-bit alpha, then a DXT1 colour block."""
    out = bytearray(w * h * 4)
    p = 0
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            blk = data[p:p + 16]
            p += 16
            c0, c1, idx = struct.unpack_from("<HHI", blk, 8)
            cs = []
            for c in (c0, c1):
                cs.append(((c >> 11 & 31) * 255 // 31, (c >> 5 & 63) * 255 // 63, (c & 31) * 255 // 31))
            cs += [tuple((2 * a + b) // 3 for a, b in zip(cs[0], cs[1])), tuple((a + 2 * b) // 3 for a, b in zip(cs[0], cs[1]))]
            for i in range(16):
                x, y = bx + i % 4, by + i // 4
                if x < w and y < h:
                    a = (blk[i // 2] >> (4 * (i & 1)) & 15) * 17
                    out[(y * w + x) * 4:(y * w + x) * 4 + 4] = bytes(cs[idx >> (2 * i) & 3] + (a,))
    return bytes(out)
# the injury kinds' text ids, in kind order (0 none ... 48, 49 a suspension): the table default.xbe's 0x1E03A0 builds
# (19700.. in order, but 23 "a bruised ankle" from 23753, and 49 "suspension" 17990)
INJURY_TEXT = [None] + list(range(19700, 19722)) + [23753] + list(range(19722, 19747)) + [17990]


def read_loc(data):
    """{text id: text} from an EA .loc file: LOCH, LOCI (count, then (id u16, index u16) pairs), LOCL (count, offsets
    from its start, UTF-16 strings)."""
    sec, o = {}, 0
    while o + 8 <= len(data):
        size = struct.unpack_from("<I", data, o + 4)[0]
        if size < 8:
            break
        sec[data[o:o + 4]] = data[o:o + size]
        o += size
    if b"LOCI" not in sec or b"LOCL" not in sec:
        raise NewsError("the game's text file isn't laid out as expected")
    li, ll = sec[b"LOCI"], sec[b"LOCL"]
    ids = [struct.unpack_from("<HH", li, 16 + 4 * i) for i in range(struct.unpack_from("<I", li, 8)[0])]
    texts = []
    for i in range(struct.unpack_from("<I", ll, 12)[0]):
        a = e = struct.unpack_from("<I", ll, 16 + 4 * i)[0]
        while ll[e:e + 2] not in (b"\0\0", b""):
            e += 2
        texts.append(ll[a:e].decode("utf-16-le", "replace"))
    return {i: texts[x] for i, x in ids if x < len(texts)}


def day(n):
    return DAY0 + datetime.timedelta(days=n - 1)


# ---- your game's database --------------------------------------------------------------------------------------
class Database:
    """Names and teams from the installed game's database.big (nothing of EA's is shipped)."""

    def __init__(self, root):
        import sys
        inst = os.path.join(os.path.dirname(HERE), "installer")
        if inst not in sys.path:
            sys.path.insert(0, inst)
        import potd
        path = os.path.join(root, *potd.DB)
        if not os.path.isfile(path):
            raise NewsError("the game isn't installed here (no database.big): League News reads names from it")
        self.root = root
        with open(path, "rb") as f:
            d = potd._big_dir(f)

            def rows(name):
                off, size = d[name]
                f.seek(off)
                text = potd._unpack(f.read(size)).decode("latin-1")
                return {int(k, 16) & 0xFFFFFFFF: v for k, v in potd._rows(text).items()}
            self.players, self.teams, orgs = rows("attrib.dat"), rows("team.dat"), rows("org.dat")
            # the 2005 rosters: a player's team when the save's own news doesn't say where he went
            team_of = {int(r[1], 16) & 0xFFFFFFFF: int(r[0], 16) & 0xFFFFFFFF
                       for r in rows("roster.dat").values() if r.get(0) and r.get(1)}
        self.franchises = sorted((k for k, v in orgs.items() if v.get(5) == "1"),
                                 key=lambda k: int(self.teams.get(k, {}).get(6, 99) or 99))
        self.injuries = {}  # kind -> "a pulled hamstring": from the game's text file, when it's there
        try:
            with open(os.path.join(root, *LOC), "rb") as f:
                text = read_loc(f.read())
            self.injuries = {k: text[t] for k, t in enumerate(INJURY_TEXT) if t in text}
        except (OSError, NewsError, struct.error):
            pass
        self.org_of, self.levels = {}, {}
        for k in self.franchises:
            self.org_of[k] = k
            for c, lv in ((2, "AAA"), (3, "AA"), (4, "A")):
                v = orgs[k].get(c)  # (org.dat's team ids are written in decimal)
                if v and v.isdigit() and int(v):
                    self.org_of[int(v)] = k
                    self.levels[int(v)] = lv
        # (not the All-Star, Legends or Heroes teams: a club's or one of its farm teams')
        self.team_of = {p: t for p, t in team_of.items() if t in self.org_of}

    def name(self, key):
        p = self.players.get(key)
        return " ".join(f"{p.get(0, '')} {p.get(1, '')}".split()) if p else None

    def short(self, key):
        return self.teams.get(key, {}).get(3) or "?"

    def club(self, key):
        t = self.teams.get(key, {})
        return t.get(2) or t.get(1) or "?"

    def city(self, key):
        return self.teams.get(key, {}).get(1) or "?"

    def logo(self, key, big=False):
        """The team's logo from the game's logos.big, as a data: URL of a PNG (64 or 128 pixels), or "" """
        cache = self.__dict__.setdefault("_logos", {})
        if (key, big) in cache:
            return cache[(key, big)]
        url = ""
        try:
            import base64
            import io
            import potd
            from PIL import Image
            i = self.franchises.index(key)
            with open(os.path.join(self.root, *LOGOS), "rb") as f:
                off, size = potd._big_dir(f)[f"l{i:03d}.xsh"]
                f.seek(off)
                u = potd._unpack(f.read(size))
            for n in range(struct.unpack_from("<I", u, 8)[0]):
                if u[16 + 8 * n:17 + 8 * n] == (b"a" if big else b"i"):
                    o = struct.unpack_from("<I", u, 20 + 8 * n)[0]
                    w, h = struct.unpack_from("<HH", u, o + 4)
                    if u[o] == 0x61:
                        buf = io.BytesIO()
                        im = Image.frombytes("RGBA", (w, h), _dxt3(u[o + 16:], w, h))
                        if big:  # (the game's 128 pixels, resampled to 192 so the browser shrinks it, not stretches)
                            im = im.resize((w * 3 // 2, h * 3 // 2), Image.LANCZOS)
                        kind = "png"
                        if big:  # (WebP keeps the page small; PNG when this Pillow can't write it)
                            try:
                                im.save(buf, "WEBP", quality=90, method=4)
                                kind = "webp"
                            except (OSError, KeyError, ValueError):
                                buf = io.BytesIO()
                        if kind == "png":
                            im.save(buf, "PNG", optimize=True)
                        url = f"data:image/{kind};base64," + base64.b64encode(buf.getvalue()).decode()
                    break
        except Exception:  # (no logos, or a picture this doesn't read: the page goes without)
            url = ""
        cache[(key, big)] = url
        return url

    def badge(self):
        """The game's own badge (the MVP Baseball 2005 title image in your default.xbe), as a data: URL, or "" """
        if "_badge" not in self.__dict__:
            self._badge = ""
            try:
                import base64
                import io
                import title_icon
                with open(os.path.join(self.root, "assets", "default.xbe"), "rb") as f:
                    im = title_icon.title_image(f.read())
                buf = io.BytesIO()
                im.save(buf, "PNG", optimize=True)
                self._badge = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
            except Exception:  # (no disc's xbe here: the header goes without)
                pass
        return self._badge

    def team_at(self, i):
        """The team in roster block i of a save (and a history row's team byte): the database's teams in their art
        ids' order, the 30 franchises first (checked on the KCR dynasty's rosters)."""
        if "_by_art" not in self.__dict__:
            self._by_art = sorted(self.teams, key=lambda k: int(self.teams[k].get(6, 999) or 999))
        return self._by_art[i] if 0 <= i < len(self._by_art) else None

    def injury(self, kind):
        """The injury's name (from the game's text, when it's read), or "" """
        return self.injuries.get(kind, "")

    def full(self, key):
        """ "Kansas City Royals" """
        t = self.teams.get(key, {})
        return " ".join(f"{t.get(1, '')} {t.get(2, '')}".split()) or "?"

    def level(self, key):
        """AAA, AA, A for a farm team, "" for a big-league club."""
        org = self.org_of.get(key)
        return "" if org in (None, key) else self.levels.get(key, "")

    def farm(self, key):
        """ "Omaha (AAA)" for a farm team, the full name for a big-league club."""
        lv = self.level(key)
        return f"{self.city(key)} ({lv})" if lv else self.full(key)

    def named(self, key):
        """ "the Omaha Royals (Kansas City Royals, AAA)", "the Kansas City Royals" """
        lv = self.level(key)
        return f"the {self.full(key)}" + (f" ({self.full(self.org_of[key])}, {lv})" if lv else "")

    def tag(self, key):
        """ "KC" for a big-league club, "Omaha, AAA" for a farm team """
        lv = self.level(key)
        return f"{self.city(key)}, {lv}" if lv else self.short(key)

    def pos(self, key):
        """RHP, LHP, C, 1B ... OF, DH, or "" when the database doesn't have him."""
        p = self.players.get(key)
        if not p:
            return ""
        code = int(p.get(5) or -1)
        if code in (0, 10):
            return "LHP" if p.get(4) == "1" else "RHP"
        return {1: "C", 2: "1B", 3: "2B", 4: "3B", 5: "SS", 6: "OF", 7: "OF", 8: "OF", 9: "DH"}.get(code, "")

    def importance(self, key):
        """0..1.3: star power, salary and top prospect flag (a player the dynasty made: 0.15)."""
        p = self.players.get(key)
        if not p:
            return 0.15
        star = int(p.get(42) or 0) / 4
        pay = min(int(p.get(40) or 0) / 150, 1)
        return 0.1 + 0.55 * star + 0.35 * pay + 0.3 * int(p.get(43) or 0)

    def age(self, key, ref):
        """His age on the date ref (from the birth date, column 45: days from 1948-01-01), or None"""
        p = self.players.get(key)
        try:
            born = DAY0 + datetime.timedelta(days=int(p.get(45) or 0)) if p else None
        except (TypeError, ValueError):
            return None
        if not p or born == DAY0:
            return None
        return ref.year - born.year - ((ref.month, ref.day) < (born.month, born.day))

    def salary(self, key):
        p = self.players.get(key)
        return int(p.get(40) or 0) * 100_000 if p else 0


# ---- the save ---------------------------------------------------------------------------------------------------
def _wire(x, end):
    """The last 30 trades (each side: a team and the players it gave up) and 60 roster moves, after the schedules"""
    tc, mc = struct.unpack_from("<II", x, end)
    if tc > 30 or mc > 60:
        raise NewsError("this save's trades aren't where they should be")
    trades = []
    for i in range(tc):
        r = x[end + 12 + 42 * i:end + 54 + 42 * i]
        sides = []
        for s in (0, 20):
            keys = struct.unpack_from("<3I", r, s)
            sides.append(dict(team=struct.unpack_from("<I", r, s + 16)[0], players=list(keys[:min(r[s + 12], 3)])))
        trades.append(dict(day=struct.unpack_from("<H", r, 40)[0], sides=sides))
    moves = [dict(zip(("player", "team", "day"), struct.unpack_from("<IIH", x, end + 1272 + 10 * i)))
             for i in range(mc)]
    return trades, moves


def read_wire(data):
    """Only what the transactions need from a save (quick, for the game's backups): dict(name, kind, user, last
    (the newest played game's day), trades, moves)."""
    name, kind, x = _payload(data)
    marks = [m.start() for m in re.finditer(re.escape(MARKER), x)]
    if len(marks) < 6:
        raise NewsError("this save's sections aren't where they should be")
    p = marks[2] + 4
    last = 0
    for i in range(min(struct.unpack_from("<I", x, p)[0], SCHED_CAPS[0])):
        dn, bf = struct.unpack_from("<HH", x, p + 4 + 28 * i)
        if bf >> 11:
            last = max(last, dn)
    trades, moves = _wire(x, p + 16 + 28 * sum(SCHED_CAPS))
    user = struct.unpack_from("<I", x, marks[len(marks) - 3] + 8)[0] if len(marks) in (7, 9) else None
    return dict(name=name, kind=kind, user=user, last=last, trades=trades, moves=moves)


def with_backups(root, save):
    """save, its trades and roster moves joined by the ones in the game's own backups of it (save backups/<time>/E/
    UDATA/45410056/<its folder>: the game copies the saves each time it starts, keeping the newest 30), so the
    transactions go back further than the save's own 30 and 60. A backup counts when it's the same dynasty: the
    same folder (name and kind), the same club and no further on. save["from_backups"]: how many were read."""
    import saves05 as S5
    base = os.path.join(root, "save backups")
    sid = S5.folder_id(save["name"], save["kind"])
    newest = max((g["day"] for g in save["games"] if g["played"]), default=None)
    # each trade once (its day and everyone in it, whichever side a copy lists first), each move once (who, where,
    # when): the save's own first, then what only the backups have
    seen_t, seen_m, trades, moves, used = set(), set(), [], [], 0

    def take(b):
        for t in b["trades"]:
            key = (t["day"], tuple(sorted(k for sd in t["sides"] for k in sd["players"])))
            if key not in seen_t:
                seen_t.add(key)
                trades.append(t)
        for m in b["moves"]:
            key = (m["player"], m["team"], m["day"])
            if key not in seen_m:
                seen_m.add(key)
                moves.append(m)
    take(save)
    prev = None  # the newest backup from before the newest game: the "previous edition"
    try:
        stamps = sorted(os.listdir(base))
    except OSError:
        stamps = []
    for stamp in stamps:
        f = os.path.join(base, stamp, "E", "UDATA", "45410056", sid, "data.dat")
        try:
            with open(f, "rb") as fh:
                b = read_wire(fh.read())
        except (OSError, NewsError, struct.error):
            continue
        if b["user"] != save["user"] or b["kind"] != save["kind"] or (newest and b["last"] > newest):
            continue
        used += 1
        take(b)
        if newest and b["last"] < newest and (prev is None or b["last"] >= prev[0]):
            prev = (b["last"], f)
    out = dict(save, trades=trades, moves=moves, from_backups=used, prev=None)
    if prev:
        try:
            with open(prev[1], "rb") as fh:
                out["prev"] = read_save(fh.read())
        except (OSError, NewsError, struct.error):
            pass
    return out


def _payload(data):
    import sys
    lib = os.path.join(HERE, "mvp05", "lib")
    if lib not in sys.path:
        sys.path.insert(0, lib)
    import containers as C
    try:
        m = C.parse_xbox(data)
    except Exception as e:
        raise NewsError(f"that isn't an MVP 2005 Xbox save ({e})")
    if m.get("typ") not in ("Dynasty", "Owner Mode"):
        import dynasty05 as DY
        raise NewsError(f"that's {DY.a_kind(m.get('typ'))} save: League News reads dynasties and owner modes")
    return m["name"], m["typ"], m["payload"]


def in_postseason(save):
    """The schedule holds only the playoff games then (41 at most: two rounds of 5 and two of 7, four series each
    for the first round): a season's shortest is 12 games a team, 180 in all. The standings then are the playoffs'
    records (0-0 before the first game)."""
    return 0 < len(save["games"]) <= 41


def read_save(data):
    """{name, kind, records {index: (W, L)}, games [...], trades, moves, injuries, user} from an Xbox save."""
    name, kind, x = _payload(data)
    marks = [m.start() for m in re.finditer(re.escape(MARKER), x)]
    if len(marks) < 6:
        raise NewsError("this save's sections aren't where they should be")
    q = x.find(POST_ROSTER_KEY, 0x12000)
    if q < 0:
        raise NewsError("couldn't find the standings in this save")
    records = {i: (x[q + 4 + 4 * i] + x[q + 6 + 4 * i], x[q + 5 + 4 * i] + x[q + 7 + 4 * i]) for i in range(30)}
    p = marks[2] + 4
    n = struct.unpack_from("<I", x, p)[0]
    if n > SCHED_CAPS[0]:
        raise NewsError("this save's schedule isn't laid out as expected")
    games = []
    for i in range(n):
        e = x[p + 4 + 28 * i:p + 32 + 28 * i]
        dn, bf = struct.unpack_from("<HH", e, 0)
        # the home team first (+4, its line +8..+15), the visitors second (+16, +20..+27): checked, a home team ahead
        # after the top of the 9th has no bottom of it in every game (270 of 270), and the playoffs' higher seeds host
        g = dict(day=dn, home=struct.unpack_from("<I", e, 4)[0], away=struct.unpack_from("<I", e, 16)[0],
                 played=bool(bf >> 11), innings=(bf >> 11) + 1 if bf >> 11 else 0)
        if g["home"] == g["away"]:  # a playoff game a series didn't need (both teams 0, marked played)
            continue
        if g["played"]:
            g.update(hr=e[8], hh=e[9], ar=e[20], ah=e[21], he=e[10] & 15, ae=e[22] & 15,
                     hline=_line(e[10:15]), aline=_line(e[22:27]))
        games.append(g)
    end = p + 16 + 28 * sum(SCHED_CAPS)
    trades, moves = _wire(x, end)
    # the game's own news list (32 events, FORMAT_NOTES 3.5): kept for when its kinds are known
    feed = []
    for i in range(min(struct.unpack_from("<I", x, end + 1872)[0], 32)):
        k, a, _, w, d1, _ = struct.unpack_from("<IIIIHH", x, end + 1876 + 20 * i)
        feed.append(dict(key=k, value=a, kind=(w >> 2) & 0x3F, word=w, day=d1))
    names, hurt, contracts = _players(x)
    rosters = _rosters(x)
    history = _history(x, marks)
    careers = _careers(x)
    user = None
    if len(marks) in (7, 9):  # the user section: marker 4 in a dynasty, 6 in an owner mode (budget05 reads it too)
        user = struct.unpack_from("<I", x, marks[len(marks) - 3] + 8)[0]
    return dict(name=name, kind=kind, records=records, games=games, trades=trades, moves=moves, hurt=hurt,
                names=names, rosters=rosters, feed=feed, user=user, history=history,
                careers=careers, contracts=contracts)


def _line(b):
    """A side's runs by inning (FORMAT_NOTES 3.4): nine slots, innings 1-8 and then the last inning played (the 9th, or
    the last of an extra-inning game; the innings between are the total less all nine). The high nibble of the first
    byte (its low nibble is the errors), then two a byte, low nibble first (bitfields on the little-endian Xbox; the
    GameCube's are swapped). Checked: every extra-inning game is tied going into its last inning."""
    return [b[0] >> 4] + [v for c in b[1:5] for v in (c & 15, c >> 4)]


def _bits(w, widths):
    out, sh = [], 0
    for b in widths:
        out.append((w >> sh) & ((1 << b) - 1))
        sh += b
    return out


def _history(x, marks):
    """Each player's season rows (FORMAT_NOTES 3.6: the player history, marker 5 in a dynasty): {key: [row]}, a row
    {year, team (franchise index), batter, stats}. This season's row is the season so far, as the game's League
    Leaders show it (checked against them on the KCR dynasty):
      batter   word 0 (10,8,7,7): AB, G, SB, CS;  word 1 (9,8,8,7): H, RBI, R, HR;  word 2 (9,8,8,7): TB, SO,
               BB (with HBP), SF (the dynasty's seasons only: the real ones before 2005 have zeros there)
      pitcher  word 0 (8,8,9,7): ER, BB, SO, G;  word 1 (9,2,6,6,9): IP, thirds, W, L, -;  word 2 (7,25): SV"""
    for i in range(len(marks) - 1):  # (the marker whose groups run exactly to the next one)
        p = marks[i] + 4
        try:
            n = struct.unpack_from("<I", x, p)[0]
            if not 100 < n < 4000:
                continue
            q, out = p + 4, {}
            for _ in range(n):
                k, c = struct.unpack_from("<IB", x, q)
                rows = []
                for j in range(c):
                    yr, team, flags = struct.unpack_from("<HBB", x, q + 9 + 20 * j)
                    w = struct.unpack_from("<3I", x, q + 13 + 20 * j)
                    if flags & 3 == 1:
                        a, b, c2 = _bits(w[0], (10, 8, 7, 7)), _bits(w[1], (9, 8, 8, 7)), _bits(w[2], (9, 8, 8, 7))
                        st = dict(ab=a[0], g=a[1], sb=a[2], cs=a[3], h=b[0], rbi=b[1], r=b[2], hr=b[3], tb=c2[0],
                                  so=c2[1], bb=c2[2], sf=c2[3])
                    else:
                        a, b, c2 = _bits(w[0], (8, 8, 9, 7)), _bits(w[1], (9, 2, 6, 6, 9)), _bits(w[2], (7, 25))
                        st = dict(er=a[0], bb=a[1], so=a[2], g=a[3], outs=3 * b[0] + b[1], w=b[2], l=b[3], sv=c2[0])
                    rows.append(dict(year=yr, team=team, batter=flags & 3 == 1, stats=st))
                out[k] = rows
                q += 5 + 20 * c
            if q == marks[i + 1]:
                return out
        except struct.error:
            continue
    return {}


def obp(s):
    d = s["ab"] + s["bb"] + s["sf"]
    return (s["h"] + s["bb"]) / d if d else 0.0


def slg(s):
    return s["tb"] / s["ab"] if s["ab"] else 0.0


def rate3(v):
    """.345, 1.092"""
    t = f"{v:.3f}"
    return t[1:] if t.startswith("0") else t


def league_norms(history, db, first=2005):
    """{(year, 0 AL / 1 NL): dict(obp, slg, era)}: each league's totals by season, from every big-leaguer's row (the
    dynasty's seasons: the real ones before it hold only the players still in the game, and no walks)."""
    tot = collections.defaultdict(collections.Counter)
    for rows in history.values():
        for r in rows:
            if r["year"] < first or r["team"] >= len(db.franchises):
                continue
            league = int(db.teams.get(db.franchises[r["team"]], {}).get(4, -1))
            tot[(r["year"], league)].update({("b_" if r["batter"] else "p_") + k: v for k, v in r["stats"].items()})
    out = {}
    for key, t in tot.items():
        b = {k[2:]: v for k, v in t.items() if k.startswith("b_")}
        b = collections.Counter(b)
        out[key] = dict(obp=obp(b) if b["ab"] else 0, slg=slg(b) if b["ab"] else 0,
                        era=27 * t["p_er"] / t["p_outs"] if t["p_outs"] else 0)
    return out


def ops_plus(s, norm):
    """100 x (OBP / the league's + SLG / the league's - 1), or None (no league line, no at-bats)"""
    if not norm or not norm["obp"] or not norm["slg"] or not s["ab"]:
        return None
    return round(100 * (obp(s) / norm["obp"] + slg(s) / norm["slg"] - 1))


def era_plus(s, norm):
    """100 x the league's ERA / his, or None (no innings, no earned runs)"""
    if not norm or not norm["era"] or not s["outs"] or not s["er"]:
        return None
    return round(100 * norm["era"] / (27 * s["er"] / s["outs"]))


# the awards: a position's worth over a season's 650 plate appearances, in runs (as the usual tables have it)
POSITION_RUNS = {"C": 10, "SS": 7, "2B": 3, "3B": 2, "OF": -2, "LF": -7, "CF": 3, "RF": -7, "1B": -10, "DH": -15}


def awards(save, db, stats, norms, most=10):
    """The award races by league: {0 AL / 1 NL: {"MVP"|"Cy Young"|"Rookie": [(key, team, why)]}}, best first.
    MVP: runs above average from OPS+ (x 0.11 a plate appearance), the position, some for HR and RBI and the
    club's record; Cy Young: runs saved against the league's ERA, wins and saves; Rookie: either, for players with
    130 big-league at-bats and 50 innings at most before this season (the careers, less this season)."""
    if not stats:
        return {}
    games, year = stats["games"], stats["year"]
    rec = {db.franchises[i]: v for i, v in save["records"].items()}
    car = save.get("careers") or {}

    def pct(t):
        w, l_ = rec.get(t, (0, 0))
        return w / (w + l_) if w + l_ else 0.5

    def league(t):
        return int(db.teams.get(t, {}).get(4, -1))

    def hitter(k, x):
        norm = norms.get((year, league(x.team)))
        op = ops_plus(x, norm) if x["ab"] else None
        if op is None:
            return None
        pa = x["ab"] + x["bb"] + x["sf"]
        runs = (op - 100) / 100 * pa * 0.11 + POSITION_RUNS.get(db.pos(k), 0) * pa / 650
        why = (f"{rate3(x['h'] / x['ab'])}/{rate3(obp(x))}/{rate3(slg(x))}, {x['hr']} HR, {x['rbi']} RBI, "
               f"{op} OPS+")
        return runs, why

    def pitcher(k, x):
        norm = norms.get((year, league(x.team)))
        if not norm or not norm["era"] or not x["outs"]:
            return None
        runs = norm["era"] * x["outs"] / 27 - x["er"]
        era = 27 * x["er"] / x["outs"]
        ip = f"{x['outs'] // 3}.{x['outs'] % 3}"
        if x["sv"] >= 5 and x["outs"] < 2 * games.get(x.team, 0):
            why = f"{x['sv']} SV, {era:.2f} ERA, {ip} IP, {x['so']} K"
        else:
            why = f"{x['w']}-{x['l']}, {era:.2f} ERA, {ip} IP, {x['so']} K"
        return runs, why

    def rookie(k, side, x):
        c = car.get(side, {}).get(k)
        if not c:
            return True  # (no big-league career before this one)
        return (c["ab"] - x["ab"] <= 130) if side == "bat" else (c["outs"] - x["outs"] <= 150)

    out = {}
    for lg_ in (0, 1):
        mvp, cy, roy = [], [], []
        for k, x in stats["bat"].items():
            if league(x.team) != lg_ or not x["ab"]:
                continue
            v = hitter(k, x)
            if not v:
                continue
            runs, why = v
            q = x["ab"] >= 2.7 * games.get(x.team, 0)
            score = runs + 0.25 * x["hr"] + 0.08 * x["rbi"] + 30 * (pct(x.team) - 0.5)
            if q:
                mvp.append((score, k, x.team, why))
            if rookie(k, "bat", x) and x["ab"] >= 1.5 * games.get(x.team, 0):
                roy.append((runs + 0.25 * x["hr"] + 0.08 * x["rbi"], k, x.team, why))
        for k, x in stats["pit"].items():
            if league(x.team) != lg_ or not x["outs"]:
                continue
            v = pitcher(k, x)
            if not v:
                continue
            runs, why = v
            if x["outs"] >= games.get(x.team, 0) or x["sv"] >= 5:
                cy.append((runs + 0.6 * x["w"] + 0.35 * x["sv"], k, x.team, why))
            if rookie(k, "pit", x) and (x["outs"] >= 0.75 * games.get(x.team, 0) or x["sv"] >= 3):
                roy.append((runs + 0.6 * x["w"] + 0.35 * x["sv"], k, x.team, why))
        out[lg_] = {name: [(k, t, why) for _, k, t, why in sorted(lst, key=lambda z: -z[0])[:most]]
                    for name, lst in (("MVP", mvp), ("Cy Young", cy), ("Rookie", roy))}
    return out


def season_stats(save, db):
    """This season's line for every player with one (the player history's rows of the newest year, FORMAT_NOTES 3.6):
    dict(year, last_season (no games yet this year: last season's rows), games {team: games played, or 162},
    bat {key: Counter}, pit {key: Counter}); each Counter's .team is the club he's with (a traded player's rows add
    up)."""
    rows = [r for rs in save["history"].values() for r in rs]
    if not rows:
        return None
    year = max(r["year"] for r in rows)
    season = min((g["day"] for g in save["games"]), default=None)
    last = season is not None and day(season).year != year
    # the season's over in the postseason (the schedule then holds only the playoff games, and the standings are the
    # playoffs' records), or when the standings are back at 0-0 with this year's lines kept
    final = not last and (in_postseason(save) or not any(sum(v) for v in save["records"].values()))
    games = {db.franchises[i]: (162 if last else sum(v)) for i, v in save["records"].items()}
    bat, pit = {}, {}
    for k, rs in save["history"].items():
        for r in rs:
            if r["year"] != year or r["team"] >= len(db.franchises):
                continue
            d = bat if r["batter"] else pit
            st = d.setdefault(k, collections.Counter())
            st.update(r["stats"])
            st.team = db.franchises[r["team"]]
    if final:  # a club's games then: the most any of its hitters played (equal to the record in every save checked;
        # a dynasty's season can be shorter than 162)
        for x in bat.values():
            games[x.team] = max(games.get(x.team, 0), x["g"])
    return dict(year=year, last_season=last, final=final, games=games, bat=bat, pit=pit)


def farm_report(save, db, stats, ref, most=5):
    """The farm teams' season (the player history's rows of this year at the AAA, AA and A clubs): dict(levels
    {"AAA"|"AA"|"A": {category: [(key, team, text)]}}, teams {farm team: dict(bat, pit, games)}, prospects [(key,
    team, age, text)]). Qualifying as in the big leagues, by the farm club's games (the most any hitter played)."""
    if not stats:
        return {}
    year = stats["year"]
    teams = collections.defaultdict(lambda: dict(bat={}, pit={}, games=0))
    for k, rs in save["history"].items():
        for r in rs:
            if r["year"] != year or r["team"] < len(db.franchises):
                continue
            t = db.team_at(r["team"])
            if t not in db.levels:
                continue
            d = teams[t]["bat" if r["batter"] else "pit"]
            st = d.setdefault(k, collections.Counter())
            st.update(r["stats"])
            st.team = t
    for t, v in teams.items():
        v["games"] = max((x["g"] for x in v["bat"].values()), default=0)
    if not teams:
        return {}
    levels = {}
    for lv in ("AAA", "AA", "A"):
        mine = [t for t in teams if db.levels[t] == lv]
        b = [(k, x) for t in mine for k, x in teams[t]["bat"].items()]
        p = [(k, x) for t in mine for k, x in teams[t]["pit"].items()]
        g = lambda x: teams[x.team]["games"]
        qb = [(k, x) for k, x in b if x["ab"] and x["ab"] >= 2.7 * g(x)]
        qp = [(k, x) for k, x in p if x["outs"] and x["outs"] >= g(x)]
        cat = {}
        cat["AVG"] = [(k, x.team, rate3(x["h"] / x["ab"])) for k, x in
                      sorted(qb, key=lambda z: (-z[1]["h"] / z[1]["ab"], -z[1]["ab"]))][:most]
        cat["HR"] = [(k, x.team, str(x["hr"])) for k, x in sorted(b, key=lambda z: -z[1]["hr"]) if x["hr"]][:most]
        cat["RBI"] = [(k, x.team, str(x["rbi"])) for k, x in sorted(b, key=lambda z: -z[1]["rbi"]) if x["rbi"]][:most]
        cat["SB"] = [(k, x.team, str(x["sb"])) for k, x in sorted(b, key=lambda z: -z[1]["sb"]) if x["sb"]][:most]
        cat["OPS"] = [(k, x.team, rate3(obp(x) + slg(x))) for k, x in
                      sorted(qb, key=lambda z: -(obp(z[1]) + slg(z[1])))][:most]
        cat["W"] = [(k, x.team, str(x["w"])) for k, x in sorted(p, key=lambda z: (-z[1]["w"], z[1]["l"])) if x["w"]][:most]
        cat["ERA"] = [(k, x.team, f"{27 * x['er'] / x['outs']:.2f}") for k, x in
                      sorted(qp, key=lambda z: (z[1]["er"] / z[1]["outs"], -z[1]["outs"]))][:most]
        cat["SO"] = [(k, x.team, str(x["so"])) for k, x in sorted(p, key=lambda z: -z[1]["so"]) if x["so"]][:most]
        cat["SV"] = [(k, x.team, str(x["sv"])) for k, x in sorted(p, key=lambda z: -z[1]["sv"]) if x["sv"]][:most]
        levels[lv] = cat
    # the prospects: the database's top-prospect flag (column 43), or a player the dynasty made (not in it), or 23
    # and under; ranked by his line against his level's (OPS for a hitter, ERA for a pitcher), the levels weighted
    lvw = {"AAA": 1.0, "AA": 0.9, "A": 0.78}
    pool = []
    for t, v in teams.items():
        for side in ("bat", "pit"):
            for k, x in v[side].items():
                p = db.players.get(k)
                age = db.age(k, ref)
                if not ((p and p.get(43) == "1") or p is None or (age is not None and age <= 23)):
                    continue
                if side == "bat":
                    if x["ab"] < max(25, 1.2 * v["games"]):
                        continue
                    o = obp(x) + slg(x)
                    score = (o - 0.70) * 100 + x["hr"] * 0.3 + x["sb"] * 0.1
                    text = (f"{rate3(x['h'] / x['ab'])}, {x['hr']} HR, {x['rbi']} RBI"
                            + (f", {x['sb']} SB" if x["sb"] >= 5 else "") + f", {rate3(o)} OPS")
                else:
                    if x["outs"] < max(30, 1.5 * v["games"]):
                        continue
                    era = 27 * x["er"] / x["outs"]
                    score = (4.5 - era) * 5 + x["so"] * 27 / x["outs"] * 1.2 + x["w"] * 0.4 + x["sv"] * 0.1
                    score *= min(1, x["outs"] / (3.6 * max(v["games"], 1))) ** 0.5  # (a starter's workload counts)
                    text = (f"{x['w']}-{x['l']}" + (f", {x['sv']} SV" if x["sv"] else "")
                            + f", {era:.2f} ERA, {x['so']} K in {x['outs'] // 3}" + (f".{x['outs'] % 3}" if x["outs"] % 3 else "") + " IP")
                bonus = 4 if (p and p.get(43) == "1") else 0
                young = (24 - age) * 1.5 if age is not None else 1.5
                pool.append(((score + bonus + young) * lvw[db.levels[t]], k, t, age, text))
    seen, prospects = set(), []
    for _, k, t, age, text in sorted(pool, key=lambda z: -z[0]):
        if k not in seen:
            seen.add(k)
            prospects.append((k, t, age, text))
    return dict(levels=levels, teams=dict(teams), prospects=prospects[:30])


def power_rankings(save, db, through=None):
    """The 30 clubs ranked on the results up to day `through` (all of them when None): a blend of the record, the
    run differential (its Pythagorean record) and the last 10 games. [(team, score, dict(w, l, rs, ra, last10,
    streak))], best first; [] before a week of games or in the postseason."""
    played = sorted((g for g in save["games"] if g["played"] and (through is None or g["day"] <= through)),
                    key=lambda g: g["day"])
    teams = [t for t in db.franchises if t in db.teams]
    if len(played) < 45 or not all(g["home"] in teams and g["away"] in teams for g in played[:5]):
        return []
    rec = {t: dict(w=0, l=0, rs=0, ra=0, form=[]) for t in teams}
    for g in played:
        for me, them, mr, tr in ((g["home"], g["away"], g["hr"], g["ar"]), (g["away"], g["home"], g["ar"], g["hr"])):
            if me not in rec:
                continue
            r = rec[me]
            r["w" if mr > tr else "l"] += 1
            r["rs"] += mr
            r["ra"] += tr
            r["form"].append("W" if mr > tr else "L")
    out = []
    for t, r in rec.items():
        n = r["w"] + r["l"]
        if not n:
            continue
        pct = r["w"] / n
        pyth = r["rs"] ** 1.83 / max(1, r["rs"] ** 1.83 + r["ra"] ** 1.83)
        last = r["form"][-10:]
        l10 = last.count("W") / len(last)
        weight = min(1, n / 60)  # (early on the run differential says more than the record)
        score = (0.45 * weight + 0.25) * pct + (0.6 - 0.45 * weight + 0.15) * pyth + 0.15 * l10
        k = 0
        while k < len(r["form"]) and r["form"][-1 - k] == r["form"][-1]:
            k += 1
        out.append((t, score, dict(w=r["w"], l=r["l"], rs=r["rs"], ra=r["ra"], last10=f"{last.count('W')}-{last.count('L')}",
                                   streak=f"{r['form'][-1]}{k}" if r["form"] else "")))
    return sorted(out, key=lambda z: -z[1])


def power(save, db, stats):
    """This edition's power rankings, with each club's rank a week of games before (from the same results), and a
    line about it: [dict(team, rank, was, score, w, l, rs, ra, last10, streak, note)]"""
    now = power_rankings(save, db)
    if not now:
        return []
    last = max(g["day"] for g in save["games"] if g["played"])
    then = {t: i + 1 for i, (t, _, _) in enumerate(power_rankings(save, db, last - 7))}
    bat = (stats or {}).get("bat", {})
    pit = (stats or {}).get("pit", {})
    best = {}
    for k, x in bat.items():
        if x["hr"] > best.get((x.team, "hr"), (0, None))[0]:
            best[(x.team, "hr")] = (x["hr"], k)
    for k, x in pit.items():
        if x["w"] > best.get((x.team, "w"), (0, None))[0]:
            best[(x.team, "w")] = (x["w"], k)
    out = []
    for i, (t, score, r) in enumerate(now):
        rank, was = i + 1, then.get(t)
        diff = r["rs"] - r["ra"]
        bits = []
        if r["streak"] and int(r["streak"][1:]) >= 4:
            bits.append(f"{'won' if r['streak'][0] == 'W' else 'lost'} {r['streak'][1:]} straight")
        elif r["last10"] in ("8-2", "9-1", "10-0"):
            bits.append(f"{r['last10']} in the last 10")
        elif r["last10"] in ("2-8", "1-9", "0-10"):
            bits.append(f"{r['last10']} in the last 10")
        if abs(diff) >= 25:
            bits.append(f"a {'+' if diff > 0 else '&minus;'}{abs(diff)} run differential")
        hr, w = best.get((t, "hr")), best.get((t, "w"))
        if hr and hr[0] >= 3:
            bits.append(f"{{P{hr[1]:x}}}'s {hr[0]} home runs")
        elif w and w[0] >= 3:
            bits.append(f"{{P{w[1]:x}}}'s {w[0]} wins")
        if was and was - rank >= 4:
            lead = f"Up {was - rank} spots"
        elif was and rank - was >= 4:
            lead = f"Down {rank - was} spots"
        else:
            lead = ""
        note = (lead + (": " if lead and bits else "")) + ", ".join(bits)
        out.append(dict(team=t, rank=rank, was=was, score=score, note=note[:1].upper() + note[1:] + ("." if note else ""),
                        **r))
    return out


ROUNDS = ("Division Series", "Championship Series", "World Series")


def playoffs(save, db):
    """The postseason's series from its schedule: [dict(round 0-2, name ("ALDS", "NLCS", "World Series"), league 0/1
    (None for the World Series), top (the team at home in game 1: the higher seed), other, best (5 or 7), wins {team:
    n}, games [game ...], winner or None, leader or None)], the rounds in order, the American League's first. The
    series a round didn't need are already gone from the schedule; a later round is there once the one before ends."""
    if not in_postseason(save):
        return []
    by = collections.OrderedDict()
    for g in sorted(save["games"], key=lambda g: g["day"]):
        if g["home"] in db.teams and g["away"] in db.teams:
            by.setdefault(frozenset((g["home"], g["away"])), []).append(g)
    starts = sorted({gs[0]["day"] for gs in by.values()})
    out = []
    # a round's series start within a day or two of each other; the next round starts after the last one's games
    rnd, first = -1, None
    for gs in sorted(by.values(), key=lambda gs: gs[0]["day"]):
        if first is None or gs[0]["day"] - first > 2:
            rnd, first = rnd + 1, gs[0]["day"]
        top, other = gs[0]["home"], gs[0]["away"]
        lgs = {int(db.teams[t].get(4, 0)) for t in (top, other)}
        league = lgs.pop() if len(lgs) == 1 else None
        r = min(rnd, 2) if league is not None else 2
        best = 5 if r == 0 else 7
        wins = {top: 0, other: 0}
        for g in gs:
            if g["played"]:
                wins[g["home"] if g["hr"] > g["ar"] else g["away"]] += 1
        need = best // 2 + 1
        winner = next((t for t, n in wins.items() if n >= need), None)
        leader = None if wins[top] == wins[other] else max(wins, key=wins.get)
        name = ("World Series" if r == 2 else ("AL" if league == 0 else "NL") + ("DS" if r == 0 else "CS"))
        out.append(dict(round=r, name=name, league=league, top=top, other=other, best=best, wins=wins, games=gs,
                        winner=winner, leader=leader))
    out.sort(key=lambda x: (x["round"], x["league"] if x["league"] is not None else 2, x["games"][0]["day"]))
    return out


def series_line(s, club):
    """ "Royals lead 2-1", "Tigers win 3-0", "Tied 1-1", "Game 1 Wednesday" (club: a team's name)"""
    a, b = s["top"], s["other"]
    wa, wb = s["wins"][a], s["wins"][b]
    if s["winner"]:
        w = s["winner"]
        l_ = b if w == a else a
        return f"{club(w)} win {s['wins'][w]}-{s['wins'][l_]}"
    if not wa and not wb:
        return "Game 1 " + day(s["games"][0]["day"]).strftime("%A")
    if wa == wb:
        return f"Tied {wa}-{wb}"
    w = s["leader"]
    return f"{club(w)} lead {s['wins'][w]}-{min(wa, wb)}"


def season_leaders(save, db, most=10, stats=None):
    """This season's leaders in each league: {0 (AL) / 1 (NL): {"AVG"|"HR"|"RBI"|"W"|"ERA"|"SV"|"SO": [(key, team,
    text)]}, year, last_season}. AVG needs 2.7 at-bats a team game, ERA an inning every three team games (the game's
    own list, checked)."""
    st = stats or season_stats(save, db)
    if not st:
        return {}
    year, games, bat, pit = st["year"], st["games"], st["bat"], st["pit"]
    out = {}
    for lg in (0, 1):
        def mine(d):
            return [(k, s) for k, s in d.items() if int(db.teams.get(s.team, {}).get(4, -1)) == lg]
        b, p = mine(bat), mine(pit)
        cat = {}
        cat["HR"] = [(k, s.team, str(s["hr"])) for k, s in sorted(b, key=lambda z: -z[1]["hr"]) if s["hr"]][:most]
        q = [(k, s) for k, s in b if s["ab"] and s["ab"] >= 2.7 * games.get(s.team, 0)]
        cat["AVG"] = [(k, s.team, f"{s['h'] / s['ab']:.3f}".lstrip("0"))
                      for k, s in sorted(q, key=lambda z: (-z[1]["h"] / z[1]["ab"], -z[1]["ab"]))][:most]
        cat["W"] = [(k, s.team, str(s["w"])) for k, s in sorted(p, key=lambda z: (-z[1]["w"], z[1]["l"])) if s["w"]][:most]
        q = [(k, s) for k, s in p if s["outs"] and s["outs"] >= games.get(s.team, 0)]
        cat["ERA"] = [(k, s.team, f"{27 * s['er'] / s['outs']:.2f}")
                      for k, s in sorted(q, key=lambda z: (z[1]["er"] / z[1]["outs"], -z[1]["outs"]))][:most]
        cat["SV"] = [(k, s.team, str(s["sv"])) for k, s in sorted(p, key=lambda z: -z[1]["sv"]) if s["sv"]][:most]
        cat["RBI"] = [(k, s.team, str(s["rbi"])) for k, s in sorted(b, key=lambda z: -z[1]["rbi"]) if s["rbi"]][:most]
        q = [(k, s) for k, s in b if s["ab"] and s["ab"] >= 2.7 * games.get(s.team, 0)]
        cat["OPS"] = [(k, s.team, rate3(obp(s) + slg(s))) for k, s in sorted(q, key=lambda z: -(obp(z[1]) + slg(z[1])))][:most]
        cat["SO"] = [(k, s.team, str(s["so"])) for k, s in sorted(p, key=lambda z: -z[1]["so"]) if s["so"]][:most]
        out[lg] = cat
    out["year"] = year
    out["last_season"] = st["last_season"]
    out["final"] = st["final"]
    return out


def _lib():
    import sys
    lib = os.path.join(HERE, "mvp05", "lib")
    if lib not in sys.path:
        sys.path.insert(0, lib)


def _players(x):
    """{player key: name} and [(key, injury kind, days left)] from the save's player records (tagged table 8,
    3250 records of 60 bytes: first name at 8, last at 20; field 0x1E the injury's kind, 0x1F its days left, the
    fields the in-game injury hook reads), found through the player key list (key, record, record)."""
    import dynasty05 as DY
    with DY._in_lib():  # (the converter's tables load from its own folder)
        import packe_decomp_layout as L
        import tablesconv as T
    tg = T.tags(x, T.TX)
    t8 = x[tg[8] + 4:tg[9]]
    if len(t8) != 3250 * 60:
        raise NewsError("this save's player records aren't where they should be")
    for start in range(tg[6], tg[6] + 1024, 4):
        if struct.unpack_from("<II", x, start) == (3250, 3250):
            break
    else:
        raise NewsError("this save's player list isn't where it should be")
    names, hurt, contracts = {}, [], {}
    for i in range(3250):
        key, row, _ = struct.unpack_from("<III", x, start + 8 + 12 * i)
        if row >= 3250:
            continue
        # a record's 60 bytes are 60 * row on: its words 0-5 first (24 bytes), then words 6-7 and the names, which is
        # the layout's record turned by 24 (checked: contracts and injuries against the game's screens and the
        # injured lists; the converters' frame, 24 bytes on, puts words 0-5 with the record before)
        o = 60 * row
        r = t8[o + 24:o + 60] + t8[o:o + 24]
        first = r[8:20].split(b"\0")[0].decode("latin-1").strip()
        last = r[20:36].split(b"\0")[0].decode("latin-1").strip()
        if first or last:
            names[key] = " ".join(f"{first} {last}".split())
        f = L.xb_fields(r)
        if f.get("f1F"):
            hurt.append(dict(player=key, kind=f.get("f1E", 0), days=f["f1F"]))
        if f.get("f19"):  # his contract: years left (this season counts) and the salary, in $100,000 steps from
            # $100,000 (f18 37 is the $3.80M a year the game shows)
            contracts[key] = ((f["f18"] + 1) * 100_000, f["f19"])
    return names, hurt, contracts


def _careers(x):
    """Every player's big-league career (the player history keeps only his last 16 seasons; these are whole, the
    real seasons and the dynasty's): {"bat": {key: Counter(g, ab, h, hr, rbi, r, sb)}, "pit": {key: Counter(g, er,
    l, w, sv, bb, so, outs)}}. Hitters: region 16's 16-byte table, a row a player (FORMAT_NOTES 3.6); pitchers:
    table 24, by the stats key list. Checked: Sheffield 488 HR, Sosa 588; Maddux 313 W, Clemens 4,465 SO."""
    import dynasty05 as DY
    with DY._in_lib():
        import tablesconv as T
    out = {"bat": {}, "pit": {}}
    try:
        tg = T.tags(x, T.TX)
        start = next(a for a in range(tg[6], tg[6] + 1024, 4) if struct.unpack_from("<II", x, a) == (3250, 3250))
        rows = {}
        for i in range(3250):
            k, r = struct.unpack_from("<II", x, start + 8 + 12 * i)
            rows[k] = r
        v = tg[16] + 39004 + 5 * 13004 + 4  # region 16: the 12-byte table, five 4-byte ones, then this
        for k, r in rows.items():
            if r >= 3250:
                continue
            w = struct.unpack_from("<4I", x, v + 16 * r)
            a, b, c, d = _bits(w[0], (12, 14)), _bits(w[1], (13, 10)), _bits(w[2], (12, 12)), _bits(w[3], (11,))
            if a[1]:
                out["bat"][k] = collections.Counter(g=a[0], ab=a[1], h=b[0], hr=b[1], rbi=c[0], r=c[1], sb=d[0])
        q = tg[16] + 156028  # the stats key list, after it
        n = struct.unpack_from("<I", x, q)[0]
        if n <= 1800:
            for i in range(n):
                k, r = struct.unpack_from("<II", x, q + 8 + 12 * i)
                if r >= 1800:
                    continue
                w = struct.unpack_from("<3I", x, tg[24] + 4 + 12 * r)
                a, b, c = _bits(w[0], (11, 12, 9)), _bits(w[1], (10, 10, 12)), _bits(w[2], (13, 13, 2))
                if c[1] or c[2]:
                    out["pit"][k] = collections.Counter(g=a[0], er=a[1], l=a[2], w=b[0], sv=b[1], bb=b[2], so=c[0],
                                                        outs=3 * c[1] + c[2])
    except (StopIteration, struct.error, IndexError, ValueError):
        pass
    return out


# milestones: the marks, and how close counts as "within reach" (FORMAT: stat, label, marks, reach)
MILESTONES = (("bat", "hr", "home runs", (100, 150, 200, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750, 800), 10),
              ("bat", "h", "hits", (1000, 1500, 2000, 2500, 3000, 3500, 4000), 60),
              ("bat", "rbi", "RBIs", (1000, 1500, 2000), 40),
              ("bat", "sb", "stolen bases", (200, 300, 400, 500, 600), 15),
              ("pit", "w", "wins", (100, 150, 200, 250, 300, 350), 8),
              ("pit", "sv", "saves", (100, 200, 300, 400, 500, 600), 15),
              ("pit", "so", "strikeouts", (1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000), 80))


def milestones(save, db, stats):
    """(near, reached): near [(key, team, stat label, mark, to go)] the active players within reach of a career mark,
    closest first; reached [(key, team, label, mark)] the marks passed this season (the career less this season's
    line was short of it)."""
    car = save.get("careers") or {}
    if not car or not stats:
        return [], []
    on = {k: db.franchises[i] for i, ks in save["rosters"].items() if i < len(db.franchises) for k in ks}
    near, reached = [], []
    for side, stat, label, marks, reach in MILESTONES:
        season = stats["bat" if side == "bat" else "pit"]
        for k, c in car[side].items():
            team = on.get(k) or getattr(season.get(k), "team", None)
            if team not in db.franchises:
                continue
            have = c[stat]
            nxt = next((m for m in marks if m > have), None)
            if nxt is not None and nxt - have <= reach:
                near.append((k, team, label, nxt, nxt - have))
            if not stats["last_season"]:
                before = have - (season[k][stat] if k in season else 0)
                for m in marks:
                    if before < m <= have:
                        reached.append((k, team, label, m))
    # how famous a mark is: 500 HR, 3,000 hits, 2,000 RBIs, 500 SB, 300 wins, 400 saves and 3,000 strikeouts are 1
    fame = {"home runs": 500, "hits": 3000, "RBIs": 2000, "stolen bases": 500, "wins": 300, "saves": 400,
            "strikeouts": 3000}
    reach = {x_[2]: x_[4] for x_ in MILESTONES}
    near.sort(key=lambda z: z[4] / reach[z[2]] - z[3] / fame[z[2]])
    reached.sort(key=lambda z: -z[3] / fame[z[2]])
    return near, reached


def _rosters(x):
    """{franchise index 0-29: [player keys]}: the 25 on each big-league club, from the roster blocks (FORMAT_NOTES
    3.1: 4 lineup units, then 25 player keys), in the franchises' order."""
    import dynasty05 as DY
    with DY._in_lib():
        import xb2gc as X
    try:
        st = X._blocks(x, X.KEYX, X.SIG_X, 0x38CB)
    except AssertionError:
        return {}
    return {k: [p for p in struct.unpack_from("<25I", x, st[k] + 192) if p and p != 0xFFFFFFFF] for k in range(30)}


# ---- the news ---------------------------------------------------------------------------------------------------
def build(save, db):
    """Everything the page shows: standings, scores, matchups and ranked headlines."""
    teams = db.franchises
    if len(teams) != 30:
        raise NewsError("the game's database doesn't have the 30 franchises")
    rec = {t: save["records"][i] for i, t in enumerate(teams)}
    played = sorted((g for g in save["games"] if g["played"]), key=lambda g: g["day"])
    upcoming = sorted((g for g in save["games"] if not g["played"]), key=lambda g: g["day"])
    last_day = played[-1]["day"] if played else None
    season_end = max((g["day"] for g in save["games"]), default=None)
    next_day = upcoming[0]["day"] if upcoming else None
    today = last_day or next_day or 0

    # per team: results in order, runs for and against, home and road
    form = collections.defaultdict(list)
    runs = collections.defaultdict(lambda: [0, 0])
    split = collections.defaultdict(lambda: [0, 0, 0, 0])
    for g in played:
        for me, them, mr, tr, home in ((g["away"], g["home"], g["ar"], g["hr"], False),
                                       (g["home"], g["away"], g["hr"], g["ar"], True)):
            w = mr > tr
            form[me].append("W" if w else "L")
            runs[me][0] += mr
            runs[me][1] += tr
            split[me][(0 if home else 2) + (0 if w else 1)] += 1

    def streak(t):
        f = form.get(t, [])
        if not f:
            return ""
        k = 1
        while k < len(f) and f[-1 - k] == f[-1]:
            k += 1
        return f"{f[-1]}{k}"

    def pct(t):
        w, l = rec[t]
        return w / (w + l) if w + l else 0.0

    divisions = []
    leader_gb = {}
    for dv in range(6):
        members = sorted((t for t in teams if int(db.teams[t].get(5, -1)) == dv), key=lambda t: (-pct(t), -rec[t][0]))
        top = members[0]
        rows = []
        for t in members:
            gb = ((rec[top][0] - rec[t][0]) + (rec[t][1] - rec[top][1])) / 2
            leader_gb[t] = gb
            last10 = form.get(t, [])[-10:]
            rows.append(dict(team=t, w=rec[t][0], l=rec[t][1], pct=pct(t), gb=gb, streak=streak(t),
                             last10=f"{last10.count('W')}-{last10.count('L')}", rs=runs[t][0], ra=runs[t][1],
                             home="%d-%d" % tuple(split[t][:2]), road="%d-%d" % tuple(split[t][2:])))
        divisions.append(dict(name=DIVISIONS[dv], rows=rows))

    # the wild card: the best non-leader in each league
    wildcard = {}
    for lg in (0, 1):
        leaders = {d["rows"][0]["team"] for d in divisions[3 * lg:3 * lg + 3]}
        rest = sorted((r for d in divisions[3 * lg:3 * lg + 3] for r in d["rows"] if r["team"] not in leaders),
                      key=lambda r: (-r["pct"], -r["w"]))
        if rest:
            best = rest[0]
            for r in rest:
                r["wcgb"] = ((best["w"] - r["w"]) + (r["l"] - best["l"])) / 2
            wildcard[lg] = rest

    games_played = max((sum(rec[t]) for t in teams), default=0)
    postseason = in_postseason(save)
    series_all = playoffs(save, db) if postseason else []
    in_playoffs = {t for sr in series_all for t in (sr["top"], sr["other"])}

    def contention(t):
        """1.0 for a team out of it, up to 1.5 for one in the thick of a race."""
        t = db.org_of.get(t, t)
        if t not in rec:
            return 0.8
        left = max(162 - sum(rec[t]), 10) if games_played else 162
        gb = min(leader_gb.get(t, 99), min((r.get("wcgb", 99) for lg in wildcard.values() for r in lg
                                            if r["team"] == t), default=99))
        close = max(0.0, 1 - gb / max(left * 0.15, 3))
        return 1.0 + 0.5 * close

    def mine(*ts):
        return save["user"] is not None and any(db.org_of.get(t, t) == save["user"] for t in ts)

    def fade(d):  # (never below a tenth: last month's blockbuster still beats this week's call-up of a nobody)
        return max(0.1, math.exp(-max(0, today - d) / WEIGHTS["fade_days"]))

    names = save["names"]

    def who(k, with_pos=True):
        """ "RHP Vicente Padilla" (the save's name for him, the database's position)"""
        n = names.get(k) or db.name(k) or "an unnamed player"
        p = db.pos(k) if with_pos else ""
        return f"{p} {n}" if p else n

    def last(k):
        n = names.get(k) or db.name(k) or "?"
        return n.split()[-1]

    def listed(keys):
        w = [who(k) for k in keys]
        return w[0] if len(w) == 1 else ", ".join(w[:-1]) + " and " + w[-1] if w else "nobody"

    # where each player is now: a big-league roster in the save, else the last trade or move, else 2005's team
    team_of = _teams_of_players(save, db)
    for i, keys in save["rosters"].items():
        for k in keys:
            team_of[k] = teams[i]

    stories = []

    def add(score, kind, head, body, d, teams_, players=(), sub=None):
        mult = WEIGHTS["your_team"] if mine(*teams_) else 1.0
        stories.append(dict(score=score * mult * fade(d), kind=kind, sub=sub or kind, head=head, body=body, day=d,
                            raw_teams=list(teams_),
                            teams=[db.org_of.get(t, t) for t in teams_], players=list(players), mine=mine(*teams_)))

    words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
    for tr in save["trades"]:
        a, b = tr["sides"]  # each side: a team and the players it gave up
        big = a["team"] in rec and b["team"] in rec
        imp_a = sum(db.importance(k) for k in a["players"])
        imp_b = sum(db.importance(k) for k in b["players"])
        size = WEIGHTS["trade"] if a["team"] in rec or b["team"] in rec else WEIGHTS["trade_minors"]
        score = size * (imp_a + imp_b) * max(contention(a["team"]), contention(b["team"]))
        # told from the side of the team that got the biggest name
        give, get = (a, b) if imp_a >= imp_b else (b, a)
        star = max(give["players"], key=db.importance, default=None)
        n = len(a["players"]) + len(b["players"])
        lop = abs(imp_a - imp_b) > 0.6
        buyer, seller = get["team"], give["team"]
        if star is None:
            head = f"{db.city(buyer)} and {db.city(seller)} make a deal"
        elif lop:
            head = f"{db.club(buyer)} land {last(star)} from {db.city(seller)}"
        elif n > 2:
            stars = sorted(give["players"] + get["players"], key=db.importance, reverse=True)[:2]
            head = f"{last(stars[0])}, {last(stars[1])} in {words.get(n, str(n))}-player deal"
        else:
            head = f"{db.club(buyer)} trade {last(get['players'][0]) if get['players'] else ''} for {last(star)}"
        body = (f"{db.named(buyer)[0].upper()}{db.named(buyer)[1:]} acquired {listed(give['players'])} from "
                f"{db.named(seller)} for {listed(get['players'])}.")
        if big and lop:
            body += f" A big pickup for {db.city(buyer)}."
        add(score, "Trade", head.replace("  ", " "), body, tr["day"], [a["team"], b["team"]],
            a["players"] + b["players"])

    NEW = object()

    def hist_team(k, d, to):
        """where k was before a move to `to` on day d, from his season rows (better than the 2005 rosters years on):
        this season's club, unless that's `to` already (the move made the row), else last season's"""
        rows = [r for r in save.get("history", {}).get(k, []) if r["year"] <= day(d).year]
        now = [db.team_at(r["team"]) for r in rows if r["year"] == day(d).year]
        if any(t_ != to for t_ in now):
            return next(t_ for t_ in reversed(now) if t_ != to)
        older = [r for r in rows if r["year"] < day(d).year]
        if older:
            return db.team_at(max(older, key=lambda r: r["year"])["team"])
        return NEW if now or not db.team_of.get(k) else None  # new to the league: signed (a free agent, a draftee)

    seen_on = {}  # where a player was before each move, by date
    for mv in sorted(save["moves"], key=lambda m: m["day"]):
        k, to = mv["player"], mv["team"]
        before = seen_on.get(k) or hist_team(k, mv["day"], to) or db.team_of.get(k)
        seen_on[k] = to
        new = before is NEW
        if new:
            before = None
        up = to in rec
        imp = db.importance(k)
        score = WEIGHTS["callup" if up else "senddown"] * imp * contention(to)
        org = db.org_of.get(to, to)
        same_org = before is not None and db.org_of.get(before, before) == org
        # into another organization with no trade: a signing (how a dynasty moves free agents)
        signed = new or before is not None and not same_org and not any(
            k in sd["players"] for t_ in save["trades"] for sd in t_["sides"] if abs(t_["day"] - mv["day"]) <= 1)
        if signed:
            sub = "Signed"
            head = f"{db.club(org)} sign {last(k)}"
            body = f"The {db.full(org)} signed {who(k)}" + (f" and assigned him to {db.farm(to)}." if to != org else ".")
        elif up and before == to:
            sub = "Assigned"
            head = f"{last(k)} stays with {db.city(to)}"
            body = f"{who(k)} was assigned to the {db.full(to)}."
        elif up:
            sub = "Call-up"
            head = f"{db.club(to)} call up {last(k)}"
            body = f"The {db.full(to)} called up {who(k)}" + (
                f" from {db.farm(before)}." if same_org and before != to else ".")
        elif same_org and before in rec:
            sub = "Sent down"
            head = f"{db.club(org)} send {last(k)} down"
            body = f"The {db.full(org)} optioned {who(k)} to {db.farm(to)}."
        elif same_org and before == to:
            sub = "Assigned"
            head = f"{last(k)} assigned to {db.city(to)}"
            body = f"{who(k)} was assigned to {db.named(to)}."
        elif same_org:
            sub = "Farm move"
            head = f"{last(k)} moves to {db.city(to)}"
            body = f"The {db.full(org)} moved {who(k)} from {db.farm(before)} to {db.farm(to)}."
        else:
            sub = "Assigned"
            head = f"{last(k)} assigned to {db.city(to)}"
            body = f"{who(k)} was assigned to {db.named(to)}."
        add(score, "Roster move", head, body, mv["day"], [to], [k], sub)

    for h in save["hurt"]:
        k, days = h["player"], h["days"]
        t = team_of.get(k)
        big_club = t in rec
        imp = db.importance(k)
        # the longer he's out and the bigger he is, the bigger the story; farm teams' injuries stay in the report
        length = min(days, 120) / 30
        score = WEIGHTS["injury"] * imp * (0.4 + length) * (contention(t) if t else 1.0) * (1 if big_club else 0.12)
        if postseason and db.org_of.get(t, t) not in in_playoffs:  # (a club whose season's over)
            score *= 0.2
        back = day(today + days) if today else None
        kind = db.injury(h["kind"])
        rest_of_year = bool(season_end and today + days > season_end)
        span = "the postseason" if postseason else "the season"
        out = (f"for the postseason ({_out_for(days)})" if postseason else
               f"for the rest of the season ({_out_for(days)})") if rest_of_year else _out_for(days)
        where = f" ({db.tag(t)})" if t else ""
        short_out = f"for {span}" if rest_of_year else _out_for(days)
        head = (f"{db.club(t)} lose {last(k)} {short_out}" if big_club and imp > 0.5 else f"{last(k)} out {short_out}")
        if h["kind"] == 49:  # a suspension, not an injury
            body = f"{who(k)}{where} is suspended, {_out_for(days)} left."
            add(score * 0.6, "Suspension", f"{last(k)} suspended", body, today, [t] if t else [], [k])
            stories[-1].update(days=days, big_club=big_club)
            continue
        body = (f"{who(k)}{where} is out" + (f" with {kind}" if kind else "") + f" {out}" +
                (f", expected back around {back.strftime('%B')} {back.day}." if back and not rest_of_year else "."))
        if kind and big_club and imp > 0.5:  # (the headline names it: "Padres lose Park to a torn rotator cuff")
            head = f"{db.club(t)} lose {last(k)} to {kind}" + (" for the season" if rest_of_year else "")
        add(score, "Injury", head, body, today, [t] if t else [], [k])
        stories[-1].update(days=days, big_club=big_club)

    for g in played:
        win, lose = (g["away"], g["home"]) if g["ar"] > g["hr"] else (g["home"], g["away"])
        wr, lr = max(g["ar"], g["hr"]), min(g["ar"], g["hr"])
        lose_hits = g["hh"] if win == g["away"] else g["ah"]
        ctx = max(contention(g["away"]), contention(g["home"]))
        if lose_hits == 0:
            add(WEIGHTS["no_hitter"] * ctx, "No-hitter", f"No-hitter! {db.club(win)} blank {db.city(lose)}",
                f"{db.club(win)} {wr}, {db.club(lose)} {lr}: not one hit for {db.city(lose)}.", g["day"], [win, lose])
        elif g["innings"] >= 13:
            add(WEIGHTS["long_game"] * ctx, "Marathon", f"{db.club(win)} outlast {db.city(lose)} in {g['innings']}",
                f"{db.club(win)} {wr}, {db.club(lose)} {lr} after {g['innings']} innings.", g["day"], [win, lose])
        elif wr - lr >= 10:
            add(WEIGHTS["blowout"] * ctx, "Rout", f"{db.club(win)} rout {db.city(lose)}, {wr}-{lr}",
                f"{db.club(win)} {wr}, {db.club(lose)} {lr}.", g["day"], [win, lose])
    for t in teams:
        s = streak(t)
        if s and int(s[1:]) >= 5 and last_day is not None:
            k = int(s[1:])
            hot = s[0] == "W"
            add((WEIGHTS["streak"] + 0.08 * (k - 5)) * contention(t), "Streak",
                f"{db.club(t)} {'win' if hot else 'drop'} {k} straight" if hot else f"{db.club(t)} skid hits {k}",
                f"{db.club(t)} are {rec[t][0]}-{rec[t][1]} and {'rolling' if hot else 'looking for answers'}.",
                last_day, [t])
    # the postseason: a series won (or swept), and where a series in progress stands
    for sr in series_all:
        played_ = [g for g in sr["games"] if g["played"]]
        if not played_:
            continue
        last_g = played_[-1]
        a, b = sr["top"], sr["other"]
        if sr["winner"]:
            w = sr["winner"]
            l_ = b if w == a else a
            ww, lw = sr["wins"][w], sr["wins"][l_]
            nxt = {0: f"the {'AL' if sr['league'] == 0 else 'NL'}CS", 1: "the World Series"}.get(sr["round"])
            if sr["round"] == 2:
                head = f"{db.club(w)} win the World Series"
            elif lw == 0:
                head = f"{db.club(w)} sweep {db.city(l_)}, move on to {nxt}"
            else:
                head = f"{db.club(w)} beat {db.city(l_)} {ww}-{lw}, move on to {nxt}"
            add(WEIGHTS["series_won"] * (1.5 if sr["round"] == 2 else 1 + 0.25 * sr["round"]), "Postseason", head,
                f"The {db.club(w)} won the {sr['name']} {ww} games to {lw} over the {db.club(l_)}, "
                f"{last_g['hr'] if last_g['home'] == w else last_g['ar']}-"
                f"{last_g['ar'] if last_g['home'] == w else last_g['hr']} in the last game.", last_g["day"], [w, l_])
        elif sr["leader"]:
            w = sr["leader"]
            l_ = b if w == a else a
            add(WEIGHTS["series_won"] * 0.6, "Postseason", f"{db.club(w)} lead {db.city(l_)} "
                f"{sr['wins'][w]}-{sr['wins'][l_]} in the {sr['name']}",
                f"{sr['best'] // 2 + 1 - sr['wins'][w]} more win{'s' if sr['best'] // 2 + 1 - sr['wins'][w] > 1 else ''} "
                f"and the {db.club(w)} take it.", last_g["day"], [w, l_])
    # a new division leader since the day before (from the schedule's results)
    if last_day is not None:
        for d in divisions:
            top = d["rows"][0]["team"]
            prev = {r["team"]: [r["w"], r["l"]] for r in d["rows"]}
            for g in played:
                if g["day"] == last_day:
                    for t, won in ((g["away"], g["ar"] > g["hr"]), (g["home"], g["hr"] > g["ar"])):
                        if t in prev:
                            prev[t][0 if won else 1] -= 1
            before = max(prev, key=lambda t: (prev[t][0] / max(sum(prev[t]), 1), prev[t][0]))
            if before != top and sum(rec[top]) >= 10:
                add(WEIGHTS["first_place"] * contention(top), "Standings", f"{db.club(top)} take over first",
                    f"{db.club(top)} pass {db.city(before)} for the {d['name']} lead.", last_day, [top, before])

    stories.sort(key=lambda s: -s["score"])
    stats = season_stats(save, db)
    near, reached = milestones(save, db, stats)
    prev_car = (save.get("prev") or {}).get("careers")
    if prev_car and last_day:  # marks passed since the previous edition (the newest earlier backup): news today
        for k, t, label, m in reached:
            side, stat, _, marks, _ = next(x_ for x_ in MILESTONES if x_[2] == label)
            if prev_car[side].get(k, {}).get(stat, 0) < m:
                add((0.6 + m / marks[-1]) * WEIGHTS["milestone"], "Milestone", f"{last(k)} reaches {m:,} {label}",
                    f"{who(k)} of the {db.full(t)} reached {m:,} career {label}.", last_day, [t], [k])
        stories.sort(key=lambda s_: -s_["score"])
    headlines = _spread(stories, recent=today - 10)
    results = [g for g in played if g["day"] == last_day] if last_day else []
    tomorrow = [g for g in upcoming if g["day"] == next_day] if next_day else []

    def matchup(g):
        a, h = g["away"], g["home"]
        both = (pct(a) + pct(h)) / 2
        rival = db.teams[a].get(5) == db.teams[h].get(5)
        close = abs(leader_gb.get(a, 0) - leader_gb.get(h, 0)) <= 3
        return both + (0.15 if rival and close else 0) + (0.2 if mine(a, h) else 0)
    tomorrow.sort(key=lambda g: -matchup(g))
    return dict(name=save["name"], kind=save["kind"], today=day(today) if today else None,
                next_day=day(next_day) if next_day else None, divisions=divisions, wildcard=wildcard,
                results=results, upcoming=tomorrow, headlines=headlines, postseason=postseason,
                # big-league clubs' deals first, then the farm teams'
                milestones=(near, reached),
                trades=sorted((s for s in stories if s["kind"] == "Trade"), key=lambda s: -s["day"]),
                injuries=sorted((s for s in stories if s["kind"] == "Injury"),
                                key=lambda s: (not s["big_club"], -s["days"])),
                moves=sorted((s for s in stories if s["kind"] == "Roster move"), key=lambda s: -s["day"]),
                user=save["user"], games_played=games_played, db=db,
                days=recaps(save["games"], db, save["user"], postseason),
                leaders=season_leaders(save, db, stats=stats), names=save["names"], contracts=save.get("contracts", {}),
                playoffs=playoffs(save, db),
                power=[] if postseason else power(save, db, stats),
                farm=farm_report(save, db, stats, day(today) if today else
                                 datetime.date(stats["year"] if stats else 2005, 7, 1)),
                awards=awards(save, db, stats, league_norms(save["history"], db)) if stats else {},
                stats=stats, rosters=save["rosters"], games=save["games"], records=rec, stories=stories,
                norms=league_norms(save["history"], db),
                history=save["history"], team_of=team_of, careers=save.get("careers") or {})


def _out_for(days):
    if days <= 10:
        return f"{days} day{'s' if days != 1 else ''}"
    if days < 60:
        return f"about {round(days / 7)} weeks"
    return f"about {round(days / 30)} months"


def _teams_of_players(save, db):
    """Which team a player is with, as far as the news knows: the team he was traded or moved to, else his 2005
    team."""
    out = dict(db.team_of)
    for tr in sorted(save["trades"], key=lambda t: t["day"]):
        a, b = tr["sides"]
        for k in a["players"]:
            out[k] = b["team"]
        for k in b["players"]:
            out[k] = a["team"]
    for mv in sorted(save["moves"], key=lambda m: m["day"]):
        out[mv["player"]] = mv["team"]
    return out


def _spread(stories, most=12, per_team=2, recent=0, per_kind=3):
    """The front page: the best stories, no more than per_team about one club and per_kind of one kind (injuries,
    trades ...), your team's best of the last ten days always among the first five."""
    out, count, kinds = [], collections.Counter(), collections.Counter()
    for s in stories:
        if len(out) >= most:
            break
        if any(count[t] >= per_team for t in s["teams"]) or kinds[s["kind"]] >= per_kind:
            continue
        out.append(s)
        count.update(set(s["teams"]))
        kinds[s["kind"]] += 1
    mine = next((s for s in stories if s["mine"] and s["day"] >= recent), None)
    if mine and mine not in out[:5]:
        if mine in out:
            out.remove(mine)
        out.insert(min(4, len(out)), mine)
    return out


# ---- the games, written up ------------------------------------------------------------------------------------
NUMBERS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve")
ORDINAL = {10: "10th", 11: "11th", 12: "12th", 13: "13th"}


def _num(n):
    return NUMBERS[n] if 0 <= n < len(NUMBERS) else str(n)


def _ord(n):
    return ORDINAL.get(n) or f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _back(gb):
    """2.5 -> "2½ games back", 0.5 -> "half a game back" """
    if gb == 0.5:
        return "half a game back"
    whole = int(gb)
    return f"{whole}{'½' if gb != whole else ''} game{'s' if gb != 1 else ''} back"


def recaps(games, db, user=None, postseason=False, days=7):
    """The last `days` days of games, newest first: [(date number, [recap])]. A recap: the game, a headline, a few
    sentences (what happened, streaks made or ended, the series, the season series, the standings after it), and
    how notable it is (for the Game of the Day)."""
    played = sorted((g for g in games if g["played"]), key=lambda g: g["day"])
    if not played:
        return []
    allg = sorted(games, key=lambda g: g["day"])
    # series: the same two clubs, the same park, on days no more than two apart
    series_of = {}
    by_pair = collections.defaultdict(list)
    for g in allg:
        by_pair[(g["away"], g["home"])].append(g)
    for lst in by_pair.values():
        run = []
        for g in lst:
            if run and g["day"] - run[-1]["day"] > 2:
                for x in run:
                    series_of[id(x)] = run
                run = []
            run.append(g)
        for x in run:
            series_of[id(x)] = run
    keep = sorted({g["day"] for g in played})[-days:]
    first_kept = keep[0]
    rec = collections.defaultdict(lambda: [0, 0])
    form = collections.defaultdict(list)
    meet = collections.defaultdict(lambda: collections.Counter())
    pair_n = collections.Counter(frozenset((g["away"], g["home"])) for g in games)
    div_of = {t: int(db.teams[t].get(5, -1)) for t in db.franchises if t in db.teams}
    out = collections.OrderedDict((d, []) for d in reversed(keep))
    i = 0
    while i < len(played):
        d = played[i]["day"]
        today = [g for g in played if g["day"] == d]
        i += len(today)
        notes = []
        for g in today:
            a, h = g["away"], g["home"]
            win, lose = (a, h) if g["ar"] > g["hr"] else (h, a)
            before = {t: (form[t][-1] if form[t] else "", _streak_len(form[t])) for t in (win, lose)}
            rec[win][0] += 1
            rec[lose][1] += 1
            form[win].append("W")
            form[lose].append("L")
            meet[frozenset((a, h))][win] += 1
            if d >= first_kept:
                notes.append((g, win, lose, before, dict(meet[frozenset((a, h))], _n=pair_n[frozenset((a, h))])))
        if d < first_kept:
            continue
        snap = {t: tuple(rec[t]) for t in db.franchises}
        for g, win, lose, before, season in notes:
            out[d].append(_recap(g, win, lose, before, season, series_of.get(id(g), [g]), snap, div_of, db, user,
                                 postseason, form))
        out[d].sort(key=lambda r: -r["weight"])
        if out[d]:
            out[d][0]["gotd"] = True
    return list(out.items())


def _streak_len(f):
    k = 0
    while k < len(f) and f[-1 - k] == f[-1]:
        k += 1
    return k


def _recap(g, win, lose, before, season, series, snap, div_of, db, user, postseason, form):
    wr, lr = max(g["ar"], g["hr"]), min(g["ar"], g["hr"])
    wh, lh = (g["ah"], g["hh"]) if win == g["away"] else (g["hh"], g["ah"])
    home_won = win == g["home"]
    inn = g["innings"]
    margin = wr - lr
    # a walk-off: the home team won in extras, or in the 9th from behind or tied after the top of it
    walkoff = home_won and (inn > 9 or sum(g["hline"][:8]) <= g["ar"])
    C = db.club
    shared = collections.Counter(db.city(t) for t in db.franchises)

    def c(t):  # the city, or "the White Sox" where two clubs share it (Chicago, New York)
        return db.city(t) if shared[db.city(t)] == 1 else f"the {C(t)}"

    def cap(x):
        return x[0].upper() + x[1:]

    def poss(t):
        x = c(t)
        return x + ("'" if x.endswith("s") else "'s")
    W, L = C(win), C(lose)
    # the headline
    if lh == 0:
        head, weight = f"No-hitter! {W} hold {db.city(lose) if shared[db.city(lose)] == 1 else C(lose)} hitless", 6.0
    elif walkoff:
        head, weight = f"{W} walk off in the {_ord(inn)}", 2.4
    elif inn > 9:
        head, weight = f"{W} outlast {c(lose)} in {inn}", 2.0
    elif lh == 1:
        head, weight = f"{W} one-hit {c(lose)}", 2.6
    elif lr == 0:
        head, weight = f"{W} blank {c(lose)}, {wr}-0", 1.4
    elif margin >= 10:
        head, weight = f"{W} pound {c(lose)}, {wr}-{lr}", 1.3
    elif wr + lr >= 18:
        head, weight = f"{W} win {wr}-{lr} slugfest", 1.4
    elif margin == 1:
        head, weight = f"{W} edge {c(lose)}, {wr}-{lr}", 1.3
    elif margin >= 5:
        head, weight = f"{W} roll past {c(lose)}", 1.0
    else:
        head, weight = f"{W} top {c(lose)}, {wr}-{lr}", 1.0
    where = f"at {db.city(g['home'])}" if not home_won else "at home"
    when = day(g["day"]).strftime("%A")
    text = [f"The {db.full(win)} beat the {db.full(lose)} {wr}-{lr} {where} on {when}"
            + (f" in {inn} innings" if inn > 9 and not walkoff else "")
            + (f", winning it in the bottom of the {_ord(inn)}" if walkoff else "") + "."]
    if lh == 0:
        text.append(f"{cap(c(lose))} didn't get a hit.")
    elif wh < lh:
        text.append(f"{cap(c(win))} won it despite being outhit {lh}-{wh}.")
    elif lr == 0 and lh <= 4:
        text.append(f"{cap(c(lose))} managed only {_num(lh)} hit{'s' if lh != 1 else ''}.")
    elif wh >= 15:
        text.append(f"{cap(c(win))} piled up {wh} hits.")
    le = g["ae"] if lose == g["away"] else g["he"]
    if le >= 3:
        text.append(f"{cap(c(lose))} made {_num(le)} errors.")
    # streaks: made or ended
    ws = _streak_len(form[win]) if form[win] and form[win][-1] == "W" else 0
    lb, ln = before[lose]
    wb, wn = before[win]
    if lb == "W" and ln >= 3:
        text.append(f"The loss snapped {poss(lose)} {_num(ln)}-game winning streak.")
        weight += 0.3
    elif wb == "L" and wn >= 4:
        text.append(f"The win ended a {_num(wn)}-game skid for {c(win)}.")
        weight += 0.3
    elif ws >= 3:
        text.append(f"{cap(c(win))} {'have' if c(win).startswith('the ') else 'has'} won {_num(ws)} straight.")
        weight += 0.1 * ws
    # the series
    played_s = [x for x in series if x["played"] and x["day"] <= g["day"]]
    n_all, k = len(series), len(played_s)
    wins = collections.Counter((x["away"] if x["ar"] > x["hr"] else x["home"]) for x in played_s)
    a_w, b_w = wins[win], wins[lose]
    size = f"{_num(n_all)}-game" if n_all > 1 else ""
    if postseason:  # the playoff series, from every meeting of the two (the schedule then holds only the playoffs)
        sw, sl = season.get(win, 0), season.get(lose, 0)
        need = 3 if season.get("_n", 7) <= 5 else 4  # (a Division Series is 5 games on the schedule)
        if sw >= need:
            text.append(f"{cap(c(win))} {'win' if c(win).startswith('the ') else 'wins'} the series {sw}-{sl}.")
            weight += 0.6
        elif sw == sl:
            text.append(f"The series is tied {sw}-{sl}.")
        else:
            lead = win if sw > sl else lose
            text.append(f"{cap(c(lead))} {'lead' if c(lead).startswith('the ') else 'leads'} the series "
                        f"{max(sw, sl)}-{min(sw, sl)}.")
    elif n_all > 1:
        if k == n_all:
            if b_w == 0:
                text.append(f"{cap(c(win))} swept the {size} series.")
                weight += 0.3
            elif a_w == b_w:
                text.append(f"The teams split the {size} series.")
            else:
                lead = win if a_w > b_w else lose
                text.append(f"{cap(c(lead))} took the {size} series, {max(a_w, b_w)}-{min(a_w, b_w)}.")
        elif k == 1:
            text.append(f"It was the opener of a {size} series.")
        elif a_w == b_w:
            text.append(f"The series is tied {a_w}-{b_w}.")
        else:
            lead = win if a_w > b_w else lose
            text.append(f"{cap(c(lead))} {'lead' if c(lead).startswith('the ') else 'leads'} the series {max(a_w, b_w)}-{min(a_w, b_w)}.")
    sw, sl = season.get(win, 0), season.get(lose, 0)
    if not postseason and sw + sl >= 3 and sw + sl > k:
        if sw == sl:
            text.append(f"The season series is tied {sw}-{sl}.")
        elif sl == 0:
            text.append(f"{cap(c(win))} {'have' if c(win).startswith('the ') else 'has'} won all {_num(sw)} meetings this season.")
        else:
            lead = win if sw > sl else lose
            text.append(f"{cap(c(lead))} {'lead' if c(lead).startswith('the ') else 'leads'} the season series {max(sw, sl)}-{min(sw, sl)}.")
    # the standings after the day's games
    if not postseason:
        bits = []
        for t in (win, lose):
            dv = div_of.get(t)
            mates = [m for m in db.franchises if div_of.get(m) == dv]
            if not mates:
                continue
            pct = lambda m: snap[m][0] / max(1, sum(snap[m]))
            top = max(mates, key=lambda m: (pct(m), snap[m][0]))
            gb = ((snap[top][0] - snap[t][0]) + (snap[t][1] - snap[top][1])) / 2
            tied = gb == 0 and sum(1 for m in mates if ((snap[top][0] - snap[m][0]) + (snap[m][1] - snap[top][1])) == 0) > 1
            spot = ("tied for first" if tied else "in first") if gb == 0 else _back(gb)
            bits.append(f"the {C(t)} ({snap[t][0]}-{snap[t][1]}) are {spot} in the {DIVISIONS[dv]}"
                        if 0 <= dv < 6 else "")
            if gb <= 2:
                weight += 0.25
        bits = [b for b in bits if b]
        if bits:
            text.append(cap("; ".join(bits)) + ".")
    if user is not None and user in (win, lose):
        weight += 2.0
    return dict(game=g, win=win, lose=lose, head=head, body=" ".join(text), weight=weight, gotd=False,
                mine=user in (win, lose))


# ---- the page ---------------------------------------------------------------------------------------------------
# laid out like a baseball site's front page from 2006: a charcoal bar with the wordmark, a gray bar of sections
# with the Team Sites list, three columns (scores and your club / the top story, standings and matchups / a navy
# rail of headlines), boxes headed in blue with an orange chevron, Tahoma and Verdana at 11 pixels
CSS = """
*{box-sizing:border-box}
body{margin:0;background:#fff;color:#000;font:11px/1.35 Verdana,Tahoma,Arial,Helvetica,sans-serif}
a{color:#00c;text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:1000px;margin:0 auto;background:#fff}
.util{height:26px;display:flex;justify-content:flex-end;align-items:center;gap:14px;padding:0 10px;font:10px Tahoma,Arial,sans-serif;color:#666}
.util b{color:#000}
.bar{background:#333;height:72px;display:flex;justify-content:space-between;position:relative}
.mark{width:390px;height:52px;margin-top:14px;background:repeating-linear-gradient(115deg,#093e9c 0 18px,#0b47b0 18px 22px);
 border-top:1px solid #4c78cf;border-bottom:1px solid #001f63;display:flex;align-items:center;padding-left:8px;position:relative}
.mark img{width:78px;height:78px;margin:-10px 6px -16px 0;filter:drop-shadow(2px 3px 2px rgba(0,0,0,.6))}
.mark b{display:block;font:italic 900 27px/1 'Arial Black',Arial,sans-serif;color:#fff;letter-spacing:-1px;text-shadow:2px 2px 0 #001a55}
.mark span{display:block;font:bold 10px Tahoma,sans-serif;color:#fc3;text-transform:uppercase;letter-spacing:2px;margin-top:2px}
.recap{padding:8px 0;border-top:1px dotted #aaa}.recap:first-child{border:0}
.recap table.line{width:auto;background:#fff;border:1px solid #bbb;margin-bottom:5px}
.recap td{border:0;padding:2px 5px;text-align:center}.recap td:first-child{text-align:left;min-width:62px}
.recap .w td{font-weight:bold}.recap th{background:#dcdcdc;border:0;text-align:center;padding:2px 5px}
.recap th:first-child{text-align:left}.recap .rhe{border-left:1px solid #bbb}
.recap b{display:block;font:bold 13px Arial,Helvetica,sans-serif;color:#006;margin-bottom:2px}
.recap p{margin:0}
.gotd{background:#fff7c8;margin:0 -7px;padding:8px 7px}
.gotd .kick{display:block;font:bold 9px Tahoma,sans-serif;color:#c00;text-transform:uppercase;letter-spacing:1px}
.gotd b{font-size:16px}
a.score{display:block;color:#000;text-decoration:none}a.score:hover{border-color:#00c}
.dpane{display:none}.dpane.on{display:block}
.lpane{display:none}.lpane.on{display:block}
.awpane{display:none}.awpane.on{display:block}ol.race{margin:0;padding-left:22px}ol.race li{padding:4px 0;border-bottom:1px solid #ddd}
.tfilter{margin:6px 0 10px;display:flex;flex-wrap:wrap;gap:6px;align-items:center}.tfilter select{font:11px Verdana,sans-serif}
.tk button{border:1px solid #999;background:#fff;font:bold 11px Tahoma,Arial,sans-serif;color:#00c;padding:2px 6px;cursor:pointer}
.tk button.on{background:#212c5d;color:#fff;border-color:#212c5d}
.tday h3{font:bold 12px Arial,Helvetica,sans-serif;color:#333;background:#dcdcdc;margin:8px 0 2px;padding:3px 6px}
.spane{display:none}.spane.on{display:block;overflow-x:auto}
table.stats th{cursor:pointer;white-space:nowrap}table.stats th.sorted{background:#dcdcdc}
table.stats td:nth-child(2),table.stats th:nth-child(2),table.stats td:nth-child(3),table.stats th:nth-child(3){text-align:left}
#stats tr.nq{display:none}#stats.all tr.nq{display:table-row}#stats tr.nq td{color:#777}
a.more2{display:block;text-align:right;padding:0 7px 6px;font-weight:bold}
.teampage{display:none;padding:6px 4px 0}
.bracket{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;align-items:center}
.bcol{display:flex;flex-direction:column;gap:10px;justify-content:space-around;height:100%}
.pbox{display:block;border:1px solid #c9d3e3;background:#f6f8fc;padding:4px 6px;color:#000;text-decoration:none}
.pbox.tbd{background:#fafafa;color:#888;border-style:dashed}
.pbox .pt{display:block;font-weight:bold;font-size:11px;color:#1f4e9c;margin-bottom:2px}
.pbox .pr{display:flex;justify-content:space-between;font-size:12px;padding:1px 0}
.pbox .pr.w{font-weight:bold}.pbox .pr.out{color:#888}.pbox .pr.out a{color:#888}
table.pbrief th{text-align:left;padding-top:5px;color:#1f4e9c}table.pbrief tr.w td{font-weight:bold}
table.pbrief tr.out td,table.pbrief tr.out a{color:#888}table.pbrief td:nth-child(2){text-align:right;padding:0 6px}
@media (max-width:700px){.bracket{grid-template-columns:1fr 1fr}}
#issues{display:flex;gap:10px;align-items:center}#issues select{font:10px Tahoma,Arial,sans-serif;max-width:190px}
#issues a b{color:#c8102e}
.sched{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:4px 14px}.sched h3{margin:6px 0 2px;font-size:13px}
.sched tr.later td{color:#666}table.ser th{text-align:left}table.ser td:nth-child(n+2){text-align:center}table.ser th:nth-child(n+2){text-align:center}
.mv{font-size:9px;color:#888;white-space:nowrap}.mv.up{color:#1a7f37}.mv.dn{color:#c8102e}
table.pwr td.rk{font-weight:bold;text-align:right}table.pwr td.note{text-align:left;color:#444;max-width:330px}
.races{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:10px}.races h3{margin:4px 0;font-size:13px}
.career td,.career th{text-align:right}.career td:nth-child(-n+2),.career th:nth-child(-n+2){text-align:left}
.career .tot td{font-weight:bold;border-top:2px solid #999}
.teampage .mb{overflow-x:auto}.teampage .back{display:inline-block;margin:2px 0 8px;font-weight:bold}
.thead{display:flex;gap:14px;align-items:center}.thead .lgb{float:none;margin:0;flex:none}
.thead h1{font:bold 24px Arial,Helvetica,sans-serif;color:#006;margin:0 0 4px}.thead p{margin:2px 0}
.roster td:nth-child(n+3),.roster th:nth-child(n+3){text-align:right}.roster{margin-bottom:8px}
.roster td:nth-child(2),.roster th:nth-child(2){text-align:left;width:40%}
.res td{text-align:left}.res td:last-child{text-align:right}.res td:first-child{width:22%}
.res .w{color:#060;font-weight:bold}.res .l{color:#a00;font-weight:bold}
@media (max-width:760px){.teampage .pair{flex-direction:column}}.lt button{font-size:11px;padding:3px 2px}
.subtabs.lt{padding:4px 0 0}.subtabs.lt button{padding:0 3px}
#leaders0 td,#leaders1 td{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:130px}
.top{display:flex;align-items:flex-start;padding:8px 10px 0 0;font:bold 11px Tahoma,Arial,sans-serif}
.top a{color:#fff;padding:0 9px;border-left:1px solid #777}.top a:first-child{border:0}.top a:hover{color:#fc3;text-decoration:none}
.sub{height:24px;background:linear-gradient(#e2e2e2,#b9b9b9);border-bottom:1px solid #888;display:flex;align-items:center;font:bold 11px Tahoma,Arial,sans-serif}
.sub>a{color:#006;padding:0 9px;border-left:1px solid #999}
.teams{position:relative;height:100%}
.teams>button{height:100%;border:0;background:linear-gradient(#5a5a5a,#2a2a2a);color:#fff;font:bold 11px Tahoma,Arial,sans-serif;padding:0 26px 0 12px;cursor:pointer;position:relative}
.teams>button:after{content:"";position:absolute;right:10px;top:9px;border:4px solid transparent;border-top-color:#fff}
.drop{display:none;position:absolute;z-index:5;left:0;top:24px;background:#fff;border:1px solid #666;box-shadow:2px 2px 4px rgba(0,0,0,.35);width:300px;padding:6px 0}
.teams:hover .drop,.teams:focus-within .drop{display:flex}
.drop div{flex:1;padding:0 6px}.drop div+div{border-left:1px solid #ccc}
.drop a{display:block;padding:3px 4px;color:#006;font:bold 11px Tahoma,Arial,sans-serif}.drop a:hover{background:#eef}
.drop small{display:block;color:#999;font:bold 9px Tahoma,sans-serif;text-transform:uppercase;padding:0 4px 3px}
.cols{display:flex;align-items:flex-start;gap:6px;padding:6px 0 0 4px}
.left{width:180px;flex:none}.mid{flex:1;min-width:0}
.rail{width:316px;flex:none;background:#1a2964;align-self:stretch;padding:8px 6px 12px;margin-left:auto}
.mod{border:1px solid #b2b2b2;border-top:0;border-radius:6px 6px 3px 3px;background:#f2efef;margin-bottom:6px;overflow:hidden}
.mh{position:relative;background:linear-gradient(#2c58b8 0,#214498 15%,#212c5d 55%,#283879 100%);color:#fff;
 font:15px/21px Impact,'Arial Narrow',Arial,sans-serif;letter-spacing:.6px;text-transform:uppercase;padding:0 8px 0 22px;
 text-shadow:1px 1px 0 #000;border-radius:6px 6px 0 0;height:22px;white-space:nowrap;overflow:hidden}
.mh:before{content:"";position:absolute;left:8px;top:5px;width:8px;height:12px;background:#f8aa34;
 clip-path:polygon(0 0,45% 0,100% 50%,45% 100%,0 100%,55% 50%)}
.mh .r{position:absolute;right:8px;top:0;font:bold 10px/22px Tahoma,Arial,sans-serif;letter-spacing:0;text-transform:none;color:#f8aa34;text-shadow:none}
.mb{padding:6px 7px}
.pair{display:flex;gap:6px}.pair>.mod{flex:1;min-width:0}
.lg{display:inline-block;width:16px;height:16px;margin-right:4px;vertical-align:-4px;background:center/contain no-repeat}
.lgb{float:left;width:100px;height:100px;margin:2px 10px 4px 0;background:center/contain no-repeat}
.kind{font:bold 9px Tahoma,Arial,sans-serif;color:#c00;text-transform:uppercase}
.date{color:#666;font-size:10px}
.lead h1{font:bold 19px/1.15 Arial,Helvetica,sans-serif;color:#006;margin:3px 0 5px}
.lead p{font-size:12px;margin:0 0 6px}
.more{clear:both;border-top:1px solid #ccc;margin-top:6px;padding-top:5px;display:grid;grid-template-columns:1fr 1fr;gap:4px 8px}
.more a{font-weight:bold}
.heads{list-style:none;margin:0;padding:0}.heads li{padding:6px 0;border-top:1px dotted #aaa}.heads li:first-child{border:0}
.heads b{display:block;font:bold 13px Arial,Helvetica,sans-serif;color:#006;margin:1px 0 2px}
.heads p{margin:0}
.mine{background:#fff7c8}
.tabs{display:flex;background:#cac9cf}.tabs button{flex:1;border:0;background:none;font:bold 12px Arial,sans-serif;color:#00c;padding:4px;cursor:pointer}
.tabs button.on{background:#f2efef;color:#006}
.tabs button.on:after{content:"";display:inline-block;margin-left:5px;border:4px solid transparent;border-top-color:#c00;vertical-align:-1px}
.subtabs{text-align:center;padding:5px 0 2px}.subtabs button{border:0;background:none;font:12px Arial,sans-serif;color:#00c;padding:0 5px;cursor:pointer}
.subtabs button.on{font-weight:bold;color:#006}
.pane{display:none}.pane.on{display:block}
table{width:100%;border-collapse:collapse;font-size:11px}
th{font:bold 10px Tahoma,Arial,sans-serif;color:#333;text-align:right;padding:3px 4px;border-bottom:1px solid #999}
td{padding:3px 4px;border-bottom:1px solid #ddd;text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
td a{color:#000}
.scores{display:grid;grid-template-columns:1fr 1fr;gap:4px}.score{border:1px solid #bbb;background:#fff}
.score div{display:flex;justify-content:space-between;padding:1px 4px}.score .w{font-weight:bold}
.score .st{background:#dcdcdc;color:#333;font:bold 9px Tahoma,sans-serif;text-transform:uppercase;padding:1px 5px}
.match{padding:4px 0;border-bottom:1px solid #ddd}.match:last-child{border:0}
.list{list-style:none;margin:0;padding:0}.list li{padding:4px 0;border-bottom:1px solid #ddd}
.list li:last-child{border:0}
.big{font-size:13px;font-weight:bold}
.rail .mod{background:none;border:0;margin-bottom:10px}
.rail .mh{background:none;border-radius:0;padding-left:16px}.rail .mh:before{left:2px}
.rail ul{list-style:none;margin:0;padding:0;border:1px solid #131925;border-width:1px 0}
.rail li{background:#445a83;border-bottom:1px solid #131925;border-top:1px solid #5b709a;color:#fff;padding:3px 8px 3px 18px;position:relative;font:11px/1.35 Verdana,Arial,sans-serif}
.rail li:before{content:"";position:absolute;left:8px;top:8px;width:4px;height:4px;background:#fff;border-radius:2px}
.rail li a{color:#fff}.rail li .date{color:#c7ceda}
.rail li.mine{background:#6b5a1e}
.rail .x{display:block;color:#f8aa34;font:bold 11px Tahoma,Arial,sans-serif;padding:5px 8px 0}
.foot{margin-top:12px;border-top:1px solid #ccc}
.foot .links{background:#ccc;text-align:center;padding:4px;font:11px Tahoma,Arial,sans-serif}
.foot .links a{color:#006;margin:0 14px}
.foot .fine{background:#000;color:#aaa;font:10px Tahoma,Arial,sans-serif;padding:10px 14px}
@media (max-width:760px){.wrap{width:auto}.cols{flex-direction:column;align-items:stretch;padding:6px}.mid{order:-1}.left,.mid,.rail{width:auto;margin:0}
 .bar{height:auto;flex-direction:column}.mark{width:auto;margin:0;height:58px}.mark img{width:50px;height:50px;margin:0 6px 0 0}.top{flex-wrap:wrap;padding:6px}.top a{padding:2px 6px}
 .pair{flex-direction:column}.util{display:none}.sub{overflow-x:auto;white-space:nowrap}.lgb{width:72px;height:72px}}
"""

AP_MONTHS = ("Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec.")

SCRIPT = """
var AW={awf:[0,0],awp:[0,0]};function pickaw(g,l,c){if(l!==null)AW[g][0]=l;if(c!==null)AW[g][1]=c;
 tab(g+'l',AW[g][0]);tab(g+'c',AW[g][1]);document.querySelectorAll('.awpane.'+g).forEach(function(p){
 p.classList.toggle('on',p.id==g+AW[g][0]+AW[g][1]);});}
var TK='all';function pickT(k){TK=k;tab('tk',k);filterT();}
function filterT(){var t=document.getElementById('tteam').value,any=false;
 document.querySelectorAll('#tlist .tday').forEach(function(d){var shown=0;
  d.querySelectorAll('li').forEach(function(li){var ok=(TK=='all'||li.dataset.k==TK)&&(!t||li.dataset.t.indexOf(' '+t+' ')>=0);
   li.style.display=ok?'':'none';if(ok)shown++;});d.style.display=shown?'':'none';if(shown)any=true;});
 document.getElementById('tnone').style.display=any?'none':'';}
var SS=[0,0];function pickstats(l,k){if(l!==null)SS[0]=l;if(k!==null)SS[1]=k;tab('sl',SS[0]);tab('sk',SS[1]);
 document.querySelectorAll('.spane').forEach(function(p){p.classList.toggle('on',p.id=='s'+SS[0]+SS[1]);});}
function renumber(){document.querySelectorAll('table.stats tbody').forEach(function(tb){var n=0;
 [].forEach.call(tb.rows,function(r){if(getComputedStyle(r).display!='none')r.cells[0].textContent=++n;});});}
function sortT(th){var tb=th.closest('table').tBodies[0],i=[].indexOf.call(th.parentNode.children,th);if(i==0)return;
 var down=th.dataset.dir!='down';[].forEach.call(th.parentNode.children,function(x){delete x.dataset.dir;x.classList.remove('sorted');});
 th.dataset.dir=down?'down':'up';th.classList.add('sorted');var text=i<=2;
 var rows=[].slice.call(tb.rows).sort(function(a,b){var x=a.cells[i].dataset.v,y=b.cells[i].dataset.v;
  var c=text?(x<y?-1:x>y?1:0):(+x-+y);return text?(down?c:-c):(down?-c:c);});
 rows.forEach(function(r){tb.appendChild(r);});renumber();}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function tm(i,txt){return i<0?esc(txt):"<a href='#team-"+i+"'><i class='lg lg"+i+"'></i>"+esc(txt)+"</a>";}
function showPlayer(k){var el=document.getElementById('playerpage'),p=PD[k],h=[];
 h.push("<a class=back href='#top'>&lsaquo; Back to the front page</a>");
 if(!p){el.innerHTML=h.join('')+"<p>No page for that player.</p>";return el;}
 var now=NOW;
 h.push("<div class=mod><div class=mh>"+esc(p.n)+"</div><div class='mb thead'>"+(p.t>=0?"<i class='lgb lg"+p.t+"b'></i>":"")+
  "<div><h1>"+esc(p.n)+"</h1><p class=big>"+esc(p.pos)+(p.t>=0?(p.pos?" &middot; ":"")+tm(p.t,document.querySelector('#team-'+p.t+' h1').textContent)+(p.f?" ("+esc(p.f)+")":""):"")+
  "</p><p>"+p.bio+"</p>"+(p.ms&&p.ms.length?"<p><b>Milestone watch:</b> "+p.ms.map(esc).join(" &middot; ")+"</p>":"")+"</div></div></div>");
 if(p.status&&p.status.length){h.push("<div class=mod><div class=mh>Status</div><div class=mb><ul class=list>");
  p.status.forEach(function(x){h.push("<li><b>"+esc(x[0])+":</b> "+esc(x[1])+"</li>");});h.push("</ul></div></div>");}
 var head=p.b?['Year','Team','AB','H','HR','RBI','R','SB','BB','SO','AVG','OBP','SLG','OPS','OPS+']:['Year','Team','G','W','L','SV','IP','ER','SO','BB','ERA','ERA+'];
 var t=["<div class=mod><div class=mh>"+(p.b?'Batting':'Pitching')+" by season</div><div class=mb><table class=career><tr>"];
 head.forEach(function(x){t.push('<th>'+x+'</th>');});t.push('</tr>');var tot=[],full=true,n=0;
 function cell(r,j){return !p.b&&j==6?Math.floor(r[j]/3)+'.'+r[j]%3:r[j];}
 function r3(v){return v.toFixed(3).replace(/^0/,'');}
 function rates(r,known){if(!p.b)return '<td>'+(r[6]?(27*r[7]/r[6]).toFixed(2):'&ndash;')+'</td>';
  var avg=r[2]?r3(r[3]/r[2]):'&ndash;';if(!known||!r[2])return '<td>'+avg+'</td><td>&ndash;</td><td>&ndash;</td><td>&ndash;</td>';
  var ob=(r[3]+r[8])/(r[2]+r[8]+r[11]),sl=r[10]/r[2];return '<td>'+avg+'</td><td>'+r3(ob)+'</td><td>'+r3(sl)+'</td><td>'+r3(ob+sl)+'</td>';}
 var last=p.b?10:10;
 p.rows.forEach(function(r){if((r.length==13)!=!!p.b)return;var plus=r[r.length-1];n++;var cls=r[0]==now?" class=mine":"",tt=TT[r[1]]||['?',-1];
  var known=!p.b||(r[8]+r[9]+r[10]+r[11]>0)||!r[3];if(!known)full=false;
  t.push('<tr'+cls+'><td>'+r[0]+'</td><td>'+tm(tt[1],tt[0])+'</td>');
  for(var j=2;j<r.length-1;j++){tot[j]=(tot[j]||0)+r[j];if(j<last)t.push('<td>'+(p.b&&j>=8&&!known?'&ndash;':cell(r,j))+'</td>');}
  t.push(rates(r,known)+'<td>'+(plus===null?(!p.b&&!r[7]&&r[6]?'&infin;':'&ndash;'):plus)+'</td></tr>');});
 if(p.car){var c=p.car,r;  // the whole career (the rows above are his last 16 seasons at most)
  if(p.b){r=[0,0,c[1],c[2],c[3],c[4],c[5],c[6]];t.push('<tr class=tot><td>Career</td><td>'+c[0]+' G</td>');
   for(var j=2;j<8;j++)t.push('<td>'+r[j]+'</td>');t.push('<td>&ndash;</td><td>&ndash;</td>'+rates(r,false)+'<td></td></tr>');}
  else{r=[0,0,c[0],c[1],c[2],c[3],c[4],c[5],c[6],c[7]];t.push('<tr class=tot><td>Career</td><td></td>');
   for(var j=2;j<10;j++)t.push('<td>'+cell(r,j)+'</td>');t.push(rates(r,true)+'<td></td></tr>');}}
 else if(n){t.push('<tr class=tot><td>Total</td><td></td>');for(var j=2;j<tot.length&&j<last;j++)t.push('<td>'+(p.b&&j>=8&&!full?'&ndash;':cell(tot,j))+'</td>');
  t.push(rates(tot,full)+'<td></td></tr>');}
 t.push('</table>'+(p.b&&!full?"<p class=date>BB, SO, OBP, SLG, OPS and OPS+ are kept for the seasons played in this dynasty only.</p>":"")+'</div></div>');h.push(t.join(''));
 if(p.news.length){h.push("<div class=mod><div class=mh>In the news</div><div class=mb><ul class=heads>");
  p.news.forEach(function(n){h.push("<li><span class=kind>"+esc(n[1])+"</span> <span class=date>"+n[0]+"</span><b>"+esc(n[2])+"</b><p>"+esc(n[3])+"</p></li>");});
  h.push("</ul></div></div>");}
 el.innerHTML=h.join('');return el;}
function tab(g,i){document.querySelectorAll('[data-g="'+g+'"]').forEach(function(b){b.classList.toggle('on',b.dataset.i==i)});}
function pick(lg,dv){tab('lg',lg);tab('dv',dv);document.querySelectorAll('.pane').forEach(function(p){
 p.classList.toggle('on',p.id=='p'+lg+dv)});window._lg=lg;window._dv=dv;}
"""


def render(news):
    db = news["db"]
    e = html.escape
    used = {}  # team -> css class of its logo (each logo is in the page once, in its style)

    def lg(t, big=False):
        if t not in db.franchises:
            return ""
        k = (t, big)
        if k not in used:
            url = db.logo(t, big)
            used[k] = (f"lg{db.franchises.index(t)}{'b' if big else ''}", url) if url else None
        return f"<i class='{'lgb' if big else 'lg'} {used[k][0]}'></i>" if used[k] else ""
    fmt = lambda d: f"{d.strftime('%A, %B')} {d.day}, {d.year}"
    short = lambda d: f"{AP_MONTHS[d.month - 1]} {d.day}"
    user = news["user"]
    heads = news["headlines"]

    def gid(g):
        return f"g{g['day']}_{g['home'] & 0xFFFFFF:x}"

    fr = {t: i for i, t in enumerate(db.franchises)}
    need = set()  # the players linked to: each gets a page (player_data)

    def pn(k):
        return news["names"].get(k) or db.name(k) or ""

    def abbrev(full):
        first, _, rest = full.partition(" ")
        return f"{first[0]}. {rest}" if rest and first else full

    def PL(k, text=None):
        need.add(k)
        return f"<a class=pl href='#p-{k:x}'>{e(text or pn(k) or '?')}</a>"

    def TM(t, text=None):
        return f"<a href='#team-{fr[t]}'>{e(text or db.club(t))}</a>" if t in fr else e(text or db.club(t))

    def linkify(text, players=(), teams=()):
        """text with the clubs' full names and the players' names linked to their pages"""
        subs = {}
        for t in teams:
            t = db.org_of.get(t, t)
            if t in fr:
                subs[e(db.full(t))] = f"<a href='#team-{fr[t]}'>{e(db.full(t))}</a>"
        for k in players:
            n = pn(k)
            if n:
                need.add(k)
                subs[e(n)] = f"<a class=pl href='#p-{k:x}'>{e(n)}</a>"
        t = e(text)
        if not subs:
            return t
        rx = re.compile("|".join(re.escape(x) for x in sorted(subs, key=len, reverse=True)))
        return rx.sub(lambda m: subs[m.group(0)], t)

    def story(h):
        return linkify(h["body"], h.get("players", ()), list(h.get("raw_teams", ())) + list(h.get("teams", ())))
    post = news["postseason"]
    out = ["<!doctype html><html lang=en><head><meta charset=utf-8>",
           "<meta name=viewport content='width=device-width,initial-scale=1'>",
           f"<title>MVP Baseball League News: {e(news['name'])}</title><style>{CSS}</style></head><body><div class=wrap>",
           f"<div class=util><span>{e(news['name'])} &middot; {e(news['kind'])}</span>"
           + "<span id=issues></span>"
           + (f"<b>{fmt(news['today'])}</b>" if news["today"] else "") + "</div>",
           "<div class=bar><div class=mark>" + (f"<img src='{db.badge()}' alt=''>" if db.badge() else "")
           + "<div><b>MVP Baseball</b><span>League News</span></div></div>"
           f"<div class=top><a href='#news'>Headlines</a><a href='#{'recaps' if news['days'] else 'scores'}'>Scores</a>"
           "<a href='#standings'>Standings</a><a href='#matchups'>Matchups</a>"
           + ("<a href='#stats'>Stats</a>" if news["stats"] else "")
           + "<a href='#transactions'>Transactions</a><a href='#injuries'>Injuries</a></div></div>"]
    # Team Sites: every club, American League then National, each to its row in the standings
    leagues = [[], []]
    for d_i, d in enumerate(news["divisions"]):
        for r in d["rows"]:
            leagues[d_i // 3].append(r["team"])
    out.append("<div class=sub><div class=teams><button>Team Sites</button><div class=drop>")
    for i, name in enumerate(("American", "National")):
        out.append(f"<div><small>{name} League</small>")
        for t in sorted(leagues[i], key=db.city):
            out.append(f"<a href='#team-{db.franchises.index(t)}'>{lg(t)}{e(db.city(t))}</a>")
        out.append("</div>")
    out.append("</div></div><a href='#scores'>Scoreboard</a><a href='#standings'>Standings</a>"
               + ("<a href='#stats'>Stats</a>" if news["stats"] else "") +
               "<a href='#matchups'>Schedule</a><a href='#transactions'>Transactions</a><a href='#injuries'>Injuries</a>"
               + ("<a href='#farm'>Farm</a>" if news.get("farm") else "")
               + ("<a href='#playoffs'>Playoffs</a>" if news.get("playoffs") else "") + "<a href='#news'>News</a></div>")
    out.append("<div class=cols><div class=left>")

    # ---- left: scoreboard, your club, hot and cold
    out.append("<div class=mod id=scores><div class=mh>Scoreboard</div><div class=mb>")
    if news["results"]:
        out.append(f"<div class=date style='margin-bottom:4px'>{fmt(news['today'])}</div><div class=scores>")
        for g in news["results"]:
            aw, hw = g["ar"] > g["hr"], g["hr"] > g["ar"]
            fin = "Final" + (f"/{g['innings']}" if g["innings"] > 9 else "")
            out.append(f"<a class=score href='#{gid(g)}' onclick='day0()'><div class=st>{fin}</div>"
                       f"<div class={'w' if aw else ''}><span>{lg(g['away'])}{e(db.short(g['away']))}</span><span>{g['ar']}</span></div>"
                       f"<div class={'w' if hw else ''}><span>{lg(g['home'])}{e(db.short(g['home']))}</span><span>{g['hr']}</span></div></a>")
        out.append("</div>")
    else:
        out.append("No final scores yet.")
    out.append("</div></div>")
    if user in db.franchises and post and news.get("playoffs"):
        mine = [x for x in news["playoffs"] if user in (x["top"], x["other"])]
        lines = []
        for x in mine:
            them = x["other"] if x["top"] == user else x["top"]
            if x["winner"] == user:
                lines.append(f"Won the {x['name']} {x['wins'][user]}-{x['wins'][them]} over the {TM(them)}")
            elif x["winner"]:
                lines.append(f"Lost the {x['name']} {x['wins'][user]}-{x['wins'][them]} to the {TM(them)}")
            else:
                lines.append(f"{x['name']} vs. the {TM(them)}: {e(series_line(x, db.club))}")
        if not mine:
            lines.append("Not in the playoffs this year.")
        out.append(f"<div class=mod><div class=mh>Your club</div><div class=mb>{lg(user)}<span class=big>"
                   f"{TM(user, db.full(user))}</span><br>" + "<br>".join(lines) + "</div></div>")
    if user in db.franchises and not post:
        row, div = next(((r, d) for d in news["divisions"] for r in d["rows"] if r["team"] == user), (None, None))
        if row:
            place = div["rows"].index(row) + 1
            nxt = next((g for g in news["upcoming"] if user in (g["away"], g["home"])), None)
            out.append(f"<div class=mod><div class=mh>Your club</div><div class=mb>{lg(user)}<span class=big>"
                       f"{TM(user, db.full(user))}</span><br>{row['w']}-{row['l']}, "
                       f"{['first', 'second', 'third', 'fourth', 'fifth', 'sixth'][place - 1]} in the {e(div['name'])}"
                       + ("" if row["gb"] == 0 else f", {row['gb']:g} back") + f"<br>Last 10: {row['last10']} &middot; "
                       f"Streak: {row['streak'] or '&ndash;'}<br>Home {row['home']} &middot; Road {row['road']}"
                       + (f"<br>Next: {'at ' + TM(nxt['home']) if nxt['away'] == user else 'vs. ' + TM(nxt['away'])}"
                          if nxt else "") + "</div></div>")
    if news["leaders"]:  # this season's leaders, as the game's Around the League shows them: hitting, then pitching
        year = f"{news['leaders']['year']} " if news["leaders"]["last_season"] or news["leaders"]["final"] else ""
        names_ = news["names"]
        for box, (title, cats) in enumerate(((f"{year}Hitting" if year else "Hitting leaders", ("AVG", "HR", "RBI", "OPS")),
                                            (f"{year}Pitching" if year else "Pitching leaders", ("W", "ERA", "SV", "SO")))):
            out.append(f"<div class=mod id=leaders{box}><div class=mh>{title}</div><div class='tabs lt'>" + "".join(
                f"<button data-g=llg{box} data-i={i} onclick='pickl({box},{i},null)'>{n}</button>"
                for i, n in enumerate(("AL", "NL"))) + "</div><div class='subtabs lt'>" + "".join(
                f"<button data-g=lcat{box} data-i={i} onclick='pickl({box},null,{i})'>{c}</button>"
                for i, c in enumerate(cats)) + "</div><div class=mb>")
            for lgi in (0, 1):
                for ci, c in enumerate(cats):
                    rows_ = news["leaders"].get(lgi, {}).get(c, [])
                    out.append(f"<div class='lpane lp{box}' id=l{box}{lgi}{ci}><table>")
                    for rank, (k, t, v) in enumerate(rows_, 1):
                        short_name = abbrev(names_.get(k) or db.name(k) or "?")
                        cls = " class=mine" if t == user else ""
                        out.append(f"<tr{cls}><td>{rank}. {lg(t)}{PL(k, short_name)}</td><td>{e(v)}</td></tr>")
                    if not rows_:
                        out.append("<tr><td>No one yet</td><td></td></tr>")
                    out.append("</table></div>")
            out.append("<a class=more2 href='#stats'>Full list &rsaquo;</a></div></div>")
    near, reached = news.get("milestones", ([], []))
    if near or reached:  # careers close to a round number, and the ones passed this season
        ab = {"home runs": "HR", "hits": "H", "RBIs": "RBI", "stolen bases": "SB", "wins": "W", "saves": "SV", "strikeouts": "K"}
        out.append("<div class=mod id=msbox><div class=mh>Milestone watch</div><div class=mb><table>")
        for k, t, label, m, gap in near[:8]:
            out.append(f"<tr><td>{lg(t)}{PL(k, abbrev(pn(k)))}</td><td>{gap} {ab[label]} from {m:,}</td></tr>")
        if reached:
            out.append("<tr><th colspan=2>Reached this season</th></tr>")
            for k, t, label, m in reached[:5]:
                out.append(f"<tr><td>{lg(t)}{PL(k, abbrev(pn(k)))}</td><td>{m:,} {ab[label]}</td></tr>")
        out.append("</table></div><a class=more2 href='#milestones'>All milestones &rsaquo;</a></div>")
    if news.get("farm", {}).get("prospects"):  # the farm's best young players
        out.append("<div class=mod id=farmbox><div class=mh>Down on the farm</div><div class=mb><table>")
        for k, t, age, text in news["farm"]["prospects"][:6]:
            out.append(f"<tr><td>{lg(db.org_of.get(t, t))}{PL(k, abbrev(pn(k)))}<br><span class=date>"
                       f"{e(db.tag(t))}: {e(text.split(', ')[0] if ',' in text else text)}</span></td></tr>")
        out.append("</table></div><a class=more2 href='#farm'>Farm report &rsaquo;</a></div>")
    if not post and news["games_played"]:
        rows = [r for d in news["divisions"] for r in d["rows"] if r["streak"]]
        hot = sorted((r for r in rows if r["streak"][0] == "W"), key=lambda r: -int(r["streak"][1:]))[:4]
        cold = sorted((r for r in rows if r["streak"][0] == "L"), key=lambda r: -int(r["streak"][1:]))[:4]
        out.append("<div class=mod><div class=mh>Hot &amp; Cold</div><div class=mb><table>")
        for label, group in (("Winning streaks", hot), ("Losing streaks", cold)):
            out.append(f"<tr><th colspan=2>{label}</th></tr>")
            for r in group:
                out.append(f"<tr><td>{lg(r['team'])}{TM(r['team'])}</td><td>{r['streak']}</td></tr>")
        out.append("</table></div></div>")

    # ---- middle: the top story, standings and matchups, all the headlines, the wire, injuries
    out.append("</div><div class=mid>")
    out.append("<div class=mod><div class=mh>Top story</div><div class='mb lead'>")
    if heads:
        h = heads[0]
        big = next((t for t in h["teams"] if t in db.franchises), None)
        out.append(f"{lg(big, True) if big else ''}<span class=kind>{e(h['kind'])}</span> "
                   f"<span class=date>{short(day(h['day']))}</span><h1>{e(h['head'])}</h1><p>{story(h)}</p>")
        if len(heads) > 1:
            out.append("<div class=more>")
            for i, h in enumerate(heads[1:5], 1):
                t = next((t for t in h["teams"] if t in db.franchises), None)
                out.append(f"<div>{lg(t) if t else ''}<a href='#s{i}'>{e(h['head'])}</a></div>")
            out.append("</div>")
    else:
        out.append("<p>No news yet: play a few days and come back.</p>")
    out.append("</div></div><div class=pair>")
    # standings, tabbed: American / National, then East / Central / West / Wild Card
    mine_dv = next((i for i, d in enumerate(news["divisions"]) for r in d["rows"] if r["team"] == user), 2)
    first = (mine_dv // 3, {0: 2, 1: 1, 2: 0}[mine_dv % 3])  # (league, tab: East, Central, West, Wild Card)
    out.append("<div class=mod id=standings><div class=mh>Standings</div>")
    if post and news.get("playoffs"):
        out.append("<div class=mb><table class=pbrief>")
        for sr in news["playoffs"]:
            out.append(f"<tr><th colspan=2>{sr['name']}</th><td class=date>{e(series_line(sr, db.club))}</td></tr>")
            for t in (sr["top"], sr["other"]):
                won = sr["winner"] == t
                out.append(f"<tr class='{'w' if won else ('out' if sr['winner'] else '')}'><td>{lg(t)}{TM(t)}</td>"
                           f"<td>{sr['wins'][t]}</td><td></td></tr>")
        out.append("</table><a href='#playoffs' style='display:block;margin-top:5px'>The bracket and every game "
                   "&rsaquo;</a></div></div>")
    elif post:
        out.append("<div class=mb>It's the postseason: the season's standings are put away until next year.</div></div>")
    else:
        out.append("<div class=tabs>" + "".join(
            f"<button data-g=lg data-i={i} onclick='pick({i},window._dv)'>{n}</button>"
            for i, n in enumerate(("American", "National"))) + "</div><div class=subtabs>" + "".join(
            f"<button data-g=dv data-i={i} onclick='pick(window._lg,{i})'>{n}</button>"
            for i, n in enumerate(("East", "Central", "West", "Wild Card"))) + "</div><div class=mb>")
        for lgi in (0, 1):
            for tab_i, dv in enumerate((2, 1, 0)):
                d = news["divisions"][3 * lgi + dv]
                out.append(f"<div class=pane id=p{lgi}{tab_i}><table><tr><th>{e(d['name'])}</th><th>W</th><th>L</th>"
                           "<th>Pct</th><th>GB</th><th>L10</th></tr>")
                for r in d["rows"]:
                    gb = "&ndash;" if r["gb"] == 0 else f"{r['gb']:g}"
                    cls = " class=mine" if r["team"] == user else ""
                    out.append(f"<tr{cls} id=t{db.franchises.index(r['team'])}><td>{lg(r['team'])}"
                               f"<a href='#team-{db.franchises.index(r['team'])}'>{e(db.club(r['team']))}</a></td><td>{r['w']}</td><td>{r['l']}</td>"
                               + f"<td>{r['pct']:.3f}".replace("0.", ".", 1) + f"</td><td>{gb}</td><td>{r['last10']}</td></tr>")
                out.append("</table></div>")
            rows = news["wildcard"].get(lgi, [])
            out.append(f"<div class=pane id=p{lgi}3><table><tr><th>{'AL' if lgi == 0 else 'NL'} Wild Card</th><th>W</th>"
                       "<th>L</th><th>GB</th></tr>")
            for r in rows[:6]:
                gb = "&ndash;" if r["wcgb"] == 0 else f"{r['wcgb']:g}"
                cls = " class=mine" if r["team"] == user else ""
                out.append(f"<tr{cls}><td>{lg(r['team'])}{TM(r['team'])}</td><td>{r['w']}</td><td>{r['l']}</td>"
                           f"<td>{gb}</td></tr>")
            out.append("</table></div>")
        out.append("<a href='#allstandings' style='display:block;margin-top:5px'>View expanded standings &rsaquo;</a>"
                   + "</div></div>")
    if news.get("power"):  # the top of the power rankings
        out.append("<div class=mod id=powerbox><div class=mh>Power poll</div><div class=mb><table class=pwr>")
        for r in news["power"][:5]:
            out.append(f"<tr><td class=rk>{r['rank']}</td><td>{_move(r)}</td><td>{lg(r['team'])}{TM(r['team'])}</td>"
                       f"<td>{r['w']}-{r['l']}</td></tr>")
        out.append("</table><a href='#power' style='display:block;margin-top:5px'>All 30 clubs &rsaquo;</a></div></div>")
    out.append("<div class=mod id=matchups><div class=mh>" + ("Postseason" if post else "Matchups") + "</div><div class=mb>")
    if news["upcoming"]:
        out.append(f"<div class=date style='margin-bottom:3px'>{fmt(news['next_day'])}</div>")
        for g in news["upcoming"][:7]:
            a, h = g["away"], g["home"]
            sr = next((x for x in news.get("playoffs", []) if g in x["games"]), None)
            if sr:
                n = sr["games"].index(g) + 1
                out.append(f"<div class=date>{sr['name']}, Game {n}: {e(series_line(sr, db.club))}</div>")
            rec = "" if post else " <span class=date>(%s)</span>"
            out.append(f"<div class=match>{lg(a)}<b>{TM(a)}</b>{rec and rec % news_record(news, a)}<br>"
                       f"<span class=date>at</span> {lg(h)}<b>{TM(h)}</b>{rec and rec % news_record(news, h)}</div>")
    else:
        out.append("No games on the schedule.")
    out.append("</div></div></div>")
    out.append("<div class=mod id=news><div class=mh>Headlines</div><div class=mb><ul class=heads>")
    for i, h in enumerate(heads):
        out.append(f"<li id=s{i} class='{'mine' if h['mine'] else ''}'><span class=kind>{e(h['kind'])}</span> "
                   f"<span class=date>{short(day(h['day']))}</span><b>{e(h['head'])}</b><p>{story(h)}</p></li>")
    if not heads:
        out.append("<li>Nothing yet.</li>")
    out.append("</ul></div></div>")
    if news["days"]:  # every game of the last week, written up; the day's best first, as the Game of the Day
        out.append("<div class=mod id=recaps><div class=mh>Scores &amp; recaps</div><div class=subtabs>")
        for i, (d, _) in reversed(list(enumerate(news["days"]))):  # oldest on the left, the newest (picked) right
            out.append(f"<button data-g=day data-i={i} onclick='pickday({i})'>{day(d).strftime('%a')} "
                       f"{day(d).month}/{day(d).day}</button>")
        out.append("</div><div class=mb>")
        for i, (d, rs) in enumerate(news["days"]):
            out.append(f"<div class=dpane id=d{i}><div class=date style='margin-bottom:4px'>{fmt(day(d))}</div>")
            for r in rs:
                g = r["game"]
                inn = f"/{g['innings']}" if g["innings"] > 9 else ""
                extra = g["innings"] > 9
                rows = ""
                for t, rr, hh, ee, line in ((g["away"], g["ar"], g["ah"], g["ae"], g["aline"]),
                                            (g["home"], g["hr"], g["hh"], g["he"], g["hline"])):
                    shown = line[:8] + [rr - sum(line), line[8]] if extra else list(line)
                    if t == g["home"] and not extra and g["hr"] > g["ar"] and sum(line[:8]) > g["ar"]:
                        shown[8] = "x"  # (ahead after the top of the 9th: no bottom of it)
                    cells = "".join(f"<td>{v}</td>" for v in shown)
                    rows += (f"<tr class={'w' if t == r['win'] else ''}><td>{lg(t)}{TM(t, db.short(t))}</td>{cells}"
                             f"<td class=rhe>{rr}</td><td>{hh}</td><td>{ee}</td></tr>")
                heads_ = "".join(f"<th>{k}</th>" for k in range(1, 9)) + (
                    (f"<th>9{'-' + str(g['innings'] - 1) if g['innings'] > 10 else ''}</th><th>{g['innings']}</th>")
                    if extra else "<th>9</th>")
                kick = "<span class=kick>Game of the day</span>" if r["gotd"] else ""
                out.append(f"<div class='recap{' gotd' if r['gotd'] else ''}{' mine' if r['mine'] and not r['gotd'] else ''}'"
                           f" id={gid(g)}><table class=line><tr><th>Final{inn}</th>{heads_}<th class=rhe>R</th><th>H</th><th>E</th></tr>"
                           f"{rows}</table>"
                           f"<div>{kick}<b>{e(r['head'])}</b><p>{linkify(r['body'], (), (r['win'], r['lose']))}</p></div></div>")
            out.append("</div>")
        out.append("</div></div>")
    out.append(awards_box(news, lg, PL, TM, most=5))
    out.append("<div class=mod id=wire><div class=mh>Transactions</div><div class=mb><ul class=list>")
    for s in sorted(news["trades"] + news["moves"], key=lambda s: -s["day"])[:15]:  # newest first (the page: all)
        out.append(f"<li><span class=date>{short(day(s['day']))}:</span> {story(s)}</li>")
    if not news["trades"] and not news["moves"]:
        out.append("<li>None yet.</li>")
    out.append("</ul></div><a class=more2 href='#transactions'>All transactions &rsaquo;</a></div>"
               "<div class=mod id=injuries><div class=mh>Injury report</div><div class=mb><ul class=list>")
    majors = [s for s in news["injuries"] if s["big_club"]]
    minors = [s for s in news["injuries"] if not s["big_club"]]
    for s in majors:
        out.append(f"<li>{story(s)}</li>")
    if not majors:
        out.append("<li>Every big-league club is healthy.</li>")
    if minors:
        out.append(f"<li><b>In the minors and elsewhere: {len(minors)} more</b></li>")
        for s in minors[:25]:
            out.append(f"<li>{story(s)}</li>")
    out.append("</ul></div></div>")
    if not post:  # every division at once, as the old "expanded standings" page had it
        out.append("<div class=mod id=allstandings><div class=mh>Expanded standings</div><div class=mb>")
        for d in news["divisions"]:
            out.append(f"<table style='margin-bottom:8px'><tr><th>{e(d['name'])}</th><th>W</th><th>L</th><th>Pct</th>"
                       "<th>GB</th><th>Home</th><th>Road</th><th>RS</th><th>RA</th><th>Strk</th></tr>")
            for r in d["rows"]:
                gb = "&ndash;" if r["gb"] == 0 else f"{r['gb']:g}"
                cls = " class=mine" if r["team"] == user else ""
                out.append(f"<tr{cls}><td>{lg(r['team'])}{TM(r['team'])}</td><td>{r['w']}</td><td>{r['l']}</td>"
                           + f"<td>{r['pct']:.3f}".replace("0.", ".", 1) + f"</td><td>{gb}</td><td>{r['home']}</td>"
                           f"<td>{r['road']}</td><td>{r['rs']}</td><td>{r['ra']}</td><td>{r['streak']}</td></tr>")
            out.append("</table>")
        out.append("</div></div>")

    # ---- right: the navy rail
    out.append("</div><div class=rail><div class=mod><div class=mh>News<span class=r>Your league</span></div><ul>")
    for i, h in enumerate(heads[:10]):
        out.append(f"<li class='{'mine' if h['mine'] else ''}'><a href='#s{i}'>{e(h['head'])}</a></li>")
    if not heads:
        out.append("<li>Nothing yet.</li>")
    out.append("</ul><a class=x href='#news'>More news &rsaquo;</a></div>")
    wire = sorted(news["trades"] + news["moves"], key=lambda s: -s["day"])[:6]
    if wire:
        out.append("<div class=mod><div class=mh>Transactions</div><ul>")
        for s in wire:
            out.append(f"<li><span class=date>{short(day(s['day']))}:</span> {e(s['head'])}</li>")
        out.append("</ul><a class=x href='#wire'>All transactions &rsaquo;</a></div>")
    hurt = [s for s in news["injuries"] if s["big_club"]][:6]
    if hurt:
        out.append("<div class=mod><div class=mh>Injuries</div><ul>")
        for s in hurt:
            out.append(f"<li>{e(s['head'])}</li>")
        out.append("</ul><a class=x href='#injuries'>Injury report &rsaquo;</a></div>")
    out.append("</div></div>")
    out.append(team_pages(news, lg, gid, PL, TM, story))
    out.append(stats_page(news, lg, PL, TM))
    out.append(transactions_page(news, lg, story))
    out.append(milestones_page(news, lg, PL, TM))
    out.append(awards_page(news, lg, PL, TM))
    out.append(playoffs_page(news, lg, TM, gid))
    out.append(farm_page(news, lg, PL))
    out.append(power_page(news, lg, PL, TM))
    out.append(schedule_pages(news, lg, gid))
    out.append("<div id=playerpage class=teampage></div>")
    season = (news["today"] or day(min((g["day"] for g in news["games"]), default=21000))).year
    out.append(f"<script>var PD={player_data(news, need)},TT={team_table(db)},NOW={season};</script>")
    out.append("<div class=foot><div class=links><a href='#news'>Headlines</a><a href='#scores'>Scores</a>"
               f"<a href='#{'standings' if post else 'allstandings'}'>Standings</a><a href='#transactions'>Transactions</a>"
               "<a href='#injuries'>Injuries</a></div>"
               "<div class=fine>Made by the MVP05-Plus Launcher from your save. Names, teams and logos are read from your "
               "own copy of the game. Nothing in your save is changed.</div></div></div>")
    out.append("<script src='editions.js'></script><script>(function(){var E=window.EDITIONS;if(!E||E.length<2)return;"
               "var me=decodeURIComponent(location.pathname.split('/').pop()),i=-1;E.forEach(function(x,n){if(x[0]==me)i=n;});"
               "var h='';if(i>=0&&i+1<E.length)h+=\"<a href='\"+E[i+1][0]+\"'>&lsaquo; Previous issue</a>\";"
               "h+=\"<select aria-label='Back issues' onchange='if(this.value)location.href=this.value'>"
               "<option value=''>Back issues (\"+E.length+\")</option>\";E.forEach(function(x){h+=\"<option value='\"+x[0]+\"'\""
               "+(x[0]==me?' disabled':'')+'>'+x[1]+(x[0]==me?' (this one)':'')+'</option>';});h+='</select>';"
               "if(i>0)h+=\"<a href='\"+E[i-1][0]+\"'>Next issue &rsaquo;</a>\";if(i>0)h+=\"<a href='\"+E[0][0]+\"'><b>Latest</b></a>\";"
               "document.getElementById('issues').innerHTML=h;})();</script>")
    out.append(f"<script>{SCRIPT}function show(t){{var r=document.getElementById('t'+t);if(!r)return;"
               f"var p=r.closest('.pane');if(p)pick(+p.id[1],+p.id[2]);}}pick({first[0]},{first[1]});"
               "function route(){var h=location.hash.slice(1),t=h.indexOf('team-')==0||h.indexOf('sched-')==0?document.getElementById(h):null;"
               "if(h.indexOf('p-')==0)t=showPlayer(h.slice(2));if(['stats','transactions','milestones','awards','farm','power','playoffs'].indexOf(h)>=0)t=document.getElementById(h);"
               "document.querySelectorAll('.teampage').forEach(function(p){p.style.display=p==t?'block':'none'});"
               "document.querySelector('.cols').style.display=t?'none':'flex';if(t){window.scrollTo(0,0);return;}"
               "var el=h&&document.getElementById(h);if(el){var d=el.closest('.dpane');if(d)pickday(+d.id.slice(1));"
               "var q=el.closest('.pane');if(q)pick(+q.id[1],+q.id[2]);el.scrollIntoView();}}"
               "window.addEventListener('hashchange',route);"
               "function pickday(i){tab('day',i);document.querySelectorAll('.dpane').forEach(function(p){"
               "p.classList.toggle('on',p.id=='d'+i)});}function day0(){pickday(0);}pickday(0);"
               "var LS=[[0,0],[0,0]];function pickl(b,l,c){if(l!==null)LS[b][0]=l;if(c!==null)LS[b][1]=c;"
               "l=LS[b][0];c=LS[b][1];tab('llg'+b,l);tab('lcat'+b,c);document.querySelectorAll('.lp'+b)"
               ".forEach(function(p){p.classList.toggle('on',p.id=='l'+b+l+c)});}"
               f"pickl(0,{first[0]},0);pickl(1,{first[0]},0);pickstats({first[0]},0);pickaw('awf',{first[0]},0);"
               f"pickaw('awp',{first[0]},0);"
               "document.querySelectorAll('table.stats th[data-def]').forEach(function(th){sortT(th);});route();</script>")
    out.append("</body></html>")
    logos = "".join(f".{c}{{background-image:url({u})}}" for v in used.values() if v for c, u in [v])
    return "".join(out).replace("</style>", logos + "</style>", 1)


def _or_dash(v, dash="&ndash;"):
    return dash if v is None else v


def team_pages(news, lg, gid, PL, TM, story):
    """One page a club (shown in place of the front page by #team-<n>): record and place, the season so far by
    game, the roster with each player's line, injuries, transactions and headlines about the club."""
    db, e = news["db"], html.escape
    stats = news["stats"] or {}
    bat, pit = stats.get("bat", {}), stats.get("pit", {})
    names = news["names"]
    recapped = {gid(r["game"]) for _, rs in news["days"] for r in rs}
    out = []
    rows = {r["team"]: (r, d) for d in news["divisions"] for r in d["rows"]}
    short_day = lambda n: f"{day(n).month}/{day(n).day}"
    for i, t in enumerate(db.franchises):
        out.append(f"<div class=teampage id=team-{i}><a class=back href='#top'>&lsaquo; Back to the front page</a>"
                   f"<div class=mod><div class=mh>{e(db.full(t))}</div><div class='mb thead'>{lg(t, True)}<div>"
                   f"<h1>{e(db.full(t))}</h1>")
        row, div = rows.get(t, (None, None))
        if row and not news["postseason"]:
            place = div["rows"].index(row) + 1
            out.append(f"<p class=big>{row['w']}-{row['l']}, {_ord(place)} in the {e(div['name'])}"
                       + ("" if row["gb"] == 0 else f", {_back(row['gb'])}") + "</p>"
                       f"<p>Last 10: {row['last10']} &middot; Streak: {row['streak'] or '&ndash;'} &middot; "
                       f"Home {row['home']} &middot; Road {row['road']}</p><p>Runs: {row['rs']} scored, {row['ra']} allowed "
                       f"({row['rs'] - row['ra']:+d})</p>".replace("(-", "(&minus;"))
            pw = next((r for r in news.get("power", []) if r["team"] == t), None)
            if pw:
                out.append(f"<p>Power ranking: <a href='#power'>No. {pw['rank']}</a> {_move(pw)}</p>")
        out.append("</div></div></div>")
        out.append("<div class=pair>")
        mine = [g for g in news["games"] if t in (g["away"], g["home"])]
        played = sorted((g for g in mine if g["played"]), key=lambda g: g["day"])[-10:][::-1]
        coming = sorted((g for g in mine if not g["played"]), key=lambda g: g["day"])[:8]
        out.append("<div class=mod><div class=mh>Last 10 games</div><div class=mb><table class=res>")
        for g in played:
            home = g["home"] == t
            opp = g["away"] if home else g["home"]
            us, them = (g["hr"], g["ar"]) if home else (g["ar"], g["hr"])
            score = f"{us}-{them}" + (f" ({g['innings']})" if g["innings"] > 9 else "")
            link = f"<a href='#{gid(g)}'>{score}</a>" if gid(g) in recapped else score
            out.append(f"<tr><td>{short_day(g['day'])}</td><td>{'vs.' if home else 'at'} {lg(opp)}"
                       f"<a href='#team-{db.franchises.index(opp)}'>{e(db.club(opp))}</a></td>"
                       f"<td class={'w' if us > them else 'l'}>{'W' if us > them else 'L'}</td><td>{link}</td></tr>")
        if not played:
            out.append("<tr><td>No games yet.</td></tr>")
        out.append("</table>" + (f"<a href='#sched-{i}'>Full schedule and season series &rsaquo;</a>" if mine else "")
                   + "</div></div>"
                   "<div class=mod><div class=mh>Coming up</div><div class=mb><table class=res>")
        for g in coming:
            home = g["home"] == t
            opp = g["away"] if home else g["home"]
            out.append(f"<tr><td>{day(g['day']).strftime('%a')} {short_day(g['day'])}</td><td>{'vs.' if home else 'at'} "
                       f"{lg(opp)}<a href='#team-{db.franchises.index(opp)}'>{e(db.club(opp))}</a></td>"
                       f"<td>{news_record(news, opp)}</td></tr>")
        if not coming:
            out.append("<tr><td>Nothing on the schedule.</td></tr>")
        out.append("</table></div></div></div>")
        # the roster: hitters, then pitchers, with this season's lines
        lnorm = news["norms"].get((stats.get("year"), int(db.teams.get(t, {}).get(4, -1))))
        keys = news["rosters"].get(i, [])
        nm = lambda k: names.get(k) or db.name(k) or "?"
        hitters = [k for k in keys if k in bat or (k not in pit and db.pos(k) not in ("RHP", "LHP"))]
        pitchers = [k for k in keys if k not in hitters]
        order = {"C": 0, "1B": 1, "2B": 2, "3B": 3, "SS": 4, "OF": 5, "DH": 6}
        hitters.sort(key=lambda k: (order.get(db.pos(k), 7), -bat.get(k, {}).get("ab", 0)))
        pitchers.sort(key=lambda k: (-pit.get(k, {}).get("outs", 0)))
        label = f"{stats.get('year', '')} " if stats.get("last_season") or stats.get("final") else ""
        out.append(f"<div class=mod><div class=mh>{label}Roster</div><div class=mb><table class=roster><tr><th>Pos</th>"
                   "<th>Hitter</th><th>AB</th><th>AVG</th><th>HR</th><th>RBI</th><th>R</th><th>SB</th><th>OPS</th><th>OPS+</th></tr>")
        for k in hitters:
            b = bat.get(k)
            line = (f"<td>{b['ab']}</td><td>{(b['h'] / b['ab']):.3f}</td>".replace(">0.", ">.") if b and b["ab"] else
                    "<td>0</td><td>&ndash;</td>") + (f"<td>{b['hr']}</td><td>{b['rbi']}</td><td>{b['r']}</td>"
                                                    f"<td>{b['sb']}</td><td>{rate3(obp(b) + slg(b)) if b['ab'] else '&ndash;'}</td>"
                                                    f"<td>{_or_dash(ops_plus(b, lnorm))}</td>" if b else "<td></td>" * 6)
            out.append(f"<tr><td>{db.pos(k)}</td><td>{PL(k)}</td>{line}</tr>")
        out.append("</table><table class=roster><tr><th></th><th>Pitcher</th><th>G</th><th>W-L</th><th>ERA</th>"
                   "<th>SV</th><th>IP</th><th>SO</th><th>ERA+</th></tr>")
        for k in pitchers:
            p = pit.get(k)
            if p and p["g"]:
                era = f"{27 * p['er'] / p['outs']:.2f}" if p["outs"] else "&ndash;"
                line = (f"<td>{p['g']}</td><td>{p['w']}-{p['l']}</td><td>{era}</td><td>{p['sv']}</td>"
                        f"<td>{p['outs'] // 3}.{p['outs'] % 3}</td><td>{p['so']}</td>"
                        f"<td>{_or_dash(era_plus(p, lnorm), '&infin;' if not p['er'] and p['outs'] else '&ndash;')}</td>")
            else:
                line = "<td>0</td>" + "<td></td>" * 6
            out.append(f"<tr><td>{db.pos(k)}</td><td>{PL(k)}</td>{line}</tr>")
        out.append("</table></div></div>")
        out.append(farm_box(news, t, PL))
        # news about the club
        about = lambda s_: t in s_["teams"] or t in s_.get("raw_teams", [])
        heads = [s_ for s_ in news["stories"] if about(s_) and s_["kind"] not in ("Injury", "Suspension")][:8]
        hurt = [s_ for s_ in news["injuries"] if about(s_)]
        wire = sorted((s_ for s_ in news["trades"] + news["moves"] if about(s_)), key=lambda s_: -s_["day"])[:12]
        out.append("<div class=pair><div class=mod><div class=mh>News</div><div class=mb><ul class=heads>")
        for h in heads:
            out.append(f"<li><span class=kind>{e(h['kind'])}</span> <span class=date>{short_day(h['day'])}</span>"
                       f"<b>{e(h['head'])}</b><p>{story(h)}</p></li>")
        if not heads:
            out.append("<li>No news yet.</li>")
        out.append("</ul></div></div><div class=mod><div class=mh>Injuries</div><div class=mb><ul class=list>")
        for h in hurt:
            out.append(f"<li>{story(h)}</li>")
        if not hurt:
            out.append("<li>Nobody's hurt.</li>")
        out.append("</ul></div><div class=mh>Transactions</div><div class=mb><ul class=list>")
        for h in wire:
            out.append(f"<li><span class=date>{short_day(h['day'])}:</span> {story(h)}</li>")
        if not wire:
            out.append("<li>None yet.</li>")
        out.append("</ul></div></div></div></div>")
    return "".join(out)


def player_data(news, keys):
    """The players' pages, as data the page fills in (one template, not a page each): {hex key: {n name, pos, t
    franchise index or -1, b 1 for a hitter, bio, rows [[year, team index, ...]], news [[date, kind, head, body]]}}.
    A hitter's row: AB, H, HR, RBI, R, SB, BB, SO, TB, SF; a pitcher's: G, W, L, SV, outs, ER, SO, BB (FORMAT_NOTES
    3.6)."""
    import json
    db = news["db"]
    hist = news["history"]
    stats = news["stats"] or {}
    on = {k: db.franchises[i] for i, ks in news["rosters"].items() for k in ks if i < len(db.franchises)}
    now = (news["today"] or day(min((g["day"] for g in news["games"]), default=21000))).year
    about = collections.defaultdict(list)
    for st in sorted(news["stories"], key=lambda st: -st["day"]):
        for k in st["players"]:
            if len(about[k]) < 6:
                about[k].append([f"{day(st['day']).month}/{day(st['day']).day}", st["kind"], st["head"], st["body"]])
    out = {}
    for k in keys:
        rows = hist.get(k, [])
        hitter = sum(r["batter"] for r in rows) * 2 >= len(rows) if rows else db.pos(k) not in ("RHP", "LHP")
        # where he is: a big-league roster, else his latest trade or move, else this season's line, else his last row
        farm = None
        team = on.get(k)
        if team is None and any(k in st["players"] for st in news["trades"] + news["moves"]):
            farm = news["team_of"].get(k)
        if team is None and farm is None:
            farm = getattr(stats.get("bat" if hitter else "pit", {}).get(k), "team", None)
            if farm is None and rows:
                farm = db.team_at(rows[-1]["team"])
        if team is None and farm is not None:
            team = db.org_of.get(farm, farm)
            if farm == team:
                farm = None
        cells = []
        for r in sorted(rows, key=lambda r: r["year"]):
            x = r["stats"]
            norm = (news["norms"].get((r["year"], int(db.teams.get(db.franchises[r["team"]], {}).get(4, -1))))
                    if r["team"] < len(db.franchises) else None)
            plus = ops_plus(x, norm) if r["batter"] else era_plus(x, norm)
            cells.append([r["year"], r["team"]] + ([x["ab"], x["h"], x["hr"], x["rbi"], x["r"], x["sb"], x["bb"],
                                                    x["so"], x["tb"], x["sf"]] if r["batter"]
                         else [x["g"], x["w"], x["l"], x["sv"], x["outs"], x["er"], x["so"], x["bb"]]) + [plus])
        p = db.players.get(k, {})
        bio = []
        if p:
            num = lambda c: int(p.get(c) or 0) if str(p.get(c) or "").isdigit() else None
            if num(2) is not None:
                bio.append(f"#{num(2)}")
            if num(3) is not None:
                bio.append(f"Bats {['right', 'left', 'both'][min(num(3), 2)]}")
            if num(4) is not None:
                bio.append(f"Throws {'left' if num(4) == 1 else 'right'}")
            if num(45):  # the birth date, in days from 1948-01-01 (as the schedule's dates)
                born = DAY0 + datetime.timedelta(days=num(45))
                ref = news["today"] or datetime.date(now, 4, 1)
                bio.append(f"Age {ref.year - born.year - ((ref.month, ref.day) < (born.month, born.day))}")
        else:
            bio.append("Created in this dynasty")
        if k in news.get("contracts", {}):  # the save's own: re-signings and new deals included
            pay, years = news["contracts"][k]
            money = f"${pay / 1e6:.2f}M" if pay >= 1_000_000 else f"${pay // 1000}K"
            bio.append(f"Contract: {money} a year, {years} year{'s' if years > 1 else ''} left (through "
                       f"{now + years - 1})")
        status = []
        for st in news["injuries"]:
            if k in st["players"]:
                status.append(["Injury", st["body"]])
        moves = [st for st in news["trades"] + news["moves"] if k in st["players"]]
        if moves:
            last = max(moves, key=lambda st: st["day"])
            status.append([f"Latest move ({day(last['day']).month}/{day(last['day']).day})", last["body"]])
        out[f"{k:x}"] = dict(n=news["names"].get(k) or db.name(k) or "?", pos=db.pos(k) or ("Pitcher" if not hitter else ""),
                             t=db.franchises.index(team) if team in db.franchises else -1, b=int(hitter),
                             bio=" &middot; ".join(bio), rows=cells, news=about.get(k, []), status=status,
                             f=f"{db.full(farm)}, {db.level(farm)}" if farm else "", **_career_bits(news, k, hitter))
    return json.dumps(out, separators=(",", ":")).replace("</", "<\\/")


def _career_bits(news, k, hitter):
    """car: his whole big-league career (the history keeps 16 seasons) as the career table's columns; ms: the next
    marks within sight"""
    car = (news.get("careers") or {}).get("bat" if hitter else "pit", {}).get(k)
    if not car:
        return dict(car=None, ms=[])
    cols = ["g", "ab", "h", "hr", "rbi", "r", "sb"] if hitter else ["g", "w", "l", "sv", "outs", "er", "so", "bb"]
    ms = []
    for side, stat, label, marks, reach in MILESTONES:
        if (side == "bat") != hitter:
            continue
        nxt = next((m for m in marks if m > car[stat]), None)
        if nxt is not None and nxt - car[stat] <= 3 * reach:
            ms.append(f"{nxt - car[stat]} {label} from {nxt:,}")
    return dict(car=[car[c] for c in cols], ms=ms)


def team_table(db):
    """[[short name, franchise index or -1]] for the history rows' team bytes"""
    import json
    out = []
    for i in range(126):
        t = db.team_at(i)
        if t is None:
            break
        org = db.org_of.get(t, t)
        out.append([db.short(t) if t in db.franchises else db.city(t),
                    db.franchises.index(org) if org in db.franchises else -1])
    return json.dumps(out, separators=(",", ":")).replace("</", "<\\/")


def stats_page(news, lg, PL, TM):
    """#stats: every big-leaguer's season so far, a table each for AL/NL hitting and pitching, sorted by a click on
    a column (qualified players first shown: 2.7 at-bats a team game, an inning every three team games)."""
    db = news["db"]
    st = news["stats"]
    if not st:
        return ""
    games = st["games"]
    year = f"{st['year']} " if st["last_season"] or st["final"] else ""

    def td(v, text=None):
        return f"<td data-v='{v}'>{text if text is not None else v}</td>"
    out = [f"<div class=teampage id=stats><a class=back href='#top'>&lsaquo; Back to the front page</a>"
           f"<div class=mod><div class=mh>{year}League leaders</div><div class=tabs>"
           + "".join(f"<button data-g=sl data-i={i} onclick='pickstats({i},null)'>{n}</button>"
                     for i, n in enumerate(("American League", "National League")))
           + "</div><div class=subtabs>" + "".join(f"<button data-g=sk data-i={i} onclick='pickstats(null,{i})'>{n}</button>"
                                                 for i, n in enumerate(("Hitting", "Pitching")))
           + "</div><div class=mb><label class=date><input type=checkbox onchange=\"document.getElementById('stats')"
             ".classList.toggle('all',this.checked);renumber()\"> Show players who don't qualify</label>"
             " <span class=date>&middot; Click a column to sort by it.</span>"]
    heads = (["#", "Player", "Team", "G", "AB", "R", "H", "HR", "RBI", "SB", "BB", "SO", "AVG", "OBP", "SLG", "OPS",
              "OPS+"], ["#", "Player", "Team", "G", "W", "L", "SV", "IP", "ER", "BB", "SO", "ERA", "ERA+", "K/9"])
    norm = lambda t: news["norms"].get((st["year"], int(db.teams.get(t, {}).get(4, -1))))
    for lgi in (0, 1):
        for kind in (0, 1):
            src = st["bat"] if kind == 0 else st["pit"]
            rows = [(k, x) for k, x in src.items() if int(db.teams.get(x.team, {}).get(4, -1)) == lgi
                    and (x["ab"] if kind == 0 else x["outs"])]
            sort_col = 12 if kind == 0 else 11
            out.append(f"<div class=spane id=s{lgi}{kind}><table class=stats><thead><tr>" + "".join(
                f"<th onclick='sortT(this)'{' data-def=1' if i == sort_col else ''}>{h}</th>" for i, h in enumerate(heads[kind]))
                + "</tr></thead><tbody>")
            for k, x in rows:
                t = x.team
                team = f"{lg(t)}{TM(t, db.short(t))}"
                if kind == 0:
                    q = x["ab"] >= 2.7 * games.get(t, 0)
                    avg, ob, sl = x["h"] / x["ab"], obp(x), slg(x)
                    cells = (td(x["g"]) + td(x["ab"]) + td(x["r"]) + td(x["h"]) + td(x["hr"]) + td(x["rbi"]) + td(x["sb"])
                             + td(x["bb"]) + td(x["so"]) + td(f"{avg:.4f}", rate3(avg)) + td(f"{ob:.4f}", rate3(ob))
                             + td(f"{sl:.4f}", rate3(sl)) + td(f"{ob + sl:.4f}", rate3(ob + sl)))
                    op = ops_plus(x, norm(t))
                    cells += td(op if op is not None else -999, op if op is not None else "&ndash;")
                else:
                    q = x["outs"] >= games.get(t, 0)
                    era = 27 * x["er"] / x["outs"]
                    k9 = 27 * x["so"] / x["outs"]
                    cells = (td(x["g"]) + td(x["w"]) + td(x["l"]) + td(x["sv"])
                             + td(x["outs"], f"{x['outs'] // 3}.{x['outs'] % 3}") + td(x["er"]) + td(x["bb"]) + td(x["so"])
                             + td(f"{-era + x['outs'] / 1e6:.6f}", f"{era:.2f}"))
                    ep = era_plus(x, norm(t))
                    cells += td(ep if ep is not None else (9999 if not x["er"] else -1),
                                ep if ep is not None else ("&infin;" if not x["er"] else "&ndash;"))
                    cells += td(f"{k9:.4f}", f"{k9:.1f}")
                cls = ("" if q else "nq") + (" mine" if t == news["user"] else "")
                name = news["names"].get(k) or db.name(k) or "?"
                out.append(f"<tr class='{cls.strip()}'><td></td><td data-v=\"{html.escape(name)}\">{PL(k)}</td>"
                           f"<td data-v='{db.short(t)}'>{team}</td>{cells}</tr>")
            out.append("</tbody></table></div>")
    out.append("</div></div></div>")
    return "".join(out)


def transactions_page(news, lg, story):
    """#transactions: every trade and roster move the save and the game's backups of it hold, newest first by day,
    filtered by club and by kind."""
    db, e = news["db"], html.escape
    items = sorted(news["trades"] + news["moves"], key=lambda s_: -s_["day"])
    kinds = ("Trade", "Signed", "Call-up", "Sent down", "Farm move", "Assigned")
    have = collections.Counter(s_["sub"] for s_ in items)
    n_back = news.get("from_backups", 0)
    since = f" since {day(items[-1]['day']).strftime('%B')} {day(items[-1]['day']).day}, {day(items[-1]['day']).year}" \
        if items else ""
    out = [f"<div class=teampage id=transactions><a class=back href='#top'>&lsaquo; Back to the front page</a>"
           f"<div class=mod><div class=mh>Transactions</div><div class=mb><p class=date>{len(items)} moves{since}"
           + (f", from this save and {n_back} of the game's backups of it" if n_back else "") + ".</p>"
           "<div class=tfilter><select id=tteam onchange='filterT()'><option value=''>All clubs</option>"]
    for t in sorted(db.franchises, key=db.city):
        out.append(f"<option value='{db.franchises.index(t)}'>{e(db.city(t))} {e(db.club(t))}</option>")
    out.append("</select> <span class=tk><button data-g=tk data-i=all class=on onclick=\"pickT('all')\">All</button>")
    for k in kinds:
        if have[k]:
            label = {"Trade": "Trades", "Signed": "Signings", "Call-up": "Call-ups", "Farm move": "Farm moves"}.get(k, k)
            out.append(f"<button data-g=tk data-i='{k}' onclick=\"pickT('{k}')\">{label} ({have[k]})</button>")
    out.append("</span></div><div id=tlist>")
    last_day = None
    for s_ in items:
        if s_["day"] != last_day:
            if last_day is not None:
                out.append("</ul></div>")
            d = day(s_["day"])
            out.append(f"<div class=tday><h3>{d.strftime('%A, %B')} {d.day}, {d.year}</h3><ul class=list>")
            last_day = s_["day"]
        orgs = " ".join(str(db.franchises.index(t)) for t in set(s_["teams"]) if t in db.franchises)
        out.append(f"<li data-t=' {orgs} ' data-k='{e(s_['sub'])}'><span class=kind>{e(s_['sub'])}</span> {story(s_)}</li>")
    if last_day is not None:
        out.append("</ul></div>")
    if not items:
        out.append("<p>No transactions yet.</p>")
    out.append("<p id=tnone class=date style='display:none'>None of those.</p></div></div></div></div>")
    return "".join(out)


FARM_CATS = (("AVG", "Average"), ("HR", "Home runs"), ("RBI", "RBIs"), ("OPS", "OPS"), ("SB", "Stolen bases"),
             ("W", "Wins"), ("ERA", "ERA"), ("SO", "Strikeouts"), ("SV", "Saves"))


def farm_page(news, lg, PL):
    """#farm: the top prospects' lines, then each level's leaders"""
    f = news.get("farm") or {}
    if not f:
        return ""
    db, e = news["db"], html.escape
    org = lambda t: db.org_of.get(t, t)
    out = ["<div class=teampage id=farm><a class=back href='#top'>&lsaquo; Back to the front page</a>"
           "<div class=mod><div class=mh>Farm report: top prospects</div><div class=mb><p class=date>The farm "
           "clubs' best young players this season: the game's top prospects, the dynasty's own draftees and anyone "
           "23 or under, ranked by how they're hitting or pitching at their level.</p><table class=stats><thead><tr>"
           "<th>#</th><th>Player</th><th>Pos</th><th>Age</th><th>Club</th><th>Organization</th><th>This season</th>"
           "</tr></thead><tbody>"]
    for n, (k, t, age, text) in enumerate(f["prospects"], 1):
        out.append(f"<tr><td>{n}</td><td>{PL(k)}</td><td>{e(db.pos(k) or ('P' if 'ERA' in text else ''))}</td><td>{age if age is not None else ''}</td>"
                   f"<td>{e(db.tag(t))}</td><td>{lg(org(t))}<a href='#team-{db.franchises.index(org(t))}'>"
                   f"{e(db.club(org(t)))}</a></td><td>{e(text)}</td></tr>")
    if not f["prospects"]:
        out.append("<tr><td colspan=7>No one has played enough yet.</td></tr>")
    out.append("</tbody></table></div></div>")
    for lv in ("AAA", "AA", "A"):
        cats = f["levels"].get(lv) or {}
        if not any(cats.values()):
            continue
        out.append(f"<div class=mod><div class=mh>{'Class A' if lv == 'A' else lv} leaders</div><div class=mb>"
                   "<div class=races>")
        for c, title in FARM_CATS:
            if not cats.get(c):
                continue
            out.append(f"<div><h3>{title}</h3><table class=res>")
            for k, t, text in cats[c]:
                out.append(f"<tr><td>{lg(org(t))}{PL(k)}</td><td>{e(db.city(t))}</td><td>{text}</td></tr>")
            out.append("</table></div>")
        out.append("</div></div></div>")
    out.append("</div>")
    return "".join(out)


def farm_box(news, t, PL):
    """A club's farm teams this season: each one's best hitters and pitchers (a team page's box)"""
    f = news.get("farm") or {}
    db, e = news["db"], html.escape
    mine = sorted((x for x in f.get("teams", {}) if db.org_of.get(x) == t), key=lambda x: ("AAA", "AA", "A").index(db.levels[x]))
    if not mine:
        return ""
    out = ["<div class=mod><div class=mh>Down on the farm</div><div class=mb><table class=res>"]
    for x in mine:
        v = f["teams"][x]
        g = v["games"]
        bats = sorted((kv for kv in v["bat"].items() if kv[1]["ab"] >= 1.5 * g),
                      key=lambda kv: -(obp(kv[1]) + slg(kv[1])))[:3]
        arms = sorted((kv for kv in v["pit"].items() if kv[1]["outs"] >= 1.2 * g),
                      key=lambda kv: kv[1]["er"] / kv[1]["outs"])[:2]
        out.append(f"<tr><th colspan=3>{e(db.full(x))} ({db.levels[x]})</th></tr>")
        for k, s in bats:
            out.append(f"<tr><td>{PL(k)}</td><td>{e(db.pos(k))}</td><td>{rate3(s['h'] / s['ab'])}, {s['hr']} HR, "
                       f"{s['rbi']} RBI, {rate3(obp(s) + slg(s))} OPS</td></tr>")
        for k, s in arms:
            out.append(f"<tr><td>{PL(k)}</td><td>{e(db.pos(k) or 'P')}</td><td>{s['w']}-{s['l']}"
                       + (f", {s['sv']} SV" if s["sv"] else "") + f", {27 * s['er'] / s['outs']:.2f} ERA, "
                       f"{s['so']} K</td></tr>")
        if not bats and not arms:
            out.append("<tr><td colspan=3>No regulars yet.</td></tr>")
    out.append("</table><a href='#farm'>Farm report &rsaquo;</a></div></div>")
    return "".join(out)


def _move(r):
    """▲3 / ▼2 / – against the rank a week before"""
    if not r["was"] or r["was"] == r["rank"]:
        return "<span class=mv>&ndash;</span>"
    up = r["was"] > r["rank"]
    return f"<span class='mv {'up' if up else 'dn'}'>{'&#9650;' if up else '&#9660;'}{abs(r['was'] - r['rank'])}</span>"


def power_note(text, PL):
    return re.sub(r"\{P([0-9a-f]+)\}", lambda m: PL(int(m.group(1), 16)), text)


def power_page(news, lg, PL, TM):
    """#power: all 30 clubs, ranked, with the move since a week of games before"""
    rows = news.get("power") or []
    if not rows:
        return ""
    out = ["<div class=teampage id=power><a class=back href='#top'>&lsaquo; Back to the front page</a>"
           "<div class=mod><div class=mh>Power rankings</div><div class=mb><p class=date>Ranked on the record, the "
           "run differential and the last 10 games; the arrows compare with the rankings a week of games ago.</p>"
           "<table class='stats pwr'><thead><tr><th>#</th><th></th><th>Club</th><th>W-L</th><th>Diff</th>"
           "<th>Last 10</th><th>Streak</th><th>Last week</th><th></th></tr></thead><tbody>"]
    for r in rows:
        d = r["rs"] - r["ra"]
        out.append(f"<tr><td class=rk>{r['rank']}</td><td>{_move(r)}</td><td>{lg(r['team'])}{TM(r['team'])}</td>"
                   f"<td>{r['w']}-{r['l']}</td><td>{'+' if d > 0 else ''}{d}</td><td>{r['last10']}</td>"
                   f"<td>{r['streak']}</td><td>{r['was'] or '&ndash;'}</td><td class=note>{power_note(r['note'], PL)}"
                   "</td></tr>")
    out.append("</tbody></table></div></div></div>")
    return "".join(out).replace("<td>-", "<td>&minus;")


def schedule_pages(news, lg, gid):
    """#sched-<n>: a club's whole season, month by month (results with the record after each, and the games to
    come), and its season series against every opponent"""
    db, e = news["db"], html.escape
    recapped = {gid(r["game"]) for _, rs in news["days"] for r in rs}
    out = []
    for i, t in enumerate(db.franchises):
        mine = sorted((g for g in news["games"] if t in (g["away"], g["home"])), key=lambda g: g["day"])
        if not mine:
            continue
        out.append(f"<div class=teampage id=sched-{i}><a class=back href='#team-{i}'>&lsaquo; Back to the "
                   f"{e(db.club(t))}</a><div class=mod><div class=mh>{e(db.full(t))}: "
                   f"{'postseason' if news['postseason'] else 'schedule and results'}</div><div class=mb><div class=sched>")
        w = l = 0
        series = collections.OrderedDict()
        month = None
        for g in mine:
            home = g["home"] == t
            opp = g["away"] if home else g["home"]
            sr = series.setdefault(opp, [0, 0, 0, 0, 0])  # won, lost, left, home games, road games
            sr[3 if home else 4] += 1
            d = day(g["day"])
            if (d.year, d.month) != month:
                if month:
                    out.append("</table></div>")
                month = (d.year, d.month)
                out.append(f"<div><h3>{d.strftime('%B')}</h3><table class=res>")
            vs = (f"{'vs.' if home else 'at'} {lg(opp)}<a href='#team-{db.franchises.index(opp)}'>"
                  f"{e(db.club(opp))}</a>")
            if g["played"]:
                us, them = (g["hr"], g["ar"]) if home else (g["ar"], g["hr"])
                won = us > them
                w, l = w + won, l + (not won)
                sr[0 if won else 1] += 1
                score = f"{us}-{them}" + (f" ({g['innings']})" if g["innings"] > 9 else "")
                link = f"<a href='#{gid(g)}'>{score}</a>" if gid(g) in recapped else score
                out.append(f"<tr><td>{d.month}/{d.day}</td><td>{vs}</td><td class={'w' if won else 'l'}>"
                           f"{'W' if won else 'L'}</td><td>{link}</td><td class=date>{w}-{l}</td></tr>")
            else:
                sr[2] += 1
                out.append(f"<tr class=later><td>{d.month}/{d.day}</td><td>{vs}</td><td></td>"
                           f"<td>{d.strftime('%a')}</td><td></td></tr>")
        out.append("</table></div></div></div></div>")
        out.append("<div class=mod><div class=mh>Season series</div><div class=mb><table class='res ser'><tr>"
                   "<th>Opponent</th><th>W</th><th>L</th><th>Left</th><th>Home</th><th>Road</th><th></th></tr>")
        order = sorted(series.items(), key=lambda kv: (int(db.teams[kv[0]].get(5, 9)) != int(db.teams[t].get(5, 9)),
                                                       int(db.teams[kv[0]].get(4, 9)) != int(db.teams[t].get(4, 9)),
                                                       db.city(kv[0])))
        for opp, (sw, sl, left, hg, rg) in order:
            if sw > sl and sw > (sl + left):
                note = "Won the series"
            elif sl > sw and sl > (sw + left):
                note = "Lost the series"
            elif not left and sw == sl:
                note = "Split"
            elif sw > sl:
                note = "Leads"
            elif sl > sw:
                note = "Trails"
            else:
                note = "Even" if sw else ""
            out.append(f"<tr><td>{lg(opp)}<a href='#team-{db.franchises.index(opp)}'>{e(db.full(opp))}</a></td>"
                       f"<td>{sw}</td><td>{sl}</td><td>{left}</td><td>{hg}</td><td>{rg}</td><td>{note}</td></tr>")
        out.append("</table></div></div></div>")
    return "".join(out)


def playoffs_page(news, lg, TM, gid):
    """#playoffs: the bracket (the AL's rounds on the left, the NL's on the right, the World Series between), then
    every series game by game, each linked to its recap"""
    rs = news.get("playoffs") or []
    if not rs:
        return ""
    db, e = news["db"], html.escape
    recapped = {gid(r["game"]) for _, x in news["days"] for r in x}

    def box(sr, title):
        if not sr:
            return f"<div class='pbox tbd'><div class=pt>{title}</div><div class=date>TBD</div></div>"
        rows = []
        for t in (sr["top"], sr["other"]):
            cls = "w" if sr["winner"] == t else ("out" if sr["winner"] else "")
            rows.append(f"<div class='pr {cls}'><span>{lg(t)}{TM(t)}</span><b>{sr['wins'][t]}</b></div>")
        return (f"<div class=pbox><a class=pt href='#ser-{rs.index(sr)}'>{sr['name']}</a>{''.join(rows)}"
                f"<div class=date>{e(series_line(sr, db.club))}</div></div>")

    pick = lambda r, lgi: [x for x in rs if x["round"] == r and x["league"] == lgi]
    cols = [(pick(0, 0), "ALDS", 2), (pick(1, 0), "ALCS", 1), ([x for x in rs if x["round"] == 2], "World Series", 1),
            (pick(1, 1), "NLCS", 1), (pick(0, 1), "NLDS", 2)]
    out = ["<div class=teampage id=playoffs><a class=back href='#top'>&lsaquo; Back to the front page</a>"
           f"<div class=mod><div class=mh>{day(rs[0]['games'][0]['day']).year} Postseason</div><div class=mb>"
           "<div class=bracket>"]
    for found, title, n in cols:
        out.append("<div class=bcol>" + "".join(box(found[i] if i < len(found) else None, title) for i in range(n))
                   + "</div>")
    out.append("</div></div></div>")
    for i, sr in enumerate(rs):
        out.append(f"<div class=mod id=ser-{i}><div class=mh>{sr['name']}: {e(db.club(sr['top']))} vs. "
                   f"{e(db.club(sr['other']))}</div><div class=mb><p class=date>Best of {sr['best']}. "
                   f"{e(series_line(sr, db.club))}.</p><table class=res>")
        for n, g in enumerate(sr["games"], 1):
            d = day(g["day"])
            at = f"{lg(g['away'])}{TM(g['away'])} at {lg(g['home'])}{TM(g['home'])}"
            if g["played"]:
                aw = g["ar"] > g["hr"]
                score = (f"{e(db.short(g['away']))} {g['ar']}, {e(db.short(g['home']))} {g['hr']}"
                         + (f" ({g['innings']})" if g["innings"] > 9 else ""))
                score = f"<a href='#{gid(g)}'>{score}</a>" if gid(g) in recapped else score
                win = g["away"] if aw else g["home"]
                out.append(f"<tr><td>Game {n}</td><td>{d.strftime('%a')} {d.month}/{d.day}</td><td>{at}</td>"
                           f"<td><b>{score}</b></td><td>{e(db.club(win))} win</td></tr>")
            else:
                out.append(f"<tr class=later><td>Game {n}</td><td>{d.strftime('%a')} {d.month}/{d.day}</td>"
                           f"<td>{at}</td><td></td><td>{'if needed' if n > sr['best'] // 2 + 1 else ''}</td></tr>")
        out.append("</table></div></div>")
    out.append("</div>")
    return "".join(out)


def milestones_page(news, lg, PL, TM):
    """#milestones: every active player within reach of a career mark, and the marks passed this season"""
    near, reached = news.get("milestones", ([], []))
    if not near and not reached:
        return ""
    db = news["db"]
    car = news.get("careers") or {}
    out = ["<div class=teampage id=milestones><a class=back href='#top'>&lsaquo; Back to the front page</a>"
           "<div class=mod><div class=mh>Milestone watch</div><div class=mb><p class=date>Career totals count every "
           "big-league season, the real ones and this dynasty's.</p><table class=stats><thead><tr><th>Player</th>"
           "<th>Club</th><th>Career</th><th>Next mark</th><th>To go</th></tr></thead><tbody>"]
    for k, t, label, m, gap in near:
        side, stat = next((x_[0], x_[1]) for x_ in MILESTONES if x_[2] == label)
        now = car.get(side, {}).get(k, {}).get(stat, m - gap)
        out.append(f"<tr><td>{PL(k)}</td><td>{lg(t)}{TM(t, db.short(t))}</td><td>{now:,} {label}</td><td>{m:,}</td>"
                   f"<td>{gap}</td></tr>")
    out.append("</tbody></table></div>")
    if reached:
        out.append("<div class=mh>Reached this season</div><div class=mb><table class=stats><thead><tr><th>Player</th>"
                   "<th>Club</th><th>Mark</th></tr></thead><tbody>")
        for k, t, label, m in reached:
            out.append(f"<tr><td>{PL(k)}</td><td>{lg(t)}{TM(t, db.short(t))}</td><td>{m:,} {label}</td></tr>")
        out.append("</tbody></table></div>")
    out.append("</div></div>")
    return "".join(out)


AWARD_NAMES = (("MVP", "MVP"), ("Cy Young", "Cy Young"), ("Rookie", "Rookie of the Year"))


def awards_box(news, lg, PL, TM, most=5, page=False):
    """The award races: a front-page box (the top 5), or #awards (the top 10); AL/NL and the award as tabs"""
    A = news.get("awards") or {}
    if not any(A.get(l_, {}).get(a) for l_ in (0, 1) for a, _ in AWARD_NAMES):
        return ""
    db = news["db"]
    st = news["stats"] or {}
    over = st.get("final") or news["postseason"]
    title = f"{st.get('year', '')} awards: the season's best" if over else "Awards races"
    g = "awp" if page else "awf"
    out = [f"<div class=mod{' id=awardsbox' if not page else ''}><div class=mh>{title}</div><div class=tabs>"
           + "".join(f"<button data-g={g}l data-i={i} onclick=\"pickaw('{g}',{i},null)\">{n}</button>"
                     for i, n in enumerate(("American League", "National League")))
           + "</div><div class=subtabs>" + "".join(
               f"<button data-g={g}c data-i={i} onclick=\"pickaw('{g}',null,{i})\">{label}</button>"
               for i, (_, label) in enumerate(AWARD_NAMES)) + "</div><div class=mb>"]
    for l_ in (0, 1):
        for ci, (a, label) in enumerate(AWARD_NAMES):
            out.append(f"<div class='awpane {g}' id={g}{l_}{ci}><ol class=race>")
            for rank, (k, t, why) in enumerate(A.get(l_, {}).get(a, [])[:most], 1):
                out.append(f"<li{' class=mine' if t == news['user'] else ''}>{lg(t)}<b>{PL(k)}</b>, "
                           f"{TM(t, db.short(t))}<br><span class=date>{html.escape(why)}</span></li>")
            if not A.get(l_, {}).get(a):
                out.append("<li>No one qualifies yet.</li>")
            out.append("</ol></div>")
    out.append("<p class=date>Picked from the stats: runs above average (OPS+ and the position) for hitters, runs "
               "saved against the league's ERA for pitchers, with some weight for HR, RBI, wins, saves and the "
               "club's record. Rookies: 130 at-bats or 50 innings at most before this season.</p>" if page else
               "<a class=more2 href='#awards'>The full races &rsaquo;</a>")
    out.append("</div></div>")
    return "".join(out)


def awards_page(news, lg, PL, TM):
    box = awards_box(news, lg, PL, TM, most=10, page=True)
    return (f"<div class=teampage id=awards><a class=back href='#top'>&lsaquo; Back to the front page</a>{box}</div>"
            if box else "")


def news_record(news, t):
    for d in news["divisions"]:
        for r in d["rows"]:
            if r["team"] == t:
                return f"{r['w']}-{r['l']}"
    return ""


KEEP_EDITIONS = 120  # (each edition is a couple of megabytes)


def publish(root, data, base):
    """This save's League News as an edition kept by its newest game day: <base>/<save name>/<date>.html, with
    editions.js (the list every edition reads for its Back issues menu, newest first) and <base>/<save name>.html
    sending to the newest. The path of the edition written."""
    import json
    save = with_backups(root, read_save(data))
    news = build(save, Database(root))
    news["from_backups"] = save["from_backups"]
    page = render(news)
    name = "".join(c if c.isalnum() or c in " -_" else "_" for c in save["name"]).strip() or "save"
    when = news["today"] or news["next_day"]
    stem = when.isoformat() if when else "preseason"
    if news["postseason"] and when:
        stem += "-postseason"
    folder = os.path.join(base, name)
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, stem + ".html")
    with open(out + ".part", "w", encoding="utf-8") as f:
        f.write(page)
    os.replace(out + ".part", out)
    pat = re.compile(r"^(\d{4})-(\d\d)-(\d\d)(-postseason)?\.html$|^preseason\.html$")
    have = sorted((n for n in os.listdir(folder) if pat.match(n)), reverse=True)
    for old in have[KEEP_EDITIONS:]:
        try:
            os.remove(os.path.join(folder, old))
        except OSError:
            pass
    have = have[:KEEP_EDITIONS]
    def label(n):
        m = pat.match(n)
        if not m or not m.group(1):
            return "Before the season"
        d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return f"{d.strftime('%a')} {d.month}/{d.day}/{d.year}" + (" (postseason)" if m.group(4) else "")
    # newest first: by date (the preseason page before every dated one)
    have.sort(key=lambda n: (n != "preseason.html", n), reverse=True)
    with open(os.path.join(folder, "editions.js"), "w", encoding="utf-8") as f:
        f.write("var EDITIONS=" + json.dumps([[n, label(n)] for n in have]) + ";\n")
    with open(os.path.join(base, name + ".html"), "w", encoding="utf-8") as f:
        href = html.escape(f"{name}/{have[0]}", quote=True).replace(" ", "%20")
        f.write(f"<!doctype html><meta charset=utf-8><title>{html.escape(name)}: League News</title>"
                f"<meta http-equiv=refresh content='0; url={href}'><a href='{href}'>The newest League News</a>")
    return out


def make(root, data):
    """The page for a save (data.dat's bytes), with the game installed at root: HTML text. Its transactions reach
    back through the game's backups of it (with_backups)."""
    save = with_backups(root, read_save(data))
    news = build(save, Database(root))
    news["from_backups"] = save["from_backups"]
    return render(news)
