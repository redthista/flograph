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

**This node stands alone.** Every chart kind, every setting and the logic
that turns them into a `px.<kind>()` call live directly below rather than
in a shared `core` module, so the file can be copied into a user-nodes
folder on an older flograph and will work there — including sharing the
one figure lock with everything else, which it parks in `sys.modules` when
there is no `core.plotly_spec` to take it from.

**Chart per Value (Plotly)** carries an identical copy of everything below
this line — the two nodes offer the same 28 chart kinds and the same
settings by construction, not by sharing code, so a chart type added here
has to be added there too. That trade was deliberate: importing this from
a shared module used to be exactly how these nodes worked, and it kept the
two in lockstep automatically — see `tests/test_plotly_kinds.py`, which
still checks the two copies agree, and `tests/test_plotly_spec.py`, which
checks each copy's `KIND_ARGS` table against the plotly actually installed.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

NODE = {
    "label": "Show Plotly",
    "category": "Viz",
    "version": "2.0",
    "card": "webview",
    "inputs": [("table", "dataframe")],
    "outputs": [("figure", "object")],
}

#: Chart kinds in dropdown order — grouped by family, the everyday ones
#: first. Each name is the Plotly Express function that draws it, so what
#: the dropdown says is also what plotly's own documentation calls it.
_KINDS: tuple[str, ...] = (
    # x/y charts
    "line", "scatter", "bar", "area", "funnel", "timeline",
    # one variable's distribution
    "histogram", "box", "violin", "strip", "ecdf",
    "density_heatmap", "density_contour",
    # parts of a whole
    "pie", "funnel_area", "sunburst", "treemap", "icicle",
    # many variables at once
    "scatter_matrix", "parallel_coordinates", "parallel_categories",
    # three axes
    "scatter_3d", "line_3d",
    "scatter_polar", "line_polar", "bar_polar",
    "scatter_ternary", "line_ternary",
)

#: The kinds whose value axis is a count or a distribution the figure
#: derives itself, rather than a column that can be bounded. Chart per
#: Value skips its shared Y scale for these, and `_build()` fills in `x`
#: rather than `y` when nothing is chosen: a histogram of a column is what
#: "histogram" means, where filling `y` would make a two-dimensional one.
_DISTRIBUTION_KINDS: frozenset[str] = frozenset({
    "histogram", "box", "violin", "strip", "ecdf",
    "density_heatmap", "density_contour",
})

#: Arguments that name the columns a chart is built from, as opposed to the
#: ones that decorate it. `_build()` treats a missing role column as an
#: error worth naming, since the chart cannot be drawn without it.
_ROLE_ARGS: frozenset[str] = frozenset({
    "x", "y", "z", "x_start", "x_end", "names", "values", "path",
    "dimensions", "r", "theta", "a", "b", "c",
})

