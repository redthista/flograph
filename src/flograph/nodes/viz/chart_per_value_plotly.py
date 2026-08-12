"""Chart per Value (Plotly)

One interactive chart for every distinct value of a column — the same plot
repeated across regions, products, months — shown as a stack on the card
and on a dashboard tile, each one with Plotly's own hover, zoom and pan.

Set "Split by" to the column to loop over and pick the X and Y columns for
each chart. Each chart sees only that group's rows.

This is the Plotly half of Chart per Value. The mechanism is identical and
is not special-cased in either node: the node returns a **list** of
figures, and flograph renders a list as a stack wherever a single one would
go. The only difference is what the list holds — matplotlib figures draw
onto a figure card, Plotly figures become HTML on a web-view card — and
both are laid out by the same rules, so a stack of either arranges the same
way on the canvas, on a dashboard and in a report.

**Bar mode** only matters for bar and histogram. Plotly stacks multiple
series on top of each other by default; **group** stands them side by
side, which is what you want when the point is to compare them. **stack**
is Plotly's own default, for when the total is the thing being read, and
**overlay** draws them on top of one another.

**Same Y scale** bounds every chart by the whole table, so the panels can
be compared by eye. **Min Y / Max Y** override that with a number of your
own: leave one blank to pin only the other end, and leave both blank —
which is the default — for the derived scale. A pinned bound is used
exactly as typed, with none of the 5% headroom a derived one gets, so Min
Y 0 puts the axis on zero. They work with Same Y scale off too: there each
chart is still scaled to its own rows, but the end you pinned stays put.
Box, violin and histogram derive their own value axis, so only a *pair* of
bounds does anything to those.

**Fill** is the plain choice: all of them **down** the page, or all of them
**across** it. With Columns and Rows both at 0 that is exactly what you
get — one column, or one row that scrolls sideways.

**Columns / Rows** constrain it into a grid: Columns 3 gives three across
and as many rows as it takes; Rows 2 gives two down and as many columns.
Set both for a fixed grid — if there are more charts than cells it grows
along the fill direction rather than hiding any.

**Scale %** zooms the card's contents the way it does on the single-chart
nodes: below 100 the charts are drawn smaller and more of the stack fits
on the card, above 100 they are drawn larger and you scroll. Here it is
the embedded browser's own zoom, so the charts stay crisp rather than
being magnified. It changes how much you see, not how big the card is —
Width and Height do that.

Scale, Columns, Rows and Fill are all marked `"cosmetic": True`, so
changing one re-arranges or re-zooms the charts without marking the node
dirty.

"Max charts" is a guard, not a preference: splitting on a high-cardinality
column by accident would otherwise build thousands of figures and hang the
run. It logs when it trims. The default is lower here than on the
matplotlib node: the page carries plotly.js once and each extra chart adds
little to its size, but every one of them is a live, interactive plot in
the same document, and that is what gets expensive to draw.

Needs the optional 'plotly' extra; install it from Tools > Manage Packages
if it is missing.
"""
NODE = {
    "label": "Chart per Value (Plotly)",
    "category": "Viz",
    "card": "webview",
    "inputs": [("table", "dataframe")],
    "outputs": [("figures", "any")],
}
PARAMS = [
    {"name": "split_by", "type": "columns", "label": "Split by",
     "multi": False, "default": "",
     "placeholder": "column to make one chart per value of"},
    {"name": "kind", "type": "choice", "label": "Kind",
     "options": ["line", "bar", "scatter", "area", "histogram", "box",
                 "violin"],
     "default": "line"},
    # Only bar and histogram read this. Plotly Express stacks bars by
    # default; side by side is nearly always what a comparison chart wants,
    # so that is the default here rather than Plotly's.
    {"name": "barmode", "type": "choice", "label": "Bar mode",
     "options": ["group", "stack", "overlay"], "default": "group"},
    {"name": "x", "type": "columns", "label": "X column", "multi": False,
     "default": "", "placeholder": "(index)"},
    {"name": "y", "type": "columns", "label": "Y columns",
     "default": "", "placeholder": "comma separated; empty = all numeric"},
    {"name": "color", "type": "columns", "label": "Color by", "multi": False,
     "default": "", "placeholder": "optional grouping column"},
    {"name": "shared_scale", "type": "bool", "label": "Same Y scale",
     "default": True},
    # Strings, not floats: blank has to mean "not pinned", and a spin box
    # has no way to say that. See core.chart_scale.
    {"name": "min_y", "type": "string", "label": "Min Y", "default": "",
     "placeholder": "(from the data)"},
    {"name": "max_y", "type": "string", "label": "Max Y", "default": "",
     "placeholder": "(from the data)"},
    {"name": "max_charts", "type": "int", "label": "Max charts",
     "default": 20, "min": 1, "max": 200},
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
    # Cosmetic here, unlike the single-chart nodes: zooming the card is
    # presentation, and re-running a slow split to show it smaller would be
    # as absurd as re-running it to show it in two columns.
    {"name": "scale", "type": "int", "label": "Scale %",
     "default": 100, "min": 25, "max": 400, "cosmetic": True},
]

