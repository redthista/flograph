# flograph

A visual node-based Python environment: dataflow on an infinite
Blueprint-style canvas, where every node is real, editable Python — and the
same graph also gives you interactive dashboards and printable reports.

![status](https://img.shields.io/badge/status-v0.1-blue)

Build the pipeline on the **model canvas**, put its live results on a
**dashboard page** for someone who will never open the model, and write the
write-up on a **report page** that pulls the same charts and numbers into
markdown and prints to PDF. One file, three surfaces, no export step between
them.

---

## Install

flograph is a standard pip-installable package (hatchling build backend):

```bash
pip install flograph        # or, from a checkout: pip install -e .
```

That puts a `flograph` command on your PATH and makes `python -m flograph`
work. Optional extras pull in what individual nodes need:

| Extra | Brings | For |
| --- | --- | --- |
| `matplotlib` | matplotlib | Show Plot, Chart per Value |
| `plotly` | plotly | Show Plotly, Chart per Value (Plotly) |
| `excel` | openpyxl | Read/Write Excel |
| `parquet` | pyarrow | Read/Write Parquet |
| `geo` | geopandas, folium | maps in a web-view node |
| `ai` | requests | the local-LLM node assistant |
| `dev` | pytest, pytest-qt | running the test suite |

```bash
pip install "flograph[matplotlib,plotly,excel]"
```

You don't have to decide up front — **Tools > Manage Packages** installs
into the running environment, and a node can use a package the moment it's
there.

> The project was renamed from **flopy** to **flograph**: `flopy` was already
> taken on PyPI (USGS MODFLOW).

### One-file script (no install)

If you can't install packages on a given machine — locked-down work laptop,
no index access — but PySide6, pandas, jedi and psutil are already there,
build a single self-contained `.py`:

```bash
python scripts/build_onefile.py       # -> dist/flograph_onefile_<version>.py
python flograph_onefile_<version>.py  # run it anywhere, no install
```

It embeds flograph's own source as a base64 zip and unpacks to a temp dir at
startup. It does not bundle the third-party dependencies themselves.

## Run it

```bash
flograph                                # after install
python -m flograph                      # equivalent
python main.py project.flograph         # open a project from a checkout
python -m flograph.engine.headless project.flograph   # run it with no GUI
```

**File > Open Example** ships nine worked projects — filter-and-visualise, an
aggregate dashboard, a custom-script chart, join/group-by comparison, an
interactive slicer dashboard, a scripted pipeline in a frame, a retail ops
command centre, and two geo/folium maps. They're the fastest way in.

---

## The idea

**Nodes are Python scripts.** Every node — the shipped library included — is
one small module: a `NODE` dict declaring typed ports, an optional `PARAMS`
list that auto-generates its properties form, and a `run(ctx, **inputs)`
function. Double-click any node to read or fork its code in the built-in
editor, with syntax highlighting, jedi completion, find/replace, and error
markers on the failing line. There is no privileged built-in tier: the
Group By node is a file you can open and change.

**Dataflow semantics.** Data flows through typed ports; execution is a
topological walk of the *dirty* subgraph on a background thread, so re-runs
only recompute what actually changed. Outputs are cached per node. Status
LEDs read at a glance: grey idle, yellow queued, pulsing blue running, green
done, red error. Cancellation is cooperative (`ctx.check_cancelled()`).

**Inspect everything.** Click any node or wire to see the data on it — a
paged table view for DataFrames (millions of rows are fine), matplotlib
figures with a toolbar, pretty-printed objects. Per-node stdout and
tracebacks land in the Log dock, with the traceback mapped back to the line
in *your* node script.

**Projects are plain JSON** (`.flograph`) — diffable, reviewable, and small.
Node output caches are written to a side-car `<project>.flograph.cache/`
directory keyed by a fingerprint of each node's source, params and
everything upstream, so reopening a project restores the results you had
without a re-run. A stale or corrupt entry just leaves that node dirty; it
can never block a load.

---

## Canvas

| Action | Binding |
| --- | --- |
| Add node | `Tab` (search palette), right-click, or drag from the library |
| Connect | drag from a port; drop on empty canvas to pick a compatible node |
| Reroute dot | double-click a wire (double-click the dot again to name it) |
| Comment frame | `Ctrl+G` around the selection (frames move their contents) |
| Run all / selected / cancel | `F5` / `F6` / `Esc` |
| Run to this node | right-click a node |
| Pan / zoom | middle-drag or `Space`+drag / wheel |
| Frame view | `F` |
| Nudge selection | arrow keys |
| Raise / lower | `Ctrl+]` / `Ctrl+[` — add `Shift` for front / back |
| Duplicate / delete / rename | `Ctrl+D` / `Del` / `F2` |
| Settings | `Ctrl+,` |
| Undo anything | `Ctrl+Z` — every graph mutation is on the undo stack |

Nodes can be recoloured, aligned and distributed, locked into frames, and
stacked in a deliberate front-to-back order. **Goto / From** nodes give you a
wire without the wire: name a value at the Goto, pick it up at any number of
Froms, and keep a busy canvas readable. A **minimap** (toggleable in
Settings) and a status-bar resource monitor — system memory, the open
project's cache footprint, the selected node's own — keep an eye on the
scale of things.

Large graphs get a GPU-accelerated viewport option and zoom-based level of
detail, so cards stop rendering their contents when they're too small to
read.

---

## Cards, dashboards and controls

Any node can declare `NODE["card"]` and become a live card on the canvas —
not a preview pane elsewhere, the node *is* the chart. Card kinds shipped
today: `figure`, `webview`, `table_viewer`, `kpi`, `grid`, `slicer`,
`button`, `note`, `control`, `report`, plus the structural `reroute`, `goto`
and `from`.

Click **+** on the page bar to add a **dashboard page**. Drag nodes onto it
and each becomes a tile — the same widget as the canvas card, resizable and
arrangeable, showing STALE when its node is dirty. Tiles maximise to
fullscreen; pages can be renamed, recoloured, reordered by dragging, and
duplicated.

**Input controls** are the other half of that: a whole node category that you
*set* rather than compute. **Slider**, **Number**, **Text**, **Date**,
**Toggle** and **Choice** each carry a caption you write, are typed properly
so wires still validate, and re-run everything downstream when you move them.
A **Slicer** does the same for picking values out of a column. The result is
a dashboard you can hand to someone who will never open the model canvas:
they turn the knobs, the charts answer.

A control's options and bounds can come from its own optional input ports —
wire a column into a Choice node and its dropdown is that column's values.

## Report pages

The other page kind is a **report**: markdown that you write, with your
results dropped in by name.

```markdown
# Q3 review

Revenue came to ![[Total Revenue]] across ![[Region Count]] regions.

![[Revenue by Region]]

![[Sales Table|filtered]]
```

`![[Label]]` embeds a node's output — a figure, a table, a scalar, a
markdown string — resolved by node label, with `![[Label|port]]` picking a
specific output port. Embeds render inline mid-sentence for scalars and as
blocks for charts and tables, update when the flow re-runs, and warn visibly
when a name doesn't resolve. The page prints to **PDF** at 300dpi; the
preview and the PDF are literally the same document, so they can't disagree.

There is also a **Report card** (`Viz > Report`) — the same markdown, but as
a node *inside* the flow, embedding its own wired inputs. It edits in place
on the canvas, has a right-click Insert menu listing everything embeddable,
and tiles onto a dashboard. That gives you rich prose on a dashboard, which
a chart tile can't do.

---

## Node library

**Input** — Slider, Number, Text, Date, Toggle, Choice.

**IO** — Read/Write CSV, Excel, Parquet, JSON (incl. JSONL) and SQLite
(query in, table out); drag a file onto the canvas to get the right reader
already configured. **Table** is a real spreadsheet you edit on the canvas,
with formulas (`=SUM(A1:A9)`, plus `AVERAGE`, `ROUND`, `POWER`, `CONCAT`,
`LEFT`/`MID`/`RIGHT`, `AND`/`OR`/`NOT` and the rest of the usual set), fill,
copy/paste, and an optional linked input that keeps its contents when you
disconnect.

**Transform** — Select Columns, Filter Rows, Sort, Join, Group By,
Expression, Concatenate, Missing Values, Duplicate Row Filter, Rename
Columns, Pivot, Unpivot, Row Sampling, Convert Types, String Manipulation,
Statistics, Data Profile.

**Viz** — Show Table, Show Plot (matplotlib, live on-canvas), Show Plotly
(a real interactive plotly.js chart embedded on the canvas — hover, zoom and
pan in place), Show Web View (render *anything* that produces HTML: folium
maps, altair, bokeh, your own template), Card (a Power BI-style KPI number),
Table Spec (the incoming table's structure), Chart per Value and Chart per
Value (Plotly) — one chart per distinct value of a column, as a stack, in
either backend — Slicer, Report.

Any web-view node has **Open in Browser** on its right-click menu — the same
document, in a real browser, refreshed in place when the flow re-runs.

**Util** — Constant, Reroute, Note, Action Button, Goto, From.

**Scripting** — Python Script, plus Node Template and Control Template to
fork when you're writing your own.

---

## Writing a node

```python
"""My Node

The first paragraph of the docstring shows in the properties panel.
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
Param types include `string, text, int, float, bool, choice, columns, date,
password`. A `columns` param renders with a ▾ picker listing the columns of
the DataFrames cached on the node's inputs (run upstream once to populate
it); add `"multi": False` so picking replaces instead of toggling a comma
list.

Rules that matter:

- **Treat inputs as read-only** — outputs are cached by reference, so a write
  that escapes your node rewrites what every other branch reads. The engine
  guards what it can guard for free: a pandas input arrives as a
  copy-on-write shallow copy, and a list, dict, set or bytearray is rebuilt
  one level deep, so appending to a list or assigning a column stays local to
  your node. A numpy array arrives read-only and raises if you write to it —
  `arr = arr.copy()` first. Reaching *through* an input (`rows[0]["x"] = 1`),
  and anything else you pass between nodes, remain yours to copy.
- **Heavy imports go inside `run()`.** Node scripts are executed to be read,
  so a top-level import runs at library-load time.
- **matplotlib: the OO API only** (`matplotlib.figure.Figure()`), never
  `pyplot` — it isn't thread-safe from the worker.
- **A list output renders as a stack.** Return a list of figures and every
  surface that draws one figure draws them stacked. That's the whole "one
  chart per value" mechanism — the loop lives in your script, not in a
  faceting UI.

Add `"card": "figure"` (or `webview`, `table_viewer`, `kpi`, `grid`, …) to
give the node a live card. For an input control, `"card": "control"` plus
`"control": "slider"` — one host renders every control shape from that and
your `PARAMS`, so a new control node is usually just a script.

Drop new `.py` files under `src/flograph/nodes/<category>/` (or your user
nodes directory) and they appear in the library on next launch. If a node's
import is missing, it loads as a broken placeholder that keeps its code and
params — install the package, re-apply the code, and it repairs itself.

### AI assistant (optional)

**Tools > AI Assistant Settings** points flograph at any local
OpenAI-compatible chat server — Ollama, LM Studio, llama.cpp. You can then
describe a change in English ("filter out rows where price is negative") and
get a rewritten node script. It is never applied automatically: the reply
lands in the editor for you to read, and Apply stays a separate, explicit
action. Nothing leaves your machine unless you point it somewhere that isn't
local.

---

## Packages

**Tools > Manage Packages** installs, upgrades and uninstalls pip packages in
flograph's own environment. Nodes execute in-process, so anything installed
there is importable from a node's `run()` immediately — no restart for new
installs; upgrades of already-imported modules take effect next launch. The
dialog uses `pip` when the interpreter has it and falls back to `uv pip`
(uv-made venvs ship without pip). flograph's own core dependencies are
protected from uninstall.

## Settings

`Ctrl+,` opens a searchable two-column settings grid with a navigation tree:
**General** (window behaviour, resets), **Canvas** (display, snapping, colour
muting strength, GPU viewport, previews, page-bar position), **Table Node**,
and **About**. Selecting a group narrows the grid; the search box filters
across the page.

---

## Development

```bash
uv pip install -p .venv/bin/python -e ".[dev]"
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q
```

Architecture (src layout):

- **`flograph/core`** — Qt-free model: graph, typed ports, script contract,
  registry, JSON serialization, spreadsheet engine, report parsing, layering.
  Fully unit-testable; a poison test keeps Qt and pandas out of its import
  graph.
- **`flograph/engine`** — background execution: plan builder, single-thread
  pool worker, output cache and its on-disk persistence, cancellation,
  per-node stdout capture, tracebacks mapped to node script lines.
- **`flograph/nodes`** — the standard library; each node is a script file
  loaded as text through the same contract as user code.
- **`flograph/ui`** — canvas (QGraphicsView from scratch), dashboard and
  report pages, code editor, inspector, properties, console.

Two invariants hold everywhere:

1. **`core/` is Qt-free**, enforced by a test that imports it in a subprocess
   and asserts PySide6 and pandas never appear.
2. **QUndoCommands are the sole writers to the graph.** UI items react to
   graph events; nothing mutates the graph from a click handler. That is why
   `Ctrl+Z` works on literally everything.

See [AGENTS.md](https://github.com/redthista/flograph/blob/master/AGENTS.md) for the full contributor briefing.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for what's new in each version.

## License

[MIT](LICENSE) — free for commercial and private use, modification and
redistribution; just keep the copyright and license notice.
