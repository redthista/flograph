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
reused once its entry goes. Gaps (A, B, D, E, H, J, K, most of G, P, Q,
R, Y and Z) are where shipped work used to be. Old numbers are kept as "(was N)" where
a code comment still cites them.

Undecided and declined ideas live in `ideas_archived.md` — also not a done
list. Ideas for *new nodes* live in `node_ideas.md`; only the ones asked for
by name are repeated here. Status notes were checked against the code on
2026-08-27; the entries added since (G10, N3, O1, S1) on 2026-08-30.
M3, M4, N6 and chunks T–X were triaged out of Dan's 0.1.13 list and
checked against the code on 2026-09-07 — of which T2, T3, U1, V2, W1,
X2 and the whole of Y shipped the same day and have left the list. Z1
was triaged here too and shipped from another branch, so Z retires
without ever having been listed.

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

**M3. A node that runs another `.flograph` file** (Dan), with the option to
bring an output back. Most of it exists: `flograph run project.flograph
--var name=value` is a shipped headless runner (`engine/headless.py`), so
this is a node wrapping a thing that works rather than a second engine. Two
things need deciding. **In-process or subprocess** — the engine wants a
`QCoreApplication` and a node's `run` is on a worker thread, so a
subprocess is the safe answer and also the one that survives the child flow
crashing. And **how an output comes back** — the CLI prints and returns an
exit code, so the child has to write somewhere the parent reads (name an
output node, write it to parquet in a temp dir, read it back). Note the
overlap with `ideas_archived.md` #4: this is "a node that is its own flow"
with a file in the middle, and the two should not end up built twice.

**M4. Send an Outlook email, one per row** (Dan). A table in, one email per
row, subject and body as templates over that row's columns — the
`{{column}}` grammar HTML Template and Story already share. There are two
implementations and they are not the same feature: **Outlook on Windows**
(COM, via `win32com`) sends as the signed-in user, with their signature,
and lands in Sent Items — and works nowhere else; **SMTP** works everywhere
and needs a host, a port and a credential. One node with a **How** choice,
not two nodes. This one wants a guard rail more than most features do: a
dry run that writes the messages to a table instead of sending them, and a
confirmation naming the count. A flow that emails four thousand people by
accident is not a bug anybody gets to undo.

---

## N. Dashboard pages

**N3. Set the shape a visual takes on a dashboard page** (Dan). Asked for as
"a wide Plotly chart, or a long thin one". On a **report page** this shipped
as the `ratio=` / `height=` embed options (0.1.12). On a **dashboard page**
(free-form tiles) the capability is already there by dragging a tile's edges;
what is missing is a numeric "W:H" input, an aspect lock while resizing, and
a few preset ratios — new UI on `TileItem` or the properties panel.

**N4. A slicer that greys out values with nothing behind them.** Excel greys
a slicer value that the *other* slicers have already filtered away, so you
can see that "Bristol" exists but is empty under the current selection
rather than watching it vanish. flograph's slicers chain instead: the second
one reads the first one's *output*, so an emptied value simply has no row.
Greying instead of dropping needs each slicer to see both the filtered and
the unfiltered frame — `slicer_options` already reads the upstream cache, so
the missing half is the *unfiltered* source, which means walking back past
the slicers above it. Worth doing only if the vanishing turns out to confuse
people; the counts shipped in 0.1.14 already answer most of "why is that
gone".

**N5. Expand / collapse all on a deep slicer tree.** A hierarchy opens fully
expanded, which is right for two levels and wrong for three over a wide
column. A pair of buttons in the slicer toolbar (and remembering which
branches were open, in a param) — small, but only worth it once someone has
a three-level slicer.

**N6. Where is this visual used?** (Dan) A right-click on any visual node
that answers "this is on dashboard page X and report page Y", and takes you
there. The links already exist in both directions — a dashboard tile stores
the node it shows, and a report page's `![[name]]` embed names it — so this
is a reverse lookup across the project's pages plus a menu entry, and the
Navigator dock (`ui/navigator/`) is probably where the answer wants to live
as well as in the menu. Include **"used by no page"** as an answer: on a
board that has grown, that is the question people are really asking.

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

## T. Table formatting — what a cell can show

Everything here is `core/table_format.py` (the rule model and its parser),
`ui/table_delegate.py` (the card) and `core/table_html.py` (paper). T1 is
the one to schedule deliberately: it changes the data model a cell's
decorations live in, and T4 writes into that model.

