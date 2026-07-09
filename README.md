# flopy

A visual node-based Python programming environment: KNIME-style dataflow on
an infinite Blueprint-style canvas, where every node is real, editable Python.

![status](https://img.shields.io/badge/status-v0.1-blue)

## Run it

```bash
.venv/bin/python main.py                 # or: .venv/bin/flopy
.venv/bin/python main.py project.flopy   # open a project
.venv/bin/python -m flopy.engine.headless project.flopy   # run without GUI
```

## The idea

- **Nodes are Python scripts.** Every node — including the shipped library —
  is a small module: a `NODE` dict declaring typed ports, an optional
  `PARAMS` list that auto-generates its properties form, and a
  `run(ctx, **inputs)` function. Double-click any node to read or fork its
  code in the built-in editor (syntax highlighting, jedi completion,
  error markers on the failing line).
- **KNIME semantics.** Data flows through typed ports; execution is a
  topological walk of the dirty subgraph; every node's outputs are cached, so
  re-runs only recompute what changed. Status LEDs: gray idle, yellow queued,
  pulsing blue running, green done, red error.
- **Inspect everything.** Click any node or wire to see the data on it —
  paged table view for DataFrames (millions of rows are fine), matplotlib
  figures with a toolbar, pretty-printed objects. Per-node stdout/logs in the
  console dock.

## Canvas

| Action | Binding |
| --- | --- |
| Add node | `Tab` (search palette), right-click, or drag from the library |
| Connect | drag from a port; drop on empty canvas to pick a compatible node |
| Reroute dot | double-click a wire |
| Comment frame | `Ctrl+G` around the selection (frames move their contents) |
| Run all / selected / cancel | `F5` / `F6` / `Esc` |
| Pan / zoom | middle-drag or `Space`+drag / wheel |
| Frame view | `F` |
| Duplicate / delete | `Ctrl+D` / `Del` |
| Undo anything | `Ctrl+Z` — every graph mutation is on the undo stack |

Projects are plain JSON (`.flopy`); caches are never saved, so a reopened
project is fully reproducible with one `F5`.

## Writing a node

```python
"""My Node

Docstring first paragraph shows in the properties panel.
"""
NODE = {
    "label": "My Node",
    "category": "Transform",
    "inputs":  [("table", "dataframe")],
    "outputs": [("result", "dataframe")],
}
PARAMS = [
    {"name": "factor", "type": "float", "default": 1.0},
]

def run(ctx, table):
    ctx.log(f"scaling by {ctx.params['factor']}")
    ctx.check_cancelled()          # cooperative cancellation
    return {"result": table * ctx.params["factor"]}
```

Port types: `any, dataframe, series, number, string, bool, object, figure`.
Rules: treat inputs as read-only (outputs are cached by reference); heavy
imports go inside `run()`; matplotlib figures must use the OO API
(`matplotlib.figure.Figure()`), never pyplot.

Drop new `.py` files under `src/flopy/nodes/<category>/` and they appear in
the library on next launch.

## Development

```bash
uv pip install -p .venv/bin/python -e ".[dev]"
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/
```

Architecture (src layout):

- `flopy/core` — Qt-free model: graph, typed ports, script contract,
  registry, JSON serialization. Fully unit-testable; a poison test keeps Qt
  and pandas out of its import graph.
- `flopy/engine` — background execution: plan builder, single-thread pool
  worker, output cache, cancellation, per-node stdout capture, tracebacks
  mapped to node script lines.
- `flopy/nodes` — the standard library; each node is a script file loaded as
  text through the same contract as user code.
- `flopy/ui` — canvas (QGraphicsView from scratch), code editor, inspector,
  properties, console. One rule everywhere: **QUndoCommands are the only
  writers to the graph**; items react to graph events.
