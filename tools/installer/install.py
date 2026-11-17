"""MVP05-Plus Launcher. Install: puts your own discs' game files where the game looks for them, in the folder the installer is in.

  Xbox disc (required)        every file, into assets/ (as Mad Dog's original asks for by hand)
  GameCube disc (optional)    only the 11 files the button art needs, read into a temporary folder, made into
                              gc_icons/ (tools/gc_layout/make_icons.py), then deleted
  PS2 disc (optional)         the same for ps2_icons/ (tools/ps2_layout/make_ps2_icons.py)

Nothing is written anywhere else: no registry, no shortcuts, no Program Files. Deleting the folder removes it all.

Save backups: the game's own backups of your saves (save backups/), listed and restored.

  MVP05-Plus-Launcher.exe                       the window
  MVP05-Plus-Launcher.exe --xbox X [--gamecube G] [--ps2 P] [--dir D]   installing without it
"""
import argparse
import datetime
import json
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
for sub in ("gc_layout", "ps2_layout", "saves", os.path.join("saves", "mvp05", "lib")):  # bundled beside this when frozen
    for base in (os.path.join(HERE, "..", sub), os.path.join(getattr(sys, "_MEIPASS", HERE), sub)):
        if os.path.isdir(base) and base not in sys.path:
            sys.path.insert(0, base)

import discs  # noqa: E402

VERSION = "Beta 2.5"
VERSION = os.environ.get("MVP05_TEST_VERSION") or VERSION  # Test-Updater.cmd: pretend to be older
GAME = "MVP05-Plus"


def game_dir():
    """The folder with MVP05.exe: the installer's own (frozen), else the repository's root."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(HERE, "..", ".."))


class Log:
    """Messages, and one progress bar across the whole install: the steps (plan) each get a share of the bar by how
    long they usually take; status shows "Step 2 of 3: ..." with the time so far."""
    def __init__(self, say=print, progress=None, status=None):
        self.say, self.progress, self.status = say, progress, status
        self.steps, self.at, self.label, self.started = [], -1, "", 0.0
        self._timer = None

    def plan(self, steps):
        """steps: [(label, seconds it usually takes)]"""
        self.steps, self.at = list(steps), -1

    def step(self, label=None):
        """On to the next step of the plan."""
        import time
        if self.at >= 0:
            self.part(1.0)
        self.at = min(self.at + 1, len(self.steps) - 1)
        self.label = label or (self.steps[self.at][0] if self.steps else "")
        self.started = time.monotonic()
        self.part(0.0)
        self.show_status()

    def show_status(self):
        if self.status and self.steps:
            import time
            t = int(time.monotonic() - self.started)
            self.status(f"Step {self.at + 1} of {len(self.steps)}: {self.label}  ({t // 60}:{t % 60:02d})")

    def part(self, f):
        """This far (0 to 1) through the current step."""
        if not self.progress:
            return
        if not self.steps or self.at < 0:
            return self.progress(f)
        total = sum(s for _, s in self.steps)
        before = sum(s for _, s in self.steps[:self.at])
        self.progress((before + min(max(f, 0.0), 1.0) * self.steps[self.at][1]) / total)

    def timed(self, seconds):
        """For work that can't say how far it is: the bar moves on by the time it usually takes, slowing as it nears the
        end of the step's share so it never sits full while there's still work."""
        log = self

        class Timer:
            def __enter__(self):
                import threading, time, math
                self.stop = threading.Event()

                def tick():
                    t0 = time.monotonic()
                    while not self.stop.wait(0.25):
                        t = time.monotonic() - t0
                        f = 0.9 * t / seconds if t < seconds else 0.9 + 0.08 * (1 - math.exp(-(t - seconds) / seconds))
                        log.part(f)
                        log.show_status()
                threading.Thread(target=tick, daemon=True).start()
                return self

            def __exit__(self, *a):
                self.stop.set()
        return Timer()

    def finish(self, text):
        if self.progress:
            self.progress(1.0)
        if self.status:
            self.status(text)


def need_space(folder, nbytes):
    free = shutil.disk_usage(folder).free
    if free < nbytes + (64 << 20):
        raise discs.DiscError(f"not enough room: {nbytes / 2**30:.1f} GB needed, {free / 2**30:.1f} GB free")


def install_xbox(src, root, log):
    assets = os.path.join(root, "assets")
    with discs.open_xbox(src) as d:
        files = d.files()
        todo = {}
        for p, (_, n) in files.items():
            dest = os.path.join(assets, *p.split("/"))
            if not (os.path.isfile(dest) and os.path.getsize(dest) == n):
                todo[p] = (dest, n)
        total = sum(n for _, n in todo.values())
        log.say(f"Xbox disc: MVP Baseball 2005, {len(files)} files"
                + (f", copying {len(todo)} ({total / 2**20:.0f} MB)" if todo else ", already in assets"))
        if todo:
            need_space(root, total)
        done = [0]

        def step(n):
            done[0] += n
            log.part(done[0] / total)

        for p, (dest, _) in sorted(todo.items()):
            d.copy(p, dest, step)
        with open(os.path.join(assets, MANIFEST), "w") as f:  # what a complete install has: checked at each start
            json.dump({"title": "MVP Baseball 2005 (Xbox)", "files": {p: n for p, (_, n) in files.items()}}, f)
    log.say("Xbox files are in assets.")


MANIFEST = "mvp05-plus-install.json"
# about how long each step takes (seconds), for its share of the progress bar; the art steps can't report progress, so
# the bar moves by these. A faster PC just finishes early
SECONDS = {"xbox": 40, "gamecube": 20, "ps2": 20}
LAUNCHER_FILE = "mvp05-plus-launcher.json"  # the Launcher's own: where DolphinTool / chdman are, once chosen


def load_tools(root):
    try:
        with open(os.path.join(root, LAUNCHER_FILE)) as f:
            discs.TOOL_PATHS.update(json.load(f).get("tools", {}))
    except (OSError, ValueError):
        pass


def remember_tool(root, tool, path):
    discs.TOOL_PATHS[tool] = path
    p = os.path.join(root, LAUNCHER_FILE)
    try:
        with open(p) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data.setdefault("tools", {})[tool] = path
    with open(p, "w") as f:
        json.dump(data, f, indent=2)


def launcher_option(root, key, default=None):
    try:
        with open(os.path.join(root, LAUNCHER_FILE)) as f:
            return json.load(f).get(key, default)
    except (OSError, ValueError):
        return default


def set_launcher_option(root, key, value):
    p = os.path.join(root, LAUNCHER_FILE)
    try:
        with open(p) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data[key] = value
    with open(p, "w") as f:
        json.dump(data, f, indent=2)


def reshuffle(root):
    """The shuffled 162-game schedule dealt anew before the game starts, if it's the one chosen. A season already
    under way keeps the schedule it started with, so this only changes seasons still to come."""
    try:
        import schedules as SCH
        if SCH.current(root) == SCH.SHUFFLED:
            SCH.apply(root, SCH.SHUFFLED)
    except Exception as e:  # never in the way of starting the game
        print(f"schedule: not reshuffled ({e})")


def check_install(root):
    """What's installed, for the window: {exe, xbox, xbox_ok, gamecube, ps2} (texts; xbox_ok True when playable)."""
    assets = os.path.join(root, "assets")
    r = {"exe": os.path.isfile(os.path.join(root, "MVP05.exe"))}
    xbe = os.path.join(assets, "default.xbe")
    if not os.path.isfile(xbe):
        r["xbox"], r["xbox_ok"] = "not installed", False
    else:
        try:
            with open(xbe, "rb") as f:
                tid, name = discs.xbe_title(f.read())
            if tid != discs.XBOX_TITLE:
                raise discs.DiscError(f"assets holds {name or 'another game'}, not MVP Baseball 2005")
            m = os.path.join(assets, MANIFEST)
            if os.path.isfile(m):
                with open(m) as f:
                    want = json.load(f)["files"]
                gone, bad = [], []
                for p, n in want.items():
                    f = os.path.join(assets, *p.split("/"))
                    if not os.path.isfile(f):
                        gone.append(p)
                    elif os.path.getsize(f) != n and not p.lower().endswith("/schedule.big"):  # the Schedule tab's
                        bad.append(p)
                if bad or gone:
                    r["xbox"], r["xbox_ok"] = f"incomplete: {len(bad) + len(gone)} of {len(want)} files missing or " \
                                              f"changed (install it again)", False
                else:
                    r["xbox"], r["xbox_ok"] = f"installed ({len(want)} files, all there)", True
            elif os.path.isfile(os.path.join(assets, "data", "frontend", "shared.big")):
                r["xbox"], r["xbox_ok"] = "installed (put there by hand)", True
            else:
                r["xbox"], r["xbox_ok"] = "incomplete: default.xbe is there but the game's data isn't", False
        except Exception as e:
            r["xbox"], r["xbox_ok"] = f"can't be used: {e}", False
    for kind, name in (("gamecube", "gc_icons"), ("ps2", "ps2_icons")):
        d = os.path.join(root, name)
        if not os.path.isfile(os.path.join(d, "data", "frontend", "shared.big")):
            r[kind] = "not installed (optional)"
        else:
            have = {os.path.relpath(os.path.join(a, f), d).replace(os.sep, "/").lower()
                    for a, _, fs in os.walk(d) for f in fs}
            missing = [f for f in ICON_FILES if f not in have]
            r[kind] = "installed" + (" (an older set, missing " + ", ".join(os.path.basename(m) for m in missing) + ")"
                                     if missing else "")
    return r


def build_art(kind, src, root, log):
    """gc_icons or ps2_icons from a disc; only the art's files are read, into a temporary folder that's deleted."""
    gc = kind == "gamecube"
    opener, names = (discs.open_gamecube, discs.GC_ART_FILES) if gc else (discs.open_ps2, discs.PS2_ART_FILES)
    out_name = "gc_icons" if gc else "ps2_icons"
    xbox_data = os.path.join(root, "assets", "data")
    if not os.path.isfile(os.path.join(xbox_data, "frontend", "shared.big")):
        raise discs.DiscError("the Xbox files aren't in assets yet: the art is made from them too")
    tmp = tempfile.mkdtemp(prefix="mvp-installer-")
    try:
        with opener(src) as d:
            log.say(f"{'GameCube' if gc else 'PS2'} disc: reading the {len(names)} files the button art needs")
            discs.extract(d, names, tmp, upper=not gc)
        disc_data = os.path.join(tmp, "data" if gc else "DATA")
        built = os.path.join(tmp, out_name)
        if gc:
            import make_icons as builder
        else:
            import make_ps2_icons as builder
        argv, sys.argv = sys.argv, [builder.__file__, xbox_data, disc_data, built]
        words = io.StringIO()
        try:
            with contextlib.redirect_stdout(words), log.timed(SECONDS[kind]):
                builder.main()
        except SystemExit as e:
            raise discs.DiscError(f"making {out_name} stopped: {e}")
        finally:
            sys.argv = argv
        put_icons(built, os.path.join(root, out_name))
        log.say(f"{out_name} made ({count_files(os.path.join(root, out_name))} files).")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def count_files(d):
    return sum(len(f) for _, _, f in os.walk(d))


def put_icons(src, dest):
    """src's set in place of dest's, the old one kept until the new one is all there."""
    old = dest + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.exists(dest):
        os.replace(dest, old)
    try:
        shutil.copytree(src, dest)
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        if os.path.exists(old):
            os.replace(old, dest)
        raise
    shutil.rmtree(old, ignore_errors=True)


# what a made set has (make_icons.py / make_ps2_icons.py); an older set may lack some, and the game shows Xbox art
# for whatever's missing
ICON_FILES = ["data/frontend/" + n for n in ("shared.big", "frontend.big", "ingame.big", "igonly.big", "minigame.big")
              ] + [f"data/frontend/load{i}.big" for i in range(8)] + ["data/igshapes/igcrsr.xsh"]


def is_icons_source(src):
    """A folder or a .zip: an icons set someone already made, not a disc."""
    return os.path.isdir(src) or src.lower().endswith(".zip")


def find_set(folder, name):
    """The set in folder: folder itself (it has data/frontend), or a name folder in it or one level further down."""
    def has(d):
        return os.path.isfile(os.path.join(d, "data", "frontend", "shared.big"))
    if has(folder) and os.path.basename(folder.rstrip("/\\")).lower() != ("ps2_icons" if name == "gc_icons" else
                                                                               "gc_icons"):
        return folder
    for d in [os.path.join(folder, name)] + [os.path.join(folder, s, name) for s in sorted(os.listdir(folder))
                                             if os.path.isdir(os.path.join(folder, s))]:
        if has(d):
            return d
    return None


def import_icons(kind, src, root, log):
    """gc_icons or ps2_icons someone already made (a folder, or a .zip with it), copied beside the game."""
    name = "gc_icons" if kind == "gamecube" else "ps2_icons"
    tmp = None
    try:
        if not os.path.isdir(src):
            import zipfile
            tmp = tempfile.mkdtemp(prefix="mvp-installer-")
            try:
                with zipfile.ZipFile(src) as z:
                    for m in z.infolist():
                        target = os.path.realpath(os.path.join(tmp, m.filename))
                        if not target.startswith(os.path.realpath(tmp) + os.sep):
                            raise discs.DiscError(f"{os.path.basename(src)} has a file outside its own folders")
                    z.extractall(tmp)
            except zipfile.BadZipFile:
                raise discs.DiscError(f"{os.path.basename(src)} isn't a zip that can be read")
            folder = tmp
        else:
            folder = src
        found = find_set(folder, name)
        if not found:
            raise discs.DiscError(f"no {name} in {os.path.basename(src) or src} (it should hold data/frontend/shared.big)")
        dest = os.path.join(root, name)
        if os.path.realpath(found) == os.path.realpath(dest):
            log.say(f"{name} is already in place.")
            return
        have = {os.path.relpath(os.path.join(d, f), found).replace(os.sep, "/").lower()
                for d, _, fs in os.walk(found) for f in fs}
        missing = [f for f in ICON_FILES if f not in have]
        put_icons(found, dest)
        log.say(f"{name} copied ({count_files(dest)} files).")
        if missing:
            log.say(f"  It's an older set without {', '.join(os.path.basename(m) for m in missing)}: the game shows "
                    f"Xbox art there. Make a new set from the disc for all of it.")
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def run(root, xbox=None, gamecube=None, ps2=None, log=None):
    load_tools(root)
    """gamecube / ps2: a disc image (the art is made from it), or a gc_icons / ps2_icons folder or .zip (copied)."""
    log = log or Log()
    if not (xbox or gamecube or ps2):
        raise discs.DiscError("choose your Xbox disc, and any GameCube or PS2 disc or icons")
    names = {"gamecube": "GameCube", "ps2": "PS2"}
    steps = [("copying the Xbox game", SECONDS["xbox"])] if xbox else []
    for kind, src in (("gamecube", gamecube), ("ps2", ps2)):
        if src:
            steps.append((f"copying the {names[kind]} button art", 2) if is_icons_source(src) else
                         (f"making the {names[kind]} button art", SECONDS[kind]))
    log.plan(steps)
    if xbox:
        log.step()
        install_xbox(xbox, root, log)
    for kind, src in (("gamecube", gamecube), ("ps2", ps2)):
        if src:
            log.step()
            (import_icons if is_icons_source(src) else build_art)(kind, src, root, log)
    if not os.path.isfile(os.path.join(root, "assets", "default.xbe")):
        log.say("The Xbox files aren't in assets yet: choose your Xbox disc too, the game needs it.")
        log.finish("Done (the Xbox game still needs installing)")
    else:
        log.say("Done. Run MVP05.exe.")
        log.finish("Done")


# ---------------------------------------------------------------- the window

