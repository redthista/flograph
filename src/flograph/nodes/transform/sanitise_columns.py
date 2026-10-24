"""Sanitise Columns

Tidy the text in chosen columns in one pass, instead of a chain of String
Manipulation or Expression nodes. Tick the fixes you want: trim the ends,
collapse runs of whitespace, change case, strip non-printable characters,
remove URLs and email addresses, and turn blank cells into real missing values
(or fill missing ones with a value).

Leave *Columns* empty to clean every text column. Numbers, dates and other
non-text columns are left alone, and missing values stay missing unless you
fill them. Fixes run in the order listed; results replace the cell in place.
"""
NODE = {
    "label": "Sanitise Columns",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "columns", "type": "columns", "label": "Columns", "default": "",
     "placeholder": "empty = every text column"},
    {"name": "case", "type": "choice", "label": "Case",
     "options": ["keep", "lower", "upper", "title", "capitalize"],
     "default": "keep"},
    {"name": "trim", "type": "bool", "label": "Trim ends", "default": True},
    {"name": "collapse", "type": "bool", "label": "Collapse whitespace to one space",
     "default": True},
    {"name": "nonprintable", "type": "bool",
     "label": "Strip non-printable characters", "default": True},
    {"name": "urls", "type": "bool", "label": "Remove URLs", "default": False},
    {"name": "emails", "type": "bool", "label": "Remove email addresses",
     "default": False},
    {"name": "blank_to_na", "type": "bool",
     "label": "Blank cells become missing", "default": True},
    {"name": "replace_na", "type": "string", "label": "Fill missing with",
     "default": "", "placeholder": "empty = leave missing"},
]

_NONPRINTABLE = r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\x{200B}-\x{200D}\x{FEFF}]"
_URL = r"(?:https?://|www\.)\S+"
_EMAIL = r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"


def run(ctx, table):
    import pandas as pd

    p = ctx.params
    names = [c.strip() for c in p["columns"].split(",") if c.strip()]
    if names:
        missing = [c for c in names if c not in table.columns]
        if missing:
            raise ValueError(f"columns not in table: {missing}")
    else:
        names = [c for c in table.columns
                 if pd.api.types.is_object_dtype(table[c])
                 or pd.api.types.is_string_dtype(table[c])]
        if not names:
            raise ValueError("no text columns to clean")

    result = table.copy(deep=False)
    for name in names:
        ctx.check_cancelled()
        s = table[name]
        if not (pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s)):
            if p["columns"].strip():
                raise ValueError(f"column {name!r} is not text ({s.dtype})")
            continue
        s = s.astype("string")
        if p["nonprintable"]:
            s = s.str.replace(_NONPRINTABLE, "", regex=True)
        if p["urls"]:
            s = s.str.replace(_URL, "", regex=True)
        if p["emails"]:
            s = s.str.replace(_EMAIL, "", regex=True)
        if p["collapse"]:
            s = s.str.replace(r"\s+", " ", regex=True)
        if p["trim"] or p["urls"] or p["emails"]:
            s = s.str.strip()
        if p["case"] != "keep":
            s = getattr(s.str, p["case"])()
        if p["blank_to_na"]:
            s = s.mask(s.str.strip() == "", pd.NA)
        if p["replace_na"] != "":
            s = s.fillna(p["replace_na"])
        result[name] = s
    ctx.log(f"sanitised {len(names)} column(s)")
    return result
