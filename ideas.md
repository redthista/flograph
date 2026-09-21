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
reused once its entry goes. Gaps (A, B, D, E, H, J, K, most of G, O, P,
Q, R, T, V, X, Y, Z, AA, AB and AC) are where shipped work used to be; AD
is the newest chunk, not a gap. Old numbers are kept
as "(was N)" where a code comment still cites them.

Undecided and declined ideas live in `ideas_archived.md` — also not a done
list. Ideas for *new nodes* live in `node_ideas.md`; only the ones asked for
by name are repeated here. Status notes were checked against the code on
2026-08-27; the entries added since (G10, N3, O1, S1) on 2026-08-30.
M3, M4, N6 and chunks T–X were triaged out of Dan's 0.1.13 list and
checked against the code on 2026-09-07 — of which T2, T3, U1, V2, W1,
X2 and the whole of Y shipped the same day and have left the list. Z1
was triaged here too and shipped from another branch, so Z retires
without ever having been listed. The raw 0.1.13 list itself was cleared on
2026-09-08: every one of its nineteen bullets is either shipped or carried
by an entry above — bar the cache bug, which is `issues.md` 8 because it
needs a repro before it is an idea. Chunk T shipped whole on 2026-09-08
and the letter retires with it: T1 gave a cell a *list* of decorations
with a place on each, and T4 then filled that list without anything being
named in advance. Chunk V shipped whole on 2026-09-08 and its
letter retires too: V1 gave a table a keep-list that fixes its column
order, and V3 gave a cell two ways to say more than fits — the whole of a
value that was cut short, and a note read from another column. N6
shipped on 2026-09-11: a node's right-click menu now says which pages show
it, and says so when none do. N3 shipped the same day: a dashboard tile
can be given a shape, and keeps it when it is resized. So did O1, and
chunk O retires with it: flograph opens on a start screen of favourite and
recent workflows. Dan's 0.1.14 list (`new_ideas.md`) was triaged here the
same day: its seventeen bullets are chunks AA–AC, G12, and additions to M3
and X1. The single letters are used up — I is skipped, it reads as a 1 —
so chunks carry on at AA. With every bullet carried here, the raw list
in `new_ideas.md` was cleared, ready for the next one. Chunk AA shipped
whole the same day and its
letter retires with it: eight papercuts, from a plain canvas by default
to the start screen's "edited" note on the name's line. Chunk AB shipped
whole the same day and retires too: a Page Links card, an Action Button
that goes to a page, Notes on dashboard pages and sections in the tab bar.
The one piece of it left over, N7, shipped the same day: a `page:` link
works in a *report* page's preview as well as in a Note. Chunk AC shipped
whole the same day and retires too: a package index of your own that pip
and uv both install from, and a list of what a flow needs installed. So
did chunk X, which retires with it: Show Table pivots into a matrix
itself, and its rules can read the rows before the pivot. G12 shipped
2026-09-12, and grew in the doing: a frame opens in a tab of its own,
and the page bar's **+** also adds a whole canvas of its own, with its
own nodes. G13 shipped 2026-09-12 too, and closes the chunk's newest
idea: a frame turns into a model canvas — a node-like box with inputs and
outputs you declare — and turns back again, and the canvas tabs fold
under the Model tab that heads them. What is left of G is the three old
entries, G1, G2 and G10. W2 shipped 2026-09-12 and chunk W retires with it: Plotly Table and
Gantt Chart filter when clicked, like every other visual that can. N5 shipped
2026-09-13: a deep slicer tree opens and shuts in one go, and arrives
opened as far as its node says. U2 shipped the same day and
chunk U retires with it: on paper, every data bar in a column starts at
the same place.

