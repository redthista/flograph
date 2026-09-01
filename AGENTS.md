# flograph — agent instructions

## Name schism (critical)

The folder is `flopy/` (legacy), the package is **`flograph`**. All imports, the CLI, and the pip package use `flograph`. `src/flopy/` is stale pre-rename code — never import from it. Always use `from flograph import ...`.

## Git identity (before first public push)

The current git identity is the author's personal address (`dconrancpw@gmail.com`)
and it is baked into the existing history. Before the repo goes public, switch to
the project-appropriate identity and scrub history if anything personal has
already been listed; an author email in git history is public forever.

- License holder: **redthista** (matches LICENSE, the GitHub org, and git name).
- Public email is **flograph@pm.me** — set `git config user.email "flograph@pm.me"`
  **before** any future commits.
- Verify with `git log --format='%an <%ae>'` before pushing that no commit
  carries the personal address.
- Ask before rewriting history (rebase/filter-branch/filter-repo); it changes
  commit hashes and invalidates existing clones.

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
- **Nodes can run at the same time.** The engine starts every node whose
  upstream nodes have finished, up to a worker limit (Settings > General >
  Nodes to run at once; `engine.scheduler.default_workers` when it is Auto).
  A node body therefore shares the process with other node bodies: module-level
  state, a shared file, a library that is not thread-safe, and `os.chdir` are
  all now races rather than merely poor style. A node that cannot tolerate
  company declares `NODE["exclusive"] = True` and the engine drains the
  in-flight set and gives it the process to itself; a user can force either
  answer per instance from the node's context menu. `print()` is safe — see
  `worker._StreamRouter`, which routes stdout by thread so output cannot land
  under the wrong node.
- **Nodes treat inputs as read-only** — outputs are cached by reference. With
  concurrent execution this is no longer only about ordering: two nodes fed by
  one upstream node hold the same object at the same time, so writing through
  an input is a data race, not just a value that changes at the wrong moment. `scheduler._read_only_view` enforces what it can enforce for free: pandas inputs become copy-on-write shallow copies, list/dict/set/bytearray are rebuilt one level deep (items are not copied — pandas items inside are guarded, everything else is not), numpy arrays become read-only views that raise on write (`errors.readonly_input_hint` explains the error). Writing *through* an input, and any other type, are the contract's job.
- **Heavy imports go inside `run()`, not top-level** — top-level code executes at registry load for every node.
- **matplotlib: OO API only** (`matplotlib.figure.Figure()`), never `pyplot`. Not thread-safe from the worker, so a node that draws with it declares `NODE["exclusive"] = True` — `viz/show_plot.py` and `viz/chart_per_value.py` do.

## Node contract

Every node script must define:
- `NODE` dict: `label`, `category`, `version`, `inputs` (list of `(name, port_type[, opts])`), `outputs`, optional `exclusive` (run with nothing else in flight)
- `version` is the node type's own edition, shown in the properties panel and the library tooltip. **Bump it whenever you change a node's params or behaviour.** It is the only way a user can tell the node in front of them from the one it replaced: the package version cannot, since two checkouts of one release carry the same number, and a node file copied into a user-nodes folder carries no package version at all. New nodes start at `"1.0"`; a test fails if a builtin has none.
- Optional `PARAMS` list of dicts with `name`, `type`, `default`, etc.
- `def run(ctx, **inputs) -> dict`: returns dict keyed by output port names

`ctx` is the whole node-facing API and is deliberately small: `ctx.params`,
`ctx.log(msg)`, `ctx.check_cancelled()`, `ctx.progress(0..1)`, `ctx.node_id`.
It carries no handle on the graph, the cache or Qt. Since iteration lives in
a node's own `run()`, a loop should call `check_cancelled()` and `progress()`
each pass — the first keeps Stop working, the second fills the ring in the
node's status LED. `progress()` is throttled inside `RunContext`, so call it
as often as is convenient.

Port types: `any, dataframe, series, number, string, bool, object, figure`.

**Every node also has a flow port**, implicitly and whatever its script says
(`core.ports.FLOW_INPUT` / `FLOW_OUTPUT`, reserved name `flow`, type
`PortType.FLOW`). A wire between two of them is an **order edge**: it hands
over no value and exists only to say "that node first". A script may declare
neither the name nor the type. It is an ordinary `Connection` on a reserved
port — so ordering, dirtying, cycle rejection, cache invalidation, undo and
persistence are all the ones wires already had — but it is deliberately kept
out of `NodeSpec.inputs`/`outputs` and out of the graph's by-input index,
because nothing about it feeds a port. `Graph.order_sources(node_id)` is how
to ask for a node's prerequisites, exactly as `var_sources` is for `${name}`.
On the canvas the pins live off a node's two upper corners
(`NodeItem.flow_ports`, keyed by direction) and the wire draws as a dashed
upward arc (`connection_item.order_path`). They are **hidden by default** —
`node_item.flow_pins_on` decides, on the same tri-state as `port_labels_on`
(per-node `NodeInstance.flow_pins`, then `scene.flow_pins_enabled`), plus
the held reveal key and `scene.drawing_order_edge`; a pin with an edge on it
is drawn regardless. Right-clicking an order edge opens a menu whose point
is `ui/canvas/order_help.py` — keep that text true if the behaviour moves,
since it is the only explanation a user can reach from the canvas.

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
- `src/flograph/docs/*.md` — the in-app handbook (Help ▸ Documentation / F1);
  GitHub-wiki-compatible Markdown, edited in the same commit as the feature
- `issues.md` — tracked bugs
- `ideas.md` — feature ideas
- `.opencode/skills/flograph/SKILL.md` — comprehensive workspace reference
- `.opencode/skills/new-node/SKILL.md` — node scaffolding guide