"""Date Arithmetic

Work out how far apart two dates are, or move a date forward or back.

*Difference* subtracts *Start column* from an end — a second column, a fixed
*End date*, or today when both are left empty — and gives the gap in days,
business days (Monday to Friday), weeks, months or years. A negative number
means the end comes before the start. *Shift* adds *Amount* of that unit to
every date in *Start column* (negative moves back).

Months and years are whole calendar steps: a difference counts only completed
ones, and a shift clips to the month's last day (31 Jan + 1 month = 28 Feb).
Missing or unreadable dates give a missing result.
"""
NODE = {
    "label": "Date Arithmetic",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
_UNITS = ["days", "business days", "weeks", "months", "years"]
PARAMS = [
    {"name": "mode", "type": "choice", "label": "Mode",
     "options": ["difference", "shift"], "default": "difference"},
    {"name": "start_column", "type": "columns", "label": "Start column",
     "default": "", "multi": False},
    {"name": "end_column", "type": "columns", "label": "End column",
     "default": "", "multi": False,
     "placeholder": "empty = End date, else today",
     "visible_when": {"mode": ["difference"]}},
    {"name": "end_date", "type": "string", "label": "End date",
     "default": "", "placeholder": "e.g. 2026-12-31 (empty = today)",
     "visible_when": {"mode": ["difference"]}},
    {"name": "unit", "type": "choice", "label": "Unit", "options": _UNITS,
     "default": "days"},
    {"name": "amount", "type": "int", "label": "Amount to shift by",
     "default": 1, "min": -100000, "max": 100000,
     "visible_when": {"mode": ["shift"]}},
    {"name": "dayfirst", "type": "bool", "label": "Day first (03/04 = 3 April)",
     "default": False},
    {"name": "output_column", "type": "string", "label": "Output column",
     "default": "", "placeholder": "empty = automatic"},
]


def _dates(table, col, dayfirst):
    import warnings

    import pandas as pd

    if not col:
        raise ValueError("no column selected — set 'Start column'")
    if col not in table.columns:
        raise ValueError(f"column {col!r} not in table")
    src = table[col]
    if pd.api.types.is_datetime64_any_dtype(src):
        dt = src
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            dt = pd.to_datetime(src, errors="coerce", dayfirst=dayfirst)
    if dt.isna().all():
        raise ValueError(f"column {col!r} has no values that parse as dates")
    if dt.dt.tz is not None:
        dt = dt.dt.tz_localize(None)
    return dt


def _whole_months(a, b):
    """Completed calendar months from a to b (both datetime Series)."""
    months = (b.dt.year - a.dt.year) * 12 + (b.dt.month - a.dt.month)
    # Position inside the month: day, then time of day.
    pos_a = a.dt.day.astype('float64') * 86400 + (a - a.dt.normalize()).dt.total_seconds()
    pos_b = b.dt.day.astype('float64') * 86400 + (b - b.dt.normalize()).dt.total_seconds()
    # A month only counts once b has reached a's place in it (and, going
    # backwards, once b has passed it).
    months = months - ((months > 0) & (pos_b < pos_a)).astype("int64") \
        + ((months < 0) & (pos_b > pos_a)).astype("int64")
    return months.where(a.notna() & b.notna()).astype("Int64")


def run(ctx, table):
    import numpy as np
    import pandas as pd

    p = ctx.params
    unit = p["unit"]
    dayfirst = bool(p.get("dayfirst", False))
    start = _dates(table, p["start_column"].strip(), dayfirst)
    result = table.copy(deep=False)
    name = p["output_column"].strip()

    if p["mode"] == "shift":
        n = int(p["amount"])
        if unit == "days":
            out = start + pd.to_timedelta(n, unit="D")
        elif unit == "weeks":
            out = start + pd.to_timedelta(7 * n, unit="D")
        elif unit == "business days":
            valid = start.notna()
            out = start.copy()
            shifted = np.busday_offset(
                start[valid].values.astype("datetime64[D]"), n, roll="forward")
            clock = start[valid] - start[valid].dt.normalize()
            out[valid] = pd.to_datetime(shifted) + clock.values
        else:
            step = pd.DateOffset(months=n * (12 if unit == "years" else 1))
            out = start + step
        result[name or f"{p['start_column'].strip()}.shifted"] = out
        ctx.log(f"shifted {p['start_column']!r} by {n} {unit}")
        return result

    end_col = p["end_column"].strip()
    if end_col:
        end = _dates(table, end_col, dayfirst)
    else:
        text = p["end_date"].strip()
        stamp = pd.Timestamp.now().normalize() if not text \
            else pd.to_datetime(text, errors="coerce", dayfirst=dayfirst)
        if pd.isna(stamp):
            raise ValueError(f"'End date' {text!r} is not a date")
        end = pd.Series(stamp, index=table.index)

    if unit == "days":
        out = ((end - start).dt.total_seconds() / 86400).apply(
            lambda v: v if pd.isna(v) else float(np.trunc(v))).astype("Int64")
    elif unit == "weeks":
        out = ((end - start).dt.total_seconds() / (7 * 86400)).apply(
            lambda v: v if pd.isna(v) else float(np.trunc(v))).astype("Int64")
    elif unit == "business days":
        valid = start.notna() & end.notna()
        counts = pd.Series(pd.NA, index=table.index, dtype="Int64")
        counts[valid] = np.busday_count(
            start[valid].values.astype("datetime64[D]"),
            end[valid].values.astype("datetime64[D]"))
        out = counts
    else:
        months = _whole_months(start, end)
        out = months if unit == "months" else \
            months.apply(lambda v: v if pd.isna(v) else int(np.trunc(v / 12))
                         ).astype("Int64")
    label = f"{p['start_column'].strip()}.to_{end_col or 'end'}.{unit.replace(' ', '_')}"
    result[name or label] = out
    ctx.log(f"difference in {unit} -> {name or label!r}")
    return result
