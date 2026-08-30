"""SQL Query

Read from any database SQLAlchemy can reach — Postgres, MySQL/MariaDB,
SQLite, DuckDB, SQL Server, Oracle, Snowflake, BigQuery, Redshift — with one
node and a connection URL:

    postgresql+psycopg://user:pass@host:5432/dbname
    mysql+pymysql://user:pass@host/dbname
    duckdb:////absolute/path/to/warehouse.duckdb
    sqlite:///./local.db
    snowflake://user:pass@account/db/schema?warehouse=WH

Put the URL in a `.env` file and reference it as `${env:DATABASE_URL}` so no
credentials land in the project. The right driver package must be installed
(`psycopg`, `pymysql`, `duckdb-engine`, …); a missing one names itself.

**Mode** is a raw SQL query or a whole table. `${name}` flow variables are
substituted into the query before it runs — parameterise a report without
string-building. **Row limit** wraps a `LIMIT` around table mode; in query
mode add your own `LIMIT` to make the database do less work.
"""
NODE = {
    "label": "SQL Query",
    "category": "Connect",
    "version": "1.0",
    "inputs": [],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "url", "type": "string", "label": "Connection URL",
     "default": "", "placeholder": "${env:DATABASE_URL}"},
    {"name": "mode", "type": "choice", "label": "Mode",
     "options": ["query", "table"], "default": "query"},
    {"name": "query", "type": "text", "label": "SQL query",
     "default": "", "placeholder": "SELECT * FROM orders WHERE day >= '2026-01-01'",
     "visible_when": {"mode": "query"}},
    {"name": "table", "type": "string", "label": "Table",
     "default": "", "placeholder": "schema.table or table",
     "visible_when": {"mode": "table"}},
    {"name": "limit", "type": "int", "label": "Row limit (0 = all)",
     "default": 0, "min": 0, "max": 100_000_000},
    {"name": "parse_dates", "type": "string", "label": "Parse dates",
     "default": "", "placeholder": "comma separated columns"},
]


def run(ctx):
    import pandas as pd
    from sqlalchemy import create_engine, text

    p = ctx.params
    url = (p.get("url") or "").strip()
    if not url:
        raise ValueError("no connection URL — set 'Connection URL' (e.g. "
                         "${env:DATABASE_URL})")
    limit = int(p.get("limit", 0) or 0)
    parse_dates = [c.strip() for c in (p.get("parse_dates") or "").split(",")
                   if c.strip()] or None

    if p.get("mode") == "table":
        name = (p.get("table") or "").strip()
        if not name:
            raise ValueError("no table name — set 'Table'")
        # quote each dotted part so "schema.table" and reserved words survive
        quoted = ".".join(f'"{part}"' for part in name.split("."))
        sql = f"SELECT * FROM {quoted}"
        if limit:
            sql += f" LIMIT {limit}"
    else:
        sql = (p.get("query") or "").strip()
        if not sql:
            raise ValueError("no SQL query — set 'SQL query'")

    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            frame = pd.read_sql(text(sql), conn, parse_dates=parse_dates)
    finally:
        engine.dispose()

    if limit and p.get("mode") != "table" and len(frame) > limit:
        frame = frame.head(limit).copy()
        ctx.log(f"trimmed to the first {limit} rows")
    ctx.log(f"read {len(frame)} rows x {len(frame.columns)} columns")
    return frame
