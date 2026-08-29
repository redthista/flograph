"""Read File

Load a table from a file — CSV, Excel, JSON, Parquet or SQLite — with one
node. **Format** picks the reader; **auto** decides from the file's
extension and says which it chose in the log. Options that belong to a
format only appear once that format is chosen, so pick the format to tidy
the panel down to what applies.

**Engine** picks what does the reading. *pandas* is the safe default and
honours every option below. *polars* reads the file with a Rust parser and
hands back a pandas frame — several times faster and it releases the GIL, so
several Read File nodes actually run in parallel rather than taking turns.
It supports fewer options; anything it cannot honour is refused with a
message naming the option rather than quietly ignored.

**Excel engine** is the one worth changing on a slow flow: *calamine* is a
Rust reader, typically ~6x faster than *openpyxl* on the same workbook and
producing the same frame. **auto** uses it when `python-calamine` is
installed and falls back to openpyxl when it is not — install it from
Tools > Manage Packages.

Column types take one `column = dtype` per line; lines starting with # are
ignored. They are applied while parsing, not after, so a column declared
`string` keeps leading zeros.
"""
NODE = {
    "label": "Read File",
    "category": "IO",
    "version": "1.0",
    "inputs": [],
    "outputs": [("table", "dataframe")],
}

_FORMATS = ["auto", "csv", "excel", "json", "parquet", "sqlite"]
# Every format-specific row lists "auto" alongside its own format: while the
# format is undecided the node cannot know which options are irrelevant, and
# hiding one the user needs with no way to bring it back is worse than a
# long panel. Choosing a format is what shortens it.
_CSV = ["auto", "csv"]
_EXCEL = ["auto", "excel"]
_JSON = ["auto", "json"]
_PARQUET = ["auto", "parquet"]
_SQLITE = ["auto", "sqlite"]
_TABULAR = ["auto", "csv", "excel"]

