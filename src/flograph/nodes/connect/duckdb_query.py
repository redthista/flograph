"""DuckDB SQL

Run analytical SQL over the tables flowing into this node — and over Parquet,
CSV and JSON files on disk — with DuckDB's in-process engine. No server, no
load step: the wired DataFrames are registered as views named `a`, `b`, `c`,
`d` (whichever inputs you connect), and you `SELECT` against them.

    SELECT a.region, sum(b.amount) AS spend
    FROM a JOIN b USING (customer_id)
    GROUP BY 1 ORDER BY 2 DESC

**Files** aliases paths and globs so they read like tables — one
`name = path` per line:

    sales = /data/sales/2026-*.parquet
    lookup = ./ref/regions.csv

then `SELECT * FROM sales`. DuckDB reads the glob directly; nothing is copied
into memory until the query touches it. `${name}` flow variables are
substituted into the SQL first. Needs the `duckdb` package.
"""
NODE = {
    "label": "DuckDB SQL",
    "category": "Connect",
    "version": "1.0",
    "inputs": [
        ("a", "dataframe", {"optional": True}),
        ("b", "dataframe", {"optional": True}),
        ("c", "dataframe", {"optional": True}),
        ("d", "dataframe", {"optional": True}),
    ],
    "outputs": [("result", "dataframe")],
}
PARAMS = [
    {"name": "query", "type": "text", "label": "SQL",
     "default": "SELECT * FROM a",
     "placeholder": "SELECT ... FROM a JOIN b USING (id)"},
    {"name": "files", "type": "text", "label": "Files",
     "default": "", "placeholder": "sales = /data/*.parquet\nrefs = ./refs.csv"},
]


def run(ctx, a=None, b=None, c=None, d=None):
    import duckdb

    p = ctx.params
    query = (p.get("query") or "").strip()
    if not query:
        raise ValueError("no SQL — set 'SQL'")

    frames = {"a": a, "b": b, "c": c, "d": d}
    connected = {name: df for name, df in frames.items() if df is not None}

    aliases = {}
    for lineno, raw in enumerate((p.get("files") or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, path = line.partition("=")
        name, path = name.strip(), path.strip()
        if not sep or not name or not path:
            raise ValueError(
                f"files line {lineno}: expected 'name = path', got {line!r}")
        if not name.isidentifier():
            raise ValueError(f"files line {lineno}: {name!r} is not a valid "
                             "view name")
        aliases[name] = path

    con = duckdb.connect(":memory:")
    try:
        for name, df in connected.items():
            con.register(name, df)
        for name, path in aliases.items():
            low = path.lower()
            if low.endswith((".csv", ".tsv", ".txt", ".csv.gz")):
                fn = "read_csv_auto"
            elif low.endswith((".json", ".ndjson", ".jsonl")):
                fn = "read_json_auto"
            else:
                fn = "read_parquet"
            # A path can't be a bound parameter in CREATE VIEW ... FROM fn(...);
            # inline it with SQL-quote escaping.
            safe = path.replace("'", "''")
            con.execute(f"CREATE VIEW {name} AS SELECT * FROM {fn}('{safe}')")
        result = con.sql(query).df()
    finally:
        con.close()

    src = ", ".join(sorted(connected) + sorted(aliases)) or "(none)"
    ctx.log(f"query over {src} → {len(result)} rows x {len(result.columns)} cols")
    return result
