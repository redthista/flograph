"""Apply Filters

Filter a table by the picks an Input Panel made on another one. Wire the
table into "table" and the panel's "filters" output into "filters": every
filter the panel applied — Region is North, Price between 20 and 70, Ordered
in the last 30 days — is applied here too.

Columns are matched by name. Where this table calls a column something else,
say so in "Column names", one per line, panel's column first:

    region = sales_region
    order_date = placed_on

A filter whose column this table doesn't have is skipped and logged, or —
with "Missing column" set to fail — stops the node, for when silently
filtering less than the panel did would be wrong.
"""
NODE = {
    "label": "Apply Filters",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe"),
               ("filters", "any",
                {"suggest": ["flograph.input.input_panel"]})],
    "outputs": [("filtered", "dataframe")],
}
PARAMS = [
    {"name": "mapping", "type": "text", "label": "Column names",
     "default": "", "placeholder": "panel column = this table's column"},
    {"name": "missing", "type": "choice", "label": "Missing column",
     "options": ["skip", "fail"], "default": "skip"},
]


def run(ctx, table, filters):
    from flograph.core.input_panel import apply_filter

    # `left = right` per line; a column name may have spaces in it, which
    # is why this isn't the Variables node's name = value reader
    mapping = {}
    for line in str(ctx.params.get("mapping") or "").splitlines():
        left, sep, right = line.partition("=")
        if line.strip() and not line.strip().startswith("#"):
            if not sep or not left.strip() or not right.strip():
                raise ValueError(f"{line.strip()!r}: expected "
                                 f"'panel column = this table's column'")
            mapping[left.strip()] = right.strip()
    if filters is None:
        filters = []
    if not isinstance(filters, (list, tuple)):
        raise TypeError(f"'filters' expects an Input Panel's filters, got "
                        f"{type(filters).__name__}")
    rows = table
    for flt in filters:
        column = mapping.get(flt["column"], flt["column"])
        ctx.check_cancelled()
        if column not in rows.columns:
            message = (f"no column {column!r} for the {flt['field']!r} "
                       f"filter")
            if ctx.params.get("missing") == "fail":
                raise KeyError(message)
            ctx.log(f"skipped: {message}")
            continue
        rows = apply_filter(rows, flt, column)
        ctx.log(f"{column} {flt['op']} {flt['value']!r}")
    ctx.log(f"{len(rows):,} of {len(table):,} rows pass")
    return {"filtered": rows}
