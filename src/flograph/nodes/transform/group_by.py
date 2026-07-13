"""Group By

Group rows and aggregate: one aggregation applied to the chosen value
columns (or all numeric columns if left empty).
"""
NODE = {
    "label": "Group By",
    "category": "Transform",
    "inputs": [("table", "dataframe")],
    "outputs": [("aggregated", "dataframe")],
}
PARAMS = [
    {"name": "by", "type": "columns", "label": "Group by",
     "default": "", "placeholder": "comma separated"},
    {"name": "agg", "type": "choice", "label": "Aggregation",
     "options": ["sum", "mean", "median", "min", "max", "count", "std"],
     "default": "sum"},
    {"name": "values", "type": "columns", "label": "Value columns",
     "default": "", "placeholder": "empty = all numeric"},
]


def run(ctx, table):
    by = [c.strip() for c in ctx.params["by"].split(",") if c.strip()]
    if not by:
        raise ValueError("no group-by columns listed")
    missing = [c for c in by if c not in table.columns]
    if missing:
        raise ValueError(f"columns not in table: {missing}")

    values_raw = ctx.params["values"].strip()
    if values_raw:
        values = [c.strip() for c in values_raw.split(",") if c.strip()]
        missing = [c for c in values if c not in table.columns]
        if missing:
            raise ValueError(f"columns not in table: {missing}")
    else:
        values = [c for c in table.columns
                  if c not in by and table[c].dtype.kind in "biufc"]
        if not values:
            raise ValueError("no numeric columns to aggregate")

    grouped = (table.groupby(by, dropna=False)[values]
               .agg(ctx.params["agg"]).reset_index())
    ctx.log(f"{len(table)} rows -> {len(grouped)} groups")
    return grouped
