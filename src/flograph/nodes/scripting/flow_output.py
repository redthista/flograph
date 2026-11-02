"""Flow Output

Marks a value for a parent Run Flow node to return. Give each output in a
child flow a distinct name, then select that name in its parent.
"""
NODE = {
    "label": "Flow Output",
    "category": "Scripting",
    "version": "1.0",
    "inputs": [("value", "any")],
    "outputs": [("value", "any")],
}
PARAMS = [
    {"name": "name", "type": "string", "label": "Name",
     "default": "result", "placeholder": "Selected by the parent flow"},
]


def run(ctx, value):
    name = str(ctx.params.get("name", "")).strip()
    if not name:
        raise ValueError("set a name for this flow output")
    ctx.log(f"flow output available as {name!r}")
    return {"value": value}
