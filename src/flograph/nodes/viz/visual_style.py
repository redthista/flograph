"""Visual Style

Decides how a page **looks**, in one place, and emits it on the **style**
output. Wire that into one or more **HTML Template** nodes and they all
share a theme, a palette, a typeface and a spacing rhythm — change it here
and every one of them changes.

It is the sibling of **Table Style**, and the split is the same one: the
template decides what the page says, this decides how it looks.

**Every box is blank and every dropdown says *inherit*, which means "leave
it alone".** A Visual Style node only changes what you actually set, so it
is safe to drop one in front of a template that already looks right. What
nobody sets falls through to the house defaults — the same dark ground,
light text and mixed accent colours the built-in web visuals use, so a
template with no style wired in already matches the rest of the board.

**Theme** picks the colour base, `dark` or `light`, and the individual
colours land on top of it — so "light, but with my accent" is two settings
rather than seven. **Palette** is the ordered run of accent colours a
template walks through with `{{_color}}`, one per repeated block; **Colours**
overrides it with your own list (`#0ea5e9, #f43f5e, …`, commas or one per
line) for a brand set.

Colours are a `#hex` or a friendly name — `green`, `red`, `amber`, `blue`,
`grey`, `purple`, `teal`, `pink`, `lime`, `cyan`, `orange`. Anything else is
reported rather than passed through, because an unrecognised colour reaching
CSS is invisible: the browser drops the line and the element inherits
something that looks deliberate.

**Sizes are plain numbers in pixels** — leave one blank to inherit it.
`Base size` scales most of the page with it, since headings, labels and big
numbers are all multiples of it.

**Stacking styles.** The **style** input takes another Visual Style's
output as a base, and this node's settings override it. That is how a
house style lives in one node and a single board departs from it in one
respect — wire the house node in, set the one thing that differs.

There is no card: a style has nothing to show on its own, and the template
it feeds is the preview.
"""
NODE = {
    "label": "Visual Style",
    "category": "Viz",
    "version": "1.0",
    "inputs": [("style", "object", {"optional": True})],
    "outputs": [("style", "object")],
}

_KEEP = "inherit"

PARAMS = [
    {"name": "theme", "type": "choice", "label": "Theme",
     "options": [_KEEP, "dark", "light"], "default": _KEEP},
    {"name": "palette", "type": "choice", "label": "Palette",
     "options": [_KEEP, "mixed", "cool", "warm", "vivid", "earth", "grey"],
     "default": _KEEP},
    {"name": "colors", "type": "text", "label": "Colours", "default": "",
     "placeholder": "#0ea5e9, #f43f5e, #f59e0b   (overrides Palette)"},

    {"name": "accent", "type": "string", "label": "Accent", "default": "",
     "placeholder": "(inherit)"},
    {"name": "bg", "type": "string", "label": "Page background",
     "default": "", "placeholder": "(inherit)"},
    {"name": "surface", "type": "string", "label": "Card background",
     "default": "", "placeholder": "(inherit)"},
    {"name": "fg", "type": "string", "label": "Text", "default": "",
     "placeholder": "(inherit)"},
    {"name": "muted", "type": "string", "label": "Muted text",
     "default": "", "placeholder": "(inherit)"},
    {"name": "border", "type": "string", "label": "Border", "default": "",
     "placeholder": "(inherit)"},

    {"name": "font", "type": "string", "label": "Font", "default": "",
     "placeholder": "(inherit) — a CSS font stack, installed on the machine"},
    {"name": "heading_font", "type": "string", "label": "Heading font",
     "default": "", "placeholder": "(inherit — same as Font)"},
    {"name": "size", "type": "string", "label": "Base size", "default": "",
     "placeholder": "(inherit) — px, most of the page scales with it"},
    {"name": "heading_size", "type": "string", "label": "Heading size",
     "default": "", "placeholder": "(inherit) — px"},
    {"name": "heading_weight", "type": "string", "label": "Heading weight",
     "default": "", "placeholder": "(inherit) — 100 to 900"},

    {"name": "radius", "type": "string", "label": "Corner radius",
     "default": "", "placeholder": "(inherit) — px, 0 for square"},
    {"name": "gap", "type": "string", "label": "Gap", "default": "",
     "placeholder": "(inherit) — px between blocks"},
    {"name": "pad", "type": "string", "label": "Padding", "default": "",
     "placeholder": "(inherit) — px inside a card"},
    {"name": "shadow", "type": "choice", "label": "Card shadow",
     "options": [_KEEP, "on", "off"], "default": _KEEP},
]

def run(ctx, style=None):
    from flograph.core.visual_style import merge_styles, style_payload, tokens

    params = dict(ctx.params)
    # "inherit" is this node's word for unset; the core module knows "keep".
    for name in ("theme", "palette", "shadow"):
        if str(params.get(name, "")).strip().lower() == _KEEP:
            params[name] = ""

    own = style_payload(params)
    for message in own["errors"]:
        ctx.log(f"ignored: {message}")

    merged = merge_styles(style if isinstance(style, dict) else None, own)
    settings = merged["tokens"]
    resolved = tokens(merged)

    if settings:
        ctx.log(f"{len(settings)} setting(s): "
                + ", ".join(sorted(settings)))
    else:
        ctx.log("nothing set — the house style passes through unchanged")
    ctx.log(f"{resolved['theme']} theme, "
            f"{len(resolved['palette'])} palette colour(s)")
    return {"style": merged}
