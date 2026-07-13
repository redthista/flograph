"""Show Plotly

Interactive Plotly chart rendered directly on the node card — hover,
zoom and pan in place. Needs the 'plotly' package: install it from
Tools > Manage Packages if missing. Outputs the plotly Figure object for
further consumers.
"""
NODE = {
    "label": "Show Plotly",
    "category": "Viz",
    "card": "webview",
    "inputs": [("table", "dataframe")],
    "outputs": [("figure", "object")],
}
PARAMS = [
    {"name": "kind", "type": "choice", "label": "Kind",
     "options": ["line", "scatter", "bar", "area", "histogram", "box",
                 "violin"],
     "default": "line"},
    {"name": "x", "type": "columns", "label": "X column", "multi": False,
     "default": "", "placeholder": "(index)"},
    {"name": "y", "type": "columns", "label": "Y columns",
     "default": "", "placeholder": "comma separated; empty = all numeric"},
    {"name": "color", "type": "columns", "label": "Color by", "multi": False,
     "default": "", "placeholder": "optional grouping column"},
    {"name": "title", "type": "string", "label": "Title", "default": ""},
    {"name": "width", "type": "int", "label": "Width",
     "default": 420, "min": 260, "max": 1600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 320, "min": 200, "max": 2000},
    {"name": "scale", "type": "int", "label": "Scale %",
     "default": 100, "min": 25, "max": 400},
]


def run(ctx, table):
    try:
        import plotly.express as px
    except ImportError:
        raise ImportError(
            "plotly is not installed — add it via Tools > Manage Packages"
        ) from None

    x_col = ctx.params["x"].strip()
    color = ctx.params["color"].strip()
    y_raw = ctx.params["y"].strip()
    if y_raw:
        y_cols = [c.strip() for c in y_raw.split(",") if c.strip()]
    else:
        y_cols = [c for c in table.columns
                  if table[c].dtype.kind in "biufc"
                  and c not in (x_col, color)]
        if not y_cols:
            raise ValueError("no numeric columns to plot")
    missing = [c for c in (*y_cols, *filter(None, (x_col, color)))
               if c not in table.columns]
    if missing:
        raise ValueError(f"columns not in table: {missing}")

    kwargs = {"y": y_cols if len(y_cols) > 1 else y_cols[0]}
    if x_col:
        kwargs["x"] = x_col
    if color:
        kwargs["color"] = color
    if ctx.params["title"]:
        kwargs["title"] = ctx.params["title"]
    fig = getattr(px, ctx.params["kind"])(table, **kwargs)
    ctx.log(f"plotted {len(y_cols)} series ({ctx.params['kind']})")
    return {"figure": fig}
