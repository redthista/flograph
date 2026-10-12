"""Multi Choice

Pick any number of a known set — several regions, a few products — shown as
chips you click on and off, with All and None beside them. The picks flow
downstream as a list, the shape `df[df["region"].isin(picked)]` wants.

The options come from whichever you give it, exactly as a Choice's do:
"Options", one per line, or a table, Series or list wired into "options"
(a table contributes the unique values of "Column", or its first column).

**Nothing ticked.** "None ticked means" decides what an empty selection
sends: **all** (every option — "no filter yet", the usual reading on a
dashboard) or **nothing** (an empty list).

Chips suit a handful to a few dozen options. For hundreds, or for a tree of
columns, use a **Slicer**, which has a search box and folds.
"""
NODE = {
    "label": "Multi Choice",
    "category": "Input",
    "version": "1.0",
    "card": "control",
    "control": "multi",
    "inputs": [("options", "any", {"optional": True})],
    "outputs": [("value", "any")],
}
PARAMS = [
    {"name": "caption", "type": "string", "label": "Caption",
     "default": "", "placeholder": "Shown above the chips"},
    {"name": "value", "type": "string", "label": "Ticked",
     "default": "", "placeholder": '["north", "south"] — or click the chips'},
    {"name": "items", "type": "text", "label": "Options",
     "default": "", "placeholder": "One per line — ignored while the "
                                   "'options' input is connected"},
    {"name": "column", "type": "columns", "label": "Column", "multi": False,
     "default": "", "placeholder": "Which column of a connected table "
                                   "(blank = the first)"},
    {"name": "none_means", "type": "choice", "label": "None ticked means",
     "options": ["all", "nothing"], "default": "all"},
    {"name": "width", "type": "int", "label": "Width",
     "default": 260, "min": 160, "max": 800, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 150, "min": 70, "max": 600, "cosmetic": True},
]


def run(ctx, options=None):
    from flograph.core.controls import (lines_to_values, multi_values,
                                        values_from_source)

    available = values_from_source(options, ctx.params.get("column", "")) \
        if options is not None else lines_to_values(ctx.params.get("items"))
    return {"value": multi_values(ctx.params.get("value"), available,
                                  ctx.params.get("none_means", "all"))}
