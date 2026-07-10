"""Read JSON

Load a JSON file into a DataFrame. 'records' expects a list of objects;
'lines' one JSON object per line (JSONL); 'columns' a mapping of
column -> {row -> value}.
"""
NODE = {
    "label": "Read JSON",
    "category": "IO",
    "inputs": [],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "path", "type": "file_open", "label": "JSON file", "default": ""},
    {"name": "layout", "type": "choice", "label": "Layout",
     "options": ["records", "lines", "columns", "index", "table"],
     "default": "records"},
]


def run(ctx):
    import pandas as pd

    path = ctx.params["path"]
    if not path:
        raise ValueError("no file selected — set 'JSON file' in the node's properties")
    layout = ctx.params["layout"]
    if layout == "lines":
        table = pd.read_json(path, orient="records", lines=True)
    else:
        table = pd.read_json(path, orient=layout)
    ctx.log(f"loaded {len(table)} rows x {len(table.columns)} columns")
    return table
