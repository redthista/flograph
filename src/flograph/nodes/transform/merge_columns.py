"""Merge Columns

Join several columns into one string with a separator between them — Power
Query's *Merge Columns*. The inverse of Split Column: rebuild a `city, state`
address line, stitch a `first`/`last` pair into a full name, make a compound
key for a join.

List the columns in the order you want them joined. Missing values become
empty by default (so `Ada` + `` + `Lovelace` with a space separator is
`Ada  Lovelace` → set *Skip blanks* to close the gap). The source columns are
removed unless *Keep source columns* is set.
"""
NODE = {
    "label": "Merge Columns",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "columns", "type": "columns", "label": "Columns to merge",
     "default": "", "placeholder": "first, last"},
    {"name": "separator", "type": "string", "label": "Separator",
     "default": " ", "placeholder": "e.g. a space, ', ', ' - '"},
    {"name": "output_column", "type": "string", "label": "New column",
     "default": "merged"},
    {"name": "skip_blanks", "type": "bool", "label": "Skip blanks",
     "default": False},
    {"name": "keep_source", "type": "bool", "label": "Keep source columns",
     "default": False},
]


def run(ctx, table):
    p = ctx.params
    names = [c.strip() for c in p["columns"].split(",") if c.strip()]
    if len(names) < 2:
        raise ValueError("list at least two columns to merge")
    missing = [c for c in names if c not in table.columns]
    if missing:
        raise ValueError(f"columns not in table: {missing}")

    out_name = p["output_column"].strip()
    if not out_name:
        raise ValueError("'New column' is empty")

    sep = p["separator"]
    cols = [table[c].astype("string").fillna("") for c in names]

    if p["skip_blanks"]:
        merged = [sep.join(v for v in parts if v != "")
                  for parts in zip(*cols)]
    else:
        merged = [sep.join(parts) for parts in zip(*cols)]

    result = table.copy(deep=False)
    at = min((result.columns.get_loc(c) for c in names))
    if not p["keep_source"]:
        result = result.drop(columns=names)
        at = min(at, result.shape[1])
    if out_name in result.columns:
        raise ValueError(f"column {out_name!r} already exists — pick another name")
    result.insert(at, out_name, merged)

    ctx.log(f"merged {names} → {out_name!r}")
    return result
