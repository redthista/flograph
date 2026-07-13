"""Concatenate

Stack the rows of two DataFrames on top of each other.
Union keeps every column and fills gaps with missing values; intersection
keeps only the columns both tables share.
"""
NODE = {
    "label": "Concatenate",
    "category": "Transform",
    "inputs": [("top", "dataframe"), ("bottom", "dataframe")],
    "outputs": [("combined", "dataframe")],
}
PARAMS = [
    {"name": "columns", "type": "choice", "label": "Columns",
     "options": ["union", "intersection"], "default": "union"},
    {"name": "reset_index", "type": "bool", "label": "Reset index",
     "default": True},
]


def run(ctx, top, bottom):
    import pandas as pd

    join = "outer" if ctx.params["columns"] == "union" else "inner"
    combined = pd.concat([top, bottom], join=join,
                         ignore_index=ctx.params["reset_index"])
    ctx.log(f"{len(top)} + {len(bottom)} rows -> {len(combined)}")
    return combined
