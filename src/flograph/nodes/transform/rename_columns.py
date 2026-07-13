"""Rename Columns

Rename columns: one `old = new` mapping per line.
Lines starting with # are ignored.
"""
NODE = {
    "label": "Rename Columns",
    "category": "Transform",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "mapping", "type": "text", "label": "Renames (old = new)",
     "default": "", "placeholder": "revenue = revenue_usd\nunits = qty"},
]


def run(ctx, table):
    mapping = {}
    for lineno, line in enumerate(ctx.params["mapping"].splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        old, sep, new = line.partition("=")
        old, new = old.strip(), new.strip()
        if not sep or not old or not new:
            raise ValueError(f"line {lineno}: expected 'old = new', got {line!r}")
        mapping[old] = new
    if not mapping:
        raise ValueError("no renames given — one 'old = new' per line")
    missing = [c for c in mapping if c not in table.columns]
    if missing:
        raise ValueError(f"columns not in table: {missing}")
    ctx.log(f"renamed {len(mapping)} column(s)")
    return table.rename(columns=mapping)
