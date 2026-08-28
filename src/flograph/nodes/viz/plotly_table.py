"""Plotly Table

A table drawn *as a Plotly figure* — themed like the charts beside it,
snapshotting into a report or PDF the same way, and sitting on a dashboard
tile as a picture rather than a widget.

This is not the node for looking at data: **Show Table** is, and it is
better at it — a real paged viewer that handles millions of rows, sorts and
scrolls. Use this one when the table has to *match* the charts: same theme,
same fonts, same export path into a report page.

It exists as its own node because Plotly Express has no table function.
Every other chart flograph draws comes from `px.<kind>()` and shares one
generated parameter set (`flograph.core.plotly_spec`); a table is a
`graph_objects` trace with a different shape entirely — headers and columns
rather than x and y — so folding it into the Kind dropdown would have meant
a chart kind that quietly ignored two-thirds of the settings around it.

**Columns** picks and orders what is shown; blank shows the lot as they
arrive. **Max rows** is a guard, not a preference: a table figure carries
every cell it draws into the page, so a million-row frame would build a
document nothing can open. It logs when it trims.

**Number format** takes a d3 format string and applies it to the numeric
columns — `,.0f` for thousands separators, `.1%` for percentages, `$,.2f`
for money. Text columns are left alone.

**Striped** shades alternate rows. **Header fill**, **Header text** and
**Font size** cover the rest; leave them blank to follow the theme.

Needs the optional 'plotly' extra; install it from Tools > Manage Packages
if it is missing.
"""
NODE = {
    "label": "Plotly Table",
    "category": "Viz",
    "card": "webview",
    "inputs": [("table", "dataframe")],
    "outputs": [("figure", "object")],
}
PARAMS = [
    {"name": "columns", "type": "columns", "label": "Columns", "default": "",
     "placeholder": "comma separated; empty = all, in order"},
    {"name": "max_rows", "type": "int", "label": "Max rows", "default": 100,
     "min": 1, "max": 5000},
    {"name": "number_format", "type": "string", "label": "Number format",
     "default": "", "placeholder": ",.0f   .1%   $,.2f"},
    {"name": "align", "type": "choice", "label": "Align",
     "options": ["left", "center", "right"], "default": "left"},
    {"name": "striped", "type": "bool", "label": "Striped rows",
     "default": True},
    {"name": "header_fill", "type": "string", "label": "Header fill",
     "default": "", "placeholder": "(from the theme)"},
    {"name": "header_color", "type": "string", "label": "Header text",
     "default": "", "placeholder": "(from the theme)"},
    {"name": "row_fill", "type": "string", "label": "Row fill",
     "default": "", "placeholder": "(from the theme)"},
    {"name": "font_size", "type": "int", "label": "Font size", "default": 0,
     "min": 0, "max": 32},
    {"name": "row_height", "type": "int", "label": "Row height",
     "default": 0, "min": 0, "max": 120},
    {"name": "template", "type": "choice", "label": "Theme",
     "options": ["default", "plotly", "plotly_white", "plotly_dark",
                 "ggplot2", "seaborn", "simple_white", "presentation",
                 "none"],
     "default": "default"},
    {"name": "title", "type": "string", "label": "Title", "default": ""},
    {"name": "width", "type": "int", "label": "Width",
     "default": 460, "min": 260, "max": 1600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 320, "min": 200, "max": 2000},
    # Cosmetic: the zoom is the embedded browser's own, applied to the
    # figure this node already produced.
    {"name": "scale", "type": "int", "label": "Scale %",
     "default": 100, "min": 25, "max": 400, "cosmetic": True},
]

#: The shade laid over alternate rows when no Row fill is given. Deliberately
#: a translucent white rather than a colour: it lightens a dark theme and
#: darkens nothing, so one value works against every template.
_STRIPE = "rgba(128, 128, 128, 0.12)"


def run(ctx, table):
    import importlib.util

    if importlib.util.find_spec("plotly") is None:
        raise RuntimeError(
            "Plotly Table requires the optional plotly extra. Install it "
            "with `pip install flograph[plotly]` or "
            "Tools > Manage Packages > plotly.")

    import plotly.graph_objects as go

    from flograph.core.plotly_spec import FIGURE_LOCK, column_list

    picked = column_list(ctx.params.get("columns"))
    if picked:
        missing = [c for c in picked if c not in table.columns]
        if missing:
            raise ValueError(f"columns not in table: {missing}")
    else:
        picked = list(table.columns)
    if not picked:
        raise ValueError("nothing to show — the input table has no columns")

    limit = int(ctx.params.get("max_rows", 100))
    shown = table.head(limit)
    if len(table) > limit:
        ctx.log(f"{len(table)} rows — showing the first {limit}. Raise "
                f"'Max rows', or filter or aggregate upstream.")

    header = {"values": [f"<b>{c}</b>" for c in picked],
              "align": ctx.params.get("align", "left")}
    if ctx.params.get("header_fill"):
        header["fill_color"] = ctx.params["header_fill"]
    if ctx.params.get("header_color"):
        header["font"] = {"color": ctx.params["header_color"]}

    cells = {"values": [shown[c].tolist() for c in picked],
             "align": ctx.params.get("align", "left")}
    fill = _row_fill(ctx.params, len(shown), len(picked))
    if fill is not None:
        cells["fill_color"] = fill
    # A d3 format is per column and means nothing to a column of words, so
    # the numeric ones get it and the rest get an empty format, which
    # plotly reads as "leave it alone".
    fmt = str(ctx.params.get("number_format") or "").strip()
    if fmt:
        numeric = set(shown.select_dtypes("number").columns)
        cells["format"] = [fmt if c in numeric else "" for c in picked]
    if int(ctx.params.get("row_height") or 0):
        cells["height"] = int(ctx.params["row_height"])

    layout = {"margin": {"t": 40 if ctx.params.get("title") else 10,
                         "b": 10, "l": 10, "r": 10}}
    if ctx.params.get("title"):
        layout["title_text"] = ctx.params["title"]
    template = ctx.params.get("template", "default")
    if template and template != "default":
        layout["template"] = template
    if int(ctx.params.get("font_size") or 0):
        layout["font"] = {"size": int(ctx.params["font_size"])}

    # Building a figure, and stamping a theme onto one, are not
    # thread-safe — see plotly_spec.FIGURE_LOCK.
    with FIGURE_LOCK:
        figure = go.Figure(go.Table(header=header, cells=cells))
        figure.update_layout(**layout)

    ctx.log(f"{len(shown)} row(s) x {len(picked)} column(s)")
    return {"figure": figure}


def _row_fill(params, rows, columns):
    """What to paint behind the cells, or None to leave it to the theme.

    Plotly wants one entry per *column*, each either a colour or a list of
    colours down the rows — so striping means building the row pattern once
    and handing the same list to every column.
    """
    plain = str(params.get("row_fill") or "").strip()
    if not params.get("striped", True):
        return [plain] * columns if plain else None
    base = plain or "rgba(0, 0, 0, 0)"
    pattern = [base if index % 2 == 0 else _STRIPE for index in range(rows)]
    return [pattern] * columns
