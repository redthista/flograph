# Dashboards and Reports

The model canvas is one surface. The same graph has two more: a **dashboard
page** for someone who will never open the model, and a **report page** that
prints to PDF. Both pull the same charts and numbers — no export step.

## Cards

Any node can declare `NODE["card"]` and become a live card on the canvas —
the node *is* the chart, not a preview elsewhere. Card kinds shipped today:
`figure`, `webview`, `table_viewer`, `kpi`, `grid`, `slicer`, `button`,
`note`, `control`, `report`.

## Dashboard pages

Click **+** on the page bar to add a dashboard page. Drag nodes onto it and
each becomes a **tile** — the same widget as the canvas card, resizable and
arrangeable, showing STALE when its node is dirty. Tiles maximise to
fullscreen; pages can be renamed, recoloured, reordered by dragging, and
duplicated.

**Lock** a finished page from its tab menu and it *is* the dashboard: tiles
stop moving, the arranging chrome goes, and the page stops behaving like a
canvas (no zoom, wheel, panning, rubber band, or context menu). What still
works is everything inside the tiles — slicers filter, sliders move,
spreadsheets take typing, a PDF turns its pages, any tile maximises.

**Scale to fit the window** sits beside the lock: the page zooms as the
window resizes so the same tiles stay framed, for when a dashboard is opened
on a different screen than it was built on. Both settings travel with the
project.

## Input controls

The other half of a dashboard: a node category you *set* rather than compute.
**Slider**, **Number**, **Text**, **Date**, **Toggle** and **Choice** each
carry a caption you write, are typed properly so wires still validate, and
re-run everything downstream when you change them. A **Slicer** picks values
out of a column. A control's options can come from its own input ports — wire
a column into a Choice node and its dropdown is that column's values.

The result is a dashboard you hand to someone who never opens the model: they
turn the knobs, the charts answer. Controls often read a
[[Flow Variables|Variables]] value for their default.

## Report pages

The other page kind is a **report**: Markdown you write, with results dropped
in by name.

```markdown
# Q3 review

Revenue came to ![[Total Revenue]] across ![[Region Count]] regions.

![[Revenue by Region]]

![[Sales Table|filtered]]
```

`![[Label]]` embeds a node's output — a figure, a table, a scalar, a Markdown
string — resolved by node label; `![[Label|port]]` picks a specific output
port. Scalars render inline mid-sentence, charts and tables as blocks. Embeds
update when the flow re-runs and warn visibly when a name does not resolve.

A chart embed takes options after another `|`: `width=50%` or `width=280`
(points) for how wide it sits, `ratio=16:9` (or `4x3`, `1.5`) or `height=180`
for the shape it is *redrawn* at — labels and all, not stretched — `scale=2`
for extra render density on a fine-detail chart, and the bare word `fit` to
shrink a chart into the space left on the page instead of bumping it to the
next. The report toolbar's **?** button lists them all with examples.

A **table** takes `width=` too, plus `rows=50` for how many rows to show
before it is cut with a "showing 30 of 4,000" note — `ratio`, `height` and
`scale` are chart-only, since a table is laid out from its text. It arrives
carrying whatever conditional formatting its **Show Table** card is showing:
colour scales, data bars, highlighted rows, icon sets, number formats and
hidden columns, re-grounded for white paper. The table stays real text, so
it can be selected in the PDF and can break across a page.

A **web view** — a Show Web View node, or any card that renders HTML —
arrives as a picture of the card, taken by the same browser the card draws
in, at the size the card is set to. The design comes with it: layout, CSS,
colours, web fonts. Resize the card to change how the HTML lays out;
`width=` places the result on the page.

**Open Example ▸ Report Visuals** is a worked flow of both: an HTML
dashboard and a formatted table, on the canvas and on the page.

The page prints to **PDF** at 300 dpi; the preview and the PDF are literally
the same document, so they cannot disagree. The report toolbar's **?** button
opens the full embed-syntax reference.

## Report card

**Viz ▸ Report** is the same Markdown but as a node *inside* the flow,
embedding its own wired inputs. It edits in place on the canvas, has a
right-click Insert menu listing everything embeddable, and tiles onto a
dashboard — rich prose on a dashboard, which a chart tile cannot do.

## Markdown Wiki card

**Viz ▸ Markdown Wiki** shows a whole folder of `.md` files as a navigable
wiki — a nav tree, a breadcrumb, and wiki-style page links — on the canvas
and as a dashboard tile. Point its **Notes folder** at a directory of notes;
leave it blank and it shows this handbook. A `_Sidebar.md` in the folder — a
nested bullet list of page links — becomes the nav tree, the same as it
would on a GitHub wiki. Navigating is cosmetic — it never re-runs the flow.
Write your model's user guide once and it ships on the dashboard to whoever
opens it. Dropping a folder of `.md` files onto the canvas creates the node
for you.
