"""Read Excel

Load a sheet from an Excel workbook (.xlsx, .xls, .xlsb, .ods) into a
DataFrame. Requires the optional `openpyxl` dependency for .xlsx.

Sheet takes a name, a 0-based index, or * to load every sheet stacked
into one table with a leading `sheet` column. Columns takes names or
Excel letter ranges (e.g. `A:C,F`). Column types take one
`column = dtype` per line; lines starting with # are ignored.
"""
NODE = {
    "label": "Read Excel",
    "category": "IO",
    "inputs": [],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "path", "type": "file_open", "label": "Excel file", "default": ""},
    {"name": "sheet_name", "type": "string", "label": "Sheet",
     "default": "0", "placeholder": "name, 0-based index, or * for all"},
    {"name": "header", "type": "bool", "label": "First row is header",
     "default": True},
    {"name": "skiprows", "type": "int", "label": "Skip rows at start",
     "default": 0, "min": 0},
    {"name": "nrows", "type": "int", "label": "Max rows (0 = all)",
     "default": 0, "min": 0},
    {"name": "columns", "type": "string", "label": "Columns",
     "default": "", "placeholder": "names or ranges like A:C,F; empty = all"},
    {"name": "index_col", "type": "string", "label": "Index column",
     "default": "", "placeholder": "name or 0-based position"},
    {"name": "na_values", "type": "string", "label": "Extra missing values",
     "default": "", "placeholder": "comma separated, e.g. -, n/a, ?"},
    {"name": "parse_dates", "type": "string", "label": "Parse dates",
     "default": "", "placeholder": "comma separated columns"},
    {"name": "dtypes", "type": "text", "label": "Column types",
     "default": "", "placeholder": "id = int64\nname = string"},
    {"name": "decimal", "type": "string", "label": "Decimal mark",
     "default": "."},
    {"name": "thousands", "type": "string", "label": "Thousands mark",
     "default": "", "placeholder": "none"},
    {"name": "engine", "type": "choice", "label": "Engine",
     "options": ["auto", "openpyxl", "calamine", "xlrd", "pyxlsb", "odf"],
     "default": "auto"},
]


def _list(raw):
    return [c.strip() for c in (raw or "").split(",") if c.strip()]


def _mapping(text):
    mapping = {}
    for lineno, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        col, sep, dtype = line.partition("=")
        col, dtype = col.strip(), dtype.strip()
        if not sep or not col or not dtype:
            raise ValueError(
                f"column types line {lineno}: expected 'column = dtype', got {line!r}")
        mapping[col] = dtype
    return mapping


def run(ctx):
    import pandas as pd

    p = ctx.params
    path = p["path"]
    if not path:
        raise ValueError("no file selected — set 'Excel file' in the node's properties")

    sheet = (p.get("sheet_name") or "0").strip() or "0"
    if sheet == "*":
        sheet_arg = None  # every sheet, as {name: frame}
    elif sheet.lstrip("-").isdigit():
        sheet_arg = int(sheet)
    else:
        sheet_arg = sheet

    kwargs = {"header": 0 if p.get("header", True) else None}
    if p.get("engine", "auto") != "auto":
        kwargs["engine"] = p["engine"]
    if p.get("skiprows", 0):
        kwargs["skiprows"] = int(p["skiprows"])
    if p.get("nrows", 0):
        kwargs["nrows"] = int(p["nrows"])
    columns_raw = (p.get("columns") or "").strip()
    if columns_raw:
        # letter ranges (A:C) go through as a string; otherwise a name list
        kwargs["usecols"] = (columns_raw if ":" in columns_raw
                             else _list(columns_raw))
    index_col = (p.get("index_col") or "").strip()
    if index_col:
        kwargs["index_col"] = int(index_col) if index_col.isdigit() else index_col
    na_values = _list(p.get("na_values"))
    if na_values:
        kwargs["na_values"] = na_values
    parse_dates = _list(p.get("parse_dates"))
    if parse_dates:
        kwargs["parse_dates"] = parse_dates
    dtypes = _mapping(p.get("dtypes"))
    if dtypes:
        kwargs["dtype"] = dtypes
    if (p.get("decimal") or ".") != ".":
        kwargs["decimal"] = p["decimal"]
    if p.get("thousands", ""):
        kwargs["thousands"] = p["thousands"]

    loaded = pd.read_excel(path, sheet_name=sheet_arg, **kwargs)
    if isinstance(loaded, dict):
        for name, frame in loaded.items():
            frame.insert(0, "sheet", name)
        table = pd.concat(loaded.values(), ignore_index=True)
        ctx.log(f"loaded {len(table)} rows x {len(table.columns)} columns "
                f"from {len(loaded)} sheet(s): {', '.join(loaded)}")
    else:
        table = loaded
        ctx.log(f"loaded {len(table)} rows x {len(table.columns)} columns "
                f"from sheet {sheet!r}")
    return table
