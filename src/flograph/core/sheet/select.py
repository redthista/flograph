"""Find & Select, Qt-free: which cells Go To and Go To Special pick.

`special_cells` is Excel's Go To Special: every formula, constant, blank or
error in the selection (or the whole sheet when one cell is selected),
formulas and constants narrowed by what they hold — numbers, text,
logicals, errors. `current_region` is the block of filled cells around a
cell, bounded by empty rows and columns; `last_cell` is the bottom-right
corner of the data. `parse_reference` reads what is typed into Go To:
``B4``, ``B2:D10``, ``B:D`` (whole columns), ``3:5`` (whole rows), ``12``
(row 12) or a column's name.
"""
from __future__ import annotations

import re
from typing import Callable, Iterable, Optional, Union

from .formula import col_index
from .schema import is_formula
from .values import FormulaError

KINDS = (("formulas", "Formulas"), ("constants", "Constants"),
         ("blanks", "Blanks"), ("errors", "Errors"),
         ("problems", "Problem cells"), ("notes", "Notes"),
         ("region", "Current region"),
         ("last", "Last cell"))
TYPES = ("numbers", "text", "logicals", "errors")
_NOUN = {"formulas": "formula", "constants": "value", "blanks": "blank cell",
         "errors": "error", "problems": "problem cell",
         "notes": "note"}

Rect = tuple[int, int, int, int]
_CELL = re.compile(r"^\$?([A-Za-z]{1,3})\$?(\d+)$")
_COLS = re.compile(r"^\$?([A-Za-z]{1,3}):\$?([A-Za-z]{1,3})$")
_ROWS = re.compile(r"^\$?(\d+):\$?(\d+)$")


def value_type(value) -> str:
    """"numbers", "text", "logicals", "errors" or "blank" for a computed
    cell value."""
    if isinstance(value, FormulaError):
        return "errors"
    if value is None or value == "":
        return "blank"
    if isinstance(value, bool):
        return "logicals"
    if isinstance(value, (int, float)):
        return "numbers"
    return "text"


def special_cells(n_rows: int, n_cols: int,
                  source: Callable[[int, int], str],
                  value: Callable[[int, int], object], kind: str,
                  types: Iterable[str] = TYPES,
                  within: Optional[Iterable[tuple[int, int]]] = None,
                  skip_row: Callable[[int], bool] = lambda _r: False,
                  problem: Callable[[int, int], bool] = lambda _r, _c: False,
                  noted: Callable[[int, int], bool] = lambda _r, _c: False
                  ) -> list[tuple[int, int]]:
    """The cells of one Go To Special `kind` (formulas, constants, blanks,
    errors, problems, notes) among `within` — every cell when None — in reading
    order. Rows `skip_row` says are hidden are passed over."""
    wanted = set(types)
    if within is None:
        cells = ((r, c) for r in range(n_rows) for c in range(n_cols))
    else:
        cells = sorted(set(within))
    found = []
    for r, c in cells:
        if not (0 <= r < n_rows and 0 <= c < n_cols) or skip_row(r):
            continue
        text = source(r, c)
        if kind == "blanks":
            hit = not text.strip()
        elif kind == "problems":
            hit = problem(r, c)
        elif kind == "notes":
            hit = noted(r, c)
        elif kind == "errors":
            hit = isinstance(value(r, c), FormulaError)
        elif kind == "formulas":
            # a formula showing nothing ("") counts as text, as in Excel
            shows = value_type(value(r, c)) if is_formula(text) else None
            hit = shows is not None and (
                "text" if shows == "blank" else shows) in wanted
        elif kind == "constants":
            hit = (bool(text.strip()) and not is_formula(text)
                   and value_type(value(r, c)) in wanted)
        else:
            raise ValueError(f"unknown kind {kind!r}")
        if hit:
            found.append((r, c))
    return found


