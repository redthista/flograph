"""Window Function

SQL window semantics as one node: partition the rows, order them, and add a
column computed over each partition without collapsing it — the thing you'd
write `OVER (PARTITION BY ... ORDER BY ...)` for.

Pick a **function**:

    row_number   rank      dense_rank    percent_rank    ntile
    lag          lead      cumsum        cummax          cummin
    running_avg  pct_of_partition        rolling_mean    rolling_sum

`row_number` / `rank` / `dense_rank` / `percent_rank` / `ntile` need only an
order; `lag` / `lead` / `cumsum` / the rolling and pct ones need a **value
column** too. `N` comes from the **Parameter** field (lag/lead offset, ntile
bucket count, or rolling window size).

The output column is named after the function unless you set **Output
column**. Rows come back in their original order.
"""
NODE = {
    "label": "Window Function",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "function", "type": "choice", "label": "Function",
     "options": [
         "row_number", "rank", "dense_rank", "percent_rank", "ntile",
         "lag", "lead", "cumsum", "cummax", "cummin",
         "running_avg", "pct_of_partition", "rolling_mean", "rolling_sum",
     ], "default": "row_number"},
    {"name": "partition_by", "type": "columns", "label": "Partition by",
     "default": "", "placeholder": "empty = whole table is one partition"},
    {"name": "order_by", "type": "columns", "label": "Order by",
     "default": "", "placeholder": "comma separated"},
    {"name": "descending", "type": "bool", "label": "Order descending",
     "default": False},
    {"name": "value_column", "type": "columns", "label": "Value column",
     "default": "", "multi": False,
     "placeholder": "for lag/lead/cumsum/rolling/pct"},
    {"name": "param_n", "type": "int", "label": "Parameter (N)",
     "default": 1, "min": 1, "max": 100000},
    {"name": "output_column", "type": "string", "label": "Output column",
     "default": "", "placeholder": "empty = name after the function"},
]

_NEEDS_VALUE = {"lag", "lead", "cumsum", "cummax", "cummin", "running_avg",
                "pct_of_partition", "rolling_mean", "rolling_sum"}
_NEEDS_ORDER = {"row_number", "rank", "dense_rank", "percent_rank", "ntile",
                "lag", "lead"}


def _cols(raw):
    return [c.strip() for c in (raw or "").split(",") if c.strip()]


def run(ctx, table):
    import numpy as np
    import pandas as pd

    p = ctx.params
    fn = p["function"]
    part = _cols(p.get("partition_by"))
    order = _cols(p.get("order_by"))
    value = (p.get("value_column") or "").strip()
    n = max(1, int(p.get("param_n", 1) or 1))
    out_name = (p.get("output_column") or "").strip() or fn

    for label, cols in (("partition", part), ("order", order)):
        missing = [c for c in cols if c not in table.columns]
        if missing:
            raise ValueError(f"{label} column(s) {missing} not in the table")
    if fn in _NEEDS_VALUE:
        if not value:
            raise ValueError(f"{fn} needs a value column — set 'Value column'")
        if value not in table.columns:
            raise ValueError(f"value column {value!r} not in the table")
    if fn in _NEEDS_ORDER and not order:
        raise ValueError(f"{fn} needs an order — set 'Order by'")

    # Work on a positional copy so the result can be restored to input order.
    work = table.reset_index(drop=True)
    work["__pos"] = np.arange(len(work))
    if order:
        work = work.sort_values(order, ascending=not p.get("descending", False),
                                kind="stable")

    # A single-group fallback keeps one code path for partitioned and not.
    if part:
        g = work.groupby(part, sort=False)
        gv = g[value] if value else None
        size = g["__pos"].transform("size")
        within = g.cumcount()
    else:
        g = None
        gv = work[value] if value else None
        size = pd.Series(len(work), index=work.index)
        within = pd.Series(np.arange(len(work)), index=work.index)

    if fn == "row_number":
        res = within + 1
    elif fn in ("rank", "dense_rank", "percent_rank"):
        method = "dense" if fn == "dense_rank" else "min"
        key = order[0]
        col = g[key] if g is not None else work[key]
        res = col.rank(method=method, pct=(fn == "percent_rank"),
                       ascending=not p.get("descending", False))
    elif fn == "ntile":
        res = (within * n // size.replace(0, 1)) + 1
    elif fn == "lag":
        res = gv.shift(n)
    elif fn == "lead":
        res = gv.shift(-n)
    elif fn in ("cumsum", "cummax", "cummin"):
        res = getattr(gv, fn)()
    elif fn == "running_avg":
        res = (gv.expanding().mean().reset_index(level=0, drop=True)
               if g is not None else gv.expanding().mean())
    elif fn == "pct_of_partition":
        total = g[value].transform("sum") if g is not None else work[value].sum()
        res = work[value] / total
    elif fn in ("rolling_mean", "rolling_sum"):
        agg = "mean" if fn == "rolling_mean" else "sum"
        if g is not None:
            res = getattr(gv.rolling(n, min_periods=1), agg)() \
                .reset_index(level=0, drop=True)
        else:
            res = getattr(gv.rolling(n, min_periods=1), agg)()
    else:  # pragma: no cover - guarded by the choice widget
        raise ValueError(f"unknown function {fn!r}")

    # Assign by index label so a group-sorted result still lands on the right
    # rows, then restore the table's original order.
    work[out_name] = res
    work = work.sort_values("__pos", kind="stable").drop(columns="__pos")
    ctx.log(f"{fn} → {out_name!r} over "
            f"{'/'.join(part) if part else 'whole table'}")
    return work.reset_index(drop=True)
