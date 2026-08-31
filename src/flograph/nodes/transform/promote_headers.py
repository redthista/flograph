"""Headers

Move data between the header row and the first data row — Power Query's *Use
First Row as Headers* and its reverse, *Headers as First Row*.

Files that arrive with a title line or two above the real column names load
with headers like `Unnamed: 0`, `Column1`; skip those junk rows on the reader
if you can, otherwise drop them here and then **Promote** the first good row
to be the header. **Demote** does the opposite — pushes the current column
names down into row 0 and replaces them with positional names (`Column1`,
`Column2`, …), which is what you want before writing a headerless export or
transposing.
"""
NODE = {
    "label": "Headers",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "mode", "type": "choice", "label": "Mode",
     "options": ["Promote first row", "Demote to first row"],
     "default": "Promote first row"},
    {"name": "skip_rows", "type": "int", "label": "Skip rows first",
     "default": 0, "min": 0,
     "placeholder": "drop this many rows before promoting"},
    {"name": "name_prefix", "type": "string", "label": "Positional name prefix",
     "default": "Column", "placeholder": "Column -> Column1, Column2, …"},
]


def _dedupe(names):
    seen, out = {}, []
    for n in names:
        if n in seen:
            seen[n] += 1
            out.append(f"{n}_{seen[n]}")
        else:
            seen[n] = 0
            out.append(n)
    return out


def run(ctx, table):
    import pandas as pd

    p = ctx.params
    prefix = p["name_prefix"]

    if p["mode"] == "Promote first row":
        skip = int(p["skip_rows"])
        if len(table) <= skip:
            raise ValueError(
                f"table has {len(table)} row(s) — nothing left to promote "
                f"after skipping {skip}")
        body = table.iloc[skip:]
        header = body.iloc[0].tolist()
        names = _dedupe([str(h) if pd.notna(h) else f"{prefix}{i + 1}"
                         for i, h in enumerate(header)])
        result = body.iloc[1:].copy()
        result.columns = names
        result = result.reset_index(drop=True)
        ctx.log(f"promoted row {skip} to header: {', '.join(names)}")
        return result

    names = [f"{prefix}{i + 1}" for i in range(table.shape[1])]
    old = pd.DataFrame([table.columns.tolist()], columns=names)
    body = table.copy()
    body.columns = names
    result = pd.concat([old, body], ignore_index=True)
    ctx.log(f"demoted {table.shape[1]} header(s) into row 0")
    return result