_KIND_ARGS: dict[str, frozenset[str]] = {
    'line': frozenset({
        'animation_frame', 'animation_group', 'category_orders',
        'color', 'color_discrete_map', 'color_discrete_sequence',
        'custom_data', 'error_x', 'error_x_minus', 'error_y',
        'error_y_minus', 'facet_col', 'facet_col_spacing',
        'facet_col_wrap', 'facet_row', 'facet_row_spacing',
        'hover_data', 'hover_name', 'line_dash', 'line_dash_map',
        'line_dash_sequence', 'line_group', 'line_shape', 'log_x',
        'log_y', 'markers', 'orientation', 'range_x', 'range_y',
        'render_mode', 'symbol', 'symbol_map', 'symbol_sequence',
        'text', 'x', 'y'
    }),
    'scatter': frozenset({
        'animation_frame', 'animation_group', 'category_orders',
        'color', 'color_continuous_midpoint', 'color_continuous_scale',
        'color_discrete_map', 'color_discrete_sequence', 'custom_data',
        'error_x', 'error_x_minus', 'error_y', 'error_y_minus',
        'facet_col', 'facet_col_spacing', 'facet_col_wrap', 'facet_row',
        'facet_row_spacing', 'hover_data', 'hover_name', 'log_x',
        'log_y', 'marginal_x', 'marginal_y', 'opacity', 'orientation',
        'range_color', 'range_x', 'range_y', 'render_mode', 'size',
        'size_max', 'symbol', 'symbol_map', 'symbol_sequence', 'text',
        'trendline', 'trendline_color_override', 'trendline_options',
        'trendline_scope', 'x', 'y'
    }),
    'bar': frozenset({
        'animation_frame', 'animation_group', 'barmode', 'base',
        'category_orders', 'color', 'color_continuous_midpoint',
        'color_continuous_scale', 'color_discrete_map',
        'color_discrete_sequence', 'custom_data', 'error_x',
        'error_x_minus', 'error_y', 'error_y_minus', 'facet_col',
        'facet_col_spacing', 'facet_col_wrap', 'facet_row',
        'facet_row_spacing', 'hover_data', 'hover_name', 'log_x',
        'log_y', 'opacity', 'orientation', 'pattern_shape',
        'pattern_shape_map', 'pattern_shape_sequence', 'range_color',
        'range_x', 'range_y', 'text', 'text_auto', 'x', 'y'
    }),
    'area': frozenset({
        'animation_frame', 'animation_group', 'category_orders',
        'color', 'color_discrete_map', 'color_discrete_sequence',
        'custom_data', 'facet_col', 'facet_col_spacing',
        'facet_col_wrap', 'facet_row', 'facet_row_spacing', 'groupnorm',
        'hover_data', 'hover_name', 'line_group', 'line_shape', 'log_x',
        'log_y', 'markers', 'orientation', 'pattern_shape',
        'pattern_shape_map', 'pattern_shape_sequence', 'range_x',
        'range_y', 'symbol', 'symbol_map', 'symbol_sequence', 'text',
        'x', 'y'
    }),
    'funnel': frozenset({
        'animation_frame', 'animation_group', 'category_orders',
        'color', 'color_discrete_map', 'color_discrete_sequence',
        'custom_data', 'facet_col', 'facet_col_spacing',
        'facet_col_wrap', 'facet_row', 'facet_row_spacing',
        'hover_data', 'hover_name', 'log_x', 'log_y', 'opacity',
        'orientation', 'range_x', 'range_y', 'text', 'x', 'y'
    }),
    'timeline': frozenset({
        'animation_frame', 'animation_group', 'category_orders',
        'color', 'color_continuous_midpoint', 'color_continuous_scale',
        'color_discrete_map', 'color_discrete_sequence', 'custom_data',
        'facet_col', 'facet_col_spacing', 'facet_col_wrap', 'facet_row',
        'facet_row_spacing', 'hover_data', 'hover_name', 'opacity',
        'pattern_shape', 'pattern_shape_map', 'pattern_shape_sequence',
        'range_color', 'range_x', 'range_y', 'text', 'x_end', 'x_start',
        'y'
    }),
    'histogram': frozenset({
        'animation_frame', 'animation_group', 'barmode', 'barnorm',
        'category_orders', 'color', 'color_discrete_map',
        'color_discrete_sequence', 'cumulative', 'facet_col',
        'facet_col_spacing', 'facet_col_wrap', 'facet_row',
        'facet_row_spacing', 'histfunc', 'histnorm', 'hover_data',
        'hover_name', 'log_x', 'log_y', 'marginal', 'nbins', 'opacity',
        'orientation', 'pattern_shape', 'pattern_shape_map',
        'pattern_shape_sequence', 'range_x', 'range_y', 'text_auto',
        'x', 'y'
    }),
    'box': frozenset({
        'animation_frame', 'animation_group', 'boxmode',
        'category_orders', 'color', 'color_discrete_map',
        'color_discrete_sequence', 'custom_data', 'facet_col',
        'facet_col_spacing', 'facet_col_wrap', 'facet_row',
        'facet_row_spacing', 'hover_data', 'hover_name', 'log_x',
        'log_y', 'notched', 'orientation', 'points', 'range_x',
        'range_y', 'x', 'y'
    }),
    'violin': frozenset({
        'animation_frame', 'animation_group', 'box', 'category_orders',
        'color', 'color_discrete_map', 'color_discrete_sequence',
        'custom_data', 'facet_col', 'facet_col_spacing',
        'facet_col_wrap', 'facet_row', 'facet_row_spacing',
        'hover_data', 'hover_name', 'log_x', 'log_y', 'orientation',
        'points', 'range_x', 'range_y', 'violinmode', 'x', 'y'
    }),
    'strip': frozenset({
        'animation_frame', 'animation_group', 'category_orders',
        'color', 'color_discrete_map', 'color_discrete_sequence',
        'custom_data', 'facet_col', 'facet_col_spacing',
        'facet_col_wrap', 'facet_row', 'facet_row_spacing',
        'hover_data', 'hover_name', 'log_x', 'log_y', 'orientation',
        'range_x', 'range_y', 'stripmode', 'x', 'y'
    }),
    'ecdf': frozenset({
        'animation_frame', 'animation_group', 'category_orders',
        'color', 'color_discrete_map', 'color_discrete_sequence',
        'ecdfmode', 'ecdfnorm', 'facet_col', 'facet_col_spacing',
        'facet_col_wrap', 'facet_row', 'facet_row_spacing',
        'hover_data', 'hover_name', 'line_dash', 'line_dash_map',
        'line_dash_sequence', 'lines', 'log_x', 'log_y', 'marginal',
        'markers', 'opacity', 'orientation', 'range_x', 'range_y',
        'render_mode', 'symbol', 'symbol_map', 'symbol_sequence',
        'text', 'x', 'y'
    }),
    'density_heatmap': frozenset({
        'animation_frame', 'animation_group', 'category_orders',
        'color_continuous_midpoint', 'color_continuous_scale',
        'facet_col', 'facet_col_spacing', 'facet_col_wrap', 'facet_row',
        'facet_row_spacing', 'histfunc', 'histnorm', 'hover_data',
        'hover_name', 'log_x', 'log_y', 'marginal_x', 'marginal_y',
        'nbinsx', 'nbinsy', 'opacity', 'orientation', 'range_color',
        'range_x', 'range_y', 'text_auto', 'x', 'y', 'z'
    }),
    'density_contour': frozenset({
        'animation_frame', 'animation_group', 'category_orders',
        'color', 'color_discrete_map', 'color_discrete_sequence',
        'facet_col', 'facet_col_spacing', 'facet_col_wrap', 'facet_row',
        'facet_row_spacing', 'histfunc', 'histnorm', 'hover_data',
        'hover_name', 'log_x', 'log_y', 'marginal_x', 'marginal_y',
        'nbinsx', 'nbinsy', 'orientation', 'range_x', 'range_y',
        'text_auto', 'trendline', 'trendline_color_override',
        'trendline_options', 'trendline_scope', 'x', 'y', 'z'
    }),
    'pie': frozenset({
        'category_orders', 'color', 'color_discrete_map',
        'color_discrete_sequence', 'custom_data', 'facet_col',
        'facet_col_spacing', 'facet_col_wrap', 'facet_row',
        'facet_row_spacing', 'hole', 'hover_data', 'hover_name',
        'names', 'opacity', 'values'
    }),
    'funnel_area': frozenset({
        'color', 'color_discrete_map', 'color_discrete_sequence',
        'custom_data', 'hover_data', 'hover_name', 'names', 'opacity',
        'values'
    }),
    'sunburst': frozenset({
        'branchvalues', 'color', 'color_continuous_midpoint',
        'color_continuous_scale', 'color_discrete_map',
        'color_discrete_sequence', 'custom_data', 'hover_data',
        'hover_name', 'ids', 'maxdepth', 'names', 'parents', 'path',
        'range_color', 'values'
    }),
    'treemap': frozenset({
        'branchvalues', 'color', 'color_continuous_midpoint',
        'color_continuous_scale', 'color_discrete_map',
        'color_discrete_sequence', 'custom_data', 'hover_data',
        'hover_name', 'ids', 'maxdepth', 'names', 'parents', 'path',
        'range_color', 'values'
    }),
    'icicle': frozenset({
        'branchvalues', 'color', 'color_continuous_midpoint',
        'color_continuous_scale', 'color_discrete_map',
        'color_discrete_sequence', 'custom_data', 'hover_data',
        'hover_name', 'ids', 'maxdepth', 'names', 'parents', 'path',
        'range_color', 'values'
    }),
    'scatter_matrix': frozenset({
        'category_orders', 'color', 'color_continuous_midpoint',
        'color_continuous_scale', 'color_discrete_map',
        'color_discrete_sequence', 'custom_data', 'dimensions',
        'hover_data', 'hover_name', 'opacity', 'range_color', 'size',
        'size_max', 'symbol', 'symbol_map', 'symbol_sequence'
    }),
    'parallel_coordinates': frozenset({
        'color', 'color_continuous_midpoint', 'color_continuous_scale',
        'dimensions', 'range_color'
    }),
    'parallel_categories': frozenset({
        'color', 'color_continuous_midpoint', 'color_continuous_scale',
        'dimensions', 'dimensions_max_cardinality', 'range_color'
    }),
    'scatter_3d': frozenset({
        'animation_frame', 'animation_group', 'category_orders',
        'color', 'color_continuous_midpoint', 'color_continuous_scale',
        'color_discrete_map', 'color_discrete_sequence', 'custom_data',
        'error_x', 'error_x_minus', 'error_y', 'error_y_minus',
        'error_z', 'error_z_minus', 'hover_data', 'hover_name', 'log_x',
        'log_y', 'log_z', 'opacity', 'range_color', 'range_x',
        'range_y', 'range_z', 'size', 'size_max', 'symbol',
        'symbol_map', 'symbol_sequence', 'text', 'x', 'y', 'z'
    }),
    'line_3d': frozenset({
        'animation_frame', 'animation_group', 'category_orders',
        'color', 'color_discrete_map', 'color_discrete_sequence',
        'custom_data', 'error_x', 'error_x_minus', 'error_y',
        'error_y_minus', 'error_z', 'error_z_minus', 'hover_data',
        'hover_name', 'line_dash', 'line_dash_map',
        'line_dash_sequence', 'line_group', 'log_x', 'log_y', 'log_z',
        'markers', 'range_x', 'range_y', 'range_z', 'symbol',
        'symbol_map', 'symbol_sequence', 'text', 'x', 'y', 'z'
    }),
    'scatter_polar': frozenset({
        'animation_frame', 'animation_group', 'category_orders',
        'color', 'color_continuous_midpoint', 'color_continuous_scale',
        'color_discrete_map', 'color_discrete_sequence', 'custom_data',
        'direction', 'hover_data', 'hover_name', 'log_r', 'opacity',
        'r', 'range_color', 'range_r', 'range_theta', 'render_mode',
        'size', 'size_max', 'start_angle', 'symbol', 'symbol_map',
        'symbol_sequence', 'text', 'theta'
    }),
    'line_polar': frozenset({
        'animation_frame', 'animation_group', 'category_orders',
        'color', 'color_discrete_map', 'color_discrete_sequence',
        'custom_data', 'direction', 'hover_data', 'hover_name',
        'line_close', 'line_dash', 'line_dash_map',
        'line_dash_sequence', 'line_group', 'line_shape', 'log_r',
        'markers', 'r', 'range_r', 'range_theta', 'render_mode',
        'start_angle', 'symbol', 'symbol_map', 'symbol_sequence',
        'text', 'theta'
    }),
    'bar_polar': frozenset({
        'animation_frame', 'animation_group', 'barmode', 'barnorm',
        'base', 'category_orders', 'color', 'color_continuous_midpoint',
        'color_continuous_scale', 'color_discrete_map',
        'color_discrete_sequence', 'custom_data', 'direction',
        'hover_data', 'hover_name', 'log_r', 'pattern_shape',
        'pattern_shape_map', 'pattern_shape_sequence', 'r',
        'range_color', 'range_r', 'range_theta', 'start_angle', 'theta'
    }),
    'scatter_ternary': frozenset({
        'a', 'animation_frame', 'animation_group', 'b', 'c',
        'category_orders', 'color', 'color_continuous_midpoint',
        'color_continuous_scale', 'color_discrete_map',
        'color_discrete_sequence', 'custom_data', 'hover_data',
        'hover_name', 'opacity', 'range_color', 'size', 'size_max',
        'symbol', 'symbol_map', 'symbol_sequence', 'text'
    }),
    'line_ternary': frozenset({
        'a', 'animation_frame', 'animation_group', 'b', 'c',
        'category_orders', 'color', 'color_discrete_map',
        'color_discrete_sequence', 'custom_data', 'hover_data',
        'hover_name', 'line_dash', 'line_dash_map',
        'line_dash_sequence', 'line_group', 'line_shape', 'markers',
        'symbol', 'symbol_map', 'symbol_sequence', 'text'
    }),
}
#: Named colour sequences for a *categorical* colour, resolved against
#: `px.colors.qualitative` at build time. Plotly takes a list of colours
#: rather than a palette name, so the name has to be looked up.
_COLOR_SEQUENCES: tuple[str, ...] = (
    "Plotly", "D3", "G10", "T10", "Set1", "Set2", "Set3", "Dark2",
    "Pastel1", "Pastel2", "Antique", "Bold", "Pastel", "Prism", "Safe",
    "Vivid", "Alphabet", "Dark24", "Light24",
)

