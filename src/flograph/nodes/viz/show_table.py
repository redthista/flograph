"""Show Table

A live preview card: drop it on the canvas and wire a DataFrame into it — it
renders the table directly on the node, scrollable with sortable-by-column
headers. Passes the table through unchanged so you can keep it wired into
further consumers (e.g. a second Show Table, or an export node).
"""
NODE = {
    "label": "Show Table",
    "category": "Viz",
    "version": "1.0",
    "card": "table_viewer",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
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


def run(ctx, table):
    return {"table": table}
