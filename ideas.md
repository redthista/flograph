# Ideas

Grouped into chunks that are buildable in one go. Each chunk is meant to be
picked up whole: the pieces inside it touch the same code and share the same
decisions, so doing them together costs much less than doing them apart.

**An idea that ships is deleted from here.** `CHANGELOG.md` is the record of
what the app does and when it started doing it; a list that keeps its own
copy of that only tells you what someone remembered to tick. So this file
holds what is *not* built.

Chunk letters are stable — an entry keeps its id for life so notes and
commit messages that cite one still point at something, and an id is never
reused once its entry goes. Gaps (A, B, D, E, H, J, K, and most of G) are
where shipped work used to be. Old numbers are kept as "(was N)" where a code
comment still cites them.

Undecided and declined ideas live in `ideas_archived.md` — also not a done
list. Ideas for *new nodes* live in `node_ideas.md`; only the ones asked for
by name are repeated here. Status notes were checked against the code on
2026-08-27; the entries added since (G10, G11, N3, O1–R1) on 2026-08-30.

---

## C. Recovering work  (was 3)

**C4. Restore a crashed workflow from undo history** (was 3). Undo
history is in-memory only today, so this means persisting it somewhere
durable — worth a spike to size before it becomes a plan.

---

## F. Canvas performance

**F1. Drop to low LOD automatically when the frame rate falls.** A setting,
on by default: while panning (middle-mouse drag) at under 60 fps, switch
nodes to their flat paint until the pan ends. The pieces exist —
`NodeGraphScene.lod_enabled` / `lod_threshold` decide flattening by zoom
today, `BaseGraphicsView.fps` already measures redraw cost, and the
statistics window draws the 60 fps budget line — so this is a policy that
watches the measurement rather than new drawing code. Decide it with G2 in
front of you: they are the same trade-off from opposite sides.

---

## G. Canvas interaction

**G1. Pan by holding right-click**, as a setting.
Built and tried 2026-08-25, then taken back out the same day at Dan's
request — see `ideas_archived.md` #14 for what was learned and what
replaced it (a show-scroll-bars setting).

**G2. Show node names over the flat (low LOD) nodes.**

  Looked at 2026-08-11 and it is *not* the small job it reads as, so it is
  worth writing down before someone (me) picks it up expecting twenty
  minutes. `NodeItem._paint_flat` is deliberately "one fill, no
  path/gradient/text — the per-node cost that dominates when many nodes are
  visible at once". Text is precisely what it exists to avoid, so drawing a
  label in it walks back the optimisation that closed issue #2.

  Nor does drawing it normally help: flattening starts below lod 0.35, and
  a 9pt label at 0.3 is under 3px tall — there, but unreadable. To answer
  the actual question ("which node is that?") the labels have to be drawn
  at a *constant screen size*, ignoring zoom, like labels on a map. That
  brings the two real problems with it: the text cost comes back at exactly
  the zoom level where there are most nodes on screen, and at any distance
  the labels overlap each other into mush, so it needs a decluttering rule
  (draw the biggest/selected/hovered ones, drop the rest) to be any use.

  Both are decidable, but they need eyes on a real canvas, not a guess.
  Worth pairing with F1, which is the same trade-off from the other side.

**G10. The right-click palette is slow to open on Windows** (Dan). The node
palette that opens on a canvas right-click is noticeably slow on one Windows
machine. `NodePalettePopup` is built once and reused, but every open tears
the list down and rebuilds it: `popup_at` calls `_refresh("")`
unconditionally, which does `self._list.clear()` then builds a fresh
`QListWidgetItem` with an icon for all ~70 specs, and `registry.search("")`
re-sorts the whole spec dict on every call. Icons are cached and the
registry is not re-scanned, so the cost is the per-open widget rebuild plus
the sort, none of it kept between opens. A persistent model, or a memoised
`registry.all()`, is the lever — but measure on the slow machine first: the
popup is a fixed 280×320 and ~70 rows should not cost this much, so the real
cause may be Windows popup/paint behaviour rather than the rebuild.

**G11. Hide the grid without losing snap-to-grid** (Dan). A toggle that stops
the background grid being drawn while leaving snapping on. The two are
already independent in the code — `drawBackground` always draws the grid
with no visibility flag, and snapping is a separate view preference read
from `scene.snap_enabled` in each item's `itemChange` — so this is a new
`grid/visible` setting checked in `drawBackground` (canvas and dashboard
views both), pushed through the same `_apply_snap_settings` path the snap
toggle uses, with a checkbox in the Snapping group in Settings.

---

## L. Version control

**L1. Optional git integration for a project.** Every save is a commit, so a
workflow gets full configuration history: browse it, diff it, roll back.
Opt-in per project. Sits well with the `.flograph` file being plain JSON.

---

## M. Nodes asked for by name

