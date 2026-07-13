"""Read Parquet

Load a Parquet file into a DataFrame (needs pyarrow — install it from
Tools > Manage Packages if missing).
"""
NODE = {
    "label": "Read Parquet",
    "category": "IO",
    "inputs": [],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "path", "type": "file_open", "label": "Parquet file", "default": ""},
    {"name": "columns", "type": "columns", "label": "Columns",
     "default": "", "placeholder": "empty = all columns"},
]


def run(ctx):
    import pandas as pd

    path = ctx.params["path"]
    if not path:
        raise ValueError("no file selected — set 'Parquet file' in the node's properties")
    columns_raw = ctx.params["columns"].strip()
    columns = ([c.strip() for c in columns_raw.split(",") if c.strip()]
               if columns_raw else None)
    table = pd.read_parquet(path, columns=columns)
    ctx.log(f"loaded {len(table)} rows x {len(table.columns)} columns")
    return table
