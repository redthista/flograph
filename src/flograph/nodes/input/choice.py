"""Choice

A dropdown, for picking one of a known set — a region, a scenario, a metric.

The options come from whichever you give it:

* type them into "Options", one per line, for a fixed list; or
* wire something into the "options" input and they come from your data.
  A DataFrame contributes the unique values of the column named in "Column"
  (or its first column when that's blank), a Series its unique values, and a
  list its entries. That's what makes controls chain — a Slicer's selection
  can drive this dropdown's options, and this dropdown can drive the next
  thing along.

Options refresh on every run. A stored pick that is no longer offered stays
visible and marked "(not in list)" rather than silently changing to
something else underneath a dashboard. Nothing picked yet means the first
option — which is what the dropdown is showing.
"""
NODE = {
    "label": "Choice",
    "category": "Input",
    "version": "1.0",
    "card": "control",
    "control": "choice",
    "inputs": [("options", "any", {"optional": True})],
    "outputs": [("value", "string")],
}
PARAMS = [
    {"name": "caption", "type": "string", "label": "Caption",
     "default": "", "placeholder": "Shown above the dropdown"},
    {"name": "value", "type": "string", "label": "Selected", "default": ""},
    {"name": "items", "type": "text", "label": "Options",
     "default": "", "placeholder": "One per line — ignored while the "
                                   "'options' input is connected"},
    {"name": "column", "type": "columns", "label": "Column", "multi": False,
     "default": "", "placeholder": "Which column of a connected table "
                                   "(blank = the first)"},
    {"name": "width", "type": "int", "label": "Width",
     "default": 220, "min": 140, "max": 600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 84, "min": 56, "max": 400},
]


def run(ctx, options=None):
    from flograph.core.controls import (choice_value, lines_to_values,
                                        values_from_source)

    # the wire wins over the typed list, exactly as the dropdown decides it
    available = values_from_source(options, ctx.params.get("column", "")) \
        if options is not None else lines_to_values(ctx.params.get("items"))
    value = choice_value(ctx.params.get("value"), available)
    if available and value and value not in available:
        ctx.log(f"choice {value!r} is not among the current options "
                f"({len(available)} available) — passing it through anyway")
    return {"value": value}
