# flograph Node Creation Guide

**Audience: an LLM writing a new flograph node.**
Follow this document literally. Every rule here is enforced by the code in
`src/flograph/core/script.py`, `src/flograph/core/params.py`,
`src/flograph/core/datatypes.py` and `src/flograph/engine/worker.py`.
Breaking a rule produces a load error, a runtime failure, or a data race.

---

## 0. Quick start — copy this, then edit it

Write one file at `src/flograph/nodes/<category_pkg>/<file_name>.py`:

```python
"""Multiply Column

Multiply one numeric column by a factor and write the result into a new
column. The source column is left untouched.
"""
NODE = {
    "label": "Multiply Column",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "column", "type": "columns", "label": "Column",
     "default": "", "multi": False},
    {"name": "factor", "type": "float", "label": "Factor", "default": 2.0},
    {"name": "new_column", "type": "string", "label": "New column",
     "default": "result", "placeholder": "blank = overwrite the source"},
]


def run(ctx, table):
    column = str(ctx.params.get("column", "")).strip()
    if not column:
        raise ValueError(
            "no column selected — set 'Column' in the node's properties")
    if column not in table.columns:
        available = ", ".join(str(c) for c in table.columns)
        raise ValueError(f"column {column!r} not in table (has: {available})")

    out = table.copy(deep=False)
    target = ctx.params.get("new_column", "").strip() or column
    out[target] = table[column] * float(ctx.params.get("factor", 1.0))
    ctx.log(f"wrote {target!r} = {column!r} * {ctx.params['factor']}")
    return {"table": out}
```

Then add a test (§11) and run the verification commands (§12).
There is **no registration step** — the file being on disk is the registration.

---

## 1. What a node is

A node is a **Python script file that is read as text and executed, never
imported as a module**. `parse_spec()` `exec()`s the whole file to read the
module-level names `NODE`, `PARAMS` and `run`.

Three consequences you must design around:

1. **Top-level code runs at load time** — when the library is built, when a
   project is opened, when a user applies edited code. So the file must only
   *declare*. Never do work, I/O or heavy imports at the top level.
2. **A top-level `import` of a missing package breaks the node at load time**,
   turning it into a broken placeholder. Imports belong inside `run()`.
3. **Every placed node carries its own copy of the source text.** A user can
   right-click ▸ Edit Code and rewrite one instance without touching others.

### File location and `type_id`

| Where the file lives | Resulting `type_id` |
|---|---|
| `src/flograph/nodes/transform/my_node.py` | `flograph.transform.my_node` |
| `src/flograph/nodes/io/read_thing.py` | `flograph.io.read_thing` |
| user nodes dir: `my_node.py` | `user.my_node` |
| user nodes dir: `group/my_node.py` | `user.group.my_node` |

Rules:

- Existing category packages: `input/`, `io/`, `scripting/`, `transform/`,
  `util/`, `viz/`. Put the file in the one that fits; only create a new
  package (with an `__init__.py`) if none does.
- File name: `lower_snake_case.py`. Files starting with `_` are skipped.
- `NODE["category"]` is the *display* name in the library tree. Keep it
  aligned with the package: `input/`→`"Input"`, `io/`→`"IO"`,
  `transform/`→`"Transform"`, `viz/`→`"Viz"`, `util/`→`"Util"`,
  `scripting/`→`"Scripting"`.
- **A malformed builtin raises immediately and breaks app startup.** There is
  no "skip the bad one" for shipped nodes. Get the contract right.

---

## 2. The module docstring — required in practice

```python
"""<Label>

<First paragraph: what the node does, in plain language. This is what the
Properties panel shows.>

<Further paragraphs: parameter semantics, edge cases, what happens when an
optional input is left unconnected. The whole docstring shows in the
library tooltip.>
"""
```

Rules:

- Line 1 = the node's label, exactly matching `NODE["label"]`.
- Blank line, then a first paragraph that stands alone as a summary.
- Write for a **non-programmer end user**, not for a developer. Say what the
  node does and what to type in each box; do not describe the implementation.
- Document every non-obvious param and every optional input's "what if I leave
  it unwired" behaviour.

---

## 3. `NODE` — the declaration dict

```python
NODE = {
    "label": "Filter Rows",        # required, non-empty str
    "category": "Transform",       # required, non-empty str
    "version": "1.0",              # required for builtins; str (or number)
    "inputs":  [("table", "dataframe")],
    "outputs": [("filtered", "dataframe"), ("rejected", "dataframe")],
    # optional:
    "exclusive": False,            # bool — run with nothing else in flight
    "card": None,                  # rich canvas card, see §8
    "control": None,               # only when card == "control", see §9
}
```

