"""Number

A number box for values that want typing rather than dragging — a price, a
row limit, a tolerance. Same output as a Slider, different affordance: use
this when the range is wide or the exact figure matters.

"Prefix" and "Suffix" are display only (£, %, " days"); the value that flows
downstream is always the bare number. Set "Decimals" above 0 for a float.

Wire a number column into "minimum" or "maximum" to bound the box by what
your data actually contains rather than by typed-in limits; a column is
reduced to its lowest value for "minimum" and its highest for "maximum".
"""
NODE = {
    "label": "Number",
    "category": "Input",
    "card": "control",
    "control": "number",
    "inputs": [("minimum", "any", {"optional": True}),
               ("maximum", "any", {"optional": True})],
    "outputs": [("value", "number")],
}
PARAMS = [
    {"name": "caption", "type": "string", "label": "Caption",
     "default": "", "placeholder": "Shown above the box"},
    {"name": "value", "type": "float", "label": "Value", "default": 0.0},
    {"name": "minimum", "type": "float", "label": "Minimum",
     "default": -1000000.0},
    {"name": "maximum", "type": "float", "label": "Maximum",
     "default": 1000000.0},
    {"name": "step", "type": "float", "label": "Step", "default": 1.0},
    {"name": "decimals", "type": "int", "label": "Decimals",
     "default": 0, "min": 0, "max": 6},
    {"name": "prefix", "type": "string", "label": "Prefix",
     "default": "", "placeholder": "e.g. £ — display only"},
    {"name": "suffix", "type": "string", "label": "Suffix",
     "default": "", "placeholder": "e.g. % — display only"},
    {"name": "width", "type": "int", "label": "Width",
     "default": 200, "min": 120, "max": 600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 84, "min": 56, "max": 400},
]


def run(ctx, minimum=None, maximum=None):
    from flograph.core.controls import as_number, clamp, reduce_bound

    decimals = int(ctx.params.get("decimals", 0) or 0)
    low = as_number(reduce_bound(minimum, high=False),
                    as_number(ctx.params.get("minimum"), -1000000.0))
    high = as_number(reduce_bound(maximum, high=True),
                     as_number(ctx.params.get("maximum"), 1000000.0))
    value = clamp(as_number(ctx.params.get("value"), low), low, high)
    return {"value": round(value, decimals) if decimals else int(round(value))}
