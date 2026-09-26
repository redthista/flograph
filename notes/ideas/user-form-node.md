# User Form node — shelved feature plan

**Status:** shelved (not started). **Planned against:** v0.1.8, commit `f87490c`
(2026-08-05, "File > Create Desktop Shortcut, pointed at the way you actually
launch"). Anything in the codebase may have moved since.

Scope decided with the author:

- Native **User Form node** (`card: "form"`), **dict-only output** (latest
  entry only — no accumulation history).
- **8 field types** in v1: `text, textarea, password, int, float, date,
  toggle, choice`.
- **Required** fields (marked with a `*`) — Submit blocks with red hints on
  empty required fields.
- Schema authored **one line per field** in the Properties panel, and
  programmatically via an optional `fields` input port (string / list of
  dicts / DataFrame).
- **Form from Table** helper node (DataFrame → schema, one field per column).
- In-form **Load trigger**: scoped run of a named flow line that retrieves
  data and repopulates the form, leaving the rest of the model intact.
- Webview JS↔Python bridge form is **deferred** — the codebase has no
  JS→Python channel and the webview re-renders on every run, so it fights
  persistent form state and is a large separate chunk of work.

## How it fits the existing architecture

The closest existing thing is the control card system (`card: "control"` +
`NODE["control"]`): one host in `ui/controls.py` builds the widget, and it
works identically as a canvas card (`ui/canvas/node_item.py`) and a dashboard
tile (`ui/dashboard/tile_item.py`). Controls commit by writing a param through
the undo stack and emitting `scene.control_changed`, which dirties the node
and re-runs everything downstream. Dashboard tiles are fullscreen-able (`⛶`),
saved with the project.

A form differs from a control in one way: it must only emit on **Submit**, not
on every change. So the widget keeps field edits local (dirty-guard so a
`sync()` — which fires on build/undo/panel-edit/post-run — doesn't clobber
what's being typed) and only on Submit serializes everything into the single
`value` param via the undo stack, which re-runs the node; `run()` outputs the
dict.

Rule this must honour: anything a control's widget and its `run()` must agree
on lives in `core/controls.py` and is never duplicated. A form's field schema
follows the same pattern — all schema logic goes in a new Qt-free
`core/form.py` (core is Qt-free, enforced by `test_no_qt_in_core.py`).

## File-by-file change list

### 1. `src/flograph/core/form.py` (new — Qt-free, pandas-free)
Single source of truth for the schema so widget and `run()` can't disagree.

- `parse_form_schema(raw) -> list[Field]` — one line per field:
  `name|type[required]|label|default[|options]`.
  - `type` ∈ `text, textarea, password, int, float, date, toggle, choice`.
  - Trailing `*` on the type marks the field **required**.
  - `choice` reads the trailing `|options` segment (comma-separated).
- `schema_from_upstream(value, fallback) -> list[Field]` — normalizes a wired
  config into `list[Field]` whether it's the pipe-string, a list/dict of
  dicts, or a DataFrame of field definitions.
- `schema_to_text(fields) -> str` — canonical pipe-string (Form from Table's
  output, pasteable into the panel).
- `coerce(field, raw)` — int/float/toggle/date/text typing, used identically
  by Submit and `run()`.
- `default_entry(fields) -> dict` — defaults for Reset.

### 2. `src/flograph/core/script.py`
Add `"form"` to `CARD_KINDS` so `NODE["card"] = "form"` parses.

### 3. `src/flograph/ui/controls.py` — `FormControl(ControlWidget)`
- Scrollable `QFormLayout`, one editor row per field:
  - `QLineEdit` (text), `QPlainTextEdit` (textarea),
    `QLineEdit(Password)` (password), `QSpinBox`/`QDoubleSpinBox`
    (int/float), `QDateEdit` (date), `_TickBox` (toggle), `QComboBox`
    (choice).
  - Bottom row: **Load / Submit / Reset** buttons.
- **Schema-hash rebuild** — rebuild rows only when the resolved field list
  changes (a normal sync never tears down an in-progress form).
- **Dirty-guard** — `_apply` repopulates the editors from the stored `value`
  param only when not dirty.
- **Submit** — `coerce` all fields; required-empty fields mark their label
  red + hint and block; else `value_committed.emit(entry_dict)`.
- **Reset** — clear to `default_entry`, mark dirty, no run.
- **Load** — hidden unless a `load_targets` param is set; emits
  `load_requested`.
- `build_form()` factory + a form default size; stylesheet additions in
  `_stylesheet()`.

### 4. Hosts (reuse the existing commit/re-run path)
- `src/flograph/ui/canvas/node_item.py` & `src/flograph/ui/dashboard/tile_item.py`
  — dispatch on card `"form"`: build/sync via `build_form()`, hook
  `value_committed` into the existing `_on_control_committed` /
  `_commit_control_value` handlers, route `load_requested` through the
  existing button-fired scene signal mainwindow already handles.
- `src/flograph/ui/dashboard/tile_item.py` — `"form"` into `TILE_ABLE_KINDS`
  + `default_tile_size`. Fullscreen/⛶ already generic for any non-button tile.
- `src/flograph/ui/dashboard/visuals_list.py` — a `"form"` glyph so it's
  draggable onto a page.
- `src/flograph/ui/mainwindow.py` — a `_on_form_load(node_id)` handler
  (alongside `_on_button_fired`) that resolves the form's `load_targets`
  (node labels or a frame title) → optionally clears that loader's cache
  (reusing Action Button's clear-cache path) → `engine.run_targets(resolved +
  [form_id])`. Scoped run, model otherwise untouched — `build_plan` runs only
  dirty nodes in targets ∪ ancestors; the run-done wiring then refreshes the
  form's fields from the fresh cache via `set_upstream`.

### 5. Node scripts (`src/flograph/nodes/input/`, category `"Input"`)
- **`user_form.py`** — `card: "form"`, input `("fields", "any", optional)`,
  output `("entry", "object")`. `PARAMS`: `fields` (`text`), `caption`,
  `submit_label`, `reset_label`, `load_targets` (`text`, blank hides Load),
  `load_clear_cache` (bool), `width`, `height`. `run()`: resolve schema from
  wired `fields` else the typed param, coerce the stored `value` JSON →
  `{"entry": {...}}` (empty dict before the first submit).
- **`form_from_table.py`** — plain transform; input `("table", "dataframe")`
  (+ `all_text` toggle), output `("fields", "string")`; one field per column
  with dtype→type mapping (int/float/bool/datetime/object), so pointing a form
  at a table is a single wire.

### 6. Tests
- `tests/test_form_schema.py` — parse (all types, required, options, malformed
  lines), `schema_from_upstream` (string/list/DataFrame), `coerce` per type,
  invalid-JSON value.
- User Form `run` happy/required/empty paths + Form from Table dtype mapping
  (in the `test_stdlib_nodes.py` style).
- Extend `tests/test_input_controls.py` — widget builds, wired-`fields`
  rebuild, dirty-guard survives sync, Submit emits dict, required blocks,
  Reset clears, Load emits and triggers a scoped `run_targets`.
- Guards stay green: `test_no_qt_in_core.py` (form logic Qt-free),
  `test_registry.py` (new scripts parse).

### 7. Docs
- `README.md` node catalog — Input section: User Form, Form from Table.
- `ideas.md` — mark the "user forms" line as done.

## Out of scope (decided)
- No accumulation history (latest entry only); a follow-up node can turn entry
  dicts into rows.
- No webview JS↔Python bridge form in v1 (largest chunk; only worth it for
  arbitrary custom HTML/JS UIs).
- No SQL/retrieval nodes for the form's output beyond the Load trigger.
