"""Write CSV

Write a DataFrame to a CSV file. Passes the table through so the pipeline
can continue.
"""
NODE = {
    "label": "Write CSV",
    "category": "IO",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "path", "type": "file_save", "label": "Output file", "default": ""},
    {"name": "index", "type": "bool", "label": "Write index", "default": False},
]


def run(ctx, table):
    path = ctx.params["path"]
    if not path:
        raise ValueError("no output file set — choose one in the node's properties")
    table.to_csv(path, index=ctx.params["index"])
    ctx.log(f"wrote {len(table)} rows to {path}")
    return table
