"""Dropdown lists read from helper tables wired into a Table node.

A Table node grows extra inputs the way Concatenate does: fill the empty
"helper" port and another appears below it (``in2``, ``in3``, ...). Any
table can go in — a list of regions, of products, of people — and a
column's Dropdown List can take its values from one of their columns
instead of a typed list: ``ColumnSpec.choices_from = {"input": "in2",
"column": "Region"}``.

The reference is a *wire*, never a node looked up by name, so the
scheduler sees it: the helper runs first, and a change to it re-runs the
table. Dropdown lists only ever describe what may be typed — they never
change a value — so all that has to happen with the helper's data is to
read it when a grid is shown. :func:`resolve` does that, given the
helper frames from the cache. The values it reads are kept in
``ColumnSpec.choices`` and saved with the sheet, so a list still opens
when the file is reopened before anything has run.

Pure Python: frames are read through ``columns`` and ``[name].tolist()``,
so nothing here imports pandas.
"""
from __future__ import annotations

from typing import Optional

#: A helper column's distinct values past this many are left off the
#: list: a dropdown is something a person reads, and a menu thousands of
#: items long is a search problem, not a pick.
MAX_CHOICES = 1000


def clean_source(raw) -> Optional[dict]:
    """A saved ``choices_from`` made safe, or None when it isn't one."""
    if not isinstance(raw, dict):
        return None
    column = str(raw.get("column") or "").strip()
    if not column:
        return None
    return {"input": str(raw.get("input") or "").strip(), "column": column}


def distinct_values(frame, column) -> list[str]:
    """A frame column's distinct non-blank values, as text, in the order
    they first appear (the order a helper table was written in is usually
    the order meant), compared without case like a typed list is."""
    from .values import format_value
    seen: set[str] = set()
    out: list[str] = []
    for value in frame[column].tolist():
        if value is None or value != value:     # None, NaN, NaT
            continue
        text = format_value(value).strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= MAX_CHOICES:
            break
    return out


def _frame_columns(frame) -> list[str]:
    return [str(c) for c in getattr(frame, "columns", ())]


def find_column(helpers: dict, source: dict):
    """(frame, column) a source names, or None.

    The named input is tried first. If it has no such column — the helper
    was rewired into another port, or ports were removed and re-added —
    the first helper that has the column is used, so the list follows the
    table rather than the port number."""
    wanted = source.get("column")
    first = helpers.get(source.get("input"))
    order = ([first] if first is not None else []) + [
        f for name, f in helpers.items() if name != source.get("input")]
    for frame in order:
        for col in getattr(frame, "columns", ()):
            if str(col) == wanted:
                return frame, col
    return None


def resolve(sheet, frames: dict, helpers: Optional[list] = None):
    """Fill the helper-sourced dropdown lists of `sheet` in place, record
    which helpers there are, and return it.

    ``frames`` is ``{input port: frame}`` for the helpers whose table is in
    hand. ``helpers`` describes every wired helper for the Dropdown List
    dialog — ``[{"input", "label", "columns"}]`` — and may name one whose
    frame isn't in hand (spilled to disk, not run yet); left out, it is
    made from ``frames``. A column whose source can't be read keeps the
    values it last read."""
    if helpers is None:
        helpers = [{"input": name, "label": name,
                    "columns": _frame_columns(frame)}
                   for name, frame in frames.items()]
    sheet.helpers = [dict(h) for h in helpers]
    for col in sheet.columns:
        if not col.choices_from:
            continue
        found = find_column(frames, col.choices_from)
        if found is not None:
            col.choices = distinct_values(*found)
    return sheet


def helper_ports(input_names) -> list[str]:
    """The helper inputs among a Table node's input names, in port order:
    everything but the linked ``table`` input and the empty ``helper``
    slot."""
    def number(name: str) -> int:
        return int(name[2:]) if name[2:].isdigit() else 0
    return sorted((n for n in input_names
                   if n.startswith("in") and n[2:].isdigit()), key=number)
