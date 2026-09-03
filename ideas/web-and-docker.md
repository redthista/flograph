# Web / Docker flograph — investigation

**Status:** investigation only, nothing started. **Written against** master
`b2545c6` (2026-09-03). Prompted by: "a web / docker version of flograph — an
always-on container where we can publish flows, maybe just from desktop, maybe
also authored in a browser."

The short answer: **the output half of this is unusually close — the Qt-free
`core/html.py` seam means a flow's dashboards already have a browser rendering
that isn't a screenshot. The input half (live controls in a browser) is a
reimplementation, and the run half (an always-on engine with no GUI and no
local disk) is a real but bounded server build.** A static "publish to HTML"
lands in days; a live "always-on container you hand to a non-technical user"
is weeks-to-months and shares its server with the multiplayer Option D.

This is the same north star the multiplayer investigation named as its
**Option D** (`ideas/multiplayer-collaboration.md` §4, `ideas_archived.md`
#15) — a designated runner that owns the document *and* the engine — but seen
from the *publishing* angle rather than the co-editing one. If both ever get
built they are plausibly one server; design them together.

---

## 1. What "web / docker flograph" actually means — pick the target

The prompt blends three different products. Cheapest first:

| Target | What it is | Interactivity | Needs |
|---|---|---|---|
| **A. Publish to static HTML** | `flograph publish flow.flograph -o site/` renders every dashboard page + report to standalone HTML, host anywhere | none — slicers frozen at saved values | a Qt-free dashboard-page renderer |
| **B. `flograph serve` — one flow, live** | a container runs the flow, browser shows the dashboard, slicers/controls drive re-runs server-side | full — controls POST/WS their value, server re-runs the subgraph | A + an ASGI layer + browser controls + data mounting + long-run hardening |
| **C. "Publish" button in the desktop** | `File ▸ Publish` pushes the current `.flograph` to a running `serve` instance, which hot-swaps it | inherits B | thin HTTP layer on top of B |
| **D. Author the canvas in a browser** | the node editor itself in the browser, talking to the server | — | a full front-end rewrite of `ui/canvas/` |

For "publish flows to an always-on container", **B is the real ask** and
**A is the thing to build first** because everything above it needs A's
renderer. **C** is a small follow-on that delivers the headline "publish from
the desktop". **D** is out of scope for a first pass — name it, don't scope it.

This lines up with the product vision (`flograph-product-vision` memory):
flows are meant to become **live apps — dashboard pages that refresh like an
Excel sheet, handed to someone who did not build them**. The web version is
how you hand it over without asking them to install a desktop Qt app. That
means B, not A, is where the vision actually lives — A is a stakeholder
snapshot.

---

## 2. What the architecture already gives us (the good news)

### 2.1 `core/html.py` — a Qt-free node-output → HTML page, already shared

`core/html.py` header, verbatim: *"It lives in core, with no Qt, because two
very different things now need the same answer: the embedded web view on a
card, and the page handed to a real browser."* `to_html(obj, …)` already
coerces every output kind a viz node produces — a raw HTML string, a Plotly
figure (`to_html(full_html=True, include_plotlyjs=True, responsive=True)`), a
folium map, a pandas Styler, anything with `_repr_html_()`, and a **list** of
figures laid out on a CSS grid from `core.chart_grid`. Plotly stays
*interactive* in that output, not snapshotted.

This is the single biggest asset. The dashboard's visual content is already
serialized to real HTML by code that never imports Qt, and `ui/browser.py`
already proves the round trip ("Open in Browser" writes exactly that HTML to a
file and hands it to the desktop).

### 2.2 The report path is Qt-free too

`core/report.py` parses a report body (markdown + `![[Label|port]]` embeds,
`​```columns` blocks, page breaks) with no Qt and no pandas import.
`ui/report/html.py` already renders a whole report as one self-contained HTML
file with charts inlined. Report pages are 90% of the way to web-publishable
today — this is `ideas_archived.md` #8 (Jinja HTML report export), and Target
A generalizes it from report pages to dashboard pages.

### 2.3 Dashboard tile geometry lives in the graph model, not just the scene

`core/graph.py`: `Tile(id, node_id, port, rect=(x,y,w,h), z)` and
`Page(tiles, maximized_tile, view_mode, fit_to_window, page setup)` are all
**serialized** (`core/serialization.py` — `.flowf` and `.flograph` both carry
them). So a Qt-free "dashboard page → HTML document" renderer has everything
it needs *from the model*: read each tile's rect, lay the tiles out on an
absolutely-positioned / CSS-grid canvas, drop each tile's `to_html()` output
into it. The QGraphicsScene in `ui/dashboard/` is a *view* of that data, not
the source of truth for layout.

### 2.4 A headless engine already exists and already runs as a job

`engine/headless.py` / `flograph run flow.flograph` loads a file, applies
`--var name=value` overrides, runs the whole graph on a bare
`QCoreApplication` — no widgets, no display — and exits non-zero on failure.
Its own docstring: *"treating a canvas project as a batch script."* The
`--var` mechanism is exactly the per-request parameterization a server needs
(§4.3).

### 2.5 `core/controls.py` — control options & values derived Qt-free

Slicer options, choice values, range pairs, date resolution, clamp — all
computed in `core/controls.py`, *deliberately* Qt-free so "the node scripts,
the engine's introspection and the widgets all agree on one answer." A browser
control and the server-side node will agree through the same module the Qt
widget and the node agree through today. The logic is shared; only the widget
is new.

### 2.6 The interactive re-run primitive is already the right shape

`mainwindow._on_slicer_changed` / `_on_control_changed`: a control edit is a
`SetParamCommand` that dirties the subgraph, then
`engine.request_run([node_id, *graph.downstream(node_id)])`, **coalesced** —
a burst of ticks becomes one run, and the request waits for any run in
flight. That is precisely the server-side handler for "viewer moved slicer X":
`set_param`, `request_run(downstream)`, then stream back the tiles whose nodes
re-ran. `request_run` coalescing already protects the engine from a viewer
dragging a slider.

### 2.7 The flow is self-contained enough to ship in one file

Node scripts are text (`NODE`/`PARAMS`/`run`), loaded not imported. Custom
`user.*` nodes **embed their script in the saved `.flograph`**
(`flograph-portable-user-nodes` memory). Pasted images inline as base64
(`flograph-image-portability`). A `.flograph` bundle can carry a warm result
cache (`core/container.py` `BundleReader`). So the artifact a container
receives — one `.flograph` file — already contains the graph, custom nodes,
inline images, and optionally a warm cache. Only bulk data and secrets live
outside it (§4).

---

## 3. What is missing or has to change (ranked by how much it hurts)

### 3.1 The dashboard is drawn in QGraphicsScene — needs a Qt-free page renderer

`ui/dashboard/tile_item.py` is 1528 lines of `QGraphicsItem`. The *content* of
a tile has an HTML path (§2.1 / §2.2); the *page* — tile rects, z-order,
maximized tile, fit-to-window scaling — is drawn by the scene from model data
it does not own (§2.3).

**The build:** a new `core/dashboard_html.py` (Qt-free), parallel to
`core/html.py` — takes a `Page` + the engine's cache and emits one HTML
document: a positioned container per tile, each tile's body from
`core.html.to_html(entry.outputs[port])` or the report renderer, plus a
per-tile-kind shell for the non-chart tiles:

- **chart / viz tile** — `core.html.to_html`, done
- **table tile** — the data table as HTML (`core/report.py` `frame_to_markdown`
  exists; a richer HTML table with sort is more work — see `ui/data_table.py`)
- **text / markdown / wiki tile** — `core/docpages.py` already renders wiki
  Markdown → HTML Qt-free
- **report tile** — `ui/report/html.py`, mostly there
- **control / slicer tile** — §3.3

Bounded and independently useful (email a dashboard, archive a run, CI
artifact). This *is* Target A, and it's the prerequisite for B and C.

### 3.2 There is no server, and the engine imports Qt

The app is one PySide6 process. `engine/scheduler.py` imports `PySide6.QtCore`
(`QObject`, `QThreadPool`, `QTimer`, `Signal`) — the `ExecutionEngine` is a
`QObject`, its worker pool is a `QThreadPool`, results cross threads via queued
signals. (`engine/context.py` — the node-facing `RunContext` — is already Qt-free,
using only `threading`; `engine/worker.py` is not.) This is the Qt-in-engine
coupling that the core invariant (`test_no_qt_in_core.py`) stops at `core/`
but not `engine/`.

**Two ways forward:**

1. **Tolerate it (v1).** Run `QCoreApplication.exec()` on a dedicated
   background thread — same object `flograph run` already uses. An ASGI app
   (FastAPI / Starlette + uvicorn, new `serve` optional-dependency group) on
   the main async loop talks to the engine over a thread-safe queue +
   `QMetaObject.invokeMethod` / queued signals; a request awaits a future
   resolved by the `run_finished` signal. No engine rewrite. This is the
   recommended v1 — `headless.py` proves the engine is happy without a screen.

2. **De-Qt the engine (later).** Replace `Signal` with a small callback/enum
   emitter and `QThreadPool` with `concurrent.futures`. A larger job and an
   ongoing invariant to hold, worth it only if the server becomes central.

Either way the ASGI layer owns: load a flow, hold one long-lived engine,
`GET` the dashboard HTML, `WS` for control changes → re-run → push changed
tiles, plus a `POST /run` webhook and a cron for scheduled base-data refresh
(this is the "engine-level schedule / webhook triggers" already noted in
`node_ideas.md` L118 — a companion feature, arguably a prerequisite for
"always-on").

### 3.3 Input controls need a browser implementation

Slicers, sliders, date pickers, text boxes, buttons are Qt widgets on
`card:"control"` / `card:"slicer"` hosts today. In the web app they become
HTML form controls whose change sends `{control_id, value}` over the
WebSocket; the server does `set_param` + `request_run(downstream)` + returns
the re-rendered tiles. `core/controls.py` (§2.5) keeps the option lists and
value normalization identical to the desktop. **This is the crux of the
vision** — without it the web version is a frozen snapshot, not a live app a
non-technical user can drive.

### 3.4 Data locality — the real ceiling (same as multiplayer §3.1)

A container cannot see `/home/dan/sales/q3.csv`. The Read CSV / Excel / PDF /
SQLite nodes hold **local filesystem paths**. For *publishing* this is more
tractable than for co-editing, because there is exactly one runner and its
filesystem is a deployment choice:

- **Volume-mount the data** next to the container, or bake it into the image.
- **A `${data}` root variable** so `${data}/q3.csv` rebinds to the mount —
  turns "broken in the container" into "set one path in the compose file".
  (Flow variables already exist — `flograph-flow-variables` memory.)
- **Bundle small inputs** into the `.flograph` the way images already inline
  (opt-in, size-capped).
- **Push toward URL / DB / cloud sources** — the Connect / Dataiku / HTTP
  nodes resolve identically everywhere. This is the honest long-term answer
  and it's user discipline, not something the tool can fully enforce.

### 3.5 Secrets

`.env` values are runtime-only and never serialized, by design
(`core/graph.py`; `SetEnvPathCommand` syncs only the *path*). Good — nothing
leaks into the published `.flograph`. The container supplies them: mounted as
env vars or a secrets file at the path the flow expects. Document it; there's
nothing to build.

### 3.6 Environment / dependencies

Desktop resolves optional extras lazily (`packages.py`, the
`[project.optional-dependencies]` groups — `excel`, `plotly`, `geo`, `sql`,
…). A container needs the flow's extras present. Options:

- **Fat image** — every extra pre-installed. Simple, big.
- **Resolve on load** — `flograph serve` reads the flow, maps node types →
  extra groups, `uv pip install`s the set into the container venv before the
  first run. The mapping mostly exists already (one group per library).

### 3.7 Long-lived process hardening

On record (`flograph-memory-safety-state`, `flopy-testing-notes` memories):
cache-pressure crashes on big projects, and Qt teardown segfaults with 2+
windows. A server process that stays up for days raises the stakes. Needs: a
per-flow memory ceiling, the existing pressure-based eviction
(`engine/pressure.py`) kept on, and a safety valve — recycle the engine on a
schedule or after N runs. **v1 = one flow per container**; multi-tenant
hosting multiplies every one of these risks and is its own project.

### 3.8 Auth and multi-viewer

Even "hand it to one person" needs a login or a signed link. Two viewers of
the same dashboard:

- **Shared engine + cache** — fast, low memory, but one viewer's slicer moves
  the other's view.
- **Session per viewer** — isolated, N× memory.
- **Shared read-only base + per-session control overrides layered on top** —
  the honest model for a dashboard, and it is *exactly* the shape of the
  `--var` / param-override mechanism (§2.4). The base flow runs once; each
  session carries its own control values and only the affected subgraph
  re-runs per session. Needs design, but the primitive exists.

### 3.9 Visual fidelity

A browser dashboard will *approximate* the Qt canvas, not match it
pixel-for-pixel — fonts, tile chrome, spacing. This is the same trade the
report "Web" preview target already accepted (`ideas_archived.md` #8, item
B1: "the preview becomes an approximation and 'open in browser' becomes the
real preview"). Acceptable; worth saying out loud.

---

## 4. Implementation options

### Option A — Publish to static HTML — build first, regardless

`flograph publish flow.flograph -o site/` (and `File ▸ Publish to HTML…` in
the desktop). Renders every dashboard page + report to standalone HTML via the
new `core/dashboard_html.py` (§3.1), Plotly inlined and interactive, one
`index.html` linking the pages. Host on S3 / Pages / an nginx container /
anything.

**Cost:** medium, all local, no server, no new runtime. Mostly §3.1.
**Ceiling:** no interactivity — slicers frozen at saved values.
**Fit:** high. Independently useful, finishes `ideas_archived.md` #8, and is
the groundwork every richer shape needs.

### Option B — `flograph serve`, one flow, live — the real ask

A container runs `flograph serve flow.flograph`. ASGI app + one long-lived
engine on a background Qt thread (§3.2 option 1). Browser gets the dashboard
as HTML (Option A's renderer); control changes go over WebSocket → server
`set_param` + `request_run(downstream)` → pushes back the changed tiles'
HTML. A `POST /webhook` and a cron refresh the base data. `docker run -v
./data:/data -e API_KEY=… flograph/serve flow.flograph`.

**Cost:** §3.1 + §3.2 + §3.3 + §3.4 + §3.7 + §3.8. Weeks-to-months.
**Ceiling:** one flow per container; browser fidelity approximate; controls
are new code, not a port.
**Fit:** this is where the product vision lives.

### Option C — "Publish" button in the desktop — small follow-on to B

`File ▸ Publish` packages the current `.flograph` (cache warm, custom nodes
embedded — both already true, §2.7) and `POST`s it to a running `flograph
serve` / a small registry. The container validates and hot-swaps the flow
(recycle the engine, reload). One-click "publish from the desktop".

**Cost:** low on top of B — an HTTP endpoint, an auth token, a reload path.
**Fit:** high — it's the headline the prompt asks for.

### Option D — Author the canvas in a browser — north star, not scoped

`ui/canvas/` (QGraphicsScene, node items, wires, the whole editor) rewritten
as a web front end talking to the server over the serialized-command stream —
the multiplayer doc's Option C/D territory (`commands.py` is already the sole
writer and already serializable). Enormous: a second full UI to build and
maintain forever.

**Cost:** very high.
**Fit:** the eventual endpoint. Name it so B's wire formats (command
serialization, the tile-HTML push protocol, the control-change message) are
chosen with it in mind — but do not build toward it yet.

---

## 5. Recommendation

1. **Build Option A now**, independent of the bigger ambition. A Qt-free
   "dashboard page + report → static HTML site" renderer is useful on its own,
   it's the fallback when a server isn't wanted, it finishes
   `ideas_archived.md` #8, and every richer shape is built on it. Low risk, no
   new runtime.
2. **Prototype Option B behind a flag.** `flograph serve` with one flow,
   engine on a background `QCoreApplication` thread, a WebSocket carrying
   exactly one message — "control C = value V" → `request_run(downstream)` →
   send back the changed tiles. Wire only a slicer and one control kind. That
   answers "how hard is the live loop" the way the multiplayer spike answers
   "how hard is the edit seam" — in days, and it de-risks everything after it.
3. **Option C is a small follow-on** to B and delivers "publish from the
   desktop".
4. **Write down Option D as the north star.** Same posture the multiplayer
   doc takes toward *its* Option D — and note explicitly that **B's server and
   multiplayer's Option D relay may be the same process**. If both are on the
   table, one design review, not two.

**Suggested first concrete step:** implement `core/dashboard_html.py` for one
real template (`05_interactive_slicer_dashboard.flograph` is the obvious
target) and a `flograph publish` subcommand that writes it out. Look at the
result in a browser (the `flopy-canvas-screenshot-harness` habit). That
proves the renderer and produces Option A in one move.

---

## 6. Limitations that survive every option

- **A published flow only produces correct numbers if its data sources
  resolve inside the container.** Local file paths don't; mounted volumes and
  URL / DB sources do. A `${data}` root turns most breakage into one config
  line, but shared/hosted sources are the real answer and they're user
  discipline, not a feature. (Identical to the multiplayer conclusion.)
- **Browser interactivity is a reimplementation of every control**, not a
  port. `core/controls.py` keeps the *logic* shared; the widgets are new code
  and a new maintenance surface.
- **Non-deterministic nodes** (AI, live APIs, `datetime.now()`, "read
  whatever is in the folder today") mean a scheduled container run and a
  desktop run of the same flow can legitimately differ. The container syncs
  the *graph*, not *reality*.
- **One long-lived engine per flow is the safe v1.** Multi-tenant hosting
  multiplies the known memory-pressure and teardown-stability risks and is a
  separate project.
- **Dashboard visual fidelity in a browser approximates the Qt canvas**, it
  does not match it — the same trade the report Web-preview target already
  accepted.
