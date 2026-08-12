"""From

Re-emit the value of a Goto node, with no wire between them. Pick which Goto
in the "Goto" dropdown; the card shows that link's current name.

Any number of From nodes may read the same Goto. A From that points at
nothing (or at a Goto that has since been deleted) stops the run rather than
passing an empty value downstream.
"""
NODE = {
    "label": "From",
    "category": "Util",
    "card": "from",
    # Not drawn on the canvas: the destination end of the invisible link. It
    # stays required so an unlinked From blocks instead of emitting None.
    "inputs": [("value", "any")],
    "outputs": [("value", "any")],
}
PARAMS = [
    {"name": "source", "type": "node_ref", "ref_kind": "goto",
     "default": "", "label": "Goto"},
    # See goto.py: off by default, and either end of a link can ask for the
    # line — turning it on here draws this From's own line back to its Goto
    # without lighting up every other From reading the same one.
    {"name": "show_lines", "type": "bool", "default": False,
     "label": "Show link line"},
]


def run(ctx, value):
    return value
