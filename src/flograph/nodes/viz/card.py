"""Card

A Power BI-style KPI card: aggregates one column of the incoming table down
to a single value (sum, average, count, …) and shows it big on the canvas.
The raw value is also emitted on the "value" port so it can feed further
logic. Use "Format" for a Python format spec (e.g. ",.2f" or ".1%"); leave
"Label" blank to caption the card with "<Aggregation> of <column>".
"""
NODE = {
    "label": "Card",
    "category": "Viz",
    "card": "kpi",
    "inputs": [("table", "dataframe")],
    "outputs": [("value", "any")],
}
PARAMS = [
    {"name": "column", "type": "columns", "label": "Column",
     "default": "", "multi": False},
    {"name": "aggregation", "type": "choice", "label": "Aggregation",
     "options": ["Sum", "Average", "Median", "Min", "Max",
                 "Count", "Distinct count", "First", "Last"],
     "default": "Sum"},
    {"name": "label", "type": "string", "label": "Label",
     "default": "", "placeholder": "Caption under the value"},
    {"name": "format", "type": "string", "label": "Format",
     "default": "", "placeholder": "Python format spec, e.g. ,.2f"},
    {"name": "width", "type": "int", "label": "Width",
     "default": 220, "min": 140, "max": 800},
    {"name": "height", "type": "int", "label": "Height",
     "default": 120, "min": 80, "max": 500},
]


def run(ctx, table):
    column = str(ctx.params.get("column", "")).strip()
    if not column:
        raise ValueError(
            "no column selected — set 'Column' in the node's properties")
    if column not in table.columns:
        available = ", ".join(str(c) for c in table.columns)
        raise ValueError(f"column {column!r} not in table (has: {available})")

    col = table[column]
    aggregation = ctx.params.get("aggregation", "Sum")
    if aggregation == "Count":
        value = int(col.count())  # non-null count, like Power BI
    elif aggregation == "Distinct count":
        value = int(col.nunique())
    elif aggregation in ("First", "Last"):
        if len(col) == 0:
            raise ValueError("table has no rows — nothing to show")
        value = col.iloc[0 if aggregation == "First" else -1]
    else:
        method = {"Sum": "sum", "Average": "mean", "Median": "median",
                  "Min": "min", "Max": "max"}[aggregation]
        try:
            value = getattr(col, method)()
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"cannot compute {aggregation} of column {column!r} "
                f"(dtype {col.dtype}): {exc}") from exc
    if hasattr(value, "item"):  # numpy scalar -> plain Python
        value = value.item()
    ctx.log(f"{aggregation}({column}) = {value!r}")
    return {"value": value}
