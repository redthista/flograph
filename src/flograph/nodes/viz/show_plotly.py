"""Show Plotly

Every chart Plotly Express draws, on an interactive card — hover, zoom and
pan in place. Needs the 'plotly' package: install it from Tools > Manage
Packages if missing. Outputs the plotly Figure for further consumers.

**Kind** picks the chart, and the rest of the panel follows it: only the
settings that chart actually has appear. Twenty-eight of them, in families:

* **x/y** — line, scatter, bar, area, funnel, timeline
* **distributions** — histogram, box, violin, strip, ecdf, density_heatmap,
  density_contour
* **parts of a whole** — pie, funnel_area, sunburst, treemap, icicle
* **many variables at once** — scatter_matrix, parallel_coordinates,
  parallel_categories
* **three axes** — scatter_3d, line_3d, scatter_polar, line_polar,
  bar_polar, scatter_ternary, line_ternary

Leave the columns blank and the chart plots every numeric column it can
find: down the Y axis for most charts, and along X for a distribution,
since a histogram of a column is what "histogram" means. A chart built from
columns named some other way — a pie's slices, a treemap's hierarchy — says
which box it needs instead of guessing.

**More options** opens the rest: encodings (size, symbol, dash, pattern,
text, hover), facets, animation frames, error bars, trendlines, marginal
plots, bin and normalisation settings, axis ranges and log scales,
palettes and colour scales, opacity. Everything hidden behind it is still
hidden per chart kind, so a box plot never offers a bin count. The tick
itself is cosmetic — opening the drawer doesn't redraw anything.

Settings that don't apply to the chart you switched to are kept, not
dropped: switch back and they are as you left them. The node logs the
ones it passed over, so a setting that appears to do nothing says why.

**Bar mode** only matters for bar and histogram. Plotly stacks multiple
series on top of each other by default; **group** stands them side by side,
which is what you want when the point is to compare them. **stack** is
Plotly's own default, for when the total is the thing being read,
**overlay** draws them on top of one another, and **relative** stacks
positive and negative away from zero.

**Min/Max Y** and **Min/Max X** pin an axis. Both ends are needed — plotly
has no way to be told about only one — and on a log axis you still type the
values you want to see, not their exponents.

For anything about how the finished chart *looks* rather than what it
shows — legend placement, axis titles, tick formats, gridlines, reference
lines, a note in the corner — wire it into a **Plotly Style** node, which
restyles any Plotly figure including this one.

The full parameter set lives in `flograph.core.plotly_spec` and is shared
with Chart per Value (Plotly), so the two nodes offer the same chart types
and the same settings.
"""
from flograph.core import plotly_spec

NODE = {
    "label": "Show Plotly",
    "category": "Viz",
    "card": "webview",
    "inputs": [("table", "dataframe")],
    "outputs": [("figure", "object")],
}
PARAMS = [
    *plotly_spec.params(),
    {"name": "width", "type": "int", "label": "Width",
     "default": 420, "min": 260, "max": 1600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 320, "min": 200, "max": 2000},
    # Cosmetic: run() never reads it — the zoom is the embedded browser's
    # own, applied to the figure this node already produced. Dirtying on it
    # would re-run the plot, and everything downstream, for the same figure.
    {"name": "scale", "type": "int", "label": "Scale %",
     "default": 100, "min": 25, "max": 400, "cosmetic": True},
]


def run(ctx, table):
    try:
        import plotly.express as px
    except ImportError:
        raise ImportError(
            "plotly is not installed — add it via Tools > Manage Packages"
        ) from None

    kind = ctx.params.get("kind", "line")
    kwargs, ignored = plotly_spec.build(ctx.params, table, px)
    try:
        # Building a figure is not thread-safe — see plotly_spec.FIGURE_LOCK.
        with plotly_spec.FIGURE_LOCK:
            fig = getattr(px, kind)(table, **kwargs)
    except ImportError as exc:
        # The one px argument with a dependency of its own: a trendline is
        # fitted by statsmodels, which plotly does not install with itself.
        # Anything else that fails to import is not ours to explain.
        if "trendline" not in kwargs:
            raise
        raise ImportError(
            f"a {kwargs['trendline']} trendline needs the 'statsmodels' "
            f"package — add it via Tools > Manage Packages, or set "
            f"Trendline back to none ({exc})") from None
    layout = plotly_spec.layout_updates(ctx.params, kind)
    if layout:
        fig.update_layout(**layout)

    ctx.log(f"plotted {len(fig.data)} trace(s) ({kind})")
    if ignored:
        ctx.log(f"a {kind} chart has no use for: {', '.join(ignored)}")
    return {"figure": fig}
