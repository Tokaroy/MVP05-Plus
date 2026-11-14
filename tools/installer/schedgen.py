"""Generated seasons for MVP 2005: any length, built from scratch the way a real one is, for the three dynasty years.

A season is a run of rounds. In each round every one of the 30 teams plays one series (3 games, or 2 or 4 where the
length needs it) against one opponent, so every team plays the same number of games. Who plays whom how often
follows the MVP 2005 disc's own season, scaled to the length:

  division rivals   about 12 games each over 162
  the rest of the league   about 10 or 11 games each
  interleague       a series against each team of the paired division, and a second one against a natural rival

Home and away are dealt so every team plays half its games at home (within a game when the length is odd) and each
pair splits its series. The calendar is the 2005 one: opening day April 4, the All-Star Game on July 12 (the HALF
column 0 before it, 1 after), off days spread through each half. A season of 100 games or more spreads over the whole
calendar; a shorter one plays its first half from opening day with an off day every few series, and its second
half from August 1, after the trade deadline, when it fits before October 3.

The rows are written as the disc's are: "DATE,GAMETIME,HOME,AWAY,HALF," then
"4/4/2005,19:05,NYY,Bos,0,19:05" (local start time, then Eastern), 2005 dates in all three years as on the disc.
"""
import datetime
import random

DIVISIONS = {"AL East": "Bal Bos NYY TB Tor", "AL Central": "CWS Cle Det KC Min", "AL West": "Ana Oak Sea Tex",
             "NL East": "Atl Fla NYM Phi Was", "NL Central": "ChC Cin Hou Mil Pit StL", "NL West": "Ari Col LA SD SF"}
AL = ("AL East", "AL Central", "AL West")
NL = ("NL East", "NL Central", "NL West")
REAL_PAIRING = {"AL East": "NL East", "AL Central": "NL Central", "AL West": "NL West"}  # 2005's
# the disc's six-game interleague pairs (two series a year)
RIVALS = (("NYY", "NYM"), ("CWS", "ChC"), ("Oak", "SF"), ("Ana", "LA"), ("Tex", "Ari"), ("Bos", "Atl"),
          ("Bal", "Phi"), ("Cle", "Cin"), ("TB", "Fla"), ("KC", "Pit"), ("Sea", "SD"), ("Tor", "Was"))
# hours behind Eastern time in summer (Arizona keeps Pacific's)
ZONE = {t: 0 for t in "Bal Bos NYY TB Tor Det Cle Atl Fla NYM Phi Was Pit Cin".split()}
ZONE.update({t: 1 for t in "CWS KC Min ChC Hou Mil StL Tex".split()})
ZONE.update({"Col": 2})
ZONE.update({t: 3 for t in "Ana Oak Sea LA SD SF Ari".split()})
TEAMS = [t for d in DIVISIONS.values() for t in d.split()]
DIV = {t: d for d, ts in DIVISIONS.items() for t in ts.split()}

OPENING = datetime.date(2005, 4, 4)
ALL_STAR = datetime.date(2005, 7, 12)
FIRST_HALF_END = datetime.date(2005, 7, 10)    # the break: July 11 to 13
SECOND_HALF = datetime.date(2005, 7, 14)
AFTER_DEADLINE = datetime.date(2005, 8, 1)
LAST_DAY = datetime.date(2005, 10, 2)
MIN_GAMES, MAX_GAMES = 12, 162
INTERLEAGUE = ("real", "choose", "rotate", "off")
ALL_STAR_HOST = ("AL", "NL", "alternate")


class GenError(Exception):
    pass


def default_options():
    return {"games": 162, "interleague": "real", "pairing": dict(REAL_PAIRING), "rivals": True,
            "all_star": "alternate"}


def pairing_for(options, year):
    """Which NL division each AL division meets in year (1 to 3), or None without interleague."""
    mode = options.get("interleague", "real")
    if mode == "off":
        return None
    if mode == "choose":
        p = dict(options.get("pairing") or REAL_PAIRING)
        if sorted(p) != sorted(AL) or sorted(p.values()) != sorted(NL):
            raise GenError("each AL division needs its own NL division")
        return p
    if mode == "rotate":
        return {a: NL[(i + year - 1) % 3] for i, a in enumerate(AL)}
    return dict(REAL_PAIRING)


