"""Pivot

Pivot a long table into a wide one (KNIME Pivot): rows grouped by the index
columns, one output column per distinct value of the pivot column, cells
aggregated.
"""
NODE = {
    "label": "Pivot",
    "category": "Transform",
    "inputs": [("table", "dataframe")],
    "outputs": [("pivoted", "dataframe")],
}
PARAMS = [
    {"name": "index", "type": "columns", "label": "Group by (rows)",
     "default": "", "placeholder": "comma separated"},
    {"name": "columns", "type": "columns", "label": "Pivot column(s)",
     "default": "", "placeholder": "comma separated"},
    {"name": "values", "type": "columns", "label": "Value columns",
     "default": "", "placeholder": "empty = all remaining numeric"},
    {"name": "agg", "type": "choice", "label": "Aggregation",
     "options": ["sum", "mean", "median", "min", "max", "count", "first"],
     "default": "sum"},
]


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
    pivoted = table.pivot_table(index=index, columns=columns, values=values,
                                aggfunc=ctx.params["agg"])
    if hasattr(pivoted.columns, "levels"):
        pivoted.columns = ["_".join(str(part) for part in col)
                           for col in pivoted.columns]
    pivoted = pivoted.reset_index()
    ctx.log(f"{len(table)} rows -> {len(pivoted)} x {len(pivoted.columns)}")
    return pivoted
