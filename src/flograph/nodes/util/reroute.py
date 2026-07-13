"""Reroute

Pass a value straight through. Used as a wire organization dot on the canvas.
"""
NODE = {
    "label": "Reroute",
    "category": "Util",
    "inputs": [("value", "any")],
    "outputs": [("value", "any")],
}


def run(ctx, value):
    return value
