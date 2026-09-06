"""Slope Chart

Two moments, one line each: **what went up, what went down, and by how
much**. Before and after, last year and this, budget and actual, the poll a
month ago and the poll today.

A grouped bar chart of the same numbers makes you compare eight pairs of
heights one pair at a time. A slope chart draws the *change itself* as the
thing on the page — a line tilting up or down — so the answer arrives before
you have read a single number, and the one series going the other way is
impossible to miss.

Give it either shape of table. **Long**: a Series column, a Period column
and a Value column, and it takes the first and last period it finds.
**Wide**: a Series column and two value columns, one per moment. Labels that
would land on top of each other are nudged apart, which is what usually
ruins a hand-made one.

Nothing is downloaded and no script draws it: Python works out every
coordinate and writes the SVG, so it looks the same on the card, in a tile,
printed into a report, and in a browser with the app closed.

**Click a line** to filter — that series goes to **selected**, and **table**
is your rows cut down to it. Colours and type come from a **Visual Style**
node on the `style` input.
"""
NODE = {
    "label": "Slope Chart",
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

    {"name": "label_column", "type": "columns", "label": "Series",
     "multi": False, "default": "",
     "placeholder": "(the first text column)"},
    {"name": "period_column", "type": "columns", "label": "Period",
     "multi": False, "default": "",
     "placeholder": "long tables only — leave blank for two columns"},
    {"name": "value_column", "type": "columns", "label": "Value",
     "multi": False, "default": "",
     "placeholder": "long tables only — the number to plot"},
    {"name": "start_column", "type": "columns", "label": "Before",
     "multi": False, "default": "", "placeholder": "the earlier column"},
    {"name": "end_column", "type": "columns", "label": "After",
     "multi": False, "default": "", "placeholder": "the later column"},

    {"name": "title", "type": "string", "label": "Title", "default": "",
     "placeholder": "heading across the top"},
    {"name": "subtitle", "type": "string", "label": "Subtitle",
     "default": "", "placeholder": "a line under the heading"},
    {"name": "value_format", "type": "string", "label": "Value format",
     "default": ",.0f", "placeholder": "$,.0f   .1%   ,.2f"},
    {"name": "colour_by", "type": "choice", "label": "Colour by",
     "options": ["direction", "series", "nothing"], "default": "direction"},

    {"name": "on_click", "type": "choice", "label": "On click",
     "options": ["nothing", "select one", "select many"],
     "default": "select one"},
    {"name": "selected", "type": "string", "label": "Selected values",
     "default": "", "placeholder": 'written by a click, e.g. ["North"]'},

    {"name": "start_label", "type": "string", "label": "Before heading",
     "default": "", "placeholder": "(the period or column name)",
     "visible_when": {"more": ["True"]}},
    {"name": "end_label", "type": "string", "label": "After heading",
     "default": "", "placeholder": "(the period or column name)",
     "visible_when": {"more": ["True"]}},
    {"name": "show_values", "type": "bool", "label": "Show the numbers",
     "default": True, "visible_when": {"more": ["True"]}},
    {"name": "show_change", "type": "bool", "label": "Show the change",
     "default": False, "visible_when": {"more": ["True"]}},
    {"name": "rows", "type": "int", "label": "Series shown", "default": 0,
     "min": 0, "max": 200, "visible_when": {"more": ["True"]}},

    {"name": "width", "type": "int", "label": "Width", "default": 460,
     "min": 260, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height", "default": 340,
     "min": 200, "max": 2000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %", "default": 100,
     "min": 25, "max": 400, "cosmetic": True},
]

#: The drawing's own coordinate space. Width is fixed and the height grows
#: with the number of series, so ten series get a taller drawing rather than
#: ten squashed ones — the SVG scales to the card either way.
_W = 1000.0
_LABEL_SIZE = 25.0       # the names and numbers down each edge
_TOP = 54.0              # the period headings
_BOTTOM = 26.0
_ROW = 44.0              # vertical room one series wants
_UP = "#10b981"
_DOWN = "#ef4444"


