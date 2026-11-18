"""The Launcher's Import a save window and its Export, driven with stand-in widgets (no window is drawn) on a folder
of sample saves: every import goes into a save of the same kind, every export saves a file, and a save of the wrong
kind is refused with a message.

    python tools/installer/tests/test_save_windows.py <samples folder>

The samples folder is the one tools/saves/tests/test_converters.py takes (its header lists the names).
"""
import os
import shutil
import sys
import tempfile
from unittest.mock import MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
if len(sys.argv) < 2:
    sys.exit(__doc__)
SAMPLES = os.path.abspath(sys.argv[1])
for n in ("tkinter", "tkinter.ttk", "tkinter.filedialog", "tkinter.messagebox", "tkinter.font"):
    sys.modules[n] = MagicMock()
sys.path[:0] = [os.path.join(REPO, "tools", "installer"), os.path.join(REPO, "tools", "saves"),
                os.path.join(REPO, "tools", "saves", "tests")]
import install  # noqa: E402
import saves05 as S5  # noqa: E402
from made_cards import gc_card  # noqa: E402

S5.game_running = lambda: False


def sample(n):
    p = os.path.join(SAMPLES, n)
    return p if os.path.isfile(p) else None


work = tempfile.mkdtemp()
root = os.path.join(work, "game")
U = os.path.join(root, "hdd", "E", "UDATA", "45410056")
folders = {}
for k, folder in (("xb_dyn.dat", "8D58821E7335"), ("xb_own.dat", "56865A2A6946"), ("xb_roster.dat", "5410A74FEB1B")):
    if sample(k):
        os.makedirs(os.path.join(U, folder))
        shutil.copy(sample(k), os.path.join(U, folder, "data.dat"))
        folders[k] = os.path.join(U, folder)
gcis = [sample(n) for n in ("gc_roster.gci", "gc_dyn.gci", "gc_own.gci")]
card = None
if all(gcis):
    card = os.path.join(work, "MemoryCardA.USA.raw")
    with open(card, "wb") as f:
        f.write(gc_card([open(g, "rb").read() for g in gcis]))

packed = None
if sample("gc_dyn.gci") and sample("xb_dyn.dat"):  # saves as people share them: in a zip, an Xbox save as its folder
    import zipfile
    packed = os.path.join(work, "shared saves.zip")
    with zipfile.ZipFile(packed, "w") as z:
        z.write(sample("gc_dyn.gci"), "MVP05/69-GV4E-Dynasty_STROS.dat.gci")
        z.write(sample("xb_dyn.dat"), "MVP05/UDATA/45410056/8D58821E7335/data.dat")
        z.writestr("readme.txt", "my dynasty")
loose = None
if sample("ps2_roster.psu"):
    loose = os.path.join(work, "a folder")
    os.makedirs(os.path.join(loose, "inner"))
    shutil.copy(sample("ps2_roster.psu"), os.path.join(loose, "inner", "rosters.psu"))


class Inline:
    def __init__(self, target=None, daemon=None, **_):
        self.t = target

    def start(self):
        self.t()


install.threading = MagicMock()
install.threading.Thread = Inline
install.choose_card_save = lambda frm, tk, ttk, found, *_: found[0]
mb = sys.modules["tkinter"].messagebox
fd = sys.modules["tkinter"].filedialog
BAD = []

# imports: (what, file, whether it should import)
imports = [(n, sample(n), not n.startswith(("mvp06", "README"))) for n in sorted(os.listdir(SAMPLES))
           if not n.startswith(("xb_", "database", "feeng", "logos"))] + [("an Xbox save's folder", folders.get("xb_dyn.dat"), True),
                                          ("Dolphin card", card, True), ("a zip of saves", packed, True),
                                          ("a folder with a save in it", loose, True),
                                          ("not a save", os.path.join(REPO, "README.md"), False),
                                          ("a folder with no save", os.path.join(REPO, "docs"), False)]
# and as new saves (the last choice in the list), named here
for n in ("gc_dyn.gci", "ps2_own.psu", "pc_roster.sav"):
    if sample(n):
        imports.append((f"{n} as a new save", sample(n), "new"))
