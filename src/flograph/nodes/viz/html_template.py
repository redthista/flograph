"""HTML Template

Builds an **infographic** from a table: a poster, a scorecard, a ranked
league table, a set of KPI cards — laid out the way you want rather than the
way a chart library wants. It is the sibling of **SVG Template**, and the
difference is the one that matters: an SVG Template is one drawing bound to
one row, and this **repeats a block for every row** and lays the blocks out.

It draws something the moment you wire a table in. Pick a **Layout**, and
the node writes the template for you; the four built-ins are worked examples
of the very markup you would write yourself, so the fastest way to learn the
grammar is to pick one and then paste it into the **Template** box to take
it over. Anything in that box wins over the layout.

**Tokens** are the same as SVG Template's, so learning one teaches the
other:

    {{region}}              a value
    {{revenue:$,.0f}}       formatted — any Python format spec, with a
                            currency symbol allowed in front
    {{{html_column}}}       triple braces insert markup **raw**; double
                            braces escape it, which is the default

**{{#each}} … {{/each}}** repeats its body once per row — this is what makes
it a builder rather than a drawing. Inside it, a bare name is that row's
value, and a few extras describe where you are in the run:

    {{_n}}       1, 2, 3 …          {{_index}}   0, 1, 2 …
    {{_count}}   how many rows      {{_color}}   the next palette colour
    {{_ci}}      that colour's number, for the `c3` / `bg3` classes

**{{#if name}} … {{#else}} … {{/if}}** keeps its body only when the value is
there and not zero, blank or false — a badge that appears only when there is
something to badge. A comparison asks something sharper, with the same
operators Table Style's rules use (`>`, `>=`, `<`, `<=`, `=`, `!=`,
`contains`), and conditions may nest:

    {{#if growth > 0}}<span class="chip up">▲ {{growth:.1f}}%</span>
    {{#else}}<span class="muted down">▼ {{growth:.1f}}%</span>{{/if}}

**Bindings** are `name = expression`, one per line, and are where the
arithmetic lives, so the tokens stay a simple lookup:

    total  = sum(revenue)      # over the whole column: sum, mean, min, max,
    best   = max(revenue)      # median, count, first, last
    share  = share(revenue)    # per row, 0-100: this row's cut of the total
    width  = pct(revenue)      # per row, 0-100: against the biggest row
    place  = rank(revenue)     # per row: 1 is the largest
    title  = Q3 by region      # a literal
    money  = revenue           # another name for a column

**Styling.** The page is built from a small set of class names — `sheet`,
`grid`, `row`, `stack`, `split`, `card`, `title`, `subtitle`, `label`,
`big`, `huge`, `muted`, `accent`, `mono`, `num`, `chip`, `track` + `bar`,
`dot`, `rule`, `up`, `down`, `good`, `warn`, `bad`, `right`, `center`,
`flat`, and `c1`…`c8` / `bg1`…`bg8` for palette colours. `up`/`down` colour
text and `good`/`warn`/`bad` fill a chip — those five stay green/amber/red
whichever palette is set, because "at risk" is not a palette decision. They
read their colours, type, spacing and
corner radius from a **Visual Style** node on the `style` input, so one node
can set the look of every template on the board. With nothing wired in they
use the house style, which matches the built-in web visuals. **Extra CSS**
is appended last, so anything you write there wins.

There is a margin around the whole page — Visual Style's **Padding** — so a
visual never sits hard against the edge of its card, its dashboard tile or
its place in a report. For a design that bleeds to the edge, put
`body{padding:0}` in Extra CSS.

A data bar is a `track` holding a `bar` whose length is a `--v` between 0
and 100:

    <div class="track"><div class="bar" style="--v:{{width:.0f}}"></div></div>

**Clicking.** With **On click** set, every repeated block becomes clickable
and writes the label it was built from back to this node, exactly as a
Slicer tick does: the **table** output narrows to the rows you picked and
everything downstream re-runs. Leave it off and the page carries no
JavaScript at all.

**Rows are drawn in the order they arrive** — sort upstream if the order
matters. A `rank()` binding numbers them by value, but it does not move
them, so a league table wants a Sort node in front of it.

**Size the card to the content.** An infographic is as tall as what it
says, and the card's box is what a dashboard tile and a report print — so
anything below the bottom edge is cut off there even though the card itself
scrolls. Drag the card until it all shows (or give the report embed a
`height=`). The page cannot do this for itself: a page being printed for a
report is laid out in a view that reports **zero** for its own width and
height, so there is nothing for it to fit *to*.

**It travels.** Nothing is fetched — no font link, no script, no stylesheet
— so what you see on the card is what lands in a dashboard tile, what prints
into a report, and what a colleague sees when you send them the file from
**Save View as HTML…**.
"""
NODE = {
    "label": "HTML Template",
    "category": "Viz",
    "version": "1.0",
    "card": "webview",
    "interactive": True,
    "inputs": [("data", "dataframe", {"optional": True}),
               ("style", "object", {"optional": True})],
    "outputs": [("html", "string"), ("table", "dataframe"),
                ("selected", "any"), ("style", "object")],
}

