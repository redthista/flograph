"""Click-to-filter on a Show Table: what was picked, and what it keeps.

The table's answer to Show Plotly's *On click*. Clicking a cell, a row
header or (Ctrl+click) a column header on the card writes a **pick** into
the node's `selected` param; the node re-runs, and its `filtered` output is
the table narrowed to the pick. The card and the node read the same param
through this module, so what is highlighted and what flows on cannot
disagree.

A pick is a small JSON object, any part of which may be absent:

    {"cells": {"region": ["north", "south"], "product": ["widget"]},
     "rows": ["0", "7"],
     "columns": ["region", "revenue"]}

* **cells** — a clicked cell means "rows with this value in this column".
  Values in one column add up (north *or* south); columns narrow each other
  (north *and* widget) — the way two slicers, or a spreadsheet's filter
  drop-downs, combine.
* **rows** — a row picked by its header is kept by its index label. Rows
  add to what the cells match rather than narrowing it: Ctrl+clicking a row
  onto a cell pick means "and this one too".
* **columns** — picked columns are the columns kept. They never touch
  which rows are kept.

Values are compared as text, `astype(str)` on both sides, which is what
Show Plotly does — a date or a float is matched by how it prints.

Qt-free, and pandas is imported by the functions that need it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

#: What the node's On click offers — the same words Show Plotly uses.
MODES = ("nothing", "select one", "select many")


def pick_mode(params: dict) -> str:
    """A node's On click as one of MODES — "nothing" for a node that has no
    such param (Table Spec shares the table card and never filters)."""
    mode = params.get("on_click")
    return mode if mode in MODES else "nothing"


@dataclass
class Picks:
    cells: dict[str, list[str]] = field(default_factory=dict)
    rows: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.cells or self.rows or self.columns)

    def to_json(self) -> str:
        """The param's text: "" for nothing picked, keys only when used."""
        if not self:
            return ""
        out: dict[str, Any] = {}
        if self.cells:
            out["cells"] = {c: list(v) for c, v in self.cells.items() if v}
        if self.rows:
            out["rows"] = list(self.rows)
        if self.columns:
            out["columns"] = list(self.columns)
        return json.dumps(out, ensure_ascii=False)


def _texts(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        seen: dict[str, None] = {}
        for v in value:
            seen.setdefault(str(v), None)
        return list(seen)
    return [str(value)]


def parse_picks(raw: Any) -> Picks:
    """The `selected` param as a `Picks`. Forgiving, because the box is
    typed into too: blank or unreadable text is no pick, a bare list is
    taken as row labels."""
    if isinstance(raw, Picks):
        return raw
    if isinstance(raw, dict):
        parsed: Any = raw
    else:
        text = str(raw or "").strip()
        if not text:
            return Picks()
        try:
            parsed = json.loads(text)
        except ValueError:
            return Picks()
    if isinstance(parsed, list):
        return Picks(rows=_texts(parsed))
    if not isinstance(parsed, dict):
        return Picks()
    cells_raw = parsed.get("cells")
    cells: dict[str, list[str]] = {}
    if isinstance(cells_raw, dict):
        for column, values in cells_raw.items():
            texts = _texts(values)
            if texts:
                cells[str(column)] = texts
    return Picks(cells=cells, rows=_texts(parsed.get("rows")),
                 columns=_texts(parsed.get("columns")))


def _column_position(table, name: str) -> int | None:
    """The first column answering to `name` — a frame may hold two."""
    for i, column in enumerate(table.columns):
        if str(column) == name:
            return i
    return None


def filter_frame(table, picks: Any) -> tuple[Any, list[str]]:
    """`table` narrowed to the pick, and a line for each thing worth
    telling the user (a column the pick names that isn't there).

    With nothing picked the table comes back as it is, the same object."""
    picks = parse_picks(picks)
    notes: list[str] = []
    if not picks:
        return table, notes
    import pandas as pd

    keep = None
    if picks.cells:
        keep = pd.Series(True, index=range(len(table)))
        matched_any = False
        for name, values in picks.cells.items():
            pos = _column_position(table, name)
            if pos is None:
                notes.append(f"no column {name!r} to filter on")
                continue
            matched_any = True
            column = table.iloc[:, pos].astype(str)
            keep &= column.isin(values).to_numpy()
        if not matched_any:
            keep = None
    if picks.rows:
        by_row = pd.Series(table.index.astype(str).isin(picks.rows),
                           index=range(len(table)))
        keep = by_row if keep is None else (keep | by_row)
    out = table if keep is None else table[keep.to_numpy()]

    if picks.columns:
        positions = []
        for name in picks.columns:
            pos = _column_position(out, name)
            if pos is None:
                notes.append(f"no column {name!r} to keep")
            else:
                positions.append(pos)
        if positions:
            out = out.iloc[:, sorted(set(positions))]
    return out, notes


def describe(picks: Any) -> str:
    """A short account of a pick for the run log."""
    picks = parse_picks(picks)
    parts = []
    for name, values in picks.cells.items():
        shown = ", ".join(values[:3]) + (" …" if len(values) > 3 else "")
        parts.append(f"{name} = {shown}")
    if picks.rows:
        parts.append(f"{len(picks.rows)} row{'s' if len(picks.rows) != 1 else ''}")
    if picks.columns:
        parts.append(f"columns {', '.join(picks.columns)}")
    return "; ".join(parts)


#: What a click picks: a cell (a row by its number, a column by Ctrl+click
#: on its header), or always the whole row.
PICK_BY = ("cell", "row")


def pick_by(params: dict) -> str:
    by = params.get("select_by")
    return by if by in PICK_BY else "cell"


def active_picks(params: dict) -> Picks:
    """The pick a node's params filter on. Nothing while On click is off;
    in row mode only the rows, so a pick left over from cell mode is shown
    nowhere and obeyed nowhere."""
    if pick_mode(params) == "nothing":
        return Picks()
    picks = parse_picks(params.get("selected", ""))
    if pick_by(params) == "row":
        return Picks(rows=picks.rows)
    return picks
