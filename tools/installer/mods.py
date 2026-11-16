"""Mods: replacement game files, each mod a folder under "mods" laid out like the game's assets folder, turned on
and put in order in mods/mods.txt (the game reads it at start: src/common/mods.cpp). The first mod in the list with
a file wins. Nothing here changes the game's own files.

Importing finds where each of a mod's files goes:
  - by its path, when the zip or folder has the game's folders in it (data/stadium/fenwday.big), wherever the game's
    part of the path starts (MyMod/data/... works too), or the end of a game path (stadium/fenwday.big);
  - else by its name, when the game has exactly one file of that name;
  - a name the game has in more than one place is for the person to pick ("pick");
  - a name the game doesn't have is left out ("unknown"), unless its path starts with one of the game's own top
    folders: then it's a new file at that path ("new").
"""
import os
import shutil
import zipfile

DIR = "mods"
LIST = "mods.txt"
JUNK = {".ds_store", "thumbs.db", "desktop.ini"}
NOT_MODDABLE = {"default.xbe"}  # MVP05-Plus runs its own copy of the game's code
HEADER = ("# MVP05-Plus mods, the first in the list winning when two have the same file. Each line is \"on\" or "
          "\"off\"\n# and then the mod's folder in this folder. The Launcher's Mods tab writes this file.\n")


def mods_dir(root):
    return os.path.join(root, DIR)


def _valid(name):
    return bool(name) and name not in (".", "..") and not any(c in name for c in '/\\:*?"<>|') and \
        name == name.strip() and not name.endswith(".")


# ---- the list -------------------------------------------------------------------------------------------------

