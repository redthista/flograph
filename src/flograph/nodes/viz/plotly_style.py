"""Plotly Style

Restyles a Plotly figure without touching what it plots. Wire any node
that makes one into it — Show Plotly, Chart per Value (Plotly), Gantt
Chart, a Python Script that builds its own — and set the theme, the legend,
the axis titles and formats, the gridlines, a reference line, a note in the
corner. The figure comes out the other side ready for a card, a dashboard
tile or a report.

The split is deliberate: **Show Plotly decides what the chart shows, this
decides how it looks.** Everything here is figure *layout*, which is why it
works on a figure from any source rather than only on charts flograph drew,
and why the same styling can be pointed at several charts by wiring one
Style node per chart from a shared setup — or dropped in later, without
disturbing a chart that already works.

Every setting has a **keep** or blank position, which is the default and
means "leave whatever the figure already had". A Style node changes only
the things you actually set, so putting one in front of a Gantt chart or a
carefully built script figure is safe.

**Theme** and **Palette** restyle the whole figure. **Legend** shows,
hides or repositions it; the inside positions float it over the plot,
which buys back the width a right-hand legend costs.

**Axis titles** replace whatever the columns were called. **Tick format**
takes a d3 format string for numbers (`,.0f` for thousands separators,
`.1%` for percentages, `$,.2f` for money) or a date format for dates
(`%b %Y`). **Sort categories** reorders a categorical axis — "total
descending" is the one that turns an unordered bar chart into a ranking.

**Reference line** draws a horizontal or vertical line at a value — a
target, a budget, a threshold — with an optional label on it. **Note**
puts text in a corner of the chart.

A list of figures is styled one by one and comes out as a list, so a Chart
per Value stack can be restyled in one node.

The input figure is never modified: the node styles a copy, because the
upstream node's output is cached and shared with anything else wired to
it.

Needs the optional 'plotly' extra; install it from Tools > Manage Packages
if it is missing.
"""
NODE = {
    "label": "Plotly Style",
    "category": "Viz",
    "card": "webview",
    "inputs": [("figure", "any")],
    "outputs": [("figure", "any")],
}

# Every choice has a "keep" and every box a blank, both meaning "leave the
# figure as it is". That is what lets this node be dropped in front of a
# figure somebody else built without quietly flattening it.
_KEEP = "keep"

