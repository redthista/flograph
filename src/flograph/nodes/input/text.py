"""Text

A text box whose contents flow downstream — a search term, a label for a
chart title, a file name, a chunk of SQL.

Turn on "Multiline" for a larger box. The text commits when you leave the
box or press Enter, not on every keystroke, so one edit is one undo step and
the flow re-runs once rather than once per character.

Wire anything into "placeholder" to set the greyed hint from your data or
from another control — useful for showing what a box expects ("e.g.
North") without putting a value in it that would flow downstream.
"""
NODE = {
    "label": "Text",
    "category": "Input",
    "version": "1.0",
    "card": "control",
    "control": "text",
    "inputs": [("placeholder", "any", {"optional": True})],
    "outputs": [("value", "string")],
}
PARAMS = [
    {"name": "caption", "type": "string", "label": "Caption",
     "default": "", "placeholder": "Shown above the box"},
    {"name": "value", "type": "string", "label": "Value", "default": ""},
    {"name": "placeholder", "type": "string", "label": "Placeholder",
     "default": "", "placeholder": "Greyed hint shown while empty"},
    {"name": "multiline", "type": "bool", "label": "Multiline",
     "default": False},
    {"name": "width", "type": "int", "label": "Width",
     "default": 240, "min": 140, "max": 800},
    {"name": "height", "type": "int", "label": "Height",
     "default": 84, "min": 56, "max": 600},
]


def run(ctx, placeholder=None):
    return {"value": str(ctx.params.get("value", "") or "")}
