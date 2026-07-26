# Danny's testing to-do

Manual test passes waiting to be run in the app. Tick a line when it
behaves. Anything that misbehaves — note it under the item rather than
deleting it. Once a whole section is signed off and committed, delete it
and leave a one-liner under **Done and signed off**; the detail lives in
the commit message and the changelog, and a file of ticked boxes is a file
nobody reads.

---

## Report pages + PDF export (idea #1, pass 1) — NOT YET TESTED

Committed? **yes** — `871dc45`, on Danny's call that it is usable now and
will be improved after real-world testing. The unticked lines below are
still worth running; anything they turn up is a follow-up fix, not a
blocker.

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

## Report cards (the report-node idea) — NOT YET TESTED

Committed? **yes** — `871dc45`. The chart/grid half of that work is signed
off; these lines are what's left unrun.

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

Also still worth doing from that round: **re-export a report PDF** and
compare a single chart against a stacked one, since the 300dpi change
(`PRINT_DPI`) landed after the last export was checked.

---

## Known and parked

Not bugs to fix now — decisions we took knowingly, recorded so they aren't
rediscovered as surprises.

- **Charts render "larger in scale"** than before the 300dpi change.
  Consistent, so parked — revisit with per-embed sizing
  (`![[chart|width=50%]]`).
- **`width`/`height` params still dirty their node** like any other, unlike
  the layout params which are `cosmetic`. Same class of thing; left alone
  because changing it touches every card node.

---

## Done and signed off

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
