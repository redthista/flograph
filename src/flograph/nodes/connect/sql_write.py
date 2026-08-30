"""SQL Write

Write a DataFrame into any database SQLAlchemy can reach, then pass the table
through so the flow can keep going. Same connection URLs as **SQL Query** —
keep the credentials in a `.env` file and reference `${env:DATABASE_URL}`.

**If exists** controls the collision:

    fail     — stop if the table is already there
    replace  — drop it and recreate from this frame
    append   — add these rows to what's there
    upsert   — replace rows whose key columns already match, insert the rest
               (needs **Key columns**)

`upsert` deletes the incoming key tuples then inserts, one transaction per
chunk. It's portable across every dialect and needs no unique constraint,
but it's for the hundreds-to-thousands range — for a bulk load, `append`
into a staging table and `MERGE` in SQL.
"""
NODE = {
    "label": "SQL Write",
    "category": "Connect",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "url", "type": "string", "label": "Connection URL",
     "default": "", "placeholder": "${env:DATABASE_URL}"},
    {"name": "table", "type": "string", "label": "Target table",
     "default": "", "placeholder": "schema.table or table"},
    {"name": "if_exists", "type": "choice", "label": "If exists",
     "options": ["fail", "replace", "append", "upsert"], "default": "append"},
    {"name": "keys", "type": "columns", "label": "Key columns",
     "default": "", "placeholder": "for upsert",
     "visible_when": {"if_exists": "upsert"}},
    {"name": "chunksize", "type": "int", "label": "Chunk size",
     "default": 1000, "min": 1, "max": 1_000_000},
]


def _split_schema(name):
    if "." in name:
        schema, _, tbl = name.rpartition(".")
        return schema, tbl
    return None, name


def run(ctx, table):
    from sqlalchemy import create_engine

    p = ctx.params
    url = (p.get("url") or "").strip()
    target = (p.get("table") or "").strip()
    if not url:
        raise ValueError("no connection URL — set 'Connection URL'")
    if not target:
        raise ValueError("no target table — set 'Target table'")
    schema, tbl = _split_schema(target)
    mode = p.get("if_exists", "append")
    chunk = int(p.get("chunksize", 1000) or 1000)

    engine = create_engine(url)
    try:
        if mode == "upsert":
            keys = [c.strip() for c in (p.get("keys") or "").split(",")
                    if c.strip()]
            if not keys:
                raise ValueError("upsert needs 'Key columns'")
            missing = [k for k in keys if k not in table.columns]
            if missing:
                raise ValueError(f"key column(s) {missing} not in the table")
            _upsert(engine, table, tbl, schema, keys, chunk, ctx)
        else:
            table.to_sql(tbl, engine, schema=schema, if_exists=mode,
                         index=False, chunksize=chunk, method="multi")
            ctx.log(f"{mode}: wrote {len(table)} rows to {target}")
    finally:
        engine.dispose()
    return table


def _upsert(engine, frame, tbl, schema, keys, chunk, ctx):
    """Delete-then-insert on the key tuples, one transaction per chunk.

    Portable across every dialect and needs no pre-existing unique
    constraint — the trade-off is one DELETE per batch, which is why this is
    for the hundreds-to-thousands range, not a bulk load.
    """
    from sqlalchemy import MetaData, Table, and_, tuple_

    # Create the table from the frame's shape if it isn't there yet.
    frame.head(0).to_sql(tbl, engine, schema=schema, if_exists="append",
                         index=False)
    meta = MetaData()
    sa_table = Table(tbl, meta, schema=schema, autoload_with=engine)
    key_cols = [sa_table.c[k] for k in keys]
    records = frame.astype(object).where(frame.notna(), None).to_dict("records")

    with engine.begin() as conn:
        for i in range(0, len(records), chunk):
            ctx.check_cancelled()
            batch = records[i:i + chunk]
            key_tuples = [tuple(r[k] for k in keys) for r in batch]
            if len(keys) == 1:
                conn.execute(sa_table.delete().where(
                    key_cols[0].in_([t[0] for t in key_tuples])))
            else:
                conn.execute(sa_table.delete().where(
                    tuple_(*key_cols).in_(key_tuples)))
            conn.execute(sa_table.insert(), batch)
    ctx.log(f"upsert: merged {len(records)} rows into {tbl} on {', '.join(keys)}")