The broader wishlist is `node_ideas.md`; these are the ones asked for
directly.

**M2. User forms.** A form with fields and a submit button — one node, or a
node pair with a retrieval side — writing to a DataFrame, a SQL table, or
whatever else is useful. The Input category covers single values today;
this is the "capture a record" shape it cannot express.

---

## N. Dashboard pages

**N3. Set the shape a visual takes on a page** (Dan). Asked for as "a wide
Plotly chart, or a long thin one". The two page kinds answer this
differently today:

  On a **report page** (the flowing document), `![[chart|width=50%]]` is
  the only per-embed control — `EMBED_OPTIONS == ("width",)`, and a test
  pins it closed. The figure's wide-or-tall shape comes from the figure's
  own `layout.width` / `layout.height`, set on the chart node or a Plotly
  Style node; the report only scales the placement width. A `height=` or
  `ratio=` embed option is the natural addition, plumbed through
  `parse_options` and `render.plotly_geometry` — but the render code
  deliberately resists resizing Plotly figures, because the labels do not
  scale with them. Sits with `ideas_archived.md` #7, which already parks
  `![[chart|fit]]` and embed alignment.

  On a **dashboard page** (free-form tiles) the capability is already there
  by dragging a tile's edges; what is missing is a numeric "W:H" input, an
  aspect lock while resizing, and a few preset ratios — new UI on `TileItem`
  or the properties panel.

---

## O. Opening a project

**O1. A start screen, the way PyCharm opens** (Dan). A list of recent
projects — each with its name, its folder, and a generated initials tile —
shown when the app has no project open, instead of dropping straight onto an
empty canvas. Half of it exists: QSettings already keeps `recent_files`
(the last 8 paths), `_recent_files()` filters them to what still exists, and
the Open Recent menu is built from exactly that. What is missing is the
surface to show it on — the window always holds a live canvas, there is no
"no project" state — and any per-project detail beyond the path: no stored
display name, no thumbnail, no last-opened time, so those are derived (name
and initials from the filename) or newly recorded. The initials tile can
borrow the `mark_pixmap` / `mark_icon` pattern already used for node marks.
Pairs well with a thumbnail written on save.

---

## P. Running a flow without the app

**P1. A real CLI for headless runs** (Dan). Asked for as: run a `.flograph`
file end to end from a terminal, or from another tool (a Dataiku recipe, a
cron job) that has flograph installed. Most of this already works but is
unadvertised — `python -m flograph.engine.headless project.flograph [--var
name=value …]` loads the file, applies Variables-node overrides, runs the
whole graph on a `QCoreApplication` (no widgets, no display) and exits
non-zero if any node failed. What is missing is the front door:

  - a `flograph run <file>` console entry — today `[project.scripts]` has
    only the GUI `flograph`, and `python -m flograph` also opens the GUI;
  - a library call — `src/flograph/__init__.py` is empty, so there is no
    `flograph.run(path)`;
  - the caveat, worth stating in the docs: the engine imports Qt
    (`QCoreApplication`, `QThreadPool`, signals) and needs an event loop, so
    a headless run still needs PySide6 installed — only `flograph.core` is
    strictly Qt-free. It does not need a display.

  Mostly plumbing: an argparse dispatch in `app.py` (or a new `cli.py`)
  routing `run` to `engine.headless.main`, plus a thin `flograph.run`
  wrapper.

---

## Q. The code editor

**Q1. Give the editor's message its own row** (Dan). In the Code panel the
apply/error message (`self._message`) shares one horizontal row with the
Ask AI / Save / Reset / Apply buttons. A short "Applied." fits; a
word-wrapped traceback from a failed run does not, and wraps into two or
three lines in the narrow space left beside the buttons, squeezing the row.
Split the footer into a message row above the button row. The message is a
`QLabel` (click to copy the full traceback), not a text area — a scrollable
log view would be a larger change and probably belongs with the Log dock.

---

## R. Data tables

**R1. Fit a column to its header, not just its contents** (Dan). The
editable Table node and its pop-out editor use `SpreadsheetView`, which
auto-sizes columns — but `resizeColumnToContents` measures the cells and the
72px default section size can swallow a longer header. The read-only
`DataTableView` behind Show Table, the Inspector dock and the column-spec
view does no auto-sizing at all — `PandasModel` answers no `SizeHintRole`
and nothing calls a resize. Either way the ask is the same: a column should
be at least as wide as its name. For `DataTableView` that means new sizing
that takes `max(content, header)` over the paged-in rows only (the model is
lazy); `DataTableView` is shared by node cards and dashboard tiles too, so
the change lands in four places at once.

---

## Elsewhere

- **Metanodes / subfolders / collapsible frames** (Stu, and a recurring
  ask). Already written up as `ideas_archived.md` #4, where it is parked as
  LARGE and undecided — decide it there rather than forking a second note.