sys.modules["tkinter"].simpledialog.askstring.side_effect = lambda *a, **k: k.get("initialvalue") or "NEW"
for what, path, ok in imports:
    if not path:
        continue
    mb.reset_mock()
    mb.askyesno.return_value = mb.askokcancel.return_value = True
    texts = []
    tk, ttk = MagicMock(), MagicMock()
    lab = MagicMock()
    lab.configure = lambda **k: texts.append(k["text"]) if k.get("text") else None
    ttk.Label.return_value = lab
    box = MagicMock()
    box.current.return_value = 0
    ttk.Combobox.return_value = box
    frm = MagicMock()
    frm.after = lambda ms, fn: fn()
    r = install.import_tool(frm, root, tk, ttk)
    r.use(path)
    picked = ([t for t in texts if "can't be used" in t or "✓" in t] or ["?"])[-1]
    offered = [c.kwargs.get("values") for c in box.configure.call_args_list if "values" in c.kwargs]
    offered = offered[-1] if offered else []
    result = ""
    if offered and "can't" not in picked:
        if ok == "new":
            box.current.return_value = len(offered) - 1
        go = [c.kwargs["command"] for c in ttk.Button.return_value.configure.call_args_list if "command" in c.kwargs][1]
        go()
        res = [t for t in texts if t.startswith(("Done", "Nothing"))]
        result = res[-1] if res else "no result"
    good = result.startswith("Done") if ok else ("can't be used" in picked)
    if ok == "new":
        made = [x for x in S5.list_saves(root) if f'"{x["name"]}"' in result]
        good = good and len(made) == 1 and os.path.basename(made[0]["folder"]) == S5.folder_id(
            made[0]["name"], made[0]["type"]) and S5.savemeta_name(made[0]["folder"]).startswith(made[0]["name"])
        result += f" [{made[0]['name']} ({made[0]['type']}) in {os.path.basename(made[0]['folder'])}]" if made else ""
    print(f"{'ok ' if good else 'BAD'} import {what:24} | {picked[:70]} | {result[:60]}")
    if not good:
        BAD.append(what)

# exports: (save kind, console, base file, whether it should save)
exports = [("xb_dyn.dat", "GameCube", sample("gc_dyn.gci"), True), ("xb_dyn.dat", "PS2", sample("ps2_dyn.psu"), True),
           ("xb_dyn.dat", "PC", sample("pc_dyn.sav"), True), ("xb_own.dat", "GameCube", sample("gc_own.gci"), True),
           ("xb_own.dat", "PS2", sample("ps2_own.psu"), True), ("xb_own.dat", "PC", sample("pc_own.sav"), True),
           ("xb_roster.dat", "GameCube", sample("gc_roster.gci"), True),
           ("xb_roster.dat", "PS2", sample("ps2_roster.psu"), True),
           ("xb_roster.dat", "PS2", sample("ps2_card.ps2"), True), ("xb_roster.dat", "PC", sample("pc_roster.sav"), True),
           ("xb_dyn.dat", "GameCube", card, True), ("xb_own.dat", "GameCube", card, True),
           ("xb_roster.dat", "GameCube", card, True),
           ("xb_roster.dat", "GameCube", sample("gc_own.gci"), False), ("xb_dyn.dat", "PS2", sample("ps2_card.ps2"), False),
           ("xb_own.dat", "PC", sample("pc_dyn.sav"), False)]
for i, (k, to, base, ok) in enumerate(exports):
    if not base or k not in folders:
        continue
    mb.reset_mock()
    mb.askokcancel.return_value = mb.askyesno.return_value = True
    fd.askopenfilename.return_value = base
    dest = os.path.join(work, f"out{i}")
    fd.asksaveasfilename.return_value = dest
    install.export_dynasty(MagicMock(), folders[k], k, to, MagicMock(), MagicMock())
    shown = [c.args[1] for f in ("showinfo", "showerror") for c in getattr(mb, f).call_args_list]
    said = shown[-1].splitlines()[0] if shown else "nothing shown"
    good = (said.startswith("Saved") and os.path.isfile(dest)) if ok else not os.path.isfile(dest)
    print(f"{'ok ' if good else 'BAD'} export {k[3:-4]:6} to {to:8} on {os.path.basename(base)[:24]:24} | {said[:80]}")
    if not good:
        BAD.append(f"export {k} to {to} on {os.path.basename(base)}")