def read_list(root):
    """[(name, on)] in order: mods.txt's, then any mod folders it doesn't name (off), by name."""
    d = mods_dir(root)
    out, seen = [], set()
    try:
        with open(os.path.join(d, LIST), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                state, _, name = line.partition(" ")
                name = name.strip()
                if state not in ("on", "off") or not _valid(name) or name.lower() in seen:
                    continue
                if os.path.isdir(os.path.join(d, name)):
                    out.append((name, state == "on"))
                    seen.add(name.lower())
    except OSError:
        pass
    try:
        extra = sorted(n for n in os.listdir(d) if os.path.isdir(os.path.join(d, n)) and n.lower() not in seen
                       and _valid(n))
    except OSError:
        extra = []
    return out + [(n, False) for n in extra]


def write_list(root, items):
    d = mods_dir(root)
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, LIST + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(HEADER)
        for name, on in items:
            f.write(f"{'on' if on else 'off'} {name}\n")
    os.replace(tmp, os.path.join(d, LIST))


def mod_files(root, name):
    """The mod's files as game paths (with "/"), as they're stored."""
    base = os.path.join(mods_dir(root), name)
    out = []
    for dp, _, fns in os.walk(base):
        for fn in fns:
            out.append(os.path.relpath(os.path.join(dp, fn), base).replace(os.sep, "/"))
    return sorted(out)


def clashes(root, items):
    """{name: [(other, files in both, this one wins)]} among the mods that are on."""
    owners = {}
    on = [n for n, o in items if o]
    for n in on:
        for p in mod_files(root, n):
            owners.setdefault(p.lower(), []).append(n)
    out = {n: {} for n in on}
    for names in owners.values():
        for a in names:
            for b in names:
                if a != b:
                    out[a][b] = out[a].get(b, 0) + 1
    order = {n: i for i, n in enumerate(on)}
    return {a: [(b, c, order[a] < order[b]) for b, c in sorted(o.items(), key=lambda x: order[x[0]])]
            for a, o in out.items() if o}


def unique_name(root, base):
    base = "".join(c for c in base if c not in '/\\:*?"<>|').strip().rstrip(".") or "Mod"
    taken = {n.lower() for n, _ in read_list(root)}
    name, i = base, 2
    while name.lower() in taken or os.path.exists(os.path.join(mods_dir(root), name)):
        name, i = f"{base} ({i})", i + 1
    return name


def name_problem(root, name, current=None):
    """Why name can't be a mod's name (None if it can): current is the mod being renamed."""
    name = name.strip()
    if not name:
        return "Give the mod a name."
    if not _valid(name) or name.lower() == LIST:
        return 'A name can\'t have / \\ : * ? " < > | in it, or end with a dot.'
    if len(name) > 80:
        return "That name is too long (80 letters at most)."
    if (current is None or name.lower() != current.lower()) and (
            any(n.lower() == name.lower() for n, _ in read_list(root)) or
            os.path.exists(os.path.join(mods_dir(root), name))):
        return f"There's already a mod called {name}."
    return None


def rename(root, old, new):
    """Renames a mod, keeping its place and whether it's on. Returns why it couldn't, or None."""
    new = new.strip()
    problem = name_problem(root, new, current=old)
    if problem or new == old:
        return problem
    items = read_list(root)
    d = mods_dir(root)
    try:
        if new.lower() == old.lower():  # only the case changes: by way of another name
            tmp = os.path.join(d, old + ".renaming")
            os.rename(os.path.join(d, old), tmp)
            os.rename(tmp, os.path.join(d, new))
        else:
            os.rename(os.path.join(d, old), os.path.join(d, new))
    except OSError as e:
        return f"Couldn't rename it: {e.strerror or e}"
    write_list(root, [(new if n == old else n, o) for n, o in items])
    return None


def suggested_name(paths):
    """The name a mod gets at first: its folder's or zip's, else the files' folder's."""
    if len(paths) == 1:
        p = os.path.normpath(paths[0])
        return os.path.basename(p) if os.path.isdir(p) else os.path.splitext(os.path.basename(p))[0]
    return os.path.basename(os.path.dirname(os.path.normpath(paths[0]))) or "New mod"


def remove(root, name):
    shutil.rmtree(os.path.join(mods_dir(root), name), ignore_errors=True)
    write_list(root, [(n, o) for n, o in read_list(root) if n != name])


# ---- matching -------------------------------------------------------------------------------------------------

class Assets:
    """The game's files under assets: by path and by name (both lower case)."""

    def __init__(self, root):
        base = os.path.join(root, "assets")
        self.by_path, self.by_name, self.tops = {}, {}, set()
        for dp, dns, fns in os.walk(base):
            for fn in fns:
                rel = os.path.relpath(os.path.join(dp, fn), base).replace(os.sep, "/")
                if rel.lower() in NOT_MODDABLE or "/" not in rel and fn.lower().endswith(".txt"):
                    continue
                self.by_path[rel.lower()] = rel
                self.by_name.setdefault(fn.lower(), []).append(rel)
            if dp == base:
                self.tops = {d.lower() for d in dns}
        for v in self.by_name.values():
            v.sort()

    def __bool__(self):
        return bool(self.by_path)

    def match(self, path):
        """(status, [game paths]) for a file at path in a mod (with "/"): status is "path", "name", "pick",
        "new" or "unknown"; "pick" lists the places to choose from."""
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        for k in range(len(parts) - 1):  # the game's part of the path, wherever it starts
            hit = self.by_path.get("/".join(parts[k:]).lower())
            if hit:
                return "path", [hit]
        if parts and parts[-1].lower() in NOT_MODDABLE:
            return "unknown", []
        for k in range(len(parts) - 1):  # the end of a game path (a mod made from inside data, say)
            end = "/" + "/".join(parts[k:]).lower()
            hits = sorted(v for key, v in self.by_path.items() if key.endswith(end))
            if hits:
                return ("path" if len(hits) == 1 else "pick"), hits
        hits = self.by_name.get(parts[-1].lower(), []) if parts else []
        if len(hits) == 1:
            return "name", hits
        if hits:
            return "pick", hits
        for k in range(len(parts) - 1):  # a new file in one of the game's folders
            if parts[k].lower() in self.tops:
                return "new", ["/".join(parts[k:])]
        return "unknown", []


def _junk(path):
    parts = path.replace("\\", "/").split("/")
    return any(p.lower() == "__macosx" or p.startswith("._") for p in parts) or parts[-1].lower() in JUNK


class Source:
    """What's being imported: files, a folder or a zip, as [(path in the mod, opener)]."""

    def __init__(self, name, entries, zf=None):
        self.name, self.entries, self.zf = name, entries, zf

    def close(self):
        if self.zf:
            self.zf.close()


def from_files(paths):
    stem = os.path.splitext(os.path.basename(paths[0]))[0] if len(paths) == 1 else "Mod"
    return Source(stem, [(os.path.basename(p), lambda p=p: open(p, "rb")) for p in paths])


def from_folder(folder):
    entries = []
    for dp, _, fns in os.walk(folder):
        for fn in fns:
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            if not _junk(rel):
                entries.append((rel, lambda p=full: open(p, "rb")))
    return Source(os.path.basename(os.path.normpath(folder)), sorted(entries))


def from_zip(path):
    zf = zipfile.ZipFile(path)
    entries = [(i.filename, lambda i=i: zf.open(i)) for i in zf.infolist()
               if not i.is_dir() and not _junk(i.filename)]
    return Source(os.path.splitext(os.path.basename(path))[0], sorted(entries), zf)


def plan(assets, source):
    """[(path in the mod, status, [game paths])] for each of source's files."""
    return [(p, *assets.match(p)) for p, _ in source.entries]


def install(root, source, planned, picks, name=None):
    """The planned files copied into a new mod (picks: {path in the mod: [game paths]} for the "pick" ones; others
    of them are left out), added to the end of the list, on. Returns (name, files copied); none copied, no mod."""
    name = unique_name(root, name or source.name)
    base = os.path.join(mods_dir(root), name)
    opener = dict(source.entries)
    done = set()
    try:
        for path, status, targets in planned:
            if status == "pick":
                targets = picks.get(path, [])
            elif status == "unknown":
                continue
            for t in targets:
                if t.lower() in done:  # two of the mod's files for one place: the first
                    continue
                dest = os.path.join(base, *t.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with opener[path]() as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
                done.add(t.lower())
    except Exception:
        shutil.rmtree(base, ignore_errors=True)
        raise
    if not done:
        shutil.rmtree(base, ignore_errors=True)
        return None, 0
    write_list(root, [(n, o or n == name) for n, o in read_list(root)])  # new folders come last
    return name, len(done)
