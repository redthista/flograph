"""Remove Duplicates, Qt-free: which rows repeat an earlier one.

Rows are compared on the chosen columns by the values they show — so two
formulas giving the same answer match — ignoring case and the spaces
around a value, as Excel does. The first row of each set stays; every
later one is a duplicate.
"""
from __future__ import annotations

from typing import Callable, Iterable


def _key(text: str) -> str:
    return text.strip().casefold()


def duplicate_rows(n_rows: int, cols: Iterable[int],
                   shown: Callable[[int, int], str],
                   rows: Iterable[int] | None = None) -> list[int]:
    """The rows (among `rows`, every row when None) that repeat an earlier
    one on all of `cols`, where `shown(row, col)` is the value a cell
    shows."""
    cols = list(cols)
    if not cols:
        return []
    seen: set[tuple] = set()
    dupes = []
    for r in (range(n_rows) if rows is None else rows):
        key = tuple(_key(shown(r, c)) for c in cols)
        if key in seen:
            dupes.append(r)
        else:
            seen.add(key)
    return dupes


def summary(removed: int, kept: int) -> str:
    """Excel's message, in plain words."""
    if not removed:
        return f"No duplicates — all {kept} rows are different."
    rows = "row" if removed == 1 else "rows"
    return (f"{removed} duplicate {rows} removed; {kept} unique "
            f"{'row' if kept == 1 else 'rows'} remain.")
