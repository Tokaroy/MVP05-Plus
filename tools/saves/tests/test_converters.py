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
"""
import contextlib
import io
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import dynasty05 as DY
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
KNOWN = (RO.RosterError, GR.GcRosterError, DY.DynastyError, PD.Ps2DynastyError, PCD.PcDynastyError, OW.OwnerError,
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
