"""Write JSON

Write a DataFrame to a JSON file. Passes the table through so the pipeline
can continue. 'lines' writes one JSON object per line (JSONL).
"""
NODE = {
    "label": "Write JSON",
    "category": "IO",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "path", "type": "file_save", "label": "Output file", "default": ""},
    {"name": "layout", "type": "choice", "label": "Layout",
     "options": ["records", "lines", "columns", "index", "table"],
     "default": "records"},
    {"name": "indent", "type": "int", "label": "Indent (0 = compact)",
     "default": 2, "min": 0, "max": 8},
]


def run(ctx, table):
    path = ctx.params["path"]
    if not path:
        raise ValueError("no output file set — choose one in the node's properties")
    layout = ctx.params["layout"]
    kwargs = {"orient": "records", "lines": True} if layout == "lines" \
        else {"orient": layout, "indent": ctx.params["indent"] or None}
    table.to_json(path, **kwargs)
    ctx.log(f"wrote {len(table)} rows to {path}")
    return table
