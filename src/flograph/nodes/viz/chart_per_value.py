"""Chart per Value

One chart for every distinct value of a column — the same plot repeated
across regions, products, months — shown as a scrolling stack on the card
and on a dashboard tile.

Set "Split by" to the column to loop over and pick the X and Y columns for
each chart. Each chart sees only that group's rows.

It works because the node returns a **list** of figures, and flograph
renders a list as a stack wherever a single one would go: the canvas card,
a dashboard tile, and a report page, where one `![[Chart per Value]]`
embeds the whole run of them. That is the general mechanism, not a feature
of this node — fork it (Edit Code) and the loop is yours: sort the groups,
skip the small ones, give each chart its own scale, mix chart kinds. Nothing
here is special-cased, so any list of figures a node returns behaves the
same way.

**Fill** is the plain choice: all of them **down** the page, or all of them
**across** it. With Columns and Rows both at 0 that is exactly what you
get — one column, or one row that scrolls sideways.

**Columns / Rows** constrain it into a grid: Columns 3 gives three across
and as many rows as it takes; Rows 2 gives two down and as many columns.
Set both for a fixed grid — if there are more charts than cells it grows
along the fill direction rather than hiding any. The layout is read by
every host, so the card, a dashboard tile and the PDF all agree.

All three are marked `"cosmetic": True`, so changing one re-arranges the
charts without marking the node dirty — re-running a slow split just to
show it in two columns would be absurd.

"Max charts" is a guard, not a preference: splitting on a high-cardinality
column by accident would otherwise build thousands of figures and hang the
run. It logs when it trims.
"""
NODE = {
    "label": "Chart per Value",
    "category": "Viz",
    "card": "figure",
    "inputs": [("table", "dataframe")],
    "outputs": [("figures", "any")],
}
PARAMS = [
    {"name": "split_by", "type": "columns", "label": "Split by",
     "multi": False, "default": "",
     "placeholder": "column to make one chart per value of"},
    {"name": "kind", "type": "choice", "label": "Kind",
     "options": ["line", "bar", "scatter", "hist"], "default": "line"},
    {"name": "x", "type": "columns", "label": "X column", "multi": False,
     "default": "", "placeholder": "(index)"},
    {"name": "y", "type": "columns", "label": "Y columns",
     "default": "", "placeholder": "comma separated; empty = all numeric"},
    {"name": "shared_scale", "type": "bool", "label": "Same Y scale",
     "default": True},
    {"name": "max_charts", "type": "int", "label": "Max charts",
     "default": 40, "min": 1, "max": 500},
    # Layout of the stack, read by every host that shows it (canvas card,
    # dashboard tile, report/PDF). 0 = work it out; see core.chart_grid.
    {"name": "columns", "type": "int", "label": "Columns",
     "default": 0, "min": 0, "max": 12, "cosmetic": True},
    {"name": "rows", "type": "int", "label": "Rows",
     "default": 0, "min": 0, "max": 12, "cosmetic": True},
    {"name": "direction", "type": "choice", "label": "Fill",
     "options": ["down", "across"], "default": "down", "cosmetic": True},
    {"name": "width", "type": "int", "label": "Width",
     "default": 460, "min": 260, "max": 1600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 380, "min": 200, "max": 2000},
]


def run(ctx, table):
    import importlib.util

    if importlib.util.find_spec("matplotlib") is None:
        raise RuntimeError(
            "Chart per Value requires the optional matplotlib extra. "
            "Install it with `pip install flograph[matplotlib]` or "
            "Tools > Manage Packages > matplotlib.")

    from matplotlib.figure import Figure   # OO API only — never pyplot

    split_by = (ctx.params.get("split_by") or "").strip()
    if not split_by:
        raise ValueError("set 'Split by' to the column to make one chart per")
    if split_by not in table.columns:
        raise ValueError(f"no column {split_by!r} in the input")

    x = (ctx.params.get("x") or "").strip()
    y = [c.strip() for c in (ctx.params.get("y") or "").split(",") if c.strip()]
    if not y:
        y = [c for c in table.select_dtypes("number").columns if c != split_by]
    if not y:
        raise ValueError("no numeric columns to plot")

    kind = ctx.params.get("kind", "line")
    limit = int(ctx.params.get("max_charts", 40))
    groups = list(table.groupby(split_by, sort=True, observed=True))
    if len(groups) > limit:
        ctx.log(f"{len(groups)} values in {split_by!r} — charting the first "
                f"{limit}. Raise 'Max charts' or filter upstream.")
        groups = groups[:limit]

    # one scale across every chart, so the panels can be compared by eye —
    # which is usually the entire reason for splitting a chart up
    limits = None
    if ctx.params.get("shared_scale", True) and kind != "hist":
        values = table[y].apply(lambda s: s.astype("float64"), axis=0)
        low, high = float(values.min().min()), float(values.max().max())
        if low == low and high == high:      # not NaN
            pad = (high - low) * 0.05 or 1.0
            limits = (low - pad, high + pad)

    figures = []
    for value, group in groups:
        ctx.check_cancelled()
        figure = Figure(figsize=(7, 3.2), layout="tight")
        axes = figure.add_subplot()
        for column in y:
            if kind == "hist":
                axes.hist(group[column].dropna(), bins=20, label=str(column))
            elif kind == "scatter":
                axes.scatter(group[x] if x else group.index, group[column],
                             s=12, label=str(column))
            elif kind == "bar":
                axes.bar(group[x].astype(str) if x
                         else group.index.astype(str), group[column],
                         label=str(column))
            else:
                axes.plot(group[x] if x else group.index, group[column],
                          label=str(column))
        if limits is not None:
            axes.set_ylim(*limits)
        axes.set_title(f"{split_by}: {value}")
        if len(y) > 1:
            axes.legend(fontsize="small")
        figures.append(figure)

    ctx.log(f"{len(figures)} chart(s), one per value of {split_by!r}")
    return {"figures": figures}
