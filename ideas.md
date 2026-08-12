# Ideas

Grouped into chunks that are buildable in one go. Each chunk is meant to be
picked up whole: the pieces inside it touch the same code and share the same
decisions, so doing them together costs much less than doing them apart.

Old numbers are kept as "(was N)" — a couple of code comments still cite
them, and they have already drifted once. Status notes were checked against
the code on 2026-07-27.

---

## A. Reports — finish pass 1  (was 1)

Pass 1 shipped: the report page kind, `![[node]]` and `![[node|port]]`
embeds for figures / tables / scalars / markdown strings, a live preview,
and PDF export. Plotly figures render without kaleido as of 0.1.8.

A1 (page setup), A2 (running headers and footers) and A3 (forced page
breaks) shipped in 0.1.9 as one job, which is what they always were — all
three are page geometry and all three wanted the same settings surface.
That surface is `core/page_setup.py`, kept Qt-free and *not* expressed in
Qt's vocabulary, so chunk B reads the same dataclass instead of inventing a
second one; `page_css()` is already there and already tested.

What is left of A3 is the half Qt cannot do: **keeping a chart off a page
boundary** (`page-break-inside: avoid`). It is not a Qt job at all — it
belongs to chunk B and is listed there.

**A4. Per-embed sizing** shipped in 0.1.9 — `![[chart|width=50%]]` and
`width=280`. Alignment did not: centring an image means setting the
*block's* alignment after the document is built, which is a different job
from sizing and was not worth half-doing. Still open, and small.

**A10. Shrink a chart into the space left on the page.** The question that
produced A4: a heading, a paragraph and a chart, where the chart doesn't
fit in what's left and so starts a new page, leaving a gap. `width=` is the
manual answer; the automatic one is to notice the overflow and scale that
one image down.

Sketch, if it gets picked up: after `setHtml`, for each image block use
`documentLayout().blockBoundingRect()` to find its `y`, work out
`remaining = body_height - (y % body_height)`, and if the image is taller
than that but shorter than a whole page, scale it to fit and lay out again
(twice at most — it converges or it doesn't). The reason it is *not*
already done is that it makes charts silently different sizes on different
pages, which is worse than a gap unless it is asked for. So: opt-in per
embed, `![[chart|fit]]`, not a global.

**A11. Columns — text on the left, chart on the right.** Markdown has no
columns, but the renderer already lays a *list* of charts out on a grid by
emitting a small HTML table (`_Resolver.render_list`), and Qt's rich text
understands those, so the machinery exists. What is missing is a way to say
it in the body. Wants a syntax decision first — a fenced block (` ```columns `)
reads better than anything inline, and has somewhere to put widths.
Worth doing after B, where CSS grid does it properly and the Qt side would
be the fallback rather than the design.

**A5. A Report Text node**, so prose can be templated from data without
hand-writing a Python Script node each time.

**A6. Let a report page embed a report card.** Report cards exist (Viz >
Report, embeds its wired inputs, tileable on a dashboard); a page cannot
embed one yet.

**A7. Export headless** — every report in a project at once, from the CLI.

**A8. docx export?**

A4–A8 are small and independent — pick any subset in any order.

A9 (Export PDF / Open in Browser from a report *card's* context menu)
shipped in 0.1.9. It left behind `ui/report/html.py`, which writes a
rendered report as one self-contained HTML file with its pictures inlined
as data URIs — the asset-handling half of chunk B, done.

---

## B. Reports — HTML export via Jinja  (was 1, "BIG ONE")

Agreed 2026-07-26, to be done as its own pass. A **second** export target
alongside the PDF one, not a replacement.

Why it's worth it — things Qt's text layout simply cannot do:
- real CSS: `@page`, `@media print`, forced page breaks,
  `page-break-inside: avoid` (the A3 problem), running headers and footers
  with counters
- web fonts, flexbox/grid, proper design control
- Plotly stays **interactive** in the browser
- browser print-to-PDF beats Qt for anything designed

Shape:
- a Jinja template the user can replace, plus a code node that injects CSS
  (fits how the rest of flograph works)
- "Export HTML" and "Open in browser" buttons on a report page
- the embed resolver already produces the right intermediate (values keyed
  by ref); only the *rendering* forks
- asset handling: charts as embedded data URIs, so one file travels

Cost to be honest about: the in-app preview stops being exactly what you
get. Today the preview and the PDF are literally the same QTextDocument, so
they cannot disagree. With a browser round trip the preview becomes an
approximation, and "open in browser" becomes the real preview.

This is also where **keeping a chart off a page boundary** lives — the
half of A3 Qt has no answer for. In CSS it is one declaration
(`page-break-inside: avoid`); in Qt it is not expressible at all.

Groundwork already done: the HTML coercion lives in `core/html.py`
(Qt-free), and `ui/browser.py` writes a named page to a session temp dir
and hands it to the desktop. Both are tested. Two more pieces landed with
0.1.9, which shrinks this chunk again:

- `core/page_setup.py` — the geometry, Qt-free, with `page_css()` already
  emitting the `@page` rule. The settings surface does not need designing
  a second time; the template just has to read it.
- `ui/report/html.py` — a rendered report written out as one
  self-contained HTML file, charts inlined as data URIs (animations kept
  as the GIF/WebP they arrived as, so they still move). That is the asset
  handling this chunk listed as a task.

What is genuinely left is the *template*: Jinja, a stylesheet the user can
replace, `@media print`, running elements with counters, and keeping Plotly
interactive rather than snapshotting it.

**B1. A preview that can show either target.** Asked for on 2026-08-12,
after the first look at Save HTML: the HTML doesn't look like the PDF, so
the preview is only telling the truth about one of them. The shape is a
target dropdown on the report toolbar — *Pages* (today's paged preview,
what the PDF will be) and *Web* (a QWebEngineView of the exported HTML,
what a browser will be). The app already embeds Chromium (the Plotly
snapshotter uses it), so the view itself is cheap; what it needs is B's
template to exist, or it is a preview of a page nobody would ship.

0.1.9 narrowed the gap in the meantime rather than closing it: the exported
HTML now carries the page's own `@page` size and margins and measures its
body to the same text column, so it is at least the same shape and prints
sensibly from the browser. It is still one continuous page, not a stack of
sheets, and it always will be — that difference is the point of having two
targets.

One of the original arguments has since evaporated: "and it needs no
kaleido" was true when this was written, but 0.1.8 snapshots Plotly through
the embedded Chromium, so the PDF path needs no extra library either. The
CSS and pagination arguments stand on their own — this is just a smaller
win than it looked.

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
- on dashboard pages, sort viz pane items by node type, and then alpha, 