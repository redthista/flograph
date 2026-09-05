"""Read CSV (Folder)

Load every CSV in a folder and stack the results into one DataFrame.
Compressed files (.gz, .zip, .bz2, .xz, .zst) count as CSVs and are
decompressed as they are read, so `sales.csv.gz` is picked up alongside
`sales.csv`.

Separator accepts \\t for tab and 'auto' to sniff the delimiter per file —
useful for a folder of exports that do not all agree. Column types take one
`column = dtype` per line; lines starting with # are ignored, and the types
are applied while parsing, so a column declared `string` keeps its leading
zeros.

Connect a string to **path_input** to supply the folder at run time — a
non-empty value there wins over the *Folder* parameter.

**Include / exclude patterns** are comma-separated globs matched against file
names: include keeps only what matches (blank = keep everything), exclude
then drops what matches. **Add source file column** records which file each
row came from — worth having when the file name carries the month or region
that is not inside the data.

**Search subfolders** walks the whole tree below the folder rather than
reading only its top level. **Include / exclude folders** then narrow that
walk: they are globs matched against a subfolder's path below the chosen
folder (`2023/q1`) or against its own name (`q1`), include keeps only the
folders that match, and exclude drops a folder together with everything
under it. `*` crosses `/`, so `2023*` covers everything below `2023`. A file
pattern containing a `/` is matched against the file's path below the folder
instead of its name, e.g. `2023/*.csv`.

**Add folder column** records which subfolder each row came from — `.` for
the folder itself, otherwise a relative path like `2023/q1`.

**Max rows per file** keeps the first N rows of each file, so reading a
folder gives a slice of every file rather than all of the first one.

**Engine**: *polars* reads with a Rust parser and hands back a pandas frame;
pandas' own *c* parser is already fast and also releases the GIL, so both
overlap properly across files. *pyarrow* is fastest per file but honours
fewer of the options below. polars refuses by name anything it cannot apply
rather than quietly ignoring it.
"""
NODE = {
    "label": "Read CSV (Folder)",
    "category": "IO",
    "version": "1.0",
    "inputs": [("path_input", "string", {"optional": True})],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "path", "type": "folder_open", "label": "Folder", "default": "",
     "placeholder": "folder holding the CSV files"},
    {"name": "sep", "type": "string", "label": "Separator", "default": ",",
     "placeholder": ", ; \\t or auto"},
    {"name": "recursive", "type": "bool", "label": "Search subfolders",
     "default": False},
    {"name": "include_pattern", "type": "string", "label": "Include patterns",
     "default": "", "placeholder": "globs, e.g. sales_*.csv, *2023*"},
    {"name": "exclude_pattern", "type": "string", "label": "Exclude patterns",
     "default": "", "placeholder": "globs, e.g. *draft*, *tmp*"},
    {"name": "include_dirs", "type": "string", "label": "Include folders",
     "default": "", "placeholder": "globs, e.g. 2023*, */actuals",
     "visible_when": {"recursive": ["True"]}},
    {"name": "exclude_dirs", "type": "string", "label": "Exclude folders",
     "default": "", "placeholder": "globs, e.g. archive*, *_old",
     "visible_when": {"recursive": ["True"]}},
    {"name": "add_source_file", "type": "bool", "label": "Add source file column",
     "default": False},
    {"name": "add_folder_column", "type": "bool", "label": "Add folder column",
     "default": False},
    {"name": "header", "type": "bool", "label": "First row is header",
     "default": True},
    {"name": "encoding", "type": "string", "label": "Encoding", "default": "",
     "placeholder": "auto (utf-8)"},
    {"name": "columns", "type": "string", "label": "Columns",
     "default": "", "placeholder": "empty = all columns"},
    {"name": "index_col", "type": "string", "label": "Index column",
     "default": "", "placeholder": "name or 0-based position"},
    {"name": "skiprows", "type": "int", "label": "Skip rows at start",
     "default": 0, "min": 0},
    {"name": "nrows", "type": "int", "label": "Max rows per file (0 = all)",
     "default": 0, "min": 0},
    {"name": "decimal", "type": "string", "label": "Decimal mark", "default": "."},
    {"name": "thousands", "type": "string", "label": "Thousands mark",
     "default": "", "placeholder": "none"},
    {"name": "quotechar", "type": "string", "label": "Quote char", "default": '"'},
    {"name": "comment", "type": "string", "label": "Comment char",
     "default": "", "placeholder": "e.g. # — rest of line is ignored"},
    {"name": "na_values", "type": "string", "label": "Extra missing values",
     "default": "", "placeholder": "comma separated, e.g. -, n/a, ?"},
    {"name": "parse_dates", "type": "string", "label": "Parse dates",
     "default": "", "placeholder": "comma separated columns"},
    {"name": "skip_blank_lines", "type": "bool", "label": "Skip blank lines",
     "default": True},
    {"name": "on_bad_lines", "type": "choice", "label": "On bad lines",
     "options": ["error", "warn", "skip"], "default": "error"},
    {"name": "engine", "type": "choice", "label": "Engine",
     "options": ["auto", "polars", "c", "python", "pyarrow"], "default": "auto"},
    {"name": "parallel_files", "type": "int", "label": "Parallel file reads (0 = auto)",
     "default": 0, "min": 0, "max": 32},
    {"name": "dtypes", "type": "text", "label": "Column types",
     "default": "", "placeholder": "id = int64\nname = string"},
]

EXTENSIONS = (".csv", ".tsv", ".txt", ".psv")


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