PARAMS = [
    {"name": "path", "type": "file_open", "label": "File", "default": ""},
    {"name": "format", "type": "choice", "label": "Format",
     "options": _FORMATS, "default": "auto"},

    # --- what to read out of the file -------------------------------------
    {"name": "sheet_name", "type": "string", "label": "Sheet",
     "default": "0", "placeholder": "name, 0-based index, or * for all",
     "visible_when": {"format": _EXCEL}},
    {"name": "separator", "type": "string", "label": "Separator",
     "default": ",", "placeholder": ", ; \\t or auto",
     "visible_when": {"format": _CSV}},
    {"name": "layout", "type": "choice", "label": "Layout",
     "options": ["records", "lines", "columns", "index", "table"],
     "default": "records", "visible_when": {"format": _JSON}},
    {"name": "source", "type": "choice", "label": "Read from",
     "options": ["query", "table"], "default": "query",
     "visible_when": {"format": _SQLITE}},
    {"name": "table", "type": "string", "label": "Table",
     "default": "", "placeholder": "table name",
     "visible_when": {"format": _SQLITE}},

    # --- shaping, shared across formats -----------------------------------
    {"name": "header", "type": "bool", "label": "First row is header",
     "default": True, "visible_when": {"format": _TABULAR}},
    {"name": "skiprows", "type": "int", "label": "Skip rows at start",
     "default": 0, "min": 0, "visible_when": {"format": _TABULAR}},
    {"name": "nrows", "type": "int", "label": "Max rows (0 = all)",
     "default": 0, "min": 0},
    {"name": "columns", "type": "columns", "label": "Columns",
     "default": "", "placeholder": "empty = all columns",
     "visible_when": {"format": ["auto", "csv", "excel", "parquet"]}},
    {"name": "index_col", "type": "string", "label": "Index column",
     "default": "", "placeholder": "name or 0-based position",
     "visible_when": {"format": ["auto", "csv", "excel", "sqlite"]}},
    {"name": "encoding", "type": "string", "label": "Encoding", "default": "",
     "placeholder": "auto (utf-8)",
     "visible_when": {"format": ["auto", "csv", "json"]}},
    {"name": "na_values", "type": "string", "label": "Extra missing values",
     "default": "", "placeholder": "comma separated, e.g. -, n/a, ?",
     "visible_when": {"format": _TABULAR}},
    {"name": "parse_dates", "type": "string", "label": "Parse dates",
     "default": "", "placeholder": "comma separated columns",
     "visible_when": {"format": ["auto", "csv", "excel", "sqlite"]}},
    {"name": "decimal", "type": "string", "label": "Decimal mark",
     "default": ".", "visible_when": {"format": _TABULAR}},
    {"name": "thousands", "type": "string", "label": "Thousands mark",
     "default": "", "placeholder": "none",
     "visible_when": {"format": _TABULAR}},

    # --- CSV's long tail ---------------------------------------------------
    {"name": "quotechar", "type": "string", "label": "Quote char",
     "default": '"', "visible_when": {"format": _CSV}},
    {"name": "comment", "type": "string", "label": "Comment char",
     "default": "", "placeholder": "e.g. # — rest of line is ignored",
     "visible_when": {"format": _CSV}},
    {"name": "skip_blank_lines", "type": "bool", "label": "Skip blank lines",
     "default": True, "visible_when": {"format": _CSV}},
    {"name": "on_bad_lines", "type": "choice", "label": "On bad lines",
     "options": ["error", "warn", "skip"], "default": "error",
     "visible_when": {"format": _CSV}},

    # --- JSON ---------------------------------------------------------------
    {"name": "flatten", "type": "bool", "label": "Flatten nested objects",
     "default": False, "visible_when": {"format": _JSON}},
    {"name": "flatten_sep", "type": "string", "label": "Flatten separator",
     "default": ".", "visible_when": {"format": _JSON}},
    {"name": "convert_dates", "type": "bool", "label": "Detect date columns",
     "default": True, "visible_when": {"format": _JSON}},

    # --- Parquet ------------------------------------------------------------
    {"name": "dtype_backend", "type": "choice", "label": "Dtype backend",
     "options": ["default", "numpy_nullable", "pyarrow"], "default": "default",
     "visible_when": {"format": _PARQUET}},

    # --- engines ------------------------------------------------------------
    {"name": "engine", "type": "choice", "label": "Engine",
     "options": ["auto", "pandas", "polars"], "default": "auto"},
    {"name": "excel_engine", "type": "choice", "label": "Excel engine",
     "options": ["auto", "calamine", "openpyxl", "xlrd", "pyxlsb", "odf"],
     "default": "auto", "visible_when": {"format": _EXCEL}},
    {"name": "csv_engine", "type": "choice", "label": "CSV parser",
     "options": ["auto", "c", "python", "pyarrow"], "default": "auto",
     "visible_when": {"format": _CSV}},
    {"name": "parquet_engine", "type": "choice", "label": "Parquet engine",
     "options": ["auto", "pyarrow", "fastparquet"], "default": "auto",
     "visible_when": {"format": _PARQUET}},

    # --- multiline blocks last (see the panel's tall-row rule) --------------
    {"name": "query", "type": "text", "label": "SQL query",
     "default": "", "placeholder": "SELECT * FROM my_table",
     "visible_when": {"format": _SQLITE}},
    {"name": "filters", "type": "text", "label": "Row filters",
     "default": "", "placeholder": "region == north\nunits >= 10",
     "visible_when": {"format": _PARQUET}},
    {"name": "dtypes", "type": "text", "label": "Column types",
     "default": "", "placeholder": "id = int64\nname = string"},
]

# Extension -> format. Compression suffixes are stripped first, so
# "sales.csv.gz" is a CSV rather than an unknown ".gz".
_COMPRESSED = {".gz", ".zip", ".bz2", ".xz", ".zst", ".zstd"}
_BY_SUFFIX = {
    ".csv": "csv", ".tsv": "csv", ".txt": "csv", ".psv": "csv",
    ".xlsx": "excel", ".xlsm": "excel", ".xls": "excel",
    ".xlsb": "excel", ".ods": "excel",
    ".json": "json", ".jsonl": "json", ".ndjson": "json",
    ".parquet": "parquet", ".pq": "parquet",
    ".db": "sqlite", ".sqlite": "sqlite", ".sqlite3": "sqlite",
}
# Extensions that mean JSONL whatever the Layout box says — the layout
# default is "records" and a .jsonl file read as records fails confusingly.
_LINES_SUFFIXES = {".jsonl", ".ndjson"}

