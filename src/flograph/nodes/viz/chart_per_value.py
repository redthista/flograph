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

**Bar mode** only matters for the bar kind. matplotlib has no equivalent
of Plotly's barmode: drawn plainly, every series lands on the same x
positions at full width and the later ones simply hide the earlier, so
this node used to show only the last y column. **group** stands them side
by side, **stack** piles them up, and **overlay** is the old draw-on-top
behaviour, which is still useful with an alpha or a single series.

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
    # Only the bar kind reads this. Side by side is nearly always what a
    # comparison chart wants, and it matches the Plotly node's default.
    {"name": "barmode", "type": "choice", "label": "Bar mode",
     "options": ["group", "stack", "overlay"], "default": "group"},
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


def _draw_bars(axes, group, x, y, mode):
    """Every y column's bars on one axes, laid out by `mode`.

    Offsetting a series sideways needs numbers to offset from, so the x
    values become tick labels over arange() rather than matplotlib's own
    categories. Rows are taken as they come: one bar per row, not one per
    distinct x, which is what the other kinds here already do.
    """
    import numpy as np

    labels = (group[x] if x else group.index).astype(str)
    positions = np.arange(len(group))
    if mode == "group" and len(y) > 1:
        span = 0.8
        width = span / len(y)
        for index, column in enumerate(y):
            axes.bar(positions - span / 2 + width * (index + 0.5),
                     group[column], width=width, label=str(column))
    elif mode == "stack":
        # separate piles above and below zero, so a negative series does
        # not eat into the height of the positive ones
        up = np.zeros(len(group))
        down = np.zeros(len(group))
        for column in y:
            values = group[column].to_numpy(dtype="float64", na_value=0.0)
            bottom = np.where(values >= 0, up, down)
            axes.bar(positions, values, width=0.8, bottom=bottom,
                     label=str(column))
            up = up + np.clip(values, 0, None)
            down = down + np.clip(values, None, 0)
    else:
        for column in y:
            axes.bar(positions, group[column], width=0.8, label=str(column))
    axes.set_xticks(positions)
    axes.set_xticklabels(labels)


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
    barmode = ctx.params.get("barmode", "group")
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
        if kind == "bar" and barmode == "stack":
            # a stacked bar reaches the row's total, not its tallest
            # column — bounding by the column max would crop every bar
            low = float(values.clip(upper=0).sum(axis=1).min())
            high = float(values.clip(lower=0).sum(axis=1).max())
        else:
            low, high = float(values.min().min()), float(values.max().max())
        if low == low and high == high:      # not NaN
            pad = (high - low) * 0.05 or 1.0
            limits = (low - pad, high + pad)

    figures = []
    for value, group in groups:
        ctx.check_cancelled()
        figure = Figure(figsize=(7, 3.2), layout="tight")
        axes = figure.add_subplot()
        if kind == "bar":
            _draw_bars(axes, group, x, y, barmode)
        else:
            for column in y:
                if kind == "hist":
                    axes.hist(group[column].dropna(), bins=20,
                              label=str(column))
                elif kind == "scatter":
                    axes.scatter(group[x] if x else group.index,
                                 group[column], s=12, label=str(column))
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
