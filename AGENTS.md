# flograph — agent instructions

## Name schism (critical)

The folder is `flopy/` (legacy), the package is **`flograph`**. All imports, the CLI, and the pip package use `flograph`. `src/flopy/` is stale pre-rename code — never import from it. Always use `from flograph import ...`.

## Dev commands

```bash
# Install editable + dev deps
uv pip install -p .venv/bin/python -e ".[dev]"

# All tests (offscreen required — no display)
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q

# Single test file
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_stdlib_nodes.py -q

# Run app (needs display)
python main.py
flograph
```

## Test quirks

- **`QT_QPA_PLATFORM=offscreen` is mandatory for headless test runs.** No display server needed.
- `conftest.py` has an **autouse fixture** that force-collects Qt deferred deletions after every test. Without it, dangling timers from previous tests segfault later tests. This is not a bad test — it's the fixture doing its job.
- `test_no_qt_in_core.py` is a **poison test**: it runs `import flograph.core` in a subprocess and asserts PySide6 and pandas are NOT pulled in. If you add a top-level import to `core/`, this test breaks.
- `test_registry.py` parses every built-in node script. If a new node has a malformed `NODE` dict or `run()` signature, this test catches it.
- **Known flaky crash** (~25%, teardown-only): jedi completion threads from the editor dock survive into GC and cause `double free or corruption` / `QBasicTimer::stop` abort. Tests themselves pass. See `issues.md` for details.

## Architecture invariants

- **`flograph/core/` is Qt-free.** No PySide6, no pandas, no matplotlib at top level. Enforced by poison test.
- **QUndoCommands are the sole writers to the graph.** UI items react to graph events; never mutate the graph directly from a click handler.
- **Nodes are text scripts, never imported.** They live under `src/flograph/nodes/<category>/` and are parsed by `flograph.core.script.parse_spec()`.
- **Nodes treat inputs as read-only** — outputs are cached by reference. `scheduler._read_only_view` enforces what it can enforce for free: pandas inputs become copy-on-write shallow copies, list/dict/set/bytearray are rebuilt one level deep (items are not copied — pandas items inside are guarded, everything else is not), numpy arrays become read-only views that raise on write (`errors.readonly_input_hint` explains the error). Writing *through* an input, and any other type, are the contract's job.
- **Heavy imports go inside `run()`, not top-level** — top-level code executes at registry load for every node.
- **matplotlib: OO API only** (`matplotlib.figure.Figure()`), never `pyplot`. Not thread-safe from the worker.

## Node contract

Every node script must define:
- `NODE` dict: `label`, `category`, `inputs` (list of `(name, port_type[, opts])`), `outputs`
- Optional `PARAMS` list of dicts with `name`, `type`, `default`, etc.
- `def run(ctx, **inputs) -> dict`: returns dict keyed by output port names

Port types: `any, dataframe, series, number, string, bool, object, figure`.

Optional `NODE["card"]` gives a node a rich canvas card / dashboard tile
(`figure`, `webview`, `table_viewer`, `kpi`, `grid`, `slicer`, `button`,
`note`, `control`, ...). `card: "control"` additionally requires
`NODE["control"]` naming the widget shape (`slider`, `number`, `text`,
`date`, `toggle`, `choice`) — one host in `ui/controls.py` renders all of
them from that plus `PARAMS`, so a new control node is usually just a
script (see `nodes/scripting/control_template.py`). A control's settings
may also come from its own optional input ports, resolved by
`engine.introspect.control_upstream()`. Anything a control's widget and its
`run()` must agree on — option lists, bounds, clamping — lives in
`core/controls.py` and is never duplicated: if they disagree, the card
shows one number and the flow carries another.
Relevant skills: `.opencode/skills/new-node/` and `.opencode/skills/flograph/`.

**Pages come in kinds.** `Page.kind` is `"dashboard"` (tiles on a canvas)
or `"report"` (markdown in `Page.body`). One dataclass, because title,
colour, order, duplication and undo are identical; the window switches on
`kind` to build `DashboardPage` or `ReportPage`. Anything sweeping every
page for a *canvas* setting must go through `MainWindow._canvas_pages()` —
report pages have no scene or view. Report embeds (`![[Label]]`) are parsed
in `core/report.py` (Qt-free) and resolved in `ui/report/render.py`; images
are carried through Qt's markdown reader as tokens because it drops image
syntax outright. The preview and the PDF share one QTextDocument, on
purpose.

A report **page** resolves embeds by node label (`by_label`) because a page
is a view outside the flow. A report **card** (`card: "report"`) resolves
them against its own wired inputs (`by_wired_input`) because a node is
*inside* the flow — reaching across the graph would be a dependency the
scheduler can't see, so it would neither re-run nor order correctly.

**A list output renders as a stack.** Wherever one figure renders, a list of
them renders stacked — `FigureView.set_figure`, `plotly_view.to_html`, and
the report resolver each handle it. That is the whole "one chart per value
of a column" mechanism: the loop belongs in the node's own script (see
`nodes/viz/chart_per_value.py`), never in a faceting UI.

**Node scripts are executed to be read.** `parse_spec` runs the whole
script to get at `NODE`/`PARAMS`, so a *top-level* import happens at load
time — building the library, opening a project, applying code. Imports
belong inside `run()`. When a top-level one isn't installed,
`MissingDependencyError` (a `NodeScriptError`) is raised and the node loads
as a broken placeholder that keeps its code and params; installing the
package and re-applying the unchanged code repairs it. Never let a script
failure abort a whole project load — `graph_from_dict` falls back to
`_broken_spec`.

**Stacking order.** Nodes, frames and tiles carry a `z` — their index in a
back-to-front order of their *own kind*, normalized to 0..n-1 on every
change. The reordering rule is one pure function, `core/layers.restack()`;
Qt z-values are derived from it through the bands in
`ui/canvas/stacking.py` (frames below wires below nodes) and are never
stored. `z=None` means "not placed yet" — `Graph.add_node`/`add_frame`/
`add_tile` put it on top, which is also how files written before layering
keep their old insertion-order stacking.

## Project structure

```
src/flograph/
├── core/       # Qt-free data model (graph, ports, registry, serialization)
├── engine/     # Background execution, caching, headless runner
├── nodes/      # Stdlib node scripts (io/, input/, transform/, viz/, util/, scripting/)
├── ui/         # QGraphicsView canvas, editor, inspector, console, dashboard
├── templates/  # Built-in .flograph project files
├── app.py      # QApplication bootstrap + main window
├── packages.py # Runtime pip/uv package management dialog
└── paths.py    # Path resolution
tests/         # pytest + pytest-qt (no display needed)
```

## Key documentation files

- `README.md` — full project docs, canvas bindings, node library catalog
- `issues.md` — tracked bugs
- `ideas.md` — feature ideas
- `.opencode/skills/flograph/SKILL.md` — comprehensive workspace reference
- `.opencode/skills/new-node/SKILL.md` — node scaffolding guide