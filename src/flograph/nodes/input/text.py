"""Text

A text box whose contents flow downstream — a search term, a label for a
chart title, a file name, a chunk of SQL.

Turn on "Multiline" for a larger box. The text commits when you leave the
box or press Enter, not on every keystroke, so one edit is one undo step and
the flow re-runs once rather than once per character. Turn on "Search as you
type" for a search box instead: the flow follows the typing, once it pauses.

Wire anything into "placeholder" to set the greyed hint from your data or
from another control — useful for showing what a box expects ("e.g.
North") without putting a value in it that would flow downstream.

**Checking what is typed.** "Pattern" is a regular expression the whole
text must match — `[A-Z]{2}\\d{4}` for a code like AB1234, `\\d+` for digits
only. Text that doesn't match is outlined red on the card and stops the
nodes after it with "Pattern message" (or a plain description of the
mismatch). An empty box always passes; tick "Required" under Behaviour to
refuse that too.

"Hide what is typed" shows dots instead of the text. It is still saved in
the project in plain text — a password belongs in a secret, `${env:NAME}`,
never in a Text control.
"""
NODE = {
    "label": "Text",
    "category": "Input",
    "version": "1.1",
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
    {"name": "live_typing", "type": "bool", "label": "Search as you type",
     "default": False, "cosmetic": True},
    {"name": "pattern", "type": "string", "label": "Pattern",
     "default": "", "placeholder": r"Regular expression, e.g. [A-Z]{2}\d{4}"},
    {"name": "pattern_message", "type": "string", "label": "Pattern message",
     "default": "", "placeholder": "Said when the text doesn't match",
     "cosmetic": True},
    {"name": "mask", "type": "bool", "label": "Hide what is typed",
     "default": False, "cosmetic": True},
    {"name": "width", "type": "int", "label": "Width",
     "default": 240, "min": 140, "max": 800, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 84, "min": 56, "max": 600, "cosmetic": True},
]


def run(ctx, placeholder=None):
    from flograph.core.controls import pattern_problem

    value = str(ctx.params.get("value", "") or "")
    problem = pattern_problem(value, ctx.params.get("pattern", ""),
                              ctx.params.get("pattern_message", ""))
    if problem:
        raise ValueError(problem)
    return {"value": value}
