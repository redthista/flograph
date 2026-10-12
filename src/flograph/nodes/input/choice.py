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

**Style.** A dropdown suits a long list; type while it is open to narrow it
down. For a handful of options, "buttons" lays them out as a row of buttons
and "radio" as a column of round buttons, so every option is visible at once.

**(All).** Tick "Offer (All)" and the list starts with an "(All)" entry,
which emits an empty value — what an Input Panel reads as "don't filter on
this" — and is the pick a fresh control starts on.

**Emits.** "text" sends the option as written. "number" sends 2024 rather
than "2024", for options that are years, sizes or thresholds; an option that
isn't a number still goes as text.
"""
NODE = {
    "label": "Choice",
    "category": "Input",
    "version": "1.1",
    "card": "control",
    "control": "choice",
    "inputs": [("options", "any", {"optional": True})],
    # "any", not "string": with Emits = number the value is a number
    "outputs": [("value", "any")],
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
    {"name": "style", "type": "choice", "label": "Style",
     "options": ["dropdown", "buttons", "radio"], "default": "dropdown",
     "cosmetic": True},
    {"name": "all_option", "type": "bool", "label": "Offer (All)",
     "default": False},
    {"name": "value_type", "type": "choice", "label": "Emits",
     "options": ["text", "number"], "default": "text"},
    {"name": "width", "type": "int", "label": "Width",
     "default": 220, "min": 140, "max": 800, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 84, "min": 56, "max": 600, "cosmetic": True},
]


def run(ctx, options=None):
    from flograph.core.controls import (cast_choice, choice_value,
                                        lines_to_values, values_from_source)

    # the wire wins over the typed list, exactly as the dropdown decides it
    available = values_from_source(options, ctx.params.get("column", "")) \
        if options is not None else lines_to_values(ctx.params.get("items"))
    all_option = bool(ctx.params.get("all_option", False))
    value = choice_value(ctx.params.get("value"), available, all_option)
    if available and value and value not in available:
        ctx.log(f"choice {value!r} is not among the current options "
                f"({len(available)} available) — passing it through anyway")
    return {"value": cast_choice(value, ctx.params.get("value_type", "text"))}
