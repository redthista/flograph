"""Slider

Drag a value along a track and everything downstream re-runs with it — a
threshold for a filter, a bin count for a histogram, a top-N cutoff.

Set "Decimals" above 0 for a float slider; at 0 it emits whole numbers.
"Step" is the size of one notch, so a 0–1 slider with step 0.05 and 2
decimals gives you twenty stops.

**Bounds from your data.** Wire a number column into "minimum" and
"maximum" and the track covers exactly the range your data spans, instead
of limits somebody typed once and forgot. Either port on its own works; a
column is reduced to its lowest value for "minimum" and its highest for
"maximum". The position stays yours — it is only pulled inside the range
when the range moves, which is what makes an untouched slider start
somewhere sensible.

Drop it on a dashboard page and it comes with it: the person reading the
dashboard moves the slider, the charts follow, and they never see the model.
"""
NODE = {
    "label": "Slider",
    "category": "Input",
    "version": "1.0",
    "card": "control",
    "control": "slider",
    "inputs": [("minimum", "any", {"optional": True}),
               ("maximum", "any", {"optional": True})],
    "outputs": [("value", "number")],
}
PARAMS = [
    {"name": "caption", "type": "string", "label": "Caption",
     "default": "", "placeholder": "Shown above the slider"},
    {"name": "value", "type": "float", "label": "Value", "default": 50.0},
    {"name": "minimum", "type": "float", "label": "Minimum", "default": 0.0},
    {"name": "maximum", "type": "float", "label": "Maximum", "default": 100.0},
    {"name": "step", "type": "float", "label": "Step", "default": 1.0},
    {"name": "decimals", "type": "int", "label": "Decimals",
     "default": 0, "min": 0, "max": 6},
    {"name": "width", "type": "int", "label": "Width",
     "default": 240, "min": 140, "max": 600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 96, "min": 60, "max": 400, "cosmetic": True},
]


def run(ctx, minimum=None, maximum=None):
    from flograph.core.controls import as_number, clamp, reduce_bound

    decimals = int(ctx.params.get("decimals", 0) or 0)
    low = as_number(reduce_bound(minimum, high=False),
                    as_number(ctx.params.get("minimum"), 0.0))
    high = as_number(reduce_bound(maximum, high=True),
                     as_number(ctx.params.get("maximum"), 100.0))
    value = clamp(as_number(ctx.params.get("value"), low), low, high)
    return {"value": round(value, decimals) if decimals else int(round(value))}
