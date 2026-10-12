"""File

A "Choose…" button that lets whoever is using the dashboard point the flow
at a file of their own — this month's export, their region's sheet. The
path flows downstream as text: wire it into a Read node's path, or give it a
Variable name (Behaviour) and write `${name}` in one.

"Pick" chooses a file or a folder. "File types" narrows the dialog, written
the way the dialog wants it: `CSV files (*.csv);;Excel (*.xlsx)`.

With "Must exist" ticked, a path that isn't there stops the nodes after it
with a message saying so, rather than letting a Read fail further down with
something less clear.
"""
NODE = {
    "label": "File",
    "category": "Input",
    "version": "1.0",
    "card": "control",
    "control": "file",
    "inputs": [],
    "outputs": [("value", "string")],
}
PARAMS = [
    {"name": "caption", "type": "string", "label": "Caption",
     "default": "", "placeholder": "Shown above the button"},
    {"name": "value", "type": "file_open", "label": "Path", "default": ""},
    {"name": "mode", "type": "choice", "label": "Pick",
     "options": ["file", "folder"], "default": "file"},
    {"name": "filter", "type": "string", "label": "File types",
     "default": "", "placeholder": "CSV files (*.csv);;All files (*)",
     "cosmetic": True},
    {"name": "must_exist", "type": "bool", "label": "Must exist",
     "default": True},
    {"name": "width", "type": "int", "label": "Width",
     "default": 260, "min": 160, "max": 800, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 84, "min": 56, "max": 600, "cosmetic": True},
]


def run(ctx):
    import os

    path = str(ctx.params.get("value", "") or "").strip()
    if path and ctx.params.get("must_exist", True):
        exists = os.path.isdir(path) if ctx.params.get("mode") == "folder" \
            else os.path.isfile(path)
        if not exists:
            raise FileNotFoundError(f"{path!r} does not exist")
    return {"value": path}
