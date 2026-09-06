# Writing a Node

Every node — the shipped library included — is one Python module loaded as
text. Double-click any node to read or fork its code in the built-in editor
(syntax highlighting, jedi completion, find/replace, error markers on the
failing line). This page is the full contract; the [[Node Cookbook]] has
complete nodes to copy, a checklist, and what each load error means.

## Anatomy

```python
"""My Node

The first paragraph of this docstring shows in the properties panel.
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
    return {"result": table * ctx.params["factor"]}
```

Three things: a `NODE` dict, an optional `PARAMS` list, and a `run` function.
Top-level code is *executed* every time the node is loaded — to read `NODE`
and `PARAMS` — so it should only declare. Everything else goes inside `run`.

## The NODE dict

| Key | Required | Meaning |
| --- | --- | --- |
| `label` | yes | Name in the palette and on the node. |
| `category` | yes | Library section: `IO`, `Transform`, `Viz`, `Input`, `Util`, `Scripting`, or your own. |
| `inputs` | yes | List of `(name, type)` tuples — see Ports. |
| `outputs` | yes | List of `(name, type)` tuples. |
| `version` | no | The node *type's* version, e.g. `"2.0"`. Bump it when params or behaviour change so a copy of the file elsewhere can be told apart from the current one. Shows in the properties panel and the library tooltip. |
| `exclusive` | no | `True` = this node runs with nothing else in flight. See Concurrency. |
| `card` | no | Makes the node a live card — see Cards. |
| `control` | no | With `"card": "control"`, the widget shape — see Cards. |
| `interactive` | no | With `"card": "webview"`, lets the page write this node's params from JavaScript — see Interactive views. |

Unknown keys are ignored, so a newer node file still loads on an older
flograph.

## Ports

Port types: `any`, `dataframe`, `series`, `number`, `string`, `bool`,
`object`, `figure`. A wire is allowed when the types are compatible (`any`
fits anything).

```python
"inputs": [
    ("table", "dataframe"),
    ("extra", "dataframe", {"optional": True}),   # may be left unconnected
],
"outputs": [("kept", "dataframe"), ("dropped", "dataframe")],
```

- An **unconnected optional input arrives as `None`**. A required input that
  is unconnected keeps the node from running.
- `run` receives each input as a **keyword argument** named for the port.
- `run` returns a **dict keyed by output port name**. A bare value is
  accepted when there is exactly one output.

Every node also has hidden **flow pins** for order edges (`[[The Canvas]]`);
you do not declare those.

## PARAMS

Each entry is a dict that becomes one widget in the properties panel. Its
value arrives in `run` via `ctx.params[name]`.

| `type` | Widget |
| --- | --- |
| `string` | single-line text |
| `text` | multi-line text |
| `int` | spin box |
| `float` | spin box (decimals) |
| `bool` | checkbox |
| `choice` | dropdown — needs `"options": [...]` |
| `columns` | comma list of column names, with a ▾ picker of the input's columns |
| `date` | calendar picker, stores `"YYYY-MM-DD"` |
| `password` | masked entry with a reveal toggle |
| `file_open` / `file_save` / `folder_open` | text + a browse button |
| `node_ref` | dropdown of other nodes in the graph, stores a node id |

Extra keys, all optional:

| Key | For | Meaning |
| --- | --- | --- |
| `label` | any | Row label (defaults to a title-cased `name`). |
| `default` | any | Starting value. |
| `placeholder` | text-like | Grey hint shown when empty. |
| `options` | `choice` | The dropdown values. May also be supplied at runtime by wiring a column into the node. |
| `min` / `max` | `int`, `float` | Spin-box bounds. |
| `multi` | `columns` | `False` = pick one column instead of a list. |
| `ref_kind` | `node_ref` | Restrict the dropdown to nodes with this card kind. |
| `visible_when` | any | `{"format": ["csv", "auto"]}` — show this row only while another param holds one of those values. Presentational only: `run` still gets every param. |
| `insert_columns` | `text` | Offer a column-name picker for a box that is *about* columns but isn't a plain list — `"inline"` inserts at the cursor, `"mapping"` treats the box as `column = value` lines. |
| `hidden` | any | Not shown in the panel (edited elsewhere). |
| `cosmetic` | any | Changing it does **not** mark the node dirty — its cached output survives. For things that only affect arrangement, like how a list of charts is laid out. |

