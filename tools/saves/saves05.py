"""MVP Baseball 2005 dynasty saves (the game's own, in hdd beside MVP05.exe): listed, and short seasons' standings
projected to 162 games in the save file, for the Launcher's Tools tab. The save converters come back here later.

  hdd/E/UDATA/45410056/<12-hex folder>/   data.dat, SaveMeta.xbx (UTF-16LE with BOM: "Name=<name> (<type>)"),
                                          saveimage.xbx
"""
import datetime
import struct
import os
import shutil
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "mvp05", "lib")  # (in the Tools exe the modules and their .json tables are bundled)
TITLE = "45410056"
GC_PAYLOAD_OFF, GC_PAYLOAD_LEN = 0x2138, 0x186C00
XB_PAYLOAD_OFF, XB_PAYLOAD_LEN = 0x108, 0x222C00
_lock = threading.Lock()


class SaveError(Exception):
    pass


def _lib():
    if LIB not in sys.path:
        sys.path.insert(0, LIB)
    import containers
    import gc_checksums
    return containers, gc_checksums


def udata(root):
    return os.path.join(root, "hdd", "E", "UDATA", TITLE)


def game_running():
    if os.name != "nt":
        return False
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq MVP05.exe", "/NH"], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return "mvp05.exe" in r.stdout.lower()
    except OSError:
        return False


def savemeta_name(folder):
    try:
        with open(os.path.join(folder, "SaveMeta.xbx"), "rb") as f:
            b = f.read()
        t = b.decode("utf-16-le" if b[:2] == b"\xff\xfe" else "latin-1").lstrip("﻿")
        for line in t.splitlines():
            if line.startswith("Name="):
                return line[5:].strip()
    except OSError:
        pass
    return ""


def list_saves(root):
    """[{folder, id, name, type, when}] newest first; type is the game's ("Dynasty", "Season", ...)."""
    C, _ = _lib()
    out = []
    base = udata(root)
    if not os.path.isdir(base):
        return out
    for d in os.listdir(base):
        folder = os.path.join(base, d)
        dat = os.path.join(folder, "data.dat")
        if not os.path.isfile(dat):
            continue
        name, typ = savemeta_name(folder), ""
        try:
            with open(dat, "rb") as f:
                m = C.parse_xbox(f.read(XB_PAYLOAD_OFF))
            name, typ = m["name"] or name, m["typ"]
        except Exception:
            pass
        out.append(dict(folder=folder, id=d, name=name or d, type=typ or "?",
                        when=datetime.datetime.fromtimestamp(os.path.getmtime(dat))))
    return sorted(out, key=lambda s: s["when"], reverse=True)


def backup_folder(root, folder, why):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H.%M.%S")
    dest = os.path.join(root, "save backups", f"{stamp} before {why}", os.path.basename(folder))
    n = 2
    while os.path.exists(dest):  # a second backup of the same save in the same second
        dest = os.path.join(root, "save backups", f"{stamp} before {why} ({n})", os.path.basename(folder))
        n += 1
    shutil.copytree(folder, dest)
    return dest


# A save's folder is named from its name and type as the game shows them, "NAME (Type)": the Xbox library's hash
# (0x3F36B5 in default.xbe): each UTF-16 character in turn, h = (h * 65536 + c) mod (2^48 - 59), written as 12
# upper-case hex digits. Checked on saves the game made (KCRTEST (Dynasty) -> 8D58821E7335). A save put in any other
# folder loads, but the game's next save of that name goes to the folder of the hash: a second copy.
_FOLDER_MOD = (1 << 48) - 59
NAME_MOST = 10  # letters: the GameCube's limit, and room to spare in the Xbox header (16)


def folder_id(name, typ):
    h = 0
    for c in f"{name} ({typ})":
        h = (h * 65536 + ord(c)) % _FOLDER_MOD
    return f"{h:012X}"


