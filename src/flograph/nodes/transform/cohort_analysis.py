"""Cohort Analysis

Group people by when they first turned up, and count how many are still
there each period after — the signup-month retention table.

Pick the column that says **who** (a customer, user or account id) and the
**date** of each event. Every row is labelled with its person's **cohort** —
the period of their first event — and a **period** index: 0 for the period
they joined in, 1 for the next, and so on. That labelled table comes out of
**table**, ready for a Group By or a Crosstab of your own.

**retention** is the matrix itself: one row per cohort, its **cohort_size**,
then a column per period counting the distinct people active in it. Set
**Show retention as** to *percent* to divide each by the cohort's size, so
cohorts of different sizes compare at a glance (period 0 is always 1.0).

**Cohort by** and **Count periods in** can differ — monthly cohorts measured
week by week. **Smallest cohort** drops cohorts with fewer people than that,
so a cohort of three doesn't swing the chart.
"""
NODE = {
    "label": "Cohort Analysis",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe"), ("retention", "dataframe")],
}
PARAMS = [
    {"name": "user_id", "type": "columns", "label": "Person column",
     "default": "", "multi": False, "placeholder": "customer / user id"},
    {"name": "date_column", "type": "columns", "label": "Date column",
     "default": "", "multi": False},
    {"name": "cohort_unit", "type": "choice", "label": "Cohort by",
     "options": ["day", "week", "month", "quarter", "year"],
     "default": "month"},
    {"name": "period_unit", "type": "choice", "label": "Count periods in",
     "options": ["same as cohort", "day", "week", "month", "quarter", "year"],
     "default": "same as cohort"},
    {"name": "min_count", "type": "int", "label": "Smallest cohort",
     "default": 1, "min": 1, "max": 1_000_000},
    {"name": "retention_as", "type": "choice", "label": "Show retention as",
     "options": ["count", "percent"], "default": "count"},
]

# Weeks run Monday to Sunday ("W-SUN" is the week *ending* Sunday).
_FREQ = {"day": "D", "week": "W-SUN", "month": "M", "quarter": "Q",
         "year": "Y"}


def _label(periods, unit):
    """A cohort label that sorts as text: 2026-01, 2026-Q1, 2026, or the
    start date for days and weeks."""
    if unit in ("day", "week"):
        return periods.dt.start_time.dt.strftime("%Y-%m-%d")
    if unit == "quarter":
        return periods.dt.year.astype(str) + "-Q" + periods.dt.quarter.astype(str)
    if unit == "year":
        return periods.dt.year.astype(str)
    return periods.dt.strftime("%Y-%m")


def run(ctx, table):
    import warnings

    import pandas as pd

    p = ctx.params
    who = str(p["user_id"]).strip()
    col = str(p["date_column"]).strip()
    if not who:
        raise ValueError("no column selected — set 'Person column'")
    if not col:
        raise ValueError("no column selected — set 'Date column'")
    for name in (who, col):
        if name not in table.columns:
            raise ValueError(f"column {name!r} not in table")
    if who == col:
        raise ValueError("the person and date columns must differ")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        dates = pd.to_datetime(table[col], errors="coerce")
    if dates.isna().all():
        raise ValueError(f"column {col!r} has no values that parse as dates")
    if dates.dt.tz is not None:
        dates = dates.dt.tz_localize(None)

    cohort_unit = p["cohort_unit"]
    period_unit = p["period_unit"]
    if period_unit == "same as cohort":
        period_unit = cohort_unit

    keep = dates.notna() & table[who].notna()
    dropped = int((~keep).sum())
    work = table[keep].copy()
    dates = dates[keep]
    first = dates.groupby(work[who]).transform("min")

    cohort = _label(first.dt.to_period(_FREQ[cohort_unit]), cohort_unit)
    freq = _FREQ[period_unit]
    index = (dates.dt.to_period(freq).array.asi8
             - first.dt.to_period(freq).array.asi8)
    work["cohort"] = cohort.values
    work["period"] = index

    sizes = work.groupby("cohort")[who].nunique()
    small = sizes[sizes < int(p["min_count"])].index
    if len(small):
        work = work[~work["cohort"].isin(small)]
        sizes = sizes.drop(small)
    if work.empty:
        raise ValueError(
            "no cohort has at least 'Smallest cohort' people — lower it")

    active = (work.groupby(["cohort", "period"])[who].nunique()
              .unstack("period").sort_index(axis=1))
    if p["retention_as"] == "percent":
        active = active.div(sizes, axis=0)
    else:
        active = active.astype("Int64")
    retention = active.reset_index()
    retention.insert(1, "cohort_size", sizes.reindex(active.index).values)
    retention.columns = [str(c) for c in retention.columns]

    ctx.log(f"{len(sizes)} cohort(s) by {cohort_unit}, periods in "
            f"{period_unit}s, {sizes.sum()} people"
            + (f"; {dropped} row(s) without a person or date left out"
               if dropped else "")
            + (f"; {len(small)} cohort(s) under the minimum dropped"
               if len(small) else ""))
    return {"table": work, "retention": retention}