def host_for(options, year):
    h = options.get("all_star", "alternate")
    return h if h in ("AL", "NL") else ("AL", "NL", "AL")[(year - 1) % 3]


# --- who plays whom: series counts per pair

def _weights(pairing, rivals):
    w = {}
    for i, a in enumerate(TEAMS):
        for b in TEAMS[i + 1:]:
            if DIV[a] == DIV[b]:
                x = 12.3
            elif DIV[a][:2] == DIV[b][:2]:
                x = 10.6
            else:
                x = 0.0
                if pairing:
                    al, nl = (a, b) if DIV[a] in AL else (b, a)
                    if pairing[DIV[al]] == DIV[nl]:
                        x += 3.0
                    if rivals and ((al, nl) in RIVALS):
                        x += 3.0
            if x:
                w[(a, b)] = x
    return w


def _key(a, b):
    return (a, b) if TEAMS.index(a) < TEAMS.index(b) else (b, a)


def _series_counts(rounds, pairing, rivals, rng):
    """{pair: series} with every team in exactly `rounds` series."""
    w = _weights(pairing, rivals)
    tot = {t: 0.0 for t in TEAMS}
    for (a, b), x in w.items():
        tot[a] += x
        tot[b] += x
    x = {}
    for (a, b), v in w.items():
        target = rounds * v / ((tot[a] + tot[b]) / 2)
        n = int(target)
        if rng.random() < target - n:
            n += 1
        x[(a, b)] = n
    deg = {t: 0 for t in TEAMS}
    for (a, b), n in x.items():
        deg[a] += n
        deg[b] += n
    league = [p for p in w if DIV[p[0]][:2] == DIV[p[1]][:2]]
    for _ in range(20000):
        over = [t for t in TEAMS if deg[t] > rounds]
        under = [t for t in TEAMS if deg[t] < rounds]
        if not over and not under:
            break
        if len(over) >= 2 and rng.random() < 0.5 or not under:
            a = rng.choice(over)
            opts = [p for p in w if a in p and x[p] > 0 and deg[p[0] if p[1] == a else p[1]] > rounds]
            if opts:
                p = max(opts, key=lambda p: (x[p] - w[p] * rounds / 54) + rng.random() * 0.5)
                x[p] -= 1
                deg[p[0]] -= 1
                deg[p[1]] -= 1
                continue
            # take one away from a and give it to a partner pair: a-b out, b-c in, where c is under
            opts = [p for p in w if a in p and x[p] > 0]
            p = rng.choice(opts)
            b = p[0] if p[1] == a else p[1]
            x[p] -= 1
            deg[a] -= 1
            deg[b] -= 1
            continue
        a = rng.choice(under)
        opts = [p for p in league if a in p and deg[p[0] if p[1] == a else p[1]] < rounds]
        opts = opts or [p for p in w if a in p and deg[p[0] if p[1] == a else p[1]] < rounds]
        if opts:
            p = min(opts, key=lambda p: (x[p] - w[p] * rounds / 54) + rng.random() * 0.5)
            x[p] += 1
            deg[p[0]] += 1
            deg[p[1]] += 1
            continue
        # every other team is full: one of a's league partners b gives up a series with c, and a plays both
        opts = [p for p in league if a in p]
        p = rng.choice(opts)
        b = p[0] if p[1] == a else p[1]
        rest = [q for q in w if b in q and a not in q and x[q] > 0]
        if not rest:
            continue
        q = rng.choice(rest)
        c = q[0] if q[1] == b else q[1]
        x[q] -= 1
        deg[c] -= 1
        deg[b] -= 1
        x[p] += 1
        deg[a] += 1
        deg[b] += 1
        k = _key(a, c)
        if k in x:
            x[k] += 1
            deg[a] += 1
            deg[c] += 1
    if any(deg[t] != rounds for t in TEAMS):
        raise GenError("couldn't share out the series")
    return {p: n for p, n in x.items() if n}


# --- rounds: every team plays one series in each