_FILTER_OPS = ("not in", "in", "==", "!=", "<=", ">=", "<", ">")


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
            ops = " ".join(_FILTER_OPS)
            raise ValueError(f"row filters line {lineno}: expected "
                             f"'column op value' (ops: {ops}), got {line!r}")
        op = match.group("op")
        raw = match.group("val")
        value = ([_value(v) for v in raw.split(",")] if op in ("in", "not in")
                 else _value(raw))
        out.append((match.group("col").strip(), op, value))
    return out


def _suffix(path):
    """The meaningful extension, with any compression suffix peeled off."""
    from pathlib import Path

    suffixes = Path(path).suffixes
    while suffixes and suffixes[-1].lower() in _COMPRESSED:
        suffixes.pop()
    return suffixes[-1].lower() if suffixes else ""


def _detect(path):
    suffix = _suffix(path)
    fmt = _BY_SUFFIX.get(suffix)
    if not fmt:
        known = ", ".join(sorted(set(_BY_SUFFIX)))
        raise ValueError(
            f"cannot tell the format of {path!r} from its extension "
            f"{suffix or '(none)'} — set Format explicitly. Known "
            f"extensions: {known}")
    return fmt


def _have(module):
    import importlib.util

    return importlib.util.find_spec(module) is not None


def _refuse(engine, fmt, unsupported):
    """Fail on options the chosen engine cannot honour.

    Silently ignoring one is the worst outcome available: the run succeeds
    and the frame is quietly wrong. `unsupported` maps a param's label to
    whether the user actually set it.
    """
    named = sorted(label for label, was_set in unsupported.items() if was_set)
    if named:
        options = ", ".join(repr(n) for n in named)
        raise ValueError(
            f"the {engine} engine cannot apply {options} when reading "
            f"{fmt} — clear the option(s), or set Engine to pandas")


# --------------------------------------------------------------- polars types

# Only the mappings that are unambiguous. Anything else is refused by name
# rather than guessed at, because a wrong dtype here is a silently wrong
# column rather than an error.
_POLARS_DTYPES = {
    "string": "String", "str": "String", "object": "String",
    "int64": "Int64", "int32": "Int32", "int16": "Int16", "int8": "Int8",
    "uint64": "UInt64", "uint32": "UInt32",
    "float64": "Float64", "float32": "Float32",
    "bool": "Boolean", "boolean": "Boolean",
}


def _normalise_letter_range(spec):
    """Make a pandas `usecols` string fastexcel will take.

    fastexcel understands the whole spelling — `A:C`, `A:C,F`, `A,C`,
    `A:C,E:F` — with one exception: a range whose ends are the same column
    ("A:A") is rejected as an empty range, where pandas reads it as that one
    column. Collapse those and the two engines accept the same input.
    """
    import re

    parts = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        match = re.fullmatch(r"([A-Za-z]+):([A-Za-z]+)", part)
        if match and match.group(1).upper() == match.group(2).upper():
            part = match.group(1)
        parts.append(part)
    return ",".join(parts)


def _polars_schema(dtypes):
    import polars as pl

    schema = {}
    for column, dtype in dtypes.items():
        name = _POLARS_DTYPES.get(str(dtype).lower())
        if name is None:
            known = ", ".join(sorted(_POLARS_DTYPES))
            raise ValueError(
                f"the polars engine has no unambiguous equivalent for column "
                f"type {dtype!r} on {column!r} — set Engine to pandas, or use "
                f"one of: {known}")
        schema[column] = getattr(pl, name)
    return schema


# ------------------------------------------------------------------ readers


