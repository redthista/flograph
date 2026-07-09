"""Show Figure

A live preview card: drop it on the canvas and wire a figure into it — it
renders the plot directly on the node, with pan/zoom/save controls built in.
Passes the figure through unchanged so you can keep it wired into further
consumers (e.g. a second Show Figure, or an export node).
"""
NODE = {
    "label": "Show Figure",
    "category": "Viz",
    "inputs": [("figure", "figure")],
    "outputs": [("figure", "figure")],
}
PARAMS = [
    {"name": "width", "type": "int", "label": "Width",
     "default": 420, "min": 260, "max": 1600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 320, "min": 200, "max": 2000},
]


def run(ctx, figure):
    return {"figure": figure}