Flow variables work in any text param: write `${data_dir}` and it resolves
from a `[[Flow Variables|Variables]]` node.

## run(ctx, \*\*inputs)

`ctx` is the engine's run context — a small, stable API:

| | |
| --- | --- |
| `ctx.params` | current param values (dict) |
| `ctx.vars` | the flow's `${name}` variables, read-only, for a script that wants one directly |
| `ctx.log(msg)` | write a line to the Log dock |
| `ctx.progress(f)` | `0..1` through this node's own work — fills the ring in the node's status LED and the status-bar line. Call it as often as you like; it is throttled for you. A node that never calls it just pulses. |
| `ctx.check_cancelled()` | raise if the user hit Cancel — call it in long loops |
| `ctx.node_id` | this node instance's id |

`print()` is safe whoever else is printing — output is routed back to the
node that wrote it and lands in the Log dock, with a traceback mapped to the
line in *your* script.

## The rules that matter

**Treat inputs as read-only.** Outputs are cached and shared by reference, so
a write that escapes your node rewrites what every other branch reads. The
engine guards what it can for free:

- a pandas input arrives as a **copy-on-write shallow copy** — assigning a
  column or filtering lands on your copy;
- a **list, dict, set or bytearray** is rebuilt one level deep — appending is
  safe;
- a **numpy array** arrives read-only and raises if you write to it — take
  `arr = arr.copy()` first.

Reaching *through* an input (`rows[0]["x"] = 1`), and anything else passed
between nodes — a figure, a connection — stay yours to copy.

**Concurrency.** Branches that do not depend on each other run at the same
time, so your `run` may execute beside another node's. Anything
process-wide — a module-level variable, a file you write, the working
directory, a library that isn't thread-safe — is a race. Keep to the
arguments and the return value and there is nothing to think about; when you
can't, set `NODE["exclusive"] = True` and the node runs with nothing else in
flight.

**Heavy imports go inside `run`.** The script is executed to read `NODE` and
`PARAMS`, so a top-level `import pandas` runs at library-load time — and on a
machine without the package the node loads as a broken placeholder instead of
working. An import inside `run` costs nothing until the node runs, and a
missing package then fails only that node with a message saying what to
install.

**matplotlib: the OO API only** — `matplotlib.figure.Figure()`, never
`pyplot`. pyplot isn't thread-safe from a worker.

**A list output renders as a stack.** Return a list of figures and every
surface that draws one figure draws them stacked. That is the whole "one
chart per value" mechanism — the loop lives in your script, not in a
faceting UI.

## Cards

Add `"card": <kind>` and the node becomes a live card on the canvas and a
tile on a dashboard — the node *is* the view.

`figure`, `webview`, `table_viewer`, `kpi`, `grid`, `image`, `pdf`,
`slicer`, `button`, `note`, `report`, `control`, plus the structural
`reroute`, `goto`, `from`, `vars`.

For an input control, `"card": "control"` plus `"control": <shape>` —
`slider`, `range`, `number`, `text`, `date`, `toggle`, `choice`. One host
renders every control from that declaration plus your `PARAMS`, so a new
control node is usually just a script.

## Interactive views

A `webview` node that adds `"interactive": True` gets a `flograph` object in
its page's JavaScript, so a click inside the visual can reach the graph:

```js
flograph.select(["north", "south"])  // writes the "selected" param
flograph.set("depth", 3)             // writes any param the node declares
flograph.ready(function (api) {})    // runs once the channel is live
flograph.connected                   // false outside flograph
```

A write commits as one undo step and re-runs the node and everything
downstream — the same thing a Slicer tick does, from inside your own HTML.
Read the value back in `run()` from `ctx.params`, redraw from it, and the
page and the graph stay in step without any state of their own.

The rules:

- **Declared params only.** A page can write what the node lists in
  `PARAMS`, and nothing else. Anything else is reported in the status bar.
- **Typed.** Values are coerced to the param's declared type and clamped to
  its declared `min`/`max`.
- **A cosmetic param commits without re-running**, like every other
  cosmetic param.
