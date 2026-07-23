"""Write SQLite

Write a DataFrame into a table of a SQLite database file (creates the file
if it doesn't exist). Passes the table through so the pipeline can continue.

Column SQL types override the guessed schema when the table is created:
one `column = SQLTYPE` per line (e.g. `id = INTEGER`, `name = TEXT`,
`price = REAL`); lines starting with # are ignored.
"""
NODE = {
    "label": "Write SQLite",
    "category": "IO",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "path", "type": "file_save", "label": "Database file", "default": ""},
    {"name": "table_name", "type": "string", "label": "Table name",
     "default": "data"},
    {"name": "if_exists", "type": "choice", "label": "If table exists",
     "options": ["replace", "append", "fail"], "default": "replace"},
    {"name": "index", "type": "bool", "label": "Write index", "default": False},
    {"name": "index_label", "type": "string", "label": "Index column name",
     "default": "", "placeholder": "used when writing the index"},
    {"name": "dtypes", "type": "text", "label": "Column SQL types",
     "default": "", "placeholder": "id = INTEGER\nname = TEXT"},
    {"name": "chunksize", "type": "int", "label": "Rows per batch (0 = all)",
     "default": 0, "min": 0},
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
                f"column SQL types line {lineno}: expected 'column = SQLTYPE', got {line!r}")
        mapping[col] = dtype
    return mapping


def run(ctx, table):
    import sqlite3

    p = ctx.params
    path = p["path"]
    if not path:
        raise ValueError("no output file set — choose one in the node's properties")
    name = (p.get("table_name") or "").strip()
    if not name:
        raise ValueError("no table name given")

    kwargs = {
        "if_exists": p.get("if_exists", "replace"),
        "index": p.get("index", False),
    }
    if p.get("index", False) and (p.get("index_label") or "").strip():
        kwargs["index_label"] = p["index_label"].strip()
    dtypes = _mapping(p.get("dtypes"))
    if dtypes:
        kwargs["dtype"] = dtypes
    if p.get("chunksize", 0):
        kwargs["chunksize"] = int(p["chunksize"])

    with sqlite3.connect(path) as conn:
        table.to_sql(name, conn, **kwargs)
    ctx.log(f"wrote {len(table)} rows to {path}:{name}")
    return table
