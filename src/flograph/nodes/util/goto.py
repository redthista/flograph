"""Goto

Name a value here and pick it up anywhere else in the model with a From node
-- a wire without the wire, for keeping a busy canvas readable.

Whatever arrives on the input is passed straight through to every From that
selects this node. Rename the link (the "Link name" field) and both ends
follow: From nodes bind to this node itself, not to its name, so renaming can
never break a link and two links may share a name.
"""
NODE = {
    "label": "Goto",
    "category": "Util",
    "version": "1.0",
    "card": "goto",
    "inputs": [("value", "any")],
    # Not drawn on the canvas: this is the source end of the invisible link,
    # which the engine sees as an ordinary edge (see flograph.core.links).
    "outputs": [("value", "any")],
}
PARAMS = [
    {"name": "name", "type": "string", "default": "",
     "label": "Link name", "placeholder": "e.g. Cleaned sales"},
    # Off by default: the whole point of a link is the wire it saves. Turned
    # on (here or from the card's right-click menu) the canvas draws a dashed
    # line to every From reading this Goto, for when following one matters
    # more than the clean canvas.
    {"name": "show_lines", "type": "bool", "default": False,
     "label": "Show link lines"},
]


def run(ctx, value):
    return value
