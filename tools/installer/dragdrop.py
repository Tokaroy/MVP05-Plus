"""Files dragged from Explorer onto a part of the Launcher (Windows; elsewhere this does nothing).

  accept(widget, on_drop)   on_drop([paths]) is called, on Tk's own thread, when files or folders are dropped on
                            widget or anything inside it. False where drops can't be taken.

Tk has no file drops of its own, and the add-on that gives it them (tkdnd) is another thing to ship, so this uses
Windows' older drop messages: the widget's window is marked as accepting files (DragAcceptFiles) and its window
procedure is wrapped to take WM_DROPFILES, everything else going on to Tk's. Windows doesn't deliver drops from
Explorer to a program running as administrator, so there the buttons are the way.
"""
import os

_kept = {}  # hwnd -> (the wrapped procedure, Tk's), kept for as long as the Launcher runs
_gone = []  # the procedures of windows since closed (kept: one may still be running when its window goes)
WM_DROPFILES = 0x0233
WM_NCDESTROY = 0x0082
GWLP_WNDPROC = -4


def accept(widget, on_drop):
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        setlong = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
        setlong.restype = ctypes.c_void_p
        setlong.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        user32.CallWindowProcW.restype = LRESULT
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                           wintypes.LPARAM]
        shell32.DragQueryFileW.restype = wintypes.UINT
        shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
        shell32.DragFinish.argtypes = [ctypes.c_void_p]
        shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        widget.update_idletasks()
        hwnd = widget.winfo_id()
        if not hwnd or hwnd in _kept:
            return bool(hwnd)

        def proc(h, msg, wparam, lparam):
            if msg == WM_DROPFILES:
                paths = []
                try:
                    for i in range(shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)):
                        n = shell32.DragQueryFileW(wparam, i, None, 0)
                        buf = ctypes.create_unicode_buffer(n + 1)
                        shell32.DragQueryFileW(wparam, i, buf, n + 1)
                        paths.append(buf.value)
                finally:
                    shell32.DragFinish(wparam)
                if paths:
                    try:  # after this message is done with: on_drop may open windows of its own
                        widget.after(1, lambda: on_drop(paths))
                    except Exception:
                        pass
                return 0
            old_proc = _kept[h][1]
            if msg == WM_NCDESTROY:  # the window is going: its number can be given to a new one, hooked afresh
                _gone.append(_kept.pop(h)[0])
            return user32.CallWindowProcW(old_proc, h, msg, wparam, lparam)

        wrapped = WNDPROC(proc)
        _kept[hwnd] = (wrapped, None)
        old = setlong(hwnd, GWLP_WNDPROC, ctypes.cast(wrapped, ctypes.c_void_p))
        if not old:
            del _kept[hwnd]
            return False
        _kept[hwnd] = (wrapped, old)
        shell32.DragAcceptFiles(hwnd, True)
        return True
    except Exception:
        return False