def check_name(name):
    """A new save's name, or SaveError: 1 to 10 letters, digits and spaces."""
    name = " ".join(name.split())
    if not name:
        raise SaveError("the save needs a name")
    if len(name) > NAME_MOST:
        raise SaveError(f"a save's name can have {NAME_MOST} letters at most")
    if not all(c.isascii() and (c.isalnum() or c == " ") for c in name):
        raise SaveError("a save's name can have only letters, digits and spaces")
    return name


def renamed(data, name):
    """An Xbox save (rosters, dynasty or owner mode: the same header) under a new name, signed again."""
    import hashlib
    import hmac
    C, _ = _lib()
    b = bytearray(data)
    typ = b[0x88:0xA8].decode("utf-16-le").split("\0")[0]
    b[0x68:0x88] = name.encode("utf-16-le").ljust(0x20, b"\0")[:0x20]
    b[0xA8:0xE8] = f"{name} ({typ})".encode("utf-16-le").ljust(0x40, b"\0")[:0x40]
    key = bytes(16)
    b[0:20] = hmac.new(key, bytes(b[0x50:0x108]), hashlib.sha1).digest()
    b[20:40] = hmac.new(key, bytes(b[0x108:]), hashlib.sha1).digest()
    return bytes(b), typ


def new_save(root, base_folder, data, name):
    """data (an Xbox save) as a new save called name, beside base_folder (one of yours, whose picture it takes):
    its folder, or SaveError if there's a save of that name already."""
    C, _ = _lib()
    name = check_name(name)
    out, typ = renamed(data, name)
    folder = os.path.join(udata(root), folder_id(name, typ))
    if os.path.exists(folder):
        raise SaveError(f"there's a save called \"{name}\" already: pick another name")
    os.makedirs(folder + ".part")
    try:
        img = os.path.join(base_folder, "saveimage.xbx")
        if os.path.isfile(img):
            shutil.copy2(img, os.path.join(folder + ".part", "saveimage.xbx"))
        with open(os.path.join(folder + ".part", "SaveMeta.xbx"), "wb") as f:
            f.write(C.xbox_savemeta(name, typ))
        with open(os.path.join(folder + ".part", "data.dat"), "wb") as f:
            f.write(out)
        os.replace(folder + ".part", folder)
    except OSError:
        shutil.rmtree(folder + ".part", ignore_errors=True)
        raise
    return folder


def copy_save(root, folder, name):
    """A copy of one of your saves under a new name (a dynasty to branch off, say): its folder."""
    _check_not_running()
    with open(os.path.join(folder, "data.dat"), "rb") as f:
        data = f.read()
    return new_save(root, folder, data, name)


def rename_save(root, folder, name):
    """One of your saves under a new name, in the folder the game uses for it (backed up first): its folder."""
    _check_not_running()
    with open(os.path.join(folder, "data.dat"), "rb") as f:
        data = f.read()
    new = new_save(root, folder, data, name)
    backup_folder(root, folder, "renaming")
    shutil.rmtree(folder)
    return new


def _check_not_running():
    if game_running():
        raise SaveError("close MVP05.exe first: the game keeps its saves open while it runs")


MLB_TEAMS = ["ANA", "OAK", "SEA", "TEX", "CWS", "CLE", "DET", "KC", "MIN", "BAL", "BOS", "NYY", "TB", "TOR", "ARI",
             "COL", "LAD", "SD", "SF", "CHC", "CIN", "HOU", "MIL", "PIT", "STL", "ATL", "FLA", "WAS", "NYM", "PHI"]
POST_ROSTER_KEY = b"\x6a\xbc\x3d\x69"
MARKER = b"\x0d\xf0\xef\xbe"
MLB_SCHEDULE_CAP = 2442


def project(w, l, games=162):
    """The memory patcher's projection: the same winning percentage over a full season."""
    gp = w + l
    if gp == 0:
        return games // 2, games - games // 2
    pw = max(0, min(games, round(w / gp * games)))
    return pw, games - pw


