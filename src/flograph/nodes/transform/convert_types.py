"""Convert Types

Convert columns to another type. Each target type brings its own options,
shown only while that type is picked:

- integer / decimal: decimal and thousands marks (1.234,56 and 1,234.56
  both parse), currency symbols to strip, trailing % as a fraction, and
  accounting brackets — (123) means -123.
- datetime: preset formats (ISO, US, EU, dotted, month names, compact,
  unix seconds/millis, Excel serial days) or a custom strftime pattern
  such as %d.%m.%Y, plus a day-first switch for auto-detect.
- boolean: your own true/false words, matched without regard to case —
  1/0 always count, and anything unlisted follows On bad values.
- string: trims whitespace, changes case, and keeps missings missing
  (or writes them as empty text) instead of the literal "nan".
- category: ordered or not, with an optional explicit category order.

On errors either fail the node or coerce the offending cells to missing
values.
"""
NODE = {
    "label": "Convert Types",
    "category": "Transform",
    "version": "2.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}

_NUMERIC = ("int", "float")

_DATE_FORMATS = {
    "auto-detect": "auto",
    "ISO 8601 (2024-03-15T14:30)": "iso",
    "year-month-day (2024-03-15)": "%Y-%m-%d",
    "day/month/year (15/03/2024)": "%d/%m/%Y",
    "month/day/year (03/15/2024)": "%m/%d/%Y",
    "day-month-year (15-03-2024)": "%d-%m-%Y",
    "day.month.year (15.03.2024)": "%d.%m.%Y",
    "day Mon year (15 Mar 2024)": "%d %b %Y",
    "Month day, year (March 15, 2024)": "%B %d, %Y",
    "compact (20240315)": "%Y%m%d",
    "unix seconds": "unix_s",
    "unix milliseconds": "unix_ms",
    "Excel serial days": "excel",
    "custom...": "custom",
}

PARAMS = [
    {"name": "columns", "type": "columns", "label": "Columns",
     "default": "", "placeholder": "comma separated"},
    {"name": "to", "type": "choice", "label": "Target type",
     "options": ["int", "float", "string", "bool", "datetime", "category"],
     "default": "float"},
    {"name": "on_error", "type": "choice", "label": "On bad values",
     "options": ["fail", "set missing"], "default": "fail"},

    # --- numbers ------------------------------------------------------
    {"name": "decimal", "type": "choice", "label": "Decimal mark",
     "options": [".", ","], "default": ".",
     "visible_when": {"to": ["int", "float"]}},
    {"name": "thousands", "type": "choice", "label": "Thousands mark",
     "options": ["none", ",", ".", "space", "'"], "default": "none",
     "visible_when": {"to": ["int", "float"]}},
    {"name": "strip_symbols", "type": "string", "label": "Strip symbols",
     "default": "$, \u20ac, \u00a3",
     "placeholder": "comma separated, e.g. $, \u20ac, USD",
     "visible_when": {"to": ["int", "float"]}},
    {"name": "percent", "type": "bool", "label": "45% means 0.45",
     "default": True, "visible_when": {"to": ["int", "float"]}},
    {"name": "accounting", "type": "bool", "label": "(123) means -123",
     "default": False, "visible_when": {"to": ["int", "float"]}},

    # --- datetimes ----------------------------------------------------
    {"name": "date_format", "type": "choice", "label": "Date format",
     "options": list(_DATE_FORMATS), "default": "auto-detect",
     "visible_when": {"to": ["datetime"]}},
    {"name": "custom_format", "type": "string", "label": "Custom pattern",
     "default": "", "placeholder": "strftime, e.g. %d.%m.%Y %H:%M",
     "visible_when": {"to": ["datetime"],
                      "date_format": ["custom..."]}},
    {"name": "dayfirst", "type": "bool", "label": "Day comes first",
     "default": False, "visible_when": {"to": ["datetime"]}},


    # --- booleans -----------------------------------------------------
    {"name": "true_values", "type": "string", "label": "True words",
     "default": "true, yes, y, 1",
     "placeholder": "comma separated",
     "visible_when": {"to": ["bool"]}},
    {"name": "false_values", "type": "string", "label": "False words",
     "default": "false, no, n, 0",
     "placeholder": "comma separated",
     "visible_when": {"to": ["bool"]}},

    # --- strings ------------------------------------------------------
    {"name": "trim", "type": "bool", "label": "Trim whitespace",
     "default": False, "visible_when": {"to": ["string"]}},
    {"name": "case", "type": "choice", "label": "Case",
     "options": ["keep", "lower", "upper", "title"], "default": "keep",
     "visible_when": {"to": ["string"]}},
    {"name": "on_missing", "type": "choice", "label": "On missing values",
     "options": ["keep missing", "empty text"], "default": "keep missing",
     "visible_when": {"to": ["string"]}},

    # --- categories ---------------------------------------------------
    {"name": "ordered", "type": "bool", "label": "Ordered categories",
     "default": False, "visible_when": {"to": ["category"]}},
    {"name": "categories", "type": "string", "label": "Category order",
     "default": "", "placeholder": "comma separated — empty = as they appear",
     "visible_when": {"to": ["category"], "ordered": ["True"]}},
]


def _words(box):
    """A comma-separated box as a set of lowercase words."""
    return {w.strip().lower() for w in str(box).split(",") if w.strip()}


def _clean_number(value, decimal, thousands, symbols, accounting, percent):
    """A number written for humans as plain text pandas can parse: symbol
    stripping, accounting brackets and a trailing % are unwrapped first,
    then the thousands mark is removed and the decimal mark becomes ".".
    Returns the cleaned text and whether a % was consumed as a fraction."""
    text = value.strip()
    negative = False
    if accounting and text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1].strip()
    has_percent = percent and text.endswith("%")
    if has_percent:
        text = text[:-1].strip()
    for symbol in symbols:
        if symbol:
            text = text.replace(symbol, "")
    text = text.strip()
    if thousands and thousands != decimal:
        text = text.replace(thousands, "")
        if thousands == " ":
            text = text.replace("\u00a0", "")
    if decimal != ".":
        text = text.replace(decimal, ".")
    if negative:
        text = "-" + text
    return text, has_percent