def _read_csv_pandas(ctx, p, path, kw):
    import pandas as pd

    separator = (p.get("separator") or ",").replace("\\t", "\t")
    engine = p.get("csv_engine", "auto")
    engine = None if engine == "auto" else engine
    kwargs = {
        "header": 0 if p.get("header", True) else None,
        "skip_blank_lines": p.get("skip_blank_lines", True),
    }
    if separator == "auto":
        kwargs["sep"] = None       # sniffing needs the python engine
        engine = "python"
    else:
        kwargs["sep"] = separator
    if engine:
        kwargs["engine"] = engine
    if kw["encoding"]:
        kwargs["encoding"] = kw["encoding"]
    if kw["columns"]:
        kwargs["usecols"] = kw["columns"]
    if kw["index_col"] is not None:
        kwargs["index_col"] = kw["index_col"]
    if kw["skiprows"]:
        kwargs["skiprows"] = kw["skiprows"]
    if kw["nrows"]:
        kwargs["nrows"] = kw["nrows"]
    if kw["decimal"] != ".":
        kwargs["decimal"] = kw["decimal"]
    if kw["thousands"]:
        kwargs["thousands"] = kw["thousands"]
    if (p.get("quotechar") or '"') != '"':
        kwargs["quotechar"] = p["quotechar"]
    if (p.get("comment") or "").strip():
        kwargs["comment"] = p["comment"].strip()[0]
    if kw["na_values"]:
        kwargs["na_values"] = kw["na_values"]
    if kw["parse_dates"]:
        kwargs["parse_dates"] = kw["parse_dates"]
    if kw["dtypes"]:
        kwargs["dtype"] = kw["dtypes"]
    if p.get("on_bad_lines", "error") != "error":
        kwargs["on_bad_lines"] = p["on_bad_lines"]
    return pd.read_csv(path, **kwargs), True


def _read_csv_polars(ctx, p, path, kw):
    import polars as pl

    separator = (p.get("separator") or ",").replace("\\t", "\t")
    _refuse("polars", "CSV", {
        "Separator = auto (sniffing)": separator == "auto",
        "Thousands mark": bool(kw["thousands"]),
        "On bad lines": p.get("on_bad_lines", "error") != "error",
        "Skip blank lines (off)": not p.get("skip_blank_lines", True),
    })
    if kw["decimal"] not in (".", ","):
        raise ValueError(
            f"the polars engine reads a decimal mark of '.' or ',', not "
            f"{kw['decimal']!r} — set Engine to pandas")

    kwargs = {
        "separator": separator,
        "has_header": bool(p.get("header", True)),
        "decimal_comma": kw["decimal"] == ",",
    }
    if kw["skiprows"]:
        kwargs["skip_rows"] = kw["skiprows"]
    if kw["nrows"]:
        kwargs["n_rows"] = kw["nrows"]
    if kw["columns"]:
        kwargs["columns"] = kw["columns"]
    if kw["encoding"]:
        # polars takes utf8 / utf8-lossy; anything else is pandas' job
        if kw["encoding"].replace("-", "").lower() not in ("utf8", "utf8lossy"):
            raise ValueError(
                f"the polars engine reads utf-8 only, not {kw['encoding']!r} "
                f"— set Engine to pandas")
    if kw["na_values"]:
        kwargs["null_values"] = kw["na_values"]
    if (p.get("quotechar") or '"') != '"':
        kwargs["quote_char"] = p["quotechar"]
    if (p.get("comment") or "").strip():
        kwargs["comment_prefix"] = p["comment"].strip()[0]
    if kw["dtypes"]:
        kwargs["schema_overrides"] = _polars_schema(kw["dtypes"])
    return pl.read_csv(path, **kwargs).to_pandas(), bool(kw["nrows"])


def _sheet_arg(p):
    sheet = (p.get("sheet_name") or "0").strip() or "0"
    if sheet == "*":
        return sheet, None
    if sheet.lstrip("-").isdigit():
        return sheet, int(sheet)
    return sheet, sheet


def _excel_engine(p, path):
    """Which Excel engine to hand pandas, or None to let it decide.

    auto reaches for calamine when it is installed: it reads the same
    workbook several times faster and produces the same frame, so there is
    no reason to prefer openpyxl when both are present.
    """
    chosen = p.get("excel_engine", "auto")
    if chosen != "auto":
        return chosen
    if _have("python_calamine"):
        return "calamine"
    return None


