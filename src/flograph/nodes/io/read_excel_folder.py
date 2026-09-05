"""Read Excel (Folder)

Load a sheet from every Excel workbook (.xlsx, .xlsm, .xls, .xlsb, .ods) in a
folder and stack the results into one DataFrame. Excel's own `~$…` lock files
are ignored.

Sheet takes a name, a 0-based index, or * for every sheet, stacked with a
leading `sheet` column. Columns takes names or Excel letter ranges (e.g.
`A:C,F`). Column types take one `column = dtype` per line; lines starting
with # are ignored.

Connect a string to **path_input** to supply the folder at run time — a
non-empty value there wins over the *Folder* parameter, so one flow can be
pointed at a different folder per run.

**Include / exclude patterns** are comma-separated globs matched against file
names: include keeps only what matches (blank = keep everything), exclude
then drops what matches. A pattern containing a `/` is matched against the
file's path below the folder instead, e.g. `2023/*.xlsx`.

**Search subfolders** walks the whole tree below the folder rather than
reading only its top level. **Include / exclude folders** then narrow that
walk: they are globs matched against a subfolder's path below the chosen
folder (`2023/q1`) or against its own name (`q1`), include keeps only the
folders that match, and exclude drops a folder together with everything
under it. `*` crosses `/`, so `2023*` covers everything below `2023`.

**Add source file column** records which workbook each row came from, and
**Add folder column** which subfolder — `.` for the folder itself,
otherwise a relative path like `2023/q1`.

**Max rows per sheet** keeps the first N rows of each sheet read, so a
folder of workbooks gives a slice of every one of them rather than all of
the first. With *Sheet* set to `*` the cap is per sheet, not per workbook.

**Header** — ticked, row 0 holds the column names. Unticked, *Header row*
names the 0-based row that does; leave it blank for no header at all.

**Engine** is where the time goes on a folder of any size. *calamine* is a
Rust reader that produces the same frame as *openpyxl* roughly 6x quicker.
*polars* is quicker still and releases the GIL, so whole workbooks overlap.
*auto* picks the fastest one installed. **Parallel file reads** is how many
are parsed at once — 0 lets the engine decide, and openpyxl stays at one
because it is pure Python and gains nothing from threads.
"""
NODE = {
    "label": "Read Excel (Folder)",
    "category": "IO",
    "version": "1.0",
    # Optional: a required input that nobody has wired up blocks the node
    # from ever running, which is not what a fallback port wants.
    "inputs": [("path_input", "string", {"optional": True})],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "path", "type": "folder_open", "label": "Folder", "default": "",
     "placeholder": "folder holding the workbooks"},
    {"name": "sheet_name", "type": "string", "label": "Sheet",
     "default": "0", "placeholder": "name, 0-based index, or * for all"},
    {"name": "recursive", "type": "bool", "label": "Search subfolders",
     "default": False},
    {"name": "include_pattern", "type": "string", "label": "Include patterns",
     "default": "", "placeholder": "globs, e.g. sales_*.xlsx, *2023*"},
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
    {"name": "header_row", "type": "string", "label": "Header row (0-based)",
     "default": "", "placeholder": "blank = no header",
     "visible_when": {"header": ["False"]}},
    {"name": "skiprows", "type": "int", "label": "Skip rows at start",
     "default": 0, "min": 0},
    {"name": "nrows", "type": "int", "label": "Max rows per sheet (0 = all)",
     "default": 0, "min": 0},
    {"name": "columns", "type": "string", "label": "Columns",
     "default": "", "placeholder": "names or ranges like A:C,F; empty = all"},
    {"name": "index_col", "type": "string", "label": "Index column",
     "default": "", "placeholder": "name or 0-based position"},
    {"name": "na_values", "type": "string", "label": "Extra missing values",
     "default": "", "placeholder": "comma separated, e.g. -, n/a, ?"},
    {"name": "parse_dates", "type": "string", "label": "Parse dates",
     "default": "", "placeholder": "comma separated columns"},
    {"name": "decimal", "type": "string", "label": "Decimal mark", "default": "."},
    {"name": "thousands", "type": "string", "label": "Thousands mark",
     "default": "", "placeholder": "none"},
    {"name": "engine", "type": "choice", "label": "Engine",
     "options": ["auto", "polars", "calamine", "openpyxl", "xlrd", "pyxlsb", "odf"],
     "default": "auto"},
    {"name": "parallel_files", "type": "int", "label": "Parallel file reads (0 = auto)",
     "default": 0, "min": 0, "max": 32},
    {"name": "dtypes", "type": "text", "label": "Column types",
     "default": "", "placeholder": "id = int64\nname = string"},
]