def _convert_number(ctx, series, target, coerce):
    import pandas as pd

    params = ctx.params
    decimal = params.get("decimal", ".")
    thousands = {"none": "", ",": ",", ".": ".",
                 "space": " ", "'": "'"}.get(params.get("thousands", "none"),
                                             "")
    symbols = [s.strip() for s in str(
        params.get("strip_symbols", "")).split(",")]
    percent = bool(params.get("percent", True))
    accounting = bool(params.get("accounting", False))
    errors = "coerce" if coerce else "raise"

    def clean(value):
        if isinstance(value, str):
            text, was_percent = _clean_number(value, decimal, thousands,
                                              symbols, accounting, percent)
            number = pd.to_numeric(text, errors=errors)
            if was_percent and pd.notna(number):
                number = number / 100
            return number
        return value

    converted = pd.to_numeric(series.map(clean), errors=errors)
    # nullable Int64 keeps ints even when coercion produced missings
    return converted.astype("Int64" if target == "int" else float)


def _convert_datetime(ctx, series, coerce):
    import pandas as pd

    params = ctx.params
    errors = "coerce" if coerce else "raise"
    if isinstance(series.dtype, pd.DatetimeTZDtype) or \
            pd.api.types.is_datetime64_any_dtype(series):
        return series
    fmt = _DATE_FORMATS.get(params.get("date_format", "auto-detect"), "auto")
    if fmt == "custom":
        fmt = str(params.get("custom_format", "")).strip()
        if not fmt:
            raise ValueError("custom date pattern is empty")
    if fmt == "unix_s":
        numeric = pd.to_numeric(series, errors=errors)
        return pd.to_datetime(numeric, unit="s", errors=errors)
    if fmt == "unix_ms":
        numeric = pd.to_numeric(series, errors=errors)
        return pd.to_datetime(numeric, unit="ms", errors=errors)
    if fmt == "excel":
        numeric = pd.to_numeric(series, errors=errors)
        return pd.to_datetime(numeric, origin="1899-12-30", unit="D",
                              errors=errors)
    if fmt == "iso":
        return pd.to_datetime(series, errors=errors)
    if fmt == "auto":
        return pd.to_datetime(series, errors=errors,
                              dayfirst=bool(params.get("dayfirst", False)))
    return pd.to_datetime(series, format=fmt, errors=errors)


def _convert_bool(ctx, series, coerce):
    import pandas as pd

    params = ctx.params
    true = _words(params.get("true_values", ""))
    false = _words(params.get("false_values", ""))
    bad: list = []

    def convert(value):
        if value is None or (not isinstance(value, bool) and pd.isna(value)):
            return pd.NA
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value == 1:
                return True
            if value == 0:
                return False
        key = str(value).strip().lower()
        if key in true:
            return True
        if key in false:
            return False
        bad.append(value)
        return pd.NA

    converted = series.map(convert).astype("boolean")
    if bad and not coerce:
        sample = ", ".join(repr(v) for v in bad[:5])
        raise ValueError(f"not true/false words: {sample}")
    return converted


def _convert_string(ctx, series):
    import pandas as pd

    params = ctx.params
    missing = series.isna()
    text = series.astype("string")
    if bool(params.get("trim", False)):
        text = text.str.strip()
    case = params.get("case", "keep")
    if case == "lower":
        text = text.str.lower()
    elif case == "upper":
        text = text.str.upper()
    elif case == "title":
        text = text.str.title()
    text[missing] = pd.NA
    if params.get("on_missing", "keep missing") == "empty text":
        text = text.fillna("")
    return text


def _convert_category(ctx, series, coerce):
    import pandas as pd

    params = ctx.params
    ordered = bool(params.get("ordered", False))
    cats = [c.strip() for c in str(
        params.get("categories", "")).split(",") if c.strip()]
    if not cats:
        converted = series.astype("category")
        return converted.cat.as_ordered() if ordered else converted
    if not coerce:
        unknown = sorted({str(v) for v in series.dropna().unique()
                          if str(v) not in cats})
        if unknown:
            sample = ", ".join(unknown[:5])
            raise ValueError(f"values outside the category order: {sample}")
    return pd.Categorical(series, categories=cats, ordered=ordered)


def run(ctx, table):
    columns = [c.strip() for c in str(
        ctx.params["columns"]).split(",") if c.strip()]
    if not columns:
        raise ValueError("no columns listed")
    missing = [c for c in columns if c not in table.columns]
    if missing:
        raise ValueError(f"columns not in table: {missing}")

    target = ctx.params["to"]
    coerce = ctx.params["on_error"] == "set missing"
    result = table.copy()
    for col in columns:
        series = result[col]
        if target == "datetime":
            result[col] = _convert_datetime(ctx, series, coerce)
        elif target in ("int", "float"):
            result[col] = _convert_number(ctx, series, target, coerce)
        elif target == "string":
            result[col] = _convert_string(ctx, series)
        elif target == "bool":
            result[col] = _convert_bool(ctx, series, coerce)
        else:
            result[col] = _convert_category(ctx, series, coerce)
    ctx.log(f"converted {len(columns)} column(s) to {target}")
    return result