_LAYOUTS = ("cards", "bars", "kpi strip", "big number")

PARAMS = [
    {"name": "more", "type": "bool", "label": "More options",
     "default": False, "cosmetic": True},

    {"name": "layout", "type": "choice", "label": "Layout",
     "options": list(_LAYOUTS), "default": "cards"},
    {"name": "title", "type": "string", "label": "Title", "default": "",
     "placeholder": "heading across the top"},
    {"name": "subtitle", "type": "string", "label": "Subtitle",
     "default": "", "placeholder": "a line under the heading"},
    {"name": "label_column", "type": "columns", "label": "Label column",
     "multi": False, "default": "",
     "placeholder": "(the first text column)"},
    {"name": "value_column", "type": "columns", "label": "Value column",
     "multi": False, "default": "",
     "placeholder": "(the first number column)"},
    {"name": "value_format", "type": "string", "label": "Value format",
     "default": ",.0f", "placeholder": "$,.0f   .1%   ,.2f"},
    {"name": "columns", "type": "int", "label": "Columns across",
     "default": 3, "min": 1, "max": 12},

    {"name": "on_click", "type": "choice", "label": "On click",
     "options": ["nothing", "select one", "select many"],
     "default": "nothing"},
    # What the page writes through flograph.select(). Visible rather than
    # hidden: when a click isn't filtering what you expect, the first
    # question is what it actually sent, and this is the answer.
    {"name": "selected", "type": "string", "label": "Selected values",
     "default": "", "placeholder": 'written by a click, e.g. ["north"]'},

    {"name": "template", "type": "text", "label": "Template", "default": "",
     "placeholder": "leave blank to use the Layout above — or paste one in "
                    "and change it"},
    {"name": "bindings", "type": "text", "label": "Bindings", "default": "",
     "placeholder": "total = sum(revenue)\nwidth = pct(revenue)"},
    {"name": "css", "type": "text", "label": "Extra CSS", "default": "",
     "placeholder": ".card{border-left:4px solid var(--accent)}"},

    {"name": "rows", "type": "int", "label": "Rows shown", "default": 0,
     "min": 0, "max": 5000, "visible_when": {"more": ["True"]}},
    {"name": "row", "type": "int", "label": "Row", "default": 0, "min": 0,
     "max": 1_000_000, "visible_when": {"more": ["True"]}},
    {"name": "missing", "type": "choice", "label": "Missing token",
     "options": ["leave as-is", "blank", "error"], "default": "leave as-is",
     "visible_when": {"more": ["True"]}},

    {"name": "width", "type": "int", "label": "Width", "default": 460,
     "min": 260, "max": 4000, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height", "default": 340,
     "min": 200, "max": 4000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %", "default": 100,
     "min": 25, "max": 400, "cosmetic": True},
]

# The built-in layouts. These are the documentation as much as the default:
# every one of them is valid in the Template box, so "pick a layout, then
# paste it in and change it" is a real path rather than advice.
_HEADING = ("{{#if _title}}<div class=\"stack\">"
            "<h1 class=\"title\">{{_title}}</h1>"
            "{{#if _subtitle}}<p class=\"subtitle\">{{_subtitle}}</p>"
            "{{/if}}</div>{{/if}}")