def _read_excel_pandas(ctx, p, path, kw):
    import pandas as pd

    label, sheet_arg = _sheet_arg(p)
    engine = _excel_engine(p, path)
    kwargs = {"header": 0 if p.get("header", True) else None}
    if kw["skiprows"]:
        kwargs["skiprows"] = kw["skiprows"]
    if kw["nrows"]:
        kwargs["nrows"] = kw["nrows"]
    if kw["columns_raw"]:
        # letter ranges (A:C) go through as a string; otherwise a name list
        kwargs["usecols"] = (kw["columns_raw"] if ":" in kw["columns_raw"]
                             else kw["columns"])
    if kw["index_col"] is not None:
        kwargs["index_col"] = kw["index_col"]
    if kw["na_values"]:
        kwargs["na_values"] = kw["na_values"]
    if kw["parse_dates"]:
        kwargs["parse_dates"] = kw["parse_dates"]
    if kw["dtypes"]:
        kwargs["dtype"] = kw["dtypes"]
    if kw["decimal"] != ".":
        kwargs["decimal"] = kw["decimal"]
    if kw["thousands"]:
        kwargs["thousands"] = kw["thousands"]

    if sheet_arg is None:
        with pd.ExcelFile(path, engine=engine) as workbook:
            names = list(workbook.sheet_names)
            if not names:
                raise ValueError(f"no sheets in {path}")
            frames = []
            for index, name in enumerate(names):
                ctx.check_cancelled()
                ctx.progress(index / len(names))
                frame = workbook.parse(name, **kwargs)
                frame.insert(0, "sheet", name)
                frames.append(frame)
        ctx.log(f"read {len(names)} sheet(s): {', '.join(names)}")
        # nrows applied per sheet by the reader, so the stack can exceed it
        return pd.concat(frames, ignore_index=True), False
    ctx.log(f"read sheet {label!r} with the "
            f"{engine or 'default'} engine")
    return pd.read_excel(path, sheet_name=sheet_arg, engine=engine,
                         **kwargs), bool(kw["nrows"])


def _read_excel_polars(ctx, p, path, kw):
    import pandas as pd
    import polars as pl

    label, sheet_arg = _sheet_arg(p)
    _refuse("polars", "Excel", {
        "Extra missing values": bool(kw["na_values"]),
        "Decimal mark": kw["decimal"] != ".",
        "Thousands mark": bool(kw["thousands"]),
        "Column types": bool(kw["dtypes"]),
    })

    read_options = {}
    if kw["skiprows"]:
        read_options["skip_rows"] = kw["skiprows"]
    if kw["nrows"]:
        read_options["n_rows"] = kw["nrows"]
    kwargs = {"has_header": bool(p.get("header", True))}
    if kw["columns_raw"] and ":" in kw["columns_raw"]:
        # fastexcel takes the same "A:C,F" spelling pandas' usecols does,
        # bar a range whose ends match ("A:A"), which it calls empty
        read_options["use_columns"] = _normalise_letter_range(kw["columns_raw"])
    elif kw["columns"]:
        kwargs["columns"] = kw["columns"]
    if read_options:
        kwargs["read_options"] = read_options

    if sheet_arg is None:
        sheets = pl.read_excel(path, sheet_id=0, **kwargs)
        if not sheets:
            raise ValueError(f"no sheets in {path}")
        frames = []
        for index, (name, frame) in enumerate(sheets.items()):
            ctx.check_cancelled()
            ctx.progress(index / len(sheets))
            out = frame.to_pandas()
            out.insert(0, "sheet", name)
            frames.append(out)
        ctx.log(f"read {len(sheets)} sheet(s): {', '.join(sheets)}")
        return pd.concat(frames, ignore_index=True), False
    if isinstance(sheet_arg, int):
        # polars counts sheets from 1; the node counts from 0 like pandas
        kwargs["sheet_id"] = sheet_arg + 1
    else:
        kwargs["sheet_name"] = sheet_arg
    ctx.log(f"read sheet {label!r} with polars")
    return pl.read_excel(path, **kwargs).to_pandas(), bool(kw["nrows"])


