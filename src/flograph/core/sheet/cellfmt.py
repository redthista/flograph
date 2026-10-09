"""A cell's own look, Qt-free: bold, italic, underline, fill, font colour
and alignment — Excel's Home ▸ Font and Alignment, per cell.

A format is a small dict: ``{"b": True, "fill": "#fde68a", "align":
"center"}``; a cell with none has no entry. Display only — a format never
changes a value or what flows on. Conditional formatting paints over it,
as in Excel.
"""
from __future__ import annotations

import re
from typing import Optional

FLAGS = ("b", "i", "u")
ALIGNS = ("left", "center", "right")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

#: Excel-ish swatches for the Fill and Font Colour menus: (name, hex)
FILLS = (("Yellow", "#fde68a"), ("Orange", "#fdba74"), ("Red", "#fca5a5"),
         ("Pink", "#f9a8d4"), ("Purple", "#c4b5fd"), ("Blue", "#93c5fd"),
         ("Teal", "#5eead4"), ("Green", "#86efac"), ("Grey", "#d1d5db"),
         ("Dark grey", "#4b5563"))
INKS = (("Red", "#ef4444"), ("Orange", "#f97316"), ("Amber", "#eab308"),
        ("Green", "#22c55e"), ("Teal", "#14b8a6"), ("Blue", "#3b82f6"),
        ("Purple", "#a855f7"), ("Pink", "#ec4899"), ("Grey", "#9ca3af"),
        ("White", "#ffffff"), ("Black", "#111827"))


def clean(raw) -> Optional[dict]:
    """A stored format made safe; None when nothing is left."""
    if not isinstance(raw, dict):
        return None
    out: dict = {}
    for flag in FLAGS:
        if raw.get(flag) is True:
            out[flag] = True
    for key in ("fill", "color"):
        value = raw.get(key)
        if isinstance(value, str) and _HEX.match(value):
            out[key] = value.lower()
    if raw.get("align") in ALIGNS:
        out["align"] = raw["align"]
    return out or None


def merged(old: Optional[dict], changes: dict) -> Optional[dict]:
    """`old` with `changes` laid over it; a change to None or False takes
    that part off."""
    out = dict(old or {})
    for key, value in changes.items():
        if value in (None, False, ""):
            out.pop(key, None)
        else:
            out[key] = value
    return clean(out)
