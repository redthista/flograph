# Node Cookbook

[[Writing a Node]] is the contract — what `NODE`, `PARAMS` and `run` mean.
This page is the other half: complete nodes you can copy, the rules about
what `run` may hand back, and a checklist and error table for when one
doesn't load.

Every example here is a whole file. Paste one into the editor of a fresh
**Node Template** (Scripting category), or save it into your nodes folder,
and it works as written.

## Where the file goes

A node is one `.py` file. Its location decides its type id and its library
group; nothing else registers it.

| File | Type id | Library group |
| --- | --- | --- |
| `<nodes>/scale_column.py` | `user.scale_column` | ungrouped |
| `<nodes>/finance/margin.py` | `user.finance.margin` | Finance |
| `src/flograph/nodes/transform/sort.py` | `flograph.transform.sort` | from `NODE["category"]` |

`<nodes>` is your nodes directory — see [[Nodes and the Library]]. New files
appear in the library on next launch; **Save as user node…** in the editor
writes one for you. Files whose name starts with `_` are skipped.

## A whole node, start to finish

```python
"""Scale Column

Multiply one numeric column by a factor and write the result into a new
column. Leave "New column" blank to overwrite the source column instead.
"""
NODE = {
    "label": "Scale Column",
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
     "default": "scaled", "placeholder": "blank = overwrite the source"},
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

Five things are worth noticing, because they recur in every node below:

- The **docstring's first line is the label** and its first paragraph is what
  the properties panel shows. Write it for whoever will use the node, not for
  whoever will maintain it.
- Params are read with `.get()` and a default. A node saved by an older
  version of itself may not carry every key you now declare.
- The column is checked, and the failure **says what to fix and lists what
  was available**. That message is the node's error UI.
- `table.copy(deep=False)` before writing. See *Treat inputs as read-only* in
  [[Writing a Node]].
- One `ctx.log` line, in the user's terms, saying what happened.

## What run may return

| Outputs declared | What `run` may return |
| --- | --- |
| none | anything — it is discarded. Return `{}`. |
| one | the bare value, **or** `{"<port>": value}` |
| two or more | a dict whose keys are **exactly** the port names — nothing missing, nothing extra |

Every returned value is then checked against its port type, so a node
declaring `dataframe` and returning `None` fails with
`output 'table': got None for a port of type 'dataframe'`. If an output can
legitimately be `None`, or its type depends on the params, declare it `any`.

There is one trap. With a single output named `x`, returning `{"x": 1}` is
read as the *port mapping*, not as a dict you meant to output. If a single
`any` output has to carry a dict whose keys might collide with the port name,
wrap it: `return {"x": {"x": 1}}`.

Returning the explicit dict is the habit worth having — it says what you
mean, and it still says it after you add a second output.

## Two outputs

```python
"""Split On Threshold

Send rows at or above the cut-off out of "high" and the rest out of "low".
"""
NODE = {
    "label": "Split On Threshold",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("high", "dataframe"), ("low", "dataframe")],
}
PARAMS = [
    {"name": "column", "type": "columns", "label": "Column",
     "default": "", "multi": False},
    {"name": "threshold", "type": "float", "label": "Cut-off", "default": 0.0},
]


def run(ctx, table):
    column = str(ctx.params.get("column", "")).strip()
    if not column:
        raise ValueError(
            "no column selected — set 'Column' in the node's properties")
    if column not in table.columns:
        available = ", ".join(str(c) for c in table.columns)
        raise ValueError(f"column {column!r} not in table (has: {available})")

    mask = table[column] >= float(ctx.params.get("threshold", 0.0))
    ctx.log(f"{int(mask.sum())} at or above, {int((~mask).sum())} below")
    return {"high": table[mask], "low": table[~mask]}
```

Both ports must be in the dict. Returning only `{"high": ...}` fails with
`run() must return a dict keyed by the output ports ['high', 'low'];
missing ['low']` — an empty frame (`table.iloc[0:0]`) is how you say "nothing
came out of this side".

## A reader, with no inputs

```python
"""Read JSON Lines

Load a newline-delimited JSON file (.jsonl / .ndjson) into a table, one
object per line. Set "Max rows" above 0 to read only the start of a large
file.
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

`import pandas` sits **inside** `run`. A node with no inputs still takes
`ctx`. The bounds on `nrows` are `min` and `max` — those exact keys.

A file path is one of the few params worth failing on when it is blank: the
node genuinely cannot do anything without it. A blank *filter* or a blank
*sort key*, by contrast, should pass the table through rather than raise —
an unfilled box is a node you haven't finished configuring, not an error.

## A chart card

```python
"""Histogram

Draw a histogram of one numeric column and show it on the node itself.
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
    from matplotlib.figure import Figure   # the OO API — never pyplot

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

Three card habits:

- **`width` and `height` params make the card resizable.** The corner grip
  writes straight into them, so a card without them has nowhere to store a
  new size and shows no grip at all. Put them last in `PARAMS`.
- **`scale` is `cosmetic`.** `run` never reads it — the zoom applies to the
  card, to a figure the node already produced — so marking it cosmetic stops
  a zoom from re-running the plot and everything downstream.
