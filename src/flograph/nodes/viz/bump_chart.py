"""Bump Chart

**Who is winning, and when did that change?** A line per contender, running
left to right through the periods, but the height is the *place* — first at
the top — rather than the score. Crossings are overtakes, and you can see
who overtook whom, in which month, from across the room.

Use it when the ranking is the story and the raw numbers are not: brands by
share, teams by points, products by sales, keywords by traffic, regions by
anything. A line chart of the same figures answers "how much?" and buries
the overtake somewhere in the middle of a bundle of lines; this answers "who
is ahead?" and can do nothing else, which is the point.

A tie holds the same place. A contender missing from a period leaves a gap
in its line rather than a plunge to the bottom — not reporting is not the
same as coming last.

Nothing is downloaded and no script draws it: Python works out every
coordinate and writes the SVG, so it looks the same on the card, in a tile,
printed into a report, and in a browser with the app closed.

**Click a line** to filter — that contender goes to **selected**, and
**table** is your rows cut down to it. Colours and type come from a
**Visual Style** node on the `style` input.
"""
NODE = {
    "label": "Bump Chart",
    "category": "Viz",
    "version": "1.0",
    "card": "webview",
    "interactive": True,
    "inputs": [("table", "dataframe"),
               ("style", "object", {"optional": True})],
    "outputs": [("html", "string"), ("table", "dataframe"),
                ("selected", "any"), ("style", "object")],
}

PARAMS = [
    {"name": "more", "type": "bool", "label": "More options",
     "default": False, "cosmetic": True},

    {"name": "label_column", "type": "columns", "label": "Contender",
     "multi": False, "default": "",
     "placeholder": "(the first text column)"},
    {"name": "period_column", "type": "columns", "label": "Period",
     "multi": False, "default": "",
     "placeholder": "(the second text column) — across the bottom"},
    {"name": "value_column", "type": "columns", "label": "Ranked by",
     "multi": False, "default": "",
     "placeholder": "(the first number column)"},
    {"name": "best", "type": "choice", "label": "First place is",
     "options": ["the highest", "the lowest"], "default": "the highest"},
    {"name": "top", "type": "int", "label": "Places shown", "default": 0,
     "min": 0, "max": 60, "placeholder": "0 = all of them"},

    {"name": "title", "type": "string", "label": "Title", "default": "",
     "placeholder": "heading across the top"},
    {"name": "subtitle", "type": "string", "label": "Subtitle",
     "default": "", "placeholder": "a line under the heading"},
    {"name": "on_click", "type": "choice", "label": "On click",
     "options": ["nothing", "select one", "select many"],
     "default": "select one"},
    {"name": "selected", "type": "string", "label": "Selected values",
     "default": "", "placeholder": 'written by a click, e.g. ["Alpha"]'},

    {"name": "dots", "type": "choice", "label": "In the dots",
     "options": ["the place", "the value", "nothing"],
     "default": "the place", "visible_when": {"more": ["True"]}},
    {"name": "value_format", "type": "string", "label": "Value format",
     "default": ",.0f", "placeholder": "$,.0f   .1%   ,.2f",
     "visible_when": {"more": ["True"]}},
    {"name": "labels", "type": "choice", "label": "Names",
     "options": ["both ends", "left", "right", "nothing"],
     "default": "both ends", "visible_when": {"more": ["True"]}},
    {"name": "curve", "type": "float", "label": "Curve", "default": 0.5,
     "min": 0.0, "max": 0.8, "visible_when": {"more": ["True"]}},
    {"name": "legend", "type": "bool", "label": "Legend", "default": False,
     "visible_when": {"more": ["True"]}},

    {"name": "width", "type": "int", "label": "Width", "default": 520,
     "min": 260, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height", "default": 340,
     "min": 200, "max": 2000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %", "default": 100,
     "min": 25, "max": 400, "cosmetic": True},
]

_W = 1000.0
_TOP = 70.0              # the period headings
_BOTTOM = 24.0
_PLACE = 52.0            # vertical room one place wants
_DOT = 15.0
_NAME_SIZE = 24.0        # the contenders' names down each edge


