"""Expression

Add or overwrite columns using pandas eval expressions — one assignment per
line, e.g.:

    margin = revenue - cost
    ratio = margin / revenue
"""
NODE = {
    "label": "Expression",
    "category": "Transform",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "expressions", "type": "text", "label": "Assignments",
     "default": "", "placeholder": "new_col = col_a * 2"},
]


def run(ctx, table):
    lines = [l.strip() for l in ctx.params["expressions"].splitlines()
             if l.strip() and not l.strip().startswith("#")]
    if not lines:
        raise ValueError("no expressions given")
    result = table.copy(deep=False)
    for line in lines:
        result = result.eval(line)
    return result