#: Named colour scales for a *continuous* colour. Plotly resolves these
#: from the name itself, so they are passed through untouched. Sequential
#: first, then the diverging ones, which are the ones worth a midpoint.
_COLOR_SCALES: tuple[str, ...] = (
    "Viridis", "Cividis", "Plasma", "Inferno", "Magma", "Turbo",
    "Blues", "Greens", "Reds", "Purples", "Oranges", "Greys",
    "YlGnBu", "YlOrRd", "Portland", "Electric", "Hot", "Jet", "Rainbow",
    "RdBu", "RdYlGn", "Spectral", "Balance", "Curl", "Delta", "Tealrose",
    "Temps", "Tropic", "Picnic", "Earth",
)

#: Figure themes. Plotly's own names — `template=None` is "default", which
#: means whatever plotly's global default is set to.
_TEMPLATES: tuple[str, ...] = (
    "default", "plotly", "plotly_white", "plotly_dark", "ggplot2",
    "seaborn", "simple_white", "presentation", "none",
)


#: Arguments every px function takes, so they are not in the per-kind
#: table and no chart kind hides them.
_UNIVERSAL_ARGS: frozenset[str] = frozenset({
    "title", "subtitle", "template", "labels", "width", "height",
})


def _kinds_taking(*args: str) -> list[str]:
    """The chart kinds whose px function accepts any of `args`.

    This is what makes a param's `visible_when` self-maintaining: a row
    that feeds `trendline` is shown for exactly the kinds that have a
    trendline, worked out from the signature table rather than from a list
    somebody has to remember to update.
    """
    if any(a in _UNIVERSAL_ARGS for a in args):
        return list(_KINDS)
    return [k for k in _KINDS if any(a in _KIND_ARGS[k] for a in args)]


