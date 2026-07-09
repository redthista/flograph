"""Show Plot

Plot and Show Figure combined into a single card: wire a DataFrame straight
in and it draws the chart and renders it directly on the node, with
pan/zoom/save controls built in. Leave "Y columns" empty to plot every
numeric column. Outputs the drawn figure so you can keep it wired into
further consumers (e.g. an export node).
"""
NODE = {
    "label": "Show Plot",
    "category": "Viz",
    "inputs": [("table", "dataframe")],
    "outputs": [("figure", "figure")],
}
PARAMS = [
    {"name": "kind", "type": "choice", "label": "Kind",
     "options": ["line", "scatter", "bar", "hist"], "default": "line"},
    {"name": "x", "type": "columns", "label": "X column",
     "default": "", "placeholder": "(index)"},
    {"name": "y", "type": "columns", "label": "Y columns",
     "default": "", "placeholder": "comma separated; empty = all numeric"},
    {"name": "title", "type": "string", "label": "Title", "default": ""},
    {"name": "width", "type": "int", "label": "Width",
     "default": 420, "min": 260, "max": 1600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 320, "min": 200, "max": 2000},
]


def run(ctx, table):
    from matplotlib.figure import Figure  # OO API only — never pyplot in nodes

    fig = Figure(figsize=(7, 4.5), layout="tight")
    ax = fig.add_subplot()

    x_col = ctx.params["x"].strip()
    y_raw = ctx.params["y"].strip()
    if y_raw:
        y_cols = [c.strip() for c in y_raw.split(",") if c.strip()]
        missing = [c for c in y_cols if c not in table.columns]
        if missing:
            raise ValueError(f"columns not in table: {missing}")
    else:
        y_cols = [c for c in table.columns
                  if table[c].dtype.kind in "biufc" and c != x_col]
        if not y_cols:
            raise ValueError("no numeric columns to plot")

    if x_col and x_col not in table.columns:
        raise ValueError(f"x column {x_col!r} not in table")
    x = table[x_col] if x_col else table.index

    kind = ctx.params["kind"]
    for col in y_cols:
        if kind == "line":
            ax.plot(x, table[col], label=col)
        elif kind == "scatter":
            ax.scatter(x, table[col], label=col, s=12)
        elif kind == "bar":
            ax.bar(x, table[col], label=col)
        elif kind == "hist":
            ax.hist(table[col], label=col, bins=30, alpha=0.7)

    if len(y_cols) > 1 or kind == "hist":
        ax.legend()
    ax.set_xlabel(x_col or "index")
    if ctx.params["title"]:
        ax.set_title(ctx.params["title"])
    ctx.log(f"plotted {len(y_cols)} series ({kind})")
    return {"figure": fig}
