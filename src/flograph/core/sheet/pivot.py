"""PivotTable from a selection: which columns go down the side, which
across the top, which are totalled — and the Show Table settings that
draw it.

flograph has no PivotTable of its own: Show Table *is* one. Its matrix
mode puts Rows down the side, Columns across the top and Values in the
cells; its grouped mode gathers rows under a foldable header carrying
their subtotal. So Insert ▸ PivotTable is a Show Table wired to the
Table, set up from the selection:

* labels across the top as well as down the side → **matrix**;
* labels down the side only → **grouped**, groups folded, so it opens
  as one subtotal line per label (Excel's compact pivot) and each one
  unfolds to the rows behind it.

Either way there is a grand total row. Qt-free; ``preview`` works the
same numbers out in plain Python so the dialog can show them first.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .chart import column_role
from .summary import is_number

PIVOT_NODE = "flograph.viz.show_table"

#: Summarise values by: (Show Table's matrix aggregation, label).
AGGS: tuple[tuple[str, str], ...] = (
    ("sum", "Sum"),
    ("mean", "Average"),
    ("count", "Count"),
    ("min", "Min"),
    ("max", "Max"),
    ("median", "Median"),
)
#: What each role is called in the dialog.
ROLES = ("Rows", "Columns", "Values", "Leave out")

# the total row's aggregation for a grouped pivot (its subtotals use it
# too) — Show Table's names, which say "average" where pandas says "mean"
_GROUP_TOTAL = {"sum": "sum", "mean": "average", "count": "count",
                "min": "min", "max": "max", "median": "median"}
# a matrix's cells are already aggregated; its total row adds them up,
# except where adding them would be wrong
_MATRIX_TOTAL = {"sum": "sum", "mean": "average", "count": "sum",
                 "min": "min", "max": "max", "median": "median"}


@dataclass
class PivotLayout:
    rows: list = field(default_factory=list)
    columns: list = field(default_factory=list)
    values: list = field(default_factory=list)
    agg: str = "sum"
    total: bool = True

    @property
    def matrix(self) -> bool:
        return bool(self.columns)


@dataclass
class PivotPick:
    """What the host adds: a Show Table with these params."""
    params: dict
    title: str
    node_type: str = PIVOT_NODE
    kind: str = "PivotTable"
    note: str = ""


def guess(columns: Sequence[tuple[str, str, Sequence]]) -> PivotLayout:
    """The layout the selected columns suggest: labels down the side —
    the last of several across the top — and the numbers totalled."""
    labels, numbers = [], []
    for name, col_type, values in columns:
        (numbers if column_role(col_type, values) == "number"
         else labels).append(name)
    if len(labels) > 1:
        return PivotLayout(rows=labels[:-1], columns=labels[-1:],
                           values=numbers)
    return PivotLayout(rows=labels, values=numbers)


def check(layout: PivotLayout) -> Optional[str]:
    """Why the layout can't be drawn yet, or None."""
    for name in (*layout.rows, *layout.columns, *layout.values):
        if "," in name:
            return (f"The column {name!r} has a comma in its name, and a "
                    "PivotTable's column lists are comma-separated. Rename "
                    "it first.")
    if not layout.rows:
        return "Put at least one column in Rows — what runs down the side."
    if not layout.values:
        return ("Put at least one column in Values — the numbers to "
                f"{_verb(layout.agg)}.")
    return None


def _verb(agg: str) -> str:
    return {"sum": "add up", "mean": "average", "count": "count",
            "min": "take the smallest of", "max": "take the largest of",
            "median": "take the middle of"}.get(agg, "total")


def _listing(names: Sequence[str]) -> str:
    names = list(names)
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def agg_label(agg: str) -> str:
    return next((label for key, label in AGGS if key == agg), agg)


def title(layout: PivotLayout) -> str:
    """"Sum of Sales by Region and Month"."""
    by = _listing([*layout.rows, *layout.columns])
    return f"{agg_label(layout.agg)} of {_listing(layout.values)} by {by}"