# Dolphin's own cards, as its settings have them: Slot A a GCI folder (its default), Slot B a .raw card. An export
# built on the folder's dynasty goes into that folder under a name of its own (a second one under the next name);
# one built on the .raw card's rosters gives a copy of the card.
if sample("gc_dyn.gci") and "xb_dyn.dat" in folders:
    import dynasty05 as DY
    import gccard as GCC
    dol = os.path.join(work, "Dolphin Emulator")
    gcd = os.path.join(dol, "GC")
    cardA = os.path.join(gcd, "USA", "Card A")
    os.makedirs(cardA)
    os.makedirs(os.path.join(dol, "Config"))
    shutil.copy(sample("gc_dyn.gci"), os.path.join(cardA, "01-GV4E-dynasty.gci"))
    if card:
        shutil.copy(card, os.path.join(gcd, "MemoryCardB.USA.raw"))
    with open(os.path.join(dol, "Config", "Dolphin.ini"), "w") as f:
        f.write("[Core]\nSlotA = 8\nSlotB = 1\n")
    real = install.emulator_dirs
    install.emulator_dirs = lambda to: [gcd] if to == "GameCube" else []
    cards = install.dolphin_cards()
    good = [c[1] for c in cards] == ["folder", "raw"] if card else [c[1] for c in cards] == ["folder"]
    print(f"{'ok ' if good else 'BAD'} Dolphin's cards from its settings | {[(c[0], os.path.basename(c[2])) for c in cards]}")
    if not good:
        BAD.append("Dolphin's cards")
    names = []
    for n in range(2):
        mb.reset_mock()
        mb.askokcancel.return_value = mb.askyesno.return_value = True
        fd.askopenfilename.reset_mock()
        install.export_dynasty(MagicMock(), folders["xb_dyn.dat"], "xb_dyn.dat", "GameCube", MagicMock(), MagicMock())
        shown = [c.args[1] for f in ("showinfo", "showerror") for c in getattr(mb, f).call_args_list]
        names.append(shown[-1].splitlines()[0] if shown else "nothing shown")
    inside = sorted(os.listdir(cardA))
    own = []
    for x in inside:
        with open(os.path.join(cardA, x), "rb") as fh:
            g = fh.read()
        own.append(g[8:0x28].split(b"\0")[0].decode())
        DY.read_gc(g)
    good = (len(inside) == 3 and len(set(own)) == 3 and not fd.askopenfilename.called
            and all(x.startswith("Saved") for x in names))
    print(f"{'ok ' if good else 'BAD'} export into Dolphin's GCI folder, twice | {own} | {names[-1][:60]}")
    if not good:
        BAD.append("export into Dolphin's GCI folder")
    if card:  # the rosters are only on the .raw card
        mb.reset_mock()
        mb.askokcancel.return_value = mb.askyesno.return_value = True
        dest = os.path.join(work, "dolphin-card-out.raw")
        fd.asksaveasfilename.return_value = dest
        install.export_dynasty(MagicMock(), folders["xb_roster.dat"], "xb_roster.dat", "GameCube", MagicMock(), MagicMock())
        good = os.path.isfile(dest) and GCC.is_card(open(dest, "rb").read())
        print(f"{'ok ' if good else 'BAD'} export rosters onto Dolphin's .raw card (Slot B) | {os.path.basename(dest)}")
        if not good:
            BAD.append("export onto Dolphin's .raw card")
    install.emulator_dirs = real

# copy and rename (right-click in Saves)
if "xb_dyn.dat" in folders:
    names = iter(["COPIED", "RENAMED"])
    sys.modules["tkinter"].simpledialog.askstring.side_effect = lambda *a, **k: next(names)
    install.copy_or_rename(MagicMock(), root, folders["xb_dyn.dat"], False, lambda: None)
    copied = [x for x in S5.list_saves(root) if x["name"] == "COPIED"]
    install.copy_or_rename(MagicMock(), root, copied[0]["folder"] if copied else folders["xb_dyn.dat"], True,
                           lambda: None)
    have = {x["name"]: os.path.basename(x["folder"]) for x in S5.list_saves(root)}
    good = "COPIED" not in have and have.get("RENAMED") == S5.folder_id("RENAMED", "Dynasty") and "KCRTEST" in have
    print(f"{'ok ' if good else 'BAD'} copy a save, then rename the copy | {sorted(have)}")
    if not good:
        BAD.append("copy and rename")

# the save library: four dynasties fill the game; a fifth goes back only in exchange for one of them
if "xb_dyn.dat" in folders:
    src = os.path.join(work, "dynasty.dat")
    shutil.copy(sample("xb_dyn.dat"), src)
    for x in S5.in_game(root, "Dynasty"):  # (the steps above left some): the game starts with none
        S5.put_away(root, x["folder"])
    for n in ("LIBA", "LIBB", "LIBC", "LIBD"):
        S5.new_save(root, work, open(src, "rb").read(), n)
    have = lambda: sorted(x["name"] for x in S5.in_game(root, "Dynasty"))
    four = have()
    install.set_active(MagicMock(), root, [x for x in S5.list_saves(root) if x["name"] == "LIBA"][0]["folder"], False,
                       MagicMock(), MagicMock(), lambda: None)  # unticked
    S5.new_save(root, work, open(src, "rb").read(), "LIBE")
    lib = [x for x in S5.list_library(root) if x["name"] == "LIBA"][0]["folder"]
    install.choose_one = lambda frm, tk, ttk, title, text, options: [i for i, o in enumerate(options)
                                                                     if o.startswith("LIBE")][0]
    install.set_active(MagicMock(), root, lib, True, MagicMock(), MagicMock(), lambda: None)  # ticked: swaps LIBE out
    now, put = have(), [x["name"] for x in S5.list_library(root)]
    good = four == ["LIBA", "LIBB", "LIBC", "LIBD"] and "LIBA" in now and "LIBE" not in now and "LIBE" in put
    print(f"{'ok ' if good else 'BAD'} checkbox: untick a dynasty, tick it again with 4 in | game {now}, library {put}")
    if not good:
        BAD.append("save library")

shutil.rmtree(work, ignore_errors=True)
print("No problems." if not BAD else f"PROBLEMS: {', '.join(BAD)}")
sys.exit(1 if BAD else 0)