| Key | Type | Required | Notes |
|---|---|---|---|
| `label` | non-empty `str` | **yes** | shown on the canvas and in the palette |
| `category` | non-empty `str` | **yes** | library tree group |
| `version` | `str` (or `int`/`float`, stringified) | **yes for builtins** | new nodes start at `"1.0"` |
| `inputs` | list of tuples | no (default `[]`) | see §4 |
| `outputs` | list of tuples | no (default `[]`) | see §4 |
| `exclusive` | `bool` | no (default `False`) | see §6 |
| `card` | `str` from `CARD_KINDS` | no | see §8 |
| `control` | `str` from `CONTROL_KINDS` | no | **required** iff `card == "control"` |

Unknown keys are ignored — older flograph builds read newer node files without
complaint. Do not rely on that to smuggle in behaviour.

### `version` — bump it

`version` is the **node type's own edition**, not the app version. It is shown
in the Properties panel and the library tooltip, and it is the only way a user
can tell the node in front of them from the one it replaced (two checkouts of
one release share a package version; a node file copied into a user-nodes
folder carries none at all).

- New node → `"1.0"`.
- **Changed params or behaviour on an existing node → bump it** (`"1.1"`,
  `"2.0"`). A rewrite that changes the param surface is a major bump.
- `tests/test_node_versions.py` fails if any builtin has no version.

---

## 4. Ports

### Syntax

```python
"inputs": [
    ("table", "dataframe"),                                     # required
    ("extra", "dataframe", {"optional": True}),                 # may be unwired
    ("more",  "dataframe", {"optional": True, "spare": True}),  # grows
],
"outputs": [("result", "dataframe")],
```

Each entry is `(name, type)` or `(name, type, opts)`.

### Port name rules

- Must be a valid Python identifier (it becomes a `run()` keyword argument).
- Must be unique **within its direction** (an input and an output may share a
  name — `("table", …)` on both sides is idiomatic for a pass-through node).
- `"flow"` is **reserved** and rejected. Every node already has an implicit
  flow port in each direction; a wire between two of them is an *order edge*
  ("run that one first") and carries no value. A script may never declare one.

### Port types — the complete list

| Type | Accepts / must be | Wire colour |
|---|---|---|
| `any` | anything, including `None` | `#e8e8e8` |
| `dataframe` | `pandas.DataFrame` | `#2dd4bf` |
| `series` | `pandas.Series` | `#7dd3c8` |
| `number` | `int` or `float` (**not `bool`**) | `#4ade80` |
| `string` | `str` | `#fbbf24` |
| `bool` | `bool` | `#f87171` |
| `object` | anything, including `None` | `#9ca3af` |
| `figure` | `matplotlib.figure.Figure` | `#c084fc` |

There is no other type. `list`, `dict`, `path`, `html` etc. do **not** exist —
use `any` or `object`.

### Connection compatibility

A wire from an output of type `A` to an input of type `B` is allowed when:

- `A == B`, or
- either side is `any`, or
- `B` is `object` and `A` is one of `dataframe, series, number, string, bool,
  figure` (one-way widening into `object`).

Choosing a type:

- Use the **narrowest type that is always true**. Outputs are type-checked
  after every run; declaring `dataframe` and returning `None` is a node failure.
- If an output may legitimately be `None`, or its type varies with params,
  declare `any` (or `object`).
- Use `object` for an input that means "give me whatever you have" and `any`
  for a value you will inspect.

### Port options

| Option | Applies to | Meaning |
|---|---|---|
| `{"optional": True}` | inputs | node runs with the port unconnected; the argument arrives as `None`. **You must give the parameter a `=None` default in `run()`.** |
| `{"spare": True}` | inputs | the trailing "one more slot" of an open-ended stack (see `transform/concatenate.py`). Wiring a spare promotes it to a permanent port and a new spare appears. Implies `optional`. |

A **required** (non-optional) input blocks execution while unconnected — the
node simply does not run. Only make an input optional if `run()` genuinely
handles `None`.

Zero ports is legal: display-only nodes (`util/note.py`) take no part in
dataflow.

---

## 5. `PARAMS` — the properties panel

`PARAMS` is an optional list of dicts. Each dict becomes exactly one widget
row, rendered top-to-bottom **in list order**. Values are plain
JSON-serialisable scalars and arrive in `ctx.params`.

### Param types — the complete list

| `type` | Widget | Default when omitted |
|---|---|---|
| `string` | single-line text box | `""` |
| `text` | multiline box (~90px tall) | `""` |
| `int` | spin box | `0` |
| `float` | decimal spin box | `0.0` |
| `bool` | check box | `False` |
| `choice` | dropdown — **`options` is required** | `options[0]` |
| `file_open` | text box + browse (existing file) | `""` |
| `file_save` | text box + browse (save path) | `""` |
| `folder_open` | text box + browse (existing directory) | `""` |
| `columns` | column picker fed from the upstream table | `""` |
| `password` | masked text box with a reveal toggle | `""` |
| `node_ref` | dropdown of other nodes; stores a node id | `""` |
| `date` | calendar picker; stores ISO `"YYYY-MM-DD"` | `""` |

