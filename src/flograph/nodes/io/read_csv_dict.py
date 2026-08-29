"""Read CSV (Folder → Dict)

Load every CSV in a folder and hand back a **dictionary** of
`file name -> DataFrame`, one entry per file, instead of stacking them into
one table. Reach for this when the files are not one thing sliced up — a
folder holding `customers.csv`, `orders.csv` and `products.csv` has three
schemas and no sensible concatenation — or when a later step needs to know
which file it is looking at while it works.

If the files *are* one table split across months or regions, use **Read CSV
(Folder)** instead: it stacks them and can add a source-file column.

The dictionary comes out of the **tables** port, which carries an object
rather than a table, so it does not plug into Show Table or the transform
nodes. Its consumer is a **Python Script** node, where the dict arrives as an
ordinary `dict` and `for name, df in tables.items():` does the rest. Entries
are in file-name order, and an empty folder is an error rather than an empty
dict.

**Dictionary key** chooses what the keys are: the file name (`sales.csv`),
the name with its extension dropped (`sales` — handy when the key is about to
become a sheet name or a label), or the full path. Names are unique within a
folder; stems can collide (`sales.csv` and `sales.tsv`) and that is reported
rather than letting one file quietly overwrite the other.

Everything else works as it does in Read CSV (Folder): compressed files
(.gz, .zip, .bz2, .xz, .zst) count as CSVs, separator accepts \\t for tab and
'auto' to sniff per file, include/exclude are comma-separated globs matched
against file names, and column types take one `column = dtype` per line.
**Max rows per file** caps each file separately, since here each file is its
own frame.

Connect a string to **path_input** to supply the folder at run time — a
non-empty value there wins over the *Folder* parameter.

**Engine**: *polars* reads with a Rust parser and hands back a pandas frame;
pandas' own *c* parser is already fast and also releases the GIL, so both
overlap properly across files. *pyarrow* is fastest per file but honours
fewer of the options below. polars refuses by name anything it cannot apply
rather than quietly ignoring it.
"""
NODE = {
    "label": "Read CSV (Folder → Dict)",
    "category": "IO",
    "version": "1.0",
    "inputs": [("path_input", "string", {"optional": True})],
    "outputs": [("tables", "object")],
}
PARAMS = [
    {"name": "path", "type": "folder_open", "label": "Folder", "default": "",
     "placeholder": "folder holding the CSV files"},
    {"name": "key", "type": "choice", "label": "Dictionary key",
     "options": ["file name", "name without extension", "full path"],
     "default": "file name"},
    {"name": "sep", "type": "string", "label": "Separator", "default": ",",
     "placeholder": ", ; \\t or auto"},
    {"name": "include_pattern", "type": "string", "label": "Include patterns",
     "default": "", "placeholder": "globs, e.g. sales_*.csv, *2023*"},
    {"name": "exclude_pattern", "type": "string", "label": "Exclude patterns",
     "default": "", "placeholder": "globs, e.g. *draft*, *tmp*"},
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


def _keys(files, style):
    """The dictionary key for each file, in file order.

    A folder listing cannot repeat a file name, but dropping the extension
    can make two of them the same — and a dict would keep whichever was read
    last, losing a whole file without a word. So the collision is named.
    """
    import os

    if style == "full path":
        return [os.path.abspath(path) for path in files]
    names = [os.path.basename(path) for path in files]
    if style != "name without extension":
        return names

    stems, seen = [], {}
    for name in names:
        stem = os.path.splitext(name)[0]
        seen.setdefault(stem, []).append(name)
        stems.append(stem)
    clashes = {stem: got for stem, got in seen.items() if len(got) > 1}
    if clashes:
        detail = "; ".join(f"{stem!r} <- {', '.join(got)}"
                           for stem, got in sorted(clashes.items()))
        raise ValueError(
            f"dropping the extension makes these files share a key: {detail} "
            f"— set 'Dictionary key' to 'file name', or exclude one of them")
    return stems


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
    files = folders.discover(folder, EXTENSIONS, include, exclude)
    folders.require_files(files, folder, EXTENSIONS,
                          bool(folders.patterns(include) or folders.patterns(exclude)))
    # Before a byte is read, so a key clash costs nothing to find out about.
    keys = _keys(files, p.get("key", "file name"))

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

        def parse(path):
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

        def parse(path):
            return pd.read_csv(path, **kwargs)

    def read_one(path):
        # One bad file in fifty, and "No columns to parse from file" on its
        # own does not say which of the fifty. Here the file *is* the
        # identity of a result, so it belongs in the message. NodeCancelled
        # is raised on the consuming side, never in here, so catching
        # Exception cannot swallow a Stop.
        try:
            return parse(path)
        except Exception as exc:
            raise ValueError(f"{os.path.basename(path)}: {exc}") from exc

    workers = folders.worker_count(p.get("parallel_files", 0), engine, len(files))
    ctx.log(f"{len(files)} file(s), {engine} engine"
            + (f", {workers} at a time" if workers > 1 else ""))

    tables, rows = {}, 0
    reads = folders.read_files(ctx, files, read_one, workers)
    for key, (path, frame) in zip(keys, reads):
        if engine == "polars":
            missing = [c for c in parse_dates if c not in frame.columns]
            if missing:
                raise ValueError(f"parse dates: no such column(s) in "
                                 f"{os.path.basename(path)}: {', '.join(missing)}")
            for column in parse_dates:
                frame[column] = pd.to_datetime(frame[column])
            if index_col:
                frame = frame.set_index(
                    frame.columns[int(index_col)] if index_col.isdigit() else index_col)
        tables[key] = frame
        rows += len(frame)
    ctx.progress(1.0)

    ctx.log(f"loaded {len(tables)} table(s), {rows} rows in total, via {engine}")
    # Named, not bare. A single output normally takes a bare return, but the
    # value here *is* a dict, and a bare dict whose keys happen to match the
    # port names is read as the port mapping instead — one file called
    # tables.csv, keyed by stem, and the node would quietly emit that one
    # frame rather than the dictionary. The named form is never ambiguous.
    return {"tables": tables}
