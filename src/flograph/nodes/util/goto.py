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
    "card": "goto",
    "inputs": [("value", "any")],
    # Not drawn on the canvas: this is the source end of the invisible link,
    # which the engine sees as an ordinary edge (see flograph.core.links).
    "outputs": [("value", "any")],
}
PARAMS = [
    {"name": "name", "type": "string", "default": "",
     "label": "Link name", "placeholder": "e.g. Cleaned sales"},
]


def run(ctx, value):
    return value