### Param keys — the complete list

| Key | Type | Applies to | Meaning |
|---|---|---|---|
| `name` | `str` identifier | all | **required**; the `ctx.params` key. Unique. |
| `type` | `str` from the table above | all | **required** |
| `label` | `str` | all | row label. Default: `name.replace("_"," ").capitalize()`. Write one explicitly. |
| `default` | scalar | all | starting value; type default if omitted |
| `options` | `list[str]` | `choice` | **required and non-empty** for `choice` |
| `placeholder` | `str` | string-likes | grey hint text. Use it to explain what blank means. |
| `min` / `max` | number | `int`, `float` | spin box bounds |
| `multi` | `bool` (default `True`) | `columns` | `False` = pick one column, `True` = comma-separated list |
| `hidden` | `bool` | all | not shown in the panel (edited elsewhere, e.g. by a card) |
| `ref_kind` | `str` | `node_ref` | restricts the dropdown to nodes with that card kind |
| `insert_columns` | `True` / `"inline"` / `"mapping"` | `text` | offers an upstream-column inserter (see below) |
| `visible_when` | `dict[str, list[str]]` | all | show this row only for certain values of other params |
| `cosmetic` | `bool` | all | changing it does **not** dirty the node (see below) |

#### `visible_when`

```python
{"name": "sheet", "type": "string", "label": "Sheet",
 "visible_when": {"format": ["excel"]}},
```

Show the row only while `format` is `"excel"`. Several keys are ANDed. A bare
string is accepted for a single value. A param **cannot** depend on itself, and
an empty allowed-list is an error.

This is **purely presentational**: `run()` still receives every param, visible
or not. Never treat a hidden row as an unset value.

#### `cosmetic`

Mark a param `cosmetic` when changing it **cannot change what `run()`
produces** — a card zoom level, a grid column count. Cosmetic params do not
mark the node dirty, so its cached output (and everything downstream) survives.
If `run()` reads the param, it is **not** cosmetic.

#### `insert_columns`

For a `text` box whose content is *about* columns but is not a list of them:

- `"inline"` — insert the column name at the cursor. For a line naming several
  columns, e.g. `margin = revenue - cost`.
- `"mapping"` — the box is one `column = value` entry per line; the picker is a
  set of ticks that add/remove whole lines. Blank and `#` lines pass through.
- `True` is a synonym for `"inline"`.

Either way the stored value is just the text.

### Ordering `PARAMS` for a clean panel

Order matters visually. Follow this layout:

1. Single-line params first (`string`, `int`, `float`, `bool`, `choice`,
   `columns`, file/folder pickers), most important first.
2. Multiline `text` params next, **grouped together**, never interleaved.
3. `width` / `height` / `scale` last.

Why: a `text` param renders as a fixed ~90px box. A short single value (a name,
a small list literal) in a `text` param looks like an oversized empty gap — use
`string` for those. Alternating tall/short rows makes the panel look broken.
See `util/note.py` for the canonical pattern.

### Reading params defensively

```python
column = str(ctx.params.get("column", "")).strip()
count  = int(ctx.params.get("count", 0) or 0)
factor = float(ctx.params.get("factor", 1.0))
```

Use `.get()` with a default. A user-edited node, or an older saved project, may
not carry every key you declared.

---

## 6. `run()` — the execution contract

### Signature

```python
def run(ctx, <one keyword argument per input port>):
```

- The first parameter is always `ctx`.
- Every declared input becomes a keyword argument **named exactly after the
  port**.
- Every **optional** input needs a `=None` default:
  `def run(ctx, table, extra=None):`
- A node with no inputs is `def run(ctx):`.

### Return value — exact rules

| Declared outputs | What `run()` may return |
|---|---|
| 0 | anything; it is discarded. Return `{}`. |
| 1 | the bare value, **or** a dict `{"<port>": value}` |
| 2+ | a dict whose keys are **exactly** the output port names — no missing, no extra |

Then **every returned value is type-checked** against its port type. A failure
raises `output 'name': got None for a port of type 'dataframe'` and the node
fails.

**Single-output gotcha.** With one output named `x`, returning the dict
`{"x": 1}` is read as the *port mapping*, not as a dict value. If a single
`any`/`object` output must carry a dict that could collide with the port name,
wrap it explicitly: `return {"x": {"x": 1}}`.

Prefer the explicit dict form always — it is unambiguous and survives adding a
second output later.

### Concurrency — the rule that bites hardest

**Your `run()` may be executing at the same time as another node's `run()`.**
Independent branches of a flow run side by side on worker threads.

Therefore:

- **Never** use module-level mutable state.
- **Never** `os.chdir()`.
- **Never** write to a fixed shared file path.
- **Never** use a library that is not thread-safe (matplotlib `pyplot` is the
  classic one).
