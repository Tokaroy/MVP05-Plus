"""MVP Baseball 2005 owner mode saves between the Xbox and the PC, PS2 and GameCube.

  read_xbox(data)               an Xbox owner mode data.dat, checked: its container's {name, typ, flags, payload}
  pc_to_xbox(pc, xbox)          a PC owner mode .sav as an Xbox data.dat, built on an Xbox owner mode save of yours
  ps2_to_xbox(ps2, xbox)        a PS2 owner mode save (.psu or .sav) the same way
  gc_to_xbox(gci, xbox)         a GameCube owner mode .gci the same way
  xbox_to_pc(xbox, pc)          an Xbox owner mode save as a PC .sav, built on a PC owner mode save of yours
  xbox_to_ps2(xbox, ps2)        ... as a PS2 save: (".psu" or ".sav", bytes), as the one given was
  xbox_to_gc(xbox, gci)         ... as a GameCube .gci: (file name, bytes)
  bank(payload) / set_bank(...) the owner's bank balance in an Xbox owner mode payload

An owner mode save is a dynasty save with two sections more (found from spy_jam's matched Yankees saves from all four
consoles, 2026-11-17). Its stream has 9 markers where a dynasty's has 7: markers 0 to 3 as a dynasty's, then

  4  the owner's finances (0x132C9 bytes on the Xbox: a long table, empty in a new owner mode, then the owner's
     settings, prices and money)
  5  the owner (0x140 bytes on the Xbox: his name, then six records of u16s, and the team's key)
  6  the user section, 7 the player history, 8 the stream end: a dynasty's 4, 5 and 6

and in the managers' list one slot fewer in use (the owner has no manager of his own; the dynasty readers take that).
So the dynasty part converts as a dynasty does, with sections 4 and 5 taken out (split), and those two are moved
across by the maps below and put back (join).

The two owner sections are the same on all four consoles but for padding, a 1-byte flag the PS2 and GameCube keep
in 4, and the GameCube's byte order. Where one console has bytes the other hasn't (padding), the save you build on
gives them. What's converted has been checked against the matched saves; a played owner mode has more in the long
table (empty in those), copied as it is between the Xbox, PC and PS2, which keep it the same way.
"""
import struct

import dynasty05 as DY
import pcdynasty05 as PCD
import ps2dynasty05 as PD
import rosters05 as RO

EXTRA = 0x13800  # an owner mode body's size over a dynasty's, on every console
XB_LEN = DY.XB_LEN + EXTRA       # 2,319,360: the Xbox payload, and the PC body
PS2_LEN = PD.SIZE + EXTRA        # 1,680,384: the PS2 body, and the GameCube's
TYP = "Owner Mode"

# The two owner sections as pieces in order: ("data", lengths, rule) is the same values on each console (rule: how
# the GameCube orders its bytes), ("pad", lengths) padding the console being written to gives itself, ("flag",
# lengths) a value kept in 1 byte on the Xbox and PC and in 4 on the PS2 and GameCube. Lengths are (Xbox, PC, PS2,
# GameCube). Rules: "w4" 4-byte values from the piece's start (a byte or a u16 followed by padding stays one),
# "w2" 2-byte values, "s5" section 5's head (marker and a u32, the owner's name in UTF-16, padding).
S4 = (("data", (0x12B90,) * 4, "w4"),
      ("pad", (0, 4, 4, 0)),
      ("data", (0x1321F - 0x12B90,) * 4, "w4"),
      ("pad", (0, 0, 15, 15)),
      ("data", (0x132C4 - 0x1321F,) * 4, "w4"),
      ("pad", (0, 0, 3, 3)),
      ("data", (4,) * 4, "w4"),          # a float (about $230 million in a new owner mode)
      ("flag", (1, 1, 4, 4)))
S5 = (("data", (0x2E,) * 4, "s5"),
      ("pad", (0, 0, 0, 2)),
      ("data", (0x13C - 0x2E,) * 4, "w2"),
      ("pad", (0, 0, 6, 4)),
      ("data", (4,) * 4, "w4"))          # the team's key