def _standings_at(payload):
    q = payload.find(POST_ROSTER_KEY, 0x12000)
    if q < 0:
        raise SaveError("couldn't find the standings in this save (no post-roster table)")
    t = q + 4
    recs = [(payload[t + 4 * i], payload[t + 4 * i + 1]) for i in range(30)]
    if any(payload[t + 4 * i + 2] or payload[t + 4 * i + 3] for i in range(30)):
        raise SaveError("the standings table isn't laid out as expected ([W][L][0][0] per team); nothing written")
    return t, recs


def _schedule_progress(payload):
    """(played, scheduled) games in the MLB schedule."""
    marks = []
    i = payload.find(MARKER)
    while i >= 0 and len(marks) < 7:
        marks.append(i)
        i = payload.find(MARKER, i + 4)
    if len(marks) < 4:
        return None
    p = marks[2] + 4
    n = struct.unpack_from("<I", payload, p)[0]
    if n > MLB_SCHEDULE_CAP:
        return None
    played = sum(1 for k in range(n) if (struct.unpack_from("<H", payload, p + 4 + 28 * k + 2)[0] >> 11) & 0x1F)
    return played, n


def read_standings(folder):
    """{name, records [(team, W, L)], played, scheduled, season} of a dynasty save; season: games per team, from the
    schedule's size (every game has two teams), when the schedule was found."""
    C, _ = _lib()
    with open(os.path.join(folder, "data.dat"), "rb") as f:
        xf = f.read()
    m = C.parse_xbox(xf)
    if m.get("typ") not in ("Dynasty", "Owner Mode"):
        raise SaveError(f"that's a {m.get('typ')} save: standings are in dynasty and owner mode saves")
    _, recs = _standings_at(m["payload"])
    prog = _schedule_progress(m["payload"]) or (None, None)
    season = round(prog[1] * 2 / len(MLB_TEAMS)) if prog[1] else None
    return dict(name=m["name"], records=[(t, w, l) for t, (w, l) in zip(MLB_TEAMS, recs)],
                played=prog[0], scheduled=prog[1], season=season)


def patch_standings(root, folder, games=162, say=print):
    """Every MLB team's record projected to `games` games in the save (backed up first)."""
    _check_not_running()
    C, _ = _lib()
    dat = os.path.join(folder, "data.dat")
    with open(dat, "rb") as f:
        xf = f.read()
    m = C.parse_xbox(xf)
    if m.get("typ") not in ("Dynasty", "Owner Mode"):
        raise SaveError(f"that's a {m.get('typ')} save: pick a dynasty or owner mode save")
    if not C.verify_xbox(xf):
        raise SaveError("that save's signature doesn't check out; it's left as it is")
    payload = bytearray(m["payload"])
    t, recs = _standings_at(payload)
    if not any(w + l for w, l in recs):
        raise SaveError("no MLB team has played a game in this save yet")
    if all(w + l == games for w, l in recs):
        raise SaveError(f"every team already has {games} games: this save's standings are already projected")
    for i, (w, l) in enumerate(recs):
        pw, pl = project(w, l, games)
        payload[t + 4 * i], payload[t + 4 * i + 1] = pw, pl
    out = C.build_xbox(xf, dict(name=m["name"], typ=m["typ"], flags=m["flags"], payload=bytes(payload)))
    if not C.verify_xbox(out):
        raise SaveError("the patched save didn't pass its signature check; nothing written")
    b = backup_folder(root, folder, "standings patch")
    say(f"Backed up the save to {os.path.relpath(b, root)}")
    with open(dat + ".part", "wb") as f:
        f.write(out)
    os.replace(dat + ".part", dat)
    say(f"Done: {m['name']}'s standings are projected to {games} games. Load it in the game and advance to the "
        f"playoffs, then save.")
