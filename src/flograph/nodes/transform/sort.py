"""Sort

Sort rows by one or more columns.
"""
NODE = {
    "label": "Sort",
    "category": "Transform",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "by", "type": "columns", "label": "Sort by",
     "default": "", "placeholder": "comma separated"},
    {"name": "descending", "type": "bool", "label": "Descending",
     "default": False},
]


def run(ctx, table):
    by = [c.strip() for c in ctx.params["by"].split(",") if c.strip()]
    if not by:
        raise ValueError("no sort columns listed")
    missing = [c for c in by if c not in table.columns]
    if missing:
        raise ValueError(f"columns not in table: {missing}")
    return table.sort_values(by=by, ascending=not ctx.params["descending"],
                             kind="stable")