XB, PC, PS2, GC = range(4)
# true/false values kept in a byte (then padding) on the Xbox and PC and in 4 bytes on the PS2 and GameCube, by their
# offset in the Xbox's section 4: the last field of the 82 16-byte records from 0x12CD0
BOOLS4 = tuple(range(0x12CDC, 0x131F0, 16))
BANK_AT = 0x12B80  # in section 4 (the same on every console): the game's owner object +0x12B7C, the section being that object from its +0 on, 4 bytes in


class OwnerError(Exception):
    pass


def _check(ok, msg):
    if not ok:
        raise OwnerError(msg)


def _fill(a, b):
    return bytes(0x55 if k % 2 == 0 else 0xBB for k in range(a, b))


def markers(body, be=False):
    mk = PD.MARKER[::-1] if be else PD.MARKER
    out, i = [], body.find(mk)
    while i >= 0:
        out.append(i)
        i = body.find(mk, i + 1)
    return out


def is_owner_body(body, be=False):
    m = markers(body, be)
    return len(m) == 9 and struct.unpack_from(">I" if be else "<I", body, m[8] + 4)[0] == m[8] + 4


def split(body, size, be=False):
    """An owner mode body -> (a dynasty-shaped body of size bytes, section 4, section 5)."""
    m = markers(body, be)
    _check(len(m) == 9, "not an owner mode save this reads (its sections aren't there)")
    _check(struct.unpack_from(">I" if be else "<I", body, m[8] + 4)[0] == m[8] + 4,
           "not an owner mode save this reads (no stream end)")
    d = bytearray(body[:m[4]] + body[m[6]:m[8]])
    _end(d, be)
    _check(len(d) <= size, "the owner mode save is bigger than this reads")
    d += _fill(len(d), size)
    return bytes(d), bytes(body[m[4]:m[5]]), bytes(body[m[5]:m[6]])


def _end(d, be):
    pos = len(d)
    d += PD.MARKER[::-1] if be else PD.MARKER
    d += struct.pack(">I" if be else "<I", pos + 4)


def join(dyn, s4, s5, size, be=False, tpl=None):
    """A dynasty-shaped body and the two owner sections -> an owner mode body of size bytes (the unused end as tpl's,
    the save built on, when given: the GameCube's isn't the others' pattern)."""
    m = markers(dyn, be)
    _check(len(m) == 7, "the converted save's sections aren't there")
    d = bytearray(dyn[:m[4]] + s4 + s5 + dyn[m[4]:m[6]])
    _end(d, be)
    _check(len(d) <= size, "the converted owner mode doesn't fit the save")
    d += tpl[len(d):size] if tpl is not None and len(tpl) == size else _fill(len(d), size)
    _check(is_owner_body(bytes(d), be), "the converted owner mode didn't come out as one")
    return bytes(d)


def _pieces(sect, plan, plat):
    """A section cut into its pieces' bytes, by plan, as plat keeps it."""
    out, at = [], 0
    for kind, lens, *rule in plan:
        out.append((kind, sect[at:at + lens[plat]], rule[0] if rule else None))
        at += lens[plat]
    _check(at == len(sect), "the owner mode's sections aren't the size this reads")
    return out


PADB = (0x55, 0xBB)


def _w4(b):
    out = bytearray()
    for i in range(0, len(b) - 3, 4):
        w = b[i:i + 4]
        if all(c in PADB for c in w[1:]):      # a byte, then padding: as it is
            out += w
        elif all(c in PADB for c in w[2:]):    # a u16, then padding
            out += w[1::-1] + w[2:]
        else:
            out += w[::-1]
    return bytes(out + b[len(b) - len(b) % 4:])


def _w2(b):
    return bytes(b"".join(b[i:i + 2][::-1] for i in range(0, len(b) - 1, 2)) + b[len(b) - len(b) % 2:])


