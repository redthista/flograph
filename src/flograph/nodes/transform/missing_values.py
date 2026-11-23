"""Missing Values

Handle missing values: drop the rows that contain
them, or fill them — with a fixed value, the previous/next row's value, or
a per-column mean/median. With "Blank text is missing" ticked, empty or
whitespace-only text cells count as missing too, so they are dropped or
filled alongside NaN.
"""
NODE = {
    "label": "Missing Values",
    "category": "Transform",
    "version": "1.1",
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
    {"name": "blank_as_missing", "type": "bool",
     "label": "Blank text is missing",
     "default": False},
]


def _blanks_to_na(table, columns):
    """Copy of *table* with empty/whitespace-only strings in *columns* set to NA."""
    result = table.copy()
    for col in columns:
        series = result[col]
        if series.dtype.kind not in "OSU" and str(series.dtype) != "string":
            continue
        blank = series.map(lambda v: isinstance(v, str) and not v.strip())
        if blank.any():
            result[col] = series.mask(blank)
    return result


def run(ctx, table):
    columns_raw = ctx.params["columns"].strip()
    if columns_raw:
        columns = [c.strip() for c in columns_raw.split(",") if c.strip()]
        missing = [c for c in columns if c not in table.columns]
        if missing:
            raise ValueError(f"columns not in table: {missing}")
    else:
        columns = list(table.columns)

    if ctx.params.get("blank_as_missing"):
        table = _blanks_to_na(table, columns)

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
