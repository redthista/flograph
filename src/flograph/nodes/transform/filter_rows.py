"""Filter Rows

Keep the rows of a DataFrame that match; the rows that don't come out of
the second port.

Pick a **Column**, how to **Match** and a **Value** — no code.
Text: contains, starts with, ends with, equals (and their opposites).
`*` stands for any run of characters and `?` for one; every other
character means itself. Case is ignored unless *Match case* is ticked.
Numbers and dates: `>`, `>=`, `<`, `<=`, equals. A column of dates — or of
text that reads as dates, as a CSV's often is — compares the value as a
date: `2026-10-05`, `5 Oct 2026`, or `05/10/2026` (day first). A date with
no time compares whole days, so `<= 2026-10-05` keeps all of the 5th, and
*equals* a day matches any time on it. A blank cell matches nothing — so
*does not contain* and *does not equal* keep it. *is blank* finds the
empty cells (nothing in them, or only spaces) and *is not blank* the rest;
neither needs a Value.

**Advanced options ▸ Query expression** takes a pandas query instead, e.g.
`price > 5 and region == 'North'`. A column with a space in its name can be
written as it is spelled (`unit price > 5`) or in backticks
(`` `unit price` > 5 ``); a name with other punctuation in it, like
`price($)`, needs the backticks. With a condition and a query both filled
in, a row has to pass both.

Untick *Output rejected rows* when nothing reads the second port: it then
carries an empty table, so a large table isn't held twice in the cache.
"""
NODE = {
    "label": "Filter Rows",
    "category": "Transform",
    "version": "1.2",
    "inputs": [("table", "dataframe")],
    "outputs": [("filtered", "dataframe"), ("rejected", "dataframe")],
}
# The comparisons, by the label the Match dropdown shows.
ORDER = {"> greater than": "gt", ">= greater than or equal": "ge",
         "< less than": "lt", "<= less than or equal": "le"}
# The matches that look only at the cell, so need no Value.
BLANK = ["is blank", "is not blank"]
MATCHES = ["contains", "does not contain", "starts with", "ends with",
           "equals", "does not equal", *ORDER, *BLANK]
_NEEDS_VALUE = {"match": [m for m in MATCHES if m not in BLANK]}
PARAMS = [
    {"name": "column", "type": "columns", "label": "Column", "default": "",
     "multi": False},
    {"name": "match", "type": "choice", "label": "Match",
     "options": MATCHES, "default": "contains"},
    {"name": "value", "type": "string", "label": "Value", "default": "",
     "placeholder": "apple, app*, 100 or 2026-10-05",
     "visible_when": _NEEDS_VALUE},
    {"name": "case_sensitive", "type": "bool", "label": "Match case",
     "default": False, "visible_when": _NEEDS_VALUE},
    {"name": "keep_rejected", "type": "bool", "label": "Output rejected rows",
     "default": True},
    {"name": "query", "type": "string", "label": "Query expression",
     "default": "", "placeholder": "col_a > 0 and col_b == 'x'",
     "section": "Advanced options", "folded": True},
]


# ---------------------------------------------------------------- condition

def _condition_mask(table, p):
    from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype
    from pandas.api.types import is_numeric_dtype

    column = str(p.get("column") or "").strip()
    if not column:
        raise ValueError("Pick the column to match in 'Column'")
    if column not in table.columns:
        raise ValueError(f"No column named {column!r} in the table")
    match = p.get("match") or "contains"
    if match not in MATCHES:
        raise ValueError(f"'Match' can't be {match!r}")
    value = str(p.get("value") or "").strip()
    case = bool(p.get("case_sensitive"))
    cells = table[column]
    if match in BLANK:
        blank = cells.map(lambda v: not (t := _cell_text(v)) or not t.strip())
        blank = blank.astype(bool)
        return blank if match == "is blank" else ~blank

    negate = match.startswith("does not")
    is_date = is_datetime64_any_dtype(cells)
    is_number = is_numeric_dtype(cells) and not is_bool_dtype(cells)
    if match in ORDER:
        op = ORDER[match]
    elif match in ("equals", "does not equal") and (is_date or is_number) \
            and not any(ch in value for ch in "*?"):
        op = "eq"
    else:
        hit = _text_hit(cells, match, value, case)
        return ~hit if negate else hit

    if is_date:
        hit = _date_hit(cells, op, value, column)
    elif is_number:
        number = _number(value)
        if number is None:
            raise ValueError(
                f"{value!r} isn't a number, and {column!r} holds numbers")
        hit = getattr(cells, op)(number)
    else:
        hit = _mixed_hit(cells, op, value, case)
    hit = hit.fillna(False).astype(bool)
    return ~hit if negate else hit


