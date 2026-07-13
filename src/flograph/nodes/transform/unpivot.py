"""Unpivot

Melt a wide table into a long one (KNIME Unpivot): the retained columns
repeat on every row, each value column becomes (variable, value) pairs.
"""
NODE = {
    "label": "Unpivot",
    "category": "Transform",
    "inputs": [("table", "dataframe")],
    "outputs": [("long", "dataframe")],
}
PARAMS = [
    {"name": "id_columns", "type": "columns", "label": "Retained columns",
     "default": "", "placeholder": "comma separated"},
    {"name": "value_columns", "type": "columns", "label": "Value columns",
     "default": "", "placeholder": "empty = all others"},
    {"name": "var_name", "type": "string", "label": "Variable column name",
     "default": "variable"},
    {"name": "value_name", "type": "string", "label": "Value column name",
     "default": "value"},
]


def run(ctx, table):
    def cols(name):
        raw = ctx.params[name].strip()
        if not raw:
            return None
        listed = [c.strip() for c in raw.split(",") if c.strip()]
        missing = [c for c in listed if c not in table.columns]
        if missing:
            raise ValueError(f"columns not in table: {missing}")
        return listed

    long = table.melt(id_vars=cols("id_columns"),
                      value_vars=cols("value_columns"),
                      var_name=ctx.params["var_name"] or "variable",
                      value_name=ctx.params["value_name"] or "value")
    ctx.log(f"{len(table)} rows -> {len(long)}")
    return long
