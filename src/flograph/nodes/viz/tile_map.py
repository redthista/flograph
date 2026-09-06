"""Tile Map

A map where every place is the **same size square**, arranged so the country
still reads as itself. A tile-grid cartogram.

It exists because a real map answers the wrong question. Ask "which region
is doing best?" of a real map of the UK and the eye answers "the Highlands",
because they are enormous; London, where most of the money is, is a dot you
cannot click. Area becomes importance, and the reader gets the answer
backwards before reading a single number. Give every place an equal square
and the colour is the only thing left to compare — which is what you wanted
compared.

Built in: **UK regions**, **UK nations** and **US states**. Names are
matched generously, so "Yorkshire and The Humber", "Yorks & Humber" and
"YH" all land on the same square, and anywhere in the grid your data does
not mention is drawn empty rather than left out — a blank square is a fact
worth seeing.

Every grid is a compromise with the geography, and a compromise you
disagree with is not a bug: pick **Custom** and write your own, one
`name, row, column` per line. Sales territories, wards, depots, floors of a
building, seats in a room — anything with a shape people recognise.

Nothing is downloaded and no script draws it: Python works out every square
and writes the SVG, so it looks the same on the card, in a tile, printed
into a report, and in a browser with the app closed.

**Click a square** to filter — that place goes to **selected**, and
**table** is your rows cut down to it. Colours and type come from a
**Visual Style** node on the `style` input.
"""
NODE = {
    "label": "Tile Map",
    "category": "Viz",
    "version": "1.0",
    "card": "webview",
    "interactive": True,
    "inputs": [("table", "dataframe"),
               ("style", "object", {"optional": True})],
    "outputs": [("html", "string"), ("table", "dataframe"),
                ("selected", "any"), ("style", "object")],
}

_RAMPS = ("accent", "cool", "warm", "heat", "green", "grey")

PARAMS = [
    {"name": "more", "type": "bool", "label": "More options",
     "default": False, "cosmetic": True},

    {"name": "region_column", "type": "columns", "label": "Place",
     "multi": False, "default": "",
     "placeholder": "(the first text column)"},
    {"name": "value_column", "type": "columns", "label": "Value",
     "multi": False, "default": "",
     "placeholder": "(the first number column — or blank to count rows)"},
    {"name": "grid", "type": "choice", "label": "Grid",
     "options": ["UK regions", "UK nations", "US states", "Custom"],
     "default": "UK regions"},
    {"name": "ramp", "type": "choice", "label": "Colours",
     "options": list(_RAMPS), "default": "accent"},

    {"name": "title", "type": "string", "label": "Title", "default": "",
     "placeholder": "heading across the top"},
    {"name": "subtitle", "type": "string", "label": "Subtitle",
     "default": "", "placeholder": "a line under the heading"},
    {"name": "value_format", "type": "string", "label": "Value format",
     "default": ",.0f", "placeholder": "$,.0f   .1%   ,.2f"},
    {"name": "show_value", "type": "bool", "label": "Show the numbers",
     "default": True},

    {"name": "on_click", "type": "choice", "label": "On click",
     "options": ["nothing", "select one", "select many"],
     "default": "select one"},
    {"name": "selected", "type": "string", "label": "Selected values",
     "default": "", "placeholder": 'written by a click, e.g. ["London"]'},

    {"name": "custom_grid", "type": "text", "label": "Custom grid",
     "default": "", "placeholder": "North, 0, 1\nWest, 1, 0\nEast, 1, 2",
     "visible_when": {"grid": ["Custom"]}},
    {"name": "reverse", "type": "bool", "label": "Reverse the colours",
     "default": False, "visible_when": {"more": ["True"]}},
    {"name": "legend", "type": "bool", "label": "Legend", "default": True,
     "visible_when": {"more": ["True"]}},
    {"name": "captions", "type": "bool", "label": "Name every square",
     "default": True, "visible_when": {"more": ["True"]}},

    {"name": "width", "type": "int", "label": "Width", "default": 420,
     "min": 260, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height", "default": 360,
     "min": 200, "max": 2000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %", "default": 100,
     "min": 25, "max": 400, "cosmetic": True},
]

#: One tile's slot in the drawing's own units, and the gap inside it.
_CELL = 100.0
_GAP = 8.0


