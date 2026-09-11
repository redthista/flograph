"""Page Links

A strip of buttons, one for each of the project's pages — click one to go to
that page. Put it on each dashboard page and it is the way round them for
someone who never looks at the tabs. It reads the page list as it is, so a
page added, renamed, moved or recoloured turns up on every Page Links card
without touching any of them. Show every page, the pages in the same
tab-bar group as the page it sits on, or a chosen few; the page it sits on is
highlighted. Right-click it to move or resize it on the canvas; on a
dashboard, right-click selects it.
"""
NODE = {
    "label": "Page Links",
    "category": "Util",
    "version": "1.0",
    "card": "pagelinks",
    "inputs": [],
    "outputs": [],
}
PARAMS = [
    # all cosmetic: nothing runs, so nothing should be marked as needing to
    {"name": "show", "type": "choice", "label": "Show",
     "options": ["Every page", "This page's group", "Chosen pages"],
     "default": "Every page", "cosmetic": True},
    {"name": "pages", "type": "page_ref", "multi": True, "label": "Pages",
     "default": "", "placeholder": "Every page",
     "visible_when": {"show": "Chosen pages"}, "cosmetic": True},
    {"name": "layout", "type": "choice", "label": "Layout",
     "options": ["Row", "Column"], "default": "Row", "cosmetic": True},
    {"name": "width", "type": "int", "label": "Width",
     "default": 480, "min": 120, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 44, "min": 32, "max": 1200, "cosmetic": True},
]


def run(ctx):
    return {}