def gui(root):
    import tkinter as tk
    from tkinter import filedialog, ttk

    w = tk.Tk()
    w.title(f"{GAME} Launcher ({VERSION}) by spy_jam")
    import title_icon
    title_icon.ensure(root)  # the game's icon from the Xbox disc, once it's installed

    def set_icon():
        ico = os.path.join(root, title_icon.ICO)
        if os.name == "nt" and os.path.isfile(ico):
            try:
                w.iconbitmap(default=ico)
            except tk.TclError:
                pass
    set_icon()
    w.resizable(False, False)
    tabs = ttk.Notebook(w)
    tabs.grid(padx=8, pady=8)
    tab = ttk.Frame(tabs, padding=12)
    tabs.add(tab, text="Install")
    saves_tab(tabs, root, tk, ttk)
    schedule_tab(tabs, root, tk, ttk)
    tools_tab(tabs, root, tk, ttk)
    mods_tab(tabs, root, tk, ttk)
    settings_tab(tabs, root, tk, ttk)

    # --- what's installed, with Launch: shown when the game is ready to play
    ready = ttk.Frame(tab)
    ttk.Label(ready, text=f"{GAME} is installed", font=("Segoe UI", 12, "bold")).grid(
        row=0, column=0, columnspan=2, sticky="w")
    ttk.Label(ready, text=root, foreground="#555", wraplength=400, justify="left").grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))
    lines = {}
    for i, (k, label) in enumerate((("xbox", "Xbox game"), ("gamecube", "GameCube button art"),
                                    ("ps2", "PS2 button art"))):
        mark = None
        text = ttk.Label(ready)
        text.grid(row=2 + i, column=0, columnspan=2, sticky="w", pady=1)
        lines[k] = (mark, text, label)
    # the game's own title art from your Xbox disc (default.xbe's title image), in the top right corner
    art = ttk.Label(ready)
    art.grid(row=0, column=2, rowspan=6, sticky="ne", padx=(12, 0))
    ready.columnconfigure(1, weight=1)
    # double-click the title art: one of spy_jam's dogs, in the empty corner under it (click it to put it away)
    # (laid over the corner, so nothing else on the tab moves; the controller lines wrap short of it meanwhile)
    dog = ttk.Label(ready.master, cursor="hand2")

    def show_dog(*_):
        import random
        folder = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "easter")
        try:
            files = sorted(f for f in os.listdir(folder) if f.endswith(".png"))
        except OSError:
            return
        if not files:
            return
        last = getattr(dog, "file", None)
        pick = random.choice([f for f in files if f != last] or files)
        try:
            dog.picture = tk.PhotoImage(file=os.path.join(folder, pick))
        except tk.TclError:
            return
        dog.file = pick
        dog.configure(image=dog.picture)
        dog.place(relx=1.0, rely=1.0, x=-12, y=-12, anchor="se")
        dog.lift()
        for x in (pad_adapter, pad_others):
            x.configure(wraplength=380)

    def hide_dog(*_):
        dog.place_forget()
        for x in (pad_adapter, pad_others):
            x.configure(wraplength=520)

    art.bind("<Double-Button-1>", show_dog)
    dog.bind("<Button-1>", hide_dog)

    def show_art():
        if getattr(art, "picture", None):
            return
        try:
            import base64
            with open(os.path.join(root, "assets", "default.xbe"), "rb") as f:
                im = title_icon.title_image(f.read())
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            art.picture = tk.PhotoImage(data=base64.b64encode(buf.getvalue()))
            art.configure(image=art.picture)
        except Exception:  # no picture is fine: the rest of the tab is as it was
            pass
    rb = ttk.Frame(ready)
    rb.grid(row=6, column=0, columnspan=3, sticky="we", pady=(16, 0))
    launch = ttk.Button(rb, text="Launch MVP 05")
    launch.pack(side="left", ipadx=18, ipady=6)
    change = ttk.Button(rb, text="Add or change button art, or reinstall…")
    change.pack(side="left", padx=10)
    launch_note = ttk.Label(ready, text="", foreground="#a33", wraplength=520, justify="left")
    # gridded only when there's something to say, so its empty line doesn't push the rest down
    # what Windows sees right now (controllers.py): the adapter and its driver, and the other controllers
    ttk.Label(ready, text="Controllers", font=("Segoe UI", 10, "bold")).grid(row=8, column=0, columnspan=2,
                                                                            sticky="w", pady=(18, 2))
    pad_adapter = ttk.Label(ready, text="Looking…", wraplength=520, justify="left")
    pad_adapter.grid(row=9, column=0, columnspan=2, sticky="w")
    pad_others = ttk.Label(ready, text="", wraplength=520, justify="left")
    pad_others.grid(row=10, column=0, columnspan=2, sticky="w")
    ttk.Label(ready, foreground="#777", wraplength=520, justify="left", text=(
        "Button art follows the controller connected when the game starts.")).grid(
        row=11, column=0, columnspan=2, sticky="w", pady=(4, 0))
    # Player of the Day (potd.py): one MLB player from the disc's rosters, the same for everyone on the same date,
    # with his picture from your own installed game
    potd_card = ttk.Frame(ready)
    potd_pic = ttk.Label(potd_card)
    potd_pic.grid(row=0, column=0, rowspan=4, sticky="nw", padx=(0, 10))
    ttk.Label(potd_card, text="PLAYER OF THE DAY", foreground="#777", font=("Segoe UI", 8, "bold")).grid(
        row=0, column=1, sticky="w")
    potd_name = ttk.Label(potd_card, font=("Segoe UI", 11, "bold"))
    potd_name.grid(row=1, column=1, sticky="w")
    potd_team = ttk.Label(potd_card, foreground="#444")
    potd_team.grid(row=2, column=1, sticky="w")
    potd_line = ttk.Label(potd_card, foreground="#666")
    potd_line.grid(row=3, column=1, sticky="nw")

    def show_potd():
        if getattr(potd_card, "day", None) == datetime.date.today():
            return

        def work():
            import potd
            day = datetime.date.today()
            try:
                p, im = potd.today(root, day)
            except Exception:  # no card is fine: the tab is as it was
                return
            data = None
            if im is not None:
                import base64
                from PIL import Image
                buf = io.BytesIO()
                im.resize((76, 76), Image.LANCZOS).save(buf, format="PNG")
                data = base64.b64encode(buf.getvalue())
            w.after(0, lambda: shown(day, p, data))

        def shown(day, p, data):
            potd_card.day = day
            if data:
                potd_pic.picture = tk.PhotoImage(data=data)
                potd_pic.configure(image=potd_pic.picture)
            potd_name.configure(text=p["name"])
            potd_team.configure(text="  \u00b7  ".join(x for x in (
                f"#{p['number']}" if p["number"] else "", p["pos"], p["team"]) if x))
            potd_line.configure(text=p["line"])
            potd_card.grid(row=12, column=0, columnspan=2, sticky="w", pady=(28, 0))
        threading.Thread(target=work, daemon=True).start()
    colours = {"ok": "#1a7f37", "warn": "#b35900", "none": "#777"}

    def watch_pads():
        import controllers

        def look():
            try:
                st = controllers.status()
            except Exception as e:
                st = e
            w.after(0, lambda: show_pads(st))

        def show_pads(st):
            if st is None:
                pad_adapter.configure(text="Controller status is shown on Windows.", foreground="#777")
            elif isinstance(st, Exception):
                pad_adapter.configure(text=f"Couldn't read the controllers: {st}", foreground="#777")
            else:
                (level, text), line = controllers.summary(st)
                pad_adapter.configure(text=text, foreground=colours[level])
                pad_others.configure(text=line, foreground="#1a7f37" if st["pads"] or st["xinput"] else "#777")
            if st is not None:
                w.after(3000, lambda: threading.Thread(target=look, daemon=True).start())
        threading.Thread(target=look, daemon=True).start()

    # --- the discs
    frm = ttk.Frame(tab)
    ttk.Label(frm, text=f"{GAME} installs into this folder:", font=("Segoe UI", 10, "bold")).grid(
        row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(frm, text=root, foreground="#555").grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 10))
    kinds = [
        ("xbox", "Xbox disc (required)", [("Xbox image", "*.iso *.xiso"), ("All files", "*.*")], True),
        ("gamecube", "GameCube disc, or a gc_icons folder or .zip someone made (optional, button art)",
         [("GameCube image or icons zip", "*.iso *.gcm *.rvz *.gcz *.ciso *.wia *.zip"), ("All files", "*.*")],
         "gc_icons"),
        ("ps2", "PS2 disc, or a ps2_icons folder or .zip someone made (optional, button art)",
         [("PS2 image or icons zip", "*.iso *.chd *.zip"), ("All files", "*.*")], "ps2_icons"),
    ]
    vars_ = {}
    labels = {}
    for i, (k, label, types, folder_ok) in enumerate(kinds):
        v = tk.StringVar()
        vars_[k] = v
        labels[k] = ttk.Label(frm, text=label)
        labels[k].grid(row=2 + 2 * i, column=0, columnspan=3, sticky="w")
        ttk.Entry(frm, textvariable=v, width=60).grid(row=3 + 2 * i, column=0, sticky="we", pady=(0, 6))

        def pick(v=v, types=types):
            p = filedialog.askopenfilename(filetypes=types)
            if p:
                v.set(os.path.normpath(p))

        ttk.Button(frm, text="Image…", command=pick).grid(
            row=3 + 2 * i, column=1, padx=(6, 0), pady=(0, 6))

        def pickdir(v=v, what=folder_ok):
            p = filedialog.askdirectory(title="The folder with default.xbe" if what is True else f"The {what} folder")
            if p:
                v.set(os.path.normpath(p))
        ttk.Button(frm, text="Folder…", command=pickdir).grid(row=3 + 2 * i, column=2, padx=(6, 0), pady=(0, 6))

    status_text = tk.StringVar(value="")
    ttk.Label(frm, textvariable=status_text, foreground="#444").grid(row=8, column=0, columnspan=3, sticky="w",
                                                                     pady=(8, 0))
    bar = ttk.Progressbar(frm, length=440, mode="determinate", maximum=1.0)
    bar.grid(row=9, column=0, columnspan=3, sticky="we", pady=(2, 4))
    out = tk.Text(frm, width=72, height=8, state="disabled", wrap="word", relief="flat", background="#f4f4f4")
    out.grid(row=10, column=0, columnspan=3, pady=4)
    fb = ttk.Frame(frm)
    fb.grid(row=11, column=0, columnspan=3, sticky="we", pady=(6, 0))
    go = ttk.Button(fb, text="Install")
    go.pack(side="right")
    back = ttk.Button(fb, text="← Back")

    def say(t):
        def f():
            out.configure(state="normal")
            out.insert("end", t + "\n")
            out.see("end")
            out.configure(state="disabled")
        w.after(0, f)

    def show(state=None):
        """The installed view when the game's ready to play, else the discs."""
        r = state or check_install(root)
        ok = r["xbox_ok"] and r["exe"]
        tabs.tab(tab, text="Play" if ok else "Install")  # Install until the game's installed, then Play
        if ok:
            for k, (mark, text, label) in lines.items():
                good = r[k].startswith("installed")
                text.configure(text=f"{label}: {r[k]}", foreground="#1a7f37" if good else "#777")
            frm.grid_remove()
            ready.grid(row=0, column=0, sticky="nwe")
            tab.columnconfigure(0, weight=1)
            show_art()
            show_potd()
            back.pack(side="left")
            labels["xbox"].configure(text="Xbox disc (installed: leave empty, or choose one to install again)")
        else:
            ready.grid_remove()
            frm.grid(row=0, column=0, sticky="nw")
            if not r["exe"]:
                say("Note: MVP05.exe isn't in this folder. Put MVP05-Plus Launcher in the game's folder.")
            elif r["xbox"] != "not installed":
                say(f"Xbox game: {r['xbox']}")
        return ok

    def progress(x):
        w.after(0, lambda: bar.configure(value=x))

    def status(t):
        w.after(0, lambda: status_text.set(t))

    def work():
        try:
            run(root, **{k: (v.get().strip() or None) for k, v in vars_.items()}, log=Log(say, progress, status))
            w.after(0, lambda: bar.configure(value=1.0))
            import title_icon
            if title_icon.ensure(root, say):
                w.after(0, set_icon)
            r = check_install(root)
            if r["xbox_ok"] and r["exe"]:
                w.after(1200, lambda: (show(r), [v.set("") for v in vars_.values()]))
        except discs.ToolMissing as e:
            w.after(0, lambda: ask_tool(e))
        except discs.DiscError as e:
            say(f"Stopped: {e}")
        except Exception:
            say("Something went wrong:\n" + traceback.format_exc(limit=4))
        finally:
            w.after(0, lambda: go.configure(state="normal"))

    def ask_tool(e):
        """Where DolphinTool / chdman is, asked once and remembered; then the install goes on."""
        say(str(e))
        p = filedialog.askopenfilename(title=f"Where is {e.exe}?", filetypes=[(e.exe, e.exe), ("Programs", "*.exe")])
        if p:
            remember_tool(root, e.tool, os.path.normpath(p))
            say(f"Using {os.path.normpath(p)}")
            start()

    def start():
        go.configure(state="disabled")
        bar.configure(value=0)
        threading.Thread(target=work, daemon=True).start()

    def offer_bring_over(*_):
        """The first time the Launcher opens in a folder without the game, and on Ctrl+Shift+B: an older MVP05-Plus
        (Beta 1 has no updater) or Mad Dog's MVP05, its game, saves and settings brought in instead of the discs."""
        from tkinter import messagebox
        set_launcher_option(root, "offered_bring_over", True)
        if not messagebox.askyesno("Already have MVP05-Plus?", (
                "Coming from MVP05-Plus Beta 1 or Mad Dog's MVP05?\n\n"
                "Bring over its game, saves and settings, instead of installing from your discs.\n\n"
                "(Ctrl+Shift+B asks again later.)"), parent=w):
            return
        bring_over()

    def bring_over():
        """An older install's game, saves and settings, copied or moved in."""
        import carryover
        from tkinter import messagebox
        old = filedialog.askdirectory(title="Your older MVP05-Plus folder (the one with MVP05.exe)")
        if not old:
            return
        old = os.path.normpath(old)
        try:
            size = carryover.check(old, root)
        except carryover.CarryError as e:
            return messagebox.showinfo("Bring it over", f"That folder can't be used: {e}.", parent=w)
        how = {}
        win = tk.Toplevel(w)
        win.title("Bring it over")
        win.transient(w)
        win.grab_set()
        f = ttk.Frame(win, padding=14)
        f.grid()
        gb = f"{size / 2**30:.1f} GB"
        ttk.Label(f, wraplength=420, justify="left", text=(
            f"Bring over your game, saves and settings from:\n{old} ({gb})")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        ttk.Label(f, wraplength=420, justify="left", text=(
            f"Copy: keeps the old folder. Needs {gb} free.\n"
            "Move: needs no extra space. The old folder won't work afterwards.")).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(0, 12))
        for i, (text, v) in enumerate((("Copy", False), ("Move", True))):
            ttk.Button(f, text=text, command=lambda v=v: (how.update(move=v), win.destroy())).grid(
                row=3, column=i, padx=(0, 6), sticky="w")
        ttk.Button(f, text="Cancel", command=win.destroy).grid(row=3, column=2, sticky="e")
        win.wait_window()
        if "move" not in how:
            return
        if updater_running():
            return messagebox.showinfo("Bring it over", "Close MVP05.exe first.", parent=w)
        go.configure(state="disabled")
        bar.configure(value=0)
        status("Bringing it over...")

        def job():
            try:
                carryover.bring_over(old, root, how["move"], say, progress)
                import title_icon
                if title_icon.ensure(root, say):
                    w.after(0, set_icon)
                r = check_install(root)
                status("")
                if r["xbox_ok"] and r["exe"]:
                    say("Done: everything's here. The old folder can be deleted once you've checked it all.")
                    w.after(1500, lambda: show(r))
                else:
                    say(f"Brought over, but the game isn't ready: {r['xbox']}")
            except (OSError, carryover.CarryError) as e:
                status("")
                say(f"Stopped: {e}")
            finally:
                w.after(0, lambda: go.configure(state="normal"))
        threading.Thread(target=job, daemon=True).start()

    def updater_running():
        import updater
        return updater.game_running()

    def do_launch():
        exe = os.path.join(root, "MVP05.exe")
        import gamepad_nav
        gamepad_nav.release()  # the GameCube adapter, if the Launcher was reading it: the game needs it
        reshuffle(root)  # the shuffled schedule, if chosen: a new deal for the seasons to come
        try:
            game = subprocess.Popen([exe], cwd=root, close_fds=True)
        except OSError as e:
            launch_note.configure(text=f"MVP05.exe wouldn't start: {e}")
            launch_note.grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))
            return
        # the Launcher stays, minimized: alt-tab to it for the Tools while the game runs. It closes with the game,
        # unless it was brought back up (to patch a save after quitting, say): then it stays until it's closed.
        w.after(800, w.iconify)

        def watch():
            if game.poll() is None:
                return w.after(1000, watch)
            import updater
            if updater.game_running():  # another MVP05.exe took over (a title launch): wait for that one too
                return w.after(2000, watch)
            if w.state() == "iconic":
                w.destroy()
        w.after(2000, watch)

    def do_change():
        ready.grid_remove()
        frm.grid(row=0, column=0, sticky="nw")

    go.configure(command=start)
    w.bind_all("<Control-Shift-B>", offer_bring_over)
    w.bind_all("<Control-Shift-b>", offer_bring_over)
    launch.configure(command=do_launch)
    change.configure(command=do_change)
    back.configure(command=lambda: show())
    if not show() and not launcher_option(root, "offered_bring_over", False):
        w.after(600, offer_bring_over)  # the first time, in a folder without the game
    watch_pads()
    import gamepad_nav  # a controller moves around the Launcher too
    gamepad_nav.attach(w, tabs, on_start=lambda: do_launch() if ready.winfo_ismapped() and
                       tabs.index(tabs.select()) == 0 else None)
    tabs.focus_set()
    import updater
    updater.tidy(root)
    if launcher_option(root, "check_updates", True):
        check_for_update(w, root, tk, ttk, quiet=True)
    w.mainloop()


def when_text(t):
    """11-07-2026 3:39 PM"""
    return f"{t.month:02d}-{t.day:02d}-{t.year} {t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def right_click_menu(tree, items_for):
    """A right-click menu on a list's rows: the row under the pointer is picked (kept with the others when it's
    already one of several picked), then items_for(row) gives the menu's [(label, command)]."""
    import tkinter as tk

    def popup(e):
        iid = tree.identify_row(e.y)
        if not iid:
            return
        if iid not in tree.selection():
            tree.selection_set(iid)
        tree.focus(iid)
        m = tk.Menu(tree, tearoff=0)
        for label, cmd in items_for(iid):
            m.add_command(label=label, command=cmd)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()
    tree.bind("<Button-3>", popup)


def open_in_explorer(path):
    os.makedirs(path, exist_ok=True)
    if os.name == "nt":
        os.startfile(path)


def saves_tab(tabs, root, tk, ttk):
    """Saves: your saves or their backups, one switch apart. Import a save opens from your saves."""
    outer = ttk.Frame(tabs, padding=12)
    tabs.add(outer, text="Saves")
    head = ttk.Frame(outer)
    head.grid(row=0, column=0, sticky="we", pady=(0, 6))
    outer.columnconfigure(0, weight=1)
    ttk.Label(head, text="Saves", font=("Segoe UI", 10, "bold")).pack(side="left")
    view = tk.StringVar(value="saves")
    switch = ttk.Frame(head)
    switch.pack(side="right")
    pages = {"saves": ttk.Frame(outer), "backups": ttk.Frame(outer)}
    refresh_current = current_saves_tab(pages["saves"], root, tk, ttk)
    refresh_backups = backups_tab(pages["backups"], root, tk, ttk, refresh_current)
    refresh = {"saves": refresh_current, "backups": refresh_backups}

    def show(*_):
        for k, f in pages.items():
            if k == view.get():
                f.grid(row=1, column=0, sticky="nwe")
            else:
                f.grid_remove()
        refresh[view.get()]()  # each list as it is now when it's looked at
    for value, text in (("saves", "Your saves"), ("backups", "Backups")):
        ttk.Radiobutton(switch, text=text, value=value, variable=view, style="Toolbutton", command=show).pack(
            side="left")
    show()
    outer.bind("<Map>", lambda _: refresh[view.get()]())