# Every row below is a ParamSpec dict plus, at most, these three private
# keys, which `_params()` strips before handing the row to the node:
#
#   "arg"      the px argument this row feeds. Decides which kinds show it
#              (via _kinds_taking) and how _build() emits it.
#   "kinds"    an explicit kind list, for the few rows whose visibility
#              isn't a straight read of one px argument.
#   "advanced" hide behind the "More options" tick.
#
# Order is the order of the properties panel: what the chart is made of,
# then what it is coloured and split by, then the shape of the chart
# itself, then axes, then theme, then the card.
_ROWS: list[dict[str, Any]] = [
    {"name": "kind", "type": "choice", "label": "Kind",
     "options": list(_KINDS), "default": "line"},
    # Reveals the two-thirds of the panel that no chart needs every day.
    # Cosmetic, so opening the drawer doesn't re-run the chart.
    {"name": "more", "type": "bool", "label": "More options",
     "default": False, "cosmetic": True},

    # ---------------------------------------------------- what to plot
    {"name": "x", "type": "columns", "label": "X column", "multi": False,
     "default": "", "placeholder": "(index)", "arg": "x"},
    {"name": "y", "type": "columns", "label": "Y columns", "default": "",
     "placeholder": "comma separated; empty = all numeric", "arg": "y"},
    {"name": "z", "type": "columns", "label": "Z column", "multi": False,
     "default": "", "placeholder": "the value at each x/y", "arg": "z"},
    {"name": "x_start", "type": "columns", "label": "Start column",
     "multi": False, "default": "", "placeholder": "when each bar begins",
     "arg": "x_start"},
    {"name": "x_end", "type": "columns", "label": "Finish column",
     "multi": False, "default": "", "placeholder": "when each bar ends",
     "arg": "x_end"},
    {"name": "names", "type": "columns", "label": "Labels column",
     "multi": False, "default": "", "placeholder": "one slice per value",
     "arg": "names"},
    {"name": "values", "type": "columns", "label": "Values column",
     "multi": False, "default": "", "placeholder": "how big each slice is",
     "arg": "values"},
    {"name": "path", "type": "columns", "label": "Hierarchy",
     "default": "", "placeholder": "outermost level first, comma separated",
     "arg": "path"},
    {"name": "dimensions", "type": "columns", "label": "Dimensions",
     "default": "", "placeholder": "comma separated; empty = all numeric",
     "arg": "dimensions"},
    {"name": "r", "type": "columns", "label": "Radius column",
     "multi": False, "default": "", "arg": "r"},
    {"name": "theta", "type": "columns", "label": "Angle column",
     "multi": False, "default": "", "arg": "theta"},
    {"name": "a", "type": "columns", "label": "Corner A", "multi": False,
     "default": "", "arg": "a"},
    {"name": "b", "type": "columns", "label": "Corner B", "multi": False,
     "default": "", "arg": "b"},
    {"name": "c", "type": "columns", "label": "Corner C", "multi": False,
     "default": "", "arg": "c"},

    # -------------------------------------------- what to encode it by
    {"name": "color", "type": "columns", "label": "Color by", "multi": False,
     "default": "", "placeholder": "optional grouping column",
     "arg": "color"},
    {"name": "size", "type": "columns", "label": "Size by", "multi": False,
     "default": "", "placeholder": "marker size from a column",
     "arg": "size"},
    {"name": "size_max", "type": "int", "label": "Largest marker",
     "default": 0, "min": 0, "max": 100, "arg": "size_max",
     "advanced": True},
    {"name": "symbol", "type": "columns", "label": "Symbol by",
     "multi": False, "default": "", "arg": "symbol", "advanced": True},
    {"name": "line_dash", "type": "columns", "label": "Dash by",
     "multi": False, "default": "", "arg": "line_dash", "advanced": True},
    {"name": "pattern_shape", "type": "columns", "label": "Pattern by",
     "multi": False, "default": "", "arg": "pattern_shape",
     "advanced": True},
    {"name": "line_group", "type": "columns", "label": "One line per",
     "multi": False, "default": "", "arg": "line_group", "advanced": True},
    {"name": "text", "type": "columns", "label": "Text labels",
     "multi": False, "default": "",
     "placeholder": "print a column on each mark",
     "arg": "text", "advanced": True},
    {"name": "text_auto", "type": "bool", "label": "Print the values",
     "default": False, "arg": "text_auto", "advanced": True},
    {"name": "hover_name", "type": "columns", "label": "Hover title",
     "multi": False, "default": "", "arg": "hover_name", "advanced": True},
    {"name": "hover_data", "type": "columns", "label": "Hover extras",
     "default": "", "placeholder": "more columns in the tooltip",
     "arg": "hover_data", "advanced": True},
    {"name": "labels", "type": "text", "label": "Rename axes",
     "default": "", "insert_columns": "mapping",
     "placeholder": "column = Label, one per line",
     "arg": "labels", "advanced": True},
    {"name": "facet_row", "type": "columns", "label": "Facet rows by",
     "multi": False, "default": "", "placeholder": "a panel per value, down",
     "arg": "facet_row"},
    {"name": "facet_col", "type": "columns", "label": "Facet columns by",
     "multi": False, "default": "", "placeholder": "a panel per value, across",
     "arg": "facet_col"},
    {"name": "facet_col_wrap", "type": "int", "label": "Facets per row",
     "default": 0, "min": 0, "max": 12, "arg": "facet_col_wrap",
     "advanced": True},
    {"name": "animation_frame", "type": "columns", "label": "Animate by",
     "multi": False, "default": "", "placeholder": "a frame per value",
     "arg": "animation_frame", "advanced": True},
    {"name": "animation_group", "type": "columns", "label": "Animation id",
     "multi": False, "default": "",
     "placeholder": "what makes a row the same row between frames",
     "arg": "animation_group", "advanced": True},
    {"name": "error_y", "type": "columns", "label": "Y error", "multi": False,
     "default": "", "arg": "error_y", "advanced": True},
    {"name": "error_y_minus", "type": "columns", "label": "Y error (down)",
     "multi": False, "default": "", "placeholder": "for an uneven error bar",
     "arg": "error_y_minus", "advanced": True},
    {"name": "error_x", "type": "columns", "label": "X error", "multi": False,
     "default": "", "arg": "error_x", "advanced": True},
    {"name": "error_x_minus", "type": "columns", "label": "X error (left)",
     "multi": False, "default": "", "arg": "error_x_minus",
     "advanced": True},
    {"name": "error_z", "type": "columns", "label": "Z error", "multi": False,
     "default": "", "arg": "error_z", "advanced": True},

    # ------------------------------------------ the shape of the chart
    {"name": "orientation", "type": "choice", "label": "Orientation",
     "options": ["auto", "vertical", "horizontal"], "default": "auto",
     "arg": "orientation", "advanced": True},
    {"name": "barmode", "type": "choice", "label": "Bar mode",
     "options": ["group", "stack", "overlay", "relative"], "default": "group",
     "arg": "barmode"},
    # px.bar is the one bar chart without a barnorm argument, so for that
    # kind _build() leaves it to _layout_updates(); layout.barnorm means
    # the same thing.
    {"name": "barnorm", "type": "choice", "label": "Bar totals",
     "options": ["none", "fraction", "percent"], "default": "none",
     "kinds": sorted(set(_kinds_taking("barnorm")) | {"bar"},
                     key=_KINDS.index),
     "advanced": True},
    {"name": "groupnorm", "type": "choice", "label": "Area totals",
     "options": ["none", "fraction", "percent"], "default": "none",
     "arg": "groupnorm", "advanced": True},
    {"name": "boxmode", "type": "choice", "label": "Series mode",
     "options": ["group", "overlay"], "default": "group", "arg": "boxmode",
     "advanced": True},
    {"name": "violinmode", "type": "choice", "label": "Series mode",
     "options": ["group", "overlay"], "default": "group",
     "arg": "violinmode", "advanced": True},
    {"name": "stripmode", "type": "choice", "label": "Series mode",
     "options": ["group", "overlay"], "default": "group",
     "arg": "stripmode", "advanced": True},
    {"name": "histfunc", "type": "choice", "label": "Summarise with",
     "options": ["count", "sum", "avg", "min", "max"], "default": "count",
     "arg": "histfunc"},
    {"name": "histnorm", "type": "choice", "label": "Normalise",
     "options": ["none", "percent", "probability", "density",
                 "probability density"],
     "default": "none", "arg": "histnorm", "advanced": True},
    {"name": "nbins", "type": "int", "label": "Bins", "default": 0,
     "min": 0, "max": 500, "arg": "nbins"},
    {"name": "nbinsx", "type": "int", "label": "X bins", "default": 0,
     "min": 0, "max": 500, "arg": "nbinsx", "advanced": True},
    {"name": "nbinsy", "type": "int", "label": "Y bins", "default": 0,
     "min": 0, "max": 500, "arg": "nbinsy", "advanced": True},
    {"name": "cumulative", "type": "bool", "label": "Running total",
     "default": False, "arg": "cumulative", "advanced": True},
    {"name": "marginal", "type": "choice", "label": "Marginal plot",
     "options": ["none", "rug", "box", "violin", "histogram"],
     "default": "none", "arg": "marginal", "advanced": True},
    {"name": "marginal_x", "type": "choice", "label": "Marginal (top)",
     "options": ["none", "rug", "box", "violin", "histogram"],
     "default": "none", "arg": "marginal_x", "advanced": True},
    {"name": "marginal_y", "type": "choice", "label": "Marginal (right)",
     "options": ["none", "rug", "box", "violin", "histogram"],
     "default": "none", "arg": "marginal_y", "advanced": True},
    {"name": "trendline", "type": "choice", "label": "Trendline",
     "options": ["none", "ols", "lowess", "rolling", "expanding", "ewm"],
     "default": "none", "arg": "trendline"},
    {"name": "trendline_scope", "type": "choice", "label": "Trendline over",
     "options": ["trace", "overall"], "default": "trace",
     "arg": "trendline_scope", "advanced": True},
    {"name": "trendline_window", "type": "int", "label": "Trendline window",
     "default": 0, "min": 0, "max": 1000, "arg": "trendline_options",
     "advanced": True},
    {"name": "points", "type": "choice", "label": "Points",
     "options": ["outliers", "all", "suspected outliers", "none"],
     "default": "outliers", "arg": "points", "advanced": True},
    {"name": "notched", "type": "bool", "label": "Notched", "default": False,
     "arg": "notched", "advanced": True},
    {"name": "box", "type": "bool", "label": "Box inside", "default": False,
     "arg": "box", "advanced": True},
    {"name": "ecdfnorm", "type": "choice", "label": "ECDF axis",
     "options": ["probability", "percent", "none"], "default": "probability",
     "arg": "ecdfnorm", "advanced": True},
    {"name": "ecdfmode", "type": "choice", "label": "ECDF counts",
     "options": ["standard", "complementary", "reversed"],
     "default": "standard", "arg": "ecdfmode", "advanced": True},
    {"name": "lines", "type": "bool", "label": "Draw the line",
     "default": True, "arg": "lines", "advanced": True},
    {"name": "markers", "type": "bool", "label": "Show markers",
     "default": False, "arg": "markers", "advanced": True},
    {"name": "line_shape", "type": "choice", "label": "Line shape",
     "options": ["auto", "linear", "spline", "hv", "vh", "hvh", "vhv"],
     "default": "auto", "arg": "line_shape", "advanced": True},
    {"name": "line_close", "type": "bool", "label": "Close the loop",
     "default": False, "arg": "line_close", "advanced": True},
    {"name": "hole", "type": "float", "label": "Hole", "default": 0.0,
     "min": 0.0, "max": 0.95, "arg": "hole"},
    {"name": "branchvalues", "type": "choice", "label": "Branch values",
     "options": ["remainder", "total"], "default": "remainder",
     "arg": "branchvalues", "advanced": True},
    {"name": "maxdepth", "type": "int", "label": "Levels shown",
     "default": 0, "min": 0, "max": 12, "arg": "maxdepth",
     "advanced": True},
    {"name": "dimensions_max_cardinality", "type": "int",
     "label": "Max values per dimension", "default": 0, "min": 0,
     "max": 500, "arg": "dimensions_max_cardinality", "advanced": True},
    {"name": "base", "type": "columns", "label": "Bars start at",
     "multi": False, "default": "", "arg": "base", "advanced": True},
    # Not "direction": Chart per Value already has one, for the way its
    # stack fills. A param name has to be unique within a node.
    {"name": "polar_direction", "type": "choice", "label": "Angles run",
     "options": ["counterclockwise", "clockwise"],
     "default": "counterclockwise", "arg": "direction", "advanced": True},
    {"name": "start_angle", "type": "int", "label": "Zero angle at",
     "default": 90, "min": -360, "max": 360, "arg": "start_angle",
     "advanced": True},
    {"name": "render_mode", "type": "choice", "label": "Draw with",
     "options": ["auto", "svg", "webgl"], "default": "auto",
     "arg": "render_mode", "advanced": True},

    # ------------------------------------------------------- the axes
    {"name": "log_x", "type": "bool", "label": "Log X", "default": False,
     "arg": "log_x"},
    {"name": "log_y", "type": "bool", "label": "Log Y", "default": False,
     "arg": "log_y"},
    {"name": "log_z", "type": "bool", "label": "Log Z", "default": False,
     "arg": "log_z", "advanced": True},
    {"name": "log_r", "type": "bool", "label": "Log radius",
     "default": False, "arg": "log_r", "advanced": True},
    # Strings, not floats: blank has to mean "not pinned", and a spin box
    # has no way to say that.
    {"name": "min_y", "type": "string", "label": "Min Y", "default": "",
     "placeholder": "(from the data)", "arg": "range_y"},
    {"name": "max_y", "type": "string", "label": "Max Y", "default": "",
     "placeholder": "(from the data)", "arg": "range_y"},
    {"name": "min_x", "type": "string", "label": "Min X", "default": "",
     "placeholder": "(from the data)", "arg": "range_x", "advanced": True},
    {"name": "max_x", "type": "string", "label": "Max X", "default": "",
     "placeholder": "(from the data)", "arg": "range_x", "advanced": True},
    {"name": "min_z", "type": "string", "label": "Min Z", "default": "",
     "placeholder": "(from the data)", "arg": "range_z", "advanced": True},
    {"name": "max_z", "type": "string", "label": "Max Z", "default": "",
     "placeholder": "(from the data)", "arg": "range_z", "advanced": True},
    {"name": "min_r", "type": "string", "label": "Min radius", "default": "",
     "placeholder": "(from the data)", "arg": "range_r", "advanced": True},
    {"name": "max_r", "type": "string", "label": "Max radius", "default": "",
     "placeholder": "(from the data)", "arg": "range_r", "advanced": True},
    {"name": "min_theta", "type": "string", "label": "Min angle",
     "default": "", "placeholder": "degrees", "arg": "range_theta",
     "advanced": True},
    {"name": "max_theta", "type": "string", "label": "Max angle",
     "default": "", "placeholder": "degrees", "arg": "range_theta",
     "advanced": True},

    # ------------------------------------------------ colour and theme
    {"name": "template", "type": "choice", "label": "Theme",
     "options": list(_TEMPLATES), "default": "default"},
    {"name": "color_sequence", "type": "choice", "label": "Palette",
     "options": ["default", *_COLOR_SEQUENCES], "default": "default",
     "arg": "color_discrete_sequence", "advanced": True},
    {"name": "color_scale", "type": "choice", "label": "Color scale",
     "options": ["default", *_COLOR_SCALES], "default": "default",
     "arg": "color_continuous_scale", "advanced": True},
    {"name": "color_min", "type": "string", "label": "Color scale min",
     "default": "", "placeholder": "(from the data)", "arg": "range_color",
     "advanced": True},
    {"name": "color_max", "type": "string", "label": "Color scale max",
     "default": "", "placeholder": "(from the data)", "arg": "range_color",
     "advanced": True},
    {"name": "color_midpoint", "type": "string", "label": "Color midpoint",
     "default": "", "placeholder": "for a diverging scale",
     "arg": "color_continuous_midpoint", "advanced": True},
    {"name": "opacity", "type": "float", "label": "Opacity", "default": 1.0,
     "min": 0.05, "max": 1.0, "arg": "opacity", "advanced": True},

    # ------------------------------------------------------- the card
    {"name": "title", "type": "string", "label": "Title", "default": ""},
    {"name": "subtitle", "type": "string", "label": "Subtitle",
     "default": "", "advanced": True},
]

