"""Read Excel

Load a sheet from an Excel workbook into a DataFrame. Requires the
optional `openpyxl` dependency.
"""
NODE = {
    "label": "Read Excel",
    "category": "IO",
    "inputs": [],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "path", "type": "file_open", "label": "Excel file", "default": ""},
    {"name": "sheet_name", "type": "string", "label": "Sheet (name or index)",
     "default": "0"},
    {"name": "header", "type": "bool", "label": "First row is header",
     "default": True},
]


def run(ctx):
    import pandas as pd

    path = ctx.params["path"]
    if not path:
        raise ValueError("no file selected — set 'Excel file' in the node's properties")
    sheet = (ctx.params["sheet_name"] or "0").strip() or "0"
    sheet = int(sheet) if sheet.lstrip("-").isdigit() else sheet
    table = pd.read_excel(
        path,
        sheet_name=sheet,
        header=0 if ctx.params["header"] else None,
    )
    ctx.log(f"loaded {len(table)} rows x {len(table.columns)} columns from sheet {sheet!r}")
    return table
