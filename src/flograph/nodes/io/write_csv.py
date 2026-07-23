"""Write CSV

Write a DataFrame to a CSV file. Passes the table through so the pipeline
can continue. A .gz/.zip/.bz2/.xz/.zst extension compresses automatically.

Separator accepts \\t for tab. Append mode adds rows to an existing file
without repeating the header.
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
    {"name": "sep", "type": "string", "label": "Separator", "default": ",",
     "placeholder": ", ; or \\t"},
    {"name": "header", "type": "bool", "label": "Write header", "default": True},
    {"name": "mode", "type": "choice", "label": "If file exists",
     "options": ["overwrite", "append"], "default": "overwrite"},
    {"name": "encoding", "type": "string", "label": "Encoding", "default": "",
     "placeholder": "auto (utf-8)"},
    {"name": "columns", "type": "columns", "label": "Columns",
     "default": "", "placeholder": "empty = all columns"},
    {"name": "na_rep", "type": "string", "label": "Missing value text",
     "default": "", "placeholder": "empty cell"},
    {"name": "float_format", "type": "string", "label": "Float format",
     "default": "", "placeholder": "e.g. %.2f"},
    {"name": "date_format", "type": "string", "label": "Date format",
     "default": "", "placeholder": "e.g. %Y-%m-%d"},
    {"name": "decimal", "type": "string", "label": "Decimal mark",
     "default": "."},
    {"name": "quoting", "type": "choice", "label": "Quoting",
     "options": ["minimal", "all", "nonnumeric", "none"], "default": "minimal"},
]


def run(ctx, table):
    import csv
    import os

    p = ctx.params
    path = p["path"]
    if not path:
        raise ValueError("no output file set — choose one in the node's properties")

    kwargs = {
        "index": p.get("index", False),
        "sep": (p.get("sep") or ",").replace("\\t", "\t"),
        "header": p.get("header", True),
    }
    appending = (p.get("mode", "overwrite") == "append"
                 and os.path.exists(path) and os.path.getsize(path) > 0)
    if appending:
        kwargs["mode"] = "a"
        kwargs["header"] = False  # the existing file already has one
    if p.get("encoding", "").strip():
        kwargs["encoding"] = p["encoding"].strip()
    columns = [c.strip() for c in (p.get("columns") or "").split(",") if c.strip()]
    if columns:
        missing = [c for c in columns if c not in table.columns]
        if missing:
            raise ValueError(f"columns not in table: {missing}")
        kwargs["columns"] = columns
    if p.get("na_rep", ""):
        kwargs["na_rep"] = p["na_rep"]
    if p.get("float_format", "").strip():
        kwargs["float_format"] = p["float_format"].strip()
    if p.get("date_format", "").strip():
        kwargs["date_format"] = p["date_format"].strip()
    if (p.get("decimal") or ".") != ".":
        kwargs["decimal"] = p["decimal"]
    quoting = p.get("quoting", "minimal")
    if quoting != "minimal":
        kwargs["quoting"] = {"all": csv.QUOTE_ALL,
                             "nonnumeric": csv.QUOTE_NONNUMERIC,
                             "none": csv.QUOTE_NONE}[quoting]

    table.to_csv(path, **kwargs)
    verb = "appended" if appending else "wrote"
    ctx.log(f"{verb} {len(table)} rows to {path}")
    return table
