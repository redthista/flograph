"""String Manipulation

Apply a string operation to one column: case
changes, whitespace strip, or find & replace (plain text or regex). Write
the result in place or into a new column.
"""
NODE = {
    "label": "String Manipulation",
    "category": "Transform",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "column", "type": "columns", "label": "Column", "default": "",
     "multi": False},
    {"name": "operation", "type": "choice", "label": "Operation",
     "options": ["upper", "lower", "title", "capitalize", "strip", "replace"],
     "default": "lower"},
    {"name": "find", "type": "string", "label": "Find (replace only)",
     "default": ""},
    {"name": "replace_with", "type": "string", "label": "Replace with",
     "default": ""},
    {"name": "regex", "type": "bool", "label": "Find is a regex",
     "default": False},
    {"name": "output_column", "type": "string", "label": "Output column",
     "default": "", "placeholder": "empty = replace in place"},
]


def run(ctx, table):
    column = ctx.params["column"].strip()
    if not column:
        raise ValueError("no column selected")
    if column not in table.columns:
        raise ValueError(f"column {column!r} not in table")

    series = table[column].astype("string")
    operation = ctx.params["operation"]
    if operation == "replace":
        find = ctx.params["find"]
        if not find:
            raise ValueError("'replace' needs a 'Find' value")
        series = series.str.replace(find, ctx.params["replace_with"],
                                    regex=ctx.params["regex"])
    else:
        series = getattr(series.str, operation)()

    result = table.copy()
    target = ctx.params["output_column"].strip() or column
    result[target] = series
    ctx.log(f"{operation} on {column!r} -> {target!r}")
    return result
