"""Data Profile

Comprehensive column-by-column summary: dtype, count, missing (count & %),
unique (count & %), and for numeric columns — mean, std, min, 25%/50%/75%, max.
Outputs a DataFrame ready to wire into Show Table (or export).
"""
NODE = {
    "label": "Data Profile",
    "category": "Transform",
    "inputs": [("table", "dataframe")],
    "outputs": [("profile", "dataframe")],
}
PARAMS = [
    {"name": "columns", "type": "columns", "label": "Columns",
     "default": "", "placeholder": "empty = all columns"},
    {"name": "cardinality_warn", "type": "int", "label": "Cardinality warn threshold",
     "default": 100, "min": 1, "max": 100000,
     "placeholder": "flag columns with unique count exceeding this"},
]


def run(ctx, table):
    import pandas as pd

    col_list = _resolve_columns(table, ctx.params["columns"])
    if not col_list:
        raise ValueError("no columns to profile — table has no columns or selection mismatch")

    max_unique = ctx.params["cardinality_warn"]
    total_rows = len(table)
    rows: list[dict] = []

    for col in col_list:
        series = table[col]
        dtype_name = str(series.dtype)
        non_null = int(series.count())
        missing_count = total_rows - non_null
        missing_pct = round(100 * missing_count / total_rows, 2) if total_rows > 0 else 0.0

        unique_count = int(series.nunique())
        unique_pct = round(100 * unique_count / total_rows, 2) if total_rows > 0 else 0.0

        row: dict = {
            "column": col,
            "dtype": dtype_name,
            "count": non_null,
            "missing": missing_count,
            "missing_pct": missing_pct,
            "unique": unique_count,
            "unique_pct": unique_pct,
        }

        flag = ""
        if missing_pct > 0:
            flag += "M"
        if unique_count > max_unique:
            flag += "U"
        row["flags"] = flag or ""

        if series.dtype.kind in "biufc":
            desc = series.describe()
            row["mean"] = _round_val(desc.get("mean"))
            row["std"] = _round_val(desc.get("std"))
            row["min"] = _round_val(desc.get("min"))
            row["p25"] = _round_val(desc.get("25%"))
            row["p50"] = _round_val(desc.get("50%"))
            row["p75"] = _round_val(desc.get("75%"))
            row["max"] = _round_val(desc.get("max"))
        else:
            for stat in ("mean", "std", "min", "p25", "p50", "p75", "max"):
                row[stat] = None

        rows.append(row)

    profile = pd.DataFrame(rows)

    ctx.log(
        f"profiled {len(profile)} column(s): "
        f"{int(profile['missing'].sum())} missing values total, "
        f"{int((profile['flags'] != '').sum())} column(s) flagged"
    )
    return {"profile": profile}


def _resolve_columns(table, raw: str) -> list[str]:
    import pandas as pd
    candidates = (
        [c.strip() for c in raw.split(",") if c.strip()]
        if raw.strip()
        else list(table.columns)
    )
    missing = [c for c in candidates if c not in table.columns]
    if missing:
        raise ValueError(f"columns not found in table: {missing}")
    return candidates


def _round_val(val):
    if val is None:
        return None
    try:
        v = round(float(val), 2)
        return int(v) if v == int(v) else v
    except (TypeError, ValueError):
        return None