# Kinds where a y-range means nothing: the value axis is a count or a
# distribution the figure derives itself, not a column we can bound.
_UNSCALED = ("histogram", "box", "violin")


def _stacks(kind, barmode):
    """Whether this kind piles its series on top of one another.

    px.area sets a stackgroup unconditionally, so it always does; bars only
    when asked to. Either way the Y scale has to bound the row totals.
    """
    return kind == "area" or (kind == "bar" and barmode == "stack")


def run(ctx, table):
    import importlib.util

    if importlib.util.find_spec("plotly") is None:
        raise RuntimeError(
            "Chart per Value (Plotly) requires the optional plotly extra. "
            "Install it with `pip install flograph[plotly]` or "
            "Tools > Manage Packages > plotly.")

    import plotly.express as px

    from flograph.core.chart_scale import as_bound, data_extent, y_limits

    split_by = (ctx.params.get("split_by") or "").strip()
    if not split_by:
        raise ValueError("set 'Split by' to the column to make one chart per")
    if split_by not in table.columns:
        raise ValueError(f"no column {split_by!r} in the input")

    x = (ctx.params.get("x") or "").strip()
    color = (ctx.params.get("color") or "").strip()
    y = [c.strip() for c in (ctx.params.get("y") or "").split(",") if c.strip()]
    if not y:
        y = [c for c in table.select_dtypes("number").columns
             if c not in (split_by, x, color)]
    if not y:
        raise ValueError("no numeric columns to plot")
    missing = [c for c in (*y, *filter(None, (x, color)))
               if c not in table.columns]
    if missing:
        raise ValueError(f"columns not in table: {missing}")

    kind = ctx.params.get("kind", "line")
    barmode = ctx.params.get("barmode", "group")
    limit = int(ctx.params.get("max_charts", 20))
    groups = list(table.groupby(split_by, sort=True, observed=True))
    if len(groups) > limit:
        ctx.log(f"{len(groups)} values in {split_by!r} — charting the first "
                f"{limit}. Raise 'Max charts' or filter upstream.")
        groups = groups[:limit]

    min_y = as_bound(ctx.params.get("min_y"))
    max_y = as_bound(ctx.params.get("max_y"))
    pinned = min_y is not None or max_y is not None
    stacked = _stacks(kind, barmode) and len(y) > 1
    scalable = kind not in _UNSCALED
    shared = bool(ctx.params.get("shared_scale", True)) and scalable

    # one scale across every chart, so the panels can be compared by eye —
    # which is usually the entire reason for splitting a chart up
    limits = None
    if not scalable:
        # nothing to derive from a distribution the figure works out for
        # itself, but both ends pinned by hand still bounds it
        limits = y_limits(None, min_y, max_y)
    elif shared:
        limits = y_limits(data_extent(table, y, stacked), min_y, max_y)

    plot = getattr(px, kind)
    figures = []
    for index, (value, group) in enumerate(groups):
        ctx.check_cancelled()
        ctx.progress(index / len(groups))
        kwargs = {"y": y if len(y) > 1 else y[0],
                  "title": f"{split_by}: {value}"}
        if x:
            kwargs["x"] = x
        if color:
            kwargs["color"] = color
        figure = plot(group, **kwargs)
        if scalable and not shared and pinned:
            # each chart keeps its own scale, but the pinned end holds —
            # measured on this group's rows, since there is no shared
            # extent to take the free end from
            limits = y_limits(data_extent(group, y, stacked), min_y, max_y)
        if limits is not None:
            figure.update_yaxes(range=list(limits))
        if kind in ("bar", "histogram"):
            figure.update_layout(barmode=barmode)
        # The stack sizes each cell itself; a figure that insists on its own
        # pixel height would overflow the cell it was given.
        figure.update_layout(autosize=True, margin={"t": 40, "b": 30,
                                                    "l": 40, "r": 20})
        figures.append(figure)

    ctx.log(f"{len(figures)} chart(s), one per value of {split_by!r}")
    return {"figures": figures}
