"""Join

Merge/align two DataFrames using pandas merge/join semantics.
Supports on, left_on/right_on, suffixes, indicator, and all join types.
"""
NODE = {
    "label": "Join",
    "category": "Transform",
    "version": "1.1",
    "inputs": [("left", "dataframe"), ("right", "dataframe")],
    "outputs": [("joined", "dataframe")],
}
PARAMS = [
    {"name": "how", "type": "choice", "label": "Join type",
     "options": ["inner", "left", "right", "outer"], "default": "left",
     "section": "Join"},
    {"name": "on", "type": "columns", "label": "Shared key columns",
     "default": "", "section": "Key columns",
     "placeholder": "in both tables; empty = use left/right keys below"},
    {"name": "left_on", "type": "columns", "label": "Left key columns",
     "default": "", "section": "Key columns",
     "placeholder": "from the left table, when the names differ"},
    {"name": "right_on", "type": "columns", "label": "Right key columns",
     "default": "", "section": "Key columns",
     "placeholder": "from the right table, in the same order"},
    {"name": "suffixes_left", "type": "string", "label": "Left suffix",
     "default": "_left", "section": "Options",
     "placeholder": "added to a column name both tables share"},
    {"name": "suffixes_right", "type": "string", "label": "Right suffix",
     "default": "_right", "section": "Options",
     "placeholder": "added to a column name both tables share"},
    {"name": "indicator", "type": "bool", "label": "Add merge indicator",
     "default": False, "section": "Options"},
    {"name": "validate", "type": "choice", "label": "Check cardinality",
     "options": ["", "one_to_one", "one_to_many", "many_to_one",
                 "many_to_many"],
     "default": "", "unset_label": "Don't check", "section": "Validation"},
]


def run(ctx, left, right):
    on_raw = ctx.params["on"].strip()
    left_on_raw = ctx.params["left_on"].strip()
    right_on_raw = ctx.params["right_on"].strip()

    kwargs: dict = {"how": ctx.params["how"]}

    keys_left = [c.strip() for c in left_on_raw.split(",") if c.strip()] if left_on_raw else []
    keys_right = [c.strip() for c in right_on_raw.split(",") if c.strip()] if right_on_raw else []

    # left_on/right_on mode
    if keys_left or keys_right:
        if not keys_left or not keys_right:
            raise ValueError("both left_on and right_on must be specified together")
        missing_l = [c for c in keys_left if c not in left.columns]
        missing_r = [c for c in keys_right if c not in right.columns]
        if missing_l:
            raise ValueError(f"left_on columns missing from left DataFrame: {missing_l}")
        if missing_r:
            raise ValueError(f"right_on columns missing from right DataFrame: {missing_r}")
        kwargs["left_on"] = keys_left
        kwargs["right_on"] = keys_right
    else:
        # on mode or common columns fallback
        if on_raw:
            keys_on = [c.strip() for c in on_raw.split(",") if c.strip()]
            missing = [c for c in keys_on if c not in left.columns or c not in right.columns]
            if missing:
                raise ValueError(f"key columns missing from a side: {missing}")
            kwargs["on"] = keys_on
        else:
            # default pandas behaviour: merge on all common columns
            pass

    kwargs["suffixes"] = (ctx.params["suffixes_left"], ctx.params["suffixes_right"])

    if ctx.params.get("indicator"):
        kwargs["indicator"] = True

    validate = ctx.params.get("validate", "")
    if validate:
        kwargs["validate"] = validate

    joined = left.merge(right, **kwargs)
    ctx.log(f"{len(left)} x {len(right)} rows -> {len(joined)}")
    return joined