def _read_json_pandas(ctx, p, path, kw):
    import json

    import pandas as pd

    layout = kw["layout"]
    encoding = kw["encoding"] or "utf-8"
    if p.get("flatten", False):
        if layout not in ("records", "lines"):
            raise ValueError("flatten only works with the records or lines layout")
        with open(path, encoding=encoding) as fh:
            if layout == "lines":
                records = []
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    records.append(json.loads(line))
                    if kw["nrows"] and len(records) >= kw["nrows"]:
                        break
            else:
                records = json.load(fh)
                if not isinstance(records, list):
                    raise ValueError(
                        "flatten expects the file to hold a list of objects "
                        "(records layout)")
        table = pd.json_normalize(records, sep=p.get("flatten_sep") or ".")
        return table, bool(kw["nrows"]) and layout == "lines"

    kwargs = {"convert_dates": p.get("convert_dates", True)}
    if kw["encoding"]:
        kwargs["encoding"] = kw["encoding"]
    if layout == "lines":
        kwargs["orient"] = "records"
        kwargs["lines"] = True
        if kw["nrows"]:
            kwargs["nrows"] = kw["nrows"]
        return pd.read_json(path, **kwargs), bool(kw["nrows"])
    kwargs["orient"] = layout
    return pd.read_json(path, **kwargs), False


def _read_json_polars(ctx, p, path, kw):
    import polars as pl

    layout = kw["layout"]
    _refuse("polars", "JSON", {
        "Flatten nested objects": bool(p.get("flatten", False)),
        "Detect date columns (off)": not p.get("convert_dates", True),
    })
    if layout not in ("records", "lines"):
        raise ValueError(
            f"the polars engine reads the records and lines layouts, not "
            f"{layout!r} — set Engine to pandas")
    if layout == "lines":
        frame = pl.read_ndjson(path)
    else:
        frame = pl.read_json(path)
    return frame.to_pandas(), False


def _read_parquet_pandas(ctx, p, path, kw):
    import pandas as pd

    from flograph.packages import parquet_problem

    problem = parquet_problem(p.get("parquet_engine", "auto"))
    if problem:
        raise RuntimeError(problem)

    kwargs = {}
    if kw["columns"]:
        kwargs["columns"] = kw["columns"]
    filters = _filters(p.get("filters"))
    if filters:
        kwargs["filters"] = filters
    if p.get("parquet_engine", "auto") != "auto":
        kwargs["engine"] = p["parquet_engine"]
    if p.get("dtype_backend", "default") != "default":
        kwargs["dtype_backend"] = p["dtype_backend"]
    return pd.read_parquet(path, **kwargs), False


def _read_parquet_polars(ctx, p, path, kw):
    import polars as pl

    _refuse("polars", "Parquet", {
        "Row filters": bool((p.get("filters") or "").strip()),
        "Dtype backend": p.get("dtype_backend", "default") != "default",
    })
    kwargs = {}
    if kw["columns"]:
        kwargs["columns"] = kw["columns"]
    if kw["nrows"]:
        kwargs["n_rows"] = kw["nrows"]
    return pl.read_parquet(path, **kwargs).to_pandas(), bool(kw["nrows"])


def _read_sqlite(ctx, p, path, kw):
    import sqlite3

    import pandas as pd

    nrows = kw["nrows"]
    with sqlite3.connect(path) as conn:
        if p.get("source", "query") == "table":
            name = (p.get("table") or "").strip()
            if not name:
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "ORDER BY name").fetchall()
                available = ", ".join(r[0] for r in rows) or "(none)"
                raise ValueError(f"no table name given — tables in this "
                                 f"database: {available}")
            quoted = name.replace('"', '""')
            query = f'SELECT * FROM "{quoted}"'
            if nrows:
                # This half we wrote, so the limit goes into the SQL and the
                # rows are never fetched at all.
                query += f" LIMIT {nrows}"
            pushed = bool(nrows)
        else:
            query = (p.get("query") or "").strip()
            if not query:
                raise ValueError("no SQL query given")
            # The SQL is the user's; wrapping it to bolt a LIMIT on breaks as
            # soon as it is anything but a plain SELECT.
            pushed = False

        kwargs = {}
        if kw["index_col"] is not None:
            kwargs["index_col"] = kw["index_col"]
        if kw["parse_dates"]:
            kwargs["parse_dates"] = kw["parse_dates"]
        if kw["dtypes"]:
            kwargs["dtype"] = kw["dtypes"]
        return pd.read_sql_query(query, conn, **kwargs), pushed


