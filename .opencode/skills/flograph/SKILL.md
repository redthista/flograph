---
name: flograph
description: Workspace navigation for the flograph project — a visual node-based Python dataflow programming environment (PySide6 + pandas + jedi). Use for all flograph development tasks: understanding architecture, finding files, running tests, adding features, or fixing bugs in this codebase.
---

# flograph — workspace reference

Visual node-based Python dataflow programming environment (MIT, v0.1.5). Nodes
are Python scripts loaded as text; execution is topological; the canvas is an
infinite QGraphicsView Blueprint-style editor.

## Project root

```
/home/dc/PycharmProjects/PythonProject/flopy/
```
The folder is named `flopy` (legacy) but the package is `flograph`.

## Key files

| File | Purpose |
|------|---------|
| `main.py` | Thin CLI launcher |
| `pyproject.toml` | Package metadata, deps, scripts, build config (hatchling) |
| `issues.md` | Tracked bugs/tasks |
| `ideas.md` | Feature ideas and brainstorming |
| `README.md` | Full project documentation |
| `uv.lock` | Lockfile |

## Architecture

```
src/flograph/
├── core/          # Qt-free data model
├── engine/        # Background execution & caching  
├── nodes/         # Standard library node scripts (text, not imported)
├── ui/            # QGraphicsView canvas, editor, inspector, console
├── templates/     # Built-in .flograph project templates
├── app.py         # Application bootstrap (QApplication, MainWindow)
├── ai.py          # AI integration helpers
├── packages.py    # Runtime pip package management dialog
└── paths.py       # Path resolution utilities
```

### core/ (12 files)
Qt-free model — the only writer restriction: **QUndoCommands are the sole
writers to the graph; everything else reacts to graph events.**

| File | Purpose |
|------|---------|
| `graph.py` | Directed graph of nodes and edges, serialization, mutation signals |
| `node.py` | Node model: type_id, label, params dict, position, status |
| `ports.py` | Typed input/output ports, type system (`dataframe`, `series`, `number`, `string`, `bool`, `object`, `figure`, `any`) |
| `registry.py` | Discovers and loads node scripts from `nodes/` sub-packages |
| `script.py` | Parses a node script text into its `NODE` dict, `PARAMS` list, and `run()` |
| `serialization.py` | JSON round-trip for graph state (`.flograph` files) |
| `spec.py` | Node type specification: plugin definitions, `SPEC` dict |
| `datatypes.py` | Custom data type validation/coercion |
| `params.py` | Parameter definitions: `type`, `default`, `options`, `min`/`max`, `columns` |
| `events.py` | Event bus / signal definitions |
| `user_nodes.py` | User-authored node scripts (saved separately from builtins) |
| `__init__.py` | Re-exports core symbols |

### engine/ (9 files)
Background execution runs on a single-thread pool (per-node isolation).

| File | Purpose |
|------|---------|
| `scheduler.py` | Topological walk of dirty subgraph, plan builder |
| `worker.py` | Executes one node's `run()` per invocation, captures stdout |
| `cache.py` | Output cache keyed by (node_id, output_port) |
| `cache_persistence.py` | Optional persistence; caches are NOT saved in .flograph files |
| `context.py` | `ctx` object: `log()`, `check_cancelled()`, `params`, `progress()` |
| `headless.py` | CLI runner for `python -m flograph.engine.headless` |
| `errors.py` | Error types: execution failure, type mismatch |
| `introspect.py` | Inspect node inputs/outputs without running |
| `__init__.py` | Re-exports |

### nodes/ (30 scripts across 5 categories)
Each `.py` file is a node script **loaded as text**, never imported. Script
contact: `NODE` dict, optional `PARAMS` list, `run(ctx, **inputs)` function.
See the `new-node` skill for the authoring template.