#: Rows that feed a px argument, keyed by param name — used by _build().
_ARG_OF: dict[str, str] = {r["name"]: r["arg"] for r in _ROWS if "arg" in r}
_LABEL_OF: dict[str, str] = {r["name"]: r["label"] for r in _ROWS}
_DEFAULT_OF: dict[str, Any] = {r["name"]: r.get("default") for r in _ROWS}
_TYPE_OF: dict[str, str] = {r["name"]: r["type"] for r in _ROWS}
_MULTI: frozenset[str] = frozenset(
    r["name"] for r in _ROWS
    if r["type"] == "columns" and r.get("multi", True))

#: The two-box axis ranges, as param name -> (px argument, which end).
_RANGES: dict[str, tuple[str, int]] = {
    "min_x": ("range_x", 0), "max_x": ("range_x", 1),
    "min_y": ("range_y", 0), "max_y": ("range_y", 1),
    "min_z": ("range_z", 0), "max_z": ("range_z", 1),
    "min_r": ("range_r", 0), "max_r": ("range_r", 1),
    "min_theta": ("range_theta", 0), "max_theta": ("range_theta", 1),
    "color_min": ("range_color", 0), "color_max": ("range_color", 1),
}

#: The two ends of each range, by px argument, so a half-filled pair can
#: be reported by the names on the boxes rather than by the argument.
_RANGE_PAIRS: dict[str, tuple[str, str]] = {}
for _name, (_arg, _end) in _RANGES.items():
    _pair = _RANGE_PAIRS.setdefault(_arg, ["", ""])
    _pair[_end] = _name
