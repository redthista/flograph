"""Waffle

A hundred squares, shared out between your categories in proportion — the
chart for **"what is this made of?"** when the answer has to be countable.

It is the honest version of a pie chart. A pie asks the eye to compare
angles, which it is bad at; a waffle asks it to count squares, which it is
good at, and 38 squares out of 100 reads as 38% without a label. Ten
categories in a pie is a mess of slivers. Ten in a waffle is ten colours,
and the ones too small to matter are visibly too small to matter.

Set **Squares** to 100 and each one is a percent. Set it to the number of
things you actually have — 30 beds, 24 vans, 52 weeks — and each square is
one of them, which is where it stops being a chart and becomes a picture of
the thing itself. Swap the shape for a **circle** and it is a dot plot; give
it an **icon** and it is a pictogram, one little figure per hundred staff.

Nothing is downloaded and nothing is drawn by a script: Python works out
every square and writes the SVG, so it looks the same on the card, in a
dashboard tile, printed into a report, and in a browser with the app closed.

**Click a square** — or a key in the legend — to filter: that category goes
to **selected**, and **table** is your rows cut down to it.

Colours, type and corner radius come from a **Visual Style** node on the
`style` input, so a whole page of visuals can be re-themed from one place.
"""
NODE = {
    "label": "Waffle",
    "category": "Viz",
    "version": "1.0",
    "card": "webview",
    "interactive": True,
    "inputs": [("table", "dataframe"),
               ("style", "object", {"optional": True})],
    "outputs": [("html", "string"), ("table", "dataframe"),
                ("selected", "any"), ("style", "object")],
}

_SHAPES = ("square", "rounded", "circle", "icon")

PARAMS = [
    {"name": "more", "type": "bool", "label": "More options",
     "default": False, "cosmetic": True},

    {"name": "label_column", "type": "columns", "label": "Category",
     "multi": False, "default": "",
     "placeholder": "(the first text column)"},
    {"name": "value_column", "type": "columns", "label": "Value",
     "multi": False, "default": "",
     "placeholder": "(the first number column — or blank to count rows)"},
    {"name": "cells", "type": "int", "label": "Squares", "default": 100,
     "min": 4, "max": 2000},
    {"name": "across", "type": "int", "label": "Squares across",
     "default": 10, "min": 1, "max": 100},
    {"name": "shape", "type": "choice", "label": "Shape",
     "options": list(_SHAPES), "default": "rounded"},

    {"name": "title", "type": "string", "label": "Title", "default": "",
     "placeholder": "heading across the top"},
    {"name": "subtitle", "type": "string", "label": "Subtitle",
     "default": "", "placeholder": "a line under the heading"},
    {"name": "on_click", "type": "choice", "label": "On click",
     "options": ["nothing", "select one", "select many"],
     "default": "select one"},
    {"name": "selected", "type": "string", "label": "Selected values",
     "default": "", "placeholder": 'written by a click, e.g. ["North"]'},

    {"name": "icon", "type": "string", "label": "Icon",
     "default": "●", "placeholder": "any character: ● ★ ▲ or an emoji",
     "visible_when": {"shape": ["icon"]}},
    {"name": "fill_by", "type": "choice", "label": "Fill order",
     "options": ["rows then columns", "columns then rows"],
     "default": "rows then columns", "visible_when": {"more": ["True"]}},
    {"name": "sort", "type": "choice", "label": "Order",
     "options": ["as given", "largest first", "smallest first"],
     "default": "largest first", "visible_when": {"more": ["True"]}},
    {"name": "legend", "type": "bool", "label": "Legend", "default": True,
     "visible_when": {"more": ["True"]}},
    {"name": "value_format", "type": "string", "label": "Value format",
     "default": ",.0f", "placeholder": "$,.0f   .1%   ,.2f",
     "visible_when": {"more": ["True"]}},
    {"name": "legend_shows", "type": "choice", "label": "Legend shows",
     "options": ["share", "value", "squares", "nothing"],
     "default": "share", "visible_when": {"more": ["True"]}},

    {"name": "width", "type": "int", "label": "Width", "default": 420,
     "min": 260, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height", "default": 320,
     "min": 200, "max": 2000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %", "default": 100,
     "min": 25, "max": 400, "cosmetic": True},
]

#: One square's slot in the drawing's own units. The gap is a share of it,
#: so squares stay square whatever the grid.
_STEP = 10.0
_GAP = 1.6


def _pick_columns(rows, params):
    """Which column names the category and which holds the number."""
    from flograph.core.svgplot import to_number

    label = str(params.get("label_column", "") or "").strip()
    value = str(params.get("value_column", "") or "").strip()
    if not rows:
        return label, value

    columns = list(rows[0].keys())
    if label and label not in columns:
        raise ValueError(f"no column called {label!r} — the table has: "
                         + ", ".join(map(str, columns)))
    if value and value not in columns:
        raise ValueError(f"no column called {value!r} — the table has: "
                         + ", ".join(map(str, columns)))

    if not label:
        for column in columns:
            if any(to_number(row.get(column)) is None
                   and row.get(column) is not None for row in rows):
                label = column
                break
        label = label or (columns[0] if columns else "")
    if not value:
        for column in columns:
            if column != label and any(to_number(row.get(column)) is not None
                                       for row in rows):
                value = column
                break
    return label, value


def _totals(rows, label, value):
    """Category totals in first-seen order, adding up duplicate rows.

    Counting rows when there is no value column is deliberate: a waffle of
    "how many of each" is the commonest thing you want from a raw list, and
    making the user add a Group By first to get it would be a poor trade.
    """
    from flograph.core.svgplot import text_of, to_number

    totals: dict[str, float] = {}
    for row in rows:
        name = text_of(row.get(label))
        if not name:
            continue
        if value:
            number = to_number(row.get(value))
            if number is None:
                continue
        else:
            number = 1.0
        totals[name] = totals.get(name, 0.0) + number
    return totals


