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
        self.injuries = {}  # kind -> name: from the game's text file, once its layout is known
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

    def salary(self, key):
        p = self.players.get(key)
        return int(p.get(40) or 0) * 100_000 if p else 0


# ---- the save ---------------------------------------------------------------------------------------------------
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
        g = dict(day=dn, away=struct.unpack_from("<I", e, 4)[0], home=struct.unpack_from("<I", e, 16)[0],
                 played=bool(bf >> 11), innings=(bf >> 11) + 1 if bf >> 11 else 0)
        if g["played"]:
            g.update(ar=e[8], ah=e[9], hr=e[20], hh=e[21])
        games.append(g)
    end = p + 16 + 28 * sum(SCHED_CAPS)
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
    # the game's own news list (32 events, FORMAT_NOTES 3.5): kept for when its kinds are known
    feed = []
    for i in range(min(struct.unpack_from("<I", x, end + 1872)[0], 32)):
        k, a, _, w, d1, _ = struct.unpack_from("<IIIIHH", x, end + 1876 + 20 * i)
        feed.append(dict(key=k, value=a, kind=(w >> 2) & 0x3F, word=w, day=d1))
    names, hurt = _players(x)
    rosters = _rosters(x)
    user = None
    if len(marks) in (7, 9):  # the user section: marker 4 in a dynasty, 6 in an owner mode (budget05 reads it too)
        user = struct.unpack_from("<I", x, marks[len(marks) - 3] + 8)[0]
    return dict(name=name, kind=kind, records=records, games=games, trades=trades, moves=moves, hurt=hurt,
                names=names, rosters=rosters, feed=feed, user=user)


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
    twice = t8 + t8[:60]  # (the records start 24 bytes in and the last one wraps to the table's start)
    names, hurt = {}, []
    for i in range(3250):
        key, row, _ = struct.unpack_from("<III", x, start + 8 + 12 * i)
        if row >= 3250:
            continue
        o = (24 + 60 * row) % len(t8)
        r = twice[o:o + 60]
        first = r[8:20].split(b"\0")[0].decode("latin-1").strip()
        last = r[20:36].split(b"\0")[0].decode("latin-1").strip()
        if first or last:
            names[key] = " ".join(f"{first} {last}".split())
        f = L.xb_fields(r)
        if f.get("f1F"):
            hurt.append(dict(player=key, kind=f.get("f1E", 0), days=f["f1F"]))
    return names, hurt


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
    # the postseason: the season's records are cleared and the schedule holds only the playoff games
    postseason = games_played == 0 and 0 < len(save["games"]) <= 41

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

    def add(score, kind, head, body, d, teams_, players=()):
        mult = WEIGHTS["your_team"] if mine(*teams_) else 1.0
        stories.append(dict(score=score * mult * fade(d), kind=kind, head=head, body=body, day=d,
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

    seen_on = {}  # where a player was before each move, by date
    for mv in sorted(save["moves"], key=lambda m: m["day"]):
        k, to = mv["player"], mv["team"]
        before = seen_on.get(k, db.team_of.get(k))
        seen_on[k] = to
        up = to in rec
        imp = db.importance(k)
        score = WEIGHTS["callup" if up else "senddown"] * imp * contention(to)
        org = db.org_of.get(to)
        same_org = before is not None and db.org_of.get(before) == org
        if up:
            head = f"{db.club(to)} call up {last(k)}"
            body = f"The {db.full(to)} called up {who(k)}" + (
                f" from {db.farm(before)}." if same_org and before != to else ".")
        elif same_org and before in rec:
            head = f"{db.club(org)} send {last(k)} down"
            body = f"The {db.full(org)} optioned {who(k)} to {db.farm(to)}."
        elif same_org:
            head = f"{last(k)} moves to {db.city(to)}"
            body = f"The {db.full(org)} moved {who(k)} from {db.farm(before)} to {db.farm(to)}."
        else:
            head = f"{last(k)} assigned to {db.city(to)}"
            body = f"{who(k)} was assigned to {db.named(to)}."
        add(score, "Roster move", head, body, mv["day"], [to], [k])

    for h in save["hurt"]:
        k, days = h["player"], h["days"]
        t = team_of.get(k)
        big_club = t in rec
        imp = db.importance(k)
        # the longer he's out and the bigger he is, the bigger the story; farm teams' injuries stay in the report
        length = min(days, 120) / 30
        score = WEIGHTS["injury"] * imp * (0.4 + length) * (contention(t) if t else 1.0) * (1 if big_club else 0.12)
        back = day(today + days) if today else None
        kind = db.injury(h["kind"])
        rest_of_year = bool(season_end and today + days > season_end)
        span = "the postseason" if postseason else "the season"
        out = (f"for the postseason ({_out_for(days)})" if postseason else
               f"for the rest of the season ({_out_for(days)})") if rest_of_year else _out_for(days)
        where = f" ({db.tag(t)})" if t else ""
        short_out = f"for {span}" if rest_of_year else _out_for(days)
        head = (f"{db.club(t)} lose {last(k)} {short_out}" if big_club and imp > 0.5 else f"{last(k)} out {short_out}")
        body = (f"{who(k)}{where} is out {out}" + (f" with {kind}" if kind else "") +
                (f", expected back around {back.strftime('%B')} {back.day}." if back and not rest_of_year else "."))
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
                trades=sorted((s for s in stories if s["kind"] == "Trade"),
                              key=lambda s: (not any(t in rec for t in s["raw_teams"]), -s["day"])),
                injuries=sorted((s for s in stories if s["kind"] == "Injury"),
                                key=lambda s: (not s["big_club"], -s["days"])),
                moves=sorted((s for s in stories if s["kind"] == "Roster move"),
                             key=lambda s: (not any(t in rec for t in s["raw_teams"]), -s["day"])),
                user=save["user"], games_played=games_played, db=db)


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


# ---- the page ---------------------------------------------------------------------------------------------------
CSS = """
:root{--ink:#1b1b1b;--muted:#5d6670;--line:#c9d1da;--paper:#fff;--bg:#e9edf1;--navy:#0b2a4a;--navy2:#123c66;
--red:#b3122e;--hi:#fff7d6;--link:#0b4f8a}
@media (prefers-color-scheme:dark){:root{--ink:#e6e9ec;--muted:#9aa5b1;--line:#34404c;--paper:#151b22;--bg:#0d1217;
--navy:#0a1f36;--navy2:#0f2d4d;--hi:#3a3216;--link:#8cc4ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:13px/1.45 Verdana,Tahoma,Arial,sans-serif}
.wrap{max-width:1000px;margin:0 auto;background:var(--paper);border-left:1px solid var(--line);border-right:1px solid var(--line)}
header{background:linear-gradient(var(--navy2),var(--navy));color:#fff;padding:14px 16px 10px;border-bottom:4px solid var(--red)}
header h1{margin:0;font:bold 26px/1.1 Georgia,'Times New Roman',serif;letter-spacing:.5px}
header .sub{color:#c8d6e5;font-size:11px;margin-top:4px;text-transform:uppercase;letter-spacing:1px}
nav{display:flex;flex-wrap:wrap;background:#dfe5ec;border-bottom:1px solid var(--line)}
@media (prefers-color-scheme:dark){nav{background:#1b232c}}
nav a{padding:6px 12px;color:var(--navy2);font-weight:bold;font-size:11px;text-decoration:none;text-transform:uppercase;border-right:1px solid var(--line)}
@media (prefers-color-scheme:dark){nav a{color:#bcd3ea}}
.ticker{display:flex;gap:6px;overflow-x:auto;padding:8px;background:#f4f6f8;border-bottom:1px solid var(--line)}
@media (prefers-color-scheme:dark){.ticker{background:#10161c}}
.box{min-width:118px;border:1px solid var(--line);background:var(--paper);font-size:11px}
.box div{display:flex;justify-content:space-between;padding:2px 6px}.box .w{font-weight:bold}
.box .st{background:#dfe5ec;color:var(--muted);font-size:10px;padding:1px 6px;text-transform:uppercase}
@media (prefers-color-scheme:dark){.box .st{background:#1b232c}}
main{display:grid;grid-template-columns:1fr 330px;gap:16px;padding:16px}
@media (max-width:760px){main{grid-template-columns:1fr}}
h2{font:bold 12px Verdana,sans-serif;text-transform:uppercase;letter-spacing:1px;color:#fff;background:var(--navy2);margin:18px 0 8px;padding:4px 8px}
h2:first-child{margin-top:0}
.lead h3{font:bold 24px/1.15 Georgia,serif;margin:4px 0 6px}.lead p{font-size:14px;margin:0 0 8px}
.kind{display:inline-block;font-size:10px;font-weight:bold;text-transform:uppercase;color:var(--red);letter-spacing:.5px}
.date{color:var(--muted);font-size:11px}
.heads{list-style:none;margin:0;padding:0}.heads li{padding:8px 0;border-top:1px dotted var(--line)}
.heads b{font-family:Georgia,serif;font-size:15px}.heads p{margin:2px 0 0;color:var(--muted)}
.mine{background:var(--hi)}
table{width:100%;border-collapse:collapse;font-size:11px;margin-bottom:10px}
th{background:#dfe5ec;text-align:right;padding:3px 5px;font-size:10px;text-transform:uppercase}
@media (prefers-color-scheme:dark){th{background:#1b232c}}
td{padding:3px 5px;border-bottom:1px solid var(--line);text-align:right;font-variant-numeric:tabular-nums}
th:first-child,td:first-child{text-align:left}
.list{list-style:none;padding:0;margin:0;font-size:12px}.list li{padding:4px 0;border-bottom:1px solid var(--line)}
.match{border:1px solid var(--line);padding:6px 8px;margin-bottom:6px}.match b{font-family:Georgia,serif}
footer{color:var(--muted);font-size:10px;padding:10px 16px;border-top:1px solid var(--line)}
"""


def render(news):
    db = news["db"]
    e = html.escape
    fmt = lambda d: d.strftime("%A, %B %-d, %Y") if os.name != "nt" else d.strftime("%A, %B %d, %Y").replace(" 0", " ")
    short = lambda d: f"{d.strftime('%b')} {d.day}"
    out = ["<!doctype html><html lang=en><head><meta charset=utf-8>",
           "<meta name=viewport content='width=device-width,initial-scale=1'>",
           f"<title>League News: {e(news['name'])}</title><style>{CSS}</style></head><body><div class=wrap>",
           "<header><h1>Baseball Today</h1>",
           f"<div class=sub>{e(news['name'])} &middot; {e(news['kind'])}"
           + (f" &middot; {fmt(news['today'])}" if news["today"] else "") + "</div></header>",
           "<nav><a href='#top'>Headlines</a><a href='#scores'>Scores</a><a href='#standings'>Standings</a>"
           "<a href='#matchups'>Matchups</a><a href='#wire'>Transactions</a><a href='#injuries'>Injuries</a></nav>"]
    if news["results"]:
        out.append("<div class=ticker id=scores>")
        for g in news["results"]:
            aw, hw = g["ar"] > g["hr"], g["hr"] > g["ar"]
            fin = "Final" + (f"/{g['innings']}" if g["innings"] > 9 else "")
            out.append(f"<div class=box><div class=st>{fin}</div>"
                       f"<div class={'w' if aw else ''}><span>{e(db.short(g['away']))}</span><span>{g['ar']}</span></div>"
                       f"<div class={'w' if hw else ''}><span>{e(db.short(g['home']))}</span><span>{g['hr']}</span></div></div>")
        out.append("</div>")
    out.append("<main><div>")
    heads = news["headlines"]
    out.append("<h2 id=top>Top stories</h2>")
    if heads:
        h = heads[0]
        out.append(f"<div class='lead{' mine' if h['mine'] else ''}'><span class=kind>{e(h['kind'])}</span> "
                   f"<span class=date>{short(day(h['day']))}</span><h3>{e(h['head'])}</h3><p>{e(h['body'])}</p></div>")
        out.append("<ul class=heads>")
        for h in heads[1:]:
            out.append(f"<li class='{'mine' if h['mine'] else ''}'><span class=kind>{e(h['kind'])}</span> "
                       f"<span class=date>{short(day(h['day']))}</span><br><b>{e(h['head'])}</b><p>{e(h['body'])}</p></li>")
        out.append("</ul>")
    else:
        out.append("<p>No news yet: play a few days and come back.</p>")
    out.append("<h2 id=wire>Transactions</h2><ul class=list>")
    for s in (news["trades"] + news["moves"])[:40]:
        out.append(f"<li><span class=date>{short(day(s['day']))}</span> {e(s['body'])}</li>")
    if not news["trades"] and not news["moves"]:
        out.append("<li>None yet.</li>")
    out.append("</ul><h2 id=injuries>Injury report</h2><ul class=list>")
    majors = [s for s in news["injuries"] if s["big_club"]]
    minors = [s for s in news["injuries"] if not s["big_club"]]
    for s in majors:
        out.append(f"<li>{e(s['body'])}</li>")
    if not majors:
        out.append("<li>Every big-league club is healthy.</li>")
    if minors:
        out.append(f"<li class=date>In the minors and elsewhere: {len(minors)} more</li>")
        for s in minors[:25]:
            out.append(f"<li>{e(s['body'])}</li>")
    out.append("</ul></div><aside>")
    out.append("<h2 id=standings>Standings</h2>")
    if news["postseason"]:
        out.append("<p>It's the postseason: the season's standings are put away until next year.</p>")
    for d in ([] if news["postseason"] else news["divisions"]):
        out.append(f"<table><tr><th>{e(d['name'])}</th><th>W</th><th>L</th><th>Pct</th><th>GB</th><th>L10</th>"
                   "<th>Strk</th></tr>")
        for r in d["rows"]:
            gb = "&ndash;" if r["gb"] == 0 else f"{r['gb']:g}"
            cls = " class=mine" if r["team"] == news["user"] else ""
            out.append(f"<tr{cls}><td>{e(db.club(r['team']))}</td><td>{r['w']}</td><td>{r['l']}</td>"
                       f"<td>{r['pct']:.3f}".replace("0.", ".", 1) + f"</td><td>{gb}</td><td>{r['last10']}</td>"
                       f"<td>{r['streak']}</td></tr>")
        out.append("</table>")
    for lg, rows in ([] if news["postseason"] else sorted(news["wildcard"].items())):
        out.append(f"<table><tr><th>{'AL' if lg == 0 else 'NL'} Wild Card</th><th>W</th><th>L</th><th>GB</th></tr>")
        for r in rows[:5]:
            gb = "&ndash;" if r["wcgb"] == 0 else f"{r['wcgb']:g}"
            out.append(f"<tr><td>{e(db.club(r['team']))}</td><td>{r['w']}</td><td>{r['l']}</td><td>{gb}</td></tr>")
        out.append("</table>")
    if news["upcoming"]:
        out.append(f"<h2 id=matchups>{'Postseason' if news['postseason'] else 'Next up'}: "
                   f"{short(news['next_day'])}</h2>")
        for g in news["upcoming"][:6]:
            a, h = g["away"], g["home"]
            ra, rh = news_record(news, a), news_record(news, h)
            rec = "" if news["postseason"] else " (%s)"
            out.append(f"<div class=match><b>{e(db.club(a))}</b>{rec and rec % ra} at "
                       f"<b>{e(db.club(h))}</b>{rec and rec % rh}</div>")
    out.append("</aside></main>")
    out.append("<footer>Made by the MVP05-Plus Launcher from your save. Names and teams are read from your own game. "
               "Nothing in your save is changed.</footer></div></body></html>")
    return "".join(out)


def news_record(news, t):
    for d in news["divisions"]:
        for r in d["rows"]:
            if r["team"] == t:
                return f"{r['w']}-{r['l']}"
    return ""


def make(root, data):
    """The page for a save (data.dat's bytes), with the game installed at root: HTML text."""
    return render(build(read_save(data), Database(root)))
