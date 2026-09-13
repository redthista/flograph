"""Period Comparison

Add columns that compare a measure against a previous period — last
month's revenue next to this month's, the same quarter a year ago, the
year before — with the absolute delta and the change as a ratio
(0.12 = up 12%).

Pick the **Date column**, the **Measure** and the period it repeats over;
rows are aligned by that period and any **Group by** columns, so each
product line compares against its own history, never a neighbour's. Rows
are aggregated to the period first — **Aggregation** sums by default,
which is right for revenue; choose *mean* or another when the table
already holds one value per period or the measure is a rate — and the
comparison columns come back on every original row.

The new columns are named `{measure}_previous`, `{measure}_delta` and
`{measure}_pct`. The first period of a series has nothing to compare
against, so its three columns are missing there.
"""
NODE = {
    "label": "Period Comparison",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "date_column", "type": "columns", "label": "Date column",
     "default": "", "multi": False},
    {"name": "measure", "type": "columns", "label": "Measure",
     "default": "", "multi": False},
    {"name": "group_by", "type": "columns", "label": "Group by",
     "default": "", "placeholder": "empty = compare the whole table"},
    {"name": "period", "type": "choice", "label": "Period",
     "options": ["month", "quarter", "year"], "default": "month"},
    {"name": "basis", "type": "choice", "label": "Compare with",
     "options": ["previous period", "same period last year"],
     "default": "previous period"},
    {"name": "agg", "type": "choice", "label": "Aggregation",
     "options": ["sum", "mean", "median", "min", "max", "first", "last"],
     "default": "sum"},
]

_AGGS = ("sum", "mean", "median", "min", "max", "first", "last")


def _cols(raw):
    return [c.strip() for c in (raw or "").split(",") if c.strip()]


def _period_key(dates, period):
    """(year[, sub]) key per row — (2026, 8) for a month, (2026, 3) for a
    quarter, (2026,) for a year."""
    if period == "month":
        return list(zip(dates.dt.year, dates.dt.month))
    if period == "quarter":
        return list(zip(dates.dt.year, dates.dt.quarter))
    return list(zip(dates.dt.year,))


def _shift(key, period, steps):
    """The period key `steps` periods before (or after) `key`."""
    if period == "month":
        y, m = key
        total = y * 12 + (m - 1) + steps
        return (total // 12, total % 12 + 1)
    if period == "quarter":
        y, q = key
        total = y * 4 + (q - 1) + steps
        return (total // 4, total % 4 + 1)
    return (key[0] + steps,)


def run(ctx, table):
    import warnings

    import pandas as pd

    p = ctx.params
    date_col = (p.get("date_column") or "").strip()
    measure = (p.get("measure") or "").strip()
    groups = _cols(p.get("group_by"))
    period = p["period"]
    basis = p.get("basis", "previous period")
    agg = p.get("agg", "sum")

    for label, name in (("date", date_col), ("measure", measure)):
        if not name:
            raise ValueError(f"no {label} column selected — set "
                             f"'{label.title()} column'")
        if name not in table.columns:
            raise ValueError(f"{label} column {name!r} not in table")
    missing = [g for g in groups if g not in table.columns]
    if missing:
        raise ValueError(f"group column(s) {missing} not in table")
    if date_col in groups or measure in groups:
        raise ValueError(
            "'Date column' and 'Measure' must not be 'Group by' columns")
    if agg not in _AGGS:
        raise ValueError(f"unknown aggregation {agg!r}")
    if not pd.api.types.is_numeric_dtype(table[measure]):
        raise ValueError(f"measure column {measure!r} is "
                         f"{table[measure].dtype}, not numeric — convert it "
                         "with Convert Types first")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        dates = pd.to_datetime(table[date_col], errors="coerce")
    bad = dates.isna().sum()
    if bad == len(dates):
        raise ValueError(f"column {date_col!r} has no values that parse "
                         "as dates")
    if bad:
        raise ValueError(f"column {date_col!r} has {bad} row(s) that don't "
                         "parse as dates — fix or drop them first")

    steps = (-1 if basis == "previous period"
             else {"month": -12, "quarter": -4, "year": -1}[period])

    work = table.copy(deep=False)
    work["__key"] = pd.Series(_period_key(dates, period), index=table.index)
    work["__prior"] = work["__key"].map(
        lambda key: _shift(key, period, steps))

    period_table = (work.groupby(groups + ["__key"], as_index=False)
                    [measure].agg(agg))
    period_table["__prior"] = period_table["__key"].map(
        lambda key: _shift(key, period, steps))
    this = period_table.set_index(groups + ["__key"])[measure].rename(
        "__this")
    prior = period_table.set_index(groups + ["__key"])[measure].rename(
        "__prior_val")

    work = work.join(this, on=groups + ["__key"])
    work = work.join(prior, on=groups + ["__prior"])

    prev = work["__prior_val"]
    delta = work["__this"] - prev
    pct = (delta / prev).where(prev.notna() & (prev != 0))

    prev_name = f"{measure}_previous"
    delta_name = f"{measure}_delta"
    pct_name = f"{measure}_pct"
    result = work.drop(columns=["__key", "__prior", "__this", "__prior_val"])
    result[prev_name] = prev.values
    result[delta_name] = delta.values
    result[pct_name] = pct.values
    ctx.log(f"{measure!r} {basis} by {period}"
            + (f", per {'/'.join(groups)}" if groups else "")
            + f" → {prev_name}, {delta_name}, {pct_name}")
    return result