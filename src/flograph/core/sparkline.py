"""Sparklines — a row of numbers drawn as a chart the size of a word.

Qt-free on purpose. A `spark` rule (see table_format) reads several columns
of one row and hands the numbers here; this module decides where every
line, bar and dot goes, and nothing else. The card paints those shapes with
a QPainter (ui/table_delegate.py) and a printed report gets the very same
shapes written out as SVG (`svg` / `data_uri`), so the two cannot draw one
row two ways.

Six kinds::

    line      the default — the shape of the numbers
    area      a line with the ground under it filled
    step      holds each value until the next one arrives
    bars      a column per value, from zero; negatives hang below it
    winloss   up or down and nothing else — did it gain or lose
    dots      a dot per value, no line between them

and marks laid on top of any of them: the ``first`` and ``last`` point,
the ``high`` and the ``low``, or every point (``points``). On a bar kind a
mark colours the bar instead of adding a dot, which is how Excel does it
and the only thing that reads at this size.

**Missing values are gaps, not zeros.** A month nobody reported is not a
month that sold nothing, and a line that drops to the floor there says
something false. So a line breaks round a hole and a bar is simply absent.
A row with fewer than two numbers draws nothing: one point is not a trend.
"""
from __future__ import annotations

import base64
import math
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

#: The kinds, and the words people type for each.
KINDS = {
    "line": "line", "lines": "line",
    "area": "area",
    "step": "step", "steps": "step",
    "bars": "bars", "bar": "bars", "columns": "bars", "column": "bars",
    "winloss": "winloss", "win-loss": "winloss", "win/loss": "winloss",
    "dots": "dots", "dot": "dots", "scatter": "dots",
}

#: The marks, and the words for them. `ends` is the two of them at once,
#: because "where did it start and where is it now" is one question.
MARKS = {
    "first": ("first",), "start": ("first",),
    "last": ("last",), "end": ("last",), "latest": ("last",),
    "high": ("high",), "max": ("high",), "peak": ("high",),
    "low": ("low",), "min": ("low",),
    "ends": ("first", "last"),
    "points": ("points",), "markers": ("points",),
}

#: A reference line's words. A number is taken as it is.
REFS = {"mean": "mean", "avg": "mean", "average": "mean",
        "median": "median", "zero": 0.0}

#: The line's own colour when none is named. Bright enough to read on the
#: dark grid, dark enough to survive on paper.
DEFAULT_COLOR = "#4a90d9"
NEGATIVE_COLOR = "#d9534f"
#: What a mark is drawn in when the rule names no colour for it. `last`
#: and `points` take the line's colour, so they read as part of it.
MARK_COLORS = {"high": "#5cb85c", "low": "#d9534f", "first": "#9aa0a6"}
REF_COLOR = "#8a8f98"

#: Vivid colours a spark may be named in. The fill presets the rest of the
#: rules use are dark *grounds* and would vanish drawn as a line.
COLORS = {
    "blue": "#4a90d9", "green": "#5cb85c", "red": "#d9534f",
    "amber": "#e0a83d", "orange": "#e8833a", "yellow": "#e6c84f",
    "purple": "#9b7fd1", "teal": "#3fb8af", "pink": "#e36fa5",
    "grey": "#9aa0a6", "gray": "#9aa0a6", "white": "#e5e7eb",
}

#: How wide a spark standing *beside* a value is on the card, in pixels.
#: One placed above, below or in place of the value takes the cell's width.
BESIDE_WIDTH = 64
#: How wide a spark is on paper, in points — beside a value, and standing
#: on its own (in place of the value, or on a line above or below it).
PAPER_BESIDE = 48
PAPER_ALONE = 72
#: How tall, in points, on paper. `tall` doubles it.
PAPER_HEIGHT = 12

#: A row needs this many numbers before it is a line.
MIN_POINTS = 2

#: The share of a bar's slot the bar takes; the rest is the gap.
_BAR_SHARE = 0.72
_AREA_OPACITY = 0.28
#: How much sharper than its drawn size an SVG spark is written. A report
#: prints at 300 dpi, and Qt rasterises an SVG at the size it states.
SVG_DENSITY = 4


