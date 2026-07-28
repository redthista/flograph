"""Between

Two handles on one track: everything from the low one to the high one. Emits
the pair as separate `low` and `high` outputs, which is the shape a filter
wants — `df[df.price.between(low, high)]`, or a date window, or a top-and-
bottom cutoff.

Where a Slider gives you a threshold, this gives you a window. That is the
whole difference, and it is why the span between the handles is filled in:
the control should read as "this much of the range", not as two numbers that
happen to sit near each other.

Set "Decimals" above 0 for a float range; at 0 it emits whole numbers.
"Step" is the size of one notch, so a 0–1 range with step 0.05 and 2 decimals
gives you twenty stops per handle.

**Bounds from your data.** Wire a number column into "minimum" and "maximum"
and the track covers exactly the range your data spans, instead of limits
somebody typed once and forgot. Either port on its own works; a column is
reduced to its lowest value for "minimum" and its highest for "maximum". An
untouched Between spans its whole range, so wiring a column into both ports
gives you a window over exactly the data you have and nothing outside it.

Drag either handle past the other and they swap rather than jam, so a range
can always be reopened from wherever you grabbed it.

Drop it on a dashboard page and it comes with it: the person reading the
dashboard moves the handles, the charts follow, and they never see the model.
"""
NODE = {
    "label": "Between",
    "category": "Input",
    "card": "control",
    "control": "range",
    "inputs": [("minimum", "any", {"optional": True}),
               ("maximum", "any", {"optional": True})],
    "outputs": [("low", "number"), ("high", "number")],
}
PARAMS = [
    {"name": "caption", "type": "string", "label": "Caption",
     "default": "", "placeholder": "Shown above the slider"},
    # The pair travels as JSON in one param because the host writes exactly
    # one "value" for every control shape — the same arrangement a Slicer
    # uses for its ticked values. Blank means "never touched", which the
    # widget and run() both read as the full range.
    {"name": "value", "type": "string", "label": "Range",
     "default": "", "placeholder": "e.g. [10, 50] — or just drag the handles"},
    {"name": "minimum", "type": "float", "label": "Minimum", "default": 0.0},
    {"name": "maximum", "type": "float", "label": "Maximum", "default": 100.0},
    {"name": "step", "type": "float", "label": "Step", "default": 1.0},
    {"name": "decimals", "type": "int", "label": "Decimals",
     "default": 0, "min": 0, "max": 6},
    {"name": "width", "type": "int", "label": "Width",
     "default": 260, "min": 160, "max": 600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 96, "min": 60, "max": 400},
]


def run(ctx, minimum=None, maximum=None):
    from flograph.core.controls import (as_number, clamp, range_values,
                                        reduce_bound)

    decimals = int(ctx.params.get("decimals", 0) or 0)
    low_bound = as_number(reduce_bound(minimum, high=False),
                          as_number(ctx.params.get("minimum"), 0.0))
    high_bound = as_number(reduce_bound(maximum, high=True),
                           as_number(ctx.params.get("maximum"), 100.0))
    if high_bound < low_bound:
        high_bound = low_bound

    low, high = range_values(ctx.params.get("value"), low_bound, high_bound)
    # Clamped exactly as the widget clamps, so the card and the flow can
    # never disagree — the same rule that makes a wired bound double as a
    # sensible default for an untouched control.
    low = clamp(low, low_bound, high_bound)
    high = clamp(high, low_bound, high_bound)
    if high < low:
        low, high = high, low

    def emit(value):
        return round(value, decimals) if decimals else int(round(value))

    return {"low": emit(low), "high": emit(high)}
