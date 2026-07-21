"""Node Template

A commented starting point for writing your own node. Drop it on the canvas,
right-click it and choose Edit Code — every placed node carries its own copy
of this code, so you can rewrite it freely without affecting other nodes.

The example below appends a computed column to a table; swap out the ports,
params and run() body to build whatever you need.
"""

# NODE declares how the node appears to the graph: its palette label and
# category, and the ports wires can attach to. Ports are (name, type) tuples
# — add {"optional": True} as a third element for inputs that may be left
# unconnected. Valid port types: any, dataframe, series, number, string,
# bool, object, figure.
NODE = {
    "label": "Node Template",
    "category": "Scripting",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}

# PARAMS declares the widgets shown in the properties panel; each value
# arrives in run() via ctx.params. Valid types: string (line edit), text
# (multiline), int, float, bool, choice (needs "options"), file_open,
# file_save, columns, password (masked, with a show/hide toggle).
PARAMS = [
    {"name": "source", "type": "string", "label": "Source column",
     "default": "", "placeholder": "blank = first numeric column"},
    {"name": "operation", "type": "choice", "label": "Operation",
     "options": ["multiply", "add"], "default": "multiply"},
    {"name": "factor", "type": "float", "label": "Factor", "default": 2.0},
    {"name": "new_column", "type": "string", "label": "New column",
     "default": "result"},
]


# run() is called with each input port as a keyword argument (unconnected
# optional inputs arrive as None) and returns a dict keyed by output port
# name. Treat inputs as read-only — outputs are cached and shared by
# reference, so copy before mutating. Keep heavy imports inside run(), and
# create figures with matplotlib.figure.Figure(), never pyplot.
#
# ctx is the run context:
#   ctx.params            current param values (dict)
#   ctx.log(msg)          write to the log console
#   ctx.progress(0.5)     report progress from long loops
#   ctx.check_cancelled() raise if the user hit cancel
def run(ctx, table):
    source = ctx.params["source"].strip()
    if not source:
        numeric = table.select_dtypes("number").columns
        if numeric.empty:
            raise ValueError("no numeric column to compute from")
        source = numeric[0]
    if source not in table.columns:
        raise ValueError(f"column {source!r} not in table")

    factor = ctx.params["factor"]
    if ctx.params["operation"] == "multiply":
        computed = table[source] * factor
    else:
        computed = table[source] + factor

    out = table.copy()
    out[ctx.params["new_column"] or "result"] = computed
    ctx.log(f"computed {ctx.params['new_column']!r} from {source!r}")
    return {"table": out}
