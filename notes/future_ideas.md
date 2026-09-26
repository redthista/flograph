# Future directions

The long-horizon, architecture-shaping directions — the ones that are not a
buildable chunk you pick up in a week, and not "parked because small or
declined" either. Each is a genuine product direction with a full
investigation behind it.

How this differs from the other lists:

- `ideas.md` — the In-Tray. Buildable chunks, picked up whole. What is *not*
  built yet but has a clear shape.
- `ideas_archived.md` — undecided or declined small ideas. Not a done list.
- `node_ideas.md` — new-node backlog.
- **this file** — big directions. Each links to a full writeup in `ideas/`.
  An entry here is a decision waiting to be made about *where the product
  goes*, not a task waiting for a free afternoon.

Nothing here is committed to. Order is roughly "closest to feasible" first.

---

## FD1. Web / Docker flograph — an always-on container that publishes flows

**Full writeup:** `ideas/web-and-docker.md` (against `b2545c6`, 2026-09-03).
**Prompt:** "a web / docker version — an always-on container where we publish
flows, maybe just from the desktop, maybe also authored in a browser."

The ask splits into three halves in very different states:

- **Output half — nearly free.** `core/html.py` is already Qt-free and was
  built for exactly "the page handed to a real browser" — it coerces any
  viz-node output (Plotly, folium, Styler, `_repr_html_`, chart grids) to
  real *interactive* HTML. Report rendering is Qt-free too. Dashboard `Tile`
  geometry (rect, z, port) lives in the *serialized graph model*, not just
  the QGraphicsScene. So a Qt-free "dashboard page → HTML document" renderer
  is a bounded build, not a rewrite.
- **Input half — a reimplementation.** Browser slicers / sliders / date
  pickers driving server-side re-runs. `core/controls.py` keeps the
  option/value logic shared (the same seam the Qt widget and the node agree
  through today), and `engine.request_run([node, *downstream])` — already
  coalesced — is the exact re-run primitive. But the widgets are new code and
  a new maintenance surface. This is where the "live app for a non-technical
  user" vision actually lives.
- **Run half — a server build.** No HTTP layer exists; `engine/scheduler.py`
  imports `PySide6.QtCore`. v1 runs `QCoreApplication` on a background thread
  with an ASGI app (FastAPI + uvicorn, new `serve` extra) talking to it over
  a queue — not a de-Qt rewrite. Same data-locality ceiling as FD2: local
  file paths don't resolve in a container (mount volumes / push to URL+DB
  sources / add a `${data}` root variable).

**Four targets, cheapest first:**

| Target | What it is | Interactivity |
|---|---|---|
| **A. `flograph publish` → static HTML site** | render every dashboard + report to standalone HTML, host anywhere | none — slicers frozen at saved values |
| **B. `flograph serve` — one flow, live** | a container runs the flow, browser shows the dashboard, controls drive re-runs over WebSocket | full |
| **C. `File ▸ Publish` button** | desktop pushes the current `.flograph` to a running `serve` instance, which hot-swaps it | inherits B |
| **D. Author the canvas in a browser** | the node editor itself in the browser | — |

**Recommendation:** build **A** first regardless — a Qt-free "dashboard +
report → static HTML" renderer is independently useful, it finishes
`ideas_archived.md` #8 (Jinja HTML export), and every richer target is built
on it. Prototype **B** behind a flag with one message type
("control C = value V" → re-run downstream → push changed tiles). **C** is a
small follow-on and delivers the "publish from the desktop" headline. **D**
is a second full UI — north star only.

**Note:** B's server and FD2's Option D relay may be the same process. If
both are on the table, one design review, not two.

**First concrete step:** implement `core/dashboard_html.py` for one template
(`05_interactive_slicer_dashboard.flograph`) plus a `flograph publish`
subcommand; look at the result in a browser. That proves the renderer and
produces Target A in one move.

---

## FD2. Multiplayer / co-editing — 2–3 devs in one workflow

**Full writeup:** `ideas/multiplayer-collaboration.md` (against `b2545c6`,
2026-09-03). *(Doc currently lives on the unpushed branch
`worktree-multiplayer-investigation` — bring it onto master with this file.)*
**Prompt:** "how could 2–3 devs work in the same workflow, how would it work,
what are the limitations."

**The short answer:** the graph model is unusually ready for shared *editing*;
the execution and data-locality model is not ready for shared *running*.

- **Editing is a small job.** `ui/commands.py` is already the sole writer to
  the graph, and every mutation is already a small serializable named object
  with `redo()`/`undo()`. The graph is Qt-free and event-sourced, so a remote
  op applied through the same mutators fans out to the scene through the
  identical path a local edit takes — there is no separate "apply someone
  else's change" rendering path to build. Node ids are already `uuid4`, so
  concurrent creation needs no coordination. The insertion point is a single
  class: a `QUndoStack` subclass that broadcasts serialized commands.
- **Shared execution is structurally blocked.** Nodes hold local file paths;
  `.env` is per-machine by design; `uv` environments diverge; result caches
  are gigabytes and per-machine; non-deterministic nodes (AI, live APIs,
  time, randomness) never converge across machines. In a shared session,
  results stay *local* — everyone shares the graph, everyone runs it
  themselves.

**Rungs, cheapest first:** (0) async branch-and-merge over `.flowf`;
(1) shared session with soft locks + presence, execution local — **the sweet
spot for 2–3 people**; (2) real-time fine-grained CRDT — solves a problem 3
people don't have, at several times the cost; (3) shared execution via a
designated runner — "server edition", a product direction not a feature.

**Recommendation:** ship rung 0 regardless (it subsumes `ideas.md` L1 and the
graph merge it forces is reused by every higher rung); prototype rung 1
behind a flag; write down rung 3 as the north star so rung 1's wire formats
are chosen with it in mind. **First step:** a throwaway two-window
localhost-WebSocket spike wiring only add/move/connect/param commands, to
measure how clean the `commands.py` seam really is.

---

## Limitations shared by FD1 and FD2

- **A flow only produces the same numbers everywhere if its data sources
  resolve the same everywhere.** Local file paths don't; mounted volumes and
  URL / DB / cloud sources do. A `${data}` root variable turns most breakage
  into one config line, but shared/hosted sources are the real answer and
  they're user discipline, not a feature the tool can fully enforce.
- **Non-deterministic nodes never converge** — AI, live APIs, `datetime.now()`,
  "read whatever is in the folder today". Both directions sync the *graph*,
  not *reality*.
- **The engine assumes local everything.** `engine/scheduler.py` imports
  `PySide6.QtCore`; the result cache is large and per-process; a long-lived
  engine process raises the stakes on the known cache-pressure and Qt-teardown
  stability issues. v1 of anything server-shaped is one flow per process.
