"""Table

A spreadsheet you fill in directly on the canvas — type values into the grid
and they flow out as a DataFrame. No inputs; drop it wherever you need
literal tabular data. Use the +Row/+Col buttons on the card to grow the
grid, and double-click a column header to rename it.
"""
import json

NODE = {
    "label": "Table",
    "category": "IO",
    "inputs": [],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "data", "type": "text", "label": "Table data (JSON)",
     "default": json.dumps({"columns": ["A", "B"], "rows": [["", ""], ["", ""]]})},
    {"name": "width", "type": "int", "label": "Width",
     "default": 320, "min": 220, "max": 1600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 220, "min": 140, "max": 2000},
]


def _coerce_column(values):
    """Best-effort numeric coercion for a column of strings; None means
    "leave the whole column as strings" (mixed or non-numeric content)."""
    numeric = []
    for v in values:
        if v is None or v == "":
            numeric.append(None)
            continue
        try:
            numeric.append(int(v))
            continue
        except (TypeError, ValueError):
            pass
        try:
            numeric.append(float(v))
        except (TypeError, ValueError):
            return None
    return numeric


def run(ctx):
    import pandas as pd

    data = json.loads(ctx.params["data"] or "{}")
    columns = list(data.get("columns") or [])
    rows = data.get("rows") or []
    if not columns:
        return pd.DataFrame()

    # defend against hand-edited JSON where row lengths drift from columns
    fixed_rows = []
    for row in rows:
        row = list(row)[:len(columns)]
        row += [""] * (len(columns) - len(row))
        fixed_rows.append(row)

    table = pd.DataFrame(fixed_rows, columns=columns)
    for col in table.columns:
        numeric = _coerce_column(table[col].tolist())
        if numeric is not None:
            table[col] = numeric
    ctx.log(f"{len(table)} rows x {len(table.columns)} columns")
    return table