def import_window(parent, root, tk, ttk, on_close=None, start=None):
    """Import a save, in a window of its own over the Launcher; your saves listed again when it closes. start: a
    save's path, chosen already (dragged onto the Saves tab)."""
    w = parent.winfo_toplevel()
    for c in w.winfo_children():  # one at a time
        if isinstance(c, tk.Toplevel) and getattr(c, "_import", False):
            c.lift()
            if start and getattr(c, "_use", None):
                c._use(start)
            return
    win = tk.Toplevel(w)
    win._import = True
    win.title("Import a save")
    win.transient(w)
    win.resizable(False, False)
    f = ttk.Frame(win, padding=14)
    f.grid()
    ttk.Label(f, text="Import a save", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w",
                                                                          pady=(0, 2))
    body = ttk.Frame(f)
    body.grid(row=1, column=0, sticky="nwe")
    win._use = import_tool(body, root, tk, ttk, start).use
    bar = ttk.Frame(f)
    bar.grid(row=2, column=0, sticky="e", pady=(12, 0))

    def close():
        win.destroy()
        if on_close:
            on_close()
    ttk.Button(bar, text="Close", command=close).pack(side="right")
    win.protocol("WM_DELETE_WINDOW", close)
    win.update_idletasks()  # centred over the Launcher
    x = w.winfo_rootx() + (w.winfo_width() - win.winfo_width()) // 2
    y = w.winfo_rooty() + (w.winfo_height() - win.winfo_height()) // 3
    win.geometry(f"+{max(x, 0)}+{max(y, 0)}")


def choose_card_save(parent, tk, ttk, found):
    """One of a memory card's MVP 2005 saves [(folder, file, what, save)], picked in a small window; None if
    closed."""
    win = tk.Toplevel(parent)
    win.title("Which save?")
    win.transient(parent.winfo_toplevel())
    win.grab_set()
    f = ttk.Frame(win, padding=12)
    f.grid()
    ttk.Label(f, text="The memory card has more than one MVP 2005 save. Which one?").grid(sticky="w")
    lb = tk.Listbox(f, height=min(8, len(found)), width=56, exportselection=False)
    for folder, name, what, _ in found:
        lb.insert("end", f"{name}: {what}   ({folder})")
    lb.selection_set(0)
    lb.grid(sticky="we", pady=8)
    out = {}

    def ok(*_):
        if lb.curselection():
            out["v"] = found[lb.curselection()[0]]
        win.destroy()
    ttk.Button(f, text="Use this one", command=ok).grid(sticky="e")
    lb.bind("<Double-Button-1>", ok)
    win.wait_window()
    return out.get("v")


def import_tool(frm, root, tk, ttk, start=None):
    """Import a save: a save from another MVP 2005 written into one of your saves here (backed up first), so it
    plays in MVP05-Plus. Rosters from the PS2, PC or another Xbox (Mad Dog's conversion, from his MVP Roster
    Toolkit); dynasties from the GameCube (spy_jam's converter), the PS2 and the PC (both of theirs)."""
    import dynasty05 as DY
    import gcroster05 as GR
    import ps2card as PC
    import pcdynasty05 as PCD
    import ps2dynasty05 as PD
    import rosters05 as RO
    import saves05 as S
    from tkinter import filedialog, messagebox

    frm.columnconfigure(1, weight=1)
    ttk.Label(frm, foreground="#666", wraplength=540, justify="left", text=(
        "Brings a save from another version of MVP 2005 into this one. It works with:\n"
        "\u2022  rosters or a dynasty from the PS2 (a .psu, a PCSX2 memory card .ps2, or the .sav file from a save)\n"
        "\u2022  rosters or a dynasty from the GameCube (the .gci file Dolphin exports)\n"
        "\u2022  rosters or a dynasty from the PC (.sav)\n"
        "\u2022  rosters or a dynasty from another Xbox (its data.dat)\n"
        "The save goes into one of your own saves of the same kind, which is backed up first. To take a dynasty the "
        "other way, to the GameCube, the PS2 or the PC, right-click it in your saves.")).grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(0, 12))

    def step(row, n, text):
        ttk.Label(frm, text=f"{n}.", font=("Segoe UI", 9, "bold")).grid(row=row, column=0, sticky="nw", padx=(0, 8))
        ttk.Label(frm, text=text, font=("Segoe UI", 9, "bold")).grid(row=row, column=1, sticky="w")

    step(2, 1, "Choose the save to bring in")
    line = ttk.Frame(frm)
    line.grid(row=3, column=1, sticky="w", pady=(4, 12))
    pick_b = ttk.Button(line, text="Choose a save...")
    pick_b.pack(side="left")
    src_text = ttk.Label(line, text="", foreground="#666")
    src_text.pack(side="left", padx=10)

    step(4, 2, "Pick which of your saves it replaces")
    box = ttk.Combobox(frm, state="readonly", width=48)
    box.grid(row=5, column=1, sticky="w", pady=(4, 2))
    hint = ttk.Label(frm, foreground="#666", wraplength=520, justify="left")
    hint.grid(row=6, column=1, sticky="w", pady=(0, 12))

    step(7, 3, "Import it")
    go_line = ttk.Frame(frm)
    go_line.grid(row=8, column=1, sticky="w", pady=(4, 0))
    go_b = ttk.Button(go_line, text="Import", state="disabled")
    go_b.pack(side="left")
    note = ttk.Label(frm, wraplength=520, justify="left")
    note.grid(row=9, column=1, sticky="w", pady=(8, 0))
    ttk.Label(frm, foreground="#888", wraplength=540, justify="left", text=(
        "Roster conversion by Mad Dog (MVP Roster Toolkit). GameCube conversion (rosters and dynasties) by spy_jam. "
        "PS2 and PC dynasties use both.")).grid(
        row=10, column=0, columnspan=2, sticky="w", pady=(16, 0))
    picked, targets = {}, []
    kinds = {"roster": ("roster save", "rosters"), "dynasty": ("dynasty save", "dynasty")}

    def say(text, colour="#555"):
        note.configure(text=text, foreground=colour)

    def ready():
        go_b.configure(state="normal" if picked.get("kind") and targets and box.current() >= 0 else "disabled")

    def refresh(*_):
        old, kind = box.get(), picked.get("kind")
        targets.clear()
        for s in S.list_saves(root):
            size = os.path.getsize(os.path.join(s["folder"], "data.dat"))
            if (kind == "roster" and size == RO.XBOX_SAVE_SIZE) or \
                    (kind == "dynasty" and size == DY.XB_DYNASTY_SIZE and s["type"] == "Dynasty"):
                targets.append(s)
        labels = [f"{s['name']} ({when_text(s['when'])})" for s in targets]
        box.configure(values=labels, state="readonly" if labels else "disabled")
        if old in labels:
            box.set(old)
        elif labels:
            box.current(0)
        else:
            box.set("")
        if not kind:
            hint.configure(text="Choose a save first: then your saves of the same kind are listed here.",
                           foreground="#666")
        elif labels:
            hint.configure(text=f"That {kinds[kind][0]} is backed up first. A dynasty keeps the name of the save "
                                "it goes into." if kind == "dynasty" else
                           f"That {kinds[kind][0]} is backed up first.", foreground="#666")
        else:
            hint.configure(text=f"You don't have a {kinds[kind][0]} yet. In the game, " +
                           ("save your rosters once" if kind == "roster" else "start a dynasty and save it") +
                           ", then come back here.", foreground="#a33")
        ready()

    def pick():
        p = filedialog.askopenfilename(parent=frm, title="A save from another MVP 2005", filetypes=[
            ("MVP 2005 saves", "*.gci *.psu *.ps2 *.sav *.dat"), ("All files", "*.*")])
        if p:
            use(p)

    def use(p):
        """The save at p chosen (from the button, or dragged in); an Xbox save's folder stands for its data.dat."""
        if os.path.isdir(p) and os.path.isfile(os.path.join(p, "data.dat")):
            p = os.path.join(p, "data.dat")
        picked.clear()
        say("")
        try:
            with open(p, "rb") as f:
                data = f.read()
            if data[:4] == b"GV4E" and b"Rosters" in data[:0x40]:
                GR.read_gc(data)
                picked.update(kind="roster", gc_roster=data, what="GameCube rosters")
            elif data[:4] == b"GV4E":
                meta = DY.read_gc(data)
                picked.update(kind="dynasty", data=data, what=f"GameCube dynasty \"{meta['name']}\"")
            elif data[:28] == PC.MAGIC:  # a PS2 memory card: its MVP 2005 roster and dynasty saves
                found, refused = [], []
                for folder, files in PC.Card(data).saves().items():
                    for name, b in files.items():
                        try:
                            if len(b) == RO.SIZE + RO.PC_HEAD:
                                found.append((folder, name, "rosters", RO.read(b)))
                            elif len(b) == PD.HEAD + PD.SIZE:
                                found.append((folder, name, "dynasty", PD.read(b)))
                        except (RO.RosterError, PD.Ps2DynastyError) as e:
                            refused.append(str(e))
                if not found:
                    raise RO.RosterError(refused[0] if refused else "that memory card has no MVP 2005 roster or "
                                                                    "dynasty save on it")
                which = found[0] if len(found) == 1 else choose_card_save(frm, tk, ttk, found)
                if not which:
                    return
                if which[2] == "dynasty":
                    picked.update(kind="dynasty", ps2_dynasty=which[3],
                                  what=f"PS2 dynasty \"{which[3]['name']}\" ({which[1]} on the card)")
                else:
                    picked.update(kind="roster", save=which[3], what=f"PS2 rosters ({which[1]} on the card)")
            elif len(data) == DY.XB_DYNASTY_SIZE:
                m = DY.read_xbox(data)
                picked.update(kind="dynasty", xbox_dynasty=True, data=data, what=f"Xbox dynasty \"{m['name']}\"")
            elif PCD.is_dynasty(data):
                d = PCD.read(data)
                picked.update(kind="dynasty", pc_dynasty=d, what=f"PC dynasty \"{d['name']}\"")
            elif PD.is_dynasty(data):
                d = PD.read(data)
                picked.update(kind="dynasty", ps2_dynasty=d, what=f"PS2 dynasty \"{d['name']}\"")
            else:
                save = RO.read(data)
                picked.update(kind="roster", save=save, what=f"{save.platform} rosters")
        except (OSError, RO.RosterError, DY.DynastyError, PC.CardError, GR.GcRosterError, PD.Ps2DynastyError,
                PCD.PcDynastyError) as e:
            src_text.configure(text=f"{os.path.basename(p)}: can't be used ({e})", foreground="#a33")
            return refresh()
        picked["path"] = p
        src_text.configure(text=f"{os.path.basename(p)}: {picked['what']} \u2713", foreground="#1a7f37")
        refresh()

    def go():
        kind, s = picked.get("kind"), targets[box.current()] if box.current() >= 0 else None
        if not kind or not s:
            return
        if not messagebox.askyesno("Import a save", (
                f"Replace the {kinds[kind][1]} in \"{s['name']}\" with the {picked['what']} from "
                f"{os.path.basename(picked['path'])}?\n\n\"{s['name']}\" is backed up first (Saves > Backups)."),
                parent=frm):
            return
        dat = os.path.join(s["folder"], "data.dat")
        go_b.configure(state="disabled")
        say("Converting...")

        def work():
            try:
                if S.game_running():
                    raise RO.RosterError("close MVP05.exe first: the game keeps its saves open while it runs")
                with open(dat, "rb") as f:
                    mine = f.read()
                if picked.get("xbox_dynasty"):
                    out = DY.xbox_to_xbox(picked["data"], mine)
                elif picked.get("pc_dynasty"):
                    out = PCD.to_xbox(picked["pc_dynasty"], mine)
                elif picked.get("ps2_dynasty"):
                    out = PD.to_xbox(picked["ps2_dynasty"], mine)
                elif kind == "dynasty":
                    out = DY.gc_to_xbox(picked["data"], mine)
                elif picked.get("gc_roster"):
                    out = GR.to_xbox(picked["gc_roster"], mine)
                else:
                    out = RO.to_xbox(picked["save"], mine)
                S.backup_folder(root, s["folder"], f"importing {kinds[kind][1]}")
                with open(dat + ".new", "wb") as f:
                    f.write(out)
                os.replace(dat + ".new", dat)
                msg = (f"Done. Load \"{s['name']}\" in the game. The old save is in Saves > Backups.",
                       "#1a7f37")
            except (OSError, RO.RosterError, DY.DynastyError, GR.GcRosterError, PD.Ps2DynastyError,
                    PCD.PcDynastyError) as e:
                msg = (f"Nothing was changed: {e}.", "#a33")
            frm.after(0, lambda: (say(*msg), refresh()))
        threading.Thread(target=work, daemon=True).start()

    pick_b.configure(command=pick)
    go_b.configure(command=go)
    box.bind("<<ComboboxSelected>>", lambda _: ready())
    refresh()
    import dragdrop
    if dragdrop.accept(frm.winfo_toplevel(), lambda paths: use(paths[0])):
        ttk.Label(line, text="or drag it here", foreground="#888").pack(side="left")
    if start:
        use(start)
    refresh.use = use
    return refresh


def export_dynasty(frm, folder, name, to, tk, ttk):
    """A dynasty of yours as a GameCube .gci (spy_jam's converter), a PS2 save or a PC .sav (to: "GameCube", "PS2" or
    "PC"), built on one of your own dynasty saves from there: it gives the new file its name and its place."""
    import dynasty05 as DY
    import pcdynasty05 as PCD
    import ps2card as PC
    import ps2dynasty05 as PD
    import rosters05 as RO
    from tkinter import filedialog, messagebox
    title = f"Export to {to}"
    errors = (OSError, DY.DynastyError, PD.Ps2DynastyError, RO.RosterError, PC.CardError, PCD.PcDynastyError)
    try:
        with open(os.path.join(folder, "data.dat"), "rb") as f:
            data = f.read()
        if len(data) != DY.XB_DYNASTY_SIZE:
            raise DY.DynastyError(f"only dynasty saves go to the {to} (not owner mode, rosters or the others)")
        DY.read_xbox(data)
    except errors as e:
        messagebox.showinfo(title, f"\"{name}\" can't be exported: {e}.", parent=frm)
        return
    gc = to == "GameCube"
    how = ("If you don't have one: start a dynasty in the GameCube game and save it, then in Dolphin open "
           "Tools > Memory Card Manager and export that save as a .gci file.\n\n"
           "Choose that .gci next. It isn't changed: you get a new file to import with the Memory Card Manager."
           if gc else
           "If you don't have one: start a dynasty in the PC game and save it. Choose that save next "
           "(<name>_Dynasty.sav, where the PC game keeps its saves).\n\n"
           "It isn't changed: you get a new .sav to put in that folder."
           if to == "PC" else
           "If you don't have one: start a dynasty in the PS2 game and save it. Then choose your PCSX2 memory card "
           "(.ps2) next, or that save as a .psu.\n\n"
           "It isn't changed: you get a new .psu to import (in PCSX2, with a memory card tool such as mymc; on a "
           "console, with uLaunchELF).")
    if not messagebox.askokcancel(title, (
            f"\"{name}\" is written into a copy of one of your own {to} dynasty saves.\n\n{how}"
            + ("" if to == "PC" else
               f"\n\nThe {to} keeps each player's last 6 seasons of history, so older seasons are left out.")),
            parent=frm):
        return
    p = filedialog.askopenfilename(parent=frm, title=f"One of your {to} dynasty saves", filetypes=[
        ("GameCube saves", "*.gci") if gc else ("PC saves", "*.sav") if to == "PC" else
        ("PS2 saves and memory cards", "*.psu *.ps2 *.sav"), ("All files", "*.*")])
    if not p:
        return
    try:
        with open(p, "rb") as f:
            base = f.read()
        if gc:
            fname, out = DY.xbox_to_gc(data, base)
            stem, ext = (fname[:-4] if fname.endswith(".gci") else fname) + " (from MVP05-Plus)", ".gci"
        elif to == "PC":
            out, ext = PCD.to_pc(data, base), ".sav"
            stem = os.path.splitext(os.path.basename(p))[0]
            stem = (stem[:-8] + "2_Dynasty") if stem.endswith("_Dynasty") else stem + " (from MVP05-Plus)"
        else:
            stem = os.path.splitext(os.path.basename(p))[0] + " (from MVP05-Plus)"
            if base[:28] == PC.MAGIC:  # a memory card: its dynasty, as a .psu
                found = []
                for card_folder, files in PC.Card(base).saves().items():
                    for n, b in files.items():
                        if len(b) == PD.HEAD + PD.SIZE:
                            try:
                                found.append((card_folder, n, "dynasty", PD.read(b)))
                            except PD.Ps2DynastyError:
                                pass
                if not found:
                    raise PD.Ps2DynastyError("that memory card has no MVP 2005 dynasty on it")
                which = found[0] if len(found) == 1 else choose_card_save(frm, tk, ttk, found)
                if not which:
                    return
                base = PC.to_psu(which[0], PC.Card(base).saves()[which[0]])
                stem = f"{which[0]} (from MVP05-Plus)"
            ext, out = PD.to_ps2(data, base)
    except errors as e:
        messagebox.showerror(title, f"Nothing was written: {e}.", parent=frm)
        return
    dest = filedialog.asksaveasfilename(parent=frm, title=f"Save the {to} dynasty as", initialdir=os.path.dirname(p),
                                        initialfile=stem + ext, defaultextension=ext,
                                        filetypes=[(f"{to} saves", "*" + ext)])
    if not dest:
        return
    if os.path.abspath(dest) == os.path.abspath(p) and not messagebox.askyesno(
            title, "That's the save you chose to build on. Replace it?", parent=frm):
        return
    try:
        with open(dest + ".new", "wb") as f:
            f.write(out)
        os.replace(dest + ".new", dest)
    except OSError as e:
        messagebox.showerror(title, f"Nothing was written: {e}.", parent=frm)
        return
    messagebox.showinfo(title, f"Saved {os.path.basename(dest)}.\n\n" + (
        "In Dolphin: Tools > Memory Card Manager > Import, and choose it. It takes the place of the GameCube dynasty "
        "it was built on, so delete that one from the card first if Dolphin says the save already exists."
        if gc else
        "Put it in the PC game's saves folder and load it there. If it doesn't show in the game's list, save it over "
        "the dynasty it was built on instead (keep a copy of that one first)."
        if to == "PC" else
        "Import it onto your memory card. It takes the place of the PS2 dynasty it was built on, so delete that one "
        "from the card first if the tool says the save already exists."), parent=frm)


