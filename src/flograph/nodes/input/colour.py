"""Colour

A colour picker — a swatch to click for the full picker, and an optional row
of preset swatches for the colours you want people to choose between. The
value flows downstream as "#rrggbb".

Most useful as a variable: name it (Behaviour ▸ Variable name, say
`highlight`) and write `${highlight}` into a chart's colour setting, or bind
a style node's colour to it, and whoever reads the dashboard picks the
colour.

"Swatches" lists preset colours, separated by commas or one per line:
`#2563eb, #16a34a, #dc2626`.
"""
NODE = {
    "label": "Colour",
    "category": "Input",
    "version": "1.0",
    "card": "control",
    "control": "colour",
    "inputs": [],
    "outputs": [("value", "string")],
}
PARAMS = [
    {"name": "caption", "type": "string", "label": "Caption",
     "default": "", "placeholder": "Shown above the swatch"},
    {"name": "value", "type": "color", "label": "Colour", "default": "#3b82f6"},
    {"name": "swatches", "type": "text", "label": "Swatches",
     "default": "", "placeholder": "#2563eb, #16a34a, #dc2626",
     "cosmetic": True},
    {"name": "width", "type": "int", "label": "Width",
     "default": 200, "min": 120, "max": 800, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 104, "min": 56, "max": 600, "cosmetic": True},
]


def run(ctx):
    from flograph.core.controls import colour_value

    return {"value": colour_value(ctx.params.get("value"))}