_BODIES = {
    "cards": _HEADING + """
<div class="grid">
{{#each}}
  <div class="card stack{{{_state}}}"{{{_click}}}>
    <div class="label">{{_label}}</div>
    {{#if _has_value}}
    <div class="big" style="color:{{_color}}">{{_value}}</div>
    <div class="track">
      <div class="bar" style="--v:{{_pct:.0f}};background:{{_color}}"></div>
    </div>
    <div class="muted">{{_share:.1f}}% of {{_unit}}</div>
    {{/if}}
  </div>
{{/each}}
</div>
""",
    "bars": _HEADING + """
<div class="card stack">
{{#each}}
  <div class="stack{{{_state}}}"{{{_click}}}>
    <div class="split">
      <span>{{_label}}</span>
      <span class="num" style="color:{{_color}}">{{_value}}</span>
    </div>
    <div class="track">
      <div class="bar" style="--v:{{_pct:.0f}};background:{{_color}}"></div>
    </div>
  </div>
{{/each}}
</div>
""",
    "kpi strip": _HEADING + """
<div class="row">
{{#each}}
  <div class="card stack center{{{_state}}}"{{{_click}}}>
    <div class="label">{{_label}}</div>
    <div class="huge" style="color:{{_color}}">{{_value}}</div>
  </div>
{{/each}}
</div>
""",
    "big number": _HEADING + """
<div class="card stack center">
  <div class="label">{{_label}}</div>
  <div class="huge accent">{{_value}}</div>
  <div class="muted">{{_share:.1f}}% of {{_total}} across
    {{_count}} row(s)</div>
</div>
""",
}

# Every layout sits in a `sheet`, which is what puts a margin around the
# whole thing and a gap between the heading and the blocks. Without it a
# built-in layout runs hard against the edge of its card while a
# hand-written template (which nearly always starts with a sheet) breathes —
# the two looking different was the giveaway.
_TEMPLATES = {name: '<div class="sheet">' + body + "</div>"
              for name, body in _BODIES.items()}

_CLICK_JS = """
<script>
var PICKED = /*PICKED*/;
var MODE = /*MODE*/;
function pick(name) {
  if (MODE === "nothing") { return; }
  if (MODE === "select many") {
    var at = PICKED.indexOf(name);
    if (at === -1) { PICKED.push(name); } else { PICKED.splice(at, 1); }
  } else {
    PICKED = (PICKED.length === 1 && PICKED[0] === name) ? [] : [name];
  }
  // Guarded, because the same page is meant to survive being saved out and
  // opened somewhere with no flograph behind it. There, a click does
  // nothing rather than throwing.
  if (window.flograph && flograph.select) { flograph.select(PICKED); }
}
</script>
"""