PARAMS = [
    {"name": "more", "type": "bool", "label": "More options",
     "default": False, "cosmetic": True},

    {"name": "template", "type": "choice", "label": "Theme",
     "options": [_KEEP, "plotly", "plotly_white", "plotly_dark", "ggplot2",
                 "seaborn", "simple_white", "presentation", "none"],
     "default": _KEEP},
    {"name": "colorway", "type": "choice", "label": "Palette",
     "options": [_KEEP, "Plotly", "D3", "G10", "T10", "Set1", "Set2",
                 "Set3", "Dark2", "Pastel1", "Pastel2", "Antique", "Bold",
                 "Pastel", "Prism", "Safe", "Vivid", "Alphabet", "Dark24",
                 "Light24"],
     "default": _KEEP},

    {"name": "title", "type": "string", "label": "Title", "default": "",
     "placeholder": "(keep)"},
    {"name": "subtitle", "type": "string", "label": "Subtitle",
     "default": "", "placeholder": "(keep)"},
    {"name": "title_align", "type": "choice", "label": "Title position",
     "options": [_KEEP, "left", "center", "right"], "default": _KEEP,
     "visible_when": {"more": ["True"]}},

    {"name": "x_title", "type": "string", "label": "X axis title",
     "default": "", "placeholder": "(keep)"},
    {"name": "y_title", "type": "string", "label": "Y axis title",
     "default": "", "placeholder": "(keep)"},
    {"name": "legend_title", "type": "string", "label": "Legend title",
     "default": "", "placeholder": "(keep)"},
    {"name": "colorbar_title", "type": "string", "label": "Color bar title",
     "default": "", "placeholder": "(keep)",
     "visible_when": {"more": ["True"]}},

    {"name": "legend", "type": "choice", "label": "Legend",
     "options": [_KEEP, "show", "hide"], "default": _KEEP},
    {"name": "legend_pos", "type": "choice", "label": "Legend position",
     "options": [_KEEP, "right", "top", "bottom", "inside top left",
                 "inside top right", "inside bottom left",
                 "inside bottom right"],
     "default": _KEEP},

    {"name": "hovermode", "type": "choice", "label": "Hover",
     "options": [_KEEP, "closest", "x", "y", "x unified", "y unified",
                 "off"],
     "default": _KEEP},

    {"name": "log_x", "type": "choice", "label": "Log X",
     "options": [_KEEP, "on", "off"], "default": _KEEP},
    {"name": "log_y", "type": "choice", "label": "Log Y",
     "options": [_KEEP, "on", "off"], "default": _KEEP},
    {"name": "min_x", "type": "string", "label": "Min X", "default": "",
     "placeholder": "(keep)", "visible_when": {"more": ["True"]}},
    {"name": "max_x", "type": "string", "label": "Max X", "default": "",
     "placeholder": "(keep)", "visible_when": {"more": ["True"]}},
    {"name": "min_y", "type": "string", "label": "Min Y", "default": "",
     "placeholder": "(keep)"},
    {"name": "max_y", "type": "string", "label": "Max Y", "default": "",
     "placeholder": "(keep)"},

    {"name": "grid_x", "type": "choice", "label": "X gridlines",
     "options": [_KEEP, "on", "off"], "default": _KEEP},
    {"name": "grid_y", "type": "choice", "label": "Y gridlines",
     "options": [_KEEP, "on", "off"], "default": _KEEP},
    {"name": "x_format", "type": "string", "label": "X tick format",
     "default": "", "placeholder": ",.0f  or  %b %Y",
     "visible_when": {"more": ["True"]}},
    {"name": "y_format", "type": "string", "label": "Y tick format",
     "default": "", "placeholder": ",.0f  or  .1%",
     "visible_when": {"more": ["True"]}},
    {"name": "tick_angle", "type": "string", "label": "X tick angle",
     "default": "", "placeholder": "degrees, e.g. -45",
     "visible_when": {"more": ["True"]}},
    {"name": "category_order", "type": "choice", "label": "Sort categories",
     "options": [_KEEP, "as plotted", "category ascending",
                 "category descending", "total ascending",
                 "total descending"],
     "default": _KEEP},
    {"name": "range_slider", "type": "bool", "label": "Range slider",
     "default": False, "visible_when": {"more": ["True"]}},

    {"name": "line_at", "type": "string", "label": "Reference line",
     "default": "", "placeholder": "a value, e.g. 0 or 100"},
    {"name": "line_axis", "type": "choice", "label": "Reference line on",
     "options": ["y", "x"], "default": "y"},
    {"name": "line_label", "type": "string", "label": "Reference label",
     "default": "", "placeholder": "e.g. Target"},
    {"name": "line_color", "type": "string", "label": "Reference color",
     "default": "", "placeholder": "e.g. crimson or #b00",
     "visible_when": {"more": ["True"]}},
    {"name": "line_dash", "type": "choice", "label": "Reference style",
     "options": ["dash", "solid", "dot", "dashdot"], "default": "dash",
     "visible_when": {"more": ["True"]}},

    {"name": "note", "type": "text", "label": "Note", "default": "",
     "placeholder": "text to place on the chart"},
    {"name": "note_pos", "type": "choice", "label": "Note position",
     "options": ["top left", "top right", "bottom left", "bottom right"],
     "default": "top left"},

    {"name": "font_family", "type": "string", "label": "Font",
     "default": "", "placeholder": "(keep)",
     "visible_when": {"more": ["True"]}},
    {"name": "font_size", "type": "int", "label": "Font size", "default": 0,
     "min": 0, "max": 48, "visible_when": {"more": ["True"]}},
    {"name": "font_color", "type": "string", "label": "Text color",
     "default": "", "placeholder": "(keep)",
     "visible_when": {"more": ["True"]}},
    {"name": "plot_color", "type": "string", "label": "Plot background",
     "default": "", "placeholder": "(keep)",
     "visible_when": {"more": ["True"]}},
    {"name": "paper_color", "type": "string", "label": "Card background",
     "default": "", "placeholder": "(keep)",
     "visible_when": {"more": ["True"]}},
    {"name": "margin", "type": "string", "label": "Margins", "default": "",
     "placeholder": "left,right,top,bottom in pixels",
     "visible_when": {"more": ["True"]}},

    {"name": "width", "type": "int", "label": "Width",
     "default": 460, "min": 260, "max": 1600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 340, "min": 200, "max": 2000},
    # Cosmetic: the zoom is the embedded browser's own, applied to the
    # figure this node already produced.
    {"name": "scale", "type": "int", "label": "Scale %",
     "default": 100, "min": 25, "max": 400, "cosmetic": True},
]