- `print()` **is** safe — stdout is routed back to the node that wrote it.

Keep to what arrives in the arguments and goes back in the return value and
there is nothing to think about. When that is genuinely impossible, declare:

```python
NODE = {..., "exclusive": True}
```

and the engine drains everything in flight and gives the node the process to
itself. `exclusive` costs parallelism — use it only when required (matplotlib
drawing, a global-state library).

### Inputs are read-only

Outputs are cached and shared **by reference**. Two nodes fed by one upstream
node hold the same object at the same time, so writing through an input is a
data race.

The engine guards what it can guard for free:

| Input type | What arrives | What you must do |
|---|---|---|
| `pandas.DataFrame` / `Series` | copy-on-write shallow copy | assigning a column is safe; still prefer `df.copy(deep=False)` before reshaping |
| `list`, `dict`, `set`, `bytearray` | rebuilt one level deep | appending is safe; **items inside are not copied** |
| `numpy.ndarray` | read-only view; writing raises | call `arr.copy()` first |
| everything else (figures, connections, custom objects) | the original | **do not mutate** |

Reaching *through* an input — `rows[0]["x"] = 1` — reaches upstream whatever
the type. That is always yours to honour.

### Imports go inside `run()`

```python
def run(ctx, table):
    import pandas as pd          # correct
```

Never at the top of the file. The script is *executed* to read `NODE` and
`PARAMS`, so a top-level import runs at every load. An import inside `run()`
costs nothing until the node runs, and a missing package then fails only that
node with an installable message.

For an **optional** dependency, check first and give an actionable error:

```python
def run(ctx, table):
    import importlib.util
    if importlib.util.find_spec("matplotlib") is None:
        raise RuntimeError(
            "Show Plot requires the optional matplotlib extra. Install it "
            "with `pip install flograph[matplotlib]` or "
            "Tools > Manage Packages > matplotlib.")
    from matplotlib.figure import Figure
```

### Long loops

```python
for i, item in enumerate(items):
    ctx.check_cancelled()          # keeps Stop working
    ctx.progress(i / len(items))   # fills the node's status ring
    ...
ctx.progress(1.0)
```

`ctx.progress()` is throttled inside the engine, so call it as often as is
convenient. A node that never calls it shows an indeterminate pulse instead.

### matplotlib

```python
from matplotlib.figure import Figure    # OO API only
fig = Figure(figsize=(7, 4.5), layout="tight")
ax = fig.add_subplot()
ax.plot(x, y)
return {"figure": fig}
```

**Never `import matplotlib.pyplot`.** It is not thread-safe from a worker
thread. A node that draws with matplotlib must also declare
`"exclusive": True`.

---

## 7. `ctx` — the complete node-facing API

`ctx` is deliberately tiny and stable. It carries **no** handle on the graph,
the cache, the UI or Qt. There is nothing else on it.

| Member | Type | Meaning |
|---|---|---|
| `ctx.params` | `dict[str, Any]` | the node's current param values |
| `ctx.vars` | read-only mapping | the flow's `${name}` variables, for a script that wants one directly rather than through a param |
| `ctx.log(msg)` | `None` | write one line to the Log console |
| `ctx.check_cancelled()` | `None` | raises `NodeCancelled` if the user hit Stop |
| `ctx.progress(fraction)` | `None` | `0.0..1.0` through this node's own work; throttled |
| `ctx.node_id` | `str` | this instance's id |

`ctx.vars` is a `MappingProxyType`. Variables are declared by a flow and are
**never** written by a node.

### Logging conventions

Log **one useful line** stating what happened in the user's terms:

```python
ctx.log(f"loaded {len(table)} rows x {len(table.columns)} columns")
ctx.log(f"kept {int(mask.sum())} / {len(table)} rows")
```

Do not log per-row inside a loop. Do not log debug noise.

### Error conventions

Raise a plain exception with a message that tells the user **what to do**. The
message lands on the node's tooltip, in the log console, and on the editor's
error marker.

```python
# good
raise ValueError("no file selected — set 'CSV file' in the node's properties")
raise ValueError(f"column {column!r} not in table (has: {available})")

# bad
raise ValueError("bad input")
assert column in table.columns
```

Rules:

- Name the **param label** the user must fix, in quotes, exactly as it appears
  in the panel.
- When a name was not found, list what *is* available.
- `ValueError` for bad params/data; `RuntimeError` for a missing environment
  (an absent optional package).
- Never use bare `assert` for validation — it can be stripped by `-O`.
- Never swallow an exception into a silent empty result.

---

## 8. Rich cards — `NODE["card"]`

An optional `card` gives the node a rich canvas card and dashboard tile instead
of a plain box. It travels with the code, so a copy saved as a user node keeps
the view.