def _order(b, rule):
    """A data piece's bytes in the other byte order (the GameCube's, or the others' from it)."""
    if rule == "w4":
        return _w4(b)
    if rule == "w2":
        return _w2(b)
    if rule == "s5":
        return _w4(b[:8]) + _w2(b[8:0x28]) + b[0x28:]
    raise ValueError(rule)


def _at(plan, plat, xoff):
    """Where the Xbox section's offset xoff (in a data piece) is in plat's."""
    x = p = 0
    for kind, lens, *_ in plan:
        if kind == "data" and x <= xoff < x + lens[XB]:
            return p + xoff - x
        x += lens[XB]
        p += lens[plat]
    raise ValueError(xoff)


def move(sect, plan, src, tpl, dst, bools=()):
    """sect (as src keeps it) as dst keeps it, with dst's padding from tpl (the same section of a save of dst's)."""
    out = _move(sect, plan, src, tpl, dst)
    for x in bools:
        i, o = _at(plan, src, x), _at(plan, dst, x)
        v = sect[i + 3] if src == GC else sect[i]
        if dst in (XB, PC):
            out[o] = v  # (its padding as it came)
        else:
            out[o:o + 4] = bytes([v, 0, 0, 0]) if dst == PS2 else bytes([0, 0, 0, v])
    return bytes(out)


def _move(sect, plan, src, tpl, dst):
    a, t = _pieces(sect, plan, src), _pieces(tpl, plan, dst)
    out = bytearray()
    for (kind, mine, rule), (_, theirs, _) in zip(a, t):
        if kind == "pad":
            out += theirs
        elif kind == "flag":
            v = mine[0] if src in (XB, PC, PS2) else mine[3]
            out += bytes([v]) if dst in (XB, PC) else (bytes([v, 0, 0, 0]) if dst == PS2 else bytes([0, 0, 0, v]))
        elif (src == GC) != (dst == GC):
            out += _order(mine, rule)
        else:
            out += mine
    return out


# ---- the Xbox container

def read_xbox(data):
    with DY._in_lib():
        C = DY._containers()
        try:
            meta = C.parse_xbox(data)
        except Exception as e:
            raise OwnerError(f"not an Xbox MVP 2005 save this reads ({e})")
        meta["verified"] = bool(C.verify_xbox(data))
    _check(meta.get("typ") == TYP, f"that's {DY.a_kind(meta.get('typ'))} save, not an owner mode")
    _check(len(meta["payload"]) == XB_LEN and is_owner_body(meta["payload"]),
           "not an Xbox owner mode save this reads")
    return meta


def _build_xbox(template, name, flags, payload):
    with DY._in_lib():
        C = DY._containers()
        out = C.build_xbox(template, dict(name=name, typ=TYP, flags=flags, payload=payload))
        _check(C.verify_xbox(out), "the converted save failed its signature check")
    return out


def _xb_parts(payload):
    return split(payload, DY.XB_LEN)


# ---- the PC

def read_pc(data):
    data = bytes(data)
    _check(len(data) == PCD.HEAD + XB_LEN, "not a PC MVP 2005 owner mode save")
    typ = data[0x48:0x88].decode("utf-16-le", "replace").split("\0")[0]
    _check(typ == TYP, f"that's {DY.a_kind(typ)} save, not an owner mode")
    _check(struct.unpack_from("<I", data, 0)[0] == RO.crc(data[16:PCD.HEAD]) and
           struct.unpack_from("<I", data, 4)[0] == RO.crc(data[PCD.HEAD:]),
           "the PC save's checksums don't match: it's damaged or edited")
    body = data[PCD.HEAD:]
    _check(is_owner_body(body), "not a PC owner mode save this reads")
    return dict(name=data[0x28:0x48].decode("utf-16-le", "replace").split("\0")[0], body=body)


