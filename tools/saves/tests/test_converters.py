"""Every save converter on a folder of sample saves: what converts, what round trips exactly, and what's refused
(with a message, never a crash).

    python tools/saves/tests/test_converters.py <samples folder>

The samples are your own saves (never committed), under these names in the folder; a case whose samples are
missing is skipped:

    xb_roster.dat   xb_dyn.dat   xb_dyn2.dat   xb_own.dat         Xbox data.dat files (rosters, 2 dynasties, owner)
    pc_roster.sav   pc_dyn.sav   pc_own.sav                       PC saves
    ps2_roster.psu  ps2_dyn.psu  ps2_own.psu   ps2_card.ps2       PS2 saves and a PCSX2 card with rosters on it
    gc_roster.gci   gc_dyn.gci   gc_own.gci                       GameCube .gci files from Dolphin
    mvp06_ps2.psu   mvp06_xb.dat                                  MVP 06 saves (must be refused)
    xb_dyn_played.dat   database.big                              a dynasty some way into its season, and the
    feeng.loc   logos.big                                         game's database, text and logos (League News)
    xb_dyn_kcr.dat                                                spy_jam's KCR dynasty at April 29, 2007 (its
                                                                  League Leaders screen is the test's answers)
"""
import contextlib
import io
import os
import re
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import dynasty05 as DY
from made_cards import gc_card
import gccard as GCC
import gcroster05 as GR
import owner05 as OW
import pcdynasty05 as PCD
import playoffs05 as PO
import ps2card as PC
import ps2dynasty05 as PD
import rosters05 as RO

if len(sys.argv) < 2:
    sys.exit(__doc__)
SAMPLES = sys.argv[1]
F = {}
for n in sorted(os.listdir(SAMPLES)):
    k = os.path.splitext(n)[0]
    with open(os.path.join(SAMPLES, n), "rb") as f:
        F[k] = f.read()
if "gc_dyn" in F:
    F["truncated_gc"] = F["gc_dyn"][:500000]
F["random"] = bytes((i * 2654435761 >> 13) & 255 for i in range(2239752))
OK, BAD, SKIP = [], [], []
KNOWN = (GCC.GcCardError, RO.RosterError, GR.GcRosterError, DY.DynastyError, PD.Ps2DynastyError, PCD.PcDynastyError, OW.OwnerError,
         PC.CardError, PO.PlayoffsError)


class Missing(Exception):
    pass


class Samples(dict):
    def __missing__(self, k):
        raise Missing(k)


F = Samples(F)


def t(name, fn, expect_ok=True):
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            r = fn()
        (OK if expect_ok else BAD).append((name, "ok" if expect_ok else "converted but should have been refused"))
        return r
    except Missing as e:
        SKIP.append((name, f"no {e.args[0]} sample"))
    except KNOWN as e:
        (BAD if expect_ok else OK).append((name, f"refused: {e}"))
    except Exception as e:
        BAD.append((name, "CRASH " + type(e).__name__ + ": " + str(e) + " @ " +
                    traceback.extract_tb(e.__traceback__)[-1].name))


def same(a, b, what="bytes"):
    d = sum(1 for x, y in zip(a, b) if x != y) + abs(len(a) - len(b))
    assert d == 0, f"{d} {what} differ"
    return 1


# rosters to the Xbox
for k in ('xb_roster', 'pc_roster', 'ps2_roster'):
    t(f'{k} -> xbox rosters', lambda k=k: RO.to_xbox(RO.read(F[k]), F['xb_roster']))
t('gc_roster -> xbox rosters', lambda: GR.to_xbox(F['gc_roster'], F['xb_roster']))
def card_rosters():
    c = PC.Card(F['ps2_card']); n = 0
    for folder, files in c.saves().items():
        for nm, b in files.items():
            if len(b) == RO.SIZE + RO.PC_HEAD: RO.to_xbox(RO.read(b), F['xb_roster']); n += 1
    assert n, 'no rosters on the card'
    return n
