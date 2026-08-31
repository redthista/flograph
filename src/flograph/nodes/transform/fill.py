"""Fill

Fill the blanks in a column from the nearest value that isn't blank — Power
Query's *Fill Down* and *Fill Up*. The classic use is a spreadsheet where a
label was written once and left blank on the rows beneath it ("North" on the
first row of the region, then empty for the next five); Fill Down turns that
back into a real column you can group on.

*Down* carries each value forward onto the blank rows below it; *Up* carries
it backward onto the blanks above. Leave *Columns* empty to fill every
column. Only missing values are touched — a cell that already has a value is
never overwritten.
"""
NODE = {
    "label": "Fill",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "direction", "type": "choice", "label": "Direction",
     "options": ["Down", "Up"], "default": "Down"},
    {"name": "columns", "type": "columns", "label": "Columns", "default": "",
     "placeholder": "empty = every column"},
    {"name": "treat_blank_as_missing", "type": "bool",
     "label": "Treat empty text as blank", "default": True},
]


def run(ctx, table):
    import pandas as pd

    p = ctx.params
    names = [c.strip() for c in p["columns"].split(",") if c.strip()]
    if not names:
        names = list(table.columns)
    missing = [c for c in names if c not in table.columns]
    if missing:
        raise ValueError(f"columns not in table: {missing}")

    down = p["direction"] == "Down"
    result = table.copy(deep=False)

    textlike = (lambda s: s.dtype == object
                or pd.api.types.is_string_dtype(s))
    for col in names:
        s = result[col]
        if p["treat_blank_as_missing"] and textlike(s):
            s = s.mask(s.astype("string").str.strip() == "")
        result[col] = s.ffill() if down else s.bfill()

    ctx.log(f"filled {p['direction'].lower()} on {len(names)} column(s)")
    return result