def pc_to_xbox(pc, xbox, name=None):
    src, t = read_pc(pc), read_xbox(xbox)
    d, s4, s5 = split(src["body"], PCD.SIZE)
    td, t4, t5 = _xb_parts(t["payload"])
    try:
        dyn = PCD.convert_body(d, td)
    except PCD.PcDynastyError as e:
        raise OwnerError(str(e))
    body = join(dyn, move(s4, S4, PC, t4, XB, BOOLS4), move(s5, S5, PC, t5, XB), XB_LEN)
    return _build_xbox(xbox, name or t["name"], t["flags"], body)


def xbox_to_pc(xbox, pc):
    t, base = read_xbox(xbox), read_pc(pc)
    d, s4, s5 = _xb_parts(t["payload"])
    td, t4, t5 = split(base["body"], PCD.SIZE)
    try:
        dyn = PCD.convert_body_to_pc(d, td)
    except PCD.PcDynastyError as e:
        raise OwnerError(str(e))
    body = join(dyn, move(s4, S4, XB, t4, PC, BOOLS4), move(s5, S5, XB, t5, PC), XB_LEN)
    out = bytearray(bytes(pc)[:PCD.HEAD] + body)
    struct.pack_into("<I", out, 4, RO.crc(body))
    read_pc(bytes(out))
    return bytes(out)


def xbox_to_xbox(data, xbox):
    """Another Xbox's owner mode, in your own save's container (its name and signature)."""
    src, t = read_xbox(data), read_xbox(xbox)
    return _build_xbox(xbox, t["name"], t["flags"], bytes(src["payload"]))


# ---- the PS2

def _ps2_sav(data):
    """(start of the .sav in data, its kind): a .psu holding an owner mode, or the .sav itself."""
    if len(data) == PD.HEAD + PS2_LEN:
        return 0, ".sav"
    try:
        ent = RO.psu_entries(data)
    except RO.RosterError:
        raise OwnerError("not a PS2 MVP 2005 save (.psu, or a .sav from one)")
    sav = [s for _, s, z in ent if z == PD.HEAD + PS2_LEN]
    _check(len(sav) == 1, "that PS2 save isn't an owner mode")
    return sav[0], ".psu"


def is_ps2(data):
    """Whether data is a PS2 owner mode-sized save (a .sav, or a .psu holding one): then read_ps2() it."""
    try:
        _ps2_sav(bytes(data))
        return True
    except OwnerError:
        return False


def read_ps2(data):
    data = bytes(data)
    start, _ = _ps2_sav(data)
    b = data[start:start + PD.HEAD + PS2_LEN]
    typ = b[0x48:0x88].decode("utf-16-le", "replace").split("\0")[0]
    _check(typ == TYP, f"that's {DY.a_kind(typ)} save, not an owner mode")
    _check(struct.unpack_from("<I", b, 0)[0] == RO.crc(b[16:PD.HEAD]) and
           struct.unpack_from("<I", b, 4)[0] == RO.crc(b[PD.HEAD:]),
           "the PS2 save's checksums don't match: it's damaged or edited")
    body = b[PD.HEAD:]
    _check(is_owner_body(body), "not a PS2 owner mode save this reads")
    return dict(name=b[0x28:0x48].decode("utf-16-le", "replace").split("\0")[0], body=body)


def ps2_to_xbox(ps2, xbox, name=None):
    src, t = read_ps2(ps2), read_xbox(xbox)
    d, s4, s5 = split(src["body"], PD.SIZE)
    td, t4, t5 = _xb_parts(t["payload"])
    try:
        dyn = PD.convert_body(d, td)
    except PD.Ps2DynastyError as e:
        raise OwnerError(str(e))
    body = join(dyn, move(s4, S4, PS2, t4, XB, BOOLS4), move(s5, S5, PS2, t5, XB), XB_LEN)
    return _build_xbox(xbox, name or t["name"], t["flags"], body)