- **Writing the value it already has does nothing** — no undo step, no run.
  That is what stops a page that restores its own selection on load from
  re-running the flow forever.

`flograph.set` is a no-op outside the app, so the same page still works in
Open in Browser and in an exported file — it simply isn't live there. Ask
`flograph.ready()` rather than reading `connected` as the page loads; the
channel connects asynchronously, and calls made before it does are queued
and delivered on connect.

Fork **Show Web View** for the smallest working example, or **Web View
Template** for the full thing — a runnable visual whose comments carry every
rule that matters, including the ones that only bite in a report, a browser
or a differently-shaped tile. Or set **On click** on a Show Plotly node to
get click-to-filter without writing any JavaScript at all.

## Drawing with a web library

A `webview` node can draw with D3, ECharts, Leaflet, Mermaid and friends.
Install one from **Tools ▸ Web Libraries**, then ask for it by name:

```python
def run(ctx, table):
    from flograph.weblibs import markup
    return f"<html><head>{markup('echarts')}</head><body>…</body></html>"
```

**Nothing is ever loaded from the internet when a visual renders.** A CDN is
where a library is *installed from*, once; from then on the page reads it off
your disk. That is what keeps a visual working on a train, on a locked-down
network, and in a year when that CDN URL has moved — and it is why `markup()`
raises `MissingLibrary` (naming the fix) rather than quietly reaching out
when a library isn't installed. Treat it exactly like a missing Python
package: the node reports what to install.

Anything not in the catalogue can be added from a URL in the same dialog, and
behaves identically afterwards. Behind a corporate mirror, set
`FLOGRAPH_WEBLIB_BASE_URL` and installs are fetched from
`<base>/<library>/<version>/<file>`.

Right-click a view to get it out of flograph: **Save View as HTML…** writes
one self-contained file with the libraries embedded, and **Export View as Web
Folder…** writes the page plus an `assets/` folder with relative links, for a
share or a static host.

## Drawing with no library at all

A page that is HTML and CSS rather than a chart needs nothing installed, and
it sidesteps every trap above: nothing to measure, no canvas to lose, nothing
animating into a snapshot. `flograph.core.visual_style` is the house design
token set, and it will build the page for you:

```python
def run(ctx, table, style=None):
    from flograph.core import visual_style as vs
    tok = vs.tokens(style)            # a Visual Style node's payload, or None
    body = f"<div class='sheet'><div class='card'>"
    body += f"<div class='label'>Rows</div><div class='big'>{len(table)}</div>"
    body += "</div></div>"
    return {"html": vs.page(body, tok)}
```

`page()` returns a complete document with the stylesheet inlined — the kit of
class names (`sheet`, `grid`, `card`, `big`, `label`, `muted`, `track`/`bar`,
`chip`, `c1`…`c8`) and the variables behind them. Taking a `style` input and
passing it through `tokens()` is what lets one **Visual Style** node set the
look of every visual on a board. **HTML Template** is this idea with a
template language on top; read it if you want the worked version.

## Where nodes live

- **Builtin:** `src/flograph/nodes/<category>/<name>.py` (from a checkout).
- **User:** your nodes directory — `<user data>/flograph/nodes/`. A file at
  the top level is `user.<stem>`; in a subfolder it is
  `user.<folder>.<stem>` and the folder is the library group.

New `.py` files appear in the library on next launch. **Save as user node…**
in the editor writes the current node's code to your library, asking for a
name and group. A node whose import is missing loads as a **broken
placeholder** that keeps its code and params — install the package, re-apply
the code, and it repairs itself.

Fork **Node Template**, **Control Template** or **Web View Template**
(Scripting category) for a commented starting point, or copy a finished one
from the [[Node Cookbook]].

## Editing with AI (optional)

**Tools ▸ AI Assistant Settings** points flograph at any local
OpenAI-compatible chat server (Ollama, LM Studio, llama.cpp). Describe a
change in English and get a rewritten script. It is never applied
automatically — the reply lands in the editor and **Apply** stays a separate
action. Nothing leaves your machine unless you point it somewhere that isn't
local.

## Trying it headless

`ctx.progress` and `ctx.log` are no-ops-safe outside the GUI, so a node runs
the same under `[[Running Headless|flograph run]]`. That is the quickest way
to exercise a node in a loop or from a test.
