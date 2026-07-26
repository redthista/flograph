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

- [x] Click **+** in the page bar → it now asks **Dashboard page** or
      **Report page**. Pick Report.
- [x] It opens with starter text explaining the `![[...]]` syntax, source
      on the left, live preview on the right.
- [x] Type markdown — headings, bold, lists, a table. Preview keeps up.

### Embedding

- [x] **Insert embed ▾** lists only nodes that have output. Pick one.
- [x] `![[Your Chart]]` → the chart appears as a picture.
- [x] `![[Your Table]]` → a real table. Try one with >30 rows: it should
      cut and *say* it cut.
- [ ] `![[Your KPI]]` mid-sentence → the number appears inline.
- [ ] **The programmatic one:** a Python Script node that returns a
      markdown string, embedded → it renders as real headings/bold, not as
      a quoted blob. This is the "build it from data" path — tell me if it
      doesn't feel usable.
      **FIXED 2026-07-26, needs a re-test.** Danny hit this with a
      triple-quoted string inside `run()` — it showed the raw text. Markdown
      was right: the literal carries Python's indentation on every line, and
      four leading spaces means *code block*. Danny worked around it by
      un-indenting, but the cause is invisible from the editor and everyone
      writing this path will meet it, so embedded strings are now dedented
      (`core.report.inline_markdown`). Relative indentation is kept, so
      nested lists and deliberate code blocks are unaffected. **Re-test with
      the string left indented, i.e. written the natural way.**
- [ ] `![[Node|port]]` picks a specific output port.
- [ ] Type `![[Nonsense]]` → a visible warning on the page *and* in the
      toolbar strip, not a silent gap.
- [ ] Re-run the flow with the report open → embeds update on their own.

### Exporting

- [x] **Export PDF…** → opens beside your project, named after the page.
- [x] Open the PDF: it should match the preview. Check the chart isn't
      clipped and tables aren't cut off at the right edge.
- [x] Export a report with a bad embed → it still exports, but warns you
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
- [ ] `![[Some Other Node]]` by label → **now works** (you asked for it
      2026-07-26). Check it resolves the same as it would on a page.
- [ ] Name a node the same as one of the card's inputs, e.g. call some node
      `b`, then `![[b]]` → you should get the **wired input**, not that node.
- [ ] Unwire input `c`, add a node called `c`, then `![[c]]` → it should say
      "nothing wired into c" rather than finding the node. Unplugging a wire
      mustn't silently change what a paragraph means.
- [ ] Sanity: `![[zzz]]` (neither an input nor a node) still complains.
- [ ] **Resize the card wider/narrower** → the chart resizes with it and
      never hangs off the edge.
- [ ] Drag the Report node onto a **dashboard page** → rich text on a
      dashboard, which we didn't have before.
- [ ] Fork it (Edit Code) and rename an input, e.g. `("summary", "any", …)`
      → `![[summary]]` should then work.
- [ ] Wire the Chart per Value node into a Report card → one embed, all
      the charts.
- [ ] **NEW 2026-07-26, Danny's request:** embed a Report card on a report
      **page** with `![[My Card]]` → you should see the card's *contents*
      (prose, charts, tables), not its source with `![[a]]` showing. Check
      that text *after* the embed still resolves against the page, and that
      `![[Some Page Node]]` written *inside* the card is refused — a card
      names its own inputs, and embedding it must not change that. A card
      wired into another card nests the same way.
- [ ] **Right-click inside the card's editor** (double-click the body
      first) → **Insert** submenu, above the normal cut/copy/paste.
- [ ] Its wired inputs come first; unwired ones are listed but greyed, so
      you can see `c` exists and has nothing in it.
- [ ] Then every node that has run, by label — duplicates greyed out, and
      the card itself never offered.
- [ ] Pick one → the embed lands on its own line, not glued to your prose.
- [ ] A **Note** card's editor has no Insert submenu (nothing to embed).
- [ ] Note: a Report tile **does** show STALE when its node is dirty. That's
      deliberate (its embeds come from upstream, unlike a Table tile) but it
      means a text-only edit shows STALE too. Tell me if that's annoying.

Also still worth doing from that round: **re-export a report PDF** and
compare a single chart against a stacked one, since the 300dpi change
(`PRINT_DPI`) landed after the last export was checked.

---

## Card ports: spacing + floating names (2026-07-26) — NOT YET TESTED

Committed? **not yet.**

You reported the Report card's four inputs "really bunched up". They were:
6px apart with an 11px pin, so each overlapped its neighbour by 5px.

### Spacing (a fix, no setting)

- [ ] Drop a **Viz > Report** node. Four distinct input pins down the left
      edge, a port apart, each one grabbable.
- [ ] Wire something into **c** specifically — you should be able to hit it
      first time.
- [ ] The **first pin sits in the header**, same place a one-port card puts
      it. Adding a second input shouldn't make the row jump into the body.
- [ ] A card with **one** port a side (Show Plot, Show Table) looks exactly
      as it always did.
- [ ] **Shrink a Report card** as small as it goes → the spacing holds; the
      pins do *not* squeeze up.
- [ ] Fork a card node and give it **~20 inputs** → the pins run past the
      bottom of the card onto the canvas, evenly spaced, none lost. (This is
      what the collapse toggle below is for.)