| `card` | What it renders | Example node |
|---|---|---|
| `figure` | a matplotlib figure (a list renders as a stack) | `viz/show_plot.py` |
| `webview` | HTML in an embedded Chromium view | `viz/show_web.py` |
| `table_viewer` | a scrollable read-only table | `viz/show_table.py` |
| `grid` | an editable spreadsheet grid | `io/table.py` |
| `kpi` | one big number with a caption | `viz/card.py` |
| `slicer` | a tickable list of column values | `viz/slicer.py` |
| `control` | an input widget — **also needs `NODE["control"]`** | `input/slider.py` |
| `button` | a click-to-run action button | `util/action_button.py` |
| `note` | a rendered markdown card | `util/note.py` |
| `report` | markdown with `![[Label]]` embeds resolved from wired inputs | `viz/report_card.py` |
| `image` | an image | `viz/image.py` |
| `pdf` | a rendered PDF page | `viz/pdf_viewer.py` |
| `wiki` | the markdown wiki card | `viz/markdown_wiki.py` |
| `vars` | lists the flow's `${name}` variables and what they resolved to | `util/variables.py` |
| `reroute` / `goto` / `from` | wire-routing markers | `util/reroute.py`, `util/goto.py` |

Any other value is a load error. Omit the key entirely for an ordinary node.

**`webview` contract:** `run()` returns HTML — a raw HTML `str`, or any object
with `to_html()` (Plotly figures), or any object with `_repr_html_()` (folium,
Altair, pandas Stylers, IPython HTML).

**Card sizing:** declare `width` and `height` `int` params (last in `PARAMS`)
and the card gets a corner resize grip that writes straight into them. Omit
them and the card is fixed at its default size — a drag would have nowhere to
store the result. Add a `scale` param marked `"cosmetic": True` for zoom.

**A list output renders as a stack.** Wherever one figure renders, a list of
figures renders stacked. That is the whole "one chart per value of a column"
mechanism — the loop belongs in the node's own `run()` (see
`viz/chart_per_value.py`), never in a faceting UI.

---

## 9. Control nodes — `card: "control"`

A control node is an input widget the user sets on the card or on a dashboard
page, rather than a rendered output. One host renders all shapes from the
declaration plus `PARAMS`, so a new control is usually **just a script**.

```python
NODE = {
    "label": "Percent Slider",
    "category": "Input",
    "version": "1.0",
    "card": "control",
    "control": "slider",
    "inputs": [("maximum", "any", {"optional": True})],
    "outputs": [("value", "number")],
}
```

### Widget shapes and the params each reads

| `control` | Params the shape reads (besides `value`, `caption`) |
|---|---|
| `slider` | `minimum` `maximum` `step` `decimals` |
| `range` | two handles on one track → a low/high pair |
| `number` | `minimum` `maximum` `step` `decimals` `prefix` `suffix` |
| `text` | `placeholder` `multiline` |
| `date` | `minimum` `maximum` (blank = unbounded; ISO `YYYY-MM-DD`) |
| `toggle` | `text` (the label beside the tick box) |
| `choice` | `items` (one option per line) |

Two param names are **special and required**:

- `value` — the live value the widget writes and the node must output.
- `caption` — the label drawn above the widget on the card and tile.

### Well-known input port names

| Port name | Host behaviour |
|---|---|
| `minimum` / `maximum` | a bound; a wired column is reduced for you — lowest value for `minimum`, highest for `maximum` |
| `options` | the list a `choice` offers |
| anything else | passed through as-is and read by the shape if it knows the name |

### The one rule that matters: emit what the card shows

The widget clamps the value into the live bounds, so `run()` must clamp
**identically**, or the card reads `40` while the flow carries `900`. Shared
helpers exist precisely so both sides agree — use them, never roll your own:

```python
def run(ctx, minimum=None, maximum=None):
    from flograph.core.controls import as_number, clamp, reduce_bound

    low  = as_number(reduce_bound(minimum, high=False),
                     as_number(ctx.params.get("minimum"), 0.0))
    high = as_number(reduce_bound(maximum, high=True),
                     as_number(ctx.params.get("maximum"), 100.0))
    value = clamp(as_number(ctx.params.get("value"), low), low, high)
    return {"value": value}
```

A wired bound **wins over** the typed param — that is what the widget does.

If you need a shape that does not exist (a colour picker, a star rating), that
one needs Python: add a `ControlWidget` subclass to `flograph/ui/controls.py`
and its name to `CONTROL_KINDS` in `flograph/core/script.py`. Everything a
widget and its `run()` must agree on lives in `core/controls.py` and is never
duplicated.

Start from `nodes/scripting/control_template.py`.

---

## 10. Worked examples

### 10.1 Transform — two outputs, validation, logging

