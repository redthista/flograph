"""Select Columns

Keep (or drop) the listed columns.
"""
NODE = {
    "label": "Select Columns",
    "category": "Transform",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "columns", "type": "columns", "label": "Columns",
     "default": "", "placeholder": "comma separated"},
    {"name": "mode", "type": "choice", "label": "Mode",
     "options": ["keep", "drop"], "default": "keep"},
]


def run(ctx, table):
    names = [c.strip() for c in ctx.params["columns"].split(",") if c.strip()]
    if not names:
        raise ValueError("no columns listed")
    missing = [c for c in names if c not in table.columns]
    if missing:
        raise ValueError(f"columns not in table: {missing}")
    if ctx.params["mode"] == "keep":
        return table[names]
    return table.drop(columns=names)
