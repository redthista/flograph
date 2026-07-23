"""Read CSV

Load a CSV file into a DataFrame. Compressed files (.gz, .zip, .bz2,
.xz, .zst) are decompressed automatically.

Separator accepts \\t for tab and 'auto' to sniff the delimiter.
Column types take one `column = dtype` per line (e.g. `id = int64`,
`name = string`, `flag = boolean`); lines starting with # are ignored.
"""
NODE = {
    "label": "Read CSV",
    "category": "IO",
    "inputs": [],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "path", "type": "file_open", "label": "CSV file", "default": ""},
    {"name": "sep", "type": "string", "label": "Separator", "default": ",",
     "placeholder": ", ; \\t or auto"},
    {"name": "header", "type": "bool", "label": "First row is header",
     "default": True},
    {"name": "encoding", "type": "string", "label": "Encoding", "default": "",
     "placeholder": "auto (utf-8)"},
    {"name": "columns", "type": "string", "label": "Columns",
     "default": "", "placeholder": "empty = all columns"},
    {"name": "index_col", "type": "string", "label": "Index column",
     "default": "", "placeholder": "name or 0-based position"},
    {"name": "skiprows", "type": "int", "label": "Skip rows at start",
     "default": 0, "min": 0},
    {"name": "nrows", "type": "int", "label": "Max rows (0 = all)",
     "default": 0, "min": 0},
    {"name": "decimal", "type": "string", "label": "Decimal mark",
     "default": "."},
    {"name": "thousands", "type": "string", "label": "Thousands mark",
     "default": "", "placeholder": "none"},
    {"name": "quotechar", "type": "string", "label": "Quote char",
     "default": '"'},
    {"name": "comment", "type": "string", "label": "Comment char",
     "default": "", "placeholder": "e.g. # — rest of line is ignored"},
    {"name": "na_values", "type": "string", "label": "Extra missing values",
     "default": "", "placeholder": "comma separated, e.g. -, n/a, ?"},
    {"name": "parse_dates", "type": "string", "label": "Parse dates",
     "default": "", "placeholder": "comma separated columns"},
    {"name": "dtypes", "type": "text", "label": "Column types",
     "default": "", "placeholder": "id = int64\nname = string"},
    {"name": "skip_blank_lines", "type": "bool", "label": "Skip blank lines",
     "default": True},
    {"name": "on_bad_lines", "type": "choice", "label": "On bad lines",
     "options": ["error", "warn", "skip"], "default": "error"},
    {"name": "engine", "type": "choice", "label": "Parser engine",
     "options": ["auto", "c", "python", "pyarrow"], "default": "auto"},
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
        raise ValueError("no file selected — set 'CSV file' in the node's properties")

    sep = (p.get("sep") or ",").replace("\\t", "\t")
    engine = p.get("engine", "auto")
    engine = None if engine == "auto" else engine
    kwargs = {
        "header": 0 if p.get("header", True) else None,
        "skip_blank_lines": p.get("skip_blank_lines", True),
    }
    if sep == "auto":
        # delimiter sniffing needs the python engine
        kwargs["sep"] = None
        engine = "python"
    else:
        kwargs["sep"] = sep
    if engine:
        kwargs["engine"] = engine
    if p.get("encoding", "").strip():
        kwargs["encoding"] = p["encoding"].strip()
    columns = _list(p.get("columns"))
    if columns:
        kwargs["usecols"] = columns
    index_col = (p.get("index_col") or "").strip()
    if index_col:
        kwargs["index_col"] = int(index_col) if index_col.isdigit() else index_col
    if p.get("skiprows", 0):
        kwargs["skiprows"] = int(p["skiprows"])
    if p.get("nrows", 0):
        kwargs["nrows"] = int(p["nrows"])
    if (p.get("decimal") or ".") != ".":
        kwargs["decimal"] = p["decimal"]
    if p.get("thousands", ""):
        kwargs["thousands"] = p["thousands"]
    if (p.get("quotechar") or '"') != '"':
        kwargs["quotechar"] = p["quotechar"]
    if p.get("comment", "").strip():
        kwargs["comment"] = p["comment"].strip()[0]
    na_values = _list(p.get("na_values"))
    if na_values:
        kwargs["na_values"] = na_values
    parse_dates = _list(p.get("parse_dates"))
    if parse_dates:
        kwargs["parse_dates"] = parse_dates
    dtypes = _mapping(p.get("dtypes"))
    if dtypes:
        kwargs["dtype"] = dtypes
    if p.get("on_bad_lines", "error") != "error":
        kwargs["on_bad_lines"] = p["on_bad_lines"]

    table = pd.read_csv(path, **kwargs)
    ctx.log(f"loaded {len(table)} rows x {len(table.columns)} columns")
    return table
