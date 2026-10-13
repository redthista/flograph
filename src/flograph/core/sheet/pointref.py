"""Pointing at cells while typing a formula — Excel's Point mode.

Type ``=`` (or ``=SUM(``, ``=A1+``…) and click a cell: its reference is
typed in for you. Drag across cells, or Shift+click, for a range. Click
another cell straight after and it replaces the reference just put in
rather than adding a second one, so a wrong click costs nothing.

A click only points where a reference could go next: straight after the
``=``, an opening bracket, a comma or an operator. Anywhere else — after a
number, a reference, inside "quoted text" or a ``[Column]`` — the click
does what it always did and finishes the edit. This module is the rule;
ui/spreadsheet/pointing.py turns clicks into calls to it.
"""
from __future__ import annotations

from .absref import _protected
from .formula import cell_name

# what may come straight before a reference
OPENERS = frozenset("=(,+-*/^&<>:;")


def point_span(text: str, start: int, end: int | None = None
               ) -> tuple[int, int] | None:
    """Where a pointed-at reference would go in ``text`` with the cursor
    at ``start`` (or ``start``..``end`` selected, which it replaces), or
    None when a click there should not point."""
    if not text.startswith("="):
        return None
    end = start if end is None else end
    lo, hi = min(start, end), max(start, end)
    if lo < 1 or hi > len(text):
        return None
    if any(a < lo < b for a, b in _protected(text)):
        return None          # inside "quoted text" or a [Column]
    before = text[:lo].rstrip()
    if not before or before[-1] not in OPENERS:
        return None
    return lo, hi


def range_text(a: tuple[int, int], b: tuple[int, int]) -> str:
    """The reference for cells ``a`` to ``b`` (0-based (row, col), either
    corner first): ``B3`` for one cell, ``A1:C4`` for more."""
    r0, r1 = sorted((a[0], b[0]))
    c0, c1 = sorted((a[1], b[1]))
    first, last = cell_name(r0, c0), cell_name(r1, c1)
    return first if first == last else f"{first}:{last}"


def put(text: str, span: tuple[int, int], ref: str
        ) -> tuple[str, tuple[int, int]]:
    """``text`` with ``ref`` in place of ``span``, and where ``ref`` now
    sits — the span the next click replaces."""
    lo, hi = span
    return text[:lo] + ref + text[hi:], (lo, lo + len(ref))