EXTENSIONS = (".xlsx", ".xlsm", ".xls", ".xlsb", ".ods")

# engine -> the third-party module that has to be importable. NOT the pandas
# shim: `pandas.io.excel._calamine` imports cleanly whether or not
# python-calamine is installed (it names it only under TYPE_CHECKING, and
# asks for it at call time), so probing the shim reports every engine as
# present and picks one that fails halfway through the read.
_ENGINE_MODULE = {
    "calamine": "python_calamine", "openpyxl": "openpyxl", "xlrd": "xlrd",
    "pyxlsb": "pyxlsb", "odf": "odf", "polars": "polars",
}
_ENGINE_ORDER = ["polars", "calamine", "openpyxl", "xlrd", "pyxlsb", "odf"]


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


def _have(module):
    import importlib.util

    return importlib.util.find_spec(module) is not None


def _resolve_engine(requested):
    if requested and requested != "auto":
        module = _ENGINE_MODULE.get(requested)
        if module and not _have(module):
            raise RuntimeError(
                f"the {requested} engine needs the {module} package — install "
                f"it from Tools > Manage Packages, then restart flograph")
        if requested == "polars" and not _have("fastexcel"):
            raise RuntimeError(
                "the polars engine reads Excel through fastexcel — install "
                "fastexcel from Tools > Manage Packages, then restart flograph")
        return requested
    for engine in _ENGINE_ORDER:
        if not _have(_ENGINE_MODULE[engine]):
            continue
        if engine == "polars" and not _have("fastexcel"):
            continue
        return engine
    raise RuntimeError(
        "no Excel engine is installed — install one of "
        + ", ".join(_ENGINE_MODULE[e] for e in _ENGINE_ORDER)
        + " from Tools > Manage Packages")


def _header(p):
    """(header for pandas, header row for polars)."""
    if p.get("header", True):
        return 0, None
    raw = (p.get("header_row") or "").strip()
    if not raw:
        return None, None
    try:
        row = int(raw)
    except ValueError:
        raise ValueError(
            f"header row must be a whole 0-based row number, got {raw!r}")
    if row < 0:
        raise ValueError("header row cannot be negative")
    return row, row


def _sheet(p):
    raw = (p.get("sheet_name") or "0").strip() or "0"
    if raw == "*":
        return raw, None
    if raw.lstrip("-").isdigit():
        return raw, int(raw)
    return raw, raw