def _ramp_stops(name, tok):
    """The colours a value is shaded between.

    `accent` is built from the style's own accent, so a re-themed page
    re-themes its map too; the rest are fixed ramps for when the accent is
    not the right story.
    """
    from flograph.core.svgplot import mix

    surface = tok["surface"]
    if name == "accent":
        return [mix(surface, tok["accent"], 0.18), tok["accent"]]
    if name == "cool":
        return ["#0e2a47", "#2563eb", "#67e8f9"]
    if name == "warm":
        return ["#3b1d06", "#ea580c", "#fde047"]
    if name == "heat":
        return ["#1d4ed8", "#a855f7", "#ef4444"]
    if name == "green":
        return ["#052e21", "#10b981", "#a7f3d0"]
    return ["#1e293b", "#64748b", "#e2e8f0"]


def _totals(rows, place, value):
    """Place totals in first-seen order, adding duplicate rows together."""
    from flograph.core.svgplot import text_of, to_number

    totals: dict[str, float] = {}
    for row in rows:
        name = text_of(row.get(place))
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


def _pick_columns(rows, params):
    from flograph.core.svgplot import to_number

    columns = list(rows[0].keys()) if rows else []
    place = str(params.get("region_column", "") or "").strip()
    value = str(params.get("value_column", "") or "").strip()
    for name, what in ((place, "Place"), (value, "Value")):
        if name and name not in columns:
            raise ValueError(f"no column called {name!r} for {what} — the "
                             "table has: " + ", ".join(map(str, columns)))
    if not place:
        place = next((c for c in columns
                      if any(to_number(row.get(c)) is None
                             and row.get(c) is not None for row in rows)),
                     columns[0] if columns else "")
    if not value:
        value = next((c for c in columns if c != place
                      and any(to_number(row.get(c)) is not None
                              for row in rows)), "")
    if not place:
        raise ValueError("a tile map needs a Place column — what each square "
                         "stands for")
    return place, value


