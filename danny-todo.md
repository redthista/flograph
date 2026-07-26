# Danny's testing to-do

Manual test passes waiting to be run in the app. Tick a line when it
behaves; strike a section through once the whole thing is signed off and
committed. Anything that misbehaves — note it under the item rather than
deleting it.

---

## Layers — bring to front / send to back (idea #15) — TESTED, GOOD

Committed? **no** — tested good 2026-07-26, ready to commit.

Right-click a node, frame or dashboard tile for a **Layer** submenu, or use
`Ctrl+]` / `Ctrl+[` (add `Shift` for all-the-way).

### Canvas

- [x] Overlap two big cards (Table, Plotly). Right-click the buried one →
      **Layer › Bring to Front**.
- [x] `Ctrl+]` / `Ctrl+[` step it one place at a time; `Ctrl+Shift+[`
      buries it completely.
- [x] Select **several** overlapping cards and bring them forward
      repeatedly — they keep their order relative to each other.
- [x] `Ctrl+Z` — one press undoes one action.
- [x] Overlap two **frames** and restack them. A node still draws over
      both; wires still draw over frames but under cards.
- [x] Select a **node and a frame together** → Bring to Front. Both rise
      among their own kind, as a single undo step.
- [x] `Ctrl+]` with nothing selected, or on something already at the
      front — does nothing at all, and adds no undo step.

### Dashboard