def _matching(left, rounds_left, last, rng, inter_bonus):
    """A perfect matching of the 30 teams from the pairs with series left, the most pressing first."""
    nbr = {t: [] for t in TEAMS}
    for (a, b), n in left.items():
        if n:
            nbr[a].append(b)
            nbr[b].append(a)

    def score(a, b):
        n = left[_key(a, b)]
        s = n / rounds_left + rng.random() * 0.35
        if frozenset((a, b)) in last:
            s -= 0.6
        if DIV[a][:2] != DIV[b][:2]:
            s += inter_bonus
        return s

    out, used = [], set()
    steps = [0]

    def go():
        free = [t for t in TEAMS if t not in used]
        if not free:
            return True
        steps[0] += 1
        if steps[0] > 4000:
            return False
        t = min(free, key=lambda t: (sum(1 for b in nbr[t] if b not in used), rng.random()))
        cands = sorted((b for b in nbr[t] if b not in used), key=lambda b: -score(t, b))
        for b in cands:
            used.update((t, b))
            out.append((t, b))
            if go():
                return True
            out.pop()
            used.difference_update((t, b))
        return False
    return out if go() else None


def _rounds(counts, rounds, rng):
    for _ in range(40):
        left = dict(counts)
        seq, last = [], set()
        for r in range(rounds):
            mid = 0.3 * rounds <= r <= 0.65 * rounds  # interleague mostly in May and June, as in 2005
            m = _matching(left, rounds - r, last, rng, 0.25 if mid else -0.15)
            if m is None:
                break
            for a, b in m:
                left[_key(a, b)] -= 1
            seq.append(m)
            last = {frozenset(p) for p in m}
        else:
            return seq
    raise GenError("couldn't lay the series out in rounds")


# --- home and away

def _flow_extras(odd_pairs, need_lo, need_hi, rng):
    """Which team of each odd pair gets its extra home series, every team t getting between need_lo[t] and
    need_hi[t] of them: augmenting paths (a b-matching of pairs to teams), first up to need_lo, then up to need_hi."""
    give, load = {}, {t: 0 for t in TEAMS}
    holds = {t: [] for t in TEAMS}
    order = odd_pairs[:]
    rng.shuffle(order)

    def dfs(p, cap, seen):
        ts = list(p)
        rng.shuffle(ts)
        for t in ts:
            if t in seen:
                continue
            seen.add(t)
            if load[t] < cap[t]:
                load[t] += 1
                holds[t].append(p)
                give[p] = t
                return True
            for q in list(holds[t]):
                u = q[0] if q[1] == t else q[1]
                if u in seen:
                    continue
                if dfs_move(q, t, u, cap, seen):
                    holds[t].remove(q)
                    holds[t].append(p)
                    give[p] = t
                    return True
        return False

    def dfs_move(q, frm, to, cap, seen):
        """q goes from team frm to team to (making room on frm), if `to` has room or can make it."""
        seen.add(to)
        if load[to] < cap[to]:
            load[to] += 1
            holds[to].append(q)
            give[q] = to
            return True
        for r in list(holds[to]):
            u = r[0] if r[1] == to else r[1]
            if u in seen:
                continue
            if dfs_move(r, to, u, cap, seen):
                holds[to].remove(r)
                holds[to].append(q)
                give[q] = to
                return True
        return False

    for cap in (need_lo, need_hi):
        for p in order:
            if p not in give:
                dfs(p, cap, set())
    if len(give) != len(odd_pairs) or any(load[t] < need_lo[t] for t in TEAMS):
        raise GenError("couldn't even out home and away")
    return give


