# Danny's testing to-do

Manual test passes waiting to be run in the app. Tick a line when it
behaves. Anything that misbehaves — note it under the item rather than
deleting it. Once a whole section is signed off and committed, delete it
and leave a one-liner under **Done and signed off**; the detail lives in
the commit message and the changelog, and a file of ticked boxes is a file
nobody reads.

---

## Report pages — what's left (idea #1, pass 1)

Committed as `871dc45`. The rest of that section is signed off; these are
the lines nobody has run.

### Embedding

- [ ] `![[Your KPI]]` mid-sentence → the number appears inline.
- [ ] `![[Node|port]]` picks a specific output port.
- [ ] Type `![[Nonsense]]` → a visible warning on the page *and* in the
      toolbar strip, not a silent gap.
- [ ] Re-run the flow with the report open → embeds update on their own.

### Exporting

- [ ] Try a **long** report (several charts) and check the page breaks —
      still the weakest part of pass 1, and the thing real use will hit
      first.
- [ ] **Re-export a PDF** and compare a single chart against a stacked one.
      The last time this was checked was *before* the 300dpi change
      (`PRINT_DPI`) landed, so the tick on it is stale.

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

## Report cards — what's left

Committed as `871dc45` and `7f5382a`. The label embeds, the Insert menu,
the nesting and the in-place editor are signed off; these are the original
card lines that were never run.

- [ ] Drop **Viz > Report**. Wire a chart into input **a** and a KPI into
      **b**. Run. Write text using `![[a]]` and `![[b]]` → chart and number
      appear in the prose.
- [ ] `![[c]]` with nothing wired → says "nothing wired into c".
- [ ] **Resize the card wider/narrower** → the chart resizes with it and
      never hangs off the edge.
- [ ] Drag the Report node onto a **dashboard page** → rich text on a
      dashboard, which we didn't have before.
- [ ] Fork it (Edit Code) and rename an input, e.g. `("summary", "any", …)`
      → `![[summary]]` should then work.
- [ ] Wire the Chart per Value node into a Report card → one embed, all the
      charts.
- [ ] A Report tile **does** show STALE when its node is dirty. That's
      deliberate (its embeds come from upstream, unlike a Table tile) but it
      means a text-only edit shows STALE too. Tell me if that's annoying.

---

## Known and parked

Not bugs to fix now — decisions taken knowingly, recorded so they aren't
rediscovered as surprises.

- **Charts render "larger in scale"** than before the 300dpi change.
  Consistent, so parked — revisit with per-embed sizing
  (`![[chart|width=50%]]`).
- **`width`/`height` params still dirty their node** like any other, unlike
  the layout params which are `cosmetic`. Same class of thing; left alone
  because changing it touches every card node.
- **A label embed on a report card is invisible to the scheduler.** It
  won't order the card after that node, and it doesn't show as a wire, so a
  partial run (Run To This Node) can leave one empty. Deliberate — wires
  stay the honest option — but it is the most likely thing to confuse
  later.

---

## Done and signed off

- ~~Report engine: dedented markdown embeds, a card's contents rendered on
  a page, naming any node by label, and the card editor's Insert menu~~ —
  signed off, `7f5382a`.
- ~~Settings as a two-column grid, with a nav tree and a search box~~ —
  signed off, `3172181`.
- ~~Card ports: spacing, floating names, collapsing, the reroute rename and
  the Control Template resize grip~~ — signed off, `f35feb2`.
- ~~Open in Browser for web-view nodes (idea #21)~~ — signed off, `36ce5fb`;
  folium maps confirmed working in a real browser too.
- ~~Chart grid (Columns / Rows / Fill) and inline report-card editing~~ —
  tested, `871dc45`.
- ~~One chart per value, and lists rendering as stacks (idea #18)~~ —
  tested, `871dc45`.
- ~~Surviving a missing library at the top of a node~~ — tested, `871dc45`.
- ~~Layers: bring to front / send to back (idea #15)~~ — tested, `871dc45`.
- ~~Linked Table keeps its contents when the input is disconnected, and
  resizing a populated linked card no longer blanks it (idea #8)~~ —
  tested, `ca2542d`.