- [x] Overlap a KPI on a chart, right-click, restack. (Tiles had no
      right-click menu before this — that's new.)
- [x] **Maximize** a tile that is stacked *below* another — nothing shows
      through over it.

### Persistence

- [x] **Save, close, reopen** — the stacking comes back.
- [x] **Duplicate a page** with restacked tiles — the copy matches.
- [x] Open an **older project** — everything looks exactly as it did
      before.

---

## Missing library at the top of a node (idea #21) — TESTED, GOOD

Committed? **no** — tested good 2026-07-26, ready to commit.

Setup: fork any node (Edit Code) and put `import some_package_you_dont_have`
on the **first line**, above `NODE`. Save the project, close it.

- [x] **Reopen the project.** It opens. Before this it refused entirely.
- [x] The bad node shows an error naming the package and pointing at
      **Manage Packages…**; every other node is fine and still wired to it.
- [x] **Save it again and reopen** — the node's code, params, label,
      colour and description all survive the round trip.
- [x] Open **Edit Code** on the broken node — the code is still there.
- [x] Hit **Apply** without changing anything → same error, still broken.
- [x] Now change the import to something you *do* have (e.g. `import json`)
      and Apply → the node repairs itself, ports and label come back.
- [x] Sanity check: on a **healthy** node, Apply with no edits still says
      "No changes to apply."
- [x] Put the import **inside `run()`** instead, with a package you don't
      have, and run → only that node errors, and the message says to
      install it. The app keeps running.
- [x] Drop a `.py` with a bad top-level import into your **user nodes**
      folder and reload the library → status bar names the file *and* the
      reason; the rest of the library still loads.

---

## Report pages + PDF export (idea #1, pass 1) — NOT YET TESTED

Committed? **no** — waiting on this pass. This is the first go at a large
idea; expect gaps, and note anything that feels wrong.

Build a model with a chart, a table and a number first, and **run it** —
embeds only resolve for nodes that have produced something.

### Making one

- [ ] Click **+** in the page bar → it now asks **Dashboard page** or
      **Report page**. Pick Report.
- [ ] It opens with starter text explaining the `![[...]]` syntax, source
      on the left, live preview on the right.
- [ ] Type markdown — headings, bold, lists, a table. Preview keeps up.

### Embedding

- [ ] **Insert embed ▾** lists only nodes that have output. Pick one.
- [ ] `![[Your Chart]]` → the chart appears as a picture.
- [ ] `![[Your Table]]` → a real table. Try one with >30 rows: it should
      cut and *say* it cut.
- [ ] `![[Your KPI]]` mid-sentence → the number appears inline.
- [ ] **The programmatic one:** a Python Script node that returns a
      markdown string, embedded → it renders as real headings/bold, not as
      a quoted blob. This is the "build it from data" path — tell me if it
      doesn't feel usable.
- [ ] `![[Node|port]]` picks a specific output port.
- [ ] Type `![[Nonsense]]` → a visible warning on the page *and* in the
      toolbar strip, not a silent gap.
- [ ] Re-run the flow with the report open → embeds update on their own.

### Exporting

- [ ] **Export PDF…** → opens beside your project, named after the page.
- [ ] Open the PDF: it should match the preview. Check the chart isn't
      clipped and tables aren't cut off at the right edge.
- [ ] Export a report with a bad embed → it still exports, but warns you
      which ones didn't resolve.
- [ ] Try a **long** report (several charts) and check the page breaks —
      I expect this to be the weakest part of pass 1.

### Housekeeping

- [ ] Rename / recolour / reorder / duplicate a report tab (the copy
      should carry the text).
- [ ] Ctrl+Z while typing — bursts should undo in chunks, not per letter.
- [ ] Save, close, reopen — the report text comes back.
- [ ] With a report page open, change **Settings > Canvas** things (snap,
      LOD, colour strength) — nothing should error.
- [ ] Right-click a node → **Add to Page** should offer dashboards only.
- [ ] Open an older project — no report pages, everything as before.

---

## Chart per value + Report cards (idea #18, and your report-node idea) — NOT YET TESTED

Committed? **no** — waiting on this pass.

The underlying rule: **a node output that is a list renders as a stack**,
everywhere a single one would.

### One chart per value (#18)

- [ ] Drop **Viz > Chart per Value**, wire a table in, set "Split by" to a
      low-cardinality column, pick X and Y. Run.
- [x] The card shows one chart per value, **scrollable**.
      **BUG FOUND + FIXED 2026-07-26:** the canvas card showed only the
      "run to view" placeholder while the report embed of the same node
      worked. `_on_figure_node_succeeded` read a hardcoded "figure" port;
      Chart per Value emits "figures". It now reads the node's own first
      output, like every other card kind already did.
- [x] Scroll the stack with the **wheel over a chart**, not just the
      scrollbar.
      **BUG FOUND + FIXED 2026-07-26:** matplotlib canvases consume wheel
      ticks for their own zoom, so with the cursor over a chart — which is
      nearly always — the scroll area never saw them and only dragging the
      scrollbar worked. Stacked canvases now decline the wheel so it falls
      through. A lone chart still keeps its toolbar and pan/zoom.
- [x] "Same Y scale" on → all panels share a scale so they compare.
      Off → each scales to itself. *Danny: shared scale is exactly right,
      it replaces facetting and eye-comparison is the point. Keep it on by
      default. 40 max charts is fine.*
- [x] Set "Max charts" to 2 → it trims and says so in the log.
- [x] Drag the node onto a **dashboard page** → the stack scrolls there too.
- [x] **Plotly per Region** is now pre-built in 01-everything.flograph
      (bottom middle of the canvas). Run and check: one scrolling page, not
      three webviews, and it shouldn't feel slow. Verified headless: 3
      charts, one shared plotly.js, 4.65 MB instead of 13.9 MB.
- [x] Embed the same node in a **report page** with `![[Chart per Value]]`
      → all the charts appear in a row down the page. Export the PDF.
      **FIXED 2026-07-26 after Danny reported the single chart looked
      pixelated next to the stacked ones:** both were in fact at the same
      198dpi — a flat 2x up-scale, which is simply too low for print and
      shows most on a big chart with thin crossing lines. Charts are now
      scaled to a *target* 300dpi (PRINT_DPI) rather than a fixed
      multiplier, so every chart lands the same on paper whatever size it
      was authored at. **Re-export and check both.**

### Report cards (your idea)

- [ ] Drop **Viz > Report**. Wire a chart into input **a** and a KPI into
      **b**. Run.
- [ ] Write text using `![[a]]` and `![[b]]` → chart and number appear in
      the prose.
- [ ] `![[c]]` with nothing wired → says "nothing wired into c".
- [ ] `![[zzz]]` → says there's no such input.
- [ ] Try `![[Some Other Node]]` by label → **should NOT work**. That's
      deliberate; tell me if it feels wrong in practice.
- [ ] **Resize the card wider/narrower** → the chart resizes with it and
      never hangs off the edge.
- [ ] Drag the Report node onto a **dashboard page** → rich text on a
      dashboard, which we didn't have before.
- [ ] Fork it (Edit Code) and rename an input, e.g. `("summary", "any", …)`
      → `![[summary]]` should then work.
- [ ] Wire the Chart per Value node into a Report card → one embed, all
      the charts.
- [ ] Note: a Report tile **does** show STALE when its node is dirty. That's
      deliberate (its embeds come from upstream, unlike a Table tile) but it
      means a text-only edit shows STALE too. Tell me if that's annoying.

---

## Chart grid + inline report editing (2026-07-26) — TESTED, GOOD

Committed? **no** — tested good 2026-07-26, ready to commit.

### Grid: Columns / Rows / Fill

On **Chart per Value** and **Plotly per Region**; any node returning a list
can declare them.

- [x] Fill = down / across with both counts 0 → one column / one row.
      **BUG FIXED:** "across" still stacked top-down — with nothing else set
      the direction had no effect on the shape.
- [x] Columns N / Rows N constrain it into a grid.
- [x] An explicitly-sized grid **keeps its shape**, e.g. 2 cols x 3 rows
      with 3 charts leaves a blank row.
      **BUG FIXED (Danny spotted):** all three hosts only created rows that
      had something in them, so the grid silently collapsed and the charts
      were re-sized to a grid nobody asked for.
- [x] Changes apply **immediately**, no re-run.
      **BUG FIXED:** a param change evicted the cache, leaving nothing to
      re-lay out.
- [x] Layout params are `"cosmetic": True` — they don't dirty the node, so
      a slow split isn't re-run just to show it in two columns.
      **BUG FIXED (Danny spotted):** that broke report page/card/tile
      refresh, which all keyed off the run signal. *Cosmetic means don't
      recompute, not don't redraw.*
- [x] No torn strip on first draw.
      **BUG FIXED:** canvases were rasterised before the grid had sized
      them; a resize was fixing it.
- [x] Plotly charts fill the available height, and a 3rd chart no longer
      paints over the 1st.
      **BUG FIXED:** plotly sizes in pixels at init and spilled out of its
      cell; nothing clipped it.
- [x] Same layout on canvas card, dashboard tile, report page and PDF.

### Report card inline editing

- [x] Double-click the card body → markdown editor in place.
      **BUG FIXED:** did nothing — the rendered view sits in a proxy widget
      over the card and swallowed the double-click.
- [x] Commit / cancel / one undo step / header still renames.

### Still open from this round

- Charts render "larger in scale" than before the 300dpi change. Consistent,
  so parked — revisit with per-embed sizing (`![[chart|width=50%]]`).
- `width`/`height` params still dirty their node like any other. Same class
  of thing as the layout params; left alone because it touches every card
  node.

---

## Done and signed off

- ~~Linked Table keeps its contents when the input is disconnected, and
  resizing a populated linked card no longer blanks it (idea #8)~~ —
  tested, committed as `ca2542d`.
