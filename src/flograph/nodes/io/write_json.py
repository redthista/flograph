"""Write JSON

Write a DataFrame to a JSON file. Passes the table through so the pipeline
can continue. 'lines' writes one JSON object per line (JSONL). A
.gz/.zip/.bz2/.xz/.zst extension compresses automatically.
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
    {"name": "date_format", "type": "choice", "label": "Date format",
     "options": ["auto", "iso", "epoch"], "default": "auto"},
    {"name": "date_unit", "type": "choice", "label": "Date precision",
     "options": ["ms", "s", "us", "ns"], "default": "ms"},
    {"name": "double_precision", "type": "int", "label": "Float digits",
     "default": 10, "min": 0, "max": 15},
    {"name": "force_ascii", "type": "bool", "label": "Escape non-ASCII",
     "default": True},
]


def run(ctx, table):
    p = ctx.params
    path = p["path"]
    if not path:
        raise ValueError("no output file set — choose one in the node's properties")

    layout = p.get("layout", "records")
    if layout == "lines":
        kwargs = {"orient": "records", "lines": True}
    else:
        kwargs = {"orient": layout, "indent": p.get("indent", 2) or None}
    if p.get("date_format", "auto") != "auto":
        kwargs["date_format"] = p["date_format"]
    if p.get("date_unit", "ms") != "ms":
        kwargs["date_unit"] = p["date_unit"]
    if p.get("double_precision", 10) != 10:
        kwargs["double_precision"] = int(p["double_precision"])
    if not p.get("force_ascii", True):
        kwargs["force_ascii"] = False

    table.to_json(path, **kwargs)
    ctx.log(f"wrote {len(table)} rows to {path}")
    return table
