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
- **Nodes treat inputs as read-only** — outputs are cached by reference. Use `df.copy(deep=False)` before mutating shape.
- **Heavy imports go inside `run()`, not top-level** — top-level code executes at registry load for every node.
- **matplotlib: OO API only** (`matplotlib.figure.Figure()`), never `pyplot`. Not thread-safe from the worker.

## Node contract

Every node script must define:
- `NODE` dict: `label`, `category`, `inputs` (list of `(name, port_type[, opts])`), `outputs`
- Optional `PARAMS` list of dicts with `name`, `type`, `default`, etc.
- `def run(ctx, **inputs) -> dict`: returns dict keyed by output port names

Port types: `any, dataframe, series, number, string, bool, object, figure`.
Relevant skills: `.opencode/skills/new-node/` and `.opencode/skills/flograph/`.

## Project structure

```
src/flograph/
├── core/       # Qt-free data model (graph, ports, registry, serialization)
├── engine/     # Background execution, caching, headless runner
├── nodes/      # Stdlib node scripts (io/, transform/, viz/, util/, scripting/)
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