- [ ] Resize a card wider → the output pin rides the right edge, wires
      follow.

### Floating names (new)

- [ ] **Settings > Canvas > Show port names** → every port gets a small
      pill: input names to the left of the node, output names to the right.
- [ ] They should look like the **reroute label pill** — that was the
      reference. Tell me if they're too big, too small or the wrong colour.
- [ ] **Zoom out** until nodes flatten → the names go away with the pins.
- [ ] Turn the setting off again → they all disappear cleanly, no smears
      left behind on the canvas.

### Per-node override (your follow-up)

- [ ] Right-click a node → **Show Port Names** (with the setting off).
      Only that node gets them.
- [ ] Right-click it again → **Hide Port Names**, back to normal.
- [ ] With the setting **on**, right-click a node → **Hide Port Names**
      hides just that one.
- [ ] The important one: pin a node with the right-click, then flip the
      **global** setting. Every *other* node should follow the global; the
      one you pinned keeps what you gave it.
- [ ] `Ctrl+Z` after a toggle — one press.
- [ ] **Save, close, reopen** → per-node choices come back.
- [ ] Open an **older project** → every node follows the setting, nothing
      looks different from before.

### Collapsing ports (new)

- [ ] A multi-port card has a small **chevron in its header**, pointing
      down. Click it → every pin gathers into the header as one, and the
      wires all converge on it.
- [ ] Click again → they fan back out exactly where they were.
- [ ] Right-click also offers **Collapse Ports** / **Expand Ports**.
- [ ] Hover the collapsed pin → the tooltip says how many ports are hidden
      and which one a dropped wire would land on. Check that reads clearly;
      it's the one place this could mislead.
- [ ] Nothing disconnects — collapse a wired node, **run the flow**, and it
      behaves exactly as before.
- [ ] `Ctrl+Z` after collapsing — one press.
- [ ] Collapse a node, **zoom out** until nodes flatten, zoom back in → it
      should still be collapsed, not silently expanded.
- [ ] **Save, close, reopen** → collapsed nodes come back collapsed.
- [ ] A one-port card (Show Plot) has **no chevron** and no menu entry.
- [ ] An ordinary (non-card) node has none either.

### Round 2 fixes (2026-07-26, from your testing)

- [ ] **Pins float clear of the node** now, a few px off the edge rather
      than half-buried in it. Check it reads cleaner on a canvas with a few
      nodes wired up, and that wires still meet the pins tidily.
- [ ] A **reroute's** pins stay on its own centre line — the dot shouldn't
      look smeared.
- [ ] With port names on, **collapse a node** → the pill reads "4 inputs",
      not "a". That was the confusing bit you spotted.
- [ ] Expand it again → the names come back.

### Settings as a grid

- [ ] **Tools > Settings > Canvas** → all nine settings on one screen, no
      scrolling, grouped under Display / Snapping / Custom colour strength.
- [ ] **Hover a row** → the explanation that used to be printed under each
      control is now the tooltip. Tell me if you'd rather have that text
      visible somewhere; it's the one thing this trade away.
- [ ] General and Table Node pages the same shape.
- [ ] Drag the column divider — the Setting column should be resizable.
- [ ] Every control still works live: toggle snap, change the grid
      resolution, move the colour-strength spinners.
- [ ] **General > All settings > Reset…** → everything goes back to
      defaults *and* the open dialog updates to match.

### Settings round 2 (your feedback)

- [ ] The **left list is a tree**: each page's groups hang under it. Click
      **Canvas > Display** → the page shows *only* the display options.
- [ ] Click **Canvas** itself → all of its settings, ungrouped.
- [ ] Move between groups → no rows left over from the last one.
- [ ] There are **no heading rows** inside a page any more; the tree is the
      structure. Say if you miss them when viewing a whole page.
- [ ] **Tooltips wrap over several lines** now instead of one long one.
      Check the width reads comfortably (it's `TOOLTIP_WRAP`, currently 68
      characters).
- [ ] **Search box** above the tree. Type "minimap" → only that setting,
      and only Canvas left in the tree.
- [ ] Search "muted" → finds the colour-strength spinners, whose *names*
      don't contain it. Searching the explanation is the point.
- [ ] Search "snapping" → the group title matches too, so the whole section
      comes back.
- [ ] Search something with no matches → empty tree, no page left offering
      an empty grid.
- [ ] **Clear the box** → everything comes back exactly as it was.

### Resize crash (found in your session log, not by testing)

Pre-existing, not from this work — it reproduces on `723f5c3` too.

- [ ] Drop a **Scripting > Control Template** and **drag its corner** — it
      resizes, no error. (It now declares width/height; before, the drag
      raised `has no param 'width'` out of the mouse handler.)
- [ ] Fork a card node and *delete* its width/height params → that card
      shows no grip at all, rather than crashing when you drag it.
- [ ] Every other card — Show Plot, Show Table, Table, KPI, Slicer, Report,
      Note, a Slider — still resizes normally.

### Renaming a reroute

- [ ] **Double-click a reroute** → the rename box, not the code editor.
- [ ] Name it → the floating pill appears above the dot.
- [ ] Leave a reroute unnamed → still no pill, as before.

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
