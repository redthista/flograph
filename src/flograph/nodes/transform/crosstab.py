"""Crosstab

A two-way frequency matrix from two category columns — rows on one side,
columns on the other, a count in every cell. The device × browser grid or
product × region matrix you'd hand-build as a Pivot with two aggregations,
as one step. The result is an ordinary table, so it feeds Group By, a
chart, or Write Excel like anything else.

Counts by default; give a **Values** column to aggregate it instead, with
the **Aggregation** to apply. **Normalise** rescales the cells to shares
of the row, column, or whole table. **Fill value** replaces empty cells;
**Row and column totals** adds a Total row and column (labelled by
**Total label**). Categories keep the order they first appear in the table
unless **Order** is set to sorted; missing categories are dropped by
default, kept as their own row/column when **Keep missing** is on.
"""
NODE = {
    "label": "Crosstab",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "rows", "type": "columns", "label": "Rows", "default": "",
     "multi": False},
    {"name": "cols", "type": "columns", "label": "Columns", "default": "",
     "multi": False},
    {"name": "values", "type": "columns", "label": "Values", "default": "",
     "multi": False, "placeholder": "empty = count the rows"},
    {"name": "agg", "type": "choice", "label": "Aggregation",
     "options": ["sum", "mean", "median", "min", "max", "first", "last"],
     "default": "sum"},
    {"name": "normalize", "type": "choice", "label": "Normalise",
     "options": ["none", "rows", "columns", "all"], "default": "none"},
    {"name": "fill_value", "type": "string", "label": "Fill value",
     "default": "", "placeholder": "empty = leave blank"},
    {"name": "keep_missing", "type": "bool", "label": "Keep missing",
     "default": False},
    {"name": "margins", "type": "bool", "label": "Row and column totals",
     "default": False},
    {"name": "margins_name", "type": "string", "label": "Total label",
     "default": "Total"},
    {"name": "order", "type": "choice", "label": "Order",
     "options": ["as seen", "sorted"], "default": "as seen"},
]


def _seen(series):
    """The series' distinct values in order of first appearance."""
    return list(dict.fromkeys(series.dropna().tolist()))


def run(ctx, table):
    import pandas as pd

    p = ctx.params
    rows = (p.get("rows") or "").strip()
    cols = (p.get("cols") or "").strip()
    if not rows:
        raise ValueError("no row column selected — set 'Rows'")
    if not cols:
        raise ValueError("no column column selected — set 'Columns'")
    for label, name in (("row", rows), ("column", cols)):
        if name not in table.columns:
            raise ValueError(f"{label} column {name!r} not in table")
    values = (p.get("values") or "").strip()
    if values and values not in table.columns:
        raise ValueError(f"values column {values!r} not in table")
    if values and values in (rows, cols):
        raise ValueError(
            "'Values' must be a different column from Rows and Columns")

    kwargs = {}
    if values:
        kwargs["values"] = table[values]
        kwargs["aggfunc"] = p["agg"]
    normalize = p.get("normalize", "none")
    if normalize != "none":
        kwargs["normalize"] = {"rows": "index"}.get(normalize, normalize)
    fill = (p.get("fill_value") or "").strip()
    if fill:
        try:
            fill = float(fill)
        except ValueError:
            pass
        kwargs["fill_value"] = fill
    margins = bool(p.get("margins", False))
    if margins:
        kwargs["margins"] = True
        kwargs["margins_name"] = p.get("margins_name") or "Total"

    result = pd.crosstab(table[rows], table[cols],
                         dropna=not bool(p.get("keep_missing", False)),
                         **kwargs)

    if p.get("order", "as seen") == "as seen":
        seen_rows = _seen(table[rows])
        seen_cols = _seen(table[cols])
        result = result.reindex(
            index=seen_rows + [i for i in result.index if i not in seen_rows],
            columns=seen_cols
            + [c for c in result.columns if c not in seen_cols])

    ctx.log(f"{rows!r} × {cols!r} → a {result.shape[0]}×{result.shape[1]} "
            "table"
            + (" (counts)" if not values else f" of {values!r} {p['agg']}"))
    return result