def _text_hit(cells, match, value, case):
    """A text match: `value` is literal except for the * and ? wildcards."""
    import re

    body = "".join(".*" if ch == "*" else "." if ch == "?" else re.escape(ch)
                   for ch in value)
    pattern = {"starts with": "^" + body, "ends with": body + "$",
               "equals": "^" + body + "$",
               "does not equal": "^" + body + "$"}.get(match, body)
    # DOTALL: a cell with a line break in it is still one value to match.
    rx = re.compile(pattern, (0 if case else re.IGNORECASE) | re.DOTALL)
    return cells.map(lambda v: (t := _cell_text(v)) is not None
                     and bool(rx.search(t))).astype(bool)


def _mixed_hit(cells, op, value, case):
    """A comparison on a column of text (or mixed values): as numbers when
    the value is one and the column holds some, then as dates, then as
    text in alphabetical order. Cells that aren't of the kind never pass."""
    import pandas as pd

    number = _number(value)
    if number is not None:
        as_numbers = pd.to_numeric(cells, errors="coerce")
        if as_numbers.notna().any():
            return getattr(as_numbers, op)(number)
    if _date(value) is not None:
        as_dates = _to_dates(cells)
        if as_dates.notna().any():
            return _date_hit(as_dates, op, value, None)
    key = value if case else value.casefold()
    return cells.map(lambda v: (t := _cell_text(v)) is not None and getattr(
        t if case else t.casefold(), f"__{op}__")(key)).astype(bool)


def _date_hit(cells, op, value, column):
    parsed = _date(value)
    if parsed is None:
        raise ValueError(
            f"{value!r} isn't a date, and {column!r} holds dates — "
            f"try 2026-10-05, 5 Oct 2026 or 05/10/2026 (day first)")
    when, whole_day = parsed
    tz = getattr(cells.dt, "tz", None)
    if tz is not None and when.tzinfo is None:
        when = when.tz_localize(tz)
    if whole_day:
        cells = cells.dt.normalize()
    return getattr(cells, op)(when)


def _number(text):
    try:
        return float(text)
    except ValueError:
        return None


def _date(text):
    """(timestamp, is a whole day) for a value that reads as a date, else
    None. ISO first: day-first parsing turns 2026-10-05 into 10 May."""
    import re

    import pandas as pd

    if not text or _number(text) is not None:
        return None
    try:
        if re.match(r"\d{4}-\d{1,2}-\d{1,2}", text):
            when = pd.Timestamp(text)
        else:
            when = pd.to_datetime(text, dayfirst=True)
    except (ValueError, TypeError, OverflowError):
        return None
    if when is pd.NaT:
        return None
    return when, ":" not in text and when == when.normalize()


def _to_dates(cells):
    """A column of text as dates, read as `_date` reads a value; anything
    that isn't one becomes NaT."""
    import pandas as pd

    text = cells.where(cells.map(lambda v: isinstance(v, str)))
    iso = pd.to_datetime(text, errors="coerce", format="ISO8601")
    rest = pd.to_datetime(text.where(iso.isna()), errors="coerce",
                          dayfirst=True, format="mixed")
    others = pd.to_datetime(cells.where(text.isna()), errors="coerce")
    return iso.fillna(rest).fillna(others)


def _cell_text(v):
    """A cell as the text it shows, or None for a blank one."""
    import pandas as pd

    if isinstance(v, str):
        return v
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):  # a list in a cell
        pass
    # 3.0 reads as "3", as it does in the table, so "equals 3" finds it.
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


# -------------------------------------------------------------------- query

def _query_mask(table, query):
    import re

    from flograph.core.column_refs import quote_bare_columns

    try:
        return table.eval(quote_bare_columns(query, table.columns))
    except Exception as exc:
        # re.error from Python's regex engine; pyarrow-backed strings say
        # "Invalid regular expression" in an ArrowInvalid instead.
        if not (isinstance(exc, re.error)
                or "regular expression" in str(exc).lower()):
            raise
        raise ValueError(
            f"The text in .str.contains(...) is read as a pattern, and it "
            f"isn't a valid one ({exc}). `contains` already matches anywhere, "
            f"so leave out * wildcards, or add regex=False to match the text "
            f"exactly — or clear the query and use Column, Match and Value.") from None


def run(ctx, table):
    p = ctx.params
    # A condition is on once it has a value to look for — or needs none.
    condition = bool(str(p.get("value") or "").strip()) or p.get("match") in BLANK
    query = str(p.get("query") or "").strip()
    if not condition and not query:
        return {"filtered": table, "rejected": table.iloc[0:0]}
    mask = _condition_mask(table, p) if condition else None
    if query:
        asked = _query_mask(table, query)
        mask = asked if mask is None else mask & asked
    ctx.log(f"kept {int(mask.sum())} / {len(table)} rows")
    rejected = table[~mask] if p.get("keep_rejected", True) else table.iloc[0:0]
    return {"filtered": table[mask], "rejected": rejected}
