"""Label Encode

Swap each value of a text column for a whole number — `bronze`, `gold`,
`silver` become 0, 1, 2 (in sorted order) — and keep the key, so numbers a
model predicts can be turned back into words.

Leave **Columns** empty to encode every text column. A missing cell becomes
**Missing as** (−1 by default).

**mappings** holds the key for every column. Wire it into the **mappings**
input of another Label Encode and that node uses the same key rather than
making its own — set **Direction** to *decode* there to turn codes back into
labels, which is how a model's predictions get their class names back. A
value the key doesn't have encodes as *Missing as*, and a code it doesn't
have decodes as missing.
"""
NODE = {
    "label": "Label Encode",
    "category": "ML",
    "version": "1.0",
    "inputs": [("table", "dataframe"),
               ("mappings", "object", {"optional": True,
                                       "suggest": ["flograph.ml.label_encode"]})],
    "outputs": [("encoded", "dataframe"), ("mappings", "object")],
}
PARAMS = [
    {"name": "direction", "type": "choice", "label": "Direction",
     "options": ["encode", "decode"], "default": "encode"},
    {"name": "columns", "type": "columns", "label": "Columns",
     "default": "", "placeholder": "empty = every text column (or every "
                                   "column the key has)"},
    {"name": "missing_value", "type": "int", "label": "Missing as",
     "default": -1},
]

_KIND = "flograph.labels"


def run(ctx, table, mappings=None):
    import pandas as pd

    p = ctx.params
    if mappings is not None and not (isinstance(mappings, dict)
                                     and mappings.get("kind") == _KIND):
        raise ValueError("'mappings' takes the mappings output of another "
                         "Label Encode")
    key = dict(mappings["columns"]) if mappings is not None else {}
    named = [c.strip() for c in str(p["columns"]).split(",") if c.strip()]
    decode = p["direction"] == "decode"
    if decode and mappings is None:
        raise ValueError("decoding needs the key — wire the mappings output "
                         "of the Label Encode that made the codes")

    if named:
        columns = named
    elif key:
        columns = [c for c in key if c in table.columns]
    else:
        columns = [c for c in table.columns
                   if not pd.api.types.is_numeric_dtype(table[c])
                   and not pd.api.types.is_datetime64_any_dtype(table[c])]
    missing = [c for c in columns if c not in table.columns]
    if missing:
        raise ValueError(f"columns not in table: {missing}")
    if not columns:
        raise ValueError("no columns to encode — name them in 'Columns'")

    out = table.copy(deep=False)
    blank = int(p["missing_value"])
    for c in columns:
        if decode:
            if c not in key:
                raise ValueError(f"the key has no column {c!r}")
            back = {code: label for label, code in key[c].items()}
            out[c] = table[c].map(back)
            continue
        if c not in key:
            levels = sorted(table[c].dropna().astype(str).unique().tolist())
            key[c] = {level: i for i, level in enumerate(levels)}
        text = table[c].astype("object").where(table[c].notna(), None)
        codes = text.map(lambda v: None if v is None else str(v)).map(key[c])
        out[c] = codes.fillna(blank).astype("int64")

    ctx.log(("decoded " if decode else "encoded ")
            + ", ".join(f"{c} ({len(key[c])})" for c in columns))
    return {"encoded": out, "mappings": {"kind": _KIND, "columns": key}}