@dataclass
class Spark:
    """Everything needed to draw one cell's sparkline.

    `low` / `high` are the scale's ends when the rule shares one scale
    down the column; left None, each row is scaled to its own numbers,
    which shows the *shape* of every row as clearly as it can be shown.
    """
    values: list
    kind: str = "line"
    color: Optional[str] = None
    negative_color: Optional[str] = None
    #: [[mark, colour | None], …] in the order the rule named them
    marks: list = field(default_factory=list)
    low: Optional[float] = None
    high: Optional[float] = None
    ref: Optional[float] = None
    #: pixels on the card; None = the default for where it sits
    width: Optional[int] = None
    tall: bool = False
    smooth: bool = False
    thick: bool = False

    def to_dict(self) -> dict:
        out = {"values": list(self.values), "kind": self.kind}
        for name in ("color", "negative_color", "low", "high", "ref",
                     "width"):
            value = getattr(self, name)
            if value is not None:
                out[name] = value
        if self.marks:
            out["marks"] = [list(m) for m in self.marks]
        for name in ("tall", "smooth", "thick"):
            if getattr(self, name):
                out[name] = True
        return out

    @classmethod
    def from_dict(cls, d: Any) -> "Spark":
        d = dict(d or {})
        known = {"values", "kind", "color", "negative_color", "marks", "low",
                 "high", "ref", "width", "tall", "smooth", "thick"}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Shapes:
    """A spark laid out in a `width` × `height` box, top-left at 0, 0.

    * `areas` — ``(top edge points, baseline y, colour, opacity)``
    * `lines` — ``(points, colour, stroke width)``
    * `rects` — ``(x, y, w, h, colour)``
    * `dots`  — ``(x, y, radius, colour)``
    * `guides` — ``(y, colour, dashed)``, drawn across the whole width

    `smooth` says whether the areas and lines are curves through their
    points (see `curve`) or straight segments between them.
    """
    areas: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    rects: list = field(default_factory=list)
    dots: list = field(default_factory=list)
    guides: list = field(default_factory=list)
    smooth: bool = False