- Drawing with matplotlib means `"exclusive": True`, because pyplot's
  machinery isn't thread-safe and branches otherwise run side by side.

For a chart from a library that emits HTML instead — Plotly, folium, Altair,
a pandas Styler — use `"card": "webview"` and return the HTML, or any object
with `to_html()` or `_repr_html_()`. Fork **Show Web View** for that.

## An optional input with something to fall back on

An optional input arrives as `None` when nothing is wired to it, so `run`
needs a default in its signature and a branch for the unwired case:

```python
"""Value List

Emit a one-column table of values. Wire a table in to take a column's
distinct values; leave it unwired and the values typed into "Values" are
used instead, so the node works as a standalone source.
"""
NODE = {
    "label": "Value List",
    "category": "Util",
    "version": "1.0",
    "inputs": [("table", "dataframe", {"optional": True})],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "column", "type": "columns", "label": "Column",
     "default": "", "multi": False},
    {"name": "values", "type": "text", "label": "Values (one per line)",
     "default": "", "placeholder": "Used only when no table is connected"},
]


def run(ctx, table=None):
    import pandas as pd

    column = str(ctx.params.get("column", "")).strip()

    if table is None:
        values = [v.strip() for v in ctx.params.get("values", "").splitlines()
                  if v.strip()]
        ctx.log(f"standalone: {len(values)} values")
        return pd.DataFrame({column or "value": values})

    if not column:
        raise ValueError(
            "no column selected — set 'Column' in the node's properties")
    if column not in table.columns:
        available = ", ".join(str(c) for c in table.columns)
        raise ValueError(f"column {column!r} not in table (has: {available})")

    values = sorted(table[column].astype(str).unique())
    ctx.log(f"{len(values)} distinct values of {column!r}")
    return pd.DataFrame({column: values})
```

Say in the docstring what happens when the port is left unwired — it is the
first thing someone wonders. And if the `None` branch only ever raises, the
input wasn't optional: drop `{"optional": True}` and let the engine hold the
node back until it is connected.

## A control the user drives

A control node is one of the built-in widget shapes plus whatever `run` does
with the value. `value` and `caption` are the two special param names; the
rest are read by the shape you named.

```python
"""Percent Slider

A 0–100 slider that emits a fraction (0.0–1.0), for feeding straight into a
sample size or a threshold. Wire a number column into "maximum" to bound the
track by your data instead of by a typed-in limit.
"""
NODE = {
    "label": "Percent Slider",
    "category": "Input",
    "version": "1.0",
    "card": "control",
    "control": "slider",
    "inputs": [("maximum", "any", {"optional": True})],
    "outputs": [("value", "number")],
}
PARAMS = [
    {"name": "caption", "type": "string", "label": "Caption",
     "default": "Sample", "placeholder": "Shown above the slider"},
    {"name": "value", "type": "float", "label": "Value", "default": 10.0},
    {"name": "minimum", "type": "float", "label": "Minimum", "default": 0.0},
    {"name": "maximum", "type": "float", "label": "Maximum", "default": 100.0},
    {"name": "step", "type": "float", "label": "Step", "default": 5.0},
    {"name": "width", "type": "int", "label": "Width",
     "default": 240, "min": 140, "max": 600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 96, "min": 60, "max": 400},
]


def run(ctx, maximum=None):
    from flograph.core.controls import as_number, clamp, reduce_bound

    low = as_number(ctx.params.get("minimum"), 0.0)
    # a wired bound wins over the typed one, which is what the widget does
    high = as_number(reduce_bound(maximum, high=True),
                     as_number(ctx.params.get("maximum"), 100.0))
    percent = clamp(as_number(ctx.params.get("value"), low), low, high)

    ctx.log(f"{percent:g}% -> {percent / 100.0:g}")
    return {"value": percent / 100.0}
```

The rule that matters for a control: **emit what the card is showing.** The
widget clamps into the live bounds, so `run` has to clamp the same way, or
the card reads 40 while the flow carries 900. The helpers in
`flograph.core.controls` exist so both sides do it identically — use them
rather than writing your own.

Well-known input port names the host understands: `minimum` and `maximum`
(a wired column is reduced for you — lowest value for one, highest for the
other) and `options` (the list a `choice` offers). Fork **Control Template**
for the annotated version.

## Params that make a good panel

Each entry in `PARAMS` is one row, top to bottom, in the order you list them.
Two habits keep the panel readable:

**Order them: single-line first, `text` boxes grouped next, `width` /
`height` / `scale` last.** A `text` param renders as a fixed multi-line box,
so alternating tall and short rows makes the panel look broken.

**Use `text` only for genuinely multi-line content** — code, markdown, one
mapping per line. A short single value in a `text` box is an oversized empty
gap; that wants `string`, with a `placeholder` saying what blank means.

Where a box is *about* columns but isn't a plain list of them, add
`insert_columns` — `"inline"` to insert a name at the cursor, `"mapping"`
when each line is `column = value`. And `visible_when` keeps a row hidden
until it applies, which is what stops a reader that handles five file formats
from showing all five sets of options at once.

## Trying it without the GUI

