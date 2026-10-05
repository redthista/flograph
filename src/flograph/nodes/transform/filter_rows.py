"""Filter Rows

Keep the rows of a DataFrame that match; the rows that don't come out of
the second port.

*Filter by* picks how a row is matched:

- **Query** — a pandas query expression, e.g. `price > 5 and region == 'North'`.
  A column with a space in its name can be written as it is spelled
  (`unit price > 5`) or in backticks (`` `unit price` > 5 ``); a name with
  other punctuation in it, like `price($)`, needs the backticks.
- **Text match** — pick a column, how to match (contains, starts with,
  equals, ...) and the text. `*` stands for any run of characters and `?`
  for one character; every other character means itself. Case is ignored
  unless *Match case* is ticked. A blank cell holds no text, so it never
  contains anything — and is kept by *does not contain*.

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
_TEXT = {"mode": ["Text match"]}
MATCHES = ["contains", "does not contain", "starts with", "ends with",
           "equals", "does not equal"]
PARAMS = [
    {"name": "mode", "type": "choice", "label": "Filter by",
     "options": ["Query", "Text match"], "default": "Query"},
    {"name": "query", "type": "string", "label": "Query expression",
     "default": "", "placeholder": "col_a > 0 and col_b == 'x'",
     "visible_when": {"mode": ["Query"]}},
    {"name": "column", "type": "columns", "label": "Column", "default": "",
     "multi": False, "visible_when": _TEXT},
    {"name": "match", "type": "choice", "label": "Match",
     "options": MATCHES, "default": "contains", "visible_when": _TEXT},
    {"name": "text", "type": "string", "label": "Text", "default": "",
     "placeholder": "e.g. apple — * any characters, ? one",
     "visible_when": _TEXT},
    {"name": "case_sensitive", "type": "bool", "label": "Match case",
     "default": False, "visible_when": _TEXT},
    {"name": "keep_rejected", "type": "bool", "label": "Output rejected rows",
     "default": True},
]


def _pattern(text, match):
    """The regex for `text` under `match`: literal except for * and ?."""
    import re

    body = "".join(".*" if ch == "*" else "." if ch == "?" else re.escape(ch)
                   for ch in text)
    if match == "starts with":
        return "^" + body
    if match == "ends with":
        return body + "$"
    if match in ("equals", "does not equal"):
        return "^" + body + "$"
    return body


def _text_mask(table, p):
    import re

    column = str(p.get("column") or "").strip()
    if not column:
        raise ValueError("Pick the column to match in 'Column'")
    if column not in table.columns:
        raise ValueError(f"No column named {column!r} in the table")
    match = p.get("match") or "contains"
    flags = 0 if p.get("case_sensitive") else re.IGNORECASE
    # DOTALL: a cell with a line break in it is still one value to match.
    rx = re.compile(_pattern(str(p.get("text") or ""), match), flags | re.DOTALL)
    hit = table[column].map(
        lambda v: (t := _cell_text(v)) is not None and bool(rx.search(t)))
    hit = hit.astype(bool)
    return ~hit if match.startswith("does not") else hit


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
            f"exactly — or set 'Filter by' to Text match.") from None


def run(ctx, table):
    p = ctx.params
    text_match = p.get("mode") == "Text match"
    wanted = str(p.get("text" if text_match else "query") or "")
    if not wanted.strip():
        return {"filtered": table, "rejected": table.iloc[0:0]}
    mask = _text_mask(table, p) if text_match else _query_mask(table, wanted.strip())
    ctx.log(f"kept {int(mask.sum())} / {len(table)} rows")
    rejected = table[~mask] if p.get("keep_rejected", True) else table.iloc[0:0]
    return {"filtered": table[mask], "rejected": rejected}
