"""Expression

Add or overwrite columns using pandas eval expressions — one assignment per
line, e.g.:

    margin = revenue - cost
    ratio = margin / revenue
    big order = qty >= 100
    north = region == 'North'
    gap = abs(margin)

The right-hand side can do arithmetic and brackets, compare (`>=`, `==`,
`!=`; text goes in quotes), combine with `and` / `or`, and call `abs`,
`sqrt`, `log`, `exp` and the like. A later line can use a column an
earlier one made, and assigning to an existing column overwrites it. Lines
starting with `#` are skipped.

A column with a space in its name can be written as it is spelled, or in
backticks — `line total = unit price * qty` and
`` `line total` = `unit price` * qty `` both work. A name with other
punctuation in it and no space, like `price($)`, needs the backticks.
"""
NODE = {
    "label": "Expression",
    "category": "Transform",
    "version": "1.1",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "expressions", "type": "text", "label": "Assignments",
     "default": "",
     "placeholder": "margin = revenue - cost\n"
                    "ratio = margin / revenue\n"
                    "line total = unit price * qty\n"
                    "big order = qty >= 100\n"
                    "north = region == 'North'\n"
                    "gap = abs(margin)\n"
                    "euros = `price($)` * 0.92",
     "insert_columns": "inline"},
]


def run(ctx, table):
    from flograph.core.column_refs import quote_bare_columns, split_assignment

    lines = [(lineno, raw.strip())
             for lineno, raw in enumerate(ctx.params["expressions"].splitlines(), 1)
             if raw.strip() and not raw.strip().startswith("#")]
    if not lines:
        raise ValueError("no expressions given")
    result = table.copy(deep=False)
    for lineno, line in lines:
        parts = split_assignment(line)
        if parts is None or not parts[0] or not parts[1]:
            raise ValueError(f"line {lineno}: expected 'new_column = expression', "
                             f"got {line!r}")
        # the assignment is made here rather than by eval: pandas names a
        # backticked target BACKTICK_QUOTED_STRING_<name>
        target, expression = parts
        result[target] = result.eval(quote_bare_columns(expression, result.columns))
    return result
