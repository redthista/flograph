"""Pivot

Pivot a long table into a wide one: rows grouped by the index
columns, one output column per distinct value of the pivot column, cells
aggregated.

With a single value column the output columns are the bare pivot values
(`Jan`, `Feb`) — no prefix to strip afterwards.

**Column names** matters once several value columns are listed, when each
output column has to carry its value to stay apart. *Value first*
(`revenue_Jan`) is the classic; *pivot first* (`Jan_revenue`) scans
better across months; *values only* drops the value name
Power-Query-style (`Jan`) and dedupes collisions with ` (2)`, ` (3)`.
**Name separator** joins the parts, so ` / ` gives `revenue / Jan`.

**Empty cells** have no rows behind them and come back blank; put `0`
there to fill them, which is what a sum or count usually wants.

**Grand totals** adds a total row and/or column under **Total label**,
aggregated from the underlying rows with the same aggregation — a mean
total is the mean of the rows, not of the displayed cells.

**Order** decides how the new rows and columns are arranged. *As they
appear* (the default) keeps the order the incoming table is already in, so
a table sorted into Jan, Feb, Mar pivots into columns in that order.
*Sorted* arranges them alphabetically instead, which is what pandas does on
its own — and is why a month column used to come back Apr, Aug, Dec. A sort
set upstream is a decision, so the default is to keep it; there is nowhere
downstream to put it back, since the pivot is what invented the columns.
"""
NODE = {
    "label": "Pivot",
    "category": "Transform",
    "version": "1.2",
    "inputs": [("table", "dataframe")],
    "outputs": [("pivoted", "dataframe")],
}
PARAMS = [
    {"name": "index", "type": "columns", "label": "Group by (rows)",
     "default": "", "placeholder": "comma separated"},
    {"name": "columns", "type": "columns", "label": "Pivot column(s)",
     "default": "", "placeholder": "comma separated"},
    {"name": "values", "type": "columns", "label": "Value columns",
     "default": "", "placeholder": "empty = all others"},
    {"name": "agg", "type": "choice", "label": "Aggregation",
     "options": ["sum", "mean", "median", "min", "max", "count",
                 "distinct count", "std", "first"],
     "default": "sum"},
    {"name": "headers", "type": "choice", "label": "Column names",
     "options": ["value first", "values only", "pivot first"],
     "default": "value first"},
    {"name": "separator", "type": "string", "label": "Name separator",
     "default": "_"},
    {"name": "fill", "type": "string", "label": "Empty cells fill",
     "default": "", "placeholder": "empty = leave blank, e.g. 0"},
    {"name": "totals", "type": "choice", "label": "Grand totals",
     "options": ["off", "rows + columns", "rows only", "columns only"],
     "default": "off"},
    {"name": "total_label", "type": "string", "label": "Total label",
     "default": "Total"},
    {"name": "order", "type": "choice", "label": "Row / column order",
     "options": ["as they appear", "sorted"], "default": "as they appear"},
]


def _fill_scalar(raw):
    """The Empty-cells box as a value: blank stays blank, numbers come
    back as numbers so a sum pivot fills with 0 rather than "0"."""
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def run(ctx, table):
    def cols(name, required):
        raw = ctx.params[name].strip()
        if not raw:
            if required:
                raise ValueError(f"no {name} columns listed")
            return None
        listed = [c.strip() for c in raw.split(",") if c.strip()]
        missing = [c for c in listed if c not in table.columns]
        if missing:
            raise ValueError(f"columns not in table: {missing}")
        return listed

    index = cols("index", required=True)
    columns = cols("columns", required=True)
    values = cols("values", required=False)
    from flograph.core.matrix import pivot

    # `.get`, not `[]`: a project saved before the node grew a param keeps
    # working by taking the new default like everything else.
    params = ctx.params
    pivoted = pivot(table, index, columns, values,
                    params.get("agg") or "sum",
                    params.get("order") or "as they appear",
                    headers=params.get("headers") or "value first",
                    separator=params.get("separator", "_"),
                    fill=_fill_scalar(params.get("fill")),
                    totals=params.get("totals") or "off",
                    total_label=(params.get("total_label") or "Total"))
    ctx.log(f"{len(table)} rows -> {len(pivoted)} x {len(pivoted.columns)}")
    return pivoted