_RANGE_PAIRS = {a: tuple(p) for a, p in _RANGE_PAIRS.items()}

#: Which log tick, if any, turns a range into exponents — see `_log_range`.
_RANGE_LOG: dict[str, str] = {
    "range_x": "log_x", "range_y": "log_y",
    "range_z": "log_z", "range_r": "log_r",
}

#: String params holding a number rather than text. Strings because blank
#: has to mean "not set", which no spin box can say.
_NUMERIC_TEXT: frozenset[str] = frozenset({"color_midpoint"})

#: Choice values whose displayed wording isn't what plotly wants. A value
#: of None means "don't pass this argument at all".
_CHOICE_VALUES: dict[str, dict[str, Any]] = {
    "orientation": {"auto": None, "vertical": "v", "horizontal": "h"},
    "render_mode": {"auto": None},
    "barnorm": {"none": None},
    "groupnorm": {"none": None},
    "histnorm": {"none": None},
    "histfunc": {"count": None},
    "marginal": {"none": None},
    "marginal_x": {"none": None},
    "marginal_y": {"none": None},
    "trendline": {"none": None},
    "points": {"suspected outliers": "suspectedoutliers", "none": False},
    "ecdfnorm": {"none": None},
    "line_shape": {"auto": None},
    "color_sequence": {"default": None},
    "color_scale": {"default": None},
}


def _params() -> list[dict[str, Any]]:
    """The PARAMS rows for every Plotly Express setting this node offers.

    Each row comes back with its `visible_when` filled in — the chart
    kinds that accept its argument, ANDed with the "More options" tick for
    an advanced row — and with this module's private keys removed.
    """
    out = []
    for row in _ROWS:
        spec = {k: v for k, v in row.items()
                if k not in ("arg", "kinds", "advanced")}
        when: dict[str, list[str]] = {}
        kinds = row.get("kinds")
        if kinds is None and "arg" in row:
            kinds = _kinds_taking(row["arg"])
        if kinds is not None and len(kinds) < len(_KINDS):
            # A row every kind takes needs no gate; one no kind takes would
            # be a typo in an argument name, and is caught by the test that
            # checks this table against plotly itself.
            when["kind"] = list(kinds)
        if row.get("advanced"):
            when["more"] = ["True"]
        if when:
            spec["visible_when"] = when
        out.append(spec)
    return out