def _pick_columns(rows, params):
    """Contender, period and value — named, or worked out from the table."""
    from flograph.core.svgplot import to_number

    columns = list(rows[0].keys()) if rows else []
    label = str(params.get("label_column", "") or "").strip()
    period = str(params.get("period_column", "") or "").strip()
    value = str(params.get("value_column", "") or "").strip()
    for name, what in ((label, "Contender"), (period, "Period"),
                       (value, "Ranked by")):
        if name and name not in columns:
            raise ValueError(f"no column called {name!r} for {what} — the "
                             "table has: " + ", ".join(map(str, columns)))

    texty = [c for c in columns
             if any(to_number(row.get(c)) is None and row.get(c) is not None
                    for row in rows)]
    if not label:
        label = next((c for c in texty if c != period), "")
    if not period:
        period = next((c for c in texty if c != label), "")
    if not value:
        value = next((c for c in columns
                      if c not in (label, period)
                      and any(to_number(row.get(c)) is not None
                              for row in rows)), "")

    if not label:
        raise ValueError("a bump chart needs a Contender column — the thing "
                         "each line stands for")
    if not period:
        raise ValueError("a bump chart needs a Period column — what runs "
                         "along the bottom")
    if not value:
        raise ValueError("a bump chart needs something to rank by — a "
                         "number column")
    return label, period, value


def _runs(places, count):
    """Split a contender's places into unbroken stretches.

    A missing period breaks the line in two rather than being drawn
    through: a contender that did not report in March did not slide from
    second to fifth and back, and a line that says so is a lie the reader
    has no way to catch.
    """
    out, run = [], []
    for index in range(count):
        if index in places:
            run.append(index)
        elif run:
            out.append(run)
            run = []
    if run:
        out.append(run)
    return out


def _draw(names, periods, places, values, params, tok, colours, picked, mode):
    from flograph.core import infographic, svgplot

    deepest = max((place for row in places.values() for place in row.values()),
                  default=1)
    height = max(_W * 0.42, _TOP + _BOTTOM + _PLACE * deepest)
    top, bottom = _TOP, height - _BOTTOM

    label_mode = str(params.get("labels", "both ends") or "nothing")
    # Sized to the names there actually are. A fixed gutter either wastes
    # half the drawing on "Q1" or cuts "Yorkshire and The Humber" off at
    # both ends, and which of those happens is not the chart's to choose.
    wanted = svgplot.gutter(names, _NAME_SIZE, pad=_DOT + 24)
    left_room = wanted if label_mode in ("both ends", "left") else 40.0
    right_room = wanted if label_mode in ("both ends", "right") else 40.0
    left, right = left_room, _W - right_room
    step = (right - left) / max(1, len(periods) - 1)

    def at(index, place):
        x = left + step * index if len(periods) > 1 else (left + right) / 2
        y = top + (bottom - top) * ((place - 0.5) / max(1, deepest))
        return x, y

    spec = str(params.get("value_format", ",.0f") or "")
    inside = str(params.get("dots", "the place") or "nothing")
    tension = max(0.0, min(0.8, float(params.get("curve", 0.5) or 0)))
    chosen = set(picked)

    out = [svgplot.svg_open(_W, height)]

    for index, period in enumerate(periods):
        x = left + step * index if len(periods) > 1 else (left + right) / 2
        out.append(
            f"<text x='{svgplot.num(x)}' y='{svgplot.num(top - 32)}' "
            f"fill='{tok['muted']}' font-size='25' font-weight='600' "
            f"text-anchor='middle'>"
            f"{svgplot.escape(svgplot.shorten(str(period), 12))}</text>"
            f"<line x1='{svgplot.num(x)}' y1='{svgplot.num(top - 16)}' "
            f"x2='{svgplot.num(x)}' y2='{svgplot.num(bottom)}' "
            f"stroke='{tok['border']}' stroke-width='1.5'/>")

    for name in names:
        row = places[name]
        colour = colours[name]
        if chosen and name not in chosen:
            colour = svgplot.fade(colour, 0.7)
        klass = f"bump{svgplot.hit_class(mode)}"
        out.append(f"<g class='{klass}'{svgplot.click_attr(name, mode)}>")

        for run in _runs(row, len(periods)):
            points = [at(index, row[index]) for index in run]
            path = svgplot.smooth_path(points, tension)
            if len(points) > 1:
                out.append(
                    f"<path d='{path}' fill='none' stroke='transparent' "
                    f"stroke-width='26'/>"
                    f"<path d='{path}' fill='none' stroke='{colour}' "
                    f"stroke-width='5' stroke-linecap='round'/>")

        for index, place in sorted(row.items()):
            x, y = at(index, place)
            out.append(
                f"<circle cx='{svgplot.num(x)}' cy='{svgplot.num(y)}' "
                f"r='{svgplot.num(_DOT)}' fill='{colour}' "
                f"stroke='{tok['bg']}' stroke-width='2.5'/>")
            text = ""
            if inside == "the place":
                text = str(place)
            elif inside == "the value":
                text = infographic.format_value(values[name].get(index), spec)
            if text:
                out.append(
                    f"<text x='{svgplot.num(x)}' y='{svgplot.num(y)}' "
                    f"fill='{svgplot.readable_on(colour)}' font-size='17' "
                    f"font-weight='700' text-anchor='middle' "
                    f"dominant-baseline='central'>"
                    f"{svgplot.escape(text)}</text>")

        ends = sorted(row)
        shown = svgplot.fit(name, wanted - _DOT - 24, _NAME_SIZE)
        if ends and label_mode in ("both ends", "left"):
            x, y = at(ends[0], row[ends[0]])
            out.append(
                f"<text x='{svgplot.num(x - _DOT - 12)}' "
                f"y='{svgplot.num(y + 8)}' text-anchor='end' "
                f"font-size='{svgplot.num(_NAME_SIZE)}' "
                f"fill='{tok['fg']}'>{svgplot.escape(shown)}</text>")
        if ends and label_mode in ("both ends", "right"):
            x, y = at(ends[-1], row[ends[-1]])
            out.append(
                f"<text x='{svgplot.num(x + _DOT + 12)}' "
                f"y='{svgplot.num(y + 8)}' text-anchor='start' "
                f"font-size='{svgplot.num(_NAME_SIZE)}' "
                f"fill='{tok['fg']}'>{svgplot.escape(shown)}</text>")
        out.append("</g>")

    out.append("</svg>")
    return "".join(out)


