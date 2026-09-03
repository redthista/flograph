"""Show Table

A live preview card: drop it on the canvas and wire a DataFrame into it — it
renders the table directly on the node, scrollable with sortable-by-column
headers. Passes the table through unchanged so you can keep it wired into
further consumers (e.g. a second Show Table, or an export node).

Wire a **Table Style** node into the **Style** input to colour cells by
value (a heatmap), draw in-cell data bars, highlight the cells or rows that
pass a test, or add an icon set. The formatting is presentation only — the
table flowing out is untouched — and the Style object is passed through on
the **style** output so a second Show Table can share it.
"""
NODE = {
    "label": "Show Table",
    "category": "Viz",
    "version": "1.1",
    "card": "table_viewer",
    "inputs": [("table", "dataframe"),
               ("style", "object", {"optional": True})],
    "outputs": [("table", "dataframe"), ("style", "object")],
}
PARAMS = [
    {"name": "width", "type": "int", "label": "Width",
     "default": 420, "min": 260, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 320, "min": 200, "max": 2000, "cosmetic": True},
    # Cosmetic: run() never reads it — the zoom is applied to the card, to
    # the table this node already passed through.
    {"name": "scale", "type": "int", "label": "Scale %",
     "default": 100, "min": 25, "max": 400, "cosmetic": True},
]


def run(ctx, table, style=None):
    return {"table": table, "style": style}