def _column_list(value: Any) -> list[str]:
    """A comma-separated columns param as a list, blanks dropped."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [c.strip() for c in str(value).split(",") if c.strip()]


#: Multi-column params that must collapse to a bare name when only one
#: column is picked. A one-item list puts plotly into "wide" mode, where
#: the frame's own columns are the series — which fights every other role
#: column on the chart, so `px.scatter_3d(y=["revenue"], z="lat")` is
#: rejected outright. `path`, `dimensions` and `hover_data` are genuinely
#: lists to plotly and stay lists however few they hold.
_COLLAPSE_SINGLE: frozenset[str] = frozenset({"y"})


def _column_value(name: str, raw: Any) -> Any:
    """One columns param as plotly wants it: a list, a name, or None."""
    picked = _column_list(raw)
    if not picked:
        return None
    if name in _MULTI and not (name in _COLLAPSE_SINGLE and len(picked) == 1):
        return picked
    return picked[0]


def _default_columns(table, values: dict[str, Any],
                     exclude: Iterable[str] = ()) -> list[str]:
    """The numeric columns to plot when the user named none.

    Anything already spoken for — the x axis, the colour, the facets — is
    left out, since plotting a column against itself is never what was
    meant.
    """
    spoken_for = set(exclude)
    for name in _ARG_OF:
        if _TYPE_OF.get(name) == "columns":
            spoken_for.update(_column_list(values.get(name)))
    return [c for c in table.select_dtypes("number").columns
            if c not in spoken_for]


def _as_bound(value: Any) -> Optional[float]:
    """A manual axis bound as a float, or None when it isn't one.

    A copy of `core.chart_scale.as_bound` rather than an import of it, to
    keep this node self-contained — see the note above `_figure_lock`.
    Unreadable is the same as blank on purpose: half-typed text in an axis
    box should leave the chart alone, not fail the run.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build(values: dict[str, Any], table, px,
          exclude: Iterable[str] = ()) -> tuple[dict[str, Any], list[str]]:
    """Keyword arguments for `px.<kind>(table, **kwargs)`.

    `px` is `plotly.express`, passed in rather than imported, so this
    function stays out of the way until `run()` actually needs plotly. It
    is used only to resolve a named colour palette, which plotly takes as
    a list of colours rather than by name.

    Returns the kwargs and the labels of any settings the chosen chart
    kind has no use for, so the node can say so in its log rather than
    silently ignoring them — switching kind on a chart that was set up as
    something else is the normal way to end up here.

    `exclude` names columns the node has claimed for its own purposes, so
    that "plot every numeric column" doesn't pick them up.

    Raises ValueError if a named column isn't in the table, or if the
    chart needs a column that hasn't been given.
    """
    kind = str(values.get("kind") or "line")
    if kind not in _KIND_ARGS:
        raise ValueError(f"unknown chart kind {kind!r}")
    accepted = _KIND_ARGS[kind] | _UNIVERSAL_ARGS

    columns = set(table.columns)
    kwargs: dict[str, Any] = {}
    ignored: list[str] = []
    ranges: dict[str, list[Optional[float]]] = {}

    for name, arg in _ARG_OF.items():
        raw = values.get(name, _DEFAULT_OF[name])
        ptype = _TYPE_OF[name]
        untouched = raw == _DEFAULT_OF[name]

        # what the user actually asked for, in plotly's own vocabulary
        if name in _RANGES or name in _NUMERIC_TEXT:
            value = _as_bound(raw)
        elif ptype == "columns":
            value = _column_value(name, raw)
        elif ptype == "choice":
            value = _CHOICE_VALUES.get(name, {}).get(raw, raw)
        elif ptype == "bool":
            value = bool(raw)
        elif ptype in ("int", "float"):
            value = _number(raw, _DEFAULT_OF[name])
        else:
            value = str(raw).strip() or None
        if value is None:
            continue
        # A number or a tick left where it was says nothing: passing it
        # would override a px default that may not be the same value. The
        # value is what counts, not the box: an unreadable number has
        # already fallen back to the default and is equally silent.
        if ptype in ("bool", "int", "float") and value == _DEFAULT_OF[name]:
            continue

        if arg not in accepted:
            # Only a setting somebody actually changed is worth reporting.
            # A chart kind sees dozens of arguments it has no use for and
            # saying so for every one of them would bury the one that
            # matters.
            if not untouched:
                ignored.append(_LABEL_OF[name])
            continue

        if name in _RANGES:
            arg, end = _RANGES[name]
            ranges.setdefault(arg, [None, None])[end] = value
        elif name == "labels":
            kwargs["labels"] = _mapping(value)
        elif name == "trendline_window":
            kwargs["trendline_options"] = {"window": int(value)}
        elif name == "color_sequence":
            kwargs["color_discrete_sequence"] = getattr(
                px.colors.qualitative, str(value))
        else:
            kwargs[arg] = value

    # A half-given range is no range: plotly wants both ends, and there is
    # nothing sensible to put in the other one — an axis pinned at the
    # bottom and free at the top is a thing to want, but not a thing to
    # ask plotly for.
    for arg, (low, high) in ranges.items():
        if low is not None and high is not None:
            kwargs[arg] = _log_range([low, high], arg, values)
        elif arg in accepted:
            lo_name, hi_name = _RANGE_PAIRS[arg]
            given, absent = ((lo_name, hi_name) if low is not None
                             else (hi_name, lo_name))
            ignored.append(f"{_LABEL_OF[given]} without "
                           f"{_LABEL_OF[absent]}")

    _fill_defaults(kwargs, values, table, kind, accepted, exclude)
    _check_columns(kwargs, columns, kind)
    # Every px function takes these, so they are outside the per-kind
    # table and never reported as ignored.
    if values.get("title"):
        kwargs["title"] = values["title"]
    if values.get("subtitle"):
        kwargs["subtitle"] = values["subtitle"]
    template = values.get("template", "default")
    if template and template != "default":
        kwargs["template"] = template
    return kwargs, sorted(set(ignored))


def _log_range(bounds: list[float], arg: str,
               values: dict[str, Any]) -> list[float]:
    """A pinned range as plotly wants it for that axis.

    A log axis takes its range in *exponents* — `[0, 3]` means 1 to 1000 —
    which is not what anyone types into a box labelled "Max Y". The bounds
    are converted when the matching log tick is on, so the numbers in the
    boxes always mean the numbers on the axis.

    Zero and negatives have no logarithm, and plotly fails deep inside
    itself on them (a bare "math domain error"), so they are refused here
    by the name of the box that holds them.
    """
    import math

    log_param = _RANGE_LOG.get(arg)
    if not log_param or not values.get(log_param):
        return bounds
    out = []
    for bound, name in zip(bounds, _RANGE_PAIRS[arg]):
        if bound <= 0:
            raise ValueError(
                f"{_LABEL_OF[name]} is {bound:g}, which a log axis has no "
                f"room for — pin it above zero or turn "
                f"{_LABEL_OF[log_param]} off")
        out.append(math.log10(bound))
    return out


