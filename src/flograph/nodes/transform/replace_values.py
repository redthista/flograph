"""Replace Values

Swap one value for another across the table — Power Query's *Replace Values*.
Fix a recurring typo, map `N/A` / `-` / `null` to a real blank, standardise
`USA` / `U.S.A.` / `United States` to one spelling.

One `find = replace` pair per line. By default a cell must equal *find*
exactly to be replaced (*Match* = *Whole cell*); switch to *Substring* to
replace it anywhere inside the text, or *Regex* for a pattern. Leave the
right-hand side empty to replace with a blank, or write `<NA>` for a true
missing value. Restrict to some columns with *Columns*, or leave it empty for
the whole table.
"""
import re

NODE = {
    "label": "Replace Values",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "match", "type": "choice", "label": "Match",
     "options": ["Whole cell", "Substring", "Regex"], "default": "Whole cell"},
    {"name": "columns", "type": "columns", "label": "Columns", "default": "",
     "placeholder": "empty = whole table"},
    {"name": "case_insensitive", "type": "bool", "label": "Ignore case",
     "default": False},
    {"name": "pairs", "type": "text", "label": "Replacements (find = replace)",
     "default": "", "placeholder": "N/A = <NA>\n- = <NA>\nU.S.A. = USA"},
]


def run(ctx, table):
    import pandas as pd

    p = ctx.params
    pairs = []
    for lineno, raw in enumerate(p["pairs"].splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        find, sep, repl = line.partition("=")
        find = find.strip()
        if not sep or not find:
            raise ValueError(f"line {lineno}: expected 'find = replace', "
                             f"got {line!r}")
        repl = repl.strip()
        pairs.append((find, pd.NA if repl == "<NA>" else repl))
    if not pairs:
        raise ValueError("no replacements — one 'find = replace' per line")

    names = [c.strip() for c in p["columns"].split(",") if c.strip()]
    if not names:
        names = list(table.columns)
    missing = [c for c in names if c not in table.columns]
    if missing:
        raise ValueError(f"columns not in table: {missing}")

    mode = p["match"]
    flags = re.IGNORECASE if p["case_insensitive"] else 0
    result = table.copy(deep=False)
    changed = 0

    def as_column_type(series, token):
        """Coerce a parsed find/replace token to the column's kind so a
        Whole-cell rule can match a numeric or boolean column."""
        if token is pd.NA:
            return pd.NA
        if pd.api.types.is_bool_dtype(series) and token.lower() in ("true", "false"):
            return token.lower() == "true"
        if pd.api.types.is_numeric_dtype(series):
            try:
                return int(token)
            except ValueError:
                try:
                    return float(token)
                except ValueError:
                    return token
        return token

    for col in names:
        s = result[col]
        if mode == "Whole cell" and not flags:
            before = s.copy()
            for find, repl in pairs:
                s = s.replace(as_column_type(s, find), as_column_type(s, repl))
            new = s
        else:
            text = s.astype("string")
            before = text.copy()
            for find, repl in pairs:
                if mode == "Whole cell":
                    hit = text.str.lower() == find.lower()
                    text = text.mask(hit, repl)
                else:
                    pat = find if mode == "Regex" else re.escape(find)
                    text = text.str.replace(
                        pat, "" if repl is pd.NA else repl,
                        regex=True, flags=flags)
                    if repl is pd.NA:
                        text = text.mask(text == "", pd.NA)
            new = text
        result[col] = new
        changed += int((before.astype("string").fillna("\x00")
                        != new.astype("string").fillna("\x00")).sum())

    ctx.log(f"{len(pairs)} rule(s) over {len(names)} column(s); "
            f"{changed} cell(s) changed")
    return result
