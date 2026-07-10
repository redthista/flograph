"""Row Sampling

Take a subset of rows (KNIME Row Sampling): the first or last rows, or a
random sample — an absolute count, or a fraction of the table when the
fraction is set above zero.
"""
NODE = {
    "label": "Row Sampling",
    "category": "Transform",
    "inputs": [("table", "dataframe")],
    "outputs": [("sample", "dataframe")],
}
PARAMS = [
    {"name": "mode", "type": "choice", "label": "Take",
     "options": ["first", "last", "random"], "default": "first"},
    {"name": "rows", "type": "int", "label": "Row count",
     "default": 100, "min": 1},
    {"name": "fraction", "type": "float", "label": "Fraction (overrides count)",
     "default": 0.0, "min": 0.0, "max": 1.0},
    {"name": "seed", "type": "int", "label": "Random seed", "default": 0},
]


def run(ctx, table):
    fraction = ctx.params["fraction"]
    count = (max(1, round(len(table) * fraction)) if fraction > 0
             else ctx.params["rows"])
    count = min(count, len(table))
    mode = ctx.params["mode"]
    if mode == "first":
        sample = table.head(count)
    elif mode == "last":
        sample = table.tail(count)
    else:
        sample = table.sample(n=count, random_state=ctx.params["seed"] or None)
    ctx.log(f"sampled {len(sample)} of {len(table)} rows ({mode})")
    return sample
