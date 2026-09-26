"""Node Template

A commented starting point for writing your own node. Drop it on the canvas,
right-click it and choose Edit Code — every placed node carries its own copy
of this code, so you can rewrite it freely without affecting other nodes.

The example below appends a computed column to a table; swap out the ports,
params and run() body to build whatever you need. Everything a node script
may declare is shown or listed here, so the file doubles as a reference —
the handbook page "Writing a Node" (F1) is the same ground in prose.
"""

# ----------------------------------------------------------------- NODE ---
# NODE declares how the node appears to the graph. Only `label`, `category`,
# `inputs` and `outputs` are required; unknown keys are ignored, so a node
# file written for a newer flograph still loads on an older one.
#
#   label        name in the palette and on the node
#   category     library section: IO, Transform, Viz, Input, Util,
#                Scripting — or a name of your own, which makes a section
#   version      this node *type's* version, bumped by hand when its params
#                or behaviour change. Not the app's version: it answers
#                "is the node in front of me the one I just edited?"
#   inputs       list of (name, type) tuples wires may attach to
#   outputs      the same, for what run() returns
#   exclusive    True = run this node with nothing else in flight. For
#                matplotlib, and for anything else that tolerates one user
#                at a time. See the concurrency note under run().
#   card         draw a live card instead of a plain node: "figure",
#                "webview", "table_viewer", "kpi", "slicer", "control",
#                "button", "note", "grid", "image", "pdf", "report",
#                "wiki", "goto", "from", "reroute", "pagelinks", "vars"
#   control      with card == "control", which widget: "slider", "range",
#                "number", "text", "date", "toggle", "choice"
#   interactive  with card == "webview", lets the page write this node's own
#                params from JavaScript, which dirties it and re-runs what
#                follows — a click inside a chart doing what a Slicer tick
#                does
#   reads_report the name of a page_ref param: the node runs after every
#                node that report page embeds (Save Report uses it)
#
# Ports are (name, type) tuples, or (name, type, opts) where opts may carry
#   {"optional": True}  the node runs with this input unconnected (it
#                       arrives as None); a required input left unwired
#                       blocks the run instead
#   {"spare": True}     the trailing "one more slot" of a node that takes an
#                       open-ended stack of inputs (see Concatenate): wiring
#                       it makes a permanent port and a fresh slot appears
#                       below it. Optional comes with it.
# Port types: any, dataframe, series, number, string, bool, object, figure.
# A wire is allowed when the types are compatible — `any` fits anything, and
# most concrete types widen into an `object` input. Every node also carries
# two hidden flow pins for order edges ("run after that one"); those are
# never declared.
NODE = {
    "label": "Node Template",
    "category": "Scripting",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}