def xbox_to_ps2(xbox, ps2):
    t = read_xbox(xbox)
    data = bytes(ps2)
    read_ps2(data)
    start, kind = _ps2_sav(data)
    sav = bytearray(data[start:start + PD.HEAD + PS2_LEN])
    d, s4, s5 = _xb_parts(t["payload"])
    td, t4, t5 = split(bytes(sav[PD.HEAD:]), PD.SIZE)
    try:
        dyn = PD.convert_body_to_ps2(d, td)
    except PD.Ps2DynastyError as e:
        raise OwnerError(str(e))
    sav[PD.HEAD:] = join(dyn, move(s4, S4, XB, t4, PS2, BOOLS4), move(s5, S5, XB, t5, PS2), PS2_LEN)
    struct.pack_into("<I", sav, 4, RO.crc(bytes(sav[PD.HEAD:])))
    out = data[:start] + bytes(sav) + data[start + PD.HEAD + PS2_LEN:]
    read_ps2(out)
    return kind, out


# ---- the GameCube (spy_jam's converter for the dynasty part)

def read_gc(data):
    data = bytes(data)
    _check(data[:4] == b"GV4E", "not an MVP 2005 GameCube save (.gci from Dolphin)")
    with DY._in_lib():
        C, _, _, GCS = DY._libs()
        try:
            meta = C.parse_gc(data)
            good = GCS.check(bytearray(data))
        except Exception as e:
            raise OwnerError(f"not a GameCube save this reads ({e})")
    _check(good, "the GameCube save's checksums don't match: it's damaged or edited")
    _check(meta.get("typ") == TYP, f"that's {DY.a_kind(meta.get('typ'))} save, not an owner mode")
    body = meta["payload"]
    _check(len(body) == PS2_LEN and is_owner_body(body, True), "not a GameCube owner mode save this reads")
    return dict(name=meta["name"], body=body, flags=meta["flags"])


def gc_to_xbox(gci, xbox, name=None):
    src, t = read_gc(gci), read_xbox(xbox)
    d, s4, s5 = split(src["body"], DY.GC_LEN, True)
    td, t4, t5 = _xb_parts(t["payload"])
    with DY._in_lib():
        _, G, _, _ = DY._libs()
        try:
            dyn, _, _ = G.convert(d, td, sched=True, hist=True)
        except Exception as e:
            raise OwnerError(DY.conversion_error(e, "this owner mode"))
    body = join(dyn, move(s4, S4, GC, t4, XB, BOOLS4), move(s5, S5, GC, t5, XB), XB_LEN)
    return _build_xbox(xbox, name or t["name"], t["flags"], body)


def xbox_to_gc(xbox, gci):
    """(file name, bytes): the GameCube save you built on, its name kept, with the Xbox owner mode in it."""
    t, base = read_xbox(xbox), read_gc(gci)
    d, s4, s5 = _xb_parts(t["payload"])
    td, t4, t5 = split(base["body"], DY.GC_LEN, True)
    with DY._in_lib():
        C, _, R, GCS = DY._libs()
        try:
            dyn = R.convert(d, td)
        except Exception as e:
            raise OwnerError(DY.conversion_error(e, "this owner mode"))
        body = join(dyn, move(s4, S4, XB, t4, GC, BOOLS4), move(s5, S5, XB, t5, GC), PS2_LEN, True, base["body"])
        out = bytearray(gci)
        out[C.GC_PAYLOAD:C.GC_PAYLOAD + len(body)] = body
        struct.pack_into(">I", out, C.GC_HDR + 4, C.ea_crc(body))  # the payload's checksum (the header's stays)
        _check(GCS.check(bytearray(out)), "the converted .gci failed its checksum check")
    fname = bytes(out[0x08:0x28]).split(b"\0")[0].decode("ascii", "replace")
    return f"69-GV4E-{fname}.gci", bytes(out)


# ---- the owner's money

def _bank_at(payload):
    m = markers(payload)
    _check(len(m) == 9, "not an owner mode save this reads")
    return m[4] + BANK_AT


def bank(payload):
    """The owner's bank balance in dollars, in an Xbox owner mode payload."""
    return struct.unpack_from("<f", payload, _bank_at(payload))[0]


def set_bank(payload, dollars):
    p = bytearray(payload)
    struct.pack_into("<f", p, _bank_at(p), float(dollars))
    return bytes(p)
