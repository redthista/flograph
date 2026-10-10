"""Charts from a selection: which chart the selected columns make, and the
Show Plotly settings that draw it.

Excel's Insert ▸ Chart reads the range you selected — a column of labels
and columns of numbers become a column chart with one bar per label. Here
a chart is a node wired to the Table, so it reads whole *columns*: the
selection says which columns to chart, and every row of them is charted,
rows added later included. That is what makes the chart stay true as the
table grows, which a fixed range would not.

`pick_chart` is the whole rule, Qt-free, so a test can read it at a
glance; the grid hands it each selected column as (name, type, values).
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Sequence

#: What the Insert Chart menu offers, in order: (kind, label). "auto" is
#: Excel's Recommended Charts — the one that suits the columns picked.
KINDS: tuple[tuple[str, str], ...] = (
    ("auto", "Recommended"),
    ("bar", "Column"),
    ("line", "Line"),
    ("area", "Area"),
    ("pie", "Pie"),
    ("scatter", "Scatter"),
    ("histogram", "Histogram"),
)

#: The node a chart is drawn by.
CHART_NODE = "flograph.viz.show_plotly"


@dataclass
class ChartPick:
    kind: str                      # the plotly kind: bar, line, pie...
    params: dict = field(default_factory=dict)   # Show Plotly params
    note: str = ""                 # what was left out, said to the user


def column_role(col_type: str, values: Sequence) -> str:
    """"number", "date" or "text" — what a column is on a chart. A typed
    column says; an auto column is a number when every filled cell is one,
    which is the same test the Table uses when it hands the column on."""
    if col_type in ("number", "integer"):
        return "number"
    if col_type == "date":
        return "date"
    if col_type in ("text", "bool"):
        return "text"
    filled = [v for v in values if v not in ("", None)]
    if filled and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                      for v in filled):
        return "number"
    if filled and all(isinstance(v, (_dt.date, _dt.datetime))
                      for v in filled):
        return "date"
    return "text"


def _listing(names: Sequence[str]) -> str:
    names = list(names)
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def pick_chart(columns: Sequence[tuple[str, str, Sequence]],
               kind: str = "auto") -> "ChartPick | str":
    """The chart the columns make, or a sentence saying why there isn't
    one. ``columns`` is (name, type, values) per selected column, left to
    right.

    The first column that isn't numbers is the X axis — the labels or
    dates each mark stands at — and the number columns are what is drawn.
    A label that repeats is summed, one bar per label, the way a pivot
    chart totals a category."""
    if not columns:
        return "Select the columns to chart first."
    for name, _type, _values in columns:
        if "," in name:
            return (f"The column {name!r} can't be charted: its name has a "
                    "comma in it, and a chart's column list is "
                    "comma-separated. Rename it first.")
    roles = [(name, column_role(t, values), list(values))
             for name, t, values in columns]
    labels = [(n, v) for n, role, v in roles if role != "number"]
    numbers = [n for n, role, _v in roles if role == "number"]
    x, x_values = labels[0] if labels else ("", [])
    x_role = next((role for n, role, _v in roles if n == x), "")
    unused = [n for n, _v in labels[1:]]

    if kind == "auto":
        if x_role == "date":
            kind = "line"
        elif x:
            kind = "bar"
        elif len(numbers) == 2:
            kind = "scatter"
        elif len(numbers) == 1:
            kind = "histogram"
        else:
            kind = "line"

    if not numbers:
        return ("There are no numbers to chart. Select a column of numbers "
                "too — with a column of labels or dates beside it for the "
                "X axis.")

    params: dict = {"kind": kind}
    notes: list[str] = []
    if kind == "pie":
        if not x:
            return ("A pie needs a column of labels — one slice per label. "
                    "Select a text column along with the numbers.")
        params.update(names=x, values=numbers[0],
                      title=f"{numbers[0]} by {x}")
        if len(numbers) > 1:
            notes.append(f"A pie shows one column of numbers, so it shows "
                         f"{numbers[0]}; {_listing(numbers[1:])} left out.")
    elif kind == "scatter":
        if len(numbers) < 2:
            return ("A scatter chart plots one column of numbers against "
                    "another — select two number columns.")
        params.update(x=numbers[0], y=", ".join(numbers[1:]),
                      title=f"{_listing(numbers[1:])} against {numbers[0]}")
        if x:
            params["color"] = x          # the labels colour the points
    elif kind == "histogram":
        params.update(x=numbers[0], title=f"How {numbers[0]} is spread")
        if x:
            params["color"] = x
        if len(numbers) > 1:
            notes.append(f"A histogram shows one column, so it shows "
                         f"{numbers[0]}; {_listing(numbers[1:])} left out.")
    else:                                 # bar, line, area: x against y
        params.update(x=x, y=", ".join(numbers))
        shown = _listing(numbers)
        params["title"] = f"{shown} by {x}" if x else shown
        filled = [v for v in x_values if v not in ("", None)]
        if x and len(set(map(str, filled))) < len(filled):
            params["summarise"] = "sum"   # one mark per label, totalled
    if unused and kind not in ("scatter", "histogram"):
        verb = "isn't" if len(unused) == 1 else "aren't"
        notes.append(f"{_listing(unused)} {verb} numbers, so not drawn — "
                     f"{x} is the X axis.")
    return ChartPick(kind=kind, params=params, note=" ".join(notes))


def place_beside(anchor: tuple[float, float, float, float],
                 size: tuple[float, float],
                 taken: Sequence[tuple[float, float, float, float]],
                 gap: float = 60.0) -> tuple[float, float]:
    """Where a new box of ``size`` goes: right of ``anchor`` (x, y, w, h)
    with its top level with the anchor's, stepping down past anything it
    would land on. Boxes are (x, y, w, h)."""
    ax, ay, aw, _ah = anchor
    w, h = size
    x, y = ax + aw + gap, ay

    def hits(top: float):
        return next((b for b in taken
                     if x < b[0] + b[2] and b[0] < x + w
                     and top < b[1] + b[3] and b[1] < top + h), None)

    for _ in range(200):
        box = hits(y)
        if box is None:
            break
        y = box[1] + box[3] + gap / 2
    return x, y
