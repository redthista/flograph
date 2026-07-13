"""Action Button

A clickable trigger you drop directly on the canvas — left-click its face to
clear the cache and (re)run a chosen set of nodes, the whole flow, or every
node inside a named frame. It can also just pop up a markdown message. It has
no ports and takes no part in the data flow; it's a canvas control, not a
transform. Right-click (or click while already selected) selects/moves it
like any other node instead of firing.
"""
NODE = {
    "label": "Action Button",
    "category": "Util",
    "card": "button",
    "inputs": [],
    "outputs": [],
}
PARAMS = [
    {"name": "action", "type": "choice", "label": "On click",
     "options": ["Run nodes", "Run whole flow", "Run frame", "Show message"],
     "default": "Run nodes"},
    {"name": "clear_cache", "type": "bool", "label": "Clear cache first",
     "default": True},
    {"name": "frame_title", "type": "string", "label": "Frame title",
     "default": "", "placeholder": "Title of the frame to run"},
    {"name": "targets", "type": "text", "label": "Node names (one per line)",
     "default": "", "placeholder": "Exact label of each node to run"},
    {"name": "message", "type": "text", "label": "Message (Markdown)",
     "default": "", "placeholder": "Shown in a popup when clicked"},
    {"name": "width", "type": "int", "label": "Width",
     "default": 150, "min": 90, "max": 400},
    {"name": "height", "type": "int", "label": "Height",
     "default": 50, "min": 36, "max": 160},
]


def run(ctx):
    return {}
