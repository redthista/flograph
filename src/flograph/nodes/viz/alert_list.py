"""Alert List

A "needs attention" tray: one line per row that arrives, tinted so it can't
be missed, and a calm "All clear" when nothing does.

Decide what counts as an alert *before* this node — a **Filter Rows**
(`days_overdue > 30`, `stock < reorder_level`) or a Data Quality Gate's
report — and wire what is left in. The tray is then exactly as clever as the
filter, and the rule lives in one place.

**Message** writes each line from the row's columns: `{invoice} for
{customer} is {days_overdue} days overdue`, with a format after a colon for
numbers — `{amount:$,.0f}`. Leave it blank to show the first few columns.
**Tone** colours the tray (red to act, amber to watch). **Most shown** caps
the lines, with "and N more" under them.

**count** is how many rows were alerts, for a Status Light or a Notify.
"""
NODE = {
    "label": "Alert List",
    "category": "Viz",
    "version": "1.0",
    "card": "webview",
    "inputs": [("table", "dataframe",
                {"suggest": ["flograph.transform.filter_rows"]}),
               ("style", "object",
                {"optional": True, "suggest": ["flograph.viz.visual_style"]})],
    "outputs": [("html", "string"), ("count", "number")],
}
PARAMS = [
    {"name": "title", "type": "string", "label": "Title",
     "default": "Needs attention"},
    {"name": "message", "type": "string", "label": "Message", "default": "",
     "placeholder": "{invoice} is {days_overdue} days overdue"},
    {"name": "tone", "type": "choice", "label": "Tone",
     "options": ["red", "amber", "neutral"], "default": "red"},
    {"name": "empty_text", "type": "string", "label": "When empty",
     "default": "All clear"},
    {"name": "max_rows", "type": "int", "label": "Most shown",
     "default": 20, "min": 1, "max": 1000},
    {"name": "width", "type": "int", "label": "Width",
     "default": 320, "min": 160, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 220, "min": 90, "max": 2000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %", "default": 100,
     "min": 25, "max": 400, "cosmetic": True},
]

_TONE = {"red": "bad", "amber": "watch", "neutral": "neutral"}

_CSS = """
.card { justify-content: flex-start; }
.tray-title { font-weight: 700; display: flex; align-items: center;
  gap: .5em; }
.count { font-size: .8em; padding: .05em .55em; border-radius: 99px;
  color: #fff; }
ul { list-style: none; margin: .3em 0 0; padding: 0; overflow: auto;
  display: flex; flex-direction: column; gap: .3em;
  scrollbar-width: thin; scrollbar-color: var(--border) transparent; }
ul::-webkit-scrollbar { width: 6px; }
ul::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
li { padding: .35em .6em; border-radius: calc(var(--radius) / 2);
  border-left: 3px solid var(--tone);
  background: color-mix(in srgb, var(--tone) 14%, transparent); }
.clear { color: var(--muted); padding: .4em 0; }
.more { color: var(--muted); font-size: .85em; }
"""


def _line(template, row, columns):
    """One alert's text. Each `{column:spec}` is written by the same
    formatter as the other cards (so `$,.0f` works); a column that isn't
    there writes nothing, so a half-typed message still draws."""
    import string

    from flograph.core.infographic import format_value

    if not template:
        return " · ".join(f"{row[c]}" for c in columns[:3]
                          if row.get(c) is not None)
    try:
        parts = list(string.Formatter().parse(template))
    except ValueError:              # an unclosed brace: show it as typed
        return template
    out = []
    for literal, field, spec, _ in parts:
        out.append(literal)
        if field is not None:
            out.append(format_value(row.get(field), spec or ""))
    return "".join(out)


def run(ctx, table, style=None):
    from flograph.core import status_cards as sc
    from flograph.core.svgplot import escape

    p = ctx.params
    tok = sc.tokens(style)
    tone = _TONE[p["tone"]]
    colour = sc.tone_colour(tone, tok) if tone != "neutral" else tok["accent"]
    count = len(table)
    limit = int(p["max_rows"])
    columns = [str(c) for c in table.columns]
    shown = table.head(limit).rename(columns=str).astype(object)
    # NaN, NA and NaT all write as nothing, never as "nan" or "<NA>"
    records = shown.where(shown.notna(), None).to_dict("records")
    items = [f"<li>{escape(_line(p['message'], row, columns))}</li>"
             for row in records]

    title = escape(p["title"])
    head = (f"<div class='tray-title'>{title}"
            + (f"<span class='count' style='background:{colour}'>{count}"
               "</span>" if count else "")
            + "</div>")
    if items:
        more = count - len(items)
        body = (head + "<ul>" + "".join(items) + "</ul>"
                + (f"<div class='more'>and {more} more</div>" if more else ""))
    else:
        body = (head + f"<div class='clear'>✓ {escape(p['empty_text'])}"
                "</div>")
    html, _ = sc.page(f"<div class='card' style='--tone:{colour}'>{body}"
                      "</div>", style, title=p["title"], extra_css=_CSS)
    ctx.log(f"{count} alert(s)" + (f", showing {len(items)}"
                                   if count > len(items) else ""))
    return {"html": html, "count": count}
