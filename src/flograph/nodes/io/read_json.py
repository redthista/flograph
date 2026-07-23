"""Read JSON

Load a JSON file into a DataFrame. 'records' expects a list of objects;
'lines' one JSON object per line (JSONL); 'columns' a mapping of
column -> {row -> value}.

Flatten nested objects expands nested dicts into dotted columns
(json_normalize) — records and lines layouts only. Column types take
one `column = dtype` per line; lines starting with # are ignored.
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
    {"name": "encoding", "type": "string", "label": "Encoding", "default": "",
     "placeholder": "auto (utf-8)"},
    {"name": "flatten", "type": "bool", "label": "Flatten nested objects",
     "default": False},
    {"name": "flatten_sep", "type": "string", "label": "Flatten separator",
     "default": "."},
    {"name": "nrows", "type": "int", "label": "Max rows (0 = all, lines only)",
     "default": 0, "min": 0},
    {"name": "convert_dates", "type": "bool", "label": "Detect date columns",
     "default": True},
    {"name": "dtypes", "type": "text", "label": "Column types",
     "default": "", "placeholder": "id = int64\nname = string"},
]


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


def _read_flattened(path, layout, encoding, sep, nrows):
    import json

    import pandas as pd

    with open(path, encoding=encoding or "utf-8") as fh:
        if layout == "lines":
            records = []
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
                if nrows and len(records) >= nrows:
                    break
        else:
            records = json.load(fh)
            if not isinstance(records, list):
                raise ValueError(
                    "flatten expects the file to hold a list of objects "
                    "(records layout)")
    return pd.json_normalize(records, sep=sep or ".")


def run(ctx):
    import pandas as pd

    p = ctx.params
    path = p["path"]
    if not path:
        raise ValueError("no file selected — set 'JSON file' in the node's properties")

    layout = p.get("layout", "records")
    encoding = (p.get("encoding") or "").strip()
    nrows = int(p.get("nrows", 0) or 0)
    dtypes = _mapping(p.get("dtypes"))

    if p.get("flatten", False):
        if layout not in ("records", "lines"):
            raise ValueError("flatten only works with the records or lines layout")
        table = _read_flattened(path, layout, encoding,
                                p.get("flatten_sep", "."), nrows)
    else:
        kwargs = {"convert_dates": p.get("convert_dates", True)}
        if encoding:
            kwargs["encoding"] = encoding
        if layout == "lines":
            kwargs["orient"] = "records"
            kwargs["lines"] = True
            if nrows:
                kwargs["nrows"] = nrows
        else:
            kwargs["orient"] = layout
        table = pd.read_json(path, **kwargs)

    if dtypes:
        table = table.astype(dtypes)
    ctx.log(f"loaded {len(table)} rows x {len(table.columns)} columns")
    return table
