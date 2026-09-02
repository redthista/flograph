"""Pivot

Pivot a long table into a wide one: rows grouped by the index
columns, one output column per distinct value of the pivot column, cells
aggregated.

With a single value column the output columns are the bare pivot values
(no value-name prefix). List more than one value column and each output
column is prefixed with its value name to keep them apart.
"""
NODE = {
    "label": "Pivot",
    "category": "Transform",
    "version": "1.0",
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
        # Drop any column level carrying a single distinct label - the
        # value-column name when only one value is pivoted - so the output
        # columns stay as bare pivot values with no forced prefix.
        while pivoted.columns.nlevels > 1 and \
                pivoted.columns.get_level_values(0).nunique() == 1:
            pivoted.columns = pivoted.columns.droplevel(0)
        if pivoted.columns.nlevels > 1:
            pivoted.columns = ["_".join(str(part) for part in col)
                               for col in pivoted.columns]
        else:
            pivoted.columns = [str(c) for c in pivoted.columns]
    pivoted = pivoted.reset_index()
    ctx.log(f"{len(table)} rows -> {len(pivoted)} x {len(pivoted.columns)}")
    return pivoted
