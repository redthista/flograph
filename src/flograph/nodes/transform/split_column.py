"""Split Column

Split one text column into several, the way Power Query's *Split Column*
does: by a delimiter (at every occurrence, or just the first / last one), by
a fixed number of characters, or at explicit character positions. The pieces
land in new columns beside the original, or — with *Split into* set to
*Rows* — as extra rows with every other value repeated.

*Number of columns* left at 0 makes as many columns as the widest value
needs; set to N and every row gets exactly N (short ones padded, extra
pieces dropped) — a stable schema for whatever comes next.
"""
NODE = {
    "label": "Split Column",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "column", "type": "columns", "label": "Column", "default": "",
     "multi": False},
    {"name": "split_by", "type": "choice", "label": "Split by",
     "options": ["Delimiter", "Number of characters", "Positions"],
     "default": "Delimiter"},
    {"name": "split_at", "type": "choice", "label": "Split at",
     "options": ["Each occurrence", "Left-most", "Right-most"],
     "default": "Each occurrence"},
    {"name": "delimiter", "type": "string", "label": "Delimiter",
     "default": ",", "placeholder": "e.g. , or ' - '"},
    {"name": "char_count", "type": "int", "label": "Number of characters",
     "default": 1, "min": 1},
    {"name": "positions", "type": "string", "label": "Positions",
     "default": "", "placeholder": "e.g. 3, 7"},
    {"name": "name_prefix", "type": "string", "label": "New column prefix",
     "default": "", "placeholder": "empty = <column>."},
    {"name": "max_columns", "type": "int", "label": "Number of columns",
     "default": 0, "min": 0, "placeholder": "0 = as many as needed"},
    {"name": "split_into", "type": "choice", "label": "Split into",
     "options": ["Columns", "Rows"], "default": "Columns"},
    {"name": "keep_original", "type": "bool", "label": "Keep original column",
     "default": False},
]


def _parse_positions(raw):
    parts = (raw or "").replace(",", " ").split()
    try:
        nums = sorted({int(x) for x in parts})
    except ValueError:
        raise ValueError(
            "'Positions' must be whole numbers separated by commas, e.g. 3, 7")
    nums = [n for n in nums if n > 0]
    if not nums:
        raise ValueError("'Positions' needs at least one positive number")
    return nums


def _by_positions(text, cuts):
    if not isinstance(text, str):
        return []
    bounds = [0] + [c for c in cuts if c < len(text)] + [len(text)]
    return [text[a:b] for a, b in zip(bounds, bounds[1:])]


def _by_count(text, n, at):
    if not isinstance(text, str):
        return []
    if at == "Left-most":
        return [text[:n], text[n:]] if len(text) > n else [text, ""]
    if at == "Right-most":
        return [text[:-n], text[-n:]] if len(text) > n else ["", text]
    return [text[i:i + n] for i in range(0, len(text), n)] or [""]


def _unique(name, seen):
    candidate, i = name, 2
    while candidate in seen:
        candidate, i = f"{name}_{i}", i + 1
    seen.add(candidate)
    return candidate


def run(ctx, table):
    import pandas as pd

    p = ctx.params
    column = p["column"].strip()
    if not column:
        raise ValueError(
            "no column selected — set 'Column' in the node's properties")
    if column not in table.columns:
        raise ValueError(f"column {column!r} not in table")

    s = table[column].astype("string")
    mode = p["split_by"]
    at = p["split_at"]

    if mode == "Delimiter":
        delim = p["delimiter"]
        if delim == "":
            raise ValueError("'Delimiter' is empty — set the text to split on")
        if at == "Left-most":
            lists = s.str.split(delim, n=1, regex=False)
        elif at == "Right-most":
            lists = s.str.rsplit(delim, n=1, regex=False)
        else:
            lists = s.str.split(delim, regex=False)
    elif mode == "Number of characters":
        n = int(p["char_count"])
        if n < 1:
            raise ValueError("'Number of characters' must be at least 1")
        lists = s.map(lambda t: _by_count(t, n, at))
    elif mode == "Positions":
        cuts = _parse_positions(p["positions"])
        lists = s.map(lambda t: _by_positions(t, cuts))
    else:
        raise ValueError(f"unknown 'Split by' mode: {mode!r}")

    lists = lists.map(lambda v: list(v) if isinstance(v, list) else [])

    prefix = p["name_prefix"].strip() or f"{column}."
    keep = bool(p["keep_original"])
    result = table.copy(deep=False)

    if p["split_into"] == "Rows":
        tmp = "__flograph_split__"
        work = result.assign(**{tmp: lists.values}).explode(tmp,
                                                            ignore_index=True)
        work[tmp] = work[tmp].astype("string")
        if keep:
            target = _unique(prefix.rstrip(".") or f"{column}_part",
                             set(work.columns))
            work = work.rename(columns={tmp: target})
        else:
            order = list(result.columns)
            work = work.drop(columns=[column]).rename(columns={tmp: column})
            work = work[order]
        ctx.log(f"split {column!r} by {mode.lower()} into "
                f"{len(work)} rows (was {len(result)})")
        return work

    fixed = int(p["max_columns"])
    if fixed > 0:
        width = fixed  # exactly this many — pad short rows, drop the overflow
    else:
        width = max((len(v) for v in lists), default=0)
    if width == 0:
        raise ValueError(f"nothing to split — every value in {column!r} was empty")

    seen = set(result.columns)
    if not keep:
        seen.discard(column)
    names = [_unique(f"{prefix}{i + 1}", seen) for i in range(width)]

    insert_at = result.columns.get_loc(column)
    if keep:
        insert_at += 1
    else:
        result = result.drop(columns=[column])

    for offset, cn in enumerate(names):
        values = [v[offset] if offset < len(v) else pd.NA for v in lists]
        result.insert(min(insert_at + offset, result.shape[1]), cn,
                      pd.array(values, dtype="string"))

    ctx.log(f"split {column!r} by {mode.lower()} into {width} columns: "
            f"{', '.join(names)}")
    return result
