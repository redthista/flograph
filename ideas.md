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

**A1. Page setup.** Size, orientation, margins, and a cover page.

**A2. Running headers and footers.** Page numbers, title, date.

**A3. Pagination control.** Page breaks you can force, and keeping a chart
off a page boundary. Qt's weakest spot — see chunk B.

A1–A3 are really one job: all three are page geometry, all three have to be
understood by both the preview and the PDF writer, and all three want the
same settings surface. Doing them separately means building that surface
three times.

**A4. Per-embed sizing and alignment** — `![[chart|width=50%]]`. The embed
parser already splits on `|` for the port name, so the syntax has room.

**A5. A Report Text node**, so prose can be templated from data without
hand-writing a Python Script node each time.

**A6. Let a report page embed a report card.** Report cards exist (Viz >
Report, embeds its wired inputs, tileable on a dashboard); a page cannot
embed one yet.

**A7. Export headless** — every report in a project at once, from the CLI.

**A8. docx export?**

**A9. Export PDF / Open in Browser from a report *card's* context menu**
(was 21). A report *page* has toolbar buttons for this; a card has no
equivalent. `ui/browser.py` already does the "get HTML in front of the
user" half, so this is mostly wiring.

A4–A9 are small and independent — pick any subset in any order.

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

Groundwork already done: the HTML coercion lives in `core/html.py`
(Qt-free), and `ui/browser.py` writes a named page to a session temp dir
and hands it to the desktop. Both are tested.

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
G3. Show images on the canvas, dragged in or node with property, the usual enable disable etc. theres been a few cases where ive used an image in plotly charts, so to be able to add my own img input and then plug it in is good.