_READERS = {
    ("csv", "pandas"): _read_csv_pandas,
    ("csv", "polars"): _read_csv_polars,
    ("excel", "pandas"): _read_excel_pandas,
    ("excel", "polars"): _read_excel_polars,
    ("json", "pandas"): _read_json_pandas,
    ("json", "polars"): _read_json_polars,
    ("parquet", "pandas"): _read_parquet_pandas,
    ("parquet", "polars"): _read_parquet_polars,
    ("sqlite", "pandas"): _read_sqlite,
}


def run(ctx):
    import pandas as pd

    p = ctx.params
    path = p["path"]
    if not path:
        raise ValueError("no file selected — set 'File' in the node's properties")

    fmt = p.get("format", "auto")
    if fmt == "auto":
        fmt = _detect(path)
        ctx.log(f"detected {fmt} from the file extension")

    engine = p.get("engine", "auto")
    if engine == "auto":
        # pandas: it honours every option on the panel, so the default never
        # refuses a flow that used to run. polars is the deliberate choice.
        engine = "pandas"
    if engine == "polars" and not _have("polars"):
        raise RuntimeError(
            "the polars engine needs the polars package — install it from "
            "Tools > Manage Packages, then restart flograph")

    reader = _READERS.get((fmt, engine))
    if reader is None:
        raise ValueError(
            f"the {engine} engine cannot read {fmt} in this node — set "
            f"Engine to pandas")

    columns_raw = (p.get("columns") or "").strip()
    layout = p.get("layout", "records")
    if fmt == "json" and _suffix(path) in _LINES_SUFFIXES and layout == "records":
        # .jsonl / .ndjson with the default layout: the extension is a
        # clearer statement of intent than a box the user never touched.
        layout = "lines"
        ctx.log("reading as JSON lines (from the file extension)")
    kw = {
        "columns_raw": columns_raw,
        "columns": _list(columns_raw),
        "nrows": int(p.get("nrows", 0) or 0),
        "skiprows": int(p.get("skiprows", 0) or 0),
        "encoding": (p.get("encoding") or "").strip(),
        "na_values": _list(p.get("na_values")),
        "parse_dates": _list(p.get("parse_dates")),
        "dtypes": _mapping(p.get("dtypes")),
        "decimal": p.get("decimal") or ".",
        "thousands": p.get("thousands") or "",
        "index_col": None,
        "layout": layout,
    }
    index_col = (p.get("index_col") or "").strip()
    if index_col:
        kw["index_col"] = int(index_col) if index_col.isdigit() else index_col

    table, row_limit_applied = reader(ctx, p, path, kw)

    # Options the readers above could not push down, applied once here so
    # every format and engine behaves the same way from the outside.
    if engine == "polars":
        if kw["parse_dates"]:
            missing = [c for c in kw["parse_dates"] if c not in table.columns]
            if missing:
                raise ValueError(
                    f"parse dates: no such column(s): {', '.join(missing)}")
            for column in kw["parse_dates"]:
                table[column] = pd.to_datetime(table[column])
        if kw["dtypes"] and fmt != "csv":
            # csv pushed them into the read; the rest convert after
            table = table.astype(kw["dtypes"])
        if kw["index_col"] is not None:
            table = table.set_index(
                table.columns[kw["index_col"]]
                if isinstance(kw["index_col"], int) else kw["index_col"])

    if kw["nrows"] and not row_limit_applied and len(table) > kw["nrows"]:
        table = table.head(kw["nrows"]).copy()
        ctx.log(f"trimmed to the first {kw['nrows']} rows")

    ctx.log(f"loaded {len(table)} rows x {len(table.columns)} columns "
            f"({fmt} via {engine})")
    return table