def run(ctx, path_input=None):
    import pandas as pd

    from flograph import folders

    p = ctx.params
    # An empty string on the port means "nothing to say", not "read the
    # folder called ''" — otherwise a disconnected upstream blanks the node.
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

    label, sheet_arg = _sheet(p)
    header_arg, header_row = _header(p)
    dtypes = _mapping(p.get("dtypes"))
    engine = _resolve_engine(p.get("engine", "auto"))
    add_source = p.get("add_source_file", False)
    add_folder = p.get("add_folder_column", False)
    nrows = int(p.get("nrows", 0) or 0)
    skiprows = int(p.get("skiprows", 0) or 0)
    columns_raw = (p.get("columns") or "").strip()
    na_values = _list(p.get("na_values"))
    parse_dates = _list(p.get("parse_dates"))
    decimal = p.get("decimal") or "."
    thousands = p.get("thousands") or ""
    index_col = (p.get("index_col") or "").strip()

    if engine == "polars":
        refused = sorted(label_ for label_, was_set in {
            "Extra missing values": bool(na_values),
            "Decimal mark": decimal != ".",
            "Thousands mark": bool(thousands),
        }.items() if was_set)
        if refused:
            raise ValueError(
                "the polars engine cannot apply "
                + ", ".join(repr(r) for r in refused)
                + " when reading Excel — clear the option(s), or pick the "
                  "calamine engine, which honours them and is still fast")

        read_options = {}
        kwargs = {}
        if header_row is not None:
            # polars raises ParameterCollisionError if has_header is given
            # beside read_options["header_row"], so it is one or the other.
            read_options["header_row"] = header_row
        else:
            kwargs["has_header"] = header_arg == 0
        if skiprows:
            read_options["skip_rows"] = skiprows
        if nrows:
            read_options["n_rows"] = nrows
        if columns_raw:
            if ":" in columns_raw:
                read_options["use_columns"] = folders.normalise_letter_range(columns_raw)
            else:
                kwargs["columns"] = _list(columns_raw)
        if read_options:
            kwargs["read_options"] = read_options

        def read_one(path):
            import polars as pl

            if sheet_arg is None:
                return [(name, frame.to_pandas()) for name, frame
                        in pl.read_excel(path, sheet_id=0, **kwargs).items()]
            # polars numbers sheets from 1; this node counts from 0, as pandas does
            extra = ({"sheet_id": sheet_arg + 1} if isinstance(sheet_arg, int)
                     else {"sheet_name": sheet_arg})
            return [(None, pl.read_excel(path, **kwargs, **extra).to_pandas())]
    else:
        kwargs = {"header": header_arg}
        if skiprows:
            kwargs["skiprows"] = skiprows
        if nrows:
            kwargs["nrows"] = nrows
        if columns_raw:
            kwargs["usecols"] = (columns_raw if ":" in columns_raw
                                 else _list(columns_raw))
        if index_col:
            kwargs["index_col"] = int(index_col) if index_col.isdigit() else index_col
        if na_values:
            kwargs["na_values"] = na_values
        if parse_dates:
            kwargs["parse_dates"] = parse_dates
        if dtypes:
            kwargs["dtype"] = dtypes
        if decimal != ".":
            kwargs["decimal"] = decimal
        if thousands:
            kwargs["thousands"] = thousands

        def read_one(path):
            if sheet_arg is None:
                with pd.ExcelFile(path, engine=engine) as workbook:
                    return [(name, workbook.parse(name, **kwargs))
                            for name in workbook.sheet_names]
            return [(None, pd.read_excel(path, sheet_name=sheet_arg,
                                         engine=engine, **kwargs))]

    workers = folders.worker_count(p.get("parallel_files", 0), engine, len(files))
    ctx.log(f"{len(files)} workbook(s), sheet {label!r}, {engine} engine"
            + (f", {workers} at a time" if workers > 1 else "")
            + (" (subfolders included)" if recursive else ""))

    frames = []
    import os

    for path, sheets in folders.read_files(ctx, files, read_one, workers):
        name = os.path.basename(path)
        where = folders.relative_folder(path, folder)
        for sheet_name, frame in sheets:
            at = 0
            if sheet_name is not None:
                frame.insert(at, "sheet", sheet_name)
                at += 1
            if add_folder:
                frame.insert(at, "source_folder", where)
                at += 1
            if add_source:
                frame.insert(at, "source_file", name)
            # Per sheet rather than per file: a sheet is the unit that
            # becomes a table here, and it is what both engines already push
            # the limit into when they read.
            frames.append(folders.cap_rows(frame, nrows))

    table = folders.stack(ctx, frames, files)

    # What the polars path could not push into the read, applied once at the
    # end so both engines look the same from outside.
    if engine == "polars":
        missing = [c for c in parse_dates if c not in table.columns]
        if missing:
            raise ValueError(f"parse dates: no such column(s): {', '.join(missing)}")
        for column in parse_dates:
            table[column] = pd.to_datetime(table[column])
        if dtypes:
            table = table.astype(dtypes)
        if index_col:
            table = table.set_index(
                table.columns[int(index_col)] if index_col.isdigit() else index_col)

    ctx.log(f"loaded {len(table)} rows x {len(table.columns)} columns "
            f"from {len(files)} workbook(s) via {engine}")
    return table
