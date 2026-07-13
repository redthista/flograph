"""Write Excel

Write a DataFrame to an Excel workbook. Passes the table through so the
pipeline can continue. Requires the optional `openpyxl` dependency.
"""
NODE = {
    "label": "Write Excel",
    "category": "IO",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "path", "type": "file_save", "label": "Output file", "default": ""},
    {"name": "sheet_name", "type": "string", "label": "Sheet name",
     "default": "Sheet1"},
    {"name": "index", "type": "bool", "label": "Write index", "default": False},
]


def run(ctx, table):
    path = ctx.params["path"]
    if not path:
        raise ValueError("no output file set — choose one in the node's properties")
    table.to_excel(path, sheet_name=ctx.params["sheet_name"] or "Sheet1",
                    index=ctx.params["index"])
    ctx.log(f"wrote {len(table)} rows to {path}")
    return table
