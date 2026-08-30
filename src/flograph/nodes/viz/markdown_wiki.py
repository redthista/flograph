"""Markdown Wiki

A folder of Markdown files, shown on the canvas and on a dashboard page as a
navigable wiki — a nav tree, a breadcrumb, and `[[wikilinks]]` that jump
between pages. Point a model at its own user guide and the guide travels
with the dashboard to whoever opens it.

Set **Notes folder** to a directory of `.md` files. Leave it blank and the
card shows flograph's own handbook (the same pages as **Help ▸
Documentation**). A `_Sidebar.md` in the folder — a nested bullet list of
`[[links]]` — becomes the nav tree, exactly as it would on a GitHub wiki;
without one the pages are listed flat.

The card renders itself — this node computes nothing. Wire a string into
**folder** to choose the directory at run time (a `${docs_dir}` variable,
say); a non-empty wired value wins over the parameter. **Current page** and
**Show nav panel** remember where the reader is and are cosmetic, so moving
around the wiki never re-runs anything.
"""
NODE = {
    "label": "Markdown Wiki",
    "category": "Viz",
    "version": "1.0",
    "card": "wiki",
    "inputs": [("folder", "string", {"optional": True})],
    "outputs": [],
}
PARAMS = [
    {"name": "folder", "type": "folder_open", "label": "Notes folder",
     "default": "",
     "placeholder": "folder of .md files — blank shows the flograph handbook"},
    {"name": "page", "type": "string", "label": "Current page",
     "default": "", "cosmetic": True},
    {"name": "show_nav", "type": "bool", "label": "Show nav panel",
     "default": True, "cosmetic": True},
    {"name": "width", "type": "int", "label": "Width",
     "default": 520, "min": 260, "max": 1600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 380, "min": 160, "max": 2000},
]


def run(ctx, folder=None):
    # Nothing to compute — the card reads the folder and renders the pages
    # itself (via flograph.core.docpages). run() exists only so the node is
    # scheduled: a Run establishes the card as part of the flow.
    return {}