# --------------------------------------------------------------- PARAMS ---
# PARAMS declares the widgets shown in the properties panel; each value
# arrives in run() via ctx.params[name]. Flow variables work in any text
# param: write ${data_dir} and it resolves from a Variables node.
#
# Types:
#   string       single-line text
#   text         multi-line text
#   int          spin box
#   float        spin box with decimals
#   bool         checkbox
#   choice       dropdown — needs "options"
#   columns      column names, with a picker of the input's columns
#   date         calendar picker, stores "YYYY-MM-DD"
#   color        swatch + colour picker, stores "#rrggbb" ("" = theme)
#   password     masked entry with a reveal toggle
#   file_open / file_save / folder_open   text plus a browse button
#   node_ref     dropdown of the other nodes in the graph, stores a node id
#   page_ref     the project's pages, stores a page id
#
# Extra keys, all optional:
#   label          row label (defaults to a title-cased name)
#   default        starting value
#   placeholder    grey hint shown while the box is empty
#   options        choice only: the dropdown values
#   unset_label    choice only: a friendlier label for the option that means
#                  "leave this alone", so a sentinel like "keep" does not
#                  read as a real choice. The stored value is unchanged.
#   min / max      int and float only: spin-box bounds
#   multi          columns: a comma list (the default) or a single column.
#                  page_ref: one page (the default) or ticks over the pages,
#                  stored as a comma list — none ticked meaning every page.
#   ref_kind       node_ref: restrict the dropdown to nodes carrying that
#                  card kind; page_ref: to pages of that kind ("report")
#   visible_when   {"format": ["csv", "auto"]} — show this row only while
#                  another param holds one of those values; several keys are
#                  ANDed. Presentational only: run() still receives every
#                  param, visible or not.
#   insert_columns text only: offer a column-name picker for a box that is
#                  *about* columns but is not a plain list of them.
#                  "inline" inserts the name at the cursor; "mapping" treats
#                  the box as one `column = value` line per column and makes
#                  the picker a set of ticks.
#   wizard         text only: which builder sits beside the box — "table"
#                  for the conditional-formatting rules manager, "chart" for
#                  the chart-rules one. (rule_wizard=True is the older
#                  spelling of "table".)
#   hidden         never shown in the panel — for a value that something
#                  else writes, a card or a dialog
#   cosmetic       changing it does NOT mark the node dirty, so its cached
#                  output survives. For anything that cannot change what
#                  run() produces — how a list of charts is arranged, say.
#   section        put the row under a folding heading of that name. Rows
#                  with no section stay at the top; a node that declares
#                  none looks like a plain list, as it always did.
#   folded         on any row of a section, that section starts folded
#
# Every text box in the panel pops out to a full editor that lints and
# completes against the upstream columns.
PARAMS = [
    {"name": "source", "type": "string", "label": "Source column",
     "default": "", "placeholder": "blank = first numeric column"},
    {"name": "operation", "type": "choice", "label": "Operation",
     "options": ["multiply", "add"], "default": "multiply"},
    {"name": "factor", "type": "float", "label": "Factor", "default": 2.0},
    {"name": "new_column", "type": "string", "label": "New column",
     "default": "result"},

    # --- Everything below is a live reference, not part of the example. ---
    # Open the two sections in the properties panel to see each widget, then
    # delete the rows you do not want. run() ignores all of them.
    {"name": "ref_text", "type": "text", "label": "Text",
     "section": "Reference — types", "folded": True,
     "placeholder": "several lines", "insert_columns": "inline"},
    {"name": "ref_mapping", "type": "text", "label": "Mapping",
     "section": "Reference — types",
     "placeholder": "one 'column = value' line each",
     "insert_columns": "mapping"},
    {"name": "ref_int", "type": "int", "label": "Int", "default": 10,
     "min": 0, "max": 100, "section": "Reference — types"},
    {"name": "ref_bool", "type": "bool", "label": "Bool", "default": False,
     "section": "Reference — types"},
    {"name": "ref_keep", "type": "choice", "label": "Choice with a sentinel",
     "options": ["keep", "upper", "lower"], "default": "keep",
     "unset_label": "leave alone", "section": "Reference — types"},
    {"name": "ref_columns", "type": "columns", "label": "Columns",
     "default": "", "placeholder": "comma separated",
     "section": "Reference — types"},
    {"name": "ref_one_column", "type": "columns", "label": "One column",
     "default": "", "multi": False, "section": "Reference — types"},
    {"name": "ref_date", "type": "date", "label": "Date", "default": "",
     "section": "Reference — types"},
    {"name": "ref_color", "type": "color", "label": "Colour", "default": "",
     "placeholder": "Theme", "section": "Reference — types"},
    {"name": "ref_password", "type": "password", "label": "Password",
     "default": "", "placeholder": "or ${API_KEY} from .env",
     "section": "Reference — types"},
    {"name": "ref_file_open", "type": "file_open", "label": "File to read",
     "default": "", "section": "Reference — types"},
    {"name": "ref_file_save", "type": "file_save", "label": "File to write",
     "default": "", "section": "Reference — types"},
    {"name": "ref_folder", "type": "folder_open", "label": "Folder",
     "default": "", "section": "Reference — types"},
    {"name": "ref_node", "type": "node_ref", "label": "Another node",
     "default": "", "ref_kind": "table_viewer",
     "section": "Reference — types"},
    {"name": "ref_page", "type": "page_ref", "label": "A page",
     "default": "", "section": "Reference — types"},

    # What the extra keys do to a row.
    {"name": "ref_format", "type": "choice", "label": "Format",
     "options": ["auto", "csv", "excel"], "default": "auto",
     "section": "Reference — behaviour", "folded": True},
    {"name": "ref_delimiter", "type": "string", "label": "Delimiter",
     "default": ",", "visible_when": {"ref_format": ["csv"]},
     "section": "Reference — behaviour"},
    {"name": "ref_sheet", "type": "string", "label": "Sheet", "default": "",
     "visible_when": {"ref_format": ["excel"]},
     "section": "Reference — behaviour"},
    {"name": "ref_cosmetic", "type": "int", "label": "Cosmetic (no re-run)",
     "default": 1, "min": 1, "max": 6, "cosmetic": True,
     "section": "Reference — behaviour"},
    # Not shown in the panel at all — a value some card or dialog writes.
    {"name": "ref_hidden", "type": "string", "default": "", "hidden": True},
]


# ------------------------------------------------------------------ run ---
# run() is called with each input port as a keyword argument (unconnected
# optional inputs arrive as None) and returns a dict keyed by output port
# name — a bare value is accepted when there is exactly one output. Collect
# an open-ended set of inputs with run(ctx, **inputs).
#
# Treat inputs as read-only — outputs are cached and shared by reference. A
# pandas input arrives as a copy-on-write shallow copy and a list, dict, set
# or bytearray is rebuilt one level deep, so writing to those is safe and
# free; a numpy input arrives read-only, so copy it first, and reaching
# through an input to change what is inside it still reaches upstream.
# Create figures with matplotlib.figure.Figure(), never pyplot.
#
# Branches that do not depend on each other run at the same time, so this
# run() may be executing beside another node's. Keep to what arrives in the
# arguments and goes back in the return and there is nothing to think about;
# when that is not possible — a module-level variable, a file it writes, a
# library that is not thread-safe — declare NODE["exclusive"] = True.
# print() is already safe whoever else is printing: output is routed back to
# the node that wrote it, and a traceback maps to the line in *this* script.
#
# Import inside run(), not at the top of the file. This script is *executed*
# to read NODE and PARAMS, so a top-level import runs every time the node is
# loaded — and on a machine without that package the node loads as a broken
# placeholder instead of working. Down here it costs nothing until the node
# runs, and a missing package fails just this node with a message saying
# what to install.
#
# ctx is the run context:
#   ctx.params            current param values (dict)
#   ctx.vars              the flow's ${name} variables, read-only, for a
#                         script that wants one directly rather than through
#                         a ${name} written into one of its params
#   ctx.log(msg)          write to the log console
#   ctx.progress(0.5)     0..1 through this node's own work; fills the ring
#                         in its status LED and shows in the status bar. Call
#                         it as often as you like — it is throttled for you.
#                         A node that never calls it just pulses instead.
#   ctx.check_cancelled() raise if the user hit cancel — call it in long
#                         loops, next to ctx.progress()
#   ctx.node_id           this node instance's id
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
