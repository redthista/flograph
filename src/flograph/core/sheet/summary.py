"""The selection summary — Excel's status bar: Average, Count and Sum of
whatever is selected, at a glance, without writing a formula.

Counts like Excel's: **Count** is every filled cell, **Numerical Count**
the ones holding a number; Sum, Average, Min and Max read the numbers
only, so a label or a TRUE in the selection never skews them. A cell with
a formula error is left out of everything but Count.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

#: What the strip can show, in the order shown: (key, label).
FIGURES: tuple[tuple[str, str], ...] = (
    ("average", "Average"),
    ("count", "Count"),
    ("numbers", "Numerical Count"),
    ("min", "Min"),
    ("max", "Max"),
    ("sum", "Sum"),
)
#: Excel's own choice out of the box.
DEFAULT_FIGURES = ("average", "count", "sum")


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@dataclass
class Summary:
    count: int = 0          # filled cells
    numbers: int = 0        # cells holding a number
    sum: float = 0.0
    min: Optional[float] = None
    max: Optional[float] = None

    @property
    def average(self) -> Optional[float]:
        return self.sum / self.numbers if self.numbers else None


def summarise(values: Iterable) -> Summary:
    out = Summary()
    for value in values:
        if value is None or value == "":
            continue
        out.count += 1
        if not is_number(value):
            continue
        out.numbers += 1
        out.sum += value
        out.min = value if out.min is None else min(out.min, value)
        out.max = value if out.max is None else max(out.max, value)
    return out


def summary_text(summary: Summary, figures: Iterable[str] = DEFAULT_FIGURES,
                 fmt: Optional[Callable[[float], str]] = None) -> str:
    """"Average 40  Count 3  Sum 120" — the chosen figures that have a
    value. ``fmt`` writes a number (the column's number format); counts
    are always plain. Empty when there is nothing to say."""
    wanted = set(figures)
    show = fmt or _plain
    parts = []
    for key, label in FIGURES:
        if key not in wanted:
            continue
        if key in ("count", "numbers"):
            if summary.count:
                parts.append(f"{label}: {getattr(summary, key)}")
            continue
        value = getattr(summary, key)
        if summary.numbers and value is not None:
            parts.append(f"{label}: {show(value)}")
    return "   ".join(parts)


def _plain(value: float) -> str:
    if float(value).is_integer() and abs(value) < 1e15:
        return f"{int(value):,}"
    return f"{value:,.10g}" if abs(value) >= 1e-4 else f"{value:.4g}"