def run(ctx, table, style=None):
    import pandas as pd

    from flograph.core import infographic, svgplot, tilegrid, visual_style
    from flograph.core.controls import selected_values

    params = ctx.params
    rows = infographic.rows_from_frame(table)
    if not rows:
        raise ValueError("nothing to draw — the table is empty")
    place, value = _pick_columns(rows, params)

    grid_name = str(params.get("grid", "UK regions") or "UK regions")
    cells = tilegrid.grid(grid_name, str(params.get("custom_grid", "") or ""))
    totals = _totals(rows, place, value)

    # Every name in the data placed on a square, and anything that could not
    # be placed said out loud. A silently missing region is the failure mode
    # of every map like this: the picture looks complete and is not.
    onto: dict[str, float] = {}
    names: dict[str, str] = {}
    stranded = []
    for name, number in totals.items():
        code = tilegrid.lookup(name, cells, grid_name)
        if code is None:
            stranded.append(name)
            continue
        onto[code] = onto.get(code, 0.0) + number
        names.setdefault(code, name)

    if not onto:
        raise ValueError(
            f"none of the places in {place!r} is on the {grid_name!r} grid — "
            + (f"nothing matched (first few: "
               f"{', '.join(sorted(totals)[:4])})" if totals
               else "there are no places in that column"))

    merged_style = visual_style.merge_styles(
        style if visual_style.is_style(style) else None, None)
    tok = visual_style.tokens(merged_style)
    stops = _ramp_stops(str(params.get("ramp", "accent") or "accent"), tok)
    if params.get("reverse", False):
        stops = list(reversed(stops))

    picked = selected_values(params.get("selected", ""))
    mode = str(params.get("on_click", "select one") or "nothing")
    if mode == "nothing":
        picked = []
    picked = [name for name in picked if name in totals]
    chosen = {tilegrid.lookup(name, cells, grid_name) for name in picked}

    low, high = svgplot.extent(onto.values())
    spec = str(params.get("value_format", ",.0f") or "")
    show_value = bool(params.get("show_value", True))
    captions = bool(params.get("captions", True))

    down, across = tilegrid.bounds(cells.values())
    out = [svgplot.svg_open(across * _CELL, down * _CELL)]
    for code, (row, column) in sorted(cells.items(), key=lambda kv: kv[1]):
        x, y = column * _CELL + _GAP / 2, row * _CELL + _GAP / 2
        side = _CELL - _GAP
        here = onto.get(code)

        if here is None:
            # On the grid, absent from the data. Drawn as an outline: the
            # shape of the country stays whole and the hole is visible.
            out.append(
                f"<rect x='{svgplot.num(x)}' y='{svgplot.num(y)}' "
                f"width='{svgplot.num(side)}' height='{svgplot.num(side)}' "
                f"rx='{svgplot.num(tok['radius'])}' fill='none' "
                f"stroke='{tok['border']}' stroke-width='2' "
                f"stroke-dasharray='6 5'/>")
            if captions:
                out.append(
                    f"<text x='{svgplot.num(x + side / 2)}' "
                    f"y='{svgplot.num(y + side / 2)}' fill='{tok['muted']}' "
                    f"font-size='20' text-anchor='middle' "
                    f"dominant-baseline='central'>"
                    f"{svgplot.escape(tilegrid.caption(code, grid_name))}"
                    f"</text>")
            continue

        fill = svgplot.ramp(stops, svgplot.position(here, low, high))
        if chosen and code not in chosen:
            fill = svgplot.fade(fill, 0.6)
        ink = svgplot.readable_on(fill)
        klass = f"tile{svgplot.hit_class(mode)}"
        click = svgplot.click_attr(names.get(code, code), mode)
        out.append(
            f"<g class='{klass}'{click}>"
            f"<rect x='{svgplot.num(x)}' y='{svgplot.num(y)}' "
            f"width='{svgplot.num(side)}' height='{svgplot.num(side)}' "
            f"rx='{svgplot.num(tok['radius'])}' fill='{fill}'/>"
            f"<title>{svgplot.escape(names.get(code, code))}: "
            f"{svgplot.escape(infographic.format_value(here, spec))}</title>")
        if captions:
            out.append(
                f"<text x='{svgplot.num(x + side / 2)}' "
                f"y='{svgplot.num(y + side * (0.36 if show_value else 0.5))}' "
                f"fill='{ink}' font-size='21' font-weight='700' "
                f"text-anchor='middle' dominant-baseline='central'>"
                f"{svgplot.escape(tilegrid.caption(code, grid_name))}</text>")
        if show_value:
            out.append(
                f"<text x='{svgplot.num(x + side / 2)}' "
                f"y='{svgplot.num(y + side * (0.66 if captions else 0.5))}' "
                f"fill='{ink}' font-size='19' text-anchor='middle' "
                f"dominant-baseline='central' opacity='0.92'>"
                f"{svgplot.escape(infographic.format_value(here, spec))}"
                f"</text>")
        out.append("</g>")
    out.append("</svg>")

    legend_html = ""
    if params.get("legend", True):
        legend_html = svgplot.ramp_legend(
            stops, infographic.format_value(low, spec),
            infographic.format_value(high, spec),
            value or "rows")

    note = ""
    if stranded:
        note = (f"{len(stranded)} not on the map: "
                + ", ".join(sorted(stranded)[:5])
                + (" …" if len(stranded) > 5 else ""))
    blank = len(cells) - len(onto)
    if blank:
        note += (" — " if note else "") + f"{blank} square(s) with no data"

    html = svgplot.chart_page(
        "".join(out), tok,
        title=str(params.get("title", "") or ""),
        subtitle=str(params.get("subtitle", "") or ""),
        legend_html=legend_html, note=note, mode=mode, picked=picked)

    ctx.log(f"{len(onto)} of {len(cells)} squares on the {grid_name} grid"
            + (f", {value} from {low:g} to {high:g}" if value
               else ", counting rows"))
    if stranded:
        ctx.log("not on the grid: " + ", ".join(sorted(stranded)))

    filtered = table
    if picked and place in table.columns:
        keep = table[place].astype(str).str.strip().isin(set(picked))
        filtered = table[keep]
        ctx.log(f"clicked {', '.join(picked)}: kept {len(filtered)} of "
                f"{len(table)} rows")
    elif picked:
        filtered = pd.DataFrame(columns=table.columns)

    return {"html": html, "table": filtered, "selected": picked,
            "style": merged_style}
