"""Correlation Matrix

How strongly each number column moves with every other one, as a coloured
grid and as a table — the first look before choosing what to feed a model.
+1 is "rise together", −1 is "one rises as the other falls", 0 is no
straight-line link at all.

**Method**: *pearson* measures a straight-line link; *spearman* only asks
whether the order agrees, so it suits skewed numbers and ranks; *kendall*
is spearman's more cautious cousin for small tables.

Leave **Columns** empty to use every number column. **matrix** is the same
numbers as a table, one row per column, for sorting or a Show Table.
"""
NODE = {
    "label": "Correlation Matrix",
    "category": "ML",
    "version": "1.0",
    # an interactive Plotly chart: hover a cell for its pair and value
    "card": "webview",
    "inputs": [("table", "dataframe")],
    "outputs": [("figure", "object"), ("matrix", "dataframe")],
}
PARAMS = [
    {"name": "method", "type": "choice", "label": "Method",
     "options": ["pearson", "spearman", "kendall"], "default": "pearson"},
    {"name": "columns", "type": "columns", "label": "Columns",
     "default": "", "placeholder": "empty = every number column"},
    {"name": "colormap", "type": "choice", "label": "Colours",
     "options": ["RdBu_r", "Tealrose", "PiYG", "BrBG", "Viridis"],
     "default": "RdBu_r"},
    {"name": "annotate", "type": "bool", "label": "Write the numbers",
     "default": True},
    {"name": "title", "type": "string", "label": "Title", "default": ""},
    {"name": "width", "type": "int", "label": "Width",
     "default": 420, "min": 260, "max": 4000, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 380, "min": 200, "max": 4000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %",
     "default": 100, "min": 25, "max": 400, "cosmetic": True},
]


def run(ctx, table):
    import pandas as pd

    from flograph.core import mlkit

    p = ctx.params
    named = mlkit.column_list(p["columns"])
    if named:
        missing = [c for c in named if c not in table.columns]
        if missing:
            raise ValueError(f"columns not in table: {missing}")
        frame = table[named].apply(pd.to_numeric, errors="coerce")
    else:
        frame = table.select_dtypes("number")
    frame = frame.loc[:, frame.notna().any()]
    if frame.shape[1] < 2:
        raise ValueError("need at least two number columns to correlate")

    corr = frame.astype(float).corr(method=p["method"])
    fig = mlkit.heatmap(corr.to_numpy(), list(corr.index),
                        list(corr.columns), colorscale=p["colormap"],
                        zmin=-1.0, zmax=1.0, annotate=bool(p["annotate"]),
                        title=p["title"] or f"{p['method'].title()} correlation")

    matrix = corr.reset_index().rename(columns={"index": "column"})
    matrix.columns = [str(c) for c in matrix.columns]
    pairs = corr.where(~pd.DataFrame(
        [[i <= j for j in range(len(corr))] for i in range(len(corr))],
        index=corr.index, columns=corr.columns)).stack()
    if len(pairs):
        a, b = pairs.abs().idxmax()
        ctx.log(f"{p['method']} over {frame.shape[1]} columns; strongest "
                f"pair {a} ~ {b} = {pairs[(a, b)]:.2f}")
    return {"figure": fig, "matrix": matrix}
