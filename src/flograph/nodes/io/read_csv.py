"""Read CSV

Load a CSV file into a DataFrame.
"""
NODE = {
    "label": "Read CSV",
    "category": "IO",
    "inputs": [],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "path", "type": "file_open", "label": "CSV file", "default": ""},
    {"name": "sep", "type": "string", "label": "Separator", "default": ","},
    {"name": "header", "type": "bool", "label": "First row is header",
     "default": True},
]


def run(ctx):
    import pandas as pd

    path = ctx.params["path"]
    if not path:
        raise ValueError("no file selected — set 'CSV file' in the node's properties")
    table = pd.read_csv(
        path,
        sep=ctx.params["sep"] or ",",
        header=0 if ctx.params["header"] else None,
    )
    ctx.log(f"loaded {len(table)} rows x {len(table.columns)} columns")
    return table
