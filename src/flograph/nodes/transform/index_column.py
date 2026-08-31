"""Index Column

Add a column of running numbers — Power Query's *Index Column*. Useful for a
stable row id to join back on later, for "row N of M" labels, or just to
preserve the current order before a sort scrambles it.

*Start* and *Step* set the first value and the gap between values (`0, 1` for
0-based, `1, 1` for 1-based, `10, 10` for `10, 20, 30…`). The column goes on
at the front by default; set *Position* to *Last* to append it instead.
"""
NODE = {
    "label": "Index Column",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "name", "type": "string", "label": "Column name",
     "default": "index"},
    {"name": "start", "type": "int", "label": "Start", "default": 1},
    {"name": "step", "type": "int", "label": "Step", "default": 1},
    {"name": "position", "type": "choice", "label": "Position",
     "options": ["First", "Last"], "default": "First"},
]


def run(ctx, table):
    p = ctx.params
    name = p["name"].strip()
    if not name:
        raise ValueError("'Column name' is empty")
    if name in table.columns:
        raise ValueError(f"column {name!r} already exists — pick another name")
    step = int(p["step"])
    if step == 0:
        raise ValueError("'Step' cannot be 0")

    start = int(p["start"])
    values = list(range(start, start + step * len(table), step))

    result = table.copy(deep=False)
    at = 0 if p["position"] == "First" else result.shape[1]
    result.insert(at, name, values)
    ctx.log(f"added {name!r} = {start}, {start + step}, … ({p['position'].lower()})")
    return result
