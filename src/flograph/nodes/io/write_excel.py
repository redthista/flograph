"""Write Excel

Write a DataFrame to an Excel workbook. Passes the table through so the
pipeline can continue. Requires the optional `openpyxl` dependency.

'add sheet' keeps the other sheets of an existing workbook and writes
into it (falling back to creating the file if it doesn't exist); 'If
sheet exists' then decides between replacing the sheet, erroring, adding
a numbered copy, or overlaying cells onto the existing sheet.
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
    {"name": "header", "type": "bool", "label": "Write header", "default": True},
    {"name": "mode", "type": "choice", "label": "If file exists",
     "options": ["overwrite file", "add sheet"], "default": "overwrite file"},
    {"name": "if_sheet_exists", "type": "choice", "label": "If sheet exists",
     "options": ["replace", "error", "new", "overlay"], "default": "replace"},
    {"name": "startrow", "type": "int", "label": "Start row (0-based)",
     "default": 0, "min": 0},
    {"name": "startcol", "type": "int", "label": "Start column (0-based)",
     "default": 0, "min": 0},
    {"name": "freeze_header", "type": "bool", "label": "Freeze header row",
     "default": False},
    {"name": "na_rep", "type": "string", "label": "Missing value text",
     "default": "", "placeholder": "empty cell"},
    {"name": "float_format", "type": "string", "label": "Float format",
     "default": "", "placeholder": "e.g. %.2f"},
    {"name": "engine", "type": "choice", "label": "Engine",
     "options": ["auto", "openpyxl", "xlsxwriter", "odf"], "default": "auto"},
]


def run(ctx, table):
    import os

    import pandas as pd

    p = ctx.params
    path = p["path"]
    if not path:
        raise ValueError("no output file set — choose one in the node's properties")

    sheet = p.get("sheet_name") or "Sheet1"
    startrow = int(p.get("startrow", 0) or 0)
    startcol = int(p.get("startcol", 0) or 0)
    kwargs = {
        "sheet_name": sheet,
        "index": p.get("index", False),
        "header": p.get("header", True),
        "startrow": startrow,
        "startcol": startcol,
    }
    if p.get("na_rep", ""):
        kwargs["na_rep"] = p["na_rep"]
    if p.get("float_format", "").strip():
        kwargs["float_format"] = p["float_format"].strip()
    if p.get("freeze_header", False) and p.get("header", True):
        kwargs["freeze_panes"] = (startrow + 1, 0)

    writer_kwargs = {}
    if p.get("engine", "auto") != "auto":
        writer_kwargs["engine"] = p["engine"]
    appending = (p.get("mode", "overwrite file") == "add sheet"
                 and os.path.exists(path))
    if appending:
        # append mode is openpyxl-only in pandas
        writer_kwargs.setdefault("engine", "openpyxl")
        writer_kwargs["mode"] = "a"
        writer_kwargs["if_sheet_exists"] = p.get("if_sheet_exists", "replace")

    with pd.ExcelWriter(path, **writer_kwargs) as writer:
        table.to_excel(writer, **kwargs)
    where = f"{path} sheet {sheet!r}"
    ctx.log(f"wrote {len(table)} rows to {where}"
            + (" (added to existing workbook)" if appending else ""))
    return table
