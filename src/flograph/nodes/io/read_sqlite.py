"""Read SQLite

Run a SQL query against a SQLite database file and load the result as a
DataFrame (SQL query reader; stdlib sqlite3 — no server needed).
"""
NODE = {
    "label": "Read SQLite",
    "category": "IO",
    "inputs": [],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "path", "type": "file_open", "label": "Database file", "default": ""},
    {"name": "query", "type": "text", "label": "SQL query",
     "default": "", "placeholder": "SELECT * FROM my_table"},
]


def run(ctx):
    import sqlite3

    import pandas as pd

    path = ctx.params["path"]
    if not path:
        raise ValueError("no database selected — set 'Database file' in the node's properties")
    query = ctx.params["query"].strip()
    if not query:
        raise ValueError("no SQL query given")
    with sqlite3.connect(path) as conn:
        table = pd.read_sql_query(query, conn)
    ctx.log(f"loaded {len(table)} rows x {len(table.columns)} columns")
    return table