t('ps2 memory card rosters -> xbox', card_rosters)
# dynasties
t('xb dyn -> xb dyn', lambda: DY.xbox_to_xbox(F['xb_dyn2'], F['xb_dyn']))
t('pc dyn -> xb', lambda: PCD.to_xbox(F['pc_dyn'], F['xb_dyn']))
t('ps2 dyn -> xb', lambda: PD.to_xbox(F['ps2_dyn'], F['xb_dyn']))
t('gc dyn -> xb', lambda: DY.gc_to_xbox(F['gc_dyn'], F['xb_dyn']))
t('xb dyn -> pc', lambda: PCD.to_pc(F['xb_dyn'], F['pc_dyn']))
t('xb dyn -> ps2', lambda: PD.to_ps2(F['xb_dyn'], F['ps2_dyn']))
t('xb dyn -> gc', lambda: DY.xbox_to_gc(F['xb_dyn'], F['gc_dyn']))
t('pc dyn round trip exact', lambda: same(PCD.to_pc(PCD.to_xbox(F['pc_dyn'], F['xb_dyn']), F['pc_dyn']), F['pc_dyn']))
def gc_rt():
    x = DY.gc_to_xbox(F['gc_dyn'], F['xb_dyn']); n, g = DY.xbox_to_gc(x, F['gc_dyn'])
    a = DY.read_gc(g)['payload']; b = DY.read_gc(F['gc_dyn'])['payload']; m = OW.markers(b, True)
    d = sum(1 for i in range(m[5]) if a[i] != b[i]); assert d == 0, f'{d} bytes differ before the history'
t('gc dyn round trip exact before history', gc_rt)
def ps2_rt():
    x = PD.to_xbox(F['ps2_dyn'], F['xb_dyn']); k, p = PD.to_ps2(x, F['ps2_dyn'])
    a = PD.read(p)['body']; b = PD.read(F['ps2_dyn'])['body']; m = PD._sections(b)
    d = sum(1 for i in range(m[5]) if a[i] != b[i]); assert d == 0, f'{d} bytes differ'
t('ps2 dyn round trip exact before history (into a different Xbox dynasty)', ps2_rt)
# owner mode
for k, fn in (('pc', OW.pc_to_xbox), ('ps2', OW.ps2_to_xbox), ('gc', OW.gc_to_xbox), ('xb', OW.xbox_to_xbox)):
    t(f'{k} owner -> xb owner', lambda fn=fn, k=k: OW.read_xbox(fn(F[k + '_own'], F['xb_own'])))
for k, fn in (('pc', OW.xbox_to_pc), ('ps2', OW.xbox_to_ps2), ('gc', OW.xbox_to_gc)):
    t(f'xb owner -> {k} owner', lambda fn=fn, k=k: fn(F['xb_own'], F[k + '_own']))
# rosters from the Xbox
t('xb rosters -> pc -> xb exact', lambda: same(RO.to_xbox(RO.read(RO.to_pc(F['xb_roster'], F['pc_roster'])),
                                                            F['xb_roster']), F['xb_roster']))
def ps2_roster_rt():
    _, b = RO.to_ps2(F['xb_roster'], F['ps2_roster'])
    return same(RO.to_xbox(RO.read(b), F['xb_roster']), F['xb_roster'])
t('xb rosters -> ps2 -> xb exact', ps2_roster_rt)
def gc_roster_rt():
    _, g = GR.xbox_to_gc(F['xb_roster'], F['gc_roster'])
    return same(GR.to_xbox(g, F['xb_roster']), F['xb_roster'])
t('xb rosters -> gc -> xb exact', gc_roster_rt)
def gc_roster_rt2():
    x = GR.to_xbox(F['gc_roster'], F['xb_roster'])
    _, g = GR.xbox_to_gc(x, F['gc_roster'])
    return same(g, F['gc_roster'])
t('gc rosters -> xb -> gc exact', gc_roster_rt2)
def card_roster_rt():
    c = PC.Card(F['ps2_card'])
    (folder, name), = [(fo, n) for fo, fs in c.saves().items() for n, b in fs.items() if len(b) == RO.SIZE + RO.PC_HEAD]
    _, sav = RO.to_ps2(F['xb_roster'], c.saves()[folder][name])
    card = c.replace_file(folder, name, sav)
    assert PC.Card(card).saves() == {**c.saves(), folder: {**c.saves()[folder], name: sav}}, "the rest of the card changed"
    return same(RO.to_xbox(RO.read(PC.Card(card).saves()[folder][name]), F['xb_roster']), F['xb_roster'])
t('xb rosters -> onto a ps2 memory card -> xb exact', card_roster_rt)
def gc_card_rt():
    card = gc_card([F['gc_roster'], F['gc_dyn'], F['gc_own']])
    files = GCC.Card(card).files()
    assert sorted(b[64:] for b in files.values()) == sorted(g[64:] for g in (F['gc_roster'], F['gc_dyn'], F['gc_own']))
    ros = [k for k in files if k.startswith('Rosters')][0]
    n, g = GR.xbox_to_gc(F['xb_roster'], files[ros])
    out = GCC.Card(card).replace(ros, g)
    after = GCC.Card(out).files()
    assert all(after[k] == files[k] for k in files if k != ros), "the card's other saves changed"
    return same(GR.to_xbox(after[ros], F['xb_roster']), F['xb_roster'])
