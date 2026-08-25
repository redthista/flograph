# Ideas

Grouped into chunks that are buildable in one go. Each chunk is meant to be
picked up whole: the pieces inside it touch the same code and share the same
decisions, so doing them together costs much less than doing them apart.

Chunk letters are stable — an entry keeps its id for life so notes and
commit messages that cite one still point at something. Gaps (A, B, D, E)
are chunks that shipped or moved to `ideas_archived.md`; they are not
reused. Old numbers are kept as "(was N)" where a code comment still cites
them.

Undecided, deliberately-shelved ideas live in `ideas_archived.md`. Ideas for
*new nodes* live in `node_ideas.md`; only the ones asked for by name are
repeated here. Status notes were checked against the code on 2026-08-19.

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

**G1. Pan by holding right-click**, as a setting. Today
`BaseGraphicsView` pans on middle-drag and on space-drag only
(`base_view.py`); right-click is the context menu, so this needs a
press/drag threshold before the menu is given up.

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

**G3. Scroll the canvas when a connection is dragged to its edge** (Stu, from
KNIME). Wiring two nodes that are not on screen together currently means
letting go, panning, and starting again. Partly answered by Goto/From, but
only for the pairs a user thought to name in advance.

**G4. Drop a node onto a wire to splice it in** (Stu, from KNIME) — and
dropping one onto an existing node replaces it, keeping the connections.
Shipped 2026-08-25; see `ideas_archived.md` #9.

**G5. Click a node's name in the statistics window to jump to it** (Stu).
Debugging a slow flow currently means reading a name in one window and
hunting for it in another. The machinery is already written and reusable:
`ui/canvas/node_search.py` selects and centres a node as you move through
its results.

---

## H. Property panel — column pickers  (Stu)

Both entries are the same widget, `ParamsPanel._fill_columns_menu` /
`_make_columns_widget` in `ui/properties/params_panel.py`, so they are one
sitting.

**H1. Keep the columns menu open while ticking, and add select all / none.**
A `columns` param with `multi` builds checkable actions in a plain `QMenu`,
which closes on every pick — so choosing six columns means opening the menu
six times. Fix is to keep the menu up on a checkable action's trigger and
add two actions at the top.

**H2. Let Rename Columns list the columns it could rename.** Its `mapping`
param is a free-text `old = new` block with no idea what is upstream, so
renaming means flicking back and forth to a table view to copy names.
`upstream_columns()` is already what feeds the picker menu elsewhere;
Rename wants an insert-a-name affordance next to the text box.

---

## J. Running: what runs, and when

**J1. A node that only runs when asked.** Per-node "manual" flag: skipped by
Run All, run by right-click → Run or by an Action Button. This is the same
request from two directions ("only run when called", "don't fire on Run
All") and one flag answers both. Sits beside the existing `active` /
`locked` / `frozen` flags on `NodeInstance` and their right-click menu.

**J2. Disable a frame** — everything inside it stops updating and stops
being cached. The frame-level counterpart of J1, and the thing that makes a
big flow workable while you are editing one corner of it.

**J3. Start a second node while one is running** (Stu). Not an engine limit:
the scheduler already runs independent nodes on a pool. It is
`ExecutionEngine.run_targets` being "a no-op while a run is in flight"
(`engine/scheduler.py`), which the reactive path already works around —
`request_run` queues instead of dropping. The choice is whether a manual run
during a run should queue behind the current one (cheap, matches
`request_run`) or join it when the target shares no ancestry (what the user
is actually asking for, and where the cache-invalidation questions live).

---

## K. Saving, cache and disk

One chunk because all three are about the same failure: a big flow filling
or exhausting the disk without saying so.

**K1. Show progress while saving a long flow**, so the app does not look
hung. Node progress already has a plumbing path
(`engine.node_progress` → the status line); saving has none.

**K2. Warn before and when the disk runs out** — a notification when local
storage is running low, and a clear message when a save fails for want of
space rather than a silent or generic failure. Nothing in the codebase
checks free space today.

**K3. Compress the cache pickles.** Cache files are written raw; a
compression step trades CPU for disk on flows whose cache dwarfs their data.
Wants a measurement first — pick a real project, record cache size and warm
time, then decide the codec.

---

## L. Version control

**L1. Optional git integration for a project.** Every save is a commit, so a
workflow gets full configuration history: browse it, diff it, roll back.
Opt-in per project. Sits well with the `.flograph` file being plain JSON.

---

## M. Nodes asked for by name

The broader wishlist is `node_ideas.md`; these are the ones asked for
directly.

**M1. Concatenate with a user-defined number of inputs** (Stu). Today
`transform/concatenate.py` is fixed at two ports (`top`, `bottom`), so
stacking five tables is four nodes. Note the constraint learned on
2026-08-18: ports generated from data were built, worked, and were rejected
as against the grain — so this wants a fixed set of *optional* ports
(say 2 visible, up to 8 declared) rather than ports grown at run time.

**M2. User forms.** A form with fields and a submit button — one node, or a
node pair with a retrieval side — writing to a DataFrame, a SQL table, or
whatever else is useful. The Input category covers single values today;
this is the "capture a record" shape it cannot express.

---

## Elsewhere

- **Metanodes / subfolders / collapsible frames** (Stu, and a recurring
  ask). Already written up as `ideas_archived.md` #4, where it is parked as
  LARGE and undecided — decide it there rather than forking a second note.
