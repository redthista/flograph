"""Read Parquet

Load a Parquet file into a DataFrame. Needs one of the two engines pandas
supports, pyarrow or fastparquet — both come with the 'parquet' extra, and
either can be installed from Tools > Manage Packages. **Engine** picks
between them; **auto** prefers pyarrow and falls back to fastparquet.
Install one into a running app and flograph must be restarted before the
node can use it.

Row filters push down to the reader so filtered row groups are never
loaded: one `column op value` per line (ops: == != < <= > >= in
not in; `in` takes a comma-separated list), combined with AND. Values
that look numeric are compared as numbers. Lines starting with # are
ignored.

**Max rows** keeps the first N rows, for building a flow against a slice of
something large. It trims after the read rather than during it — pandas'
Parquet reader takes no row limit — so it bounds what the rest of the flow
carries, not the read. Columns and Row filters are the ones that make the
read itself cheaper.
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
    {"name": "filters", "type": "text", "label": "Row filters",
     "default": "", "placeholder": "region == north\nunits >= 10"},
    {"name": "engine", "type": "choice", "label": "Engine",
     "options": ["auto", "pyarrow", "fastparquet"], "default": "auto"},
    {"name": "dtype_backend", "type": "choice", "label": "Dtype backend",
     "options": ["default", "numpy_nullable", "pyarrow"], "default": "default"},
    {"name": "nrows", "type": "int", "label": "Max rows (0 = all)",
     "default": 0, "min": 0},
]

_FILTER_OPS = ("not in", "in", "==", "!=", "<=", ">=", "<", ">")


def _value(raw):
    raw = raw.strip().strip("'\"")
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _filters(text):
    import re

    pattern = re.compile(
        r"^(?P<col>.+?)\s+(?P<op>not in|in|==|!=|<=|>=|<|>)\s+(?P<val>.+)$")
    filters = []
    for lineno, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.match(line)
        if not match:
            ops = " ".join(_FILTER_OPS)
            raise ValueError(f"row filters line {lineno}: expected "
                             f"'column op value' (ops: {ops}), got {line!r}")
        op = match.group("op")
        raw = match.group("val")
        value = ([_value(v) for v in raw.split(",")] if op in ("in", "not in")
                 else _value(raw))
        filters.append((match.group("col").strip(), op, value))
    return filters


def run(ctx):
    import pandas as pd

    from flograph.packages import parquet_problem

    p = ctx.params
    problem = parquet_problem(p.get("engine", "auto"))
    if problem:
        raise RuntimeError(problem)

    path = p["path"]
    if not path:
        raise ValueError("no file selected — set 'Parquet file' in the node's properties")

    kwargs = {}
    columns_raw = (p.get("columns") or "").strip()
    if columns_raw:
        kwargs["columns"] = [c.strip() for c in columns_raw.split(",") if c.strip()]
    filters = _filters(p.get("filters"))
    if filters:
        kwargs["filters"] = filters
    if p.get("engine", "auto") != "auto":
        kwargs["engine"] = p["engine"]
    if p.get("dtype_backend", "default") != "default":
        kwargs["dtype_backend"] = p["dtype_backend"]

    table = pd.read_parquet(path, **kwargs)
    nrows = int(p.get("nrows", 0) or 0)
    if nrows and len(table) > nrows:
        # Trimmed after reading, not while: pandas' Parquet reader has no
        # row limit to push down, so this bounds what the rest of the flow
        # carries rather than what the read itself costs. Row filters and
        # Columns above *do* push down — reach for those first on a file
        # too big to read at all.
        table = table.head(nrows).copy()
        ctx.log(f"trimmed to the first {nrows} rows")
    ctx.log(f"loaded {len(table)} rows x {len(table.columns)} columns")
    return table