t('gamecube memory card: saves read, rosters written back in place', gc_card_rt)
# renamed saves: a GameCube .gci and a PC .sav as their games name them
def gc_rename(k, reader):
    g = F[k]
    own = g[8:0x28].split(b"\0")[0].decode()
    assert DY.gc_renamed(g, own[own.rindex("_") + 1:-4])[1] == g, "renamed to its own name, it isn't the same file"
    fname, b = DY.gc_renamed(g, "RENAMED2")
    r = reader(b)
    assert (r[1] if isinstance(r, tuple) else r)["name"] == "RENAMED2" and "_RENAMED2.dat" in fname
    return 1
t('gc dynasty renamed', lambda: gc_rename('gc_dyn', DY.read_gc))
t('gc owner mode renamed', lambda: gc_rename('gc_own', OW.read_gc))
t('gc rosters renamed', lambda: gc_rename('gc_roster', GR.read_gc))
def pc_rename(k, reader):
    fname, b = PCD.pc_renamed(F[k], "RENAMED2")
    reader(b)
    assert PCD.pc_name(b)[0] == "RENAMED2" and fname.startswith("RENAMED2_")
    return 1
t('pc dynasty renamed', lambda: pc_rename('pc_dyn', PCD.read))
t('pc owner mode renamed', lambda: pc_rename('pc_own', OW.read_pc))
t('pc rosters renamed', lambda: pc_rename('pc_roster', RO.read))
# the save tools: the payroll budget (and an owner's bank balance), standings
def budget(k, bank=None):
    import shutil
    import tempfile
    import budget05 as BU
    import saves05 as S5
    S5.game_running = lambda: False
    root = tempfile.mkdtemp()
    folder = os.path.join(root, "hdd", "E", "UDATA", "45410056", "ABCDEF012345")
    os.makedirs(folder)
    with open(os.path.join(folder, "data.dat"), "wb") as f:
        f.write(F[k])
    before = BU.read(folder)
    BU.write(root, folder, 87_600_000, say=lambda *_: None, bank=bank)
    after = BU.read(folder)
    shutil.rmtree(root)
    assert after["budget"] == 87_600_000 and after["team"] == before["team"], (before, after)
    assert bank is None or abs(after["bank"] - bank) < 1, after
    return 1
t('payroll budget set in a dynasty', lambda: budget('xb_dyn'))
t('payroll budget and bank balance set in an owner mode', lambda: budget('xb_own', 12_345_678))
def standings(k):
    import tempfile
    import saves05 as S5
    folder = tempfile.mkdtemp()
    with open(os.path.join(folder, "data.dat"), "wb") as f:
        f.write(F[k])
    r = S5.read_standings(folder)
    assert len(r["records"]) == 30
    return 1
t('standings read from a dynasty', lambda: standings('xb_dyn'))
t('standings read from an owner mode', lambda: standings('xb_own'))
# a played dynasty (a roster block ends in bytes that look like a lineup unit: 127 teams were found)
def played_rt():
    fn, g = DY.xbox_to_gc(F['xb_dyn_played'], F['gc_dyn'])
    x = DY.gc_to_xbox(g, F['xb_dyn_played'])
    a, b = DY.read_xbox(x)['payload'], DY.read_xbox(F['xb_dyn_played'])['payload']
    marks = [m.start() for m in re.finditer(re.escape(b'\x0d\xf0\xef\xbe'), b)]
    d = [i for i in range(marks[5]) if a[i] != b[i]]
    # (the 9 values after the schedules are kept at zero, FORMAT_NOTES 3.5: 18 bytes at most)
    assert len(d) <= 18 and all(marks[3] - 0x600 < i < marks[3] for i in d), [hex(i) for i in d[:5]]
    return 1
t('played xb dynasty -> gc -> xb exact before history (but the 9 kept values)', played_rt)
# a lineup slot outside 0..0x40 (an empty slot): its team's 4th unit didn't match and the teams' bounds shifted
def odd_slot():
    import struct as st
    with DY._in_lib():
        import containers as C
        import xb2gc as X
    m = C.parse_xbox(F['xb_dyn'])
    d = bytearray(m['payload'])
    starts = X._blocks(bytes(d), X.KEYX, X.SIG_X, 0x38cb)
    st.pack_into('<I', d, starts[40] + 3 * 48 + 12, 0xFFFFFFFF)
    out = C.build_xbox(F['xb_dyn'], dict(name=m['name'], typ=m['typ'], flags=m['flags'], payload=bytes(d)))
    DY.xbox_to_gc(out, F['gc_dyn'])
    return 1
