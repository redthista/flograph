"""Missing Values

Handle missing values: drop the rows that contain
them, or fill them — with a fixed value, the previous/next row's value, or
a per-column mean/median.
"""
NODE = {
    "label": "Missing Values",
    "category": "Transform",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "strategy", "type": "choice", "label": "Strategy",
     "options": ["drop rows", "fill value", "forward fill", "backward fill",
                 "mean", "median"],
     "default": "drop rows"},
    {"name": "fill_value", "type": "string", "label": "Fill value",
     "default": "", "placeholder": "used by 'fill value' (number if it parses)"},
    {"name": "columns", "type": "columns", "label": "Columns",
     "default": "", "placeholder": "empty = all columns"},
]


def run(ctx, table):
    columns_raw = ctx.params["columns"].strip()
    if columns_raw:
        columns = [c.strip() for c in columns_raw.split(",") if c.strip()]
        missing = [c for c in columns if c not in table.columns]
        if missing:
            raise ValueError(f"columns not in table: {missing}")
    else:
        columns = list(table.columns)

    strategy = ctx.params["strategy"]
    before = int(table[columns].isna().sum().sum())
    if strategy == "drop rows":
        result = table.dropna(subset=columns)
        ctx.log(f"dropped {len(table) - len(result)} rows with missing values")
        return result

    result = table.copy()
    if strategy == "fill value":
        raw = ctx.params["fill_value"]
        try:
            value = float(raw)
            value = int(value) if value.is_integer() else value
        except ValueError:
            value = raw
        result[columns] = result[columns].fillna(value)
    elif strategy == "forward fill":
        result[columns] = result[columns].ffill()
    elif strategy == "backward fill":
        result[columns] = result[columns].bfill()
    else:  # mean / median
        numeric = [c for c in columns if table[c].dtype.kind in "biufc"]
        if not numeric:
            raise ValueError(f"'{strategy}' needs numeric columns, found none")
        stats = getattr(result[numeric], strategy)()
        result[numeric] = result[numeric].fillna(stats)
    after = int(result[columns].isna().sum().sum())
    ctx.log(f"filled {before - after} missing values ({after} remain)")
    return result
