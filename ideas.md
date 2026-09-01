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
reused once its entry goes. Gaps (A, B, D, E, H, J, K, most of G, P, Q and
R) are where shipped work used to be. Old numbers are kept as "(was N)" where
a code comment still cites them.

Undecided and declined ideas live in `ideas_archived.md` — also not a done
list. Ideas for *new nodes* live in `node_ideas.md`; only the ones asked for
by name are repeated here. Status notes were checked against the code on
2026-08-27; the entries added since (G10, N3, O1, S1) on 2026-08-30.

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

---

## L. Version control

**L1. Optional git integration for a project.** Every save is a commit, so a
workflow gets full configuration history: browse it, diff it, roll back.
Opt-in per project. The `.flograph` file is a zip bundle now, so the
integration should track the **`.flowf`** (File ▸ Export Workflow — plain
JSON, graph only) rather than the bundle: an Export-on-save, or a watched
`.flowf` beside the project.

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
empty canvas. Most of the *row* now exists: the title bar's project switcher
already draws exactly this (`window_frame.initials_pixmap` /
`initials_for`, and `_RecentRow` — tile, name without `.flograph`, folder
below), reading `_recent_files_existing()`. What is still missing is the
**surface** to show them on — the window always holds a live canvas, there
is no "no project" state — and any per-project detail beyond the path: no
stored last-opened time, no thumbnail, so those are derived or newly
recorded. Pairs well with a thumbnail written on save.

---

## S. Editing in the Markdown Wiki card

**S1. Edit pages from the Wiki card** (Dan). The Markdown Wiki card
(`flograph.viz.markdown_wiki`, shipped read-only) shows a folder of `.md`
files with `[[wikilink]]` navigation — `core/docpages.py` + `ui/wiki/`. It
is meant to be *written*, not just read: a model developer authoring a user
guide that ships on the dashboard. What is missing:

  - an **edit toggle** on the card — swap the `DocsBrowser` for a
    `QPlainTextEdit` on the current page's raw Markdown, **Save** writes the
    file and re-renders, with a modified indicator and a
    confirm-on-navigate-away;
  - **new page** (also offered when a `[[link]]` resolves to nothing),
    **rename** (rewrites inbound `[[links]]` across the folder), **delete**;
  - **reorder / regroup** the nav tree, which rewrites `_Sidebar.md`.

  The files are external — not graph state — so writes go straight to disk
  like the Write Text node, no undo stack. Editing is disabled when the
  folder is the bundled handbook (read-only in `site-packages` / the
  one-file temp dir) or otherwise not writable: hide the toggle and say why.
  All of it lives in `ui/wiki/` and `core/docpages.py`; the card and tile
  wiring is done.

---

## Elsewhere

- **Metanodes / subfolders / collapsible frames** (Stu, and a recurring
  ask). Already written up as `ideas_archived.md` #4, where it is parked as
  LARGE and undecided — decide it there rather than forking a second note.
  "A node that is its own flow" is the same ask; it lives there too.