# Only the mappings that are unambiguous — a guessed dtype is a silently
# wrong column, where an error is merely an error.
_POLARS_DTYPES = {
    "string": "String", "str": "String", "object": "String",
    "int64": "Int64", "int32": "Int32", "int16": "Int16", "int8": "Int8",
    "uint64": "UInt64", "uint32": "UInt32",
    "float64": "Float64", "float32": "Float32",
    "bool": "Boolean", "boolean": "Boolean",
}


def _polars_schema(dtypes):
    import polars as pl

    schema = {}
    for column, dtype in dtypes.items():
        name = _POLARS_DTYPES.get(str(dtype).lower())
        if name is None:
            raise ValueError(
                f"the polars engine has no unambiguous equivalent for column "
                f"type {dtype!r} on {column!r} — set Engine to c, or use one "
                f"of: {', '.join(sorted(_POLARS_DTYPES))}")
        schema[column] = getattr(pl, name)
    return schema


def run(ctx, path_input=None):
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

    separator = (p.get("sep") or ",").replace("\\t", "\t")
    engine = p.get("engine", "auto")
    nrows = int(p.get("nrows", 0) or 0)
    skiprows = int(p.get("skiprows", 0) or 0)
    columns = _list(p.get("columns"))
    encoding = (p.get("encoding") or "").strip()
    na_values = _list(p.get("na_values"))
    parse_dates = _list(p.get("parse_dates"))
    dtypes = _mapping(p.get("dtypes"))
    decimal = p.get("decimal") or "."
    thousands = p.get("thousands") or ""
    index_col = (p.get("index_col") or "").strip()
    on_bad_lines = p.get("on_bad_lines", "error")
    skip_blank = p.get("skip_blank_lines", True)

    if engine == "auto":
        # pandas' c parser: it honours every option here and its tokenizer
        # releases the GIL, so it already overlaps across files.
        engine = "c"
    if engine == "polars":
        import importlib.util

        if importlib.util.find_spec("polars") is None:
            raise RuntimeError(
                "the polars engine needs the polars package — install it "
                "from Tools > Manage Packages, then restart flograph")

        refused = sorted(name for name, was_set in {
            "Separator = auto (sniffing)": separator == "auto",
            "Thousands mark": bool(thousands),
            "On bad lines": on_bad_lines != "error",
            "Skip blank lines (off)": not skip_blank,
        }.items() if was_set)
        if refused:
            raise ValueError(
                "the polars engine cannot apply "
                + ", ".join(repr(r) for r in refused)
                + " when reading CSV — clear the option(s), or set Engine to c")
        if decimal not in (".", ","):
            raise ValueError(
                f"the polars engine reads a decimal mark of '.' or ',', not "
                f"{decimal!r} — set Engine to c")
        if encoding and encoding.replace("-", "").lower() not in ("utf8", "utf8lossy"):
            raise ValueError(
                f"the polars engine reads utf-8 only, not {encoding!r} — set "
                f"Engine to c")

        kwargs = {"separator": separator, "has_header": bool(p.get("header", True)),
                  "decimal_comma": decimal == ","}
        if skiprows:
            kwargs["skip_rows"] = skiprows
        if nrows:
            kwargs["n_rows"] = nrows
        if columns:
            kwargs["columns"] = columns
        if na_values:
            kwargs["null_values"] = na_values
        if (p.get("quotechar") or '"') != '"':
            kwargs["quote_char"] = p["quotechar"]
        if (p.get("comment") or "").strip():
            kwargs["comment_prefix"] = p["comment"].strip()[0]
        if dtypes:
            kwargs["schema_overrides"] = _polars_schema(dtypes)

        def read_one(path):
            import polars as pl

            return pl.read_csv(path, **kwargs).to_pandas()
    else:
        kwargs = {"header": 0 if p.get("header", True) else None,
                  "skip_blank_lines": skip_blank}
        pandas_engine = engine
        if separator == "auto":
            kwargs["sep"] = None       # sniffing needs the python engine
            pandas_engine = "python"
        else:
            kwargs["sep"] = separator
        kwargs["engine"] = pandas_engine
        if encoding:
            kwargs["encoding"] = encoding
        if columns:
            kwargs["usecols"] = columns
        if index_col:
            kwargs["index_col"] = int(index_col) if index_col.isdigit() else index_col
        if skiprows:
            kwargs["skiprows"] = skiprows
        if nrows:
            kwargs["nrows"] = nrows
        if decimal != ".":
            kwargs["decimal"] = decimal
        if thousands:
            kwargs["thousands"] = thousands
        if (p.get("quotechar") or '"') != '"':
            kwargs["quotechar"] = p["quotechar"]
        if (p.get("comment") or "").strip():
            kwargs["comment"] = p["comment"].strip()[0]
        if na_values:
            kwargs["na_values"] = na_values
        if parse_dates:
            kwargs["parse_dates"] = parse_dates
        if dtypes:
            kwargs["dtype"] = dtypes
        if on_bad_lines != "error":
            kwargs["on_bad_lines"] = on_bad_lines
        engine = pandas_engine

        def read_one(path):
            return pd.read_csv(path, **kwargs)

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
        frames.append(folders.cap_rows(frame, nrows))

    table = folders.stack(ctx, frames, files)

    if engine == "polars":
        missing = [c for c in parse_dates if c not in table.columns]
        if missing:
            raise ValueError(f"parse dates: no such column(s): {', '.join(missing)}")
        for column in parse_dates:
            table[column] = pd.to_datetime(table[column])
        if index_col:
            table = table.set_index(
                table.columns[int(index_col)] if index_col.isdigit() else index_col)

    ctx.log(f"loaded {len(table)} rows x {len(table.columns)} columns "
            f"from {len(files)} file(s) via {engine}")
    return table