def _pick_columns(rows, params):
    """Which column is the name and which is the number.

    Named settings win; otherwise the first text-ish column is the label and
    the first numeric one is the value. Auto-detection is a convenience for
    dropping the node on a table and seeing something — both are one click
    to override, and the log says what it chose.
    """
    from flograph.core.infographic import to_number

    names = list(rows[0].keys()) if rows else []
    label = str(params.get("label_column", "") or "").strip()
    value = str(params.get("value_column", "") or "").strip()
    if label and label not in names and names:
        raise ValueError(f"Label column {label!r} is not in the table "
                         f"(has: {', '.join(names)})")
    if value and value not in names and names:
        raise ValueError(f"Value column {value!r} is not in the table "
                         f"(has: {', '.join(names)})")

    def numeric(name):
        seen = [to_number(row.get(name)) for row in rows[:40]]
        known = [v for v in seen if v is not None]
        return len(known) >= max(1, len(seen) // 2)

    if not value:
        value = next((n for n in names if n != label and numeric(n)), "")
    if not label:
        label = next((n for n in names if n != value and not numeric(n)),
                     next((n for n in names if n != value), ""))
    return label, value


def run(ctx, data=None, style=None):
    import json

    import pandas as pd

    from flograph.core import infographic, visual_style
    from flograph.core.controls import selected_values

    params = ctx.params
    rows = infographic.rows_from_frame(data)
    limit = int(params.get("rows", 0) or 0)
    shown = rows[:limit] if limit > 0 else rows

    label_column, value_column = _pick_columns(shown, params)
    value_format = str(params.get("value_format", "") or "")

    picked = selected_values(params.get("selected", ""))
    mode = str(params.get("on_click", "nothing") or "nothing")
    if mode == "nothing":
        picked = []

    # Everything the built-in layouts read, computed once and handed to the
    # engine as ordinary values — so a template somebody writes themselves
    # can use exactly the same names.
    pcts = (infographic.per_row("pct", shown, value_column)
            if value_column else [0.0] * len(shown))
    shares = (infographic.per_row("share", shown, value_column)
              if value_column else [0.0] * len(shown))
    ranks = (infographic.per_row("rank", shown, value_column)
             if value_column else list(range(1, len(shown) + 1)))

    for index, row in enumerate(shown):
        raw_label = row.get(label_column) if label_column else None
        name = "" if raw_label is None else str(raw_label)
        raw_value = row.get(value_column) if value_column else None
        row["_label"] = name
        row["_raw"] = raw_value
        row["_value"] = infographic.format_value(raw_value, value_format)
        row["_has_value"] = infographic.to_number(raw_value) is not None
        row["_pct"] = pcts[index] if pcts[index] is not None else 0.0
        row["_share"] = shares[index] if shares[index] is not None else 0.0
        row["_rank"] = ranks[index]
        row["_picked"] = name in picked
        row["_click"] = (f" onclick=\"pick({infographic.escape(json.dumps(name))})\""
                         if mode != "nothing" else "")
        row["_state"] = (" pick" if mode != "nothing" else "") + (
            " picked" if row["_picked"] else
            " dim" if picked and mode != "nothing" else "")

    total = (infographic.aggregate("sum", [r.get("_raw") for r in shown])
             if value_column else None)
    page_values = {
        "_title": str(params.get("title", "") or ""),
        "_subtitle": str(params.get("subtitle", "") or ""),
        "_unit": value_column or "rows",
        "_dimension": label_column or "",
        "_total": infographic.format_value(total, value_format),
        "_max": infographic.format_value(
            infographic.aggregate("max", [r.get("_raw") for r in shown]),
            value_format),
        "_avg": infographic.format_value(
            infographic.aggregate("mean", [r.get("_raw") for r in shown]),
            value_format),
    }

    template = str(params.get("template", "") or "")
    layout = str(params.get("layout", "cards") or "cards")
    if template.strip():
        ctx.log("using the Template box (the Layout setting is ignored)")
    else:
        if layout not in _TEMPLATES:
            raise ValueError(f"unknown layout {layout!r} — one of: "
                             + ", ".join(_LAYOUTS))
        template = _TEMPLATES[layout]

    merged_style = visual_style.merge_styles(
        style if visual_style.is_style(style) else None, None)
    tok = visual_style.tokens(merged_style)

    body, unresolved = infographic.render(
        template, shown,
        bindings=params.get("bindings", ""),
        missing=str(params.get("missing", "leave as-is")),
        row=int(params.get("row", 0) or 0),
        palette=tok["palette"],
        values=page_values)

    if mode != "nothing":
        body += (_CLICK_JS
                 .replace("/*PICKED*/", json.dumps(picked))
                 .replace("/*MODE*/", json.dumps(mode)))

    across = max(1, min(12, int(params.get("columns", 3) or 3)))
    extra_css = f":root{{--cols:{across}}}\n" + str(params.get("css", "") or "")
    html = visual_style.page(body, tok, title=page_values["_title"],
                             extra_css=extra_css)

    if unresolved:
        ctx.log(f"left {len(set(unresolved))} token(s) unresolved: "
                f"{', '.join(sorted(set(unresolved)))}")
    ctx.log(f"{len(shown)} block(s) from {label_column or '(no label)'}"
            + (f" x {value_column}" if value_column else "")
            + f", {tok['theme']} theme")

    filtered = data if data is not None else pd.DataFrame()
    # `label_column` came back as text (a row dict's keys are strings), so a
    # frame with non-string column names would not answer to it.
    if (picked and data is not None and len(data)
            and label_column in data.columns):
        keep = data[label_column].astype(str).str.strip().isin(set(picked))
        filtered = data[keep]
        ctx.log(f"clicked {', '.join(picked)}: kept {len(filtered)} of "
                f"{len(data)} rows")

    return {"html": html, "table": filtered, "selected": picked,
            "style": merged_style}