def describe(layout: PivotLayout) -> str:
    """The dialog's sentence: what the PivotTable will show."""
    problem = check(layout)
    if problem:
        return problem
    what = f"{agg_label(layout.agg)} of {_listing(layout.values)}"
    if layout.matrix:
        text = (f"{what}: a row for each {_listing(layout.rows)}, a column "
                f"for each {_listing(layout.columns)}.")
    else:
        text = (f"{what} for each {_listing(layout.rows)} — click one to "
                "see the rows behind it.")
    if layout.total:
        text += " A grand total row at the bottom."
    return text


def params(layout: PivotLayout) -> dict:
    """Show Table's settings for the layout."""
    if layout.matrix:
        out = {"mode": "matrix",
               "matrix_rows": ", ".join(layout.rows),
               "matrix_columns": ", ".join(layout.columns),
               "matrix_values": ", ".join(layout.values),
               "matrix_agg": layout.agg,
               "totals": _MATRIX_TOTAL[layout.agg] if layout.total
               else "off"}
    else:
        out = {"mode": "grouped",
               "group_by": ", ".join(layout.rows),
               "groups_start": "folded",
               "subtotals": "on the group row",
               "show": ", ".join([*layout.rows, *layout.values]),
               # the subtotals follow the total row's aggregation, so it
               # is set even with the grand total row off
               "totals": _GROUP_TOTAL[layout.agg]}
        if not layout.total:
            # subtotals kept, the grand total row hidden
            out["format_rules"] = "total hidden"
    out["width"] = 520
    out["height"] = 360
    return out


def pick(layout: PivotLayout) -> "PivotPick | str":
    problem = check(layout)
    if problem:
        return problem
    return PivotPick(params=params(layout), title=title(layout))


# ------------------------------------------------------------- preview

def _aggregate(agg: str, values: list):
    if agg == "count":
        return len([v for v in values if v not in ("", None)])
    numbers = [v for v in values if is_number(v)]
    if not numbers:
        return None
    if agg == "sum":
        return sum(numbers)
    if agg == "mean":
        return sum(numbers) / len(numbers)
    if agg == "min":
        return min(numbers)
    if agg == "max":
        return max(numbers)
    return statistics.median(numbers)


def _key(value) -> str:
    return "(blank)" if value in ("", None) else str(value)


def preview(layout: PivotLayout, data: dict, max_rows: int = 8,
            max_cols: int = 8) -> tuple[list, list]:
    """(headers, rows) of the PivotTable as it will open — worked out
    from ``data`` {column: values} in plain Python, cut to a size a
    dialog can show. A grouped pivot shows its folded subtotal lines."""
    if check(layout):
        return [], []
    n = len(next(iter(data.values()), []))
    row_keys: dict = {}
    col_keys: dict = {}
    cells: dict = {}
    for i in range(n):
        rk = tuple(_key(data[c][i]) for c in layout.rows)
        ck = tuple(_key(data[c][i]) for c in layout.columns)
        row_keys.setdefault(rk, None)
        col_keys.setdefault(ck, None)
        for v in layout.values:
            cells.setdefault((rk, ck, v), []).append(data[v][i])
    headers = list(layout.rows)
    columns = [(ck, v) for v in layout.values for ck in col_keys]
    for ck, v in columns:
        if not ck:
            headers.append(v)
        else:          # one value: its heading sits above, as on the card
            headers.append(" ".join(ck) if len(layout.values) == 1
                           else " ".join([v, *ck]))
    out = []
    for rk in list(row_keys)[:max_rows]:
        out.append([*rk, *(_aggregate(layout.agg, cells.get((rk, ck, v),
                                                              []))
                           for ck, v in columns)])
    if layout.total:
        total = ["Total", *[""] * (len(layout.rows) - 1)]
        for ck, v in columns:
            if layout.matrix:
                agg = {"count": "sum", "mean": "mean"}.get(layout.agg,
                                                           layout.agg)
                parts = [_aggregate(layout.agg, cells.get((rk, ck, v), []))
                         for rk in row_keys]
                total.append(_aggregate(agg, [p for p in parts
                                              if p is not None]))
            else:
                total.append(_aggregate(layout.agg, data[v]))
        out.append(total)
    width = len(layout.rows) + max_cols
    return headers[:width], [r[:width] for r in out]
