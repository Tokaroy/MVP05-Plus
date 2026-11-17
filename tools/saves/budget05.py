"""The payroll budget of a dynasty's own team, read and changed in its Xbox save (data.dat).

  read(folder)                 {name, team, budget, bank}: the save's name, its team, its budget in dollars, and in
                               an owner mode the owner's bank balance in dollars (None in a dynasty)
  write(root, folder, dollars, bank=None)  the budget (and an owner mode's bank balance) set: backed up first, the
                               game closed

Where it is (spy_jam's converter's notes, mvp05/FORMAT_NOTES.md 3.7, checked on Xbox saves): the 34 org records,
84 bytes each from payload offset 0x477, start with the org's key, and their halfword s21 (at +58) is the budget,
the game's org_budget field. The game turns it into dollars as steps * $100,000 + $100,000 (0x1AC6E0, with
[db+0x204] and [db+0x1F4]). The user's team is the key 8 bytes into the user section (marker 4 in a dynasty,
6 in an owner mode, which has two sections more: owner05.py, with the bank balance).
"""
import os
import struct

import owner05 as OW
import ps2dynasty05 as PD
import saves05 as S
import team_changer as TC

ORGS_AT, ORG_SIZE, ORGS, BUDGET_AT = 0x477, 84, 34, 58
STEP = BASE = 100000
MOST = 0x7FFF  # steps: the game's own budgets stay well under, and the Tools menu in the game caps here too


class BudgetError(Exception):
    pass


def _team(payload):
    """(the user's org key, the index of its org record) in a dynasty or owner mode payload."""
    m = OW.markers(payload)
    if len(m) not in (7, 9):
        raise BudgetError("not a dynasty or owner mode this reads (its sections aren't there)")
    key = struct.unpack_from("<I", payload, m[len(m) - 3] + 8)[0]
    for i in range(ORGS):
        if struct.unpack_from("<I", payload, ORGS_AT + ORG_SIZE * i)[0] == key:
            return key, i
    raise BudgetError("the save's team isn't among its organizations: not a save this reads")


def _load(folder):
    C, _ = S._lib()
    with open(os.path.join(folder, "data.dat"), "rb") as f:
        xf = f.read()
    m = C.parse_xbox(xf)
    if m.get("typ") not in ("Dynasty", OW.TYP):
        raise BudgetError(f"that's a{'n' if str(m.get('typ'))[:1] in 'AEIOU' else ''} {m.get('typ')} save: the "
                          "payroll budget is in dynasty and owner mode saves")
    return C, xf, m


def team_name(key):
    return TC.ORGS[TC.IDS.index(key)] if key in TC.IDS else f"team {key:08X}"


def read(folder):
    _, _, m = _load(folder)
    p = m["payload"]
    key, i = _team(p)
    steps = struct.unpack_from("<H", p, ORGS_AT + ORG_SIZE * i + BUDGET_AT)[0]
    return dict(name=m["name"], team=team_name(key), budget=steps * STEP + BASE,
                bank=OW.bank(p) if m["typ"] == OW.TYP else None)


def steps_for(dollars):
    return max(0, min(MOST, int(round((dollars - BASE) / STEP))))


def write(root, folder, dollars, say=print, bank=None):
    S._check_not_running()
    C, xf, m = _load(folder)
    if not C.verify_xbox(xf):
        raise BudgetError("that save's signature doesn't check out; it's left as it is")
    p = bytearray(m["payload"])
    key, i = _team(p)
    steps = steps_for(dollars)
    struct.pack_into("<H", p, ORGS_AT + ORG_SIZE * i + BUDGET_AT, steps)
    if bank is not None and m["typ"] == OW.TYP:
        p = bytearray(OW.set_bank(p, bank))
    out = C.build_xbox(xf, dict(name=m["name"], typ=m["typ"], flags=m["flags"], payload=bytes(p)))
    if not C.verify_xbox(out):
        raise BudgetError("the changed save didn't pass its signature check; nothing written")
    b = S.backup_folder(root, folder, "payroll budget")
    say(f"Backed up the save to {os.path.relpath(b, root)}")
    dat = os.path.join(folder, "data.dat")
    with open(dat + ".part", "wb") as f:
        f.write(out)
    os.replace(dat + ".part", dat)
    return steps * STEP + BASE
