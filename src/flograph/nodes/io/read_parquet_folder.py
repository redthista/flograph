"""Read Parquet (Folder)

Load every Parquet file (.parquet, .pq) in a folder and stack the results
into one DataFrame — the shape a dataset written out partition by partition
usually arrives in.

Needs one of the readers pandas supports, pyarrow or fastparquet, or polars.
All three come from Tools > Manage Packages; install one into a running app
and flograph must be restarted before the node can use it.

Row filters push down to the reader so filtered row groups are never loaded:
one `column op value` per line (ops: == != < <= > >= in not in; `in` takes a
comma-separated list), combined with AND. Values that look numeric are
compared as numbers. Lines starting with # are ignored. Together with
**Columns** these are what make the read itself cheaper, rather than merely
making the result smaller.

Connect a string to **path_input** to supply the folder at run time — a
non-empty value there wins over the *Folder* parameter.

**Include / exclude patterns** are comma-separated globs matched against file
names. **Add source file column** records which file each row came from,
which is how a `part-0001.parquet` layout keeps its partition identity.

**Search subfolders** walks the whole tree below the folder rather than
reading only its top level — which is the shape a Hive-partitioned dataset
arrives in, `year=2023/region=north/part-0001.parquet`. **Include / exclude
folders** then narrow the walk: globs matched against a subfolder's path
below the chosen folder (`year=2023/region=north`) or against its own name
(`region=north`), where include keeps only the folders that match and
exclude drops a folder together with everything under it. `*` crosses `/`,
so `year=2023*` covers everything below `year=2023`. A file pattern
containing a `/` is matched against the file's path below the folder instead
of its name, e.g. `year=2023/*.parquet`.

**Add folder column** records which subfolder each row came from — `.` for
the folder itself, otherwise a relative path like `year=2023/region=north`,
which is where a partitioned dataset keeps its partition keys. The values
are the path as written; splitting `key=value` back out into columns is a
job for String Manipulation downstream.

**Max rows** trims the stacked result; Parquet takes no row limit through
pandas, so it bounds what the rest of the flow carries rather than the read.
The polars engine does take one, and pushes it down per file.
"""
NODE = {
    "label": "Read Parquet (Folder)",
    "category": "IO",
    "version": "1.0",
    "inputs": [("path_input", "string", {"optional": True})],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "path", "type": "folder_open", "label": "Folder", "default": "",
     "placeholder": "folder holding the .parquet files"},
    {"name": "recursive", "type": "bool", "label": "Search subfolders",
     "default": False},
    {"name": "include_pattern", "type": "string", "label": "Include patterns",
     "default": "", "placeholder": "globs, e.g. part-*.parquet"},
    {"name": "exclude_pattern", "type": "string", "label": "Exclude patterns",
     "default": "", "placeholder": "globs, e.g. *_SUCCESS*, *tmp*"},
    {"name": "include_dirs", "type": "string", "label": "Include folders",
     "default": "", "placeholder": "globs, e.g. year=2023*, */region=north",
     "visible_when": {"recursive": ["True"]}},
    {"name": "exclude_dirs", "type": "string", "label": "Exclude folders",
     "default": "", "placeholder": "globs, e.g. _temporary*, *.tmp",
     "visible_when": {"recursive": ["True"]}},
    {"name": "add_source_file", "type": "bool", "label": "Add source file column",
     "default": False},
    {"name": "add_folder_column", "type": "bool", "label": "Add folder column",
     "default": False},
    {"name": "columns", "type": "columns", "label": "Columns",
     "default": "", "placeholder": "empty = all columns"},
    {"name": "nrows", "type": "int", "label": "Max rows (0 = all)",
     "default": 0, "min": 0},
    {"name": "engine", "type": "choice", "label": "Engine",
     "options": ["auto", "polars", "pyarrow", "fastparquet"], "default": "auto"},
    {"name": "dtype_backend", "type": "choice", "label": "Dtype backend",
     "options": ["default", "numpy_nullable", "pyarrow"], "default": "default"},
    {"name": "parallel_files", "type": "int", "label": "Parallel file reads (0 = auto)",
     "default": 0, "min": 0, "max": 32},
    {"name": "filters", "type": "text", "label": "Row filters",
     "default": "", "placeholder": "region == north\nunits >= 10"},
]

