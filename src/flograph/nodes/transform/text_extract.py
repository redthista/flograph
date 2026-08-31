"""Text Extract

Pull a piece out of a text column — Power Query's *Extract* menu. Take the
first or last N characters, a fixed range, the text before / after / between
delimiters, or just the length. The classic uses: grab the domain out of an
email (*after* `@`), the extension off a filename (*after last* `.`), an area
code from a phone number (*between* `(` and `)`).

The result lands in a new column, named `<column>.extract` unless you set
*Output column*. Rows where the delimiter isn't found come back empty.
"""
NODE = {
    "label": "Text Extract",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
_MODES = [
    "Length", "First characters", "Last characters", "Range",
    "Text before delimiter", "Text after delimiter", "Text between delimiters",
]
PARAMS = [
    {"name": "column", "type": "columns", "label": "Column", "default": "",
     "multi": False},
    {"name": "mode", "type": "choice", "label": "Extract", "options": _MODES,
     "default": "Text after delimiter"},
    {"name": "count", "type": "int", "label": "Character count", "default": 3,
     "min": 0},
    {"name": "start", "type": "int", "label": "Range start (0-based)",
     "default": 0, "min": 0},
    {"name": "length", "type": "int", "label": "Range length", "default": 5,
     "min": 0},
    {"name": "delimiter", "type": "string", "label": "Delimiter", "default": "@",
     "placeholder": "left delimiter for 'between'"},
    {"name": "delimiter_end", "type": "string", "label": "End delimiter",
     "default": "", "placeholder": "'between' only; empty = reuse delimiter"},
    {"name": "from_end", "type": "bool", "label": "Search from the end",
     "default": False},
    {"name": "output_column", "type": "string", "label": "Output column",
     "default": "", "placeholder": "empty = <column>.extract"},
]


def run(ctx, table):
    import pandas as pd

    p = ctx.params
    col = p["column"].strip()
    if not col:
        raise ValueError("no column selected — set 'Column'")
    if col not in table.columns:
        raise ValueError(f"column {col!r} not in table")

    s = table[col].astype("string")
    mode = p["mode"]
    d1 = p["delimiter"]
    d2 = p["delimiter_end"] or d1
    from_end = p["from_end"]

    def before(text):
        if text is pd.NA or text != text:
            return pd.NA
        i = text.rfind(d1) if from_end else text.find(d1)
        return text[:i] if i != -1 else pd.NA

    def after(text):
        if text is pd.NA or text != text:
            return pd.NA
        i = text.rfind(d1) if from_end else text.find(d1)
        return text[i + len(d1):] if i != -1 else pd.NA

    def between(text):
        if text is pd.NA or text != text:
            return pd.NA
        i = text.find(d1)
        if i == -1:
            return pd.NA
        j = text.find(d2, i + len(d1))
        return text[i + len(d1):j] if j != -1 else pd.NA

    if mode == "Length":
        out = s.str.len().astype("Int64")
    elif mode == "First characters":
        out = s.str.slice(0, int(p["count"]))
    elif mode == "Last characters":
        n = int(p["count"])
        out = s.str.slice(-n) if n else s.str.slice(0, 0)
    elif mode == "Range":
        start = int(p["start"])
        out = s.str.slice(start, start + int(p["length"]))
    elif mode == "Text before delimiter":
        if not d1:
            raise ValueError("'Delimiter' is empty")
        out = s.map(before)
    elif mode == "Text after delimiter":
        if not d1:
            raise ValueError("'Delimiter' is empty")
        out = s.map(after)
    elif mode == "Text between delimiters":
        if not d1:
            raise ValueError("'Delimiter' is empty")
        out = s.map(between)
    else:
        raise ValueError(f"unknown mode: {mode!r}")

    result = table.copy(deep=False)
    name = p["output_column"].strip() or f"{col}.extract"
    result[name] = out.values
    ctx.log(f"{col!r} → {name!r} ({mode.lower()})")
    return result
