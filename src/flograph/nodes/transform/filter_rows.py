"""Filter Rows

Keep the rows of a DataFrame matching a pandas query expression; the rows
that don't match come out of the second port.

A column with a space in its name can be written as it is spelled
(`unit price > 5`) or in backticks (`` `unit price` > 5 ``); a name with
other punctuation in it, like `price($)`, needs the backticks.
"""
NODE = {
    "label": "Filter Rows",
    "category": "Transform",
    "version": "1.1",
    "inputs": [("table", "dataframe")],
    "outputs": [("filtered", "dataframe"), ("rejected", "dataframe")],
}
PARAMS = [
    {"name": "query", "type": "string", "label": "Query expression",
     "default": "", "placeholder": "col_a > 0 and col_b == 'x'"},
]


def run(ctx, table):
    from flograph.core.column_refs import quote_bare_columns

    query = ctx.params["query"].strip()
    if not query:
        return {"filtered": table, "rejected": table.iloc[0:0]}
    mask = table.eval(quote_bare_columns(query, table.columns))
    ctx.log(f"kept {int(mask.sum())} / {len(table)} rows")
    return {"filtered": table[mask], "rejected": table[~mask]}