def run(ctx, table, style=None):
    import pandas as pd

    from flograph.core import infographic, svgplot, visual_style
    from flograph.core.controls import selected_values

    params = ctx.params
    rows = infographic.rows_from_frame(table)
    if not rows:
        raise ValueError("nothing to draw — the table is empty")
    label, period, value = _pick_columns(rows, params)

    # Periods in the order the table has them, so an upstream sort decides
    # what "left to right" means — dates, quarters, seasons and made-up
    # names all order themselves differently, and only the flow knows how.
    periods = []
    for row in rows:
        key = row.get(period)
        text = svgplot.text_of(key)
        if text and text not in periods:
            periods.append(text)
    if not periods:
        raise ValueError(f"{period!r} has no periods to plot")

    highest = str(params.get("best", "the highest")) != "the lowest"
    ranks = svgplot.rank_within(rows, group=period, value=value,
                                highest_first=highest)
    top = int(params.get("top", 0) or 0)

    places: dict[str, dict[int, int]] = {}
    values: dict[str, dict[int, float]] = {}
    for index, row in enumerate(rows):
        if index not in ranks:
            continue
        name = svgplot.text_of(row.get(label))
        when = svgplot.text_of(row.get(period))
        if not name or when not in periods:
            continue
        place = ranks[index]
        if top and place > top:
            continue
        column = periods.index(when)
        places.setdefault(name, {})[column] = place
        values.setdefault(name, {})[column] = svgplot.to_number(row.get(value))

    places = {name: row for name, row in places.items() if row}
    if not places:
        raise ValueError(
            "nothing to rank — no row has both a contender and a number"
            + (f" inside the top {top}" if top else ""))

    # First seen at its best place, so the leaders take the first palette
    # colours and the legend reads top-down.
    names = sorted(places, key=lambda n: (min(places[n].values()), n))

    merged_style = visual_style.merge_styles(
        style if visual_style.is_style(style) else None, None)
    tok = visual_style.tokens(merged_style)
    colours = svgplot.series_colours(names, tok["palette"])

    picked = selected_values(params.get("selected", ""))
    mode = str(params.get("on_click", "select one") or "nothing")
    if mode == "nothing":
        picked = []
    picked = [name for name in picked if name in places]

    drawing = _draw(names, periods, places, values, params, tok, colours,
                    picked, mode)

    legend_html = ""
    if params.get("legend", False):
        legend_html = svgplot.legend(
            [(name, colours[name], "") for name in names], mode, picked)

    first, last = periods[0], periods[-1]
    # The biggest move in *either* direction. Reporting only the climbers
    # would headline a one-place gain on a chart whose actual story is
    # somebody falling from first to fourth.
    moves = [(name, places[name][0] - places[name][len(periods) - 1])
             for name in names
             if 0 in places[name] and len(periods) - 1 in places[name]]
    note = f"{len(names)} contenders over {len(periods)} periods"
    if moves:
        who, moved = max(moves, key=lambda pair: abs(pair[1]))
        if moved:
            note += (f" — {who} {'climbed' if moved > 0 else 'fell'} "
                     f"{abs(moved)} place{'s' if abs(moved) != 1 else ''} "
                     f"from {first} to {last}")
        else:
            note += f" — nobody changed place between {first} and {last}"

    html = svgplot.chart_page(
        drawing, tok,
        title=str(params.get("title", "") or ""),
        subtitle=str(params.get("subtitle", "") or ""),
        legend_html=legend_html, note=note, mode=mode, picked=picked)

    ctx.log(f"{len(names)} contender(s) ranked over {len(periods)} period(s), "
            f"{first} to {last}, by {value}"
            + (f" (top {top} only)" if top else ""))

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
