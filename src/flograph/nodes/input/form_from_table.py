"""Form from Table

Make a User Form fields schema from one table column per field. Column names
become labels and safe field keys; inferred field types keep submissions
typed for common numeric, boolean and date columns.
"""
NODE = {
    "label": "Form from Table",
    "category": "Input",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("fields", "string")],
}
PARAMS = [
    {"name": "all_text", "type": "bool", "label": "Use text fields",
     "default": False},
]


def run(ctx, table):
    import re

    import pandas as pd

    from flograph.core.form import Field, schema_to_text

    fields = []
    used = set()
    for column_index, column in enumerate(table.columns):
        label = str(column)
        name = re.sub(r"[^0-9A-Za-z_]+", "_", label.strip()).strip("_").lower()
        if not name:
            name = "field"
        if name[0].isdigit():
            name = f"field_{name}"
        base = name
        suffix = 2
        while name.casefold() in used:
            name = f"{base}_{suffix}"
            suffix += 1
        used.add(name.casefold())

        if ctx.params.get("all_text"):
            kind, default = "text", ""
        else:
            dtype = table.iloc[:, column_index].dtype
            if pd.api.types.is_bool_dtype(dtype):
                kind, default = "toggle", False
            elif pd.api.types.is_integer_dtype(dtype):
                kind, default = "int", 0
            elif pd.api.types.is_float_dtype(dtype):
                kind, default = "float", 0.0
            elif pd.api.types.is_datetime64_any_dtype(dtype):
                kind, default = "date", ""
            else:
                kind, default = "text", ""
        fields.append(Field(name, kind, label, default))
    return {"fields": schema_to_text(fields)}