```python
"""Filter Rows

Keep the rows of a DataFrame matching a pandas query expression; the rows
that don't match come out of the second port.
"""
NODE = {
    "label": "Filter Rows",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("filtered", "dataframe"), ("rejected", "dataframe")],
}
PARAMS = [
    {"name": "query", "type": "string", "label": "Query expression",
     "default": "", "placeholder": "col_a > 0 and col_b == 'x'"},
]


def run(ctx, table):
    query = ctx.params["query"].strip()
    if not query:
        return {"filtered": table, "rejected": table.iloc[0:0]}
    mask = table.eval(query)
    ctx.log(f"kept {int(mask.sum())} / {len(table)} rows")
    return {"filtered": table[mask], "rejected": table[~mask]}
```

Note: a blank query is a *pass-through*, not an error. Prefer a sensible
neutral behaviour over failing when a param is simply not filled in yet —
unless the node cannot do anything at all without it (a file path).

### 10.2 IO reader — file param, lazy import, no inputs

```python
"""Read JSON Lines

Load a newline-delimited JSON file (.jsonl / .ndjson) into a DataFrame, one
object per line. Blank lines are skipped.
"""
NODE = {
    "label": "Read JSON Lines",
    "category": "IO",
    "version": "1.0",
    "inputs": [],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "path", "type": "file_open", "label": "JSONL file", "default": ""},
    {"name": "encoding", "type": "string", "label": "Encoding",
     "default": "", "placeholder": "auto (utf-8)"},
    {"name": "nrows", "type": "int", "label": "Max rows (0 = all)",
     "default": 0, "min": 0},
]


def run(ctx):
    import pandas as pd

    path = ctx.params.get("path", "")
    if not path:
        raise ValueError(
            "no file selected — set 'JSONL file' in the node's properties")

    kwargs = {"lines": True}
    encoding = ctx.params.get("encoding", "").strip()
    if encoding:
        kwargs["encoding"] = encoding
    nrows = int(ctx.params.get("nrows", 0) or 0)
    if nrows:
        kwargs["nrows"] = nrows

    table = pd.read_json(path, **kwargs)
    ctx.log(f"loaded {len(table)} rows x {len(table.columns)} columns")
    return table
```

### 10.3 Viz — figure output, `exclusive`, cosmetic scale

```python
"""Histogram

Draw a histogram of one numeric column and render it on the card.
"""
NODE = {
    "label": "Histogram",
    "category": "Viz",
    "version": "1.0",
    "card": "figure",
    # matplotlib is not thread-safe, so this node runs on its own.
    "exclusive": True,
    "inputs": [("table", "dataframe")],
    "outputs": [("figure", "figure")],
}
PARAMS = [
    {"name": "column", "type": "columns", "label": "Column",
     "default": "", "multi": False},
    {"name": "bins", "type": "int", "label": "Bins",
     "default": 20, "min": 2, "max": 500},
    {"name": "title", "type": "string", "label": "Title", "default": ""},
    {"name": "width", "type": "int", "label": "Width",
     "default": 420, "min": 260, "max": 1600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 320, "min": 200, "max": 2000},
    {"name": "scale", "type": "int", "label": "Scale %",
     "default": 100, "min": 25, "max": 400, "cosmetic": True},
]


def run(ctx, table):
    from matplotlib.figure import Figure   # OO API only — never pyplot

    column = str(ctx.params.get("column", "")).strip()
    if not column:
        raise ValueError(
            "no column selected — set 'Column' in the node's properties")
    if column not in table.columns:
        available = ", ".join(str(c) for c in table.columns)
        raise ValueError(f"column {column!r} not in table (has: {available})")

    values = table[column].dropna()
    if values.empty:
        raise ValueError(f"column {column!r} has no values to plot")

    fig = Figure(figsize=(7, 4.5), layout="tight")
    ax = fig.add_subplot()
    ax.hist(values, bins=int(ctx.params.get("bins", 20)))
    ax.set_xlabel(column)
    ax.set_ylabel("count")
    if ctx.params.get("title", "").strip():
        ax.set_title(ctx.params["title"].strip())

    ctx.log(f"histogram of {column!r} over {len(values)} values")
    return {"figure": fig}
```

### 10.4 Optional input with a standalone fallback

```python
def run(ctx, table=None):
    import pandas as pd

    if table is None:
        # standalone: the typed-in values *are* the data
        values = [v.strip() for v in ctx.params.get("values", "").splitlines()
                  if v.strip()]
        ctx.log(f"standalone: {len(values)} values")
        return {"table": pd.DataFrame({"value": values})}
    ...
```

Document the unwired behaviour in the docstring. An optional input whose `None`
case just raises should have been a required input.

---

## 11. Tests — required

Add tests to `tests/test_stdlib_nodes.py` using the existing helper:

```python
def run_node(registry, type_id, params=None, **inputs):
    spec = registry.get(type_id)
    defaults = spec.default_params()
    defaults.update(params or {})
    run = compile_run(spec.source, f"test-{type_id}")
    return run(FakeContext(params=defaults), **inputs)
```

