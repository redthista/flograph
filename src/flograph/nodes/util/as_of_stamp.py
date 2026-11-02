"""As-of Stamp

"As of 09:41 today" under a live figure, so nobody acts on stale numbers.

Wire the node whose freshness matters into **trigger** — the read or query
at the top of the flow. The stamp is the moment this node last ran, and it
only runs when that upstream node does, so it moves when the data does and
stays put when nothing changed.

**Format** is how the time is written (`%H:%M` is 09:41, `%d %b %Y` is
25 Oct 2026). A format without the date gets "today", "yesterday" or the
date added, kept true by the card as the days go by.
**Stale after** turns the card amber once that many minutes have gone by
with no refresh, worked out by the card itself as time passes — 0 never.

**text** is the line on its own and **timestamp** the moment in ISO form
(`2026-10-25T09:41:07`), for a Report or a Write Text.
"""
NODE = {
    "label": "As-of Stamp",
    "category": "Util",
    "version": "1.0",
    "card": "webview",
    "inputs": [("trigger", "any", {"optional": True}),
               ("style", "object",
                {"optional": True, "suggest": ["flograph.viz.visual_style"]})],
    "outputs": [("html", "string"), ("text", "string"),
                ("timestamp", "string")],
}
PARAMS = [
    {"name": "prefix", "type": "string", "label": "Prefix",
     "default": "As of"},
    {"name": "format", "type": "string", "label": "Format",
     "default": "%H:%M", "placeholder": "%H:%M  ·  %d %b %Y %H:%M"},
    {"name": "stale_minutes", "type": "int", "label": "Stale after (min)",
     "default": 0, "min": 0, "max": 525600},
    {"name": "width", "type": "int", "label": "Width",
     "default": 220, "min": 120, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 60, "min": 40, "max": 600, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %", "default": 100,
     "min": 25, "max": 400, "cosmetic": True},
]

_CSS = """
.stamp { color: var(--muted); font-size: max(11px, 14vmin); }
.stamp.stale { color: #f59e0b; }
.stamp.stale::after { content: " — out of date"; }
"""


#: strftime codes that already write the date, so no "today" is added
_DATE_CODES = ("%d", "%x", "%c", "%j", "%F", "%D", "%e")


def run(ctx, trigger=None, style=None):
    import datetime as dt
    import json

    from flograph.core import status_cards as sc
    from flograph.core.svgplot import escape

    p = ctx.params
    fmt = str(p["format"]) or "%H:%M"
    now = dt.datetime.now().replace(microsecond=0)
    try:
        base = f"{p['prefix']} {now.strftime(fmt)}".strip()
    except ValueError as exc:
        raise ValueError(f"'Format' isn't a valid time format: {exc}") from exc
    dated = any(code in fmt for code in _DATE_CODES)
    text = base if dated else f"{base} today"
    stamp = now.isoformat()
    minutes = int(p["stale_minutes"])
    # The card reads the clock itself, every half-minute: a project saved
    # today and opened tomorrow must say "yesterday", not the "today" that
    # was true when it ran — and a stale stamp goes amber with nothing
    # re-running. The node's own `text` output is true when it is made.
    script = (
        "<script>(function(){var at=new Date(" + json.dumps(stamp) + "),"
        "lim=" + str(minutes * 60000) + ",dated=" + json.dumps(dated) + ","
        "base=" + json.dumps(base) + ",el=document.getElementById('s');"
        "function day(d){return new Date(d.getFullYear(),d.getMonth(),"
        "d.getDate())}"
        "function tick(){var now=new Date();if(!dated){"
        "var gap=Math.round((day(now)-day(at))/864e5);"
        "el.textContent=base+(gap===0?' today':gap===1?' yesterday':' '+"
        "at.toLocaleDateString(undefined,{day:'numeric',month:'short',"
        "year:'numeric'}))}"
        "if(lim)el.classList.toggle('stale',now-at>lim)}"
        "tick();setInterval(tick,30000)})();</script>")
    body = (f"<div class='card'><div id='s' class='stamp' "
            f"title='{escape(stamp)}'>{escape(text)}</div></div>{script}")
    html, _ = sc.page(body, style, title=text, extra_css=_CSS)
    ctx.log(text)
    return {"html": html, "text": text, "timestamp": stamp}
