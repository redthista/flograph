"""Variables

Name values once here and use them anywhere in the flow -- write ${name} in
any text box in the Properties panel, or read ctx.vars["name"] in a script.

One `name = value` per line:

    data_dir = C:/data
    region   = North

Then a Read CSV's path can be `${data_dir}/sales.csv` and a Filter's query
`region == "${region}"`. Change the value here and every node that reads it
re-runs -- flograph treats a ${name} as a real connection, so ordering and
re-runs work exactly as they would with a wire, without the wire.

**Values from data.** Wire a dict into "values", or a table into "table", to
have variables come from a config file, a slicer or anything else upstream.
Those win over the text box, which then reads as the defaults. Names that
only appear from a wired input cannot be referenced as ${name}: nothing can
know they exist until this node runs, and a node that reads one could be
scheduled before the value arrives. Declare it in the text box (any value
will do) and the wired input will override it.

**Secrets** live in a .env file, not here, and are written `${env:NAME}` --
this node never holds them, so they never enter the saved project file.
"""
NODE = {
    "label": "Variables",
    "category": "Util",
    "card": "vars",
    "inputs": [("values", "any", {"optional": True}),
               ("table", "dataframe", {"optional": True})],
    "outputs": [("vars", "any")],
}
PARAMS = [
    {"name": "assignments", "type": "text", "label": "Variables",
     "default": "", "placeholder": "data_dir = C:/data\nregion = North"},
    {"name": "table_mode", "type": "choice", "label": "From table",
     "options": ["first row (columns are names)", "name/value columns"],
     "default": "first row (columns are names)"},
]


def run(ctx, values=None, table=None):
    from flograph.core.varlinks import parse_assignments

    declared, problems = parse_assignments(ctx.params["assignments"])
    if problems:
        raise ValueError("; ".join(problems))

    resolved = dict(declared)
    resolved.update(_from_mapping(ctx, values))
    resolved.update(_from_table(ctx, table, ctx.params["table_mode"]))
    return {"vars": resolved}


def _usable(ctx, name):
    """A variable has to be nameable to be worth anything: ${2024} cannot be
    written, so a column or key that isn't an identifier is dropped rather
    than carried as something nobody can reference."""
    name = str(name)
    if name.isidentifier():
        return True
    ctx.log(f"skipped {name!r}: not a valid variable name")
    return False


def _from_mapping(ctx, values):
    if values is None:
        return {}
    if not hasattr(values, "items"):
        raise TypeError(
            f"'values' expects a dict, got {type(values).__name__}")
    return {str(k): v for k, v in values.items() if _usable(ctx, k)}


def _from_table(ctx, table, mode):
    if table is None:
        return {}
    if getattr(table, "empty", True):
        return {}
    if mode == "name/value columns":
        columns = list(table.columns)
        if len(columns) < 2:
            raise ValueError(
                "'name/value columns' needs a table with two columns")
        # By name where they exist, by position otherwise: a two-column frame
        # from a CSV usually has headers, and one built by hand usually
        # doesn't.
        name_col = "name" if "name" in columns else columns[0]
        value_col = "value" if "value" in columns else columns[1]
        pairs = zip(table[name_col], table[value_col])
        return {str(k): v for k, v in pairs if _usable(ctx, k)}
    row = table.iloc[0]
    return {str(k): row[k] for k in table.columns if _usable(ctx, k)}