def _columns_of(rows):
    return list(rows[0].keys()) if rows else []


def _need(name, columns, what):
    if name and name not in columns:
        raise ValueError(f"no column called {name!r} for {what} — the table "
                         "has: " + ", ".join(map(str, columns)))


def _series(rows, params):
    """`[(name, before, after)]`, plus the two headings.

    Long tables (a period column) and wide ones (two value columns) both
    land here, because which of the two you have is an accident of where
    the data came from, not a different chart.
    """
    from flograph.core.svgplot import text_of, to_number

    columns = _columns_of(rows)
    label = str(params.get("label_column", "") or "").strip()
    period = str(params.get("period_column", "") or "").strip()
    _need(label, columns, "Series")
    _need(period, columns, "Period")

    if not label:
        for column in columns:
            if column != period and any(
                    to_number(row.get(column)) is None
                    and row.get(column) is not None for row in rows):
                label = column
                break
        label = label or (columns[0] if columns else "")
    if not label:
        raise ValueError("a slope chart needs a Series column — the thing "
                         "each line stands for")

    if period:
        value = str(params.get("value_column", "") or "").strip()
        _need(value, columns, "Value")
        if not value:
            for column in columns:
                if column not in (label, period) and any(
                        to_number(row.get(column)) is not None
                        for row in rows):
                    value = column
                    break
        if not value:
            raise ValueError("a slope chart needs a Value column")

        periods = []
        for row in rows:
            key = row.get(period)
            text = text_of(key)
            if text and text not in periods:
                periods.append(text)
        if len(periods) < 2:
            raise ValueError(
                f"{period!r} has "
                + (f"only one period ({periods[0]!r})" if periods
                   else "no periods")
                + " — a slope chart needs two moments to join up")
        first, last = periods[0], periods[-1]

        found: dict[str, list] = {}
        for row in rows:
            name = text_of(row.get(label))
            when = text_of(row.get(period))
            if not name or when not in (first, last):
                continue
            pair = found.setdefault(name, [None, None])
            pair[0 if when == first else 1] = to_number(row.get(value))
        series = [(name, pair[0], pair[1]) for name, pair in found.items()]
        return series, first, last, label, len(periods)

    start = str(params.get("start_column", "") or "").strip()
    end = str(params.get("end_column", "") or "").strip()
    _need(start, columns, "Before")
    _need(end, columns, "After")
    if not (start and end):
        numeric = [c for c in columns if c != label
                   and any(to_number(row.get(c)) is not None for row in rows)]
        start = start or (numeric[0] if numeric else "")
        end = end or next((c for c in numeric if c != start), "")
    if not (start and end):
        raise ValueError(
            "a slope chart needs two moments: either a Period column and a "
            "Value column, or a Before column and an After column")

    series = []
    for row in rows:
        name = text_of(row.get(label))
        if not name:
            continue
        series.append((name, to_number(row.get(start)),
                       to_number(row.get(end))))
    return series, start, end, label, 2


