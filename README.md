# flograph

A visual node-based Python programming environment: KNIME-style dataflow on
an infinite Blueprint-style canvas, where every node is real, editable Python.

![status](https://img.shields.io/badge/status-v0.1-blue)

## Install

flograph is a standard pip-installable package (hatchling build backend):

```bash
pip install .            # or: uv pip install .   /   pip install -e .
```

This puts a `flograph` command on your PATH and makes `python -m flograph`
work. To build a distributable wheel/sdist instead:

```bash
python -m build          # or: uv build   ->   dist/flograph-*.whl
```

> The project was renamed from **flopy** to **flograph** because `flopy` is
> already taken on PyPI (USGS MODFLOW). To migrate projects saved by the old
> build, see [Migrating old `.flopy` projects](#migrating-old-flopy-projects).

## Run it

```bash
flograph                 # console entry point (after install)
python -m flograph                          # equivalent module entry point
python main.py project.flograph             # open a project
python -m flograph.engine.headless project.flograph   # run without GUI
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

Projects are plain JSON (`.flograph`); caches are never saved, so a reopened
project is fully reproducible with one `F5`.

### Migrating old `.flopy` projects

Projects saved by the old **flopy** build use a `.flopy` extension and embed
`flopy.*` node type-ids, which this build no longer recognises. Convert them
in place with the bundled one-shot migrator (stdlib-only, no install needed):

```bash
python scripts/flopy_to_flograph.py project.flopy          # -> project.flograph
python scripts/flopy_to_flograph.py my/projects --recursive
```

It rewrites builtin `flopy.*` type-ids to `flograph.*` (leaving `user.*`
nodes alone), renames the file and any `.flopy.cache/` side-car, and by
default keeps the original (`--delete-original` to remove it).

## Node library

The shipped library covers the KNIME basics:

- **IO** — read/write CSV, Excel, Parquet, JSON (incl. JSONL), SQLite
  (query in, table out), inline Table.
- **Transform** — Select Columns, Filter Rows, Sort, Join, Group By,
  Expression, Concatenate, Missing Values, Duplicate Row Filter,
  Rename Columns, Pivot, Unpivot, Row Sampling, Convert Types,
  String Manipulation, Statistics.
- **Viz** — Show Table, Show Plot (live on-canvas cards), Show Plotly
  (fully interactive plotly.js chart embedded on the canvas — hover, zoom
  and pan in place; needs `pip install plotly`, e.g. via
  Tools > Manage Packages).
- **Scripting / Util** — Python Script, Constant, Reroute, Note,
  Action Button.

## Packages

**Tools > Manage Packages** installs, upgrades and uninstalls pip packages
in flograph's own environment (the venv running the app). Nodes execute
in-process, so anything installed there is immediately importable from a
node's `run()` — no restart needed for new installs; upgrades of modules
the app has already imported take effect on the next launch. The dialog
uses `pip` when the interpreter has it and falls back to `uv pip` (uv-made
venvs ship without pip); flograph's own core dependencies are protected from
uninstall.

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
`columns`-typed params render with a ▾ picker listing the columns of the
DataFrames cached on the node's inputs (run upstream once to populate it);
add `"multi": False` for single-column params so picking replaces instead
of toggling a comma list.
Rules: treat inputs as read-only (outputs are cached by reference); heavy
imports go inside `run()`; matplotlib figures must use the OO API
(`matplotlib.figure.Figure()`), never pyplot.

Drop new `.py` files under `src/flograph/nodes/<category>/` and they appear in
the library on next launch.

## Development

```bash
uv pip install -p .venv/bin/python -e ".[dev]"
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/
```

Architecture (src layout):

- `flograph/core` — Qt-free model: graph, typed ports, script contract,
  registry, JSON serialization. Fully unit-testable; a poison test keeps Qt
  and pandas out of its import graph.
- `flograph/engine` — background execution: plan builder, single-thread pool
  worker, output cache, cancellation, per-node stdout capture, tracebacks
  mapped to node script lines.
- `flograph/nodes` — the standard library; each node is a script file loaded as
  text through the same contract as user code.
- `flograph/ui` — canvas (QGraphicsView from scratch), code editor, inspector,
  properties, console. One rule everywhere: **QUndoCommands are the only
  writers to the graph**; items react to graph events.
