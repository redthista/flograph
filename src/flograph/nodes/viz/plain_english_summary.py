"""Plain-English Summary

Turn a number and the one before it into a sentence — "Revenue $1.2M, up 9%
on last month" — so the dashboard writes its own headline.

Wire this period's number into **value** and the one to compare with into
**previous** (both optional to the extent the sentence doesn't use them).
**Sentence** is the wording, with blanks filled in:

* `{value}` and `{previous}` — written with **Number format**
* `{delta}` — the difference, with its sign
* `{change}` — the change as a percentage, without a sign
* `{direction}` — the **Up** / **Down** / **Flat** word for which way it went

A change smaller than **Flat within** (0.01 = 1%) reads as flat. **text** is
the sentence on its own — wire it into a Report card, a Notify message or a
chart title.
"""
NODE = {
    "label": "Plain-English Summary",
    "category": "Viz",
    "version": "1.0",
    "card": "webview",
    "inputs": [("value", "any", {"optional": True}),
               ("previous", "any", {"optional": True}),
               ("style", "object",
                {"optional": True, "suggest": ["flograph.viz.visual_style"]})],
    "outputs": [("html", "string"), ("text", "string")],
}
PARAMS = [
    {"name": "template", "type": "string", "label": "Sentence",
     "default": "{value}, {direction} {change} on last period",
     "placeholder": "Revenue {value}, {direction} {change} on last month"},
    {"name": "value_format", "type": "string", "label": "Number format",
     "default": ",.0f", "placeholder": "$,.0f"},
    {"name": "change_format", "type": "string", "label": "Change format",
     "default": ".0%"},
    {"name": "up_word", "type": "string", "label": "Up", "default": "up"},
    {"name": "down_word", "type": "string", "label": "Down",
     "default": "down"},
    {"name": "flat_word", "type": "string", "label": "Flat",
     "default": "flat"},
    {"name": "flat_band", "type": "float", "label": "Flat within",
     "default": 0.0, "min": 0.0, "max": 1.0},
    {"name": "colour_direction", "type": "bool", "label": "Colour the change",
     "default": True},
    {"name": "higher_is_better", "type": "bool", "label": "Higher is better",
     "default": True, "visible_when": {"colour_direction": ["True"]}},
    {"name": "width", "type": "int", "label": "Width",
     "default": 360, "min": 160, "max": 2000, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 90, "min": 50, "max": 1000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %", "default": 100,
     "min": 25, "max": 400, "cosmetic": True},
]

_CSS = """
.headline { font-size: max(14px, 9vmin); line-height: 1.3;
  font-family: var(--heading-font); font-weight: 600; }
"""


def _fill(template, fields):
    """`template` with each `{name}` replaced — unknown names are left as
    typed, so a half-written sentence still shows what it says."""
    out = template
    for name, text in fields.items():
        out = out.replace("{" + name + "}", text)
    return out


def run(ctx, value=None, previous=None, style=None):
    from flograph.core import status_cards as sc
    from flograph.core.infographic import format_value
    from flograph.core.svgplot import escape

    p = ctx.params
    now = sc.to_float(value) if value is not None else None
    before = sc.to_float(previous) if previous is not None else None
    template = str(p["template"])
    spec = str(p["value_format"])

    delta = change = None
    if now is not None and before is not None:
        delta = now - before
        change = delta / abs(before) if before else None
    band = float(p["flat_band"])
    if change is not None:
        moving = abs(change) > band
    else:
        moving = delta not in (None, 0)
    if delta is None or not moving:
        word, tone = p["flat_word"], "neutral"
    else:
        word = p["up_word"] if delta > 0 else p["down_word"]
        tone = sc.judge(delta, bool(p["higher_is_better"]))

    fields = {
        "value": format_value(now, spec) if now is not None else "",
        "previous": format_value(before, spec) if before is not None else "",
        "delta": ("+" if delta and delta > 0 else "")
        + format_value(delta, spec) if delta is not None else "",
        "change": format_value(abs(change), p["change_format"])
        if change is not None else "",
        "direction": word,
    }
    text = " ".join(_fill(template, fields).split())

    # colour the direction word and the change in the card, never in `text`
    shown = {k: escape(v) for k, v in fields.items()}
    if p["colour_direction"] and tone != "neutral":
        ink = sc.tone_colour(tone, sc.tokens(style))
        for key in ("direction", "change", "delta"):
            if shown[key]:
                shown[key] = f"<span style='color:{ink}'>{shown[key]}</span>"
    markup = _fill(escape(template), shown)
    html, _ = sc.page(f"<div class='card'><div class='headline'>{markup}"
                      "</div></div>", style, title=text, extra_css=_CSS)
    ctx.log(text)
    return {"html": html, "text": text}