A node runs the same headless, so the quickest way to exercise one over a
range of inputs is a terminal:

```bash
flograph run my_flow.flograph --set threshold=10
```

See [[Running Headless]] for the full command. Errors print with a traceback
mapped to the line in your own script, exactly as they appear in the Log dock.

If you are working from a checkout, `tests/test_stdlib_nodes.py` runs every
shipped node through the contract with a fake context; adding a case there is
the fastest feedback loop of all. Cover the happy path and at least one
failure — a blank param, an unknown column — so the error messages stay under
test too. They are user-facing text.

## Before you call it done

- [ ] The docstring's first line is the label, and its first paragraph reads
      like something a user would want.
- [ ] `NODE` has `label`, `category` and `version` (a new node starts at
      `"1.0"`; bump it when params or behaviour change).
- [ ] Every port type is one of `any`, `dataframe`, `series`, `number`,
      `string`, `bool`, `object`, `figure` — there are no others.
- [ ] Every input that may be left unwired is marked `{"optional": True}`
      **and** has a `=None` default in `run`.
- [ ] Every `choice` param has non-empty `options`; spin-box bounds use the
      keys `min` and `max`.
- [ ] Params are ordered single-line, then `text`, then `width` / `height`;
      anything `run` never reads is marked `cosmetic`.
- [ ] `run` returns a dict keyed by exactly the output port names, and no
      value is `None` on a port with a concrete type.
- [ ] Inputs are not written through; a numpy input is copied before writing.
- [ ] Imports are inside `run`, not at the top of the file.
- [ ] Long loops call `ctx.check_cancelled()` and `ctx.progress()`.
- [ ] Every error names the param label to fix, and lists what was available
      when a name wasn't found.
- [ ] `"exclusive": True` if — and only if — the node draws with matplotlib
      or touches something process-wide.

## When it doesn't load

A node whose script breaks the contract loads as a broken placeholder that
keeps its code, and the message says which line to look at.

| Message | What it means |
| --- | --- |
| `node script must define a NODE dict` | no `NODE` at the top level, or it isn't a dict |
| `NODE['label'] must be a non-empty string` | missing or blank label |
| `NODE['category'] must be a non-empty string` | missing or blank category |
| `NODE['version'] must be a string like '2.0'` | version isn't text or a number |
| `NODE['inputs'] must be a list of (name, type) tuples` | a dict or a bare string where a list belongs |
| `NODE['inputs'][0] must be (name, type) or (name, type, opts)` | a tuple with the wrong number of parts |
| `port name 'x y' must be a valid identifier` | a space or dash in a port name |
| `duplicate port name 'table'` | the same name twice on one side |
| `'flow' is reserved` | you declared a flow port — every node already has one |
| `unknown port type 'list'` | not one of the eight types; use `any` or `object` |
| `NODE['card'] 'chart' is not a valid card kind` | see Cards in [[Writing a Node]] |
| `NODE['control'] None is not a valid control kind` | `"card": "control"` without a `"control"` shape |
| `NODE['control'] only applies when NODE['card'] is 'control'` | a stray `control` key |
| `param 'x' has unknown type 'dropdown'` | invented a param type; a dropdown is `choice` |
| `choice param 'x' requires non-empty 'options'` | a `choice` with nothing to choose from |
| `PARAMS: duplicate param name 'width'` | declared twice |
| `param 'x' cannot depend on its own value` | a `visible_when` pointing at itself |
| `node script must define a run(ctx, ...) function` | no `run`, or it isn't callable |
| `run() must return a dict keyed by the output ports [...]` | a port missing from the returned dict, or a key that isn't a port |
| `output 'table': got None for a port of type 'dataframe'` | returned `None` on a typed port — return a value, or declare `any` |
| `output 'n': got 'str' for a port of type 'number'` | convert it, or widen the port |
| `node script needs the 'X' package, which isn't installed` | a top-level import — move it inside `run`, or install the package |
| `syntax error on line N` | the script doesn't parse |
| `error while loading node script: ...` | top-level code raised; only declare up there |

## Habits worth avoiding

| Instead of | Do this |
| --- | --- |
| `import pandas as pd` at the top of the file | import it inside `run` |
| `import matplotlib.pyplot as plt` | `from matplotlib.figure import Figure`, plus `"exclusive": True` |
| writing a column onto an input and returning it | `out = table.copy(deep=False)` first |
| writing into a numpy input | `arr = arr.copy()` — the one you get is read-only |
| a module-level `_cache = {}` | keep state in what you return; nodes run side by side |
| `os.chdir(folder)` | absolute paths — the working directory is shared |
| `assert column in table.columns` | `raise ValueError` with a message naming the column and listing what's there |
| `raise ValueError("invalid input")` | say which param to fix and why |
| `except Exception: return {}` | let it raise — a silent empty result is worse downstream |
| a `text` param holding one short value | `string`, with a `placeholder` |
| `width` and `height` halfway up `PARAMS` | put them last |
| a port typed `"list"` or `"path"` | `any` or `object` — the eight types are the whole set |
| a param `run` reads, marked `cosmetic` | drop `cosmetic`, or the node keeps a stale cached output |