t('xb dynasty with an empty lineup slot -> gc', odd_slot)
# League News: the news from a dynasty in its season, a fresh owner mode and one in the postseason
def news(k, **want):
    import shutil
    import tempfile
    import news05 as N
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "assets", "data", "database"))
    with open(os.path.join(root, "assets", "data", "database", "database.big"), "wb") as f:
        f.write(F["database"])
    if "feeng" in F and "logos" in F:
        os.makedirs(os.path.join(root, "assets", "data", "frontend"))
        with open(os.path.join(root, "assets", "data", "feeng.loc"), "wb") as f:
            f.write(F["feeng"])
        with open(os.path.join(root, "assets", "data", "frontend", "logos.big"), "wb") as f:
            f.write(F["logos"])
    db = N.Database(root)
    n = N.build(N.read_save(F[k]), db)
    page = N.render(n)
    if "feeng" in F and "logos" in F:
        assert db.injury(41) == "a torn rotator cuff" and db.injury(49) == "suspension", "injury names"
        assert db.logo(db.franchises[7]).startswith("data:image/png;base64,"), "no logo"
        assert "lg7" in page or not n["results"], "the logos aren't in the page"
    shutil.rmtree(root)
    assert len(n["divisions"]) == 6 and sum(len(d["rows"]) for d in n["divisions"]) == 30
    assert "<html" in page and "MVP Baseball" in page
    assert all(f"id=team-{i}>" in page for i in range(30)) and "href='#team-7'" in page, "team pages"
    assert "var PD={" in page and "class=pl href='#p-" in page, "player pages"
    if n["results"]:  # every game of the last day written up, the best one the Game of the Day
        last = n["days"][0][1]
        assert len(last) == len(n["results"]) and last[0]["gotd"] and " beat the " in last[0]["body"], "recaps"
        assert "Game of the day" in page
        for d, rs in n["days"]:  # the nine slots: innings 1-8 and the last one; tied going into the last in extras
            for r in rs:
                g = r["game"]
                assert sum(g["aline"]) <= g["ar"] and sum(g["hline"]) <= g["hr"], "line score"
                if g["innings"] > 9:
                    assert g["ar"] - g["aline"][8] == g["hr"] - g["hline"][8], "extra innings"
    for key, v in want.items():
        got = len(n[key]) if isinstance(n[key], list) else n[key]
        assert (got >= v) if isinstance(v, int) and not isinstance(v, bool) else got == v, (key, got, v)
    return 1
t('league news: a dynasty in its season', lambda: news('xb_dyn_played', headlines=6, results=1, upcoming=1,
                                                         games_played=17, postseason=False))
t('league news: a new owner mode', lambda: news('xb_own', postseason=False))
t('league news: the postseason', lambda: news('xb_dyn', postseason=True))


def news_leaders():
    """League leaders from the player history's season rows, checked against the game's own League Leaders screen
    (spy_jam's KCR dynasty, April 29, 2007: xb_dyn_kcr.dat, if it's in the samples)."""
    import shutil
    import tempfile
    import news05 as N
    kcr = F["xb_dyn_kcr"]  # (skipped without it)
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "assets", "data", "database"))
    with open(os.path.join(root, "assets", "data", "database", "database.big"), "wb") as f:
        f.write(F["database"])
    db = N.Database(root)
    save = N.read_save(kcr)
    L = N.season_leaders(save, db)
    shutil.rmtree(root)
    name = lambda k: save["names"].get(k) or db.name(k)
    got = {c: [(name(k), v) for k, _, v in L[0][c][:3]] for c in L[0]}
    assert got["AVG"] == [("Jason Varitek", ".406"), ("Juan Uribe", ".402"), ("Shannon Stewart", ".396")], got["AVG"]
    assert got["HR"][0] == ("Juan Uribe", "15") and got["SV"][:2] == [("Jeremy Affeldt", "11"), ("Joe Nathan", "9")]
    assert got["W"][0] == ("Jimmy Gobble", "5") and got["ERA"][2] == ("Joe Nathan", "0.77"), (got["W"], got["ERA"])
    assert [name(k) for k, _, _ in L[0]["AVG"]][6:] == ["Michael Young", "Ichiro", "Mike Sweeney", "Marco Scutaro"]
    return 1
