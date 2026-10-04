"""Action Button

A clickable trigger you drop directly on the canvas — left-click its face to
clear the cache and (re)run a chosen set of nodes, the whole flow, or every
node inside a named frame. It can also pop up a markdown message, or go to
one of the project's pages, which on a dashboard makes it the way from one
page to the next. Ticking "Update what follows" also re-runs everything
downstream of the nodes it runs — point it at a data source and every chart
and table built from it refreshes. Embedded in a report page with
![[Button label]] it is a button there too, in the app's preview only.
It has no ports and takes no part in the data flow; it's a
canvas control, not a transform. Right-click (or click while already
selected) selects/moves it like any other node instead of firing.
"""
NODE = {
    "label": "Action Button",
    "category": "Util",
    "version": "1.2",
    "card": "button",
    "inputs": [],
    "outputs": [],
}
_RUNS = ["Run nodes", "Run whole flow", "Run frame"]

PARAMS = [
    {"name": "action", "type": "choice", "label": "On click",
     "options": [*_RUNS, "Show message", "Go to page"],
     "default": "Run nodes"},
    {"name": "clear_cache", "type": "bool", "label": "Clear cache first",
     "default": True, "visible_when": {"action": _RUNS}},
    # "Run nodes" runs the named nodes and what they need; this adds what
    # needs *them*, which is what refreshing a source means
    {"name": "downstream", "type": "bool", "label": "Update what follows",
     "default": False,
     "visible_when": {"action": ["Run nodes", "Run frame"]}},
    {"name": "frame_title", "type": "string", "label": "Frame title",
     "default": "", "placeholder": "Title of the frame to run",
     "visible_when": {"action": "Run frame"}},
    {"name": "targets", "type": "text", "label": "Node names (one per line)",
     "default": "", "placeholder": "Exact label of each node to run",
     "visible_when": {"action": "Run nodes"}},
    {"name": "message", "type": "text", "label": "Message (Markdown)",
     "default": "", "placeholder": "Shown in a popup when clicked",
     "visible_when": {"action": "Show message"}},
    # by id, so renaming the page doesn't strand the button
    {"name": "page", "type": "page_ref", "label": "Page", "default": "",
     "visible_when": {"action": "Go to page"}},
    {"name": "width", "type": "int", "label": "Width",
     "default": 150, "min": 90, "max": 400, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 50, "min": 36, "max": 160, "cosmetic": True},
]


def run(ctx):
    return {}
