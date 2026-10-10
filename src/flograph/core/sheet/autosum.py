"""AutoSum (Alt+=): a total of the numbers above, or to the left, with the
range guessed — Excel's Σ button.

Two shapes, as in Excel:

* **One cell** — the formula is *proposed*: the editor opens on
  ``=SUM(B2:B9)``, the range being the run of numbers straight above the
  cell (or, with none above, to its left), selected so a drag or a typed
  range replaces it. Enter accepts.
* **A range** — the totals are *written*: one under each column of the
  selection that holds numbers, in its empty last row if it has one, else
  in the first row below where those cells are empty (a new row at the
  bottom of the table when there is none). A selection one row tall is
  totalled to its right instead.

Qt-free: the grid hands in two questions about its cells.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .formula import cell_name

#: (function, menu label) — the Σ ▾ list, Excel's order.
FUNCTIONS: tuple[tuple[str, str], ...] = (
    ("SUM", "Sum"),
    ("AVERAGE", "Average"),
    ("COUNT", "Count Numbers"),
    ("MAX", "Max"),
    ("MIN", "Min"),
)


@dataclass
class Proposal:
    """One cell: open its editor on ``text`` with ``span`` (start, end)
    selected — the range, for replacing."""
    cell: tuple[int, int]
    text: str
    span: tuple[int, int]


@dataclass
class Totals:
    """A range: write ``cells`` {(row, col): formula}; ``grows`` says a
    row or column is added at the table's edge to hold them."""
    cells: dict = field(default_factory=dict)
    grows: bool = False


def _formula(func: str, r0: int, c0: int, r1: int, c1: int) -> str:
    first, last = cell_name(r0, c0), cell_name(r1, c1)
    return f"={func}({first}:{last})" if (r0, c0) != (r1, c1) \
        else f"={func}({first})"


def propose(func: str, row: int, col: int,
            is_number: Callable[[int, int], bool]) -> Proposal:
    """The formula for one cell: the numbers straight above it, else
    those straight to its left, else an empty call to fill in."""
    top = row
    while top > 0 and is_number(top - 1, col):
        top -= 1
    if top < row:
        text = _formula(func, top, col, row - 1, col)
    else:
        left = col
        while left > 0 and is_number(row, left - 1):
            left -= 1
        if left < col:
            text = _formula(func, row, left, row, col - 1)
        else:
            text = f"={func}()"
            at = len(text) - 1
            return Proposal((row, col), text, (at, at))
    start = len(func) + 2
    return Proposal((row, col), text, (start, len(text) - 1))


def totals(func: str, box: tuple[int, int, int, int], n_rows: int,
           n_cols: int, is_number: Callable[[int, int], bool],
           is_empty: Callable[[int, int], bool]) -> "Totals | str":
    """The totals for a selected range (r0, c0, r1, c1), or a sentence
    saying why there are none."""
    r0, c0, r1, c1 = box
    if r0 == r1 and c1 > c0:
        return _row_totals(func, r0, c0, c1, n_cols, is_number, is_empty)
    # an empty last row in the selection is where the totals go
    last_empty = r1 > r0 and all(is_empty(r1, c) for c in range(c0, c1 + 1))
    end = r1 - 1 if last_empty else r1
    cols = [c for c in range(c0, c1 + 1)
            if any(is_number(r, c) for r in range(r0, end + 1))]
    if not cols:
        return "There are no numbers in the selection to total."
    if last_empty:
        target = r1
    else:
        target = r1 + 1
        while target < n_rows and not all(is_empty(target, c)
                                          for c in cols):
            target += 1
    return Totals({(target, c): _formula(func, r0, c, end, c) for c in cols},
                  grows=target >= n_rows)


def _row_totals(func, row, c0, c1, n_cols, is_number, is_empty):
    last_empty = is_empty(row, c1)
    end = c1 - 1 if last_empty else c1
    if not any(is_number(row, c) for c in range(c0, end + 1)):
        return "There are no numbers in the selection to total."
    if last_empty:
        target = c1
    else:
        target = next((c for c in range(c1 + 1, n_cols)
                       if is_empty(row, c)), None)
        if target is None:
            return ("There's no empty cell to the right of the selection "
                    "for the total — insert a column, or select a cell and "
                    "press Alt+= there.")
    return Totals({(row, target): _formula(func, row, c0, row, end)})


def label_for(func: str) -> Optional[str]:
    return next((label for f, label in FUNCTIONS if f == func), None)
