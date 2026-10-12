"""Checklist

A tick list of values — a column's regions, a set of products — with a
search box once the list is long and All / None above it. The ticked values
flow downstream as a list: `df[df["region"].isin(ticked)]`.

Where a Multi Choice lays a handful of options out as chips, a Checklist
scrolls, so it suits a few dozen. The same list is the "slicer" field of an
Input Panel, where it also shows how many rows are behind each value.

The options come from "Options" (one per line) or from a table, Series or
list wired into "options" — a table gives the unique values of "Column".
"None ticked means" decides what an empty list sends: every option, or
nothing.
"""
NODE = {
    "label": "Checklist",
    "category": "Input",
    "version": "1.0",
    "card": "control",
    "control": "list",
    "inputs": [("options", "any", {"optional": True})],
    "outputs": [("value", "any")],
}
PARAMS = [
    {"name": "caption", "type": "string", "label": "Caption",
     "default": "", "placeholder": "Shown above the list"},
    {"name": "value", "type": "string", "label": "Ticked",
     "default": "", "placeholder": '["north", "south"] — or tick the list'},
    {"name": "items", "type": "text", "label": "Options",
     "default": "", "placeholder": "One per line — ignored while the "
                                   "'options' input is connected"},
    {"name": "column", "type": "columns", "label": "Column", "multi": False,
     "default": "", "placeholder": "Which column of a connected table "
                                   "(blank = the first)"},
    {"name": "none_means", "type": "choice", "label": "None ticked means",
     "options": ["all", "nothing"], "default": "all"},
    {"name": "width", "type": "int", "label": "Width",
     "default": 240, "min": 160, "max": 800, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 220, "min": 100, "max": 600, "cosmetic": True},
]


def run(ctx, options=None):
    from flograph.core.controls import (lines_to_values, multi_values,
                                        values_from_source)

    available = values_from_source(options, ctx.params.get("column", "")) \
        if options is not None else lines_to_values(ctx.params.get("items"))
    return {"value": multi_values(ctx.params.get("value"), available,
                                  ctx.params.get("none_means", "all"))}
