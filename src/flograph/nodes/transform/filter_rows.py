"""Filter Rows

Keep the rows of a DataFrame matching a pandas query expression; the rows
that don't match come out of the second port.
"""
NODE = {
    "label": "Filter Rows",
    "category": "Transform",
    "inputs": [("table", "dataframe")],
    "outputs": [("filtered", "dataframe"), ("rejected", "dataframe")],
}
PARAMS = [
    {"name": "query", "type": "string", "label": "Query expression",
     "default": "", "placeholder": "col_a > 0 and col_b == 'x'"},
]


def run(ctx, table):
    query = ctx.params["query"].strip()
    if not query:
        return {"filtered": table, "rejected": table.iloc[0:0]}
    mask = table.eval(query)
    ctx.log(f"kept {int(mask.sum())} / {len(table)} rows")
    return {"filtered": table[mask], "rejected": table[~mask]}
