"""Table Spec

A KNIME-style spec card: shows the incoming table's structure — one row per
column with its dtype, non-null count, unique count and min/max domain —
directly on the canvas, so a flow's data shape is readable at a glance. The
spec itself is emitted as a DataFrame on the "spec" port for further use.
"""
NODE = {
    "label": "Table Spec",
    "category": "Viz",
    "inputs": [("table", "dataframe")],
    "outputs": [("spec", "dataframe")],
}
PARAMS = [
    {"name": "width", "type": "int", "label": "Width",
     "default": 420, "min": 260, "max": 1600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 240, "min": 200, "max": 2000},
    {"name": "scale", "type": "int", "label": "Scale %",
     "default": 100, "min": 25, "max": 400},
]


def run(ctx, table):
    from flograph.core.spec import spec_frame
    return {"spec": spec_frame(table)}
