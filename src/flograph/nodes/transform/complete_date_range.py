"""Complete Date Range

Make every date in a span appear, so a daily (or weekly, monthly) series has
no holes. Rows you don't have are added with the date filled in and the other
columns left empty, set to 0, or carried forward from the last real row.

Choose a *Date column* and a *Step*. Add *Group by* columns to complete each
group on its own (one series per product, say); the group values are copied
onto the added rows. *Span* decides the ends: each group's own first and last
date, the whole table's, or an explicit *From* / *To*. Within a group each date
may appear once — aggregate first if it doesn't. Dates are floored to the step
(a week starts on Monday), and rows with no date are kept at the end.
"""
NODE = {
    "label": "Complete Date Range",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "date_column", "type": "columns", "label": "Date column",
     "default": "", "multi": False},
    {"name": "group_by", "type": "columns", "label": "Group by", "default": "",
     "multi": True, "placeholder": "empty = one series"},
    {"name": "step", "type": "choice", "label": "Step",
     "options": ["day", "week", "month", "quarter", "year"], "default": "day"},
    {"name": "span", "type": "choice", "label": "Span",
     "options": ["each group's own", "whole table", "explicit"],
     "default": "each group's own"},
    {"name": "start", "type": "string", "label": "From", "default": "",
     "placeholder": "explicit span only, e.g. 2026-01-01",
     "visible_when": {"span": ["explicit"]}},
    {"name": "end", "type": "string", "label": "To", "default": "",
     "placeholder": "explicit span only",
     "visible_when": {"span": ["explicit"]}},
    {"name": "fill", "type": "choice", "label": "Fill added rows with",
     "options": ["empty", "zero", "forward fill"], "default": "empty"},
    {"name": "dayfirst", "type": "bool", "label": "Day first (03/04 = 3 April)",
     "default": False},
]

_FREQ = {"day": "D", "week": "W-SUN", "month": "M", "quarter": "Q", "year": "Y"}


def run(ctx, table):
    import warnings

    import pandas as pd

    p = ctx.params
    col = p["date_column"].strip()
    if not col:
        raise ValueError("no column selected — set 'Date column'")
    if col not in table.columns:
        raise ValueError(f"column {col!r} not in table")
    groups = [c.strip() for c in p["group_by"].split(",") if c.strip()]
    bad = [g for g in groups if g not in table.columns]
    if bad:
        raise ValueError(f"group columns not in table: {bad}")
    if col in groups:
        raise ValueError("the date column cannot also be a group column")

    dayfirst = bool(p.get("dayfirst", False))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        dates = pd.to_datetime(table[col], errors="coerce", dayfirst=dayfirst)
    if dates.isna().all():
        raise ValueError(f"column {col!r} has no values that parse as dates")
    if dates.dt.tz is not None:
        dates = dates.dt.tz_localize(None)

    freq = _FREQ[p["step"]]
    period = "W-SUN" if freq == "W-SUN" else freq
    # Floor to the step: a period's start is its canonical date.
    floored = dates.dt.to_period(period).dt.start_time
    work = table.copy()
    work[col] = floored
    undated = work[floored.isna()]
    work = work[floored.notna()]

    key = groups + [col]
    if work.duplicated(subset=key).any():
        raise ValueError(
            f"{col!r} has repeated dates within a group — aggregate to one "
            "row per date first (Group By)")

    def span_of(frame):
        return (frame[col].min(), frame[col].max())

    if p["span"] == "explicit":
        lo = pd.to_datetime(p["start"].strip() or None, dayfirst=dayfirst)
        hi = pd.to_datetime(p["end"].strip() or None, dayfirst=dayfirst)
        if pd.isna(lo) or pd.isna(hi):
            raise ValueError("'explicit' span needs both 'From' and 'To'")
        lo = pd.Period(lo, period).start_time
        hi = pd.Period(hi, period).start_time
        fixed = (lo, hi)
    elif p["span"] == "whole table":
        fixed = span_of(work)
    else:
        fixed = None

    def full(lo, hi):
        return pd.period_range(lo, hi, freq=period).start_time

    pieces = []
    if groups:
        for gvals, sub in work.groupby(groups, dropna=False, sort=True):
            ctx.check_cancelled()
            lo, hi = fixed or span_of(sub)
            gvals = gvals if isinstance(gvals, tuple) else (gvals,)
            idx = full(lo, hi)
            sub = sub.set_index(col).reindex(idx)
            sub.index.name = col
            for g, v in zip(groups, gvals):
                sub[g] = v
            pieces.append(sub.reset_index())
    else:
        lo, hi = fixed or span_of(work)
        sub = work.set_index(col).reindex(full(lo, hi))
        sub.index.name = col
        pieces.append(sub.reset_index())
    out = pd.concat(pieces, ignore_index=True) if pieces else work.iloc[:0]
    out = out[list(table.columns)]

    added = ~out.set_index(key).index.isin(work.set_index(key).index)
    others = [c for c in out.columns if c not in key]
    if p["fill"] == "zero":
        for c in others:
            if pd.api.types.is_numeric_dtype(out[c]):
                out.loc[added, c] = 0
    elif p["fill"] == "forward fill":
        # Within each group, carry the last real row down into the gaps.
        if groups:
            out[others] = out.groupby(groups, dropna=False)[others].ffill()
        else:
            out[others] = out[others].ffill()
    if len(undated):
        out = pd.concat([out, undated], ignore_index=True)
    ctx.log(f"{int(added.sum())} row(s) added; {len(out)} total")
    return out