def current_region(n_rows: int, n_cols: int,
                   filled: Callable[[int, int], bool], row: int,
                   col: int) -> Rect:
    """Excel's current region: grow a box from (row, col) while any cell
    just outside it — diagonals included — is filled."""
    r0 = r1 = row
    c0 = c1 = col
    while True:
        grown = False
        if r0 > 0 and any(filled(r0 - 1, c) for c in
                          range(max(0, c0 - 1), min(n_cols, c1 + 2))):
            r0 -= 1
            grown = True
        if r1 < n_rows - 1 and any(filled(r1 + 1, c) for c in
                                   range(max(0, c0 - 1), min(n_cols, c1 + 2))):
            r1 += 1
            grown = True
        if c0 > 0 and any(filled(r, c0 - 1) for r in
                          range(max(0, r0 - 1), min(n_rows, r1 + 2))):
            c0 -= 1
            grown = True
        if c1 < n_cols - 1 and any(filled(r, c1 + 1) for r in
                                   range(max(0, r0 - 1), min(n_rows, r1 + 2))):
            c1 += 1
            grown = True
        if not grown:
            return r0, c0, r1, c1


def last_cell(n_rows: int, n_cols: int,
              filled: Callable[[int, int], bool]) -> Optional[tuple[int, int]]:
    """The last row with anything in it, at the last column with anything
    in it — Excel's Ctrl+End. None for an empty sheet."""
    last_row = last_col = -1
    for r in range(n_rows):
        for c in range(n_cols):
            if filled(r, c):
                last_row = r
                last_col = max(last_col, c)
    if last_row < 0:
        return None
    return last_row, last_col


def parse_reference(text: str, names: list[str], n_rows: int,
                    n_cols: int) -> Union[Rect, str]:
    """What Go To was asked for, as (row0, col0, row1, col1), or a
    sentence saying why it can't be found."""
    raw = text.strip()
    if not raw:
        return "Type a cell such as B4, a range such as B2:D10, or a " \
               "column's name."
    lowered = [n.lower() for n in names]
    if raw.lower() in lowered:
        col = lowered.index(raw.lower())
        return 0, col, max(0, n_rows - 1), col
    if raw.isdigit():
        row = int(raw) - 1
        if not 0 <= row < n_rows:
            return f"There is no row {raw} — the table has {n_rows} rows."
        return row, 0, row, max(0, n_cols - 1)
    match = _ROWS.match(raw)
    if match:
        a, b = sorted(int(g) - 1 for g in match.groups())
        if a < 0 or b >= n_rows:
            return f"The table has rows 1 to {n_rows}."
        return a, 0, b, max(0, n_cols - 1)
    match = _COLS.match(raw)
    if match:
        a, b = sorted(col_index(g) for g in match.groups())
        if b >= n_cols:
            return f"The table has {n_cols} columns."
        return 0, a, max(0, n_rows - 1), b
    parts = raw.split(":")
    if len(parts) in (1, 2):
        cells = [_CELL.match(p.strip()) for p in parts]
        if all(cells):
            points = [(int(m.group(2)) - 1, col_index(m.group(1)))
                      for m in cells]
            rows = sorted(p[0] for p in points)
            cols = sorted(p[1] for p in points)
            if rows[0] < 0 or rows[-1] >= n_rows or cols[-1] >= n_cols:
                return (f"{raw.upper()} is outside the table, which has "
                        f"{n_rows} rows and {n_cols} columns.")
            return rows[0], cols[0], rows[-1], cols[-1]
    return (f"“{raw}” isn't a cell, a range or a column name. Try B4, "
            f"B2:D10, B:D, 3:5 or a column's name.")


def found_text(kind: str, count: int) -> str:
    """The note shown after a Go To Special pick."""
    noun = _NOUN.get(kind, "cell")
    if count == 0:
        return f"No {noun}s found."
    plural = noun if count == 1 else noun + "s"
    tail = (" Type a value and press Ctrl+Enter to fill them all."
            if kind == "blanks" else "")
    return f"{count} {plural} selected.{tail}"
