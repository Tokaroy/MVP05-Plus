"""mvp05-settings.toml beside the exe: read, and single values changed in place (comments and the rest of the
file kept as they are). The game reads it when it starts and never writes it."""
import os
import re

FILE = "mvp05-settings.toml"

# what the Settings tab offers, with the shipped file's values as the defaults
DISPLAY_MODES = ["windowed", "borderless", "fullscreen"]
DEFAULTS = {"display_mode": "fullscreen", "width": 0, "height": 0, "render_percent": 100, "fps_cap": 60,
            "vsync": True, "low_latency": False, "anisotropic_filtering": 16, "xbox_720p": True,
            "unlock_all": False}


def _parse(v):
    v = v.split("#", 1)[0].strip() if not v.strip().startswith('"') else v.strip()
    if v.startswith('"'):
        return v[1:v.index('"', 1)]
    if v in ("true", "false"):
        return v == "true"
    try:
        return int(v)
    except ValueError:
        return v


def _fmt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return '"' + str(v).replace('"', "") + '"'


def read(root):
    """Every value, a section's as "section.key" (the [keyboard] keys as "keyboard.a" and so on)."""
    out = {}
    try:
        with open(os.path.join(root, FILE), encoding="utf-8") as f:
            section = ""
            for line in f:
                h = re.match(r"\s*\[([A-Za-z0-9_]+)\]\s*(#.*)?$", line)
                if h:
                    section = h.group(1) + "."
                    continue
                m = re.match(r"\s*([A-Za-z0-9_]+)\s*=\s*(.*)$", line)
                if m:
                    out[section + m.group(1)] = _parse(m.group(2))
    except OSError:
        pass
    return out


def write(root, changes):
    """Each key's line given its new value (its comment after the value kept), or added: a key of the top level
    before the first [section] (a line after it would belong to the section), a "section.key" at the end of its
    section (made at the end of the file if it isn't there)."""
    p = os.path.join(root, FILE)
    try:
        with open(p, encoding="utf-8", newline="") as f:
            text = f.read()
    except OSError:
        text = ""
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    left = dict(changes)
    section, first_header, ends = "", None, {}  # ends: the line after each section's last key
    for i, line in enumerate(lines):
        h = re.match(r"\s*\[([A-Za-z0-9_]+)\]\s*(#.*)?$", line)
        if h:
            section = h.group(1) + "."
            ends[section] = i + 1
            if first_header is None:
                first_header = i
            continue
        m = re.match(r"(\s*)([A-Za-z0-9_]+)(\s*=\s*)(.*)$", line)
        if not m:
            continue
        if section:
            ends[section] = i + 1
        name = section + m.group(2)
        if name in left:
            rest = m.group(4).strip()
            if rest.startswith('"') and '"' in rest[1:]:
                rest = rest[rest.index('"', 1) + 1:]  # a quoted value may hold a #: its comment is after it
            comment = "  #" + rest.split("#", 1)[1] if "#" in rest else ""
            lines[i] = m.group(1) + m.group(2) + m.group(3) + _fmt(left.pop(name)) + comment
    top = [f"{k} = {_fmt(v)}" for k, v in left.items() if "." not in k]
    in_sections = {}
    for k, v in left.items():
        if "." in k:
            sec, key = k.split(".", 1)
            in_sections.setdefault(sec + ".", []).append(f"{key} = {_fmt(v)}")
    # the sections' own first, from the bottom up so the line numbers above stay right
    for sec in sorted((x for x in in_sections if x in ends), key=lambda x: -ends[x]):
        lines[ends[sec]:ends[sec]] = in_sections.pop(sec)
    for sec, new in in_sections.items():  # sections the file doesn't have
        lines += ["", f"[{sec[:-1]}]"] + new
    if top:
        at = first_header if first_header is not None else len(lines)
        while first_header is not None and at > 0 and (not lines[at - 1].strip() or lines[at - 1].lstrip().startswith("#")):
            at -= 1  # (above the section's own comment and blank line)
        lines[at:at] = top
    tmp = p + ".part"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(nl.join(lines) + nl)
    os.replace(tmp, p)
