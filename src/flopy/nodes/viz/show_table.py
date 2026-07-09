"""Show Table

A live preview card: drop it on the canvas and wire a DataFrame into it — it
renders the table directly on the node, scrollable with sortable-by-column
headers. Passes the table through unchanged so you can keep it wired into
further consumers (e.g. a second Show Table, or an export node).
"""
NODE = {
    "label": "Show Table",
    "category": "Viz",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "width", "type": "int", "label": "Width",
     "default": 420, "min": 260, "max": 1600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 320, "min": 200, "max": 2000},
]


def run(ctx, table):
    return {"table": table}
