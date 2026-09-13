"""Date Part

Pull pieces out of date/time columns, the way Power Query's *Date* menu
does — the year, the month number or name, the ISO week, the quarter, the day
of week, and so on. Or *floor* / *ceil* the date to the start / end of its
week / month / quarter / year so a daily series can be grouped into periods,
with an optional formatted label column (`2026-Q1`, `2026-08`).

Give one column or several (comma-separated) and one part or many: *Part*
is the common case, *More parts* takes one part name per line for the rest.
Every combination lands in its own new column, named automatically
(`order_date.year`, `ship_date.month_name`) unless a *single* new column is
being made and *Output column* names it.

Whole-number parts use nullable Int64 (missing stays missing); names and
times are strings; floors/ceilings stay datetimes. *Day of week* counts
Monday as 0, or Sunday as 0 when the week starts on Sunday. *Fiscal year*
is labelled by the calendar year it ends in — April 2024 is FY 2025 when
the year starts in April.
"""
NODE = {
    "label": "Date Part",
    "category": "Transform",
    "version": "2.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}

_PARTS = [
    "year", "quarter", "month", "month name", "iso week", "week of year",
    "day", "day of week", "day name", "day of year", "hour", "minute",
    "second", "date only", "time only",
    "start of week", "start of month", "start of quarter", "start of year",
    "end of week", "end of month", "end of quarter", "end of year",
    "is weekend", "days in month", "unix seconds",
    "age in days", "age in months", "age in years",
    "fiscal year", "fiscal quarter",
]

PARAMS = [
    {"name": "column", "type": "columns", "label": "Date column(s)",
     "default": "", "multi": True,
     "placeholder": "one column, or several comma-separated"},
    {"name": "part", "type": "choice", "label": "Part", "options": _PARTS,
     "default": "year"},
    {"name": "extra_parts", "type": "text", "label": "More parts (one per line)",
     "default": "", "placeholder": "e.g.\nmonth\nday name"},
    {"name": "output_column", "type": "string", "label": "Output column",
     "default": "", "placeholder": "single new column only — empty = automatic"},
    {"name": "label_format", "type": "string", "label": "Label format",
     "default": "", "placeholder": "strftime, e.g. %Y-Q%q or %Y-%m"},
    {"name": "week_starts_monday", "type": "bool", "label": "Week starts Monday",
     "default": True},
    {"name": "dayfirst", "type": "bool", "label": "Day first (03/04 = 3 April)",
     "default": False},
    {"name": "fiscal_start", "type": "int", "label": "Fiscal year starts in (1=Jan)",
     "default": 1, "min": 1, "max": 12},
]


def _q_strftime(dt_series, fmt):
    # strftime has no quarter token; emulate %q -> quarter number.
    import pandas as pd
    if "%q" not in fmt:
        return dt_series.dt.strftime(fmt).astype("string")
    q = dt_series.dt.quarter.astype("string")
    out = []
    for stamp, qq in zip(dt_series, q):
        if pd.isna(stamp):
            out.append(pd.NA)
        else:
            out.append(stamp.strftime(fmt.replace("%q", qq)))
    return pd.array(out, dtype="string")


def _parse_date_column(table, col, dayfirst):
    """The column as datetimes, or raise naming the column."""
    import warnings

    import pandas as pd

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
    return dt


def _extract(dt, part, week_anchor, monday, fiscal_start, today):
    """One part of a datetime Series."""
    import pandas as pd

    def ints(values):
        return pd.Series(values, index=dt.index).astype("Int64")

    if part == "year":
        return ints(dt.dt.year)
    elif part == "quarter":
        return ints(dt.dt.quarter)
    elif part == "month":
        return ints(dt.dt.month)
    elif part == "month name":
        return dt.dt.month_name().astype("string")
    elif part in ("iso week", "week of year"):
        return dt.dt.isocalendar().week.astype("Int64")
    elif part == "day":
        return ints(dt.dt.day)
    elif part == "day of week":
        # .dt.dayofweek reports NaT as -1, so mask it back to missing.
        dow = pd.Series(dt.dt.dayofweek, index=dt.index).where(dt.notna())
        return (dow if monday else (dow + 1) % 7).astype("Int64")
    elif part == "day name":
        return dt.dt.day_name().astype("string")
    elif part == "day of year":
        return ints(dt.dt.dayofyear)
    elif part == "hour":
        return ints(dt.dt.hour)
    elif part == "minute":
        return ints(dt.dt.minute)
    elif part == "second":
        return ints(dt.dt.second)
    elif part == "date only":
        return dt.dt.normalize()
    elif part == "time only":
        return dt.dt.strftime("%H:%M:%S").astype("string")
    elif part == "start of week":
        return dt.dt.to_period(week_anchor).dt.start_time
    elif part == "start of month":
        return dt.dt.to_period("M").dt.start_time
    elif part == "start of quarter":
        return dt.dt.to_period("Q").dt.start_time
    elif part == "start of year":
        return dt.dt.to_period("Y").dt.start_time
    elif part == "end of week":
        return dt.dt.to_period(week_anchor).dt.end_time.dt.normalize()
    elif part == "end of month":
        return dt.dt.to_period("M").dt.end_time.dt.normalize()
    elif part == "end of quarter":
        return dt.dt.to_period("Q").dt.end_time.dt.normalize()
    elif part == "end of year":
        return dt.dt.to_period("Y").dt.end_time.dt.normalize()
    elif part == "is weekend":
        return (dt.dt.dayofweek >= 5).where(dt.notna()).astype("boolean")
    elif part == "days in month":
        return ints(dt.dt.days_in_month)
    elif part == "unix seconds":
        # astype("int64") is resolution-dependent (s/ms/us/ns), so go via
        # epoch subtraction, which always yields true seconds.
        try:
            epoch = pd.Timestamp("1970-01-01", tz=dt.dt.tz)
            secs = (dt - epoch).dt.total_seconds()
        except Exception:
            secs = dt.dt.timestamp()
        return ints(secs)
    elif part == "age in days":
        return ints((today - dt.dt.normalize()).dt.days)
    elif part == "age in years":
        had_birthday = ((dt.dt.month < today.month)
                        | ((dt.dt.month == today.month)
                           & (dt.dt.day <= today.day)))
        return ints(today.year - dt.dt.year - (~had_birthday).astype(int))
    elif part == "age in months":
        return ints((today.year - dt.dt.year) * 12
                    + (today.month - dt.dt.month)
                    - (today.day < dt.dt.day).astype(int))
    elif part == "fiscal year":
        y, m = dt.dt.year, dt.dt.month
        return ints(y + (((m >= fiscal_start) & (fiscal_start > 1))).astype(int))
    elif part == "fiscal quarter":
        return ints(((dt.dt.month - fiscal_start) % 12) // 3 + 1)
    raise ValueError(f"unknown part: {part!r}")


def run(ctx, table):
    import pandas as pd

    p = ctx.params
    cols = [c.strip() for c in str(p["column"]).split(",") if c.strip()]
    if not cols:
        raise ValueError("no column selected — set 'Date column(s)'")

    parts = [p["part"]]
    for line in str(p.get("extra_parts", "")).splitlines():
        name = line.strip().lower()
        if not name:
            continue
        matches = [c for c in _PARTS if c == name]
        if not matches:
            valid = ", ".join(_PARTS)
            raise ValueError(
                f"unknown part {line.strip()!r} in 'More parts' "
                f"(valid: {valid})")
        if matches[0] not in parts:
            parts.append(matches[0])

    explicit = p["output_column"].strip()
    if explicit and (len(cols) > 1 or len(parts) > 1):
        n = len(cols) * len(parts)
        raise ValueError(
            f"'Output column' names one column but {n} would be created — "
            "clear it for automatic names")

    monday = bool(p["week_starts_monday"])
    week_anchor = "W-SUN" if monday else "W-SAT"
    fiscal_start = int(p.get("fiscal_start", 1) or 1)
    if not 1 <= fiscal_start <= 12:
        raise ValueError(
            f"'Fiscal year starts in' must be 1-12, got {fiscal_start}")
    today = pd.Timestamp.now().normalize()
    fmt = p["label_format"].strip()

    result = table.copy(deep=False)
    made = []
    for col in cols:
        dt = _parse_date_column(table, col, bool(p.get("dayfirst", False)))
        for part in parts:
            name = explicit or f"{col}.{part.replace(' ', '_')}"
            result[name] = _extract(
                dt, part, week_anchor, monday, fiscal_start, today).values
            made.append((name, dt))
            explicit = ""  # an explicit name can only be spent once

    for name, dt in made:
        if fmt:
            result[f"{name}.label"] = _q_strftime(dt, fmt)

    ctx.log(f"{len(cols)} column(s) × {len(parts)} part(s) → "
            + ", ".join(repr(n) for n, _ in made)
            + (f" (+{len(made)} labels)" if fmt else ""))
    return result
