"""Join

Merge two DataFrames on key columns (pandas merge).
"""
NODE = {
    "label": "Join",
    "category": "Transform",
    "inputs": [("left", "dataframe"), ("right", "dataframe")],
    "outputs": [("joined", "dataframe")],
}
PARAMS = [
    {"name": "on", "type": "columns", "label": "Key columns",
     "default": "", "placeholder": "comma separated; empty = common columns"},
    {"name": "how", "type": "choice", "label": "How",
     "options": ["inner", "left", "right", "outer"], "default": "inner"},
]


def run(ctx, left, right):
    on_raw = ctx.params["on"].strip()
    kwargs = {}
    if on_raw:
        keys = [c.strip() for c in on_raw.split(",") if c.strip()]
        missing = [c for c in keys
                   if c not in left.columns or c not in right.columns]
        if missing:
            raise ValueError(f"key columns missing from a side: {missing}")
        kwargs["on"] = keys
    joined = left.merge(right, how=ctx.params["how"], **kwargs)
    ctx.log(f"{len(left)} x {len(right)} rows -> {len(joined)}")
    return joined
