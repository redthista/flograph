"""Note

A markdown card rendered directly on the canvas — use it for titles, section
headers, and documentation, like Obsidian canvas cards. It has no ports and
takes no part in execution; double-click it to edit the text.
"""
NODE = {
    "label": "Note",
    "category": "Util",
    "card": "note",
    "inputs": [],
    "outputs": [],
}
PARAMS = [
    {"name": "text", "type": "text", "label": "Markdown",
     "default": "## Note\n\nDouble-click to edit.",
     "placeholder": "# Title\n\nSome *markdown* text…"},
    {"name": "width", "type": "int", "label": "Width",
     "default": 280, "min": 120, "max": 1600},
    {"name": "height", "type": "int", "label": "Height (0 = fit text)",
     "default": 0, "min": 0, "max": 2000},
]


def run(ctx):
    return {}
