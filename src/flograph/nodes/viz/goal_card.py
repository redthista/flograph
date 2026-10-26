"""Goal Card

A big number measured against another one — "Sales £1.2M ▲ 12% vs last
year", or "Q3 quota 78%" as a filling bar — coloured green or red by
whether that's good.

Wire the number into **value** (a Card's value, a one-cell table, anything
that comes to one number). The thing to compare it with comes from the
**comparison** input, or from **Target** when nothing is wired there.

**Show**: *change* puts the difference under the number, as an arrow and a
percentage; *progress* draws a bar of how far the value has got towards the
target. **Higher is better** says which way is good: untick it for costs,
complaints and wait times. In *progress* the bar is amber from **Amber
from** (0.8 = 80% of the target) and green once the target is reached — or,
with Higher is better off, green while under budget, amber past Amber from,
red over.

**delta** (value − comparison) and **pct** (the change as a ratio for
*change*, the share of the target for *progress*) go on downstream.
"""
NODE = {
    "label": "Goal Card",
    "category": "Viz",
    "version": "1.0",
    "card": "webview",
    "inputs": [("value", "any"),
               ("comparison", "any", {"optional": True}),
               ("style", "object",
                {"optional": True, "suggest": ["flograph.viz.visual_style"]})],
    "outputs": [("html", "string"), ("delta", "number"), ("pct", "number")],
}
PARAMS = [
    {"name": "mode", "type": "choice", "label": "Show",
     "options": ["change", "progress"], "default": "change"},
    {"name": "label", "type": "string", "label": "Label", "default": "",
     "placeholder": "e.g. Sales"},
    {"name": "target", "type": "float", "label": "Target", "default": 0.0},
    {"name": "comparison_label", "type": "string", "label": "Compared with",
     "default": "", "placeholder": "e.g. last year, quota"},
    {"name": "format", "type": "string", "label": "Format", "default": "",
     "placeholder": "Python format spec, e.g. $,.0f"},
    {"name": "higher_is_better", "type": "bool", "label": "Higher is better",
     "default": True},
    {"name": "amber_at", "type": "float", "label": "Amber from",
     "default": 0.8, "min": 0.0, "max": 10.0,
     "visible_when": {"mode": ["progress"]}},
    {"name": "width", "type": "int", "label": "Width",
     "default": 240, "min": 140, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 140, "min": 90, "max": 1000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %", "default": 100,
     "min": 25, "max": 400, "cosmetic": True},
]


def run(ctx, value, comparison=None, style=None):
    from flograph.core import status_cards as sc
    from flograph.core.infographic import format_value
    from flograph.core.svgplot import escape

    p = ctx.params
    number = sc.to_float(value)
    if number is None:
        raise ValueError(f"'value' isn't a number: {value!r}")
    if comparison is not None:
        other = sc.to_float(comparison)
        if other is None:
            raise ValueError(f"'comparison' isn't a number: {comparison!r}")
    else:
        other = sc.to_float(p["target"])
    better_up = bool(p["higher_is_better"])
    spec = str(p["format"])
    delta = number - other
    against = str(p["comparison_label"]).strip()
    tok = sc.tokens(style)

    if p["mode"] == "progress":
        if not other:
            raise ValueError("progress needs a target that isn't 0 — set "
                             "'Target' or wire 'comparison'")
        pct = number / other
        amber = float(p["amber_at"])
        if better_up:
            tone = "good" if pct >= 1 else "watch" if pct >= amber else "bad"
        else:
            tone = "bad" if pct > 1 else "watch" if pct >= amber else "good"
        ink = sc.tone_colour(tone, tok)
        fill = max(0.0, min(1.0, pct)) * 100
        detail = (f"<div class='sub'><b style='color:{ink}'>{pct:.0%}</b>"
                  f"<span class='muted'> of {escape(format_value(other, spec))}"
                  + (f" {escape(against)}" if against else "")
                  + "</span></div>"
                  f"<div class='track'><div class='bar' style='--v:{fill:.1f};"
                  f"background:{ink}'></div></div>")
    else:
        pct = delta / abs(other) if other else float("nan")
        tone = sc.judge(delta, better_up)
        ink = sc.tone_colour(tone, tok)
        shown = f"{abs(pct):.1%}" if pct == pct else \
            format_value(abs(delta), spec)
        detail = (f"<div class='sub'><b style='color:{ink}'>"
                  f"{sc.arrow(delta)} {escape(shown)}</b>"
                  + (f"<span class='muted'> vs {escape(against)}</span>"
                     if against else "")
                  + "</div>")

    label = str(p["label"])
    body = ("<div class='card'>"
            + (f"<div class='label'>{escape(label)}</div>" if label else "")
            + f"<div class='big'>{escape(format_value(number, spec))}</div>"
            + detail + "</div>")
    html, _ = sc.page(body, style, title=label or "Goal")
    ctx.log(f"{number:g} vs {other:g}: delta {delta:+g}, "
            f"{'share' if p['mode'] == 'progress' else 'change'} "
            + (f"{pct:.1%}" if pct == pct else "n/a") + f" ({tone})")
    return {"html": html, "delta": delta, "pct": pct}