#: Where a legend sits, as the plotly anchoring that puts it there. The
#: inside positions float it over the plot area, which is worth doing on a
#: narrow card: a right-hand legend can take a third of the width.
_LEGEND_POS = {
    "right": {"orientation": "v", "yanchor": "auto", "y": 1,
              "xanchor": "left", "x": 1.02},
    "top": {"orientation": "h", "yanchor": "bottom", "y": 1.02,
            "xanchor": "right", "x": 1},
    "bottom": {"orientation": "h", "yanchor": "top", "y": -0.2,
               "xanchor": "center", "x": 0.5},
    "inside top left": {"orientation": "v", "yanchor": "top", "y": 0.98,
                        "xanchor": "left", "x": 0.02},
    "inside top right": {"orientation": "v", "yanchor": "top", "y": 0.98,
                         "xanchor": "right", "x": 0.98},
    "inside bottom left": {"orientation": "v", "yanchor": "bottom",
                           "y": 0.02, "xanchor": "left", "x": 0.02},
    "inside bottom right": {"orientation": "v", "yanchor": "bottom",
                            "y": 0.02, "xanchor": "right", "x": 0.98},
}

_NOTE_POS = {
    "top left": (0.01, 0.99, "left", "top"),
    "top right": (0.99, 0.99, "right", "top"),
    "bottom left": (0.01, 0.01, "left", "bottom"),
    "bottom right": (0.99, 0.01, "right", "bottom"),
}


def run(ctx, figure):
    import importlib.util

    if importlib.util.find_spec("plotly") is None:
        raise RuntimeError(
            "Plotly Style requires the optional plotly extra. Install it "
            "with `pip install flograph[plotly]` or "
            "Tools > Manage Packages > plotly.")

    if figure is None:
        raise ValueError("nothing on the figure input — wire a node that "
                         "produces a Plotly figure into it")

    # A list in, a list out: a Chart per Value stack is styled in one go
    # and stays a stack.
    if isinstance(figure, (list, tuple)):
        if not figure:
            return {"figure": []}
        styled = []
        for index, one in enumerate(figure):
            ctx.check_cancelled()
            ctx.progress(index / len(figure))
            styled.append(_style(ctx, one))
        ctx.log(f"styled {len(styled)} figures")
        return {"figure": styled}

    styled = _style(ctx, figure)
    ctx.log("styled 1 figure")
    return {"figure": styled}


def _style(ctx, figure):
    """One figure, restyled onto a copy of itself."""
    import plotly.graph_objects as go

    if not hasattr(figure, "update_layout"):
        raise TypeError(
            f"the figure input holds a {type(figure).__name__}, not a "
            f"Plotly figure — wire this node to Show Plotly, Chart per "
            f"Value (Plotly), Gantt Chart or a script that makes one")

    # Nodes treat inputs as read-only: the upstream node's output is
    # cached and may be wired to several nodes at once, so styling the
    # figure in place would restyle somebody else's chart too.
    fig = go.Figure(figure)
    params = ctx.params

    layout = {}
    _theme(params, layout)
    _titles(params, layout)
    _legend(params, layout)
    _fonts(params, layout)
    if params.get("hovermode", "keep") != "keep":
        mode = params["hovermode"]
        layout["hovermode"] = False if mode == "off" else mode
    if layout:
        fig.update_layout(**layout)

    _axes(params, fig)
    _reference_line(params, fig)
    _note(params, fig)
    if params.get("colorbar_title"):
        fig.update_coloraxes(colorbar_title_text=params["colorbar_title"])
    return fig


def _theme(params, layout) -> None:
    import plotly.express as px

    if params.get("template", "keep") != "keep":
        layout["template"] = params["template"]
    colorway = params.get("colorway", "keep")
    if colorway != "keep":
        layout["colorway"] = getattr(px.colors.qualitative, colorway)


