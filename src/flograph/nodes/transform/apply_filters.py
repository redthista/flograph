"""Apply Filters

Filter a table by the picks an Input Panel or a Slicer made on another one.
Wire the table into "table" and the panel's or slicer's "filters" output
into "filters": every filter the panel applied — Region is North, Price
between 20 and 70, Ordered in the last 30 days — is applied here too. From
a Slicer it is exactly the slicer's ticks: the same values, the same tree
of columns (ticking a region keeps all its stores), "(blank)" for an empty
cell. Nothing ticked filters nothing.

Columns are matched by name. Where this table calls a column something else,
say so in "Column names", one per line, panel's (or slicer's) column
first — for a slicer on several columns, a line for each one that differs:

    region = sales_region
    order_date = placed_on

A filter whose column this table doesn't have is skipped and logged, or —
with "Missing column" set to fail — stops the node, for when silently
filtering less than the panel did would be wrong.
"""
NODE = {
    "label": "Apply Filters",
    "category": "Transform",
    "version": "1.1",
    "inputs": [("table", "dataframe"),
               ("filters", "any",
                {"suggest": ["flograph.input.input_panel",
                             "flograph.viz.slicer"]})],
    "outputs": [("filtered", "dataframe")],
}
PARAMS = [
    {"name": "mapping", "type": "text", "label": "Column names",
     "default": "", "placeholder": "panel column = this table's column"},
    {"name": "missing", "type": "choice", "label": "Missing column",
     "options": ["skip", "fail"], "default": "skip"},
]


def run(ctx, table, filters):
    from flograph.core.input_panel import apply_filter, filter_columns

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
        raise TypeError(f"'filters' expects an Input Panel's or a Slicer's "
                        f"filters, got "
                        f"{type(filters).__name__}")
    rows = table
    for flt in filters:
        ctx.check_cancelled()
        columns = [mapping.get(c, c) for c in filter_columns(flt)]
        absent = [c for c in columns if c not in rows.columns]
        if absent:
            message = (f"no column {absent[0]!r} for the {flt['field']!r} "
                       f"filter")
            if ctx.params.get("missing") == "fail":
                raise KeyError(message)
            ctx.log(f"skipped: {message}")
            continue
        rows = apply_filter(rows, flt, columns[0], columns)
        ctx.log(f"{' > '.join(columns)} {flt['op']} {flt['value']!r}")
    ctx.log(f"{len(rows):,} of {len(table):,} rows pass")
    return {"filtered": rows}
