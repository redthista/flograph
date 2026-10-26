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

**A lookup table.** For a longer mapping — country codes to names, status
codes to labels — wire a table into **lookup**: its first column is what to
find and its second what to put instead (a Series or a dict works too). The
lookup is applied in one step, so `A = B` and `B = C` in it never chain into
`A → C`. Typed pairs are applied first, then the lookup.

**Unmatched cells** (Whole cell only) decides what happens to a cell that no
pair or lookup row matched: keep it, make it missing, or write a **Default**
— `Unknown`, say — so every row ends up with a label.
"""
import re

NODE = {
    "label": "Replace Values",
    "category": "Transform",
    "version": "1.1",
    "inputs": [("table", "dataframe"),
               ("lookup", "any", {"optional": True})],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "match", "type": "choice", "label": "Match",
     "options": ["Whole cell", "Substring", "Regex"], "default": "Whole cell"},
    {"name": "columns", "type": "columns", "label": "Columns", "default": "",
     "placeholder": "empty = whole table"},
    {"name": "case_insensitive", "type": "bool", "label": "Ignore case",
     "default": False},
    {"name": "unmatched", "type": "choice", "label": "Unmatched cells",
     "options": ["keep as is", "make missing", "use default"],
     "default": "keep as is", "visible_when": {"match": ["Whole cell"]}},
    {"name": "default", "type": "string", "label": "Default",
     "default": "", "placeholder": "e.g. Unknown",
     "visible_when": {"unmatched": ["use default"]}},
    {"name": "pairs", "type": "text", "label": "Replacements (find = replace)",
     "default": "", "placeholder": "N/A = <NA>\n- = <NA>\nU.S.A. = USA"},
]


def _is_missing(value):
    import pandas as pd

    return value is None or (not isinstance(value, str) and pd.isna(value))


def _lookup_pairs(lookup):
    """(find, replace) pairs out of a wired table, Series or dict."""
    import pandas as pd

    if lookup is None:
        return []
    if isinstance(lookup, pd.DataFrame):
        if lookup.shape[1] < 2:
            raise ValueError("the lookup table needs two columns: what to "
                             "find, then what to put instead")
        items = zip(lookup.iloc[:, 0], lookup.iloc[:, 1])
    elif isinstance(lookup, (pd.Series, dict)):
        items = lookup.items()
    else:
        raise ValueError("'lookup' takes a two-column table, a Series or a "
                         f"dict, not {type(lookup).__name__}")
    return [(str(find).strip(), pd.NA if _is_missing(repl) else str(repl))
            for find, repl in items if not _is_missing(find)]


def run(ctx, table, lookup=None):
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
    mapped = _lookup_pairs(lookup)
    if not pairs and not mapped:
        raise ValueError("no replacements — one 'find = replace' per line, "
                         "or wire a table into 'lookup'")

    names = [c.strip() for c in p["columns"].split(",") if c.strip()]
    if not names:
        names = list(table.columns)
    missing = [c for c in names if c not in table.columns]
    if missing:
        raise ValueError(f"columns not in table: {missing}")

    mode = p["match"]
    flags = re.IGNORECASE if p["case_insensitive"] else 0
    unmatched = p.get("unmatched", "keep as is") if mode == "Whole cell" \
        else "keep as is"
    fallback = pd.NA if unmatched == "make missing" else p.get("default", "")
    keys = [find for find, _ in pairs + mapped]
    result = table.copy(deep=False)
    changed = filled = 0

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
        hit = None
        if mode == "Whole cell" and not flags:
            before = s.copy()
            for find, repl in pairs:
                s = s.replace(as_column_type(s, find), as_column_type(s, repl))
            if mapped:
                # one call maps every key at once, so the lookup never chains
                s = s.replace({as_column_type(before, f): as_column_type(before, r)
                               for f, r in mapped})
            hit = before.isin([as_column_type(before, k) for k in keys])
            new = s
        else:
            text = s.astype("string")
            before = text.copy()
            lowered = before.str.lower()
            for find, repl in pairs + (mapped if mode != "Whole cell" else []):
                if mode == "Whole cell":
                    text = text.mask(text.str.lower() == find.lower(), repl)
                else:
                    pat = find if mode == "Regex" else re.escape(find)
                    text = text.str.replace(
                        pat, "" if repl is pd.NA else repl,
                        regex=True, flags=flags)
                    if repl is pd.NA:
                        text = text.mask(text == "", pd.NA)
            if mode == "Whole cell":
                if mapped:
                    by_key = {f.lower(): r for f, r in mapped}
                    text = text.mask(lowered.isin(by_key), lowered.map(by_key))
                hit = lowered.isin([k.lower() for k in keys])
            new = text
        if unmatched != "keep as is":
            lost = ~hit.fillna(False).astype(bool) & before.notna()
            if lost.any():
                new = new.astype("object").mask(lost, fallback)
                filled += int(lost.sum())
        result[col] = new
        changed += int((before.astype("string").fillna("\x00")
                        != new.astype("string").fillna("\x00")).sum())

    ctx.log(f"{len(pairs)} rule(s)"
            + (f" + {len(mapped)} lookup row(s)" if mapped else "")
            + f" over {len(names)} column(s); {changed} cell(s) changed"
            + (f", {filled} unmatched" if filled else ""))
    return result
