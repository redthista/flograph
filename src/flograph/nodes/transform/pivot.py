"""Pivot

Pivot a long table into a wide one: rows grouped by the index
columns, one output column per distinct value of the pivot column, cells
aggregated.

With a single value column the output columns are the bare pivot values
(no value-name prefix). List more than one value column and each output
column is prefixed with its value name to keep them apart.

**Order** decides how the new rows and columns are arranged. *As they
appear* (the default) keeps the order the incoming table is already in, so
a table sorted into Jan, Feb, Mar pivots into columns in that order.
*Sorted* arranges them alphabetically instead, which is what pandas does on
its own — and is why a month column used to come back Apr, Aug, Dec. A sort
set upstream is a decision, so the default is to keep it; there is nowhere
downstream to put it back, since the pivot is what invented the columns.
"""
NODE = {
    "label": "Pivot",
    "category": "Transform",
    "version": "1.1",
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
    {"name": "order", "type": "choice", "label": "Row / column order",
     "options": ["as they appear", "sorted"], "default": "as they appear"},
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
    # `.get`, not `[]`: a project saved before this node grew an Order has
    # no such param, and its pivot should keep working.
    ordering = str(ctx.params.get("order") or "as they appear")
    # pandas sorts both axes unless told not to, and sort=False is exactly
    # "first seen wins" — for the rows, for the pivot values, and, with
    # more than one value column, within each of them. So the whole choice
    # is this keyword; there is nothing to reindex by hand afterwards.
    pivoted = table.pivot_table(index=index, columns=columns, values=values,
                                aggfunc=ctx.params["agg"],
                                sort=ordering == "sorted")
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