def _homes(seq, lengths, games, rng):
    """For each round, [(home, away)]: every team at home for half its series (within one when it has an odd number),
    each pair splitting its series and taking turns."""
    by_pair = {}
    for r, m in enumerate(seq):
        for a, b in m:
            by_pair.setdefault(_key(a, b), []).append(r)
    rounds = len(seq)
    base = {t: 0 for t in TEAMS}
    odd = []
    for p, rs in by_pair.items():
        for t in p:
            base[t] += len(rs) // 2
        if len(rs) % 2:
            odd.append(p)
    lo = {t: rounds // 2 - base[t] for t in TEAMS}
    hi = {t: (rounds + 1) // 2 - base[t] for t in TEAMS}
    if any(v < 0 for v in lo.values()):
        raise GenError("couldn't even out home and away")
    extra = _flow_extras(odd, lo, hi, rng)
    # each pair's series alternate to start with (the extra one, if odd, to the team the flow gave it)
    home = {}  # (pair, round) -> home team
    for p, rs in by_pair.items():
        f = extra[p] if p in extra else rng.choice(p)
        o = p[0] if f == p[1] else p[1]
        for k, r in enumerate(rs):
            home[(p, r)] = f if k % 2 == 0 else o
    # then swaps within a pair (one of its home series for one of its road ones), which change nobody's totals:
    # kept when they shorten long home stands and road trips (real ones are about three series at most)
    team_rounds = {t: [] for t in TEAMS}
    for r, m in enumerate(seq):
        for a, b in m:
            team_rounds[a].append((r, _key(a, b)))
            team_rounds[b].append((r, _key(a, b)))

    def penalty(t):
        run, last, cost = 0, None, 0
        for r, p in team_rounds[t]:
            h = home[(p, r)] == t
            run = run + 1 if h == last else 1
            last = h
            if run > 2:
                cost += (run - 2) ** 3
        return cost

    multi = [p for p, rs in by_pair.items() if len(rs) >= 2]
    if multi:
        for _ in range(60 * len(multi)):
            p = rng.choice(multi)
            rs = by_pair[p]
            a = [r for r in rs if home[(p, r)] == p[0]]
            b = [r for r in rs if home[(p, r)] == p[1]]
            if not a or not b:
                continue
            ra, rb = rng.choice(a), rng.choice(b)
            before = penalty(p[0]) + penalty(p[1])
            home[(p, ra)], home[(p, rb)] = p[1], p[0]
            if penalty(p[0]) + penalty(p[1]) > before:
                home[(p, ra)], home[(p, rb)] = p[0], p[1]
    out = [[None] * len(m) for m in seq]
    for r, m in enumerate(seq):
        for i, (a, b) in enumerate(m):
            hm = home[(_key(a, b), r)]
            out[r][i] = (hm, b if hm == a else a)
    return out


# --- the calendar

def _days(first, last, game_days, rounds_n, fill):
    """Start days for rounds_n rounds of the given lengths from `first`, with off days spread between them: about one
    every three series, or (fill) as many as it takes to end on `last`; never past `last` if it can help it."""
    span = (last - first).days + 1
    off = max(0, span - sum(game_days)) if fill else max(0, min(span - sum(game_days), rounds_n // 3 + 1))
    gaps = [0] * rounds_n
    if rounds_n > 1 and off:
        for k in range(off):
            gaps[1 + (k * (rounds_n - 1)) // off] += 1
    out, d = [], first
    for i, n in enumerate(game_days):
        d += datetime.timedelta(days=gaps[i])
        out.append(d)
        d += datetime.timedelta(days=n)
    return out


def _time(day, home, k, n):
    """Local start time and Eastern: Sundays and a series' last weekday game in the afternoon, else the evening."""
    if day.weekday() == 6 or (k == n - 1 and day.weekday() in (2, 3)):
        local = (13, 5)
    elif day.weekday() == 5:
        local = (16, 5) if ZONE[home] else (13, 5)
    else:
        local = (19, 5)
    east = (local[0] + ZONE[home], local[1])
    return "%d:%02d" % local, "%d:%02d" % east


def _fmt(d):
    return f"{d.month}/{d.day}/{d.year}"


def season(options, year=1, seed=None):
    """One season file (bytes), as the disc's mlb162_<year>.dat."""
    games = int(options.get("games", 162))
    if not MIN_GAMES <= games <= MAX_GAMES:
        raise GenError(f"a season has {MIN_GAMES} to {MAX_GAMES} games")
    rng = random.Random(f"{seed}:{year}")
    rounds = max(1, round(games / 3))
    lengths = [3] * rounds
    extra = games - 3 * rounds  # -1 or +1: one round of 2 or 4 games
    for k in range(abs(extra)):
        lengths[rounds // 2 + k] += 1 if extra > 0 else -1
    for attempt in range(20):
        counts = _series_counts(rounds, pairing_for(options, year), options.get("rivals", True), rng)
        try:
            seq = _rounds(counts, rounds, rng)
            break
        except GenError:
            if attempt == 19:
                raise
    homes = _homes(seq, lengths, games, rng)
    first_n = max(1, round(rounds * 0.54)) if rounds > 1 else 1
    fill = games >= 100  # a long season spreads over the whole calendar; a short one plays on, with breaks
    first = _days(OPENING, FIRST_HALF_END, lengths[:first_n], first_n, fill)
    n2 = rounds - first_n
    if n2:
        need = sum(lengths[first_n:]) + n2 // 3
        start2 = AFTER_DEADLINE if not fill and (LAST_DAY - AFTER_DEADLINE).days + 1 >= need else SECOND_HALF
        second = _days(start2, LAST_DAY, lengths[first_n:], n2, fill)
    else:
        second = []
    starts = first + second
    rows = []
    for r, (d0, n) in enumerate(zip(starts, lengths)):
        half = "0" if r < first_n else "1"
        for k in range(n):
            day = d0 + datetime.timedelta(days=k)
            for hm, aw in sorted(homes[r], key=lambda p: (ZONE[p[0]] * -1, p[0])):
                lt, et = _time(day, hm, k, n)
                rows.append((day, et, f"{_fmt(day)},{lt},{hm},{aw},{half},{et}"))
    host = host_for(options, year)
    rows.append((ALL_STAR, "20:05", f"{_fmt(ALL_STAR)},19:05,{host},{'NL' if host == 'AL' else 'AL'},-,20:05"))
    rows.sort(key=lambda x: (x[0], int(x[1].split(":")[0]) * 60 + int(x[1].split(":")[1])))
    text = "DATE,GAMETIME,HOME,AWAY,HALF,\r\n\r\n" + "".join(r[2] + "\r\n" for r in rows)
    out = text.encode("latin-1")
    check(out, games)
    return out


def seasons(options, seed):
    """The three dynasty years' season files."""
    return [season(options, y, seed) for y in (1, 2, 3)]


def check(text, games):
    """Every team plays `games`, half at home, never twice in a day, and the All-Star Game is there; or GenError."""
    played, home, days = {}, {}, {}
    star = 0
    for line in text.decode("latin-1").splitlines()[1:]:
        f = line.split(",")
        if len(f) < 6 or not f[0]:
            continue
        if f[2] in ("AL", "NL"):
            star += 1
            continue
        for t in f[2:4]:
            played[t] = played.get(t, 0) + 1
            key = (t, f[0])
            if key in days:
                raise GenError(f"{t} plays twice on {f[0]}")
            days[key] = 1
        home[f[2]] = home.get(f[2], 0) + 1
    if star != 1:
        raise GenError("the All-Star Game is missing")
    if set(played) != set(TEAMS) or set(played.values()) != {games}:
        raise GenError("not every team plays the whole season")
    rounds = max(1, round(games / 3))
    slack = 2 if rounds % 2 == 0 else 5  # an odd number of series can't split evenly: one more at home or away
    if any(abs(2 * home.get(t, 0) - games) > slack for t in TEAMS):
        raise GenError("home and away aren't even")


def team_view(text, team):
    """[(date, opponent, home?, half)] for one team, and {division, league, interleague, home, away} counts."""
    out, c = [], {"division": 0, "league": 0, "interleague": 0, "home": 0, "away": 0}
    for line in text.decode("latin-1").splitlines()[1:]:
        f = line.split(",")
        if len(f) < 5 or not f[0] or team not in f[2:4]:
            continue
        m, d, y = map(int, f[0].split("/"))
        hm = f[2] == team
        opp = f[3] if hm else f[2]
        out.append((datetime.date(y, m, d), opp, hm, f[4]))
        if opp in ("AL", "NL"):
            continue
        c["home" if hm else "away"] += 1
        c["division" if DIV[opp] == DIV[team] else "league" if DIV[opp][:2] == DIV[team][:2] else "interleague"] += 1
    return out, c
