"""Laying a list of charts out in a grid.

A node whose output is a list gets stacked wherever it is shown — the
canvas card, a dashboard tile, a report. This module decides *where each
one goes*, and is shared by all of them so a stack is arranged identically
on screen and on paper.

Three settings, read from the node's own params:

    columns   how many across   (0 = work it out)
    rows      how many down     (0 = work it out)
    direction "across" fills left-to-right, "down" fills top-to-bottom

Leaving both counts at 0 lets the direction decide: "down" is a single
column (what a stack meant before any of this existed), "across" a single
row that scrolls sideways. Setting one count derives the other from how
many charts there are; setting both fixes the grid, and any overflow
extends it along the fill direction rather than being hidden. Nothing here
can drop a chart, which matters because the whole point is comparing a
complete set.
"""
from __future__ import annotations

import math

DIRECTIONS = ("across", "down")

#: The direction assumed when a node says nothing. "down" because a stack
#: has always been a vertical column, and every list-producing node written
#: before this existed must keep looking the way it did.
DEFAULT_DIRECTION = "down"


def grid_shape(count: int, columns: int = 0, rows: int = 0,
               direction: str = DEFAULT_DIRECTION) -> tuple[int, int]:
    """(columns, rows) needed to hold `count` charts.

    0 means "derive from the other one". With *both* left at 0 there is
    nothing to derive from, so the direction decides: "down" is a single
    column, "across" a single row. That is the plain reading of the
    setting — all of them top to bottom, or all of them left to right —
    and it is what makes the direction meaningful before any count is set.

    With both given the grid is taken as asked, then grown *downwards* if
    it wouldn't hold everything — the column count is a width constraint,
    and a layout setting that silently dropped charts would be worse than
    one that scrolls.
    """
    count = max(0, int(count))
    columns, rows = max(0, int(columns)), max(0, int(rows))
    across = direction == "across"
    if not count:
        return (max(1, columns), 0) if columns else (1, 0)

    if columns and rows:
        if columns * rows >= count:
            return (columns, rows)
        # Overflow grows *rows*, never columns: the column count is a width
        # constraint (the card, the page), and extra height scrolls in every
        # host while extra width just falls off the edge.
        return (columns, math.ceil(count / columns))
    if columns:
        return (columns, math.ceil(count / columns))
    if rows:
        return (math.ceil(count / rows), rows)
    return (count, 1) if across else (1, count)


def cells(count: int, columns: int = 0, rows: int = 0,
          direction: str = DEFAULT_DIRECTION) -> list[tuple[int, int]]:
    """(row, column) for each chart in order.

    "across" numbers left-to-right along each row; "down" numbers
    top-to-bottom along each column.
    """
    if direction not in DIRECTIONS:
        raise ValueError(f"unknown direction {direction!r} "
                         f"(valid: {', '.join(DIRECTIONS)})")
    n_columns, n_rows = grid_shape(count, columns, rows, direction)
    placed = []
    for index in range(max(0, int(count))):
        if direction == "across":
            placed.append((index // n_columns, index % n_columns))
        else:
            placed.append((index % n_rows, index // n_rows))
    return placed


def grid_settings(params) -> tuple[int, int, str]:
    """(columns, rows, direction) from a node's params, defaulted.

    Tolerant on purpose: these are optional, and a node that declares none
    of them — every list-producing node written before this existed — must
    still stack the way it always did.
    """
    params = params or {}

    def whole(name: str) -> int:
        try:
            return max(0, int(params.get(name) or 0))
        except (TypeError, ValueError):
            return 0

    direction = str(params.get("direction")
                    or DEFAULT_DIRECTION).strip().lower()
    return (whole("columns"), whole("rows"),
            direction if direction in DIRECTIONS else DEFAULT_DIRECTION)
