"""Date Part

Pull a piece out of a date/time column, the way Power Query's *Date* menu
does — the year, the month number or name, the ISO week, the quarter, the day
of week, and so on. Or *floor* the date to the start of its week / month /
quarter / year so a daily series can be grouped into periods, with an
optional formatted label column (`2026-Q1`, `2026-08`).

The source column is parsed to datetime if it isn't already. The result lands
in a new column — named automatically (`order_date.year`) unless you set
*Output column*.
"""
NODE = {
    "label": "Date Part",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}

_PARTS = [
    "year", "quarter", "month", "month name", "iso week", "week of year",
    "day", "day of week", "day name", "day of year", "hour", "minute",
    "second", "date only", "time only",
    "start of week", "start of month", "start of quarter", "start of year",
    "end of month", "end of quarter", "end of year",
    "age in days",
]

PARAMS = [
    {"name": "column", "type": "columns", "label": "Date column",
     "default": "", "multi": False},
    {"name": "part", "type": "choice", "label": "Part", "options": _PARTS,
     "default": "year"},
    {"name": "output_column", "type": "string", "label": "Output column",
     "default": "", "placeholder": "empty = <column>.<part>"},
    {"name": "label_format", "type": "string", "label": "Label format",
     "default": "", "placeholder": "strftime, e.g. %Y-Q%q or %Y-%m"},
    {"name": "week_starts_monday", "type": "bool", "label": "Week starts Monday",
     "default": True},
]


def _q_strftime(dt_series, fmt):
    # strftime has no quarter token; emulate %q -> quarter number.
    import pandas as pd
    if "%q" not in fmt:
        return dt_series.dt.strftime(fmt)
    q = dt_series.dt.quarter.astype("string")
    out = []
    for stamp, qq in zip(dt_series, q):
        if pd.isna(stamp):
            out.append(pd.NA)
        else:
            out.append(stamp.strftime(fmt.replace("%q", qq)))
    return pd.array(out, dtype="string")


def run(ctx, table):
    import warnings

    import pandas as pd

    p = ctx.params
    col = p["column"].strip()
    if not col:
        raise ValueError("no column selected — set 'Date column'")
    if col not in table.columns:
        raise ValueError(f"column {col!r} not in table")

    src = table[col]
    if pd.api.types.is_datetime64_any_dtype(src):
        dt = src
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            dt = pd.to_datetime(src, errors="coerce")
    if dt.isna().all():
        raise ValueError(f"column {col!r} has no values that parse as dates")

    part = p["part"]
    week_anchor = "W-SUN" if p["week_starts_monday"] else "W-SAT"

    if part == "year":
        out = dt.dt.year
    elif part == "quarter":
        out = dt.dt.quarter
    elif part == "month":
        out = dt.dt.month
    elif part == "month name":
        out = dt.dt.month_name()
    elif part in ("iso week", "week of year"):
        out = dt.dt.isocalendar().week.astype("Int64")
    elif part == "day":
        out = dt.dt.day
    elif part == "day of week":
        out = dt.dt.dayofweek if p["week_starts_monday"] else \
            (dt.dt.dayofweek + 1) % 7
    elif part == "day name":
        out = dt.dt.day_name()
    elif part == "day of year":
        out = dt.dt.dayofyear
    elif part == "hour":
        out = dt.dt.hour
    elif part == "minute":
        out = dt.dt.minute
    elif part == "second":
        out = dt.dt.second
    elif part == "date only":
        out = dt.dt.normalize()
    elif part == "time only":
        out = dt.dt.strftime("%H:%M:%S")
    elif part == "start of week":
        out = dt.dt.to_period(week_anchor).dt.start_time
    elif part == "start of month":
        out = dt.dt.to_period("M").dt.start_time
    elif part == "start of quarter":
        out = dt.dt.to_period("Q").dt.start_time
    elif part == "start of year":
        out = dt.dt.to_period("Y").dt.start_time
    elif part == "end of month":
        out = dt.dt.to_period("M").dt.end_time.dt.normalize()
    elif part == "end of quarter":
        out = dt.dt.to_period("Q").dt.end_time.dt.normalize()
    elif part == "end of year":
        out = dt.dt.to_period("Y").dt.end_time.dt.normalize()
    elif part == "age in days":
        out = (pd.Timestamp.now().normalize() - dt.dt.normalize()).dt.days
    else:
        raise ValueError(f"unknown part: {part!r}")

    result = table.copy(deep=False)
    name = p["output_column"].strip() or f"{col}.{part.replace(' ', '_')}"
    result[name] = out.values

    fmt = p["label_format"].strip()
    if fmt:
        result[f"{name}.label"] = _q_strftime(dt, fmt)

    ctx.log(f"{col!r} → {name!r} ({part})"
            + (f" + {name}.label" if fmt else ""))
    return result