def current_saves_tab(frm, root, tk, ttk):
    import backups as B

    ttk.Label(frm, wraplength=520, justify="left", text=(
        "The saves the game uses now, in hdd beside MVP05.exe.")).grid(row=0, column=0, sticky="w", pady=(0, 8))
    tree = ttk.Treeview(frm, columns=("when", "size"), show="tree headings", height=12, selectmode="browse")
    tree.heading("#0", text="Save")
    tree.heading("when", text="Last saved")
    tree.heading("size", text="Size")
    tree.column("#0", width=330, anchor="w")
    tree.column("when", width=160, anchor="w")
    tree.column("size", width=80, anchor="e")
    tree.grid(row=1, column=0, sticky="we")
    frm.columnconfigure(0, weight=1)
    note = ttk.Label(frm, text="", foreground="#666")
    note.grid(row=3, column=0, sticky="w", pady=(6, 0))

    def refresh():
        tree.delete(*tree.get_children())
        saves = []
        for i, p in B.save_folders(os.path.join(root, "hdd")).items():
            files = [os.path.join(d, f) for d, _, fs in os.walk(p) for f in fs]
            when = max((os.path.getmtime(f) for f in files), default=os.path.getmtime(p))
            saves.append((B.save_name(p), when, sum(os.path.getsize(f) for f in files), p))
        folders.clear()
        for name, when, size, p in sorted(saves, key=lambda x: x[1], reverse=True):
            folders[tree.insert("", "end", text=name, values=(
                when_text(datetime.datetime.fromtimestamp(when)),
                f"{size / 2**20:.1f} MB" if size >= 2**20 else f"{max(1, size // 1024)} KB"))] = p
        note.configure(text="" if saves else "No saves yet: they appear here once you save in the game.")

    folders = {}
    right_click_menu(tree, lambda iid: [
        ("Open folder", lambda: open_in_explorer(folders[iid])),
        ("Export to GameCube\u2026",
         lambda: export_dynasty(frm, folders[iid], tree.item(iid, "text"), "GameCube", tk, ttk)),
        ("Export to PS2\u2026", lambda: export_dynasty(frm, folders[iid], tree.item(iid, "text"), "PS2", tk, ttk)),
        ("Export to PC\u2026", lambda: export_dynasty(frm, folders[iid], tree.item(iid, "text"), "PC", tk, ttk))])

    bar = ttk.Frame(frm)
    bar.grid(row=2, column=0, sticky="we", pady=(8, 0))
    ttk.Button(bar, text="Import a save\u2026", command=lambda: import_window(frm, root, tk, ttk, refresh)).pack(
        side="left")
    ttk.Button(bar, text="Open saves folder",
               command=lambda: open_in_explorer(os.path.join(root, "hdd", B.TITLE_UDATA))).pack(side="right")
    ttk.Button(bar, text="Refresh", command=refresh).pack(side="right", padx=6)
    import dragdrop
    if dragdrop.accept(frm, lambda paths: import_window(frm, root, tk, ttk, refresh, start=paths[0])):
        ttk.Label(bar, text="Or drag a save onto this tab.", foreground="#888").pack(side="left", padx=10)
    refresh()
    return refresh


def desktop_resolution():
    """The main screen's resolution in real pixels (not scaled by Windows' display scaling), or None."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        dc = u.GetDC(None)
        try:
            w, h = g.GetDeviceCaps(dc, 118), g.GetDeviceCaps(dc, 117)  # DESKTOPHORZRES, DESKTOPVERTRES
        finally:
            u.ReleaseDC(None, dc)
        return (w, h) if w > 0 and h > 0 else None
    except Exception:
        return None


# Game Tweaks, by group (Dynasty a page in the Tools tab, Graphics a window from Settings): (key in
# mvp05-settings.toml, title, explanation, {choice: value}) for a dropdown, or (key, None, text, None) for a
# checkbox. The first choice is the game's own (what an unset key means).
TWEAKS = {
    "Graphics": [
        ("player_full_detail", None, "More detail: umpires and fielders away from the play get the game's "
                                     "second-best player model, not its two simplest (test)", None),
        ("daylight_parks", None, "Daylight day games: day lighting and sky at Fenway, Turner Field and the other "
                                 "parks EA lit as dusk (test)", None),
        ("rain", "Rain",
         "The game has rain, but only at SBC Park (day and night) and at Safeco Field at night, as a shower in about "
         "2 games in 9. (test)",
         {"MVP 05 Default: showers at SBC Park and Safeco Field": 0,
          "Showers at every outdoor park, about 2 games in 9": 1,
          "Rain in every game, at every outdoor park": 2}),
        ("depth_of_field", None, "Depth of field: EA's background blur, turned off on the Xbox (test)", None),
        ("memory_mb", "Memory",
         "Room for what the game loads: stadiums, players, crowds. The Xbox had 64 MB, and the game keeps about 41 MB "
         "of it for these. Double it for mods that add more than the Xbox could hold.",
         {"MVP 05 Default (64 MB, 41 MB for the game)": 64,
          "Doubled (128 MB, 97 MB for the game): room for mods": 128}),
    ],
    # each list from the least to the most, MVP 05 Default where it falls
    "Dynasty": [
        ("pitcher_recovery", "Pitchers' rest",
         "How fast pitchers get their stamina back between games. By default, a starter is ready again two days after "
         "a full start and relievers are almost never tired.",
         {"Very slow (25%): starters ready after about 8 days": 25,
          "Slow (35%): starters ready after about 6 days": 35,
          "Five-man rotation (50%): starters ready after about 4 days": 50,
          "A little slower (75%): starters ready after about 3 days": 75,
          "MVP 05 Default (100%): starters ready after about 2 days": 100}),
        ("injury_length", "Injury length",
         "How long injured players stay out in a dynasty. By default, most injuries last a few days to a few weeks "
         "and the worst ones months. How often players get hurt is set by the game's own Injury sliders.",
         {"Much shorter (25%): a 20-day injury lasts 5 days": 25,
          "Shorter (50%): a 20-day injury lasts 10 days": 50,
          "A little shorter (75%): a 20-day injury lasts 15 days": 75,
          "MVP 05 Default (100%): a 20-day injury lasts 20 days": 100,
          "Longer (150%): a 20-day injury lasts 30 days": 150,
          "Much longer (200%): a 20-day injury lasts 40 days": 200,
          "Longest (300%): a 20-day injury lasts 60 days": 300}),
        ("dev_speed", "Player development",
         "The chance a player's ratings go up in the off-season, by his age and star level. By default, a "
         "25-year-old 3-star has a 60% chance, and 3-stars and better always go up until 23.",
         {"Much slower (50%): a 25-year-old 3-star, 30%": 50,
          "Slower (70%): a 25-year-old 3-star, 42%": 70,
          "A little slower (85%): a 25-year-old 3-star, 51%": 85,
          "MVP 05 Default (100%): a 25-year-old 3-star, 60%": 100,
          "A little faster (115%): a 25-year-old 3-star, 69%": 115,
          "Faster (130%): a 25-year-old 3-star, 78%": 130,
          "Much faster (150%): a 25-year-old 3-star, 90%": 150}),
        ("aging", "Aging",
         "The chance a player's ratings go down in the off-season, by his age and star level. By default, a "
         "34-year-old 3-star has a 50% chance, and a 37-year-old 80%.",
         {"Much gentler (50%): a 34-year-old 3-star, 25%": 50,
          "Gentler (70%): a 34-year-old 3-star, 35%": 70,
          "A little gentler (85%): a 34-year-old 3-star, 43%": 85,
          "MVP 05 Default (100%): a 34-year-old 3-star, 50%": 100,
          "A little harsher (115%): a 34-year-old 3-star, 58%": 115,
          "Harsher (130%): a 34-year-old 3-star, 65%": 130,
          "Much harsher (150%): a 34-year-old 3-star, 75%": 150}),
        ("retirement", "Retirement",
         "The chance a player retires in the off-season, by his age and star level. By default, a 37-year-old "
         "2-star has a 30% chance, stars never retire before 40, and everyone has retired by 45.",
         {"Much later (25%): a 37-year-old 2-star, 8%": 25,
          "Later (50%): a 37-year-old 2-star, 15%": 50,
          "A little later (75%): a 37-year-old 2-star, 23%": 75,
          "MVP 05 Default (100%): a 37-year-old 2-star, 30%": 100,
          "A little earlier (125%): a 37-year-old 2-star, 38%": 125,
          "Earlier (150%): a 37-year-old 2-star, 45%": 150,
          "Much earlier (200%): a 37-year-old 2-star, 60%": 200}),
        ("contract_prices", "Contract prices",
         "What players ask for in a new contract, free agents and your own players alike. By default, it comes "
         "from the player's ratings and what he's paid now.",
         {"Half (50%): a $4M asking price becomes $2M": 50,
          "Lower (75%): a $4M asking price becomes $3M": 75,
          "A little lower (90%): a $4M asking price becomes $3.6M": 90,
          "MVP 05 Default (100%): a $4M asking price stays $4M": 100,
          "A little higher (110%): a $4M asking price becomes $4.4M": 110,
          "Higher (125%): a $4M asking price becomes $5M": 125,
          "Much higher (150%): a $4M asking price becomes $6M": 150,
          "Double (200%): a $4M asking price becomes $8M": 200}),
        ("resign_chance", "Re-signing",
         "How often your own players agree to a new contract with you when theirs runs out. By default, an "
         "ordinary veteran agrees about half the time and a star almost every time. Each choice makes every "
         "player that much more or less likely to agree.",
         {"Much harder: a player who agreed 50% of the time agrees 20%": 70,
          "Harder: a player who agreed 50% of the time agrees 35%": 85,
          "MVP 05 Default: an ordinary veteran agrees 50% of the time": 100,
          "Easier: a player who agreed 50% of the time agrees 65%": 115,
          "Much easier: a player who agreed 50% of the time agrees 80%": 130}),
        ("rookie_quality", "Rookies",
         "The star levels of the rookies the game makes up each year. By default, 52% are 1-stars and 4% are "
         "5-stars.",
         {"Weaker: 62% 1-stars, 2% 5-stars": 3,
          "MVP 05 Default: 52% 1-stars, 4% 5-stars": 0,
          "Better: 40% 1-stars, 7% 5-stars": 1,
          "Much better: 30% 1-stars, 10% 5-stars": 2}),
    ],
}


def default_choice(choices):
    """The value of a setting's MVP 05 Default choice (the first, if none is named that)."""
    return next((v for k, v in choices.items() if k.startswith("MVP 05 Default")), list(choices.values())[0])


def tweak_controls(parent, items, saved, tk, ttk, row=0, width=58, about=None):
    """The controls for a list of TWEAKS items, from row on in parent's grid: checkboxes, or a title, an
    explanation and a dropdown. With about (a function taking a title and a text), a dropdown is one row, its title
    beside it, and its explanation goes to about when the pointer or the keyboard is on it. Returns (values, load,
    next row): values() gives {key: value} to save, load(saved) sets them again from the settings."""
    controls = []  # (key, var, choices or None)
    r = row
    for key, title, text, choices in items:
        if choices is not None and about:
            name = ttk.Label(parent, text=title)
            name.grid(row=r, column=0, sticky="w", pady=3)
            var = tk.StringVar()
            box = ttk.Combobox(parent, textvariable=var, state="readonly", width=width)
            box.grid(row=r, column=1, sticky="w", padx=(14, 0), pady=3)
            for w in (name, box):
                for event in ("<Enter>", "<FocusIn>", "<<ComboboxSelected>>"):
                    w.bind(event, lambda _, title=title, text=text: about(title, text), add="+")
            r += 1
            controls.append((key, var, (dict(choices), box)))
            continue
        if choices is None:
            var = tk.BooleanVar()
            ttk.Checkbutton(parent, text=text, variable=var).grid(row=r, column=0, columnspan=3, sticky="w", pady=2)
            r += 1
            controls.append((key, var, None))
            continue
        ttk.Label(parent, text=title, font=("Segoe UI", 9, "bold")).grid(row=r, column=0, columnspan=3, sticky="w",
                                                                       pady=(8 if r > row else 0, 0))
        ttk.Label(parent, wraplength=540, justify="left", text=text).grid(row=r + 1, column=0, columnspan=3,
                                                                          sticky="w", pady=(0, 3))
        var = tk.StringVar()
        box = ttk.Combobox(parent, textvariable=var, state="readonly", width=width)
        box.grid(row=r + 2, column=0, columnspan=3, sticky="w")
        r += 3
        controls.append((key, var, (dict(choices), box)))

    def load(saved):
        for key, var, c in controls:
            if c is None:
                var.set(saved.get(key, False) is True)
                continue
            choices, box = c
            first = default_choice(choices)
            v = saved.get(key, first)
            v = v if isinstance(v, int) and not isinstance(v, bool) else first
            name = next((k for k, x in choices.items() if x == v), None)
            if name is None:  # set by hand in the file
                name = f"Your own ({v})"
                choices[name] = v
            box.configure(values=list(choices))
            var.set(name)

    def values():
        return {key: (var.get() if c is None else c[0].get(var.get(), default_choice(c[0])))
                for key, var, c in controls}

    load(saved)
    return values, load, r


def adjustments_tool(group, heading, about):
    """A Tools page for one TWEAKS group, short enough to fit the Launcher: Save and Defaults at the top, one row a
    setting, and one place under them that explains the setting the pointer is on. Used at the game's next start."""
    def build(frm, root, tk, ttk):
        import settings as ST
        frm.columnconfigure(0, weight=1)
        head = ttk.Frame(frm)
        head.grid(row=0, column=0, sticky="we")
        ttk.Label(head, text=heading, font=("Segoe UI", 10, "bold")).pack(side="left")
        save_b = ttk.Button(head, text="Save")
        save_b.pack(side="right")
        default_b = ttk.Button(head, text="MVP 05 Default")
        default_b.pack(side="right", padx=6)
        note = ttk.Label(head, text="")
        note.pack(side="right", padx=6)
        ttk.Label(frm, foreground="#666", wraplength=600, justify="left", text=about + (
            " The game uses them the next time it starts.")).grid(row=1, column=0, sticky="w", pady=(2, 8))
        rows = ttk.Frame(frm)
        rows.grid(row=2, column=0, sticky="w")
        ttk.Separator(frm, orient="horizontal").grid(row=3, column=0, sticky="we", pady=(8, 6))
        what = ttk.Label(frm, text="", font=("Segoe UI", 9, "bold"))
        what.grid(row=4, column=0, sticky="w")
        # (tall enough for the longest explanation, so the page doesn't move as the pointer does)
        why_box = ttk.Frame(frm, height=52)
        why_box.grid(row=5, column=0, sticky="we")
        why_box.grid_propagate(False)
        why_box.columnconfigure(0, weight=1)
        why = ttk.Label(why_box, text="", foreground="#444", wraplength=600, justify="left")
        why.grid(row=0, column=0, sticky="nw")

        def explain(title=None, text=None):
            what.configure(text=title or "")
            why.configure(text=text or "Point at a setting to see what it does and what the game does by default.")

        values, load, _ = tweak_controls(rows, TWEAKS[group], ST.read(root), tk, ttk, width=56, about=explain)
        explain()

        def save():
            ST.write(root, values())
            note.configure(text="Saved. Restart the game if it's running.", foreground="#1a7f37")

        def defaults():
            load({})
            save()
            note.configure(text="Back to MVP 05 Default.", foreground="#1a7f37")

        save_b.configure(command=save)
        default_b.configure(command=defaults)
        return lambda: (load(ST.read(root)), note.configure(text=""), explain())
    return build


def graphics_window(parent, root, tk, ttk):
    """Graphics and memory (TWEAKS["Graphics"]), a window from the Settings tab. Used at the game's next start."""
    import settings as ST
    w = parent.winfo_toplevel()
    for c in w.winfo_children():  # one at a time
        if isinstance(c, tk.Toplevel) and getattr(c, "_graphics", False):
            c.lift()
            return
    win = tk.Toplevel(w)
    win._graphics = True
    win.title("Graphics and memory")
    win.transient(w)
    win.resizable(False, False)
    f = ttk.Frame(win, padding=14)
    f.grid()
    ttk.Label(f, text="Graphics and memory", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=3,
                                                                                sticky="w")
    ttk.Label(f, foreground="#666", wraplength=540, justify="left", text=(
        "Built into MVP05-Plus; your game files stay as they are. Changes take effect the next time the game "
        "starts.")).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))
    values, load, r = tweak_controls(f, TWEAKS["Graphics"], ST.read(root), tk, ttk, row=2)
    note = ttk.Label(f, text="", wraplength=540, justify="left")
    note.grid(row=r + 1, column=0, columnspan=3, sticky="w", pady=(6, 0))

    def save():
        ST.write(root, values())
        note.configure(text="Saved. Restart the game if it's running.", foreground="#1a7f37")

    def defaults():
        load({})
        save()
        note.configure(text="Back to MVP 05 Default. Restart the game if it's running.", foreground="#1a7f37")

    bar = ttk.Frame(f)
    bar.grid(row=r, column=0, columnspan=3, sticky="we", pady=(12, 0))
    ttk.Button(bar, text="Close", command=win.destroy).pack(side="right")
    ttk.Button(bar, text="Save", command=save).pack(side="right", padx=6)
    ttk.Button(bar, text="MVP 05 Default", command=defaults).pack(side="left")
    win.update_idletasks()  # centred over the Launcher
    x = w.winfo_rootx() + (w.winfo_width() - win.winfo_width()) // 2
    y = w.winfo_rooty() + (w.winfo_height() - win.winfo_height()) // 3
    win.geometry(f"+{max(x, 0)}+{max(y, 0)}")