def _number(raw: Any, default: Any) -> Any:
    """A spin box value as a number, or the default if it is not one.

    Params come back from a saved file, which is only as well-formed as
    the last thing that wrote it; a chart should not fail to draw over an
    unreadable bin count.
    """
    try:
        return type(default)(raw)
    except (TypeError, ValueError):
        return default


def _mapping(text: str) -> dict[str, str]:
    """`column = Label` lines as a dict. Blank and # lines are skipped."""
    out = {}
    for line in str(text).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, label = line.partition("=")
        out[key.strip()] = label.strip()
    return out


def _fill_defaults(kwargs, values, table, kind, accepted,
                   exclude=()) -> None:
    """Plot every numeric column when the user named none.

    Which axis gets them depends on the chart: a distribution chart with
    nothing chosen is a distribution *of* those columns, so they go on x;
    everything else plots them against whatever x is, so they go on y. A
    chart that names its columns some other way — a pie's values, a
    treemap's hierarchy — is left alone and will say what it is missing.
    """
    if "dimensions" in accepted and "dimensions" not in kwargs:
        # parallel_categories plots categories, not magnitudes, so every
        # column is a candidate there; the other two are numeric.
        picked = ([c for c in table.columns if c not in set(exclude)]
                  if kind == "parallel_categories"
                  else _default_columns(table, values, exclude))
        if picked:
            kwargs["dimensions"] = picked
        return
    if kind in _DISTRIBUTION_KINDS:
        if "x" in kwargs or "y" in kwargs:
            return
        axis = "x"
    else:
        if "y" in kwargs or "y" not in accepted:
            return
        axis = "y"
    picked = _default_columns(table, values, exclude)
    if not picked:
        raise ValueError("no numeric columns to plot — choose the columns "
                         "to chart, or feed this node a table with numbers "
                         "in it")
    kwargs[axis] = picked if len(picked) > 1 else picked[0]


def _check_columns(kwargs, columns, kind) -> None:
    """Every column named must exist, and the chart's own columns must be
    named at all — px would otherwise draw an empty figure or raise from
    inside itself, neither of which says which box to fix."""
    missing = []
    for arg, value in kwargs.items():
        if arg not in _ROLE_ARGS and arg not in _COLUMN_ARGS:
            continue
        for name in (value if isinstance(value, list) else [value]):
            if isinstance(name, str) and name not in columns:
                missing.append(name)
    if missing:
        raise ValueError(f"columns not in table: {sorted(set(missing))}")
    needed = _REQUIRED_ARGS.get(kind, ())
    absent = [a for a in needed if a not in kwargs]
    if absent:
        raise ValueError(
            f"a {kind} chart needs {' and '.join(absent)} — "
            f"set {' and '.join(_ROLE_LABELS.get(a, a) for a in absent)}")


#: Arguments other than the role columns whose value is a column name, so
#: a typo in one is caught here rather than inside plotly.
_COLUMN_ARGS: frozenset[str] = frozenset({
    "color", "size", "symbol", "line_dash", "pattern_shape", "line_group",
    "text", "hover_name", "hover_data", "facet_row", "facet_col",
    "animation_frame", "animation_group", "error_x", "error_x_minus",
    "error_y", "error_y_minus", "error_z", "base",
})

#: What a kind cannot be drawn without. Everything else px can work out or
#: do without, so this is deliberately short.
_REQUIRED_ARGS: dict[str, tuple[str, ...]] = {
    "timeline": ("x_start", "x_end", "y"),
    "pie": ("names",),
    "funnel_area": ("names",),
    "sunburst": ("path",),
    "treemap": ("path",),
    "icicle": ("path",),
    "scatter_polar": ("r", "theta"),
    "line_polar": ("r", "theta"),
    "bar_polar": ("r", "theta"),
    "scatter_ternary": ("a", "b", "c"),
    "line_ternary": ("a", "b", "c"),
    "scatter_3d": ("x", "y", "z"),
    "line_3d": ("x", "y", "z"),
}

_ROLE_LABELS: dict[str, str] = {r["arg"]: r["label"] for r in _ROWS
                                if r.get("arg") in _ROLE_ARGS}


def _layout_updates(values: dict[str, Any], kind: str) -> dict[str, Any]:
    """Figure-layout settings that aren't px arguments for this kind.

    One case, kept general because it is the sort of gap that reappears:
    every bar chart plotly draws can be normalised to fractions or
    percentages, but `px.bar` alone has no `barnorm` argument. The layout
    attribute of that name does the same job, so the setting is offered
    for bar charts too and applied here.
    """
    out: dict[str, Any] = {}
    barnorm = values.get("barnorm", "none")
    if barnorm != "none" and "barnorm" not in _KIND_ARGS.get(kind, ()):
        out["barnorm"] = barnorm
    return out


def _figure_lock():
    """The process-wide lock that serialises Plotly figure building.

    Building a figure is not thread-safe and node bodies share the
    process, so every node that builds one has to take the *same* lock —
    see `core.plotly_spec.FIGURE_LOCK` for what goes wrong otherwise.

    Prefers flograph's own, so this node queues behind the other built-in
    chart nodes rather than beside them. Falls back to one parked in
    `sys.modules` when there isn't one, which is what makes this file
    droppable into an older flograph: node scripts are executed in
    separate namespaces and so cannot share a module-level lock, but they
    do share `sys.modules`. `setdefault` is atomic, so two nodes racing to
    create the fallback still end up holding the same lock.
    """
    try:
        from flograph.core.plotly_spec import FIGURE_LOCK
        return FIGURE_LOCK
    except ImportError:
        import sys
        import threading
        import types

        name = "_flograph_plotly_figure_lock"
        module = sys.modules.get(name)
        if module is None:
            candidate = types.ModuleType(name)
            candidate.lock = threading.Lock()
            module = sys.modules.setdefault(name, candidate)
        return module.lock


PARAMS = [
    *_params(),
    {"name": "width", "type": "int", "label": "Width",
     "default": 420, "min": 260, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 320, "min": 200, "max": 2000, "cosmetic": True},
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
    kwargs, ignored = _build(ctx.params, table, px)
    try:
        # Building a figure is not thread-safe — see _figure_lock.
        with _figure_lock():
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
    layout = _layout_updates(ctx.params, kind)
    if layout:
        fig.update_layout(**layout)

    ctx.log(f"plotted {len(fig.data)} trace(s) ({kind})")
    if ignored:
        ctx.log(f"a {kind} chart has no use for: {', '.join(ignored)}")
    return {"figure": fig}