def _draw(names, counts, colours, params, picked, mode):
    """The squares themselves."""
    from flograph.core import svgplot

    across = max(1, int(params.get("across", 10) or 10))
    shape = str(params.get("shape", "rounded") or "rounded")
    icon = str(params.get("icon", "●") or "●")[:2]
    down_first = str(params.get("fill_by", "")) == "columns then rows"

    order = []
    for name, count in zip(names, counts):
        order.extend([name] * count)
    total = len(order)
    rows_needed = max(1, -(-total // across)) if total else 1

    width = across * _STEP
    height = rows_needed * _STEP
    out = [svgplot.svg_open(width, height)]

    radius = {"square": 0.0, "rounded": _STEP * 0.18,
              "circle": (_STEP - _GAP) / 2.0}.get(shape, 0.0)
    side = _STEP - _GAP
    chosen = set(picked)

    for index, name in enumerate(order):
        if down_first:
            column, row = divmod(index, rows_needed)
        else:
            row, column = divmod(index, across)
        x = column * _STEP + _GAP / 2.0
        y = row * _STEP + _GAP / 2.0
        colour = colours[name]
        if chosen and name not in chosen:
            # Dimmed, not hidden: the shape of what you did not pick is half
            # the information in "how much of the whole is this?".
            colour = svgplot.fade(colour, 0.62)
        klass = f"cell{svgplot.hit_class(mode)}"
        click = svgplot.click_attr(name, mode)

        if shape == "icon":
            out.append(
                f"<text class='{klass}' x='{svgplot.num(x + side / 2)}' "
                f"y='{svgplot.num(y + side / 2)}' fill='{colour}' "
                f"font-size='{svgplot.num(side * 1.15)}' "
                f"text-anchor='middle' dominant-baseline='central'"
                f"{click}>{svgplot.escape(icon)}</text>")
        else:
            out.append(
                f"<rect class='{klass}' x='{svgplot.num(x)}' "
                f"y='{svgplot.num(y)}' width='{svgplot.num(side)}' "
                f"height='{svgplot.num(side)}' rx='{svgplot.num(radius)}' "
                f"fill='{colour}'{click}></rect>")
    out.append("</svg>")
    return "".join(out)


def run(ctx, table, style=None):
    import pandas as pd

    from flograph.core import infographic, svgplot, visual_style
    from flograph.core.controls import selected_values

    params = ctx.params
    rows = infographic.rows_from_frame(table)
    label, value = _pick_columns(rows, params)
    if not label:
        raise ValueError("a waffle needs a Category column — the thing each "
                         "colour stands for")

    totals = _totals(rows, label, value)
    if not totals:
        raise ValueError(
            f"nothing to draw: no rows with a category in {label!r}"
            + (f" and a number in {value!r}" if value else ""))

    order = str(params.get("sort", "largest first") or "as given")
    names = list(totals)
    if order == "largest first":
        names.sort(key=lambda n: -totals[n])
    elif order == "smallest first":
        names.sort(key=lambda n: totals[n])

    cells = max(1, int(params.get("cells", 100) or 100))
    counts = svgplot.allocate([totals[n] for n in names], cells)
    grand = sum(totals.values())

    merged_style = visual_style.merge_styles(
        style if visual_style.is_style(style) else None, None)
    tok = visual_style.tokens(merged_style)
    colours = svgplot.series_colours(names, tok["palette"])

    picked = selected_values(params.get("selected", ""))
    mode = str(params.get("on_click", "select one") or "nothing")
    if mode == "nothing":
        picked = []
    # A selection naming nothing on the chart would dim every square and
    # look like a broken render; treat it as no selection.
    picked = [name for name in picked if name in totals]

    drawing = _draw(names, counts, colours, params, picked, mode)

    shows = str(params.get("legend_shows", "share") or "share")
    spec = str(params.get("value_format", ",.0f") or "")
    entries = []
    for name, count in zip(names, counts):
        if shows == "share":
            note = f"{totals[name] / grand * 100:.0f}%" if grand else ""
        elif shows == "value":
            note = infographic.format_value(totals[name], spec)
        elif shows == "squares":
            note = str(count)
        else:
            note = ""
        entries.append((name, colours[name], note))
    legend_html = (svgplot.legend(entries, mode, picked)
                   if params.get("legend", True) else "")

    each = grand / cells if cells else 0
    note = ""
    if value and grand:
        note = (f"one square ≈ "
                f"{infographic.format_value(each, spec)} {value}")

    html = svgplot.chart_page(
        drawing, tok,
        title=str(params.get("title", "") or ""),
        subtitle=str(params.get("subtitle", "") or ""),
        legend_html=legend_html, note=note, mode=mode, picked=picked)

    ctx.log(f"{len(names)} categor{'y' if len(names) == 1 else 'ies'} over "
            f"{sum(counts)} square(s)"
            + (f", {value} totalling {grand:g}" if value
               else ", counting rows"))

    filtered = table
    if picked and label in table.columns:
        keep = table[label].astype(str).str.strip().isin(set(picked))
        filtered = table[keep]
        ctx.log(f"clicked {', '.join(picked)}: kept {len(filtered)} of "
                f"{len(table)} rows")
    elif picked:
        filtered = pd.DataFrame(columns=table.columns)

    return {"html": html, "table": filtered, "selected": picked,
            "style": merged_style}