Dan's 0.1.15 list was worked through on 2026-09-18 to 2026-09-20. Ten of
its eighteen bullets shipped — the conditional-formatting rule round trip,
tooltip wrapping, icon alignment, a full-screen pop-out editor, a group
colour that stops drifting, **New ▸** on the tab bar, the frame nudge
taken out, the zoom-out drift, the bar's folds and each canvas tab's place
saved with the project, the drag that unfolded the canvases, and dropdowns
on cards opening in front and in the right place. What is *not* built from
that list is carried here: **AD** is its second row of tabs, and the rest
of it — wildcards in value rules, ragged slicer trees, a spell checker, and
two apps sharing one Plotly — is still on `0.1.15_issues.md` waiting its
turn rather than being restated here twice.

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

  Measured 2026-09-12, and the rebuild is not it. Offscreen on Linux,
  `popup_at` through show and first paint takes ~2 ms (8 ms the first time),
  `_refresh` 0.7 ms for today's 118 rows, `registry.search("")` 0.01 ms;
  `Favorites.contains` is a list lookup and `spec_icon` is cached. So the
  cost is on the Windows side, and the one Windows-only thing in the path is
  `ui/win_frame.py`: its Aero Snap filter is installed on the
  **QApplication**, so every native message in the process — the popup's
  creation, paint and mouse moves included — is handed to Python, which
  calls `isVisible()` and `winId()` before checking whether the message is
  for the main window at all. Issue 7 is what an application-wide Python
  filter costs. Cheap to tighten (cache the hwnd and compare it first, or
  move to `MainWindow.nativeEvent`), but it landed 2026-09-02 and this was
  filed 2026-08-30, so it can make it worse, not explain it. Next step is a
  timing on the slow machine itself.

  Tightened 2026-09-13, unmeasured: the filter now reads the HWND off the
  message pointer and compares it with the handle `_apply_styles`
  remembers, so a message for any other window — the palette popup's
  included — is turned away before a MSG is built or Qt is called
  (`tests/test_win_frame.py` pins that no Qt call happens). Whether that
  was the slowness is still for the slow machine to say; leave this entry
  until it has.

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

  Dan's 0.1.14 note adds the cheaper half, which may be the half to build
  first: take the table from the child file's **saved cache** when it has
  one, and run the child only when it does not (or when asked). A
  `.flograph` is a zip carrying its cache (`core/container.py`), one blob
  per node keyed in `cache/manifest.json`, so reading one node's output is
  a file read with no engine at all — the question is only what to do when
  the cached entry is stale against the child's own graph.

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

## AD. A second row of tabs

**AD1. What a second row could still replace** (Dan, 0.1.15). The row
itself shipped in 0.1.15 as a setting: headers and loose pages on the top
row, the open group's pages beneath, the Model tab heading its canvases the
same way. That was deliberately the *layout* answer — it changed where a
tab is drawn and nothing else. What it did not settle:

  - **Whether the fold survives it.** With the row on, a group's pages are
    never on the top strip, so `_folded` is only what the one-row mode
    uses. Two ways of tidying the same bar, and a project saves the fold.
  - **Whether a page can be under more than one header.** Today
    `Page.group` is one name, so the top row is an index, not a filter.
    A filter is a model change and much larger.
  - **Per-row New ▸.** The `+` deliberately stayed on the top row: it
    means *add a page*, and which row it lands on is the group's business.
    Whether a row wants its own is open.

  Settled since: a page moves between the rows by being dragged between
  them (the rows are what a group *is* in this mode), a canvas tab can be
  put in a group like any other page — the Model tab heads only the ones
  no group has taken — and **Pages on a second row** is on the bar's own
  menus, so the two rows collapse to one without going through Settings.

  What helps, unchanged: the ordering maths is Qt-free and separate
  (`core/page_nav.py` — `gather_groups`, `order_after_regroup`), and
  `Page.group`, `page_group_colors` and the saved fold state are all
  already in the file format.

---

## Elsewhere

- **Metanodes / subfolders / collapsible frames** (Stu, and a recurring
  ask). Already written up as `ideas_archived.md` #4, where it is parked as
  LARGE and undecided — decide it there rather than forking a second note.
  "A node that is its own flow" is the same ask; it lives there too.