t('league news: league leaders as the game shows them', news_leaders)
def news_standings():
    """The standings (two halves summed) agree with the schedule's results, team by team."""
    import collections
    import shutil
    import tempfile
    import news05 as N
    root = tempfile.mkdtemp()
    os.makedirs(os.path.join(root, "assets", "data", "database"))
    with open(os.path.join(root, "assets", "data", "database", "database.big"), "wb") as f:
        f.write(F["database"])
    db = N.Database(root)
    shutil.rmtree(root)
    s = N.read_save(F['xb_dyn_played'])
    won = collections.Counter()
    lost = collections.Counter()
    for g in s["games"]:
        if g["played"]:
            w, l = (g["away"], g["home"]) if g["ar"] > g["hr"] else (g["home"], g["away"])
            won[w] += 1
            lost[l] += 1
    for i, t in enumerate(db.franchises):
        assert s["records"][i] == (won[t], lost[t]), (db.short(t), s["records"][i], won[t], lost[t])
    return 1
t('league news: standings agree with the results', news_standings)
# wrong kinds: each must be refused with a message, never a crash
wrong = [
    ('owner into dynasty (gc)', lambda: DY.gc_to_xbox(F['gc_own'], F['xb_dyn'])),
    ('owner into dynasty (ps2)', lambda: PD.to_xbox(F['ps2_own'], F['xb_dyn'])),
    ('owner into dynasty (pc)', lambda: PCD.to_xbox(F['pc_own'], F['xb_dyn'])),
    ('owner into dynasty (xbox)', lambda: DY.xbox_to_xbox(F['xb_own'], F['xb_dyn'])),
    ('dynasty into owner (gc)', lambda: OW.gc_to_xbox(F['gc_dyn'], F['xb_own'])),
    ('dynasty into owner (ps2)', lambda: OW.ps2_to_xbox(F['ps2_dyn'], F['xb_own'])),
    ('dynasty into owner (pc)', lambda: OW.pc_to_xbox(F['pc_dyn'], F['xb_own'])),
    ('dynasty into owner (xbox)', lambda: OW.xbox_to_xbox(F['xb_dyn'], F['xb_own'])),
    ('dynasty built on an owner (gc export)', lambda: DY.xbox_to_gc(F['xb_dyn'], F['gc_own'])),
    ('owner built on a dynasty (gc export)', lambda: OW.xbox_to_gc(F['xb_own'], F['gc_dyn'])),
    ('owner built on a dynasty (ps2 export)', lambda: OW.xbox_to_ps2(F['xb_own'], F['ps2_dyn'])),
    ('owner built on a dynasty (pc export)', lambda: OW.xbox_to_pc(F['xb_own'], F['pc_dyn'])),
    ('dynasty built on an owner (ps2 export)', lambda: PD.to_ps2(F['xb_dyn'], F['ps2_own'])),
    ('dynasty built on an owner (pc export)', lambda: PCD.to_pc(F['xb_dyn'], F['pc_own'])),
    ('rosters into a dynasty', lambda: RO.to_xbox(RO.read(F['pc_roster']), F['xb_dyn'])),
    ('dynasty as rosters', lambda: RO.read(F['xb_dyn'])),
    ('gc rosters into a dynasty', lambda: GR.to_xbox(F['gc_roster'], F['xb_dyn'])),
    ('gc dynasty as gc rosters', lambda: GR.to_xbox(F['gc_dyn'], F['xb_roster'])),
    ('MVP 06 ps2 dynasty', lambda: PD.to_xbox(F['mvp06_ps2'], F['xb_dyn'])),
    ('MVP 06 xbox dynasty', lambda: DY.xbox_to_xbox(F['mvp06_xb'], F['xb_dyn'])),
    ('truncated gc dynasty', lambda: DY.gc_to_xbox(F['truncated_gc'], F['xb_dyn'])),
    ('random bytes as an xbox dynasty', lambda: DY.xbox_to_xbox(F['random'], F['xb_dyn'])),
    ('random bytes as rosters', lambda: RO.read(F['random'][:RO.XBOX_SAVE_SIZE])),
    ('random bytes as a ps2 card', lambda: PC.Card(F['random'][:8650752]).saves()),
    ('random bytes as a gamecube card', lambda: GCC.Card(F['random'][:0x1000000]).files()),
]
for n, fn in wrong: t(n, fn, expect_ok=False)
print("PASS")
for a, b in OK:
    print("  ", a, "-", b[:150])
if SKIP:
    print("SKIPPED")
    for a, b in SKIP:
        print("  ", a, "-", b)
print("PROBLEMS" if BAD else "No problems.")
for a, b in BAD:
    print("  ", a, "-", b[:220])
sys.exit(1 if BAD else 0)