def _titles(params, layout) -> None:
    if params.get("title"):
        layout["title_text"] = params["title"]
    if params.get("subtitle"):
        layout["title_subtitle_text"] = params["subtitle"]
    align = params.get("title_align", "keep")
    if align != "keep":
        layout["title_x"] = {"left": 0.0, "center": 0.5, "right": 1.0}[align]
        layout["title_xanchor"] = align
    if params.get("legend_title"):
        layout["legend_title_text"] = params["legend_title"]


def _legend(params, layout) -> None:
    legend = params.get("legend", "keep")
    if legend != "keep":
        layout["showlegend"] = legend == "show"
    position = params.get("legend_pos", "keep")
    if position != "keep":
        layout["legend"] = dict(_LEGEND_POS[position])


def _fonts(params, layout) -> None:
    font = {}
    if params.get("font_family"):
        font["family"] = params["font_family"]
    if int(params.get("font_size") or 0):
        font["size"] = int(params["font_size"])
    if params.get("font_color"):
        font["color"] = params["font_color"]
    if font:
        layout["font"] = font
    if params.get("plot_color"):
        layout["plot_bgcolor"] = params["plot_color"]
    if params.get("paper_color"):
        layout["paper_bgcolor"] = params["paper_color"]
    margin = _numbers(params.get("margin"))
    if len(margin) == 4:
        left, right, top, bottom = margin
        layout["margin"] = {"l": left, "r": right, "t": top, "b": bottom}


def _axes(params, fig) -> None:
    """Both axes, in one pass each.

    `update_xaxes` walks every x axis the figure has, so this styles a
    faceted chart's whole grid rather than only its first panel, and does
    nothing at all on a figure with no cartesian axes — a pie or a
    treemap — rather than failing on one.
    """
    from flograph.core.chart_scale import as_bound

    for axis, update in (("x", fig.update_xaxes), ("y", fig.update_yaxes)):
        settings = {}
        log = params.get(f"log_{axis}", "keep")
        if log != "keep":
            settings["type"] = "log" if log == "on" else "linear"
        low = as_bound(params.get(f"min_{axis}"))
        high = as_bound(params.get(f"max_{axis}"))
        if low is not None and high is not None:
            # A log axis takes exponents; the boxes take the numbers you
            # want to read off the axis, as they do on Show Plotly.
            if settings.get("type") == "log" and low > 0 and high > 0:
                import math
                low, high = math.log10(low), math.log10(high)
            settings["range"] = [low, high]
        title = params.get(f"{axis}_title")
        if title:
            settings["title_text"] = title
        grid = params.get(f"grid_{axis}", "keep")
        if grid != "keep":
            settings["showgrid"] = grid == "on"
        fmt = params.get(f"{axis}_format")
        if fmt:
            settings["tickformat"] = fmt
        if settings:
            update(**settings)

    angle = as_bound(params.get("tick_angle"))
    if angle is not None:
        fig.update_xaxes(tickangle=angle)
    order = params.get("category_order", "keep")
    if order != "keep":
        fig.update_xaxes(
            categoryorder="trace" if order == "as plotted" else order)
    if params.get("range_slider"):
        fig.update_xaxes(rangeslider_visible=True)


def _reference_line(params, fig) -> None:
    from flograph.core.chart_scale import as_bound

    at = as_bound(params.get("line_at"))
    if at is None:
        return
    line = {"line_dash": params.get("line_dash", "dash")}
    if params.get("line_color"):
        line["line_color"] = params["line_color"]
    if params.get("line_label"):
        line["annotation_text"] = params["line_label"]
    if params.get("line_axis", "y") == "y":
        fig.add_hline(y=at, **line)
    else:
        fig.add_vline(x=at, **line)


def _note(params, fig) -> None:
    text = str(params.get("note") or "").strip()
    if not text:
        return
    x, y, xanchor, yanchor = _NOTE_POS[params.get("note_pos", "top left")]
    fig.add_annotation(text=text.replace("\n", "<br>"), showarrow=False,
                       xref="paper", yref="paper", x=x, y=y,
                       xanchor=xanchor, yanchor=yanchor, align="left")


def _numbers(text) -> list[float]:
    """A comma-separated list of numbers, or [] if it isn't one."""
    from flograph.core.chart_scale import as_bound

    parsed = [as_bound(part) for part in str(text or "").split(",")]
    return [] if None in parsed else parsed
