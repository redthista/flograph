"""Which way is up for a DataFrame column, and applying that to a frame.

Split out of ``ui/table_sort.py`` when a table gained a *default* sort. A
sort typed as a rule has to reach the printed report as well as the card,
and the report renderer is core and Qt-free — so the "which way is up" half
moved here, where both can use it, and the click-a-header interaction
(``HeaderSortCycler``) stayed in ui with the QHeaderView it drives.

Both halves matter for the same reason the rest of `table_html` exists: a
report that orders its rows differently from the dashboard it came off is
worse than one with no sort at all.

Qt-free, and pandas is imported inside the functions, as everywhere in core.
"""
from __future__ import annotations

# Fraction of a sampled object column that must parse as one type before we
# sort the whole column as that type. High enough that a stray numeric code
# in a text column doesn't flip it, low enough to tolerate a few bad cells.
_DETECT_THRESHOLD = 0.9
_DETECT_SAMPLE = 1000

# Above this row count an object column of date-like text sorts lexically
# rather than chronologically: parsing the whole column with
# ``format="mixed"`` is a per-element Python loop that would freeze the UI
# thread for seconds. Numeric coercion stays on at any size — it is
# vectorised C and cheap. (ISO dates sort correctly lexically anyway.)
_MAX_TEXT_DATE_ROWS = 200_000


def _text_key(series):
    """Case-insensitive string key — the fallback for anything not sniffed
    as a number or a date, and for a column too large to date-parse."""
    return series.astype("string").str.casefold()


def pandas_sort_key(series):
    """The series pandas should actually order when sorting ``series``.

    Same shape out as in (usable as ``key=`` to
    :meth:`Series.sort_values`); NaT/NaN survive so ``na_position`` still
    applies. Never raises: a sniff or parse that fails falls back to a
    plain string key, because this runs inside the Qt slot that reorders
    the view.
    """
    import pandas as pd
    from pandas.api import types as pdt

    try:
        # Numbers, datetimes, timedeltas, bools and categoricals already
        # order correctly; only string / object / mixed columns need sniffing.
        if (pdt.is_numeric_dtype(series)
                or pdt.is_datetime64_any_dtype(series)
                or pdt.is_timedelta64_dtype(series)
                or isinstance(series.dtype, pd.CategoricalDtype)):
            return series

        sample = series.dropna().astype(str).head(_DETECT_SAMPLE)
        if sample.empty:
            return series

        as_num = pd.to_numeric(sample, errors="coerce")
        if as_num.notna().mean() >= _DETECT_THRESHOLD:
            return pd.to_numeric(series, errors="coerce")

        if len(series) <= _MAX_TEXT_DATE_ROWS:
            as_dt = pd.to_datetime(sample, errors="coerce", format="mixed")
            if as_dt.notna().mean() >= _DETECT_THRESHOLD:
                return pd.to_datetime(series, errors="coerce", format="mixed")

        return _text_key(series)
    except Exception:
        try:
            return _text_key(series)
        except Exception:
            return series


def sort_positions(frame, column: int, ascending: bool = True):
    """Row positions that put `frame` in order of its `column`-th column,
    or None if it cannot be done.

    Positions rather than a sorted frame, because the card's model needs
    them to `take()` and to keep its own row bookkeeping straight.

    The column is addressed by **position, not label**: a frame with two
    columns of the same name — a bad join or concat — is common enough,
    and ``sort_values(by="X")`` raises on it.
    """
    if not 0 <= column < len(getattr(frame, "columns", ())):
        return None
    try:
        key = pandas_sort_key(frame.iloc[:, column]).reset_index(drop=True)
        return key.sort_values(ascending=ascending, kind="stable",
                               na_position="last").index.to_numpy()
    except Exception:
        return None


def sorted_frame(frame, column: "str | None", ascending: bool = True):
    """`frame` ordered by the column *named* `column`, or unchanged.

    Unchanged is the answer to every "can't": no column named, a name the
    frame does not have, or a sort that raised. A table that quietly keeps
    its existing order is recoverable; one that raises in a render path
    blanks the card.
    """
    if not column:
        return frame
    names = [str(c) for c in getattr(frame, "columns", ())]
    try:
        index = names.index(str(column))
    except ValueError:
        return frame
    positions = sort_positions(frame, index, ascending)
    return frame if positions is None else frame.take(positions)