EXTENSIONS = (".parquet", ".pq")
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
    out = []
    for lineno, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.match(line)
        if not match:
            raise ValueError(
                f"row filters line {lineno}: expected 'column op value' "
                f"(ops: {' '.join(_FILTER_OPS)}), got {line!r}")
        op = match.group("op")
        raw = match.group("val")
        value = ([_value(v) for v in raw.split(",")] if op in ("in", "not in")
                 else _value(raw))
        out.append((match.group("col").strip(), op, value))
    return out


def run(ctx, path_input=None):
    import importlib.util
    import os

    import pandas as pd

    from flograph import folders

    p = ctx.params
    folder = (path_input.strip() if isinstance(path_input, str) and path_input.strip()
              else p["path"])
    if not folder:
        raise ValueError(
            "no folder selected — set 'Folder' in the node's properties, or "
            "connect a non-empty string to 'path_input'")

    include, exclude = p.get("include_pattern", ""), p.get("exclude_pattern", "")
    recursive = bool(p.get("recursive", False))
    # The folder patterns only mean anything while the walk is on, so a
    # subfolder rule left behind from a recursive run cannot silently empty
    # a flat one.
    include_dirs = p.get("include_dirs", "") if recursive else ""
    exclude_dirs = p.get("exclude_dirs", "") if recursive else ""
    files = folders.discover(folder, EXTENSIONS, include, exclude,
                             recursive=recursive, include_dirs=include_dirs,
                             exclude_dirs=exclude_dirs)
    folders.require_files(
        files, folder, EXTENSIONS,
        any(folders.patterns(raw)
            for raw in (include, exclude, include_dirs, exclude_dirs)),
        recursive)

    engine = p.get("engine", "auto")
    columns = [c.strip() for c in (p.get("columns") or "").split(",") if c.strip()]
    filters = _filters(p.get("filters"))
    nrows = int(p.get("nrows", 0) or 0)
    dtype_backend = p.get("dtype_backend", "default")

    if engine == "polars":
        if importlib.util.find_spec("polars") is None:
            raise RuntimeError(
                "the polars engine needs the polars package — install it "
                "from Tools > Manage Packages, then restart flograph")
        refused = sorted(name for name, was_set in {
            "Row filters": bool(filters),
            "Dtype backend": dtype_backend != "default",
        }.items() if was_set)
        if refused:
            raise ValueError(
                "the polars engine cannot apply "
                + ", ".join(repr(r) for r in refused)
                + " when reading Parquet — clear the option(s), or set Engine "
                  "to pyarrow")

        kwargs = {}
        if columns:
            kwargs["columns"] = columns
        if nrows:
            kwargs["n_rows"] = nrows

        def read_one(path):
            import polars as pl

            return pl.read_parquet(path, **kwargs).to_pandas()
    else:
        from flograph.packages import parquet_problem

        problem = parquet_problem(engine)
        if problem:
            raise RuntimeError(problem)

        kwargs = {}
        if columns:
            kwargs["columns"] = columns
        if filters:
            kwargs["filters"] = filters
        if engine != "auto":
            kwargs["engine"] = engine
        if dtype_backend != "default":
            kwargs["dtype_backend"] = dtype_backend

        def read_one(path):
            return pd.read_parquet(path, **kwargs)

        if engine == "auto":
            # Name it for the log and for the parallelism decision —
            # fastparquet holds the GIL where pyarrow does not.
            engine = ("pyarrow" if importlib.util.find_spec("pyarrow")
                      else "fastparquet")

    workers = folders.worker_count(p.get("parallel_files", 0), engine, len(files))
    ctx.log(f"{len(files)} file(s), {engine} engine"
            + (f", {workers} at a time" if workers > 1 else "")
            + (" (subfolders included)" if recursive else ""))

    add_source = p.get("add_source_file", False)
    add_folder = p.get("add_folder_column", False)
    frames = []
    for path, frame in folders.read_files(ctx, files, read_one, workers):
        at = 0
        if add_folder:
            frame.insert(at, "source_folder",
                         folders.relative_folder(path, folder))
            at += 1
        if add_source:
            frame.insert(at, "source_file", os.path.basename(path))
        frames.append(frame)

    table = folders.stack(ctx, frames, files, nrows)
    ctx.log(f"loaded {len(table)} rows x {len(table.columns)} columns "
            f"from {len(files)} file(s) via {engine}")
    return table
