"""Convert Types

Convert columns to another type (KNIME column converter nodes). On errors
either fail the node or coerce the offending cells to missing values.
"""
NODE = {
    "label": "Convert Types",
    "category": "Transform",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "columns", "type": "columns", "label": "Columns",
     "default": "", "placeholder": "comma separated"},
    {"name": "to", "type": "choice", "label": "Target type",
     "options": ["int", "float", "string", "bool", "datetime", "category"],
     "default": "float"},
    {"name": "on_error", "type": "choice", "label": "On bad values",
     "options": ["fail", "set missing"], "default": "fail"},
]


def run(ctx, table):
    import pandas as pd

    columns = [c.strip() for c in ctx.params["columns"].split(",") if c.strip()]
    if not columns:
        raise ValueError("no columns listed")
    missing = [c for c in columns if c not in table.columns]
    if missing:
        raise ValueError(f"columns not in table: {missing}")

    target = ctx.params["to"]
    coerce = ctx.params["on_error"] == "set missing"
    result = table.copy()
    for col in columns:
        series = result[col]
        if target == "datetime":
            converted = pd.to_datetime(series,
                                       errors="coerce" if coerce else "raise")
        elif target in ("int", "float"):
            converted = pd.to_numeric(series,
                                      errors="coerce" if coerce else "raise")
            # nullable Int64 keeps ints even when coercion produced missings
            converted = converted.astype("Int64" if target == "int" else float)
        elif target == "string":
            converted = series.astype(str)
        elif target == "bool":
            converted = series.astype(bool)
        else:
            converted = series.astype("category")
        result[col] = converted
    ctx.log(f"converted {len(columns)} column(s) to {target}")
    return result
