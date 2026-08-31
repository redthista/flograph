"""Transpose

Flip the table on its diagonal — rows become columns and columns become
rows, the same as Power Query's *Transpose*. The usual reason is a table that
came in "wide", one row per metric and one column per period, when every node
downstream wants it the other way round.

By default the new columns are named positionally (`Column1`, `Column2`, …)
and the old column names are kept as a first column. Set *Use column as
headers* to promote one existing column's values to the new header row
instead, and *Keep headers as a column* to preserve the old names.
"""
NODE = {
    "label": "Transpose",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "header_column", "type": "columns", "label": "Use column as headers",
     "default": "", "multi": False,
     "placeholder": "empty = Column1, Column2, …"},
    {"name": "keep_headers", "type": "bool", "label": "Keep headers as a column",
     "default": True},
    {"name": "headers_name", "type": "string", "label": "Name for that column",
     "default": "name"},
    {"name": "name_prefix", "type": "string", "label": "Positional name prefix",
     "default": "Column"},
]


def run(ctx, table):
    p = ctx.params
    df = table
    header_col = p["header_column"].strip()

    if header_col:
        if header_col not in df.columns:
            raise ValueError(f"column {header_col!r} not in table")
        new_cols = df[header_col].astype("string").tolist()
        df = df.drop(columns=[header_col])
    else:
        new_cols = [f"{p['name_prefix']}{i + 1}" for i in range(len(df))]

    if len(set(new_cols)) != len(new_cols):
        raise ValueError(
            f"header values in {header_col!r} are not unique — "
            "transpose needs distinct column names")

    old_names = df.columns.tolist()
    result = df.T
    result.columns = new_cols
    result = result.reset_index(drop=True)

    if p["keep_headers"]:
        label = p["headers_name"].strip() or "name"
        result.insert(0, label, old_names)

    ctx.log(f"transposed to {result.shape[0]} rows × {result.shape[1]} columns")
    return result