`FakeContext` (in `tests/conftest.py`) records `ctx.log()` into `.logs` and
`ctx.progress()` into `.fractions`, unthrottled.

Cover **at minimum**:

1. the happy path,
2. at least one error path (missing param, unknown column, bad file),
3. any non-obvious branch (blank param = pass-through, unwired optional input).

```python
class TestHistogram:
    def test_draws(self, registry, table):
        out = run_node(registry, "flograph.viz.histogram",
                       {"column": "units", "bins": 5}, table=table)
        assert out["figure"].axes

    def test_requires_a_column(self, registry, table):
        with pytest.raises(ValueError, match="no column selected"):
            run_node(registry, "flograph.viz.histogram", {}, table=table)

    def test_unknown_column(self, registry, table):
        with pytest.raises(ValueError, match="not in table"):
            run_node(registry, "flograph.viz.histogram",
                     {"column": "nope"}, table=table)
```

The shared `table` fixture is:

```python
pd.DataFrame({
    "region":  ["north", "south", "north", "south"],
    "units":   [10, 20, 30, 40],
    "revenue": [100.0, 150.0, 300.0, 320.0],
})
```

Match error messages with `pytest.raises(..., match=...)` on a **substring of
the user-facing text**. That keeps the message itself under test, which is the
point — the message is the node's UI.

---

## 12. Verify

```bash
# contract + node behaviour (offscreen is mandatory — no display server)
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
    tests/test_stdlib_nodes.py tests/test_registry.py tests/test_node_versions.py -q

# full suite, in parallel
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q -n12 --dist loadfile
```

- `test_registry.py` parses **every** builtin script and catches contract
  violations at load time.
- `test_node_versions.py` fails if any builtin has no `NODE["version"]`.
- For a visual check, launch the app and find the node with the Tab palette.

---

## 13. Pre-flight checklist

Tick every line before declaring the node done.

**File**

- [ ] Lives at `src/flograph/nodes/<category_pkg>/<lower_snake_case>.py`
- [ ] Module docstring: label on line 1, blank line, user-facing summary paragraph
- [ ] No top-level code other than the docstring, `NODE`, `PARAMS`, `def run`
- [ ] **No top-level imports of pandas, matplotlib, or any third-party package**

**NODE**

- [ ] `label`, `category`, `version` all present; `version` is `"1.0"` for a new node
- [ ] `category` display name matches the package directory
- [ ] Every port type is one of: `any dataframe series number string bool object figure`
- [ ] Port names are valid identifiers, unique per direction, none named `flow`
- [ ] Every input that may be unconnected has `{"optional": True}`
- [ ] `exclusive: True` if and only if the node uses matplotlib or global state
- [ ] `card` (if present) is a valid kind; `control` present iff `card == "control"`

**PARAMS**

- [ ] Every `name` is a unique valid identifier
- [ ] Every `type` is valid; every `choice` has non-empty `options`
- [ ] Every param has an explicit `label`
- [ ] `placeholder` explains what blank means, wherever blank is meaningful
- [ ] Order: single-line first, `text` grouped next, `width`/`height`/`scale` last
- [ ] Any param `run()` never reads is marked `"cosmetic": True`

**run()**

- [ ] Signature has one kwarg per input port, `=None` on every optional one
- [ ] Returns a dict keyed by **exactly** the output port names
- [ ] Every returned value matches its declared port type (never `None` for a concrete type)
- [ ] Inputs are not mutated in place; `numpy` inputs are `.copy()`d before writing
- [ ] Heavy imports are inside the function
- [ ] Any loop over user data calls `ctx.check_cancelled()` and `ctx.progress()`
- [ ] Every error is a plain exception naming the param label to fix
- [ ] One `ctx.log()` line stating what happened in the user's terms

**Tests**

- [ ] Happy path + at least one error path in `tests/test_stdlib_nodes.py`
- [ ] `test_stdlib_nodes.py`, `test_registry.py`, `test_node_versions.py` all pass

---

## 14. Error message → cause → fix

