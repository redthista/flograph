"""Write SQLite

Write a DataFrame into a table of a SQLite database file (creates the file
if it doesn't exist). Passes the table through so the pipeline can continue.
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
]


def run(ctx, table):
    import sqlite3

    path = ctx.params["path"]
    if not path:
        raise ValueError("no output file set — choose one in the node's properties")
    name = ctx.params["table_name"].strip()
    if not name:
        raise ValueError("no table name given")
    with sqlite3.connect(path) as conn:
        table.to_sql(name, conn, if_exists=ctx.params["if_exists"],
                     index=ctx.params["index"])
    ctx.log(f"wrote {len(table)} rows to {path}:{name}")
    return table
