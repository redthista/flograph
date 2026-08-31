"""Explode List Column

Turn one row with a list-valued cell into several rows, one per element —
pandas `explode`, and the "Expand to New Rows" you reach for after a JSON
read leaves a column full of arrays. `tags = ["a", "b", "c"]` on one row
becomes three rows, `a` / `b` / `c`, with every other column repeated.

If the cell holds a delimited string rather than a real list, set *Split
strings on* to a delimiter and it's split first. Empty lists become one row
with a blank (or are dropped, with *Drop empty*).
"""
NODE = {
    "label": "Explode List Column",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "column", "type": "columns", "label": "Column", "default": "",
     "multi": False},
    {"name": "split_on", "type": "string", "label": "Split strings on",
     "default": "", "placeholder": "e.g. , or ; — leave empty for real lists"},
    {"name": "drop_empty", "type": "bool", "label": "Drop empty",
     "default": False},
    {"name": "reset_index", "type": "bool", "label": "Renumber rows",
     "default": True},
]


def run(ctx, table):
    import pandas as pd

    p = ctx.params
    col = p["column"].strip()
    if not col:
        raise ValueError("no column selected — set 'Column'")
    if col not in table.columns:
        raise ValueError(f"column {col!r} not in table")

    work = table.copy(deep=False)
    sep = p["split_on"]

    if sep:
        def to_list(v):
            if isinstance(v, list):
                return v
            if v is None or (isinstance(v, float) and v != v) or v is pd.NA:
                return []
            return str(v).split(sep)
        work[col] = work[col].map(to_list)

    exploded = work.explode(col, ignore_index=bool(p["reset_index"]))

    if p["drop_empty"]:
        keep = exploded[col].notna()
        exploded = exploded[keep]
        if p["reset_index"]:
            exploded = exploded.reset_index(drop=True)

    ctx.log(f"exploded {col!r}: {len(table)} → {len(exploded)} rows")
    return exploded
