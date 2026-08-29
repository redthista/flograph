"""Toggle

A tick box that sends True or False downstream — "include returns",
"show forecast", "log scale". Write the label people see in "Checkbox
label"; the caption above it is for a heading if you want one.

Feed it into an Expression or a Python Script to branch on, or straight into
a chart node's own boolean option.

Wire anything into "text" to set the label from your data or from another
control, so a tick box can name what it is actually filtering.
"""
NODE = {
    "label": "Toggle",
    "category": "Input",
    "version": "1.0",
    "card": "control",
    "control": "toggle",
    "inputs": [("text", "any", {"optional": True})],
    "outputs": [("value", "bool")],
}
PARAMS = [
    {"name": "caption", "type": "string", "label": "Caption",
     "default": "", "placeholder": "Heading above the tick box"},
    {"name": "text", "type": "string", "label": "Checkbox label",
     "default": "Enabled", "placeholder": "Shown beside the tick box"},
    {"name": "value", "type": "bool", "label": "Ticked", "default": False},
    {"name": "width", "type": "int", "label": "Width",
     "default": 200, "min": 120, "max": 600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 76, "min": 48, "max": 400},
]


def run(ctx, text=None):
    return {"value": bool(ctx.params.get("value", False))}
