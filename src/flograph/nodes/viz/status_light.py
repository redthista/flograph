"""Status Light

A traffic light for one number: green, amber or red against two
breakpoints, so a whole page of them can be scanned in a second — red means
someone needs to act.

Wire the number into **value**. Set **Amber at** and **Red at**, and say
which way is bad in **Direction**: *higher is worse* for debt, days overdue
or error rate (at or past Red at is red); *lower is worse* for cash runway,
uptime or stock cover (at or below Red at is red). Set both to the same
number for just green and red.

**status** is the colour as a word — `green`, `amber`, `red` — for an
Expression or a Notify to branch on.
"""
NODE = {
    "label": "Status Light",
    "category": "Viz",
    "version": "1.0",
    "card": "webview",
    "inputs": [("value", "any"),
               ("style", "object",
                {"optional": True, "suggest": ["flograph.viz.visual_style"]})],
    "outputs": [("html", "string"), ("status", "string")],
}
PARAMS = [
    {"name": "label", "type": "string", "label": "Label", "default": "",
     "placeholder": "e.g. Cash runway (days)"},
    {"name": "direction", "type": "choice", "label": "Direction",
     "options": ["higher is worse", "lower is worse"],
     "default": "higher is worse"},
    {"name": "amber", "type": "float", "label": "Amber at", "default": 50.0},
    {"name": "red", "type": "float", "label": "Red at", "default": 80.0},
    {"name": "format", "type": "string", "label": "Format", "default": "",
     "placeholder": "Python format spec, e.g. ,.0f"},
    {"name": "show_value", "type": "bool", "label": "Show the number",
     "default": True},
    {"name": "width", "type": "int", "label": "Width",
     "default": 220, "min": 120, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 110, "min": 70, "max": 1000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %", "default": 100,
     "min": 25, "max": 400, "cosmetic": True},
]

_WORDS = {"good": "green", "watch": "amber", "bad": "red",
          "neutral": "unknown"}

_CSS = """
.lamp-row { display: flex; align-items: center; gap: 4vmin; }
.lamp { flex: none; width: 30vmin; height: 30vmin; min-width: 22px;
  min-height: 22px; border-radius: 50%; }
.lamp-text { min-width: 0; display: flex; flex-direction: column; gap: .2em; }
.lamp-text .big { font-size: max(18px, 14vmin); }
"""


def run(ctx, value, style=None):
    from flograph.core import status_cards as sc
    from flograph.core.infographic import format_value
    from flograph.core.svgplot import escape

    p = ctx.params
    number = sc.to_float(value)
    worse_up = p["direction"] == "higher is worse"
    amber, red = float(p["amber"]), float(p["red"])
    if worse_up and amber > red or not worse_up and amber < red:
        raise ValueError(
            f"with '{p['direction']}', Amber at ({amber:g}) should come "
            f"before Red at ({red:g}) — swap them, or change Direction")
    tone = sc.lamp_tone(number, amber, red, worse_up)
    tok = sc.tokens(style)
    colour = sc.tone_colour(tone, tok) if tone != "neutral" else tok["muted"]
    label = str(p["label"])
    shown = format_value(number, p["format"]) if number is not None else "—"
    glow = f"box-shadow:0 0 6vmin {colour}88"
    body = ("<div class='card'><div class='lamp-row'>"
            f"<div class='lamp' style='background:{colour};{glow}' "
            f"role='img' aria-label='{_WORDS[tone]}'></div>"
            "<div class='lamp-text'>"
            + (f"<div class='label'>{escape(label)}</div>" if label else "")
            + (f"<div class='big'>{escape(shown)}</div>"
               if p["show_value"] else "")
            + "</div></div></div>")
    html, _ = sc.page(body, style, title=label or "Status", extra_css=_CSS)
    ctx.log(f"{shown} -> {_WORDS[tone]}")
    return {"html": html, "status": _WORDS[tone]}
