"""Duplicate Row Filter

Remove duplicate rows, judged over all columns
or a subset. Keep the first or last occurrence, or drop every row that has
a duplicate.
"""
NODE = {
    "label": "Duplicate Row Filter",
    "category": "Transform",
    "inputs": [("table", "dataframe")],
    "outputs": [("unique", "dataframe"), ("duplicates", "dataframe")],
}
PARAMS = [
    {"name": "columns", "type": "columns", "label": "Compare columns",
     "default": "", "placeholder": "empty = all columns"},
    {"name": "keep", "type": "choice", "label": "Keep",
     "options": ["first", "last", "none"], "default": "first"},
]


def run(ctx, table):
    columns_raw = ctx.params["columns"].strip()
    subset = None
    if columns_raw:
        subset = [c.strip() for c in columns_raw.split(",") if c.strip()]
        missing = [c for c in subset if c not in table.columns]
        if missing:
            raise ValueError(f"columns not in table: {missing}")

    keep = ctx.params["keep"]
    mask = table.duplicated(subset=subset,
                            keep=False if keep == "none" else keep)
    ctx.log(f"removed {int(mask.sum())} of {len(table)} rows as duplicates")
    return {"unique": table[~mask], "duplicates": table[mask]}