| Message | Cause | Fix |
|---|---|---|
| `node script must define a NODE dict` | no module-level `NODE`, or it is not a dict | declare it |
| `NODE['label'] must be a non-empty string` | missing/blank/non-str label | set it |
| `NODE['category'] must be a non-empty string` | missing/blank category | set it |
| `NODE['version'] must be a string like '2.0'` | version is a list/dict | use `"1.0"` |
| `builtin nodes with no NODE['version']: [...]` | version missing on a builtin | add `"version": "1.0"` |
| `NODE['inputs'] must be a list of (name, type) tuples` | passed a dict or string | use a list of tuples |
| `NODE['inputs'][0] must be (name, type) or (name, type, opts)` | wrong tuple arity | 2 or 3 elements |
| `port name 'x y' must be a valid identifier` | space/hyphen in a port name | use `snake_case` |
| `duplicate port name 'table'` | same name twice in one direction | rename one |
| `'flow' is reserved` | declared a flow port | delete it; it is implicit |
| `unknown port type 'list'` | invented a type | use `any` or `object` |
| `NODE['card'] 'chart' is not a valid card kind` | typo or invented card | pick from §8, or omit |
| `NODE['control'] None is not a valid control kind` | `card: "control"` with no `control` | add `"control": "slider"` etc. |
| `NODE['control'] only applies when NODE['card'] is 'control'` | stray `control` key | remove it |
| `param 'x' has unknown type 'dropdown'` | invented param type | use `choice` |
| `choice param 'x' requires non-empty 'options'` | choice without options | add `"options": [...]` |
| `PARAMS: duplicate param name 'width'` | declared twice | rename one |
| `param 'x' cannot depend on its own value` | `visible_when` names itself | point it at another param |
| `node script must define a run(ctx, ...) function` | missing or non-callable `run` | define it |
| `run() must return a dict keyed by the output ports [...]; missing [...]` | returned fewer keys than ports | return every port |
| `... unexpected ['foo']` | returned a key that is not a port | remove it, or declare the port |
| `output 'table': got None for a port of type 'dataframe'` | returned `None` on a typed port | return a real value, or declare `any` |
| `output 'n': got 'str' for a port of type 'number'` | returned the wrong type | convert, or widen the port |
| `node script needs the 'X' package, which isn't installed` | top-level import of a missing package | move the import inside `run()` |
| `syntax error on line N` | the script does not parse | fix the syntax |
| `error while loading node script: ...` | top-level code raised | put the work inside `run()` |

---

## 15. Anti-patterns — do not do these

| Anti-pattern | Why it is wrong | Instead |
|---|---|---|
| `import pandas as pd` at the top of the file | runs at every registry load; breaks the node when the package is absent | import inside `run()` |
| `import matplotlib.pyplot as plt` | not thread-safe from a worker | `from matplotlib.figure import Figure`, plus `"exclusive": True` |
| `table["new"] = x` on a raw input then returning `table` | mutates a shared cached object | `out = table.copy(deep=False)` first |
| `arr[0] = 1` on a numpy input | the view is read-only and raises | `arr = arr.copy()` |
| `_cache = {}` at module level | shared across concurrent runs | keep state in the return value |
| `os.chdir(folder)` | process-wide; races other nodes | use absolute paths |
| `assert column in table.columns` | strippable, and a useless message | `raise ValueError("column ... not in table (has: ...)")` |
| `raise ValueError("invalid input")` | the user cannot act on it | name the param label and what is wrong |
| `except Exception: return {}` | hides failure; downstream gets silent garbage | let it raise |
| a `text` param holding a single short value | renders as an oversized empty box | use `string` |
| `width`/`height` in the middle of `PARAMS` | breaks the panel rhythm | put them last |
| a port type of `"list"` / `"path"` / `"html"` | not a real type; load error | `any` or `object` |
| a required input `run()` handles as `None` | it can never be `None` | mark it `{"optional": True}`, or make it required honestly |
| a param `run()` reads, marked `cosmetic` | stale cached output after an edit | drop `cosmetic` |
| registering the node somewhere | there is no registry list | the file on disk *is* the registration |

---

## 16. Reference implementations to imitate

| Pattern | File |
|---|---|
| Two outputs, query param, logging | `src/flograph/nodes/transform/filter_rows.py` |
| File param, many options, lazy import | `src/flograph/nodes/io/read_csv.py` |
| Figure output, optional dependency check, `exclusive` | `src/flograph/nodes/viz/show_plot.py` |
| HTML card from any library | `src/flograph/nodes/viz/show_web.py` |
| Optional input with a standalone fallback | `src/flograph/nodes/viz/slicer.py` |
| Control node with wired bounds | `src/flograph/nodes/input/slider.py` |
| No ports, display only, `text` param ordering | `src/flograph/nodes/util/note.py` |
| Open-ended `spare` input stack | `src/flograph/nodes/transform/concatenate.py` |
| Commented starting point | `src/flograph/nodes/scripting/node_template.py` |
| Commented control starting point | `src/flograph/nodes/scripting/control_template.py` |

**Source of truth**, if this guide and the code ever disagree:

- `src/flograph/core/script.py` — the contract, parsing, `CARD_KINDS`, `CONTROL_KINDS`
- `src/flograph/core/params.py` — `PARAM_TYPES` and every param key
- `src/flograph/core/datatypes.py` — `PortType`, `can_connect`, `validate_value`
- `src/flograph/engine/worker.py` — `_normalize`, output validation
- `src/flograph/engine/context.py` — `RunContext`
