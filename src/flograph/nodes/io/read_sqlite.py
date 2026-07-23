"""Read SQLite

Load rows from a SQLite database file as a DataFrame — either a whole
table or the result of a SQL query (stdlib sqlite3 — no server needed).

In table mode a blank table name fails with the list of tables in the
database. Column types take one `column = dtype` per line; lines
starting with # are ignored.
"""
NODE = {
    "label": "Read SQLite",
    "category": "IO",
    "inputs": [],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "path", "type": "file_open", "label": "Database file", "default": ""},
    {"name": "source", "type": "choice", "label": "Read from",
     "options": ["query", "table"], "default": "query"},
    {"name": "query", "type": "text", "label": "SQL query",
     "default": "", "placeholder": "SELECT * FROM my_table"},
    {"name": "table", "type": "string", "label": "Table (table mode)",
     "default": "", "placeholder": "table name"},
    {"name": "index_col", "type": "string", "label": "Index column",
     "default": "", "placeholder": "column name"},
    {"name": "parse_dates", "type": "string", "label": "Parse dates",
     "default": "", "placeholder": "comma separated columns"},
    {"name": "dtypes", "type": "text", "label": "Column types",
     "default": "", "placeholder": "id = int64\nname = string"},
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
    import sqlite3

    import pandas as pd

    p = ctx.params
    path = p["path"]
    if not path:
        raise ValueError("no database selected — set 'Database file' in the node's properties")

    with sqlite3.connect(path) as conn:
        if p.get("source", "query") == "table":
            name = (p.get("table") or "").strip()
            if not name:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "ORDER BY name").fetchall()
                available = ", ".join(r[0] for r in rows) or "(none)"
                raise ValueError(f"no table name given — tables in this "
                                 f"database: {available}")
            quoted = name.replace('"', '""')
            query = f'SELECT * FROM "{quoted}"'
        else:
            query = (p.get("query") or "").strip()
            if not query:
                raise ValueError("no SQL query given")

        kwargs = {}
        index_col = (p.get("index_col") or "").strip()
        if index_col:
            kwargs["index_col"] = index_col
        parse_dates = _list(p.get("parse_dates"))
        if parse_dates:
            kwargs["parse_dates"] = parse_dates
        dtypes = _mapping(p.get("dtypes"))
        if dtypes:
            kwargs["dtype"] = dtypes
        table = pd.read_sql_query(query, conn, **kwargs)
    ctx.log(f"loaded {len(table)} rows x {len(table.columns)} columns")
    return table
