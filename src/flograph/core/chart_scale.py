"""The Y range a chart is drawn against.

Shared by the two Chart per Value nodes, which had grown the same twenty
lines of extent arithmetic each. Nothing here draws: it answers "what
should the axis run from and to", and the node hands that to matplotlib or
to Plotly.

Two things decide the range:

**The data.** `data_extent` measures the columns being plotted, with the
one subtlety that matters — a *stacked* chart reaches the row's total, not
its tallest column, so bounding it by the column maximum crops every bar.
The extent is padded by 5% so a line touching the maximum isn't drawn on
the frame.

**The user.** `y_limits` replaces either end with a manual bound. A pinned
value is used exactly as given, unpadded: someone who types 0 means 0, not
-0.4. Pinning them the wrong way round (a Min above a Max) flips the axis,
which both libraries do happily and is occasionally what's wanted.

Blank means "not pinned", which is why the bounds are strings rather than
`float` params: a spin box has no way to say "leave this one alone", and
pinning only the top of an axis is a real thing to want.
"""
from __future__ import annotations

from typing import Any, Optional

#: Headroom added to a *derived* extent, as a fraction of its span. Manual
#: bounds skip it.
PAD = 0.05


def as_bound(value: Any) -> Optional[float]:
    """A manual axis bound as a float, or None when it isn't one.

    Unreadable is the same as blank on purpose: half-typed text in an axis
    box should leave the chart alone, not fail the run.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def data_extent(frame, columns, stacked: bool = False
                ) -> Optional[tuple[float, float]]:
    """(low, high) covering `columns` of `frame`, padded, or None if the
    data has no numbers in it.

    `stacked` bounds by the row totals instead of by the individual values,
    with the positive and negative piles measured separately so a negative
    series doesn't eat into the height of the positive ones.
    """
    if not len(columns):
        return None
    values = frame[list(columns)].apply(lambda s: s.astype("float64"), axis=0)
    if values.empty:
        return None
    if stacked:
        low = float(values.clip(upper=0).sum(axis=1).min())
        high = float(values.clip(lower=0).sum(axis=1).max())
    else:
        low, high = float(values.min().min()), float(values.max().max())
    if low != low or high != high:      # NaN — nothing numeric to bound
        return None
    pad = (high - low) * PAD or 1.0
    return (low - pad, high + pad)


def y_limits(extent: Optional[tuple[float, float]],
             min_y: Optional[float] = None,
             max_y: Optional[float] = None
             ) -> Optional[tuple[float, float]]:
    """The range to pin the axis to: `extent` with either end replaced by
    the manual bound given for it.

    None when an end is left without a value — a half-known range is not
    something either library can be handed, so the chart keeps its own
    autoscale instead.
    """
    low = min_y if min_y is not None else (extent[0] if extent else None)
    high = max_y if max_y is not None else (extent[1] if extent else None)
    if low is None or high is None:
        return None
    return (low, high)
