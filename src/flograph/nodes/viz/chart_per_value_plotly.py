"""Chart per Value (Plotly)

One interactive chart for every distinct value of a column — the same plot
repeated across regions, products, months — shown as a stack on the card
and on a dashboard tile, each one with Plotly's own hover, zoom and pan.

Set "Split by" to the column to loop over and set up the chart as you would
on Show Plotly. Each chart sees only that group's rows.

This is the Plotly half of Chart per Value. The mechanism is identical and
is not special-cased in either node: the node returns a **list** of
figures, and flograph renders a list as a stack wherever a single one would
go. The only difference is what the list holds — matplotlib figures draw
onto a figure card, Plotly figures become HTML on a web-view card — and
both are laid out by the same rules, so a stack of either arranges the same
way on the canvas, on a dashboard and in a report.

**Every chart type and setting Show Plotly has**, from the same shared
parameter set (`flograph.core.plotly_spec`): twenty-eight chart kinds, the
encodings, facets, trendlines, bins, palettes and axis settings, each one
appearing only for the chart kinds that have it, and the deeper ones behind
**More options**. A chart type added to one node appears on the other.

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
(This is the one setting that means something different here than on Show
Plotly, where the two boxes are simply the axis range and both are needed.)
Box, violin, histogram and the other distribution kinds derive their own
value axis, as do pie, treemap and the rest with no Y axis at all, so the
shared scale is skipped for those.

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
from flograph.core import plotly_spec

NODE = {
    "label": "Chart per Value (Plotly)",
    "category": "Viz",
    "version": "2.0",
    "card": "webview",
    "inputs": [("table", "dataframe")],
    "outputs": [("figures", "any")],
}
PARAMS = [
    {"name": "split_by", "type": "columns", "label": "Split by",
     "multi": False, "default": "",
     "placeholder": "column to make one chart per value of"},
    # Every chart type and every Plotly Express setting, shared with Show
    # Plotly. Min Y / Max Y come from here too but are read below rather
    # than passed to plotly, because on this node they cooperate with the
    # shared scale instead of being a plain axis range.
    *plotly_spec.params(),
    {"name": "shared_scale", "type": "bool", "label": "Same Y scale",
     "default": True},
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


def _stacks(kind, barmode):
    """Whether this kind piles its series on top of one another.

    px.area sets a stackgroup unconditionally, so it always does; bars only
    when asked to. Either way the Y scale has to bound the row totals.
    """
    return kind == "area" or (kind == "bar" and barmode in ("stack",
                                                            "relative"))


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

    kind = ctx.params.get("kind", "line")
    barmode = ctx.params.get("barmode", "group")
    # The two range boxes are this node's own shared-scale controls, so
    # they are kept away from the figure's plain axis range below.
    values = dict(ctx.params, min_y="", max_y="")
    kwargs, ignored = plotly_spec.build(values, table, px,
                                        exclude=[split_by])

    # Only the numeric part of Y can be measured for a shared scale. It
    # used to be all of it, back when the seven kinds all plotted numbers
    # up the Y axis — a timeline's Y is task names and a funnel's is
    # stages, and asking for the extent of those raises inside pandas.
    numeric = set(table.select_dtypes("number").columns)
    y = [c for c in plotly_spec.column_list(kwargs.get("y")) if c in numeric]
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
    # Only a chart with a Y axis made of columns can be bounded: a
    # distribution derives its own value axis, and a pie has none.
    scalable = bool(y) and kind not in plotly_spec.DISTRIBUTION_KINDS
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

    title = str(ctx.params.get("title") or "").strip()
    # The stack sizes each cell itself; a figure that insists on its own
    # pixel height would overflow the cell it was given.
    layout = dict(plotly_spec.layout_updates(ctx.params, kind),
                  autosize=True,
                  margin={"t": 40, "b": 30, "l": 40, "r": 20})
    plot = getattr(px, kind)
    figures = []
    for index, (value, group) in enumerate(groups):
        ctx.check_cancelled()
        ctx.progress(index / len(groups))
        panel = f"{split_by}: {value}"
        kwargs["title"] = f"{title} — {panel}" if title else panel
        # Per chart rather than around the loop: building is not
        # thread-safe (see plotly_spec.FIGURE_LOCK), but holding the lock
        # across a forty-chart split would stall every other plotly node
        # in the flow for the whole of it.
        with plotly_spec.FIGURE_LOCK:
            figure = plot(group, **kwargs)
        if scalable and not shared and pinned:
            # each chart keeps its own scale, but the pinned end holds —
            # measured on this group's rows, since there is no shared
            # extent to take the free end from
            limits = y_limits(data_extent(group, y, stacked), min_y, max_y)
        if limits is not None:
            figure.update_yaxes(range=list(limits))
        figure.update_layout(**layout)
        figures.append(figure)

    ctx.log(f"{len(figures)} chart(s), one per value of {split_by!r}")
    if ignored:
        ctx.log(f"a {kind} chart has no use for: {', '.join(ignored)}")
    return {"figures": figures}