| Category | Files |
|----------|-------|
| `io/` | `read_csv`, `read_excel`, `read_json`, `read_parquet`, `read_sqlite`, `table`, `write_csv`, `write_excel`, `write_json`, `write_parquet`, `write_sqlite` |
| `transform/` | `concatenate`, `convert_types`, `duplicate_filter`, `expression`, `filter_rows`, `group_by`, `join`, `missing_values`, `pivot`, `rename_columns`, `row_sampling`, `select_columns`, `sort`, `statistics`, `string_manipulation`, `unpivot` |
| `viz/` | `card`, `show_plot`, `show_plotly`, `show_table`, `show_web`, `slicer`, `table_spec` |
| `util/` | `action_button`, `constant`, `note`, `reroute` |
| `scripting/` | `node_template`, `python_script` |

### ui/ (44 files across 6 sub-packages)

| Sub-package | Files | Purpose |
|-------------|-------|---------|
| `canvas/` | `view.py`, `scene.py`, `node_item.py`, `connection_item.py`, `frame_item.py`, `palette.py`, `grid.py`, `minimap.py`, `base_view.py` | Infinite Blueprint canvas, node/connection/frame graphics items, search palette (`Tab`), grid snap |
| `editor/` | `editor_dock.py`, `code_editor.py`, `completion.py`, `highlighter.py`, `ai_worker.py`, `save_user_node_dialog.py` | Node code editor with jedi autocomplete, syntax highlighting, AI assistant |
| `inspector/` | `inspector_dock.py`, `pandas_model.py`, `figure_view.py`, `object_view.py`, `plotly_view.py`, `spec_view.py`, `popup_view.py`, `view_for.py` | Data inspector: DataFrames (paged), matplotlib figures, plotly, pretty-print |
| `dashboard/` | `dashboard_page.py`, `dashboard_scene.py`, `dashboard_view.py`, `tile_item.py`, `page_bar.py`, `visuals_list.py` | Dashboard/report builder |
| `properties/` | `params_panel.py` | Node properties form (auto-generated from PARAMS) |
| `console/` | `log_dock.py` | Per-node stdout/log console |

### templates/ (9 files)
Built-in `.flograph` project templates shipped with the app.

---

## Running tests

```bash
# All tests (offscreen for headless CI)
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q

# Specific test files
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_stdlib_nodes.py tests/test_registry.py -q

# Run app (GUI, needs display)
python main.py
flograph
```

Tests use `pytest` + `pytest-qt`. The `tests/conftest.py` provides shared
fixtures (QApplication, graph, registry).

---

## Node contract (quick reference)

Every node script (e.g. `nodes/transform/my_node.py`) must define:

```python
"""Label — first paragraph shows in properties panel."""
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
    ctx.log(f"factor={ctx.params['factor']}")
    ctx.check_cancelled()
    return {"result": table * ctx.params["factor"]}
```

Port types: `any, dataframe, series, number, string, bool, object, figure`.
Param types: `string, text, int, float, bool, choice, file_open, file_save, columns`.

---

## Conventions

1. **QUndoCommands are the sole graph writers.** UI items react to graph
   events; never mutate the graph directly from a click handler.
2. **Nodes treat inputs as read-only** — outputs are cached by reference.
3. **Heavy imports go inside `run()`** — top-level code runs at registry load.
4. **matplotlib uses OO API only** (`Figure()`, never `pyplot`).
5. **Projects are plain JSON** (`.flograph`); caches are never saved.
6. **The old `src/flopy/` tree** is a leftover from the pre-rename era. All
   active development is in `src/flograph/`.

---

## Legacy note

The project was renamed from **flopy** to **flograph** because `flopy` was
taken on PyPI (USGS MODFLOW). The directory still says `flopy/` but the
package, entry point, and all imports use `flograph`. `src/flopy/` contains
stale pre-rename code — when working on this project, use `src/flograph/`.

## Issues & ideas

- `issues.md` — tracked bugs and known problems
- `ideas.md` — feature ideas and brainstorming
