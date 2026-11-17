"""The whole Launcher window built with stand-in widgets (no window is drawn, nothing runs in the background), in an
empty game folder: every tab's set-up runs, so a name or call that's wrong in one shows here.
python tests/test_gui_builds.py <tools/installer>"""
import os
import sys
import tempfile
from unittest.mock import MagicMock


class Var:
    def __init__(self, master=None, value=None, name=None):
        self.v = value

    def get(self):
        return "" if self.v is None else self.v

    def set(self, v):
        self.v = v

    def trace_add(self, *a):
        pass

    trace = trace_add


class BoolVar(Var):
    def get(self):
        return bool(self.v)


class IntVar(Var):
    def get(self):
        return int(self.v or 0)


tk = MagicMock()
tk.StringVar, tk.BooleanVar, tk.IntVar, tk.DoubleVar = Var, BoolVar, IntVar, IntVar
mods = {"tkinter": tk}
for n in ("ttk", "filedialog", "messagebox", "font", "simpledialog"):
    mods["tkinter." + n] = getattr(tk, n)
for w in (tk.ttk.Treeview.return_value, tk.Listbox.return_value):
    w.selection.return_value = w.get_children.return_value = w.curselection.return_value = ()
tk.ttk.Combobox.return_value.current.return_value = -1
tk.ttk.Combobox.return_value.get.return_value = ""
sys.modules.update(mods)
sys.path[:0] = [sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), ".."),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "saves")]
import install  # noqa: E402


class NotStarted:
    def __init__(self, target=None, daemon=None, **_):
        pass

    def start(self):
        pass


install.threading = MagicMock()
install.threading.Thread = NotStarted
install.gui(tempfile.mkdtemp())
print("Launcher window builds")
