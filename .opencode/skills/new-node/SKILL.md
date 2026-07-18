---
name: new-node
description: Create a new flograph node (stdlib library node) — scaffolds the node script under src/flograph/nodes/, follows the NODE/PARAMS/run contract, and adds a headless test. Use ONLY when asked to add a node, create a node type, or extend the node library.
---

# Creating a new flograph node

A node is a Python **script file** (loaded as text, never imported) under
`src/flograph/nodes/<category_pkg>/<name>.py`. Its `type_id` becomes
`flograph.<category_pkg>.<name>` and it appears in the library/palette
automatically on next launch — no registration step.

## Steps

1. **Pick the category package.** Existing ones: `io/`, `transform/`,
   `scripting/`, `viz/`, `util/`. A new category needs a new package dir with
   an `__init__.py`; the `NODE["category"]` string (display name) is
   independent of the package name but keep them aligned.

2. **Write the script from this template:**

```python
"""<Label>

One-paragraph description — the first paragraph shows in the Properties
panel, the whole docstring in library tooltips.
"""
NODE = {
    "label": "<Label>",                    # shown on the canvas
    "category": "<Category>",              # library tree group
    "inputs":  [("table", "dataframe")],   # (name, type[, {"optional": True}])
    "outputs": [("result", "dataframe")],
}
PARAMS = [   # optional; each dict becomes a widget in the Properties panel
    {"name": "factor", "type": "float", "label": "Factor", "default": 1.0},
]

def run(ctx, table):        # inputs arrive as kwargs named after input ports
    ctx.log(f"factor={ctx.params['factor']}")
    return {"result": table * ctx.params["factor"]}
```

3. **Add a headless test** in `tests/test_stdlib_nodes.py`, using the
   existing `run_node(registry, type_id, params, **inputs)` helper. Cover the
   happy path AND at least one error path (bad param, missing column, …).

4. **Verify:**
   ```bash
   QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_stdlib_nodes.py tests/test_registry.py -q
   ```
   `test_registry.py` will catch contract violations at load time (all
   builtins are parsed by the discovery test). For a visual check, launch the
   app and find the node via Tab-palette search.

## Contract rules (violations = load error or runtime failure)

- Port types: `any, dataframe, series, number, string, bool, object, figure`.
  Port names must be valid identifiers, unique per direction.
- `run(ctx, **inputs)` returns a dict keyed by output port names; a bare
  value is allowed iff there is exactly one output. Every declared output is
  type-checked against its port type after the run.
- Required (non-optional) inputs block execution when unconnected; optional
  inputs arrive as `None`.
- Param types → widgets: `string`, `text` (multiline), `int`, `float`,
  `bool`, `choice` (needs `options`), `file_open`, `file_save`, `columns`.
  `min`/`max` supported for int/float; `placeholder` for string-likes.
- **Order `PARAMS` for a clean Properties panel.** Each entry renders as one
  form row, top to bottom, in list order. `text` renders as a fixed ~90px
  multiline box — reserve it for content that's genuinely multi-line (code,
  markdown, one-mapping-per-line lists); a short single value (a name, a
  small list literal) should be `string` instead, or its row looks like an
  oversized empty gap. Keep any `text` params grouped together rather than
  interleaved between single-line params, so the panel doesn't alternate
  tall/short rows — put single-line params first, multiline block(s) next,
  and `width`/`height` (if present) last. See `util/note.py` (text, then
  width/height) for the pattern.
- **Treat inputs as read-only** — outputs are cached and shared by
  reference. Use `df.copy(deep=False)` before mutating shape, or operations
  that return new frames.
- Heavy imports (`pandas`, network libs) go **inside `run()`**, never at
  top level — top-level code executes at registry load for every node.
- Long loops should call `ctx.check_cancelled()` periodically so Cancel
  works; `ctx.log(msg)` writes to the Log console; `ctx.progress(0..1)` is
  reserved for future progress display.
- matplotlib: build figures with `matplotlib.figure.Figure()` (OO API) and
  return them through a `figure`-typed port. **Never import pyplot** — it is
  not thread-safe from the worker.
- Raise plain exceptions with actionable messages ("no file selected — set
  'CSV file' in the node's properties"); the message lands on the node's
  tooltip, the log console, and the editor's error marker.

Good reference implementations: `src/flograph/nodes/transform/filter_rows.py`
(two outputs, query param, logging), `src/flograph/nodes/viz/show_plot.py` (figure
output, validation), `src/flograph/nodes/io/read_csv.py` (file param, lazy
import).
