"""Constant

Emit a constant value, converted to the chosen type.
"""
NODE = {
    "label": "Constant",
    "category": "Util",
    "inputs": [],
    "outputs": [("value", "any")],
}
PARAMS = [
    {"name": "kind", "type": "choice", "label": "Type",
     "options": ["string", "int", "float", "bool"], "default": "string"},
    {"name": "value", "type": "string", "label": "Value", "default": ""},
]


def run(ctx):
    raw = ctx.params["value"]
    kind = ctx.params["kind"]
    if kind == "int":
        return int(raw)
    if kind == "float":
        return float(raw)
    if kind == "bool":
        return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")
    return raw
