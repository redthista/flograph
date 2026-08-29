"""Concatenate

Stack the rows of DataFrames on top of each other — as many as you like.
Connect **top** and **bottom** to start; every time you fill the empty
port at the bottom another one appears below it, so stacking five sources
is one node rather than a chain of four.

Union keeps every column and fills gaps with missing values; intersection
keeps only the columns all the connected tables share.
"""
NODE = {
    "label": "Concatenate",
    "category": "Transform",
    "version": "1.0",
    "inputs": [
        ("top", "dataframe"),
        ("bottom", "dataframe"),
        # the always-empty slot at the bottom: wiring it adds a permanent
        # port (in3, in4, ...) and a fresh empty slot appears below
        ("more", "dataframe", {"optional": True, "spare": True}),
    ],
    "outputs": [("combined", "dataframe")],
}
PARAMS = [
    {"name": "columns", "type": "choice", "label": "Columns",
     "options": ["union", "intersection"], "default": "union"},
    {"name": "reset_index", "type": "bool", "label": "Reset index",
     "default": True},
]

_FIXED_ORDER = ("top", "bottom")


def run(ctx, **inputs):
    import pandas as pd

    def grown_number(name):
        return int(name[2:]) if name[2:].isdigit() else 0

    names = [n for n in _FIXED_ORDER if inputs.get(n) is not None]
    names += sorted((k for k in inputs if k.startswith("in")),
                    key=grown_number)
    frames = [inputs[n] for n in names]
    if not frames:
        raise ValueError(
            "Concatenate needs at least one table connected")
    if len(frames) == 1:
        ctx.log("one table connected — passing it through")

    join = "outer" if ctx.params["columns"] == "union" else "inner"
    combined = pd.concat(frames, join=join,
                         ignore_index=ctx.params["reset_index"])
    ctx.log(" + ".join(str(len(f)) for f in frames)
            + f" rows -> {len(combined)}")
    return combined