def number(value: Any) -> Optional[float]:
    """`value` as a finite float, or None for anything that is not one."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def reference(spec: Any, values: Sequence) -> Optional[float]:
    """Where a `ref` line sits for these values: a number as given, or the
    mean / median of the row."""
    if spec is None:
        return None
    present = sorted(v for v in (number(x) for x in values) if v is not None)
    if spec == "mean":
        return sum(present) / len(present) if present else None
    if spec == "median":
        if not present:
            return None
        mid = len(present) // 2
        return (present[mid] if len(present) % 2
                else (present[mid - 1] + present[mid]) / 2)
    return number(spec)


def geometry(spark: Spark, width: float, height: float) -> Optional[Shapes]:
    """The shapes `spark` draws in a box this size, or None when there is
    nothing to draw — fewer than `MIN_POINTS` numbers, or no room."""
    values = [number(v) for v in spark.values]
    present = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(present) < MIN_POINTS or width < 4 or height < 4:
        return None
    kind = spark.kind if spark.kind in KINDS.values() else "line"
    colour = spark.color or DEFAULT_COLOR
    negative = spark.negative_color or NEGATIVE_COLOR
    stroke = 2.2 if spark.thick else 1.4
    radius = 2.4 if spark.thick else 1.9
    # room for a dot's radius at every edge, so a mark on the high point is
    # a whole dot rather than half of one cut off by the cell
    pad = radius + stroke / 2
    left, top = pad, pad
    inner_w, inner_h = width - 2 * pad, height - 2 * pad
    if inner_w <= 0 or inner_h <= 0:
        return None
    n = len(values)
    shapes = Shapes(smooth=spark.smooth and kind in ("line", "area"))

    marked = _marked(spark.marks, present, colour)

    if kind == "winloss":
        slot = inner_w / n
        bar_w = max(1.0, slot * _BAR_SHARE)
        mid = top + inner_h / 2
        half = max(1.0, inner_h / 2 - 0.5)
        shapes.guides.append((mid, REF_COLOR, False))
        for i, v in present:
            if v == 0:
                continue
            x = left + i * slot + (slot - bar_w) / 2
            fill = marked.get(i) or (colour if v > 0 else negative)
            y = mid - half if v > 0 else mid + 0.5
            shapes.rects.append((x, y, bar_w, half, fill))
        return shapes

    only = [v for _i, v in present]
    lo = spark.low if spark.low is not None else min(only)
    hi = spark.high if spark.high is not None else max(only)
    ref = spark.ref
    if ref is not None:
        lo, hi = min(lo, ref), max(hi, ref)
    if kind == "bars":
        # a bar is a length from zero, so zero has to be on the scale or
        # the shortest bar reads as nothing at all
        lo, hi = min(lo, 0.0), max(hi, 0.0)

    def y_of(v: float) -> float:
        if hi == lo:
            return top + inner_h / 2
        clamped = max(lo, min(hi, v))
        return top + (hi - clamped) / (hi - lo) * inner_h

    if ref is not None:
        shapes.guides.append((y_of(ref), REF_COLOR, True))

    if kind == "bars":
        slot = inner_w / n
        bar_w = max(1.0, slot * _BAR_SHARE)
        base = y_of(0.0)
        if lo < 0 < hi:
            shapes.guides.append((base, REF_COLOR, False))
        for i, v in present:
            x = left + i * slot + (slot - bar_w) / 2
            y = y_of(v)
            fill = marked.get(i) or (colour if v >= 0 else negative)
            # a zero still gets a hairline, so "nothing" is visibly a value
            # and not a hole where a number was missing
            shapes.rects.append((x, min(y, base), bar_w,
                                 max(1.0, abs(base - y)), fill))
        return shapes

    step = inner_w / (n - 1)

    def point(i: int, v: float) -> tuple:
        return (left + i * step, y_of(v))

    if kind == "dots":
        for i, v in present:
            x, y = point(i, v)
            shapes.dots.append((x, y, radius, marked.get(i) or colour))
        return shapes

    base = y_of(max(lo, min(hi, 0.0))) if lo < 0 < hi else top + inner_h
    for run in _runs(values):
        points = [point(i, v) for i, v in run]
        if kind == "step":
            points = _stepped(points, left + inner_w)
        if len(points) == 1:
            # a value with a gap either side has nothing to join to; a dot
            # says it was there without inventing a line
            x, y = points[0]
            shapes.dots.append((x, y, stroke * 0.9, colour))
            continue
        if kind == "area":
            shapes.areas.append((points, base, colour, _AREA_OPACITY))
        shapes.lines.append((points, colour, stroke))

    for i, fill in marked.items():
        x, y = point(i, values[i])
        shapes.dots.append((x, y, radius, fill))
    return shapes


def _marked(marks, present, colour: str) -> dict:
    """index -> colour for every point a mark lands on. Later marks win a
    point they share, the same way a later rule wins a cell."""
    if not marks or not present:
        return {}
    first, last = present[0][0], present[-1][0]
    high = max(present, key=lambda p: p[1])[0]
    low = min(present, key=lambda p: p[1])[0]
    where = {"first": [first], "last": [last], "high": [high], "low": [low],
             "points": [i for i, _v in present]}
    out: dict = {}
    for entry in marks:
        name = entry[0] if isinstance(entry, (list, tuple)) else entry
        chosen = (entry[1] if isinstance(entry, (list, tuple))
                  and len(entry) > 1 else None)
        fill = chosen or MARK_COLORS.get(name) or colour
        for i in where.get(name, ()):
            out[i] = fill
    return out


def _runs(values) -> list:
    """The unbroken stretches of numbers, as lists of (index, value)."""
    runs, current = [], []
    for i, v in enumerate(values):
        if v is None:
            if current:
                runs.append(current)
            current = []
        else:
            current.append((i, v))
    if current:
        runs.append(current)
    return runs


def _stepped(points, right: float) -> list:
    """A line that holds each value until the next arrives."""
    out = []
    for (x, y), nxt in zip(points, points[1:] + [None]):
        out.append((x, y))
        if nxt is not None:
            out.append((nxt[0], y))
    return out


def curve(points) -> list:
    """Bézier segments through `points`: ``[(c1, c2, end), …]`` after a
    move to ``points[0]``.

    Catmull-Rom, with each control point held between the heights of the
    two points it joins. Unclamped, a curve through a peak swings above
    the peak — and in a spark the peak's height *is* the data, so a curve
    that invents a higher one is lying in the one way that matters.
    """
    out = []
    count = len(points)
    for i in range(count - 1):
        p0 = points[i - 1] if i > 0 else points[i]
        p1, p2 = points[i], points[i + 1]
        p3 = points[i + 2] if i + 2 < count else p2
        lo, hi = min(p1[1], p2[1]), max(p1[1], p2[1])
        c1 = (p1[0] + (p2[0] - p0[0]) / 6,
              max(lo, min(hi, p1[1] + (p2[1] - p0[1]) / 6)))
        c2 = (p2[0] - (p3[0] - p1[0]) / 6,
              max(lo, min(hi, p2[1] - (p3[1] - p1[1]) / 6)))
        out.append((c1, c2, p2))
    return out


# ------------------------------------------------------------------ SVG

def _n(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") or "0"


def _path(points, smooth: bool) -> str:
    head = f"M{_n(points[0][0])} {_n(points[0][1])}"
    if smooth:
        return head + "".join(
            f" C{_n(c1[0])} {_n(c1[1])} {_n(c2[0])} {_n(c2[1])} "
            f"{_n(p[0])} {_n(p[1])}" for c1, c2, p in curve(points))
    return head + "".join(f" L{_n(x)} {_n(y)}" for x, y in points[1:])


def svg(spark: Spark, width: float, height: float,
        density: int = SVG_DENSITY) -> Optional[str]:
    """`spark` as an SVG document, drawn in a `width` × `height` box and
    stated `density` times that size — or None when there is nothing to
    draw."""
    shapes = geometry(spark, width, height)
    if shapes is None:
        return None
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" '
           f'width="{_n(width * density)}" height="{_n(height * density)}" '
           f'viewBox="0 0 {_n(width)} {_n(height)}">']
    for y, colour, dashed in shapes.guides:
        dash = ' stroke-dasharray="2 2"' if dashed else ""
        out.append(f'<line x1="0" y1="{_n(y)}" x2="{_n(width)}" '
                   f'y2="{_n(y)}" stroke="{colour}" stroke-width="0.7"'
                   f'{dash}/>')
    for points, base, colour, opacity in shapes.areas:
        d = (_path(points, shapes.smooth)
             + f" L{_n(points[-1][0])} {_n(base)}"
             + f" L{_n(points[0][0])} {_n(base)} Z")
        out.append(f'<path d="{d}" fill="{colour}" '
                   f'fill-opacity="{_n(opacity)}" stroke="none"/>')
    for x, y, w, h, colour in shapes.rects:
        out.append(f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" '
                   f'height="{_n(h)}" fill="{colour}"/>')
    for points, colour, stroke in shapes.lines:
        out.append(f'<path d="{_path(points, shapes.smooth)}" fill="none" '
                   f'stroke="{colour}" stroke-width="{_n(stroke)}" '
                   f'stroke-linejoin="round" stroke-linecap="round"/>')
    for x, y, r, colour in shapes.dots:
        out.append(f'<circle cx="{_n(x)}" cy="{_n(y)}" r="{_n(r)}" '
                   f'fill="{colour}"/>')
    out.append("</svg>")
    return "".join(out)


def data_uri(spark: Spark, width: float, height: float) -> Optional[str]:
    """`svg` as a ``data:`` address, for an `<img>` that needs no file."""
    text = svg(spark, width, height)
    if text is None:
        return None
    return ("data:image/svg+xml;base64,"
            + base64.b64encode(text.encode("utf-8")).decode("ascii"))


# -------------------------------------------------------------- summary

def format_number(value: float) -> str:
    """A number short enough for a tooltip line."""
    if abs(value) >= 1e15:
        return f"{value:.3g}"
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def summary(values: Sequence, names: Sequence) -> Optional[str]:
    """What a spark shows, in words — for the cell's tooltip.

    ``Jan 12 → Dec 19  (+7)`` then ``high 21 (Jun) · low 9 (Feb)``: where it
    started, where it is now, and the two extremes, each with the column it
    came from, because a picture this small cannot carry its own axis.
    """
    present = [(str(name), v) for name, v in
               zip(names, (number(x) for x in values)) if v is not None]
    if len(present) < MIN_POINTS:
        return None
    (first_name, first), (last_name, last) = present[0], present[-1]
    change = last - first
    sign = "+" if change > 0 else ""
    high = max(present, key=lambda p: p[1])
    low = min(present, key=lambda p: p[1])
    return (f"{first_name} {format_number(first)} → {last_name} "
            f"{format_number(last)}  ({sign}{format_number(change)})\n"
            f"high {format_number(high[1])} ({high[0]}) · "
            f"low {format_number(low[1])} ({low[0]})")