**T1. More than one decoration in a cell, and somewhere to put it** (Dan).
Asked for as four things that are one thing: an icon on the **right** as
well as the left; **two icons at once** (an "OT" mark and then a green
tick); **above / below** as positions, with the row growing to hold them;
and **pill** styles — a coloured lozenge around an icon, some text, or the
column's own value, drawn either in place or in another column.

  It reads like drawing work and is really a model change. `CellStyle` holds
  exactly one `icon` / `icon_color` pair, and `CellStyle.over()` merges two
  rules with `icon=self.icon or base.icon` — so a second icon rule cannot
  *add*, it can only fail to replace, and no amount of delegate work gets
  round that. A cell holding a **list** of decorations, each with a position
  and an optional pill, is the piece the other three hang off; after it, the
  delegate lays them out and `table_html` writes the same arrangement for
  paper. The grammar has to grow to match — `units bar blue only` has
  nowhere today to say "on the right".

  Two decisions to take with a real table in front of you rather than
  guessing. Whether **above / below** is per-cell or, like `wrap`, a fact
  about the whole table (a row is as tall as its tallest cell, so one cell
  asking for a second line spends every row's height). And whether a
  **pill** is a decoration or a *replacement* for the value — `only`
  already means "draw the format instead of the value", so it is probably
  the latter, spelled with what exists.

**T4. Auto-colour a column by category** (Dan). Pick a column, say "auto
colour", and every distinct value takes its own colour from a palette —
text or fill, palette chosen. The point is that nothing is named in
advance, which is exactly what a rule map (T2) cannot do. The palettes
exist already on `Visual Style` and `Plotly Style`; the work is a rule that
resolves at evaluation time against the column's distinct values, in an
order stable enough that the colours do not move when a row arrives.

---

## U. The table on paper

Where the printed table is nearly the card and the gap shows. Lives in
`core/table_html.py` and `ui/report/render.py`.

**U2. A data bar on paper sits beside its number, and starts in a different
place on every row** (Dan). One cause, and the code says so: `_bar` puts
the value and the track in a two-cell nested table with the value cell
deliberately **content-sized**, because giving it a stated width made Qt
wrap `412` into three stacked digits. Content-sized means `1` and `10`
produce different-width cells, so the track's left edge moves down the
column — which is both the "bars start at different points" complaint and
the reason the column can no longer be read by length at all. Overlaying
the bar *behind* the text, as the card's delegate does, is not on offer:
Qt's rich text has no z-order and no partial-width background.

  Two ways out, and this wants deciding rather than guessing. Give the
  value cell a **measured** width — `fit_tables` already lays the document
  out for `height=` / `fit`, so a real width is obtainable now in a way it
  was not when `_bar` was written. Or let a bar column print as a
  **picture**, the way a web-view card already does. The first keeps the
  table as text; the second gets the card's exact look and gives up
  selectable numbers in that column.

---

## V. The table as a view

Show Table's own parameters (`nodes/viz/show_table.py`) and the inspector
view — how the table is *presented*, as against how its cells are painted.

**V1. Choose the columns to show, in the order you chose them** (Dan).
`Hide columns` and the `hide` rule are both subtractive: you say what to
lose. The other way round — pick what to keep, shown **in the order
picked** — is also the only way to reorder columns without a Select Columns
node upstream. Keep the two apart while building: hiding is a view thing
and the hidden column still leaves on `table`, so a chosen *order* has to
decide whether it reorders the passed-through frame as well. Probably not —
the card is a view, and Select Columns is the node that reorders data.

**V3. A hover tooltip on a table** (Dan). Left open in the ask, and worth
pinning before building, because there are two features under it. The
**full value where a cell is truncated** needs no configuration, could
simply be on, and is a `ToolTipRole` in `pandas_model.py` — half an hour.
A **tooltip from another column** — a note column that never shows but
explains the cell — is a rule (`revenue tip note`) and belongs with T1 and
T4 in the same DSL.

---

## W. Visual cards

**W2. The two Plotly visuals that don't filter when you click them.**
Clicking a visual to filter downstream is built and shipped — Show Plotly
has `On click` with a `selected` output and a filtered `table`, and so do
all nine library and drawn visuals. **Plotly Table** and **Gantt** are the
ones left out, and both are Plotly figures, so they can have it on exactly
the same terms. (Show Plot, Chart per Value, KPI Card and Mermaid are
static by nature — there is no click to catch.)

---

## X. Pivoting

**X1. A Matrix Table** (Dan) — a table that pivots inside itself, the way a
spreadsheet's pivot table does, instead of needing a Pivot node wired in
front of it. The arithmetic is already written (`nodes/transform/pivot.py`);
what is new is a card holding rows / columns / values / aggregation as its
**own** parameters, so the shape can be changed where you are looking at
the result. Decide first whether it is a new node or a **mode of Show
Table**: as a mode it inherits every conditional-formatting rule, which is
most of what makes the ask worth doing at all; as a node it stays simple
and the formatting arrives by wiring a style in.

---

## Elsewhere

- **Metanodes / subfolders / collapsible frames** (Stu, and a recurring
  ask). Already written up as `ideas_archived.md` #4, where it is parked as
  LARGE and undecided — decide it there rather than forking a second note.
  "A node that is its own flow" is the same ask; it lives there too.