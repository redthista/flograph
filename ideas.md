# Ideas

Grouped into chunks that are buildable in one go. Each chunk is meant to be
picked up whole: the pieces inside it touch the same code and share the same
decisions, so doing them together costs much less than doing them apart.

Old numbers are kept as "(was N)" — a couple of code comments still cite
them, and they have already drifted once. Status notes were checked against
the code on 2026-07-27.

---

## C. Recovering work  (was 3)

Deactivate, Lock and Freeze all shipped in 0.1.8 — `NodeInstance.active`,
`.locked` and `.frozen`, all three in the right-click menu. The three
questions the original Lock note asked are answered in code: a pin survives
save and reopen, it holds its cache against dirtying, and it contributes a
constant to the cache fingerprint so an edit above it does not invalidate
what is below.

What is left under this heading is unrelated to those:

**C4. Restore a crashed workflow from undo history** (was 3). Undo history
is in-memory only today, so this means persisting it somewhere durable —
worth a spike to size before it becomes a plan.

---

## D. Canvas at scale  (was 25)

**D1. Collapsible frames.** Collapse a frame down to a single node-sized box:
put the data inputs and tables in a frame, wire onward with gotos, collapse
it, and the canvas stays fast. Frames are already a first-class model object
(`core/graph.py`, `ui/canvas/frame_item.py`) with their own stacking order,
so the code is a display state plus a rule for what happens to wires that
cross the collapsed boundary — and that rule *is* the design question.

Already shipped in this area, for reference: per-node canvas previews can be
switched off (right-click a viz node), and zoom-out LOD flattening.

---

## E. Charts  (was 27)

**E1. Explicit Y bounds on the chart-per-value nodes.** Partly overtaken:
the "shared scale picks the tallest column rather than the tallest stack"
bug is fixed in both nodes — `_stacks()` bounds a stacked chart by the row
totals, so charts no longer grow past the sheet. What is still missing is a
manual override: `min_y` / `max_y` params to pin the axis to a chosen range
instead of a derived one.

## F. Optomisation
F1. add a setting and on by default when dragging around a canvas with middle mouse button and the fps drops below 60, then automatically change the nodes to the low lod versions, to avoid the slow down. 


## G. UX/UI
G1. a setting to enable draging the canvas by holding right click.
G2. when zoomed out and we have the low lod version of the nodes showing, can we layer the names of the nodes ontop?

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


## not sorted: 
- chart per value  - need scale option like with the other nodes.
- user forms, a simple form with submit buttons, one node? and retrieval? make work with dataframes sql anything else thats helpful. 
- table node, when selecting a column type bool, put checkbox into the column automatically. 
- optional git integreation for commits for the workflows. every save is a commit, so full config control.
- Node option - only run when called, by right click run or action button.
- search on canvas for node names
- can we look to add lines to from and goto nodes, so i right click a from or goto and have the option of show lines / hide lines. default false, just to make it easier to follow the connections.
- 