def settings_tab(tabs, root, tk, ttk):
    """Display options in mvp05-settings.toml: the game reads them when it starts."""
    import settings as ST

    frm = ttk.Frame(tabs, padding=12)
    tabs.add(frm, text="Settings")
    ttk.Label(frm, text="Display", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(frm, foreground="#666", wraplength=600, justify="left", text=(
        "Saved in mvp05-settings.toml beside the game. Changes take effect the next time the game starts.")).grid(
        row=1, column=0, columnspan=3, sticky="w", pady=(0, 6))
    mode = tk.StringVar()
    aspect = tk.StringVar()
    res = tk.StringVar()
    scale = tk.StringVar()
    fps = tk.StringVar()
    aniso = tk.StringVar()
    vsync = tk.BooleanVar()
    low_latency = tk.BooleanVar()
    x720 = tk.BooleanVar()
    desk = desktop_resolution()
    # The game plays widescreen when the resolution is 3:2 or wider (app::Widescreen), else 4:3, with black bars at
    # the sides of a wider screen. So the aspect ratio is picked here and the resolutions follow it.
    WIDE, NARROW = "Widescreen (16:9)", "Standard (4:3)"
    current = f"Current desktop resolution ({desk[0]} x {desk[1]})" if desk else "Current desktop resolution"
    fit43 = f"Fit to your screen ({desk[1] * 4 // 3} x {desk[1]})" if desk else None
    lists = {WIDE: [current, "1280 x 720", "1600 x 900", "1920 x 1080", "2560 x 1440", "3840 x 2160"],
             NARROW: ([fit43] if fit43 else []) + ["640 x 480", "800 x 600", "1024 x 768", "1280 x 960", "1440 x 1080",
                                                   "1600 x 1200", "1920 x 1440", "2880 x 2160"]}
    fps_names = {"30": 30, "60 (default)": 60, "Unlimited": 0}
    aniso_names = {"Off (as on Xbox)": 0, "2x": 2, "4x": 4, "8x": 8, "16x": 16}
    res_box = ttk.Combobox(frm, textvariable=res, values=lists[WIDE], width=34)
    rows = [
        ("Display mode", ttk.Combobox(frm, textvariable=mode, values=["Windowed", "Borderless", "Fullscreen"],
                                      state="readonly", width=34)),
        ("Aspect ratio", ttk.Combobox(frm, textvariable=aspect, values=[WIDE, NARROW], state="readonly", width=34)),
        ("Resolution", res_box),
        ("Render scale (%)", ttk.Spinbox(frm, textvariable=scale, from_=25, to=200, increment=25, width=34)),
        ("Frame rate cap", ttk.Combobox(frm, textvariable=fps, values=list(fps_names), state="readonly", width=34)),
        ("Texture filtering", ttk.Combobox(frm, textvariable=aniso, values=list(aniso_names), state="readonly",
                                           width=34)),
    ]
    for i, (label, widget) in enumerate(rows):
        ttk.Label(frm, text=label).grid(row=2 + i, column=0, sticky="w", pady=2)
        widget.grid(row=2 + i, column=1, sticky="w", padx=(12, 0), pady=2)
    ttk.Label(frm, text="(or type your own, width x height)", foreground="#666").grid(
        row=4, column=2, sticky="w", padx=8)
    ttk.Checkbutton(frm, text="VSync", variable=vsync).grid(row=8, column=0, columnspan=2, sticky="w", pady=(6, 0))
    x720_box = ttk.Checkbutton(frm, text="Xbox 720p mode (as on an Xbox console with 720p enabled in the dashboard)",
                               variable=x720)
    x720_box.grid(row=9, column=0, columnspan=3, sticky="w")
    ttk.Checkbutton(frm, text="Low latency (1 frame queued for the screen, not 3: less input delay, may stutter)",
                    variable=low_latency).grid(row=10, column=0, columnspan=3, sticky="w")
    note = ttk.Label(frm, text="", wraplength=560, justify="left")
    note.grid(row=12, column=0, columnspan=3, sticky="w", pady=(6, 0))

    def name_of(d, v):
        return next((k for k, x in d.items() if x == v), str(v))

    def parse_res(text):
        """(w, h), (0, 0) for the desktop's own, or None."""
        if text.startswith("Current desktop"):
            return 0, 0
        if text.startswith("Fit to your screen"):
            text = text[text.index("(") + 1:text.index(")")]
        try:
            w, h = (int(x) for x in text.lower().replace("×", "x").split("x"))
        except ValueError:
            return None
        return (w, h) if 320 <= w <= 16384 and 240 <= h <= 16384 else None

    def is_wide(w, h):
        if not (w and h):
            w, h = desk or (16, 9)
        return w * 2 >= h * 3

    wide_720 = [True]  # 720p mode as it was in 16:9, for switching back

    def shape_changed(_=None):
        narrow = aspect.get() == NARROW
        res_box.configure(values=lists[aspect.get()])
        r = parse_res(res.get())
        if r is None or is_wide(*r) == narrow:  # the resolution isn't the new aspect ratio: the first that is
            res.set(lists[aspect.get()][0])
        # 720p mode is widescreen only: off (and greyed) in 4:3, back as it was in 16:9
        if narrow:
            if str(x720_box.cget("state")) != "disabled":
                wide_720[0] = x720.get()
            x720.set(False)
        else:
            x720.set(wide_720[0])
        x720_box.configure(state="disabled" if narrow else "normal")
        if narrow and mode.get() == "Fullscreen":
            mode.set("Borderless")
            note.configure(text="4:3 plays with black bars at the sides. Display mode is now Borderless: fullscreen "
                                "would switch your screen to a 4:3 mode, which many screens stretch.",
                           foreground="#8a5a00")
        elif not narrow:
            note.configure(text="")

    rows[1][1].bind("<<ComboboxSelected>>", shape_changed)

    def load():
        s = dict(ST.DEFAULTS)
        s.update(ST.read(root))
        mode.set(str(s["display_mode"]).capitalize())
        w, h = int(s.get("width") or 0), int(s.get("height") or 0)
        aspect.set(WIDE if is_wide(w, h) else NARROW)
        res_box.configure(values=lists[aspect.get()])
        if not (w and h):
            res.set(current)
        elif fit43 and desk and (w, h) == (desk[1] * 4 // 3, desk[1]):
            res.set(fit43)
        else:
            res.set(f"{w} x {h}")
        x720_box.configure(state="normal" if aspect.get() == WIDE else "disabled")
        scale.set(str(s["render_percent"]))
        fps.set(name_of(fps_names, s["fps_cap"]))
        aniso.set(name_of(aniso_names, s["anisotropic_filtering"]))
        vsync.set(bool(s["vsync"]))
        low_latency.set(bool(s.get("low_latency", False)))
        wide_720[0] = bool(s["xbox_720p"]) if aspect.get() == WIDE else True
        x720.set(wide_720[0] if aspect.get() == WIDE else False)

    def save():
        r = parse_res(res.get())
        try:
            sc = int(scale.get())
            assert r is not None and 10 <= sc <= 400
        except (ValueError, AssertionError):
            note.configure(text="The resolution is width x height (like 1920 x 1080), and the render scale a "
                                "percentage (100 is the resolution itself).", foreground="#a33")
            return
        w, h = r
        if is_wide(w, h) != (aspect.get() == WIDE):
            note.configure(text=f"{w} x {h} is {'widescreen' if is_wide(w, h) else '4:3'}: pick that aspect ratio, or "
                                f"another resolution.", foreground="#a33")
            return
        try:
            fp = fps_names[fps.get()] if fps.get() in fps_names else int(fps.get())
            an = aniso_names[aniso.get()] if aniso.get() in aniso_names else int(aniso.get().rstrip("x"))
        except ValueError:  # typed into the settings file by hand, and not a number
            note.configure(text="Pick a frame rate cap and a texture filtering level from their lists.",
                           foreground="#a33")
            return
        ST.write(root, {"display_mode": mode.get().lower(), "width": w, "height": h, "render_percent": sc,
                        "fps_cap": fp, "vsync": vsync.get(), "low_latency": low_latency.get(),
                        "anisotropic_filtering": an,
                        "xbox_720p": x720.get()})
        note.configure(text="Saved. Restart the game if it's running.", foreground="#1a7f37")

    def defaults():
        ST.write(root, dict(ST.DEFAULTS))
        load()
        note.configure(text="Back to the defaults (fullscreen at your desktop's resolution). Restart the game if it's running.",
                       foreground="#1a7f37")

    # desktop shortcuts, only when asked for
    import shortcuts as SC
    # shortcuts and updates side by side under the display settings
    lower = ttk.Frame(frm)
    lower.grid(row=13, column=0, columnspan=3, sticky="nwe", pady=(8, 0))
    lower.columnconfigure(0, weight=1)
    lower.columnconfigure(2, weight=1)
    scf = ttk.Frame(lower)
    scf.grid(row=0, column=0, sticky="nw")
    ttk.Separator(lower, orient="vertical").grid(row=0, column=1, sticky="ns", padx=14)
    upf = ttk.Frame(lower)
    upf.grid(row=0, column=2, sticky="nw")
    ttk.Label(scf, text="Desktop shortcuts", font=("Segoe UI", 10, "bold")).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
    sc_rows = [(SC.GAME_NAME, lambda: os.path.join(root, "MVP05.exe"), "the game"),
               (SC.TOOLS_NAME, SC.tools_exe, "this Launcher")]
    sc_buttons = {}

    def sc_refresh():
        for name, target, _ in sc_rows:
            b, lbl = sc_buttons[name]
            if os.name != "nt" or not target() or not os.path.isfile(target()):
                b.configure(text="Create", state="disabled")
                lbl.configure(text=f"{name}: " + ("Windows only" if os.name != "nt" else
                                                  "only from the Launcher's .exe" if not target() else
                                                  "MVP05.exe isn't here"), foreground="#777")
            elif SC.exists(name):
                b.configure(text="Remove", state="normal")
                lbl.configure(text=f"{name}: on your desktop", foreground="#1a7f37")
            else:
                b.configure(text="Create", state="normal")
                lbl.configure(text=f"{name}: not on your desktop", foreground="#555")

    def sc_toggle(name, target, what):
        try:
            if SC.exists(name):
                SC.remove(name)
            else:
                import title_icon
                SC.create(name, target(), os.path.join(root, title_icon.ICO),
                          f"Opens {what}")
        except OSError as e:
            note.configure(text=f"Couldn't change the shortcut: {e}", foreground="#a33")
        sc_refresh()

    for i, (name, target, what) in enumerate(sc_rows):
        b = ttk.Button(scf, width=8, command=lambda n=name, t=target, w_=what: sc_toggle(n, t, w_))
        b.grid(row=1 + i, column=0, sticky="w", pady=2)
        lbl = ttk.Label(scf)
        lbl.grid(row=1 + i, column=1, sticky="w", padx=(8, 0))
        sc_buttons[name] = (b, lbl)
    sc_refresh()
    updates_section(upf, root, tk, ttk, 0)

    bar = ttk.Frame(frm)
    bar.grid(row=11, column=0, columnspan=3, sticky="we", pady=(8, 0))
    ttk.Button(bar, text="Save", command=save).pack(side="right")
    ttk.Button(bar, text="Defaults", command=defaults).pack(side="right", padx=6)
    ttk.Button(bar, text="Open the settings file", command=lambda: os.startfile(os.path.join(root, ST.FILE))
               if os.name == "nt" else None).pack(side="left")
    ttk.Button(bar, text="Graphics and memory...", command=lambda: graphics_window(frm, root, tk, ttk)).pack(
        side="left", padx=6)
    load()


def schedule_tab(tabs, root, tk, ttk):
    """The season schedule the game uses: its own 162 games, MVP 2004's shorter ones, ones made for Plus, or one you
    imported from any version of MVP 2005."""
    import schedules as SCH
    import settings as ST
    from tkinter import messagebox

    frm = ttk.Frame(tabs, padding=12)
    tabs.add(frm, text="Schedule")
    ttk.Label(frm, text="Season Schedule", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
    ttk.Label(frm, foreground="#666", wraplength=560, justify="left", text=(
        "A new schedule starts with the next season, when spring training ends. A shorter season ends on its own and "
        "goes on to the playoffs.")).grid(
        row=1, column=0, sticky="w", pady=(0, 8))
    have = ttk.Label(frm, font=("Segoe UI", 9, "bold"))
    have.grid(row=2, column=0, sticky="w", pady=(0, 6))
    kinds = {"original": "default, MVP 2005 disc", "mvp2004": "from the MVP 2004 disc", "custom": "made for MVP05-Plus",
             "shuffled": "MVP 2005 disc", "imported": "imported by you", "made": "created by you"}
    cat, label, by_label = [], {}, {}
    pick = tk.StringVar()
    box = ttk.Combobox(frm, state="readonly", width=58)
    box.grid(row=3, column=0, sticky="w")

    def load_catalog():
        cat[:] = SCH.catalog(root)
        label.clear()
        label.update({e["id"]: f"{e['name']}  ({kinds.get(e['kind'], e['kind'])})" for e in cat})
        by_label.clear()
        by_label.update({v: k for k, v in label.items()})
        box.configure(values=[label[e["id"]] for e in cat])
    load_catalog()
    blurb = ttk.Label(frm, foreground="#555", wraplength=560, justify="left")
    blurb.grid(row=4, column=0, sticky="w", pady=(4, 0))

    def shown(*_):
        sid = by_label.get(box.get())
        e = next((x for x in cat if x["id"] == sid), None)
        pick.set(sid or "")
        # an imported schedule has no blurb: its name and "(imported by you)" say what it is
        blurb.configure(text=(e.get("short") or e.get("about", "")) if e and e.get("kind") != "imported" else "")
        remove.configure(state="normal" if e and e.get("kind") in ("imported", "made") else "disabled")
    box.bind("<<ComboboxSelected>>", shown)
    buttons = ttk.Frame(frm)
    buttons.grid(row=5, column=0, sticky="we", pady=(10, 0))
    use = ttk.Button(buttons, text="Use this schedule")
    use.pack(side="left")
    remove = ttk.Button(buttons, text="Remove", state="disabled")
    remove.pack(side="right")
    add = ttk.Button(buttons, text="Import a schedule\u2026")
    add.pack(side="right", padx=6)
    make = ttk.Button(buttons, text="Create a schedule\u2026")
    make.pack(side="right")
    ttk.Label(frm, foreground="#777", wraplength=560, justify="left", text=(
        "Create a schedule: any length, with your choice of interleague and All-Star host, a different season each "
        "dynasty year. Import a schedule: a schedule.big, or its mlb162_1/2/3.dat files, from any version of MVP 2005 "
        "(Xbox, PS2, GameCube or PC: the schedules are the same everywhere).")).grid(
        row=7, column=0, sticky="w", pady=(14, 0))
    note = ttk.Label(frm, wraplength=560, justify="left")
    note.grid(row=6, column=0, sticky="w", pady=(6, 0))

    def refresh(*_):
        now = SCH.current(root)
        names = {e["id"]: e["name"] for e in cat}
        if now:
            have.configure(text=f"Your game has: {names.get(now, now)}" +
                                (" (the original)" if now == SCH.ORIGINAL else ""))
            if not pick.get() and now in label:
                box.set(label[now])
                shown()
        elif SCH.find_big(root):
            have.configure(text="Your game has another schedule (changed outside the Launcher).")
        else:
            have.configure(text="Install the Xbox game first (the Play tab).")
    refresh()
    if not pick.get() and SCH.ORIGINAL in label:  # nothing installed yet: the game's own to start with
        box.set(label[SCH.ORIGINAL])
        shown()
    frm.bind("<Map>", refresh)

    def go():
        sid = pick.get()
        if not sid:
            return
        import updater
        if updater.game_running():
            note.configure(text="Quit MVP05 first: the game reads the schedule while it runs.", foreground="#a33")
            return
        try:
            games = SCH.apply(root, sid)
        except (SCH.ScheduleError, OSError) as e:
            note.configure(text=f"Not changed: {e}", foreground="#a33")
            return
        ST.write(root, {"season_games": games})  # the season's length: the game ends a short season by it
        note.configure(foreground="#1a7f37", text=(
            f"Done: new seasons play {games} games." + (" The Launcher deals a new shuffle every time it starts "
            "the game." if sid == SCH.SHUFFLED else "")))
        refresh()
    use.configure(command=go)

    def do_import():
        from tkinter import filedialog, simpledialog
        paths = filedialog.askopenfilenames(parent=frm, title="A schedule.big, or mlb162 .dat files", filetypes=[
            ("MVP 2005 schedules", "*.big *.dat"), ("All files", "*.*")])
        if not paths:
            return
        try:
            games = SCH.check_season(SCH.read_schedule_files(list(paths)))
        except (SCH.ScheduleError, OSError) as e:
            note.configure(text=f"Not imported: {e}", foreground="#a33")
            return
        name = simpledialog.askstring("Import a schedule", f"{games} games a team. A name for it:",
                                      initialvalue=f"{games} games", parent=frm)
        if not name:
            return
        try:
            e = SCH.import_schedule(root, list(paths), name)
        except (SCH.ScheduleError, OSError) as e:
            note.configure(text=f"Not imported: {e}", foreground="#a33")
            return
        load_catalog()
        box.set(label[e["id"]])
        shown()
        note.configure(text=f"Imported \"{e['name']}\". Use this schedule to put it in the game.",
                       foreground="#1a7f37")

    def do_remove():
        sid = pick.get()
        e = next((x for x in cat if x["id"] == sid), None)
        if not e or e.get("kind") not in ("imported", "made"):
            return
        if SCH.current(root) == sid:
            note.configure(text="That's the schedule your game has: use another one first, then remove it.",
                           foreground="#a33")
            return
        if not messagebox.askyesno("Remove the schedule", f"Remove \"{e['name']}\" from the list?", parent=frm):
            return
        SCH.remove_imported(root, sid)
        load_catalog()
        pick.set("")
        box.set(label[SCH.ORIGINAL])
        shown()
        note.configure(text=f"Removed \"{e['name']}\".", foreground="#555")
    add.configure(command=do_import)
    remove.configure(command=do_remove)

    def saved(e):
        load_catalog()
        box.set(label[e["id"]])
        shown()
        note.configure(text=f"Saved \"{e['name']}\". Use this schedule to put it in the game.", foreground="#1a7f37")
    make.configure(command=lambda: make_schedule(frm, root, tk, ttk, saved))


def make_schedule(parent, root, tk, ttk, on_saved):
    """Create a schedule (schedgen.py): the choices, the season it makes (team by team, year by year), and Save, which
    adds it to the Schedule tab's list as one of yours."""
    import random
    import schedgen as G
    import schedules as SCH

    win = tk.Toplevel(parent)
    win.title("Create a schedule")
    win.transient(parent.winfo_toplevel())
    win.resizable(False, False)
    f = ttk.Frame(win, padding=14)
    f.grid()
    o = G.default_options()
    state = {"seed": random.randrange(10**9), "texts": None, "opts": None, "job": None, "busy": 0}
    games = tk.StringVar(value=str(o["games"]))
    modes = {"real": "2005's matchups", "choose": "Choose the matchups", "rotate": "A new matchup each year",
             "off": "None"}
    hosts = {"alternate": "AL and NL take turns", "AL": "AL hosts", "NL": "NL hosts"}
    mode = tk.StringVar(value=modes["real"])
    host = tk.StringVar(value=hosts["alternate"])
    rivals = tk.BooleanVar(value=True)

    ttk.Label(f, text="Create a schedule", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=4,
                                                                             sticky="w")
    ttk.Label(f, foreground="#666", wraplength=520, justify="left", text=(
        "Every team plays the same number of games (an even number), exactly half of them at home, in 2 to 4-game "
        "series, with a different season for each of the three dynasty years. Regenerate makes another one with the "
        "same choices.")).grid(
        row=1, column=0, columnspan=4, sticky="w", pady=(0, 10))
    opts = ttk.Frame(f)
    opts.grid(row=2, column=0, columnspan=4, sticky="w")
    ttk.Label(opts, text="Games a team").grid(row=0, column=0, sticky="w")
    ttk.Spinbox(opts, from_=G.MIN_GAMES, to=G.MAX_GAMES, increment=2, textvariable=games, width=6).grid(
        row=0, column=1, sticky="w", padx=(6, 18))
    ttk.Label(opts, text="All-Star Game").grid(row=0, column=2, sticky="w")
    ttk.Combobox(opts, state="readonly", width=20, textvariable=host, values=list(hosts.values())).grid(
        row=0, column=3, sticky="w", padx=(6, 0))
    ttk.Label(opts, text="Interleague").grid(row=1, column=0, sticky="w", pady=(6, 0))
    ttk.Combobox(opts, state="readonly", width=24, textvariable=mode, values=list(modes.values())).grid(
        row=1, column=1, columnspan=2, sticky="w", padx=(6, 0), pady=(6, 0))
    ttk.Checkbutton(opts, text="Natural rivals every year", variable=rivals).grid(
        row=1, column=3, sticky="w", padx=(6, 0), pady=(6, 0))
    pair_row = ttk.Frame(opts)
    pv = {}
    for i, al in enumerate(G.AL):
        ttk.Label(pair_row, text=al + " vs").pack(side="left", padx=(0 if i == 0 else 10, 4))
        pv[al] = tk.StringVar(value=G.REAL_PAIRING[al])
        ttk.Combobox(pair_row, state="readonly", width=10, textvariable=pv[al], values=list(G.NL)).pack(side="left")

    # the season it makes
    view = ttk.Frame(f)
    view.grid(row=3, column=0, columnspan=4, sticky="we", pady=(12, 0))
    top = ttk.Frame(view)
    top.grid(row=0, column=0, sticky="w")
    team = tk.StringVar(value=G.NAMES["NYY"])
    year = tk.StringVar(value="Year 1")
    abbr = {v: k for k, v in G.NAMES.items()}
    ttk.Label(top, text="Team").pack(side="left")
    ttk.Combobox(top, state="readonly", width=22, values=sorted(G.NAMES.values()), textvariable=team).pack(
        side="left", padx=(6, 14))
    ttk.Label(top, text="Dynasty year").pack(side="left")
    ttk.Combobox(top, state="readonly", width=8, values=["Year 1", "Year 2", "Year 3"], textvariable=year).pack(
        side="left", padx=(6, 14))
    regen = ttk.Button(top, text="Regenerate")
    regen.pack(side="left")
    summary = ttk.Label(view, wraplength=520, justify="left")
    summary.grid(row=1, column=0, sticky="w", pady=(8, 6))
    tree = ttk.Treeview(view, columns=("date", "game", "half"), show="headings", height=11)
    for c, t, w in (("date", "Date", 120), ("game", "Game", 230), ("half", "Half", 150)):
        tree.heading(c, text=t)
        tree.column(c, width=w, anchor="w")
    tree.grid(row=2, column=0, sticky="we")
    sb = ttk.Scrollbar(view, orient="vertical", command=tree.yview)
    sb.grid(row=2, column=1, sticky="ns")
    tree.configure(yscrollcommand=sb.set)

    # name and save
    bottom = ttk.Frame(f)
    bottom.grid(row=4, column=0, columnspan=4, sticky="we", pady=(12, 0))
    ttk.Label(bottom, text="Name").pack(side="left")
    name = tk.StringVar()
    ttk.Entry(bottom, textvariable=name, width=34).pack(side="left", padx=(6, 10))
    save = ttk.Button(bottom, text="Save", state="disabled")
    save.pack(side="left")
    ttk.Button(bottom, text="Close", command=win.destroy).pack(side="right")
    msg = ttk.Label(f, wraplength=520, justify="left")
    msg.grid(row=5, column=0, columnspan=4, sticky="w", pady=(8, 0))

    def choices():
        try:
            n = int(games.get())
        except ValueError:
            n = 0
        if not G.MIN_GAMES <= n <= G.MAX_GAMES or n % 2:
            raise ValueError(f"games a team: an even number from {G.MIN_GAMES} to {G.MAX_GAMES}, so every team "
                             "plays exactly half at home")
        m = next(k for k, v in modes.items() if v == mode.get())
        pairing = {al: pv[al].get() for al in G.AL}
        if m == "choose" and sorted(pairing.values()) != sorted(G.NL):
            raise ValueError("give each AL division a different NL division")
        if m != "off" and n < G.MIN_INTERLEAGUE:
            raise ValueError(f"with interleague games, a season needs at least {G.MIN_INTERLEAGUE} games a team "
                             "(so every team plays some): pick more games, or None for interleague")
        return {"games": n, "interleague": m, "pairing": pairing, "rivals": bool(rivals.get()),
                "all_star": next(k for k, v in hosts.items() if v == host.get())}

    def describe(op):
        il = {"real": "2005's interleague matchups", "choose": "interleague " + ", ".join(
            f"{a} vs {op['pairing'][a]}" for a in G.AL), "rotate": "a new interleague matchup each year",
            "off": "no interleague"}[op["interleague"]]
        riv = ", natural rivals every year" if op["rivals"] and op["interleague"] != "off" else ""
        star = {"AL": "the AL hosts", "NL": "the NL hosts", "alternate": "the AL and NL take turns"}[op["all_star"]]
        return f"Created by you: {op['games']} games a team, {il}{riv}; at the All-Star Game {star}."

    def default_name(op):
        il = {"real": "", "choose": ", chosen interleague", "rotate": ", rotating interleague",
              "off": ", no interleague"}[op["interleague"]]
        return f"{op['games']} games{il}"

    def show(*_):
        texts, op = state["texts"], state["opts"]
        tree.delete(*tree.get_children())
        if not texts:
            return
        y = int(year.get().split()[-1])
        tm = abbr[team.get()]
        rows, c = G.team_view(texts[y - 1], tm)
        div = G.DIV[tm]
        pairing = G.pairing_for(op, y)
        il = ""
        if pairing:
            other = pairing.get(div) or next((a for a, n in pairing.items() if n == div), "")
            il = f" (the {other})"
        summary.configure(text=(
            f"{len(rows)} games: {c['home']} at home, {c['away']} away. {c['division']} against the {div}, "
            f"{c['league']} against the rest of the league, {c['interleague']} interleague{il}. "
            f"The All-Star Game: {G.host_for(op, y)} hosts."))
        star = [ln.split(",") for ln in texts[y - 1].decode("latin-1").splitlines() if ",-," in ln]
        if star:
            m, dd, yy = map(int, star[0][0].split("/"))
            rows = sorted(rows + [(datetime.date(yy, m, dd), "AL", True, "-")], key=lambda x: x[0])
        for d, opp, hm, half in rows:
            when = d.strftime("%a %b ") + str(d.day)
            if half == "-":
                tree.insert("", "end", values=(when, "All-Star Game", "break"))
            else:
                tree.insert("", "end", values=(when, ("vs " if hm else "at ") + G.NAMES.get(opp, opp),
                                               "first half" if half == "0" else "second half"))

    def make(*_):
        """The season for the choices now (in the background: a long one takes a moment)."""
        state["job"] = None
        try:
            op = choices()
        except ValueError as e:
            state["texts"] = None
            save.configure(state="disabled")
            summary.configure(text="")
            tree.delete(*tree.get_children())
            msg.configure(text=str(e), foreground="#a33")
            return
        state["busy"] += 1
        ticket = state["busy"]
        seed = state["seed"]
        msg.configure(text="Making the season\u2026", foreground="#555")
        save.configure(state="disabled")

        def work():
            try:
                texts, err = SCH.generate(op, seed), None
            except SCH.ScheduleError as e:
                texts, err = None, str(e)
            try:
                win.after(0, lambda: done(ticket, op, texts, err))
            except (tk.TclError, RuntimeError):
                pass  # the window was closed meanwhile
        threading.Thread(target=work, daemon=True).start()

    def done(ticket, op, texts, err):
        if ticket != state["busy"] or not win.winfo_exists():
            return  # the choices changed meanwhile: a newer one is on its way
        if err:
            state["texts"] = None
            msg.configure(text=f"Couldn't make that season: {err}", foreground="#a33")
            return
        old = state["opts"]
        state["texts"], state["opts"] = texts, op
        if not name.get().strip() or (old and name.get().strip() == default_name(old)):
            name.set(default_name(op))
        save.configure(state="normal")
        msg.configure(text="")
        show()

    def changed(*_):
        if mode.get() == modes["choose"]:
            pair_row.grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))
        else:
            pair_row.grid_remove()
        if state["job"]:
            win.after_cancel(state["job"])
        state["job"] = win.after(400, make)

    def regenerate():
        state["seed"] = random.randrange(10**9)
        make()

    def do_save():
        if not state["texts"]:
            return
        try:
            e = SCH.save_made(root, state["texts"], name.get(), state["opts"], state["seed"],
                              describe(state["opts"]))
        except (SCH.ScheduleError, OSError) as e:
            msg.configure(text=f"Not saved: {e}", foreground="#a33")
            return
        win.destroy()
        on_saved(e)

    for v in (games, mode, host, rivals, *pv.values()):
        v.trace_add("write", changed)
    team.trace_add("write", show)
    year.trace_add("write", show)
    regen.configure(command=regenerate)
    save.configure(command=do_save)
    make()


def _checkbox_images(tk):
    """A ticked and an empty checkbox (13 x 13), drawn, for the rows of a list."""
    imgs = []
    for ticked in (False, True):
        im = tk.PhotoImage(width=13, height=13)
        im.put("#ffffff", to=(0, 0, 13, 13))
        im.put("#333333", to=(0, 0, 13, 1)); im.put("#333333", to=(0, 12, 13, 13))
        im.put("#333333", to=(0, 0, 1, 13)); im.put("#333333", to=(12, 0, 13, 13))
        if ticked:  # a check mark
            for x, y in ((3, 6), (4, 7), (5, 8), (6, 7), (7, 6), (8, 5), (9, 4)):
                im.put("#111111", to=(x, y, x + 1, y + 2))
        imgs.append(im)
    return imgs


def mods_tab(tabs, root, tk, ttk):
    """Mods: a list of the mods (a checkbox, name, file types and size each), Add a mod and Open mods folder; a right
    click on a mod renames, opens, exports or removes it (mods.py)."""
    import mods as MD
    from tkinter import filedialog

    # laid out as the Saves tab is: a bold heading, a line about the list, the list, a bar of buttons, a note
    frm = ttk.Frame(tabs, padding=12)
    tabs.add(frm, text="Mods")
    frm.columnconfigure(0, weight=1)
    ttk.Label(frm, text="Mods", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 6))
    ttk.Label(frm, wraplength=520, justify="left", text=(
        "Tick a mod to use it: its files take the place of the game's files of the same name, the next time the "
        "game starts. Your game files stay as they are.")).grid(row=1, column=0, sticky="w", pady=(0, 8))

    box = ttk.Frame(frm)
    box.grid(row=2, column=0, sticky="we")
    box.columnconfigure(0, weight=1)
    tree = ttk.Treeview(box, columns=("types", "size"), show="tree headings", selectmode="browse", height=12)
    tree.heading("#0", text="Mod")
    tree.heading("types", text="File type")
    tree.heading("size", text="Size")
    tree.column("#0", width=330, anchor="w")
    tree.column("types", width=160, anchor="w")
    tree.column("size", width=80, anchor="e")
    sb = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.grid(row=0, column=0, sticky="we")
    boxes = _checkbox_images(tk)
    tree._boxes = boxes  # kept, or Tk drops the images

    bar = ttk.Frame(frm)
    bar.grid(row=3, column=0, sticky="we", pady=(8, 0))
    add_btn = ttk.Button(bar, text="Add a mod\u2026", command=lambda: add_menu())
    add_btn.pack(side="left")
    ttk.Button(bar, text="Open mods folder", command=lambda: open_folder(MD.mods_dir(root))).pack(side="right")
    hint = ttk.Label(bar, text="", foreground="#888")
    hint.pack(side="left", padx=10)
    note = ttk.Label(frm, text="", foreground="#666", wraplength=560, justify="left")
    note.grid(row=4, column=0, sticky="w", pady=(6, 0))
    items = []

    def say(text, colour="#1a7f37"):
        note.configure(text=text, foreground=colour)

    def refresh(select=None):
        keep = select or (items[selected()][0] if selected() is not None else None)
        items[:] = MD.read_list(root)
        tree.delete(*tree.get_children())
        for i, (name, on) in enumerate(items):
            types, size = MD.summary(root, name)
            iid = tree.insert("", "end", text="  " + name, image=boxes[on], values=(types, MD.size_text(size)))
            if name == keep:
                tree.selection_set(iid)
                tree.see(iid)
        if len(items) > 12:  # a scrollbar only when the list is longer than it shows
            sb.grid(row=0, column=1, sticky="ns")
        else:
            sb.grid_remove()
        if not items:
            say("No mods yet: add one, or put a mod's folder in the mods folder.", "#666")
        elif note.cget("text").startswith("No mods yet"):
            say("")
        lost = [f"{name}: {c} of its files come from {o} instead (added first)"
                for name, cl in MD.clashes(root, items).items() for o, c, wins in cl if not wins]
        if lost:
            say("\n".join(lost), "#8a5a00")

    def selected():
        sel = tree.selection()
        return tree.index(sel[0]) if sel else None

    def set_on(i, on):
        items[i] = (items[i][0], on)
        try:
            MD.write_list(root, items)
        except OSError as e:
            say(f"Couldn't save the mod list: {e}", "#a33")
            return
        say("")
        refresh(items[i][0])
        if not note.cget("text"):
            say(f"{items[i][0]} {'on' if on else 'off'}. Restart the game if it's running.")

    def click(event):
        row = tree.identify_row(event.y)
        if row and tree.identify_column(event.x) == "#0" and (
                "image" in str(tree.identify_element(event.x, event.y)).lower() or event.x < 40):
            i = tree.index(row)
            set_on(i, not items[i][1])
            return "break"

    def space(_):
        i = selected()
        if i is not None:
            set_on(i, not items[i][1])
        return "break"

    tree.bind("<Button-1>", click)
    tree.bind("<space>", space)
    def double(event):  # on a name (not its checkbox): rename
        row = tree.identify_row(event.y)
        if row and event.x >= 40:
            rename(tree.index(row))

    tree.bind("<Double-1>", double)

    def open_folder(path):
        os.makedirs(path, exist_ok=True)
        if os.name == "nt":
            os.startfile(path)

    def context(event):
        row = tree.identify_row(event.y)
        if not row:
            return
        tree.selection_set(row)
        i = tree.index(row)
        name, on = items[i]
        m = tk.Menu(frm, tearoff=0)
        m.add_command(label="Turn off" if on else "Turn on", command=lambda: set_on(i, not on))
        m.add_separator()
        m.add_command(label="Rename\u2026", command=lambda: rename(i))
        m.add_command(label="Open folder", command=lambda: open_folder(os.path.join(MD.mods_dir(root), name)))
        m.add_command(label="Export as zip\u2026", command=lambda: export(i))
        m.add_separator()
        m.add_command(label="Remove\u2026", command=lambda: remove(i))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    tree.bind("<Button-3>", context)

    def add_menu():
        m = tk.Menu(frm, tearoff=0)
        m.add_command(label="From a folder\u2026", command=lambda: add(pick_folder))
        m.add_command(label="From files or a zip\u2026", command=lambda: add(pick_files))
        m.tk_popup(add_btn.winfo_rootx(), add_btn.winfo_rooty() + add_btn.winfo_height())

    def ask_name(title, start, current=None):
        """The name typed in a small window (start in it, all selected); None if cancelled."""
        w = frm.winfo_toplevel()
        win = tk.Toplevel(w)
        win.title(title)
        win.transient(w)
        win.resizable(False, False)
        f = ttk.Frame(win, padding=14)
        f.grid()
        ttk.Label(f, text="Name").grid(row=0, column=0, sticky="w")
        var = tk.StringVar(value=start)
        entry = ttk.Entry(f, textvariable=var, width=44)
        entry.grid(row=1, column=0, columnspan=2, sticky="we", pady=(2, 0))
        err = ttk.Label(f, text="", foreground="#a33", wraplength=320, justify="left")
        err.grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        result = []

        def ok(_=None):
            problem = MD.name_problem(root, var.get(), current)
            if problem:
                err.configure(text=problem)
                return
            result.append(var.get().strip())
            win.destroy()

        bar_ = ttk.Frame(f)
        bar_.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(bar_, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(bar_, text="OK", command=ok).pack(side="right", padx=6)
        entry.bind("<Return>", ok)
        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        win.geometry(f"+{w.winfo_rootx() + (w.winfo_width() - win.winfo_width()) // 2}"
                     f"+{w.winfo_rooty() + (w.winfo_height() - win.winfo_height()) // 3}")
        entry.focus_set()
        entry.select_range(0, "end")
        win.grab_set()
        win.wait_window()
        return result[0] if result else None

    def rename(i):
        old = items[i][0]
        new = ask_name("Rename the mod", old, current=old)
        if new is None or new == old:
            return
        problem = MD.rename(root, old, new)
        if problem:
            say(problem, "#a33")
            return
        refresh(new)
        say(f"Renamed {old} to {new}.")

    def export(i):
        name = items[i][0]
        dest = filedialog.asksaveasfilename(title="Export " + name, parent=frm, initialfile=name + ".zip",
                                            defaultextension=".zip", filetypes=[("Zip", "*.zip")])
        if not dest:
            return
        try:
            n = MD.export_zip(root, name, dest)
        except OSError as e:
            say(f"Couldn't export {name}: {e}", "#a33")
            return
        say(f"Exported {name} ({n} file{'s' if n != 1 else ''}) to {dest}.")

    def remove(i):
        name = items[i][0]
        from tkinter import messagebox
        if messagebox.askyesno("Remove the mod?", f"Remove {name}? Your game files aren't touched.", parent=frm):
            MD.remove(root, name)
            refresh()
            say(f"Removed {name}.")

    def pick_places(planned):
        """{path in the mod: [game paths]} for the files the game has in several places; None if cancelled."""
        picks = [(p, t) for p, st, t in planned if st == "pick"]
        if not picks:
            return {}
        w = frm.winfo_toplevel()
        win = tk.Toplevel(w)
        win.title("Where do these files go?")
        win.transient(w)
        win.grab_set()
        f = ttk.Frame(win, padding=14)
        f.grid()
        ttk.Label(f, wraplength=560, justify="left", text=(
            "The game has each of these files in more than one place. Pick where the mod's file goes.")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        rows, result = [], {}
        for i, (path, targets) in enumerate(picks[:40]):
            ttk.Label(f, text=path, wraplength=250, justify="left").grid(row=1 + i, column=0, sticky="w", pady=2)
            choices = [f"All {len(targets)} places"] + targets + ["Leave it out"]
            var = tk.StringVar(value=choices[0])
            ttk.Combobox(f, textvariable=var, values=choices, state="readonly", width=44).grid(
                row=1 + i, column=1, sticky="w", padx=(10, 0), pady=2)
            rows.append((path, targets, var))
        if len(picks) > 40:
            ttk.Label(f, foreground="#666", text=f"The other {len(picks) - 40} go in every place.").grid(
                row=42, column=0, columnspan=2, sticky="w")

        def ok():
            for path, targets in picks:
                result[path] = targets
            for path, targets, var in rows:
                v = var.get()
                result[path] = targets if v.startswith("All ") else [] if v == "Leave it out" else [v]
            win.destroy()

        bar = ttk.Frame(f)
        bar.grid(row=43, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(bar, text="Add the mod", command=ok).pack(side="right", padx=6)
        win.wait_window()
        return result if result else None

    def add(pick):
        assets = MD.Assets(root)
        if not assets:
            say("Install the game first (the Install tab): a mod's files are matched to the game's.", "#a33")
            return
        chosen = pick()
        if not chosen:
            return
        try:
            src = (MD.from_folder(chosen[0]) if os.path.isdir(chosen[0]) else
                   MD.from_zip(chosen[0]) if len(chosen) == 1 and chosen[0].lower().endswith(".zip") else
                   MD.from_files(list(chosen)))
        except Exception as e:  # a damaged zip, say
            say(f"Couldn't read that: {e}", "#a33")
            return
        try:
            planned = MD.plan(assets, src)
            if not any(st != "unknown" for _, st, _ in planned):
                say("None of those are game files, so there's nothing to add.", "#a33")
                return
            info = MD.source_info(src)
            start = info.get("title") or MD.suggested_name(list(chosen))
            name = ask_name("Name the mod", MD.unique_name(root, start) if MD.name_problem(root, start) else start)
            if name is None:
                return
            picks = pick_places(planned)
            if picks is None:
                say("Nothing added.", "#555")
                return
            say("Adding...", "#555")
            frm.update_idletasks()
            name, n = MD.install(root, src, planned, picks, name, info)
        except OSError as e:
            say(f"Couldn't add the mod: {e}", "#a33")
            return
        finally:
            src.close()
        left = [p for p, st, _ in planned if st == "unknown"]
        new = [t[0] for _, st, t in planned if st == "new"]
        say("")
        refresh(name)
        if not name:
            say("Nothing added.", "#555")
            return
        files = f"{n} file{'s' if n != 1 else ''}"
        if left or new:
            say(f"Added {name} ({files}), on, with {len(left) + len(new)} to look at. Restart the game if it's "
                "running.", "#8a5a00")
            import_report(name, files, left, new)
        elif not note.cget("text"):
            say(f"Added {name} ({files}), on. Restart the game if it's running.")

    def import_report(name, files, left, new):
        """After an import that wasn't all straight matches: every file left out, and every new one."""
        w = frm.winfo_toplevel()
        win = tk.Toplevel(w)
        win.title("Imported " + name)
        win.transient(w)
        f = ttk.Frame(win, padding=14)
        f.grid(sticky="nsew")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)
        parts = []
        if left:
            parts.append(f"{len(left)} left out")
        if new:
            parts.append(f"{len(new)} new")
        ttk.Label(f, text=f"{name}: {files} imported, {' and '.join(parts)}.",
                  font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        text = tk.Text(f, width=78, height=min(18, 4 + len(left) + len(new) + (3 if left and new else 0)),
                       wrap="word", relief="solid", borderwidth=1, padx=8, pady=6, font=("Segoe UI", 9))
        sb = ttk.Scrollbar(f, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=sb.set)
        text.grid(row=1, column=0, sticky="nsew")
        sb.grid(row=1, column=1, sticky="ns")
        text.tag_configure("head", font=("Segoe UI", 9, "bold"))
        text.tag_configure("why", foreground="#555")
        if left:
            text.insert("end", "Left out\n", "head")
            text.insert("end", "The game has no file with these names, so they weren't imported. A readme or a "
                               "picture is fine to leave out. If one should be a game file, its name may be "
                               "misspelled.\n", "why")
            for p in left:
                text.insert("end", "    " + p + "\n")
        if new:
            text.insert("end", ("\n" if left else "") + "New files\n", "head")
            text.insert("end", "These are in the game's folders, but the game has no file of that name there. "
                               "They were imported, but the game only uses one if another file asks for it. If "
                               "one should replace a game file, its name or folder may be wrong.\n", "why")
            for p in new:
                text.insert("end", "    " + p + "\n")
        text.configure(state="disabled")
        ttk.Button(f, text="OK", command=win.destroy).grid(row=2, column=0, columnspan=2, sticky="e", pady=(10, 0))
        win.bind("<Return>", lambda e: win.destroy())
        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        win.geometry(f"+{w.winfo_rootx() + (w.winfo_width() - win.winfo_width()) // 2}"
                     f"+{w.winfo_rooty() + (w.winfo_height() - win.winfo_height()) // 4}")
        win.grab_set()

    def pick_folder():
        p = filedialog.askdirectory(title="The mod's folder", parent=frm)
        return [p] if p else None

    def pick_files():
        ps = filedialog.askopenfilenames(title="The mod's files (or its zip)", parent=frm)
        return list(ps) if ps else None

    def dropped(paths):
        """Dragged onto the tab: each folder and each zip a mod of its own, loose files one mod together."""
        whole = [p for p in paths if os.path.isdir(p) or p.lower().endswith(".zip")]
        loose = [p for p in paths if p not in whole and os.path.isfile(p)]
        for group in [[p] for p in whole] + ([loose] if loose else []):
            add(lambda group=group: group)

    import dragdrop
    if dragdrop.accept(frm, dropped):
        hint.configure(text="Or drag a mod's folder, its zip or its files onto this tab.")
    refresh()


def tools_tab(tabs, root, tk, ttk):
    """Tools: a list of them, each opening on its own page here, with a way back to the list."""
    outer = ttk.Frame(tabs, padding=12)
    tabs.add(outer, text="Tools")
    outer.columnconfigure(0, weight=1)
    home = ttk.Frame(outer)
    home.columnconfigure(0, weight=1)
    ttk.Label(home, text="Tools", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
    ttk.Label(home, foreground="#666", wraplength=560, justify="left", text=(
        "Pick a tool to open it. The first three are in the game too: F10, or hold Back + Start (Z + Start on a "
        "GameCube controller).")).grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))
    tools = [
        ("Team Changer", "Take over another organization in your dynasty or owner mode. Based on tywiggins' Team "
         "Changer.", team_changer_tool),
        ("Playoffs Editor", "Swap teams in a playoff round before its first game. Based on tywiggins' Playoffs "
         "Creator.", playoffs_tool),
        ("Standings Projector", "Every team's record projected to 162 games, keeping its winning percentage. Short "
         "seasons don't need it: they end on their own.", short_season_tool),
        ("Dynasty adjustments", "Pitchers' rest, injury length, player development, aging, retirement, contract "
         "prices, re-signing and rookies. Set here, used the next time the game starts.",
         adjustments_tool("Dynasty", "Dynasty adjustments",
                          "Changes to how a dynasty runs, built into MVP05-Plus. Your game files stay as they "
                          "are.")),
    ]
    pages = {}

    def open_tool(i):
        name, _, build = tools[i]
        if i not in pages:
            page = ttk.Frame(outer)
            page.columnconfigure(0, weight=1)
            ttk.Button(page, text="\u2039 All tools", command=show_home).grid(row=0, column=0, sticky="w",
                                                                           pady=(0, 8))
            body = ttk.Frame(page)
            body.grid(row=1, column=0, sticky="nwe")
            pages[i] = (page, build(body, root, tk, ttk))
        home.grid_remove()
        for j, (pg, _) in pages.items():
            if j != i:
                pg.grid_remove()
        page, refresh = pages[i]
        page.grid(row=0, column=0, sticky="nwe")
        if refresh:
            refresh()

    def show_home():
        for pg, _ in pages.values():
            pg.grid_remove()
        home.grid(row=0, column=0, sticky="nwe")

    for i, (name, about, _) in enumerate(tools):
        r = 2 + i * 2
        ttk.Separator(home).grid(row=r, column=0, columnspan=2, sticky="we")
        box = ttk.Frame(home, padding=(0, 5))
        box.grid(row=r + 1, column=0, sticky="we")
        ttk.Label(box, text=name, font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(box, text=about, foreground="#555", wraplength=470, justify="left").grid(row=1, column=0,
                                                                                         sticky="w")
        ttk.Button(home, text="Open", command=lambda i=i: open_tool(i)).grid(row=r + 1, column=1, sticky="e",
                                                                           padx=(12, 0))
    ttk.Separator(home).grid(row=2 + len(tools) * 2, column=0, columnspan=2, sticky="we")
    show_home()


def team_changer_tool(frm, root, tk, ttk):
    """Team Changer (tywiggins'): the organization the dynasty's player controls, changed in the running game."""
    import team_changer as TC

    ttk.Label(frm, text="Team Changer", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(frm, foreground="#666", wraplength=540, justify="left", text=(
        "Take over another organization in your dynasty or owner mode. With the game running and the save loaded: find "
        "it here, pick the organization, and take control. Then save in the game to keep it. The same tool is in "
        "the game's Tools menu (F10).")).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 10))
    find_b = ttk.Button(frm, text="Find the save")
    find_b.grid(row=2, column=0, sticky="w")
    now = ttk.Label(frm, text="")
    now.grid(row=2, column=1, columnspan=2, sticky="w", padx=10)
    box = ttk.Combobox(frm, state="disabled", width=24, values=list(TC.ORGS))
    box.grid(row=3, column=0, sticky="w", pady=(10, 0))
    take = ttk.Button(frm, text="Take control", state="disabled")
    take.grid(row=3, column=1, sticky="w", padx=10, pady=(10, 0))
    note = ttk.Label(frm, wraplength=540, justify="left")
    note.grid(row=4, column=0, columnspan=3, sticky="w", pady=(10, 0))
    ttk.Label(frm, foreground="#888", text="Based on tywiggins' MVP 2005 Team Changer.").grid(
        row=5, column=0, columnspan=3, sticky="w", pady=(16, 0))
    found = {}

    def say(text, colour="#555"):
        note.configure(text=text, foreground=colour)

    def look():
        found.clear()
        take.configure(state="disabled")
        box.configure(state="disabled")
        try:
            h, addr, org = TC.find()
        except TC.TeamError as e:
            now.configure(text="")
            return say(f"{e}.", "#a33")
        import ctypes
        ctypes.windll.kernel32.CloseHandle(h)
        found.update(addr=addr, org=org)
        now.configure(text=f"You control: the {TC.ORGS[org]}")
        box.configure(state="readonly")
        box.current(org)
        say("")
        pick()

    def pick(*_):
        take.configure(state="normal" if found and box.current() >= 0 and box.current() != found["org"] else "disabled")

    def go():
        org = box.current()
        try:
            h, addr, cur = TC.find()
            TC.change(h, addr, org)
        except TC.TeamError as e:
            return say(f"Not changed: {e}.", "#a33")
        found.update(addr=addr, org=org)
        now.configure(text=f"You control: the {TC.ORGS[org]}")
        pick()
        say(f"Done: you control the {TC.ORGS[org]}. Save the dynasty in the game to keep it.", "#1a7f37")

    find_b.configure(command=look)
    take.configure(command=go)
    box.bind("<<ComboboxSelected>>", pick)
    return None


def playoffs_tool(frm, root, tk, ttk):
    """Playoffs Editor (from tywiggins' Playoffs Creator): the teams of a playoff round, swapped before its first game, in the running game
    or a dynasty save."""
    import playoffs05 as PO
    import saves05 as S
    from tkinter import messagebox

    ttk.Label(frm, text="Playoffs Editor", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=4,
                                                                                sticky="w")
    ttk.Label(frm, foreground="#666", wraplength=560, justify="left", text=(
        "Choose who plays in the playoffs. When a playoff round has started (before its first game), find it here, "
        "pick a new organization for any team, and change them. Each series keeps its dates and home field. Then save "
        "the dynasty in the game. The same tool is in the game's Tools menu (F10).")).grid(
        row=1, column=0, columnspan=4, sticky="w", pady=(0, 8))
    how = tk.StringVar(value="game")
    ttk.Radiobutton(frm, variable=how, value="game", text="In the running game").grid(row=2, column=0, columnspan=4,
                                                                                       sticky="w")
    ttk.Radiobutton(frm, variable=how, value="save", text="In a saved dynasty, with the game closed:").grid(
        row=3, column=0, columnspan=2, sticky="w")
    save_box = ttk.Combobox(frm, state="readonly", width=34)
    save_box.grid(row=3, column=2, columnspan=2, sticky="w", padx=(6, 0))
    find_b = ttk.Button(frm, text="Find the playoffs")
    find_b.grid(row=4, column=0, sticky="w", pady=(8, 4))
    grid = ttk.Frame(frm)
    grid.grid(row=5, column=0, columnspan=4, sticky="w")
    note = ttk.Label(frm, wraplength=560, justify="left")
    note.grid(row=6, column=0, columnspan=4, sticky="w", pady=4)
    change_b = ttk.Button(frm, text="Change the teams", state="disabled")
    change_b.grid(row=7, column=0, sticky="w")
    ttk.Label(frm, foreground="#888", text="Based on tywiggins' MVP 2005 Playoffs Creator.").grid(
        row=8, column=0, columnspan=4, sticky="w", pady=(16, 0))
    state, saves, boxes = {}, [], []

    def say(text, colour="#555"):
        note.configure(text=text, foreground=colour)

    def load_saves(*_):
        saves[:] = [x for x in S.list_saves(root) if x["type"] == "Dynasty"]
        save_box.configure(values=[f"{x['name']} ({when_text(x['when'])})" for x in saves])
        if saves and save_box.current() < 0:
            save_box.current(0)
        if not saves:
            save_box.set("(no dynasty saves yet)")

    def show(ss):
        for w in grid.winfo_children():
            w.destroy()
        boxes.clear()
        for i, srs in enumerate(ss):
            ttk.Label(grid, text=f"Series {i + 1}:").grid(row=i, column=0, sticky="w", pady=2)
            for j, t in enumerate((srs["home"], srs["away"])):
                b = ttk.Combobox(grid, state="readonly", width=16, values=list(PO.ORGS))
                b.current(PO.IDS.index(t))
                b.grid(row=i, column=1 + 2 * j, padx=(8, 0), pady=2)
                b.bind("<<ComboboxSelected>>", ready)
                boxes.append((t, b))
            ttk.Label(grid, text="(home first)" if i == 0 else "", foreground="#888").grid(row=i, column=4, padx=8)
            ttk.Label(grid, text="vs").grid(row=i, column=2, padx=(8, 0))

    def changes():
        return {t: PO.IDS[b.current()] for t, b in boxes if PO.IDS[b.current()] != t}

    def ready(*_):
        change_b.configure(state="normal" if state and changes() else "disabled")

    def find():
        state.clear()
        show([])
        ready()
        try:
            if how.get() == "save":
                if not saves or save_box.current() < 0:
                    return say("No dynasty save to choose: save one in the game first.", "#a33")
                x = saves[save_box.current()]
                with open(os.path.join(x["folder"], "data.dat"), "rb") as f:
                    ss = PO.read_save(f.read())
                state.update(kind="save", save=x)
            else:
                h, addr, ss = PO.find()
                import ctypes
                ctypes.windll.kernel32.CloseHandle(h)
                state.update(kind="game")
        except (OSError, PO.PlayoffsError) as e:
            return say(f"{e}.", "#a33")
        show(ss)
        say(f"This round: {len(ss)} series, {sum(x['games'] for x in ss)} games. Pick new teams, then change them.")

    def go():
        ch = changes()
        try:
            if state.get("kind") == "save":
                x = state["save"]
                if S.game_running():
                    raise PO.PlayoffsError("close MVP05.exe first: the game keeps its saves open while it runs")
                dat = os.path.join(x["folder"], "data.dat")
                with open(dat, "rb") as f:
                    out = PO.write_save(f.read(), ch)
                S.backup_folder(root, x["folder"], "changing the playoff teams")
                with open(dat + ".new", "wb") as f:
                    f.write(out)
                os.replace(dat + ".new", dat)
                load_saves()
                done = f"Done: load \"{x['name']}\" in the game. The old save is in Saves > Backups."
            else:
                h, addr, _ = PO.find()
                PO.change(h, addr, ch)
                done = "Done. Save the dynasty in the game to keep it."
        except (OSError, PO.PlayoffsError) as e:
            return say(f"Not changed: {e}.", "#a33")
        names = ", ".join(f"the {PO.name(new)} in place of the {PO.name(old)}" for old, new in ch.items())
        say(f"The playoffs have {names}. {done}", "#1a7f37")
        state.clear()
        ready()

    find_b.configure(command=find)
    change_b.configure(command=go)
    how.trace_add("write", lambda *_: (state.clear(), show([]), ready(), say("")))
    return load_saves


def short_season_tool(frm, root, tk, ttk):
    """Standings Projector: every MLB team's record projected to 162 games, in the running game or in a dynasty save.
    The game's own Tools menu (F10) does the first in the game. Short seasons end on their own now (hooks.cpp)."""
    import saves05 as S
    import settings as ST
    from tkinter import messagebox

    ttk.Label(frm, text="Standings Projector", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(frm, foreground="#666", wraplength=560, justify="left", text=(
        "Every team's record projected to 162 games, keeping its winning percentage. Short seasons don't need it: "
        "they end on their own and go on to the playoffs. It's for a dynasty that's stuck at the end of a short "
        "season from an older MVP05-Plus. In the game, F10 (or Back + Start) opens the same tool.")).grid(
        row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))
    how = tk.StringVar(value="game")
    ttk.Radiobutton(frm, variable=how, value="game", text=(
        "In the running game (save the dynasty after the last regular season game, stay on that screen)")).grid(
        row=2, column=0, columnspan=3, sticky="w")
    ttk.Radiobutton(frm, variable=how, value="save", text=(
        "In a saved dynasty, with the game closed:")).grid(row=3, column=0, sticky="w")
    save_box = ttk.Combobox(frm, state="readonly", width=34)
    save_box.grid(row=3, column=1, columnspan=2, sticky="w", padx=(6, 0))
    row = ttk.Frame(frm)
    row.grid(row=4, column=0, columnspan=3, sticky="w", pady=6)
    ttk.Label(row, text="Games in the season:").pack(side="left")
    games = tk.StringVar(value=str(ST.read(root).get("season_games", 162)))
    ttk.Spinbox(row, textvariable=games, from_=1, to=162, width=6).pack(side="left", padx=6)
    ttk.Label(row, foreground="#666", text="(starts as your Schedule tab's; a saved dynasty's is read from it)").pack(
        side="left")
    tree = ttk.Treeview(frm, columns=("t", "now", "full"), show="headings", height=8)
    for c, t, wd in (("t", "Team", 90), ("now", "Now", 110), ("full", "162 games", 110)):
        tree.heading(c, text=t)
        tree.column(c, width=wd, anchor="center")
    tree.grid(row=5, column=0, columnspan=3, sticky="w", pady=(4, 0))
    tree.grid_remove()  # shown once there are standings to show
    note = ttk.Label(frm, wraplength=560, justify="left")
    note.grid(row=6, column=0, columnspan=3, sticky="w", pady=4)
    buttons = ttk.Frame(frm)
    buttons.grid(row=7, column=0, columnspan=3, sticky="e")
    find_b = ttk.Button(buttons, text="Find the standings")
    write_b = ttk.Button(buttons, text="Write them, 162 games long", state="disabled")
    find_b.pack(side="left")
    write_b.pack(side="left", padx=6)
    state, saves = {}, []

    def say(text, colour="#555"):
        frm.after(0, lambda: note.configure(text=text, foreground=colour))

    def load_saves(*_):
        saves[:] = [s for s in S.list_saves(root) if s["type"] == "Dynasty"]
        save_box.configure(values=[f"{s['name']} ({when_text(s['when'])})" for s in saves])
        if saves and save_box.current() < 0:
            save_box.current(0)
        if not saves:
            save_box.set("(no dynasty saves yet)")
    load_saves()

    def forget():
        if state.get("kind") == "game":
            import standings_mem as M
            M.close(state["h"])
        state.clear()
        write_b.configure(state="disabled")

    def show(records):
        tree.delete(*tree.get_children())
        if records:
            tree.grid()
        else:
            tree.grid_remove()
        for t, wn, ls in records:
            pw, pl = S.project(wn, ls)
            tree.insert("", "end", values=(t, f"{wn}-{ls}", f"{pw}-{pl}"))

    def season_games():
        try:
            n = int(games.get())
        except ValueError:
            n = 0
        if not 1 <= n <= 162:
            messagebox.showinfo("Standings Projector", "Enter how many games the season has (1 to 162).", parent=frm)
            return None
        return n

    def find():
        forget()
        if how.get() == "save":
            if not saves or save_box.current() < 0:
                return say("No dynasty save to choose: save one in the game first.", "#a33")
            s = saves[save_box.current()]
            try:
                r = S.read_standings(s["folder"])
            except Exception as e:
                show([])
                return say(f"Stopped: {e}", "#a33")
            if r["season"]:
                games.set(str(r["season"]))
            left = r["scheduled"] - r["played"] if r["scheduled"] else None
            show(r["records"])
            if left:
                say(f"{r['name']}: {left} of the season's games aren't played yet. Write this after the last one.",
                    "#a33")
            else:
                say(f"{r['name']}" + (f": a {r['season']}-game season, all played." if r["season"] else ".") +
                    " Check the records, then write them.")
            state.update(kind="save", save=s)
            write_b.configure(state="normal")
            return
        n = season_games()
        if not n:
            return
        find_b.configure(state="disabled")
        say(f"Looking for {n}-game standings in the running game...")

        def work():
            import standings_mem as M
            try:
                h, addr, fmt, recs = M.find(n, root, lambda t: say(t))
            except Exception as e:
                frm.after(0, lambda: (show([]), find_b.configure(state="normal")))
                return say(f"Stopped: {e}", "#a33")

            def done():
                state.update(kind="game", h=h, addr=addr, fmt=fmt, n=n)
                show([(t, a, b) for t, (a, b) in zip(S.MLB_TEAMS, recs)])
                say("Found in the running game. Check the records, then write them.")
                find_b.configure(state="normal")
                write_b.configure(state="normal")
            frm.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    def write():
        kind = state.get("kind")
        try:
            if kind == "save":
                S.patch_standings(root, state["save"]["folder"], say=lambda t: say(t, "#1a7f37"))
                load_saves()
            elif kind == "game":
                import standings_mem as M
                ok = M.apply(state["h"], state["addr"], state["fmt"], state["n"])
                state.clear()
                say("Written. In the game: advance to the playoffs, then save the dynasty." if ok else
                    "Couldn't write to the game's memory: try opening the Launcher as administrator.",
                    "#1a7f37" if ok else "#a33")
        except Exception as e:
            say(f"Stopped: {e}", "#a33")
        forget()

    find_b.configure(command=find)
    write_b.configure(command=write)
    how.trace_add("write", lambda *_: (forget(), show([]), say("")))
    def opened():  # each time the tool is opened: the dynasty list, and the schedule's length as it is now
        games.set(str(ST.read(root).get("season_games", 162)))
        load_saves()
    return opened


def updates_section(frm, root, tk, ttk, row):
    """Settings tab: this version, Check for updates, the check at start, and undoing the last update."""
    import updater
    ttk.Label(frm, text="Updates", font=("Segoe UI", 10, "bold")).grid(row=row, column=0, columnspan=3, sticky="w",
                                                                      pady=(0, 4))
    line = ttk.Frame(frm)
    line.grid(row=row + 1, column=0, columnspan=3, sticky="w")
    status = ttk.Label(frm, foreground="#555", wraplength=260, justify="left")
    status.grid(row=row + 3, column=0, columnspan=3, sticky="w", pady=(4, 0))
    auto = tk.BooleanVar(value=launcher_option(root, "check_updates", True))
    ttk.Label(line, text=f"This is {VERSION}.").pack(side="left")
    ttk.Button(line, text="Check now",
               command=lambda: check_for_update(frm.winfo_toplevel(), root, tk, ttk, status=status)).pack(
        side="left", padx=(12, 0))
    ttk.Checkbutton(frm, text="Check when the Launcher opens", variable=auto,
                    command=lambda: set_launcher_option(root, "check_updates", auto.get())).grid(
        row=row + 2, column=0, columnspan=3, sticky="w", pady=(4, 0))
    last = updater.last_update(root)
    if last:
        def do_undo():
            from tkinter import messagebox
            if not messagebox.askyesno("Undo the update", f"Go back to {GAME} {last['from']}?\n\n"
                                       "Your game files, saves and settings stay as they are.", parent=frm):
                return
            try:
                back = updater.undo(root)
            except updater.UpdateError as e:
                status.configure(text=f"Couldn't undo it: {e}", foreground="#a33")
                return
            messagebox.showinfo("Undo the update", f"Back to {GAME} {back}. The Launcher restarts now.", parent=frm)
            updater.restart(pretend=back)
            frm.winfo_toplevel().destroy()
        ttk.Button(line, text=f"Back to {last['from']}", command=do_undo).pack(side="left", padx=(6, 0))


def check_for_update(w, root, tk, ttk, quiet=False, status=None):
    """Asks GitHub in the background; a newer release opens the update window. quiet: say nothing otherwise."""
    import updater

    def say(text, colour="#555"):
        if status is not None:
            w.after(0, lambda: status.configure(text=text, foreground=colour))

    def work():
        try:
            info = updater.check(VERSION)
        except updater.UpdateError as e:
            if not quiet:
                say(f"Couldn't check: {e}", "#a33")
            return
        if info:
            say(f"{GAME} {info['version']} is out.", "#1a7f37")
            w.after(0, lambda: update_window(w, root, tk, ttk, info))
        elif not quiet:
            say(f"{VERSION} is the latest.", "#1a7f37")

    say("Checking...")
    threading.Thread(target=work, daemon=True).start()


def update_window(w, root, tk, ttk, info):
    """What's new in the release, and Update now: download, check, install, restart."""
    import updater
    import webbrowser
    win = tk.Toplevel(w)
    win.title(f"{GAME} {info['version']}")
    win.transient(w)
    win.resizable(False, False)
    f = ttk.Frame(win, padding=14)
    f.grid()
    ttk.Label(f, text=f"{GAME} {info['version']} is out", font=("Segoe UI", 12, "bold")).grid(row=0, column=0,
                                                                                           columnspan=3, sticky="w")
    ttk.Label(f, foreground="#555", text=f"You have {VERSION}. Your game files, saves, backups, button art and "
              "settings stay as they are.", wraplength=520, justify="left").grid(row=1, column=0, columnspan=3,
                                                                                sticky="w", pady=(2, 8))
    notes = tk.Text(f, width=72, height=14, wrap="word", relief="solid", borderwidth=1, font=("Segoe UI", 9))
    import re
    text = "\n".join(re.sub(r"^\s*[-*] ", "\u2022 ", re.sub(r"^#+\s*", "", line)).replace("**", "")
                     for line in info["notes"].strip().splitlines())
    notes.insert("1.0", text or "(no notes)")
    notes.configure(state="disabled")
    notes.grid(row=2, column=0, columnspan=3, sticky="we")
    bar = ttk.Progressbar(f, length=520, mode="determinate", maximum=1.0)
    bar.grid(row=3, column=0, columnspan=3, sticky="we", pady=(10, 2))
    note = ttk.Label(f, foreground="#555", wraplength=520, justify="left")
    note.grid(row=4, column=0, columnspan=3, sticky="w")
    buttons = ttk.Frame(f)
    buttons.grid(row=5, column=0, columnspan=3, sticky="e", pady=(10, 0))
    go = ttk.Button(buttons, text="Update now")
    later = ttk.Button(buttons, text="Later", command=win.destroy)
    ttk.Button(buttons, text="See it on GitHub", command=lambda: webbrowser.open(info["page"])).pack(side="left")
    later.pack(side="right")
    go.pack(side="right", padx=6)

    def say(text, colour="#555"):
        win.after(0, lambda: note.configure(text=text, foreground=colour))

    def work():
        try:
            mb = info["size"] / 2**20 if info.get("size") else 0
            say(f"Downloading {info['name']}" + (f" ({mb:.0f} MB)..." if mb else "..."))
            z = updater.download(root, info, lambda d, t: win.after(0, lambda: bar.configure(
                value=min(d / t, 1.0) * 0.9 if t else 0)))
            say("Checking the download...")
            files = updater.verify(z)
            say("Installing...")
            updater.apply(root, files, VERSION)
            win.after(0, lambda: bar.configure(value=1.0))
        except updater.UpdateError as e:
            say(f"Not updated: {e}", "#a33")
            win.after(0, lambda: (go.configure(state="normal"), later.configure(state="normal")))
            return
        say(f"Updated to {info['version']}. The Launcher restarts now.", "#1a7f37")
        win.after(1500, lambda: (updater.restart(), w.destroy()))

    def start():
        if updater.game_running():
            note.configure(text="MVP05 is running: quit the game first, then Update now.", foreground="#a33")
            return
        go.configure(state="disabled")
        later.configure(state="disabled")
        threading.Thread(target=work, daemon=True).start()
    go.configure(command=start)


def backups_tab(frm, root, tk, ttk, refresh_current):
    from tkinter import messagebox
    import backups as B
    import settings as ST

    ttk.Label(frm, wraplength=520, justify="left", text=(
        "A backup is made each time the game starts. Open a date and pick the save to restore. Click the date to "
        "restore every save from that date.")).grid(
        row=1, column=0, sticky="w", pady=(0, 8))
    tree = ttk.Treeview(frm, columns=("state",), show="tree headings", height=10, selectmode="extended")
    tree.heading("#0", text="Backed up / save")
    tree.heading("state", text="Compared to current saves")
    tree.column("#0", width=370, anchor="w")
    tree.column("state", width=200, anchor="w")
    tree.grid(row=2, column=0, sticky="we")
    frm.columnconfigure(0, weight=1)
    empty = ttk.Label(frm, foreground="#666")
    empty.grid(row=4, column=0, sticky="w", pady=(6, 0))
    out = tk.Text(frm, width=10, height=3, state="disabled", wrap="word", relief="flat", background="#f4f4f4")
    out.grid(row=5, column=0, sticky="we", pady=(6, 0))
    out.grid_remove()  # shown once a restore has something to say
    rows = {}

    def say(t):
        out.grid()
        out.configure(state="normal")
        out.insert("end", t + "\n")
        out.see("end")
        out.configure(state="disabled")

    def refresh():
        tree.delete(*tree.get_children())
        rows.clear()
        for b in B.list_backups(root):
            when = when_text(b["when"]) + (" (before restore)" if "before restore" in b["name"] else "")
            n = len(b["items"])
            parent = tree.insert("", "end", text=when, values=(f"{n} save{'s' if n != 1 else ''}",))
            rows[parent] = ("backup", b, None)
            for s in b["items"]:
                iid = tree.insert(parent, "end", text=s["name"], values=(s["state"],))
                rows[iid] = ("save", b, s)
        empty.configure(text="" if rows else "No backups yet: the game makes one when it starts, once you have "
                                              "saves.")

    def do_restore():
        sel = [rows[i] for i in tree.selection()]
        if not sel:
            messagebox.showinfo("Save backups", "Pick a date, or saves under one, first.")
            return
        backups_picked = {id(b): b for _, b, _ in sel}
        if len(backups_picked) > 1:
            messagebox.showinfo("Save backups", "Pick saves from one date at a time.")
            return
        b = sel[0][1]
        whole = any(kind == "backup" for kind, _, _ in sel)
        picked = b["items"] if whole else [s for kind, _, s in sel if kind == "save"]
        when = when_text(b["when"])
        names = "\n".join("   •  " + s["name"] for s in picked) or "   (no saves)"
        if whole:
            what = (f"Restore all saves from {when}?\n\n{names}\n\nThis replaces all your current saves. They're "
                    f"backed up to the save backups folder first.")
        else:
            what = (f"Restore from {when}?\n\n{names}\n\nYour current saves are backed up to the save backups "
                    f"folder first.")
        if not messagebox.askyesno("Restore saves?", what):
            return
        try:
            B.restore(root, b["path"], say=say, ids=None if whole else [s["id"] for s in picked])
        except B.BackupError as e:
            say(f"Stopped: {e}")
        except Exception as e:
            say(f"Something went wrong: {e}")
        refresh()
        refresh_current()

    keep = tk.StringVar(value=str(ST.read(root).get("save_backups", 30)))
    choices = ["0", "15", "30", "50", "100", "250", "1000"]
    if keep.get() not in choices:  # a number set by hand in the settings file stays in the list
        choices = sorted(choices + [keep.get()], key=lambda x: int(x) if x.isdigit() else 0)

    def save_keep(*_):
        n = int(keep.get())
        if ST.read(root).get("save_backups") != n:
            ST.write(root, {"save_backups": n})

    bar = ttk.Frame(frm)
    bar.grid(row=3, column=0, sticky="we", pady=(8, 0))
    ttk.Button(bar, text="Restore…", command=do_restore).pack(side="left")

    def backup_menu(iid):
        kind, b, sv = rows[iid]
        return [("Restore…", do_restore), ("Open folder", lambda: open_in_explorer(sv["path"] if sv else b["path"]))]
    right_click_menu(tree, backup_menu)
    ttk.Label(bar, text="Keep").pack(side="left", padx=(16, 4))
    kb = ttk.Combobox(bar, textvariable=keep, values=choices, state="readonly", width=6)
    kb.pack(side="left")
    kb.bind("<<ComboboxSelected>>", save_keep)
    ttk.Label(bar, text="backups").pack(side="left", padx=(4, 0))
    ttk.Button(bar, text="Open backups folder",
               command=lambda: open_in_explorer(os.path.join(root, "save backups"))).pack(side="right")
    ttk.Button(bar, text="Refresh", command=refresh).pack(side="right", padx=6)
    refresh()
    return refresh


def main():
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--xbox")
    a.add_argument("--gamecube")
    a.add_argument("--ps2")
    a.add_argument("--dir", default=game_dir())
    o = a.parse_args()
    if not (o.xbox or o.gamecube or o.ps2):
        return gui(o.dir)
    try:
        run(o.dir, o.xbox, o.gamecube, o.ps2)
    except discs.DiscError as e:
        raise SystemExit(f"stopped: {e}")


if __name__ == "__main__":
    main()