def _draw(series, params, tok, colours, picked, mode, moments):
    from flograph.core import infographic, svgplot

    spec = str(params.get("value_format", ",.0f") or "")
    colour_by = str(params.get("colour_by", "direction") or "direction")
    show_values = bool(params.get("show_values", True))
    show_change = bool(params.get("show_change", False))
    chosen = set(picked)

    # A floor on the height as well as a per-series pitch. Three series at
    # 44 units each is a drawing nine times wider than it is tall, which
    # fits inside a card as a thin ribbon across the middle with the space
    # above and below going to waste.
    height = max(_W * 0.5, _TOP + _BOTTOM + _ROW * len(series))
    top, bottom = _TOP, height - _BOTTOM

    # Each edge gets the room its own labels want. The left holds a name
    # and a number, the right a number and possibly a change, and a fixed
    # gutter for both either wastes the middle of the chart or cuts a long
    # region name off at the edge of the card.
    left_labels = [f"{name} {infographic.format_value(before, spec)}"
                   if show_values else name
                   for name, before, _ in series]
    right_labels = []
    for name, before, after in series:
        tail = infographic.format_value(after, spec) if show_values else ""
        if show_change:
            tail += ("  " if tail else "") + \
                f"▲ {infographic.format_value(abs(after - before), spec)}"
        right_labels.append(tail or name)
    left = svgplot.gutter(left_labels, _LABEL_SIZE, pad=32.0)
    right = _W - svgplot.gutter(right_labels, _LABEL_SIZE, pad=32.0)

    low, high = svgplot.extent(
        [v for _, before, after in series for v in (before, after)])
    if high == low:
        low, high = low - 1, high + 1
    pad = (high - low) * 0.08
    low, high = low - pad, high + pad

    def place(value):
        return bottom - (bottom - top) * svgplot.position(value, low, high)

    left_targets = [place(before) for _, before, _ in series]
    right_targets = [place(after) for _, _, after in series]
    # The smallest gap two labels may sit at, grown to suit the room there
    # actually is: on a tall drawing with four series, holding them 30 units
    # apart would bunch them in the middle of an empty chart.
    gap = min(52.0, max(30.0, (bottom - top) / max(1, len(series)) * 0.8))
    left_ys = svgplot.spread(left_targets, gap, top, bottom)
    right_ys = svgplot.spread(right_targets, gap, top, bottom)

    out = [svgplot.svg_open(_W, height)]
    out.append(
        f"<line x1='{svgplot.num(left)}' y1='{svgplot.num(top - 20)}' "
        f"x2='{svgplot.num(left)}' y2='{svgplot.num(bottom)}' "
        f"stroke='{tok['border']}' stroke-width='2'/>"
        f"<line x1='{svgplot.num(right)}' y1='{svgplot.num(top - 20)}' "
        f"x2='{svgplot.num(right)}' y2='{svgplot.num(bottom)}' "
        f"stroke='{tok['border']}' stroke-width='2'/>")

    heading = str(params.get("start_label", "") or "") or moments[0]
    trailing = str(params.get("end_label", "") or "") or moments[1]
    out.append(
        f"<text x='{svgplot.num(left)}' y='{svgplot.num(top - 34)}' "
        f"fill='{tok['muted']}' font-size='24' font-weight='600' "
        f"text-anchor='end'>{svgplot.escape(heading)}</text>"
        f"<text x='{svgplot.num(right)}' y='{svgplot.num(top - 34)}' "
        f"fill='{tok['muted']}' font-size='24' font-weight='600' "
        f"text-anchor='start'>{svgplot.escape(trailing)}</text>")

    for index, (name, before, after) in enumerate(series):
        y1, y2 = left_ys[index], right_ys[index]
        if colour_by == "series":
            colour = colours[name]
        elif colour_by == "nothing":
            colour = tok["accent"]
        else:
            colour = (_UP if after > before else
                      _DOWN if after < before else tok["muted"])
        if chosen and name not in chosen:
            colour = svgplot.fade(colour, 0.66)

        klass = f"line{svgplot.hit_class(mode)}"
        click = svgplot.click_attr(name, mode)
        out.append(f"<g class='{klass}'{click}>")
        # An invisible fat line under the thin one: a 3px stroke is a hard
        # thing to hit with a mouse, and a click that usually misses reads
        # as a chart that does not respond.
        out.append(
            f"<line x1='{svgplot.num(left)}' y1='{svgplot.num(y1)}' "
            f"x2='{svgplot.num(right)}' y2='{svgplot.num(y2)}' "
            f"stroke='transparent' stroke-width='24'/>"
            f"<line x1='{svgplot.num(left)}' y1='{svgplot.num(y1)}' "
            f"x2='{svgplot.num(right)}' y2='{svgplot.num(y2)}' "
            f"stroke='{colour}' stroke-width='3.5'/>"
            f"<circle cx='{svgplot.num(left)}' cy='{svgplot.num(y1)}' r='6' "
            f"fill='{colour}'/>"
            f"<circle cx='{svgplot.num(right)}' cy='{svgplot.num(y2)}' r='6' "
            f"fill='{colour}'/>")

        value_text = (infographic.format_value(before, spec)
                      if show_values else "")
        # Whatever the number does not take, the name may have.
        name_text = svgplot.fit(
            name, left - 32 - svgplot.text_width(value_text + " ",
                                                 _LABEL_SIZE), _LABEL_SIZE)
        out.append(
            f"<text x='{svgplot.num(left - 16)}' "
            f"y='{svgplot.num(y1 + 8)}' text-anchor='end' "
            f"font-size='{svgplot.num(_LABEL_SIZE)}' "
            f"fill='{tok['fg']}'>{svgplot.escape(name_text)}"
            + (f" <tspan fill='{tok['muted']}'>"
               f"{svgplot.escape(value_text)}</tspan>" if value_text else "")
            + "</text>")

        tail = infographic.format_value(after, spec) if show_values else ""
        if show_change:
            change = after - before
            arrow = "▲" if change > 0 else "▼" if change < 0 else "▬"
            moved = infographic.format_value(abs(change), spec)
            tail = (tail + "  " if tail else "") + f"{arrow} {moved}"
        if not tail:
            tail = name
        tail = svgplot.fit(tail, _W - right - 32, _LABEL_SIZE)
        out.append(
            f"<text x='{svgplot.num(right + 16)}' "
            f"y='{svgplot.num(y2 + 8)}' text-anchor='start' "
            f"font-size='{svgplot.num(_LABEL_SIZE)}' "
            f"fill='{tok['fg']}'>{svgplot.escape(tail)}</text>")
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

    series, start_name, end_name, label, periods = _series(rows, params)
    complete = [(name, before, after) for name, before, after in series
                if before is not None and after is not None]
    dropped = len(series) - len(complete)
    if not complete:
        raise ValueError(
            "no series has a number at both moments — a slope chart joins "
            "two values, so a series missing either one has no line to draw")

    limit = int(params.get("rows", 0) or 0)
    if limit > 0:
        complete = sorted(complete, key=lambda s: -abs(s[2] - s[1]))[:limit]

    merged_style = visual_style.merge_styles(
        style if visual_style.is_style(style) else None, None)
    tok = visual_style.tokens(merged_style)
    names = [name for name, _, _ in complete]
    colours = svgplot.series_colours(names, tok["palette"])

    picked = selected_values(params.get("selected", ""))
    mode = str(params.get("on_click", "select one") or "nothing")
    if mode == "nothing":
        picked = []
    picked = [name for name in picked if name in set(names)]

    drawing = _draw(complete, params, tok, colours, picked, mode,
                    (start_name, end_name))

    rising = sum(1 for _, before, after in complete if after > before)
    falling = sum(1 for _, before, after in complete if after < before)
    note = f"{rising} up, {falling} down"
    if dropped:
        note += f" — {dropped} series left out, missing a value at one end"
    if periods > 2:
        note += (f" — {periods} periods in the data, showing "
                 f"{start_name} against {end_name}")

    # A legend only where it earns its space. Coloured by direction, green
    # and red need no key; coloured by series it is the only way to tell
    # two crossing lines apart, since the right-hand end shows numbers.
    legend_html = ""
    if str(params.get("colour_by", "")) == "series":
        legend_html = svgplot.legend(
            [(name, colours[name], "") for name in names], mode, picked)

    html = svgplot.chart_page(
        drawing, tok,
        title=str(params.get("title", "") or ""),
        subtitle=str(params.get("subtitle", "") or ""),
        legend_html=legend_html, note=note, mode=mode, picked=picked)

    ctx.log(f"{len(complete)} series, {start_name} -> {end_name}: "
            f"{rising} up, {falling} down"
            + (f", {dropped} incomplete" if dropped else ""))

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
