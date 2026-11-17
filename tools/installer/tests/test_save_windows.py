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


class Inline:
    def __init__(self, target=None, daemon=None, **_):
        self.t = target

    def start(self):
        self.t()


install.threading = MagicMock()
install.threading.Thread = Inline
install.choose_card_save = lambda frm, tk, ttk, found: found[0]
mb = sys.modules["tkinter"].messagebox
fd = sys.modules["tkinter"].filedialog
BAD = []

# imports: (what, file, whether it should import)
imports = [(n, sample(n), not n.startswith(("mvp06", "README"))) for n in sorted(os.listdir(SAMPLES))
           if not n.startswith("xb_")] + [("an Xbox save's folder", folders.get("xb_dyn.dat"), True),
                                          ("Dolphin card", card, True), ("not a save", os.path.join(REPO, "README.md"),
                                                                         False)]
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
        go = [c.kwargs["command"] for c in ttk.Button.return_value.configure.call_args_list if "command" in c.kwargs][1]
        go()
        res = [t for t in texts if t.startswith(("Done", "Nothing"))]
        result = res[-1] if res else "no result"
    good = result.startswith("Done") if ok else ("can't be used" in picked)
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

shutil.rmtree(work, ignore_errors=True)
print("No problems." if not BAD else f"PROBLEMS: {', '.join(BAD)}")
sys.exit(1 if BAD else 0)
