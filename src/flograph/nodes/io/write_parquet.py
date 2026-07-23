"""Write Parquet

Write a DataFrame to a Parquet file (needs pyarrow). Passes the table
through so the pipeline can continue.

Partition columns turn the output into a directory tree with one folder
level per column value (hive-style, e.g. `region=north/`), which the
Read Parquet node's row filters can then skip entirely.
"""
NODE = {
    "label": "Write Parquet",
    "category": "IO",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "path", "type": "file_save", "label": "Output file", "default": ""},
    {"name": "index", "type": "bool", "label": "Write index", "default": False},
    {"name": "compression", "type": "choice", "label": "Compression",
     "options": ["snappy", "gzip", "brotli", "zstd", "lz4", "none"],
     "default": "snappy"},
    {"name": "partition_cols", "type": "columns", "label": "Partition by",
     "default": "", "placeholder": "writes a folder per value"},
    {"name": "engine", "type": "choice", "label": "Engine",
     "options": ["auto", "pyarrow", "fastparquet"], "default": "auto"},
]


def run(ctx, table):
    p = ctx.params
    path = p["path"]
    if not path:
        raise ValueError("no output file set — choose one in the node's properties")

    kwargs = {"index": p.get("index", False)}
    compression = p.get("compression", "snappy")
    if compression != "snappy":
        kwargs["compression"] = None if compression == "none" else compression
    partition_cols = [c.strip() for c in (p.get("partition_cols") or "").split(",")
                      if c.strip()]
    if partition_cols:
        missing = [c for c in partition_cols if c not in table.columns]
        if missing:
            raise ValueError(f"partition columns not in table: {missing}")
        kwargs["partition_cols"] = partition_cols
    if p.get("engine", "auto") != "auto":
        kwargs["engine"] = p["engine"]

    table.to_parquet(path, **kwargs)
    ctx.log(f"wrote {len(table)} rows to {path}"
            + (f" partitioned by {', '.join(partition_cols)}"
               if partition_cols else ""))
    return table
