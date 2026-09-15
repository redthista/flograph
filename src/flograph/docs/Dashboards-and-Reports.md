# Dashboards and Reports

The model canvas is one surface. The same graph has two more: a **dashboard
page** for someone who will never open the model, and a **report page** that
prints to PDF. Both pull the same charts and numbers — no export step.

## Cards

Any node can declare `NODE["card"]` and become a live card on the canvas —
the node *is* the chart, not a preview elsewhere. Card kinds shipped today:
`figure`, `webview`, `table_viewer`, `kpi`, `grid`, `slicer`, `button`,
`note`, `control`, `report`, `pagelinks`.

## Dashboard pages

Click **+** on the page bar to add a dashboard page. Drag nodes onto it and
each becomes a **tile** — the same widget as the canvas card, resizable and
arrangeable, showing STALE when its node is dirty. Tiles maximise to
fullscreen; pages can be renamed, recoloured, reordered by dragging, and
duplicated.

**Give a tile a shape** from its right-click menu ▸ **Shape**: **Banner**
3:1, **Wide** 16:9, **Landscape** 4:3, **Square**, **Portrait** 3:4,
**Tall** 9:16 or **Column** 1:3 — a wide chart, or a long thin one. The tile
keeps its width and its height follows. From then on it *keeps* that shape:
drag any edge and the other side comes with it, until you pick **Any
Shape**. **Size and Shape…** takes numbers instead — a width and a height in
pixels, and a shape typed the way a report embed's `ratio=` takes one
(`16:9`, `4x3`, `1.5`). With several tiles selected, each choice applies to
all of them, which is the quick way to make three charts the same size.
Holding **Shift** while resizing a tile with no shape keeps the shape it
had.

**Format the page** from the **Format** pane down the right of a dashboard
page. The arrow at the page's right edge opens it, and so do right-click a
tile ▸ **Format…** and right-click the empty page ▸ **Format Page…**.
**Page** sets the page's **background** and the look *every* tile on it
takes:

* **Title** — shown or not, its text size, bold, alignment, text colour and
  the bar's colour (Transparent for a title with no bar under it).
* **Frame** — on or off, its colour and width, and the **corners**, from
  square to round.
* **Background** — the tile's **fill** (a colour, or Transparent so the
  page shows through), **padding** around its content, and a **shadow**.
* **Buttons** — whether the **maximize button** shows. Hidden, the tile
  can't be maximized at all (no double-click on its title either), so a
  finished page isn't blown up a tile at a time.

Select a tile and **Selected Visual** formats it on its own. Anything left
on *Page* follows the page, **Reset to the Page's Format** puts it back,
and **Title text** renames the tile without renaming its node. So a page
is set up once and only the exceptions change: frames off and a
transparent title bar for a clean look, a Note with a transparent fill and
no frame for a heading over a row of charts. A Note's words take the title's
text colour, so they can still be read on a light page. With several tiles
selected, a change applies to all of them. Buttons and Page Links draw their
own face and take no format.

A tile with no title bar still moves while the page is being arranged: a
grip appears along its top under the pointer, beside its maximize button,
and STALE shows in that corner. A frameless tile shows a faint dashed
edge only while the pointer is over it, so it can still be found without
the page being covered in boxes, and locking the page puts the Format pane
and its arrow away with the rest of the arranging tools. Every change is one
undo step, and copy, paste and Duplicate Page keep a tile's format.

**Find a visual** in the Visuals panel by typing in **Search visuals** — a
name, or a type (`slicer`); every word has to match. **All types** works like
a slicer: nothing ticked shows every type, and ticking types narrows the list
to them. The sort box orders the list **Name A–Z**, **Name Z–A** or by
**Type**, and **✕** clears the search and the type filter.

**Lock** a finished page from its tab menu and it *is* the dashboard: tiles
stop moving, the arranging chrome goes, and the page stops behaving like a
canvas (no zoom, wheel, panning, rubber band, or context menu). What still
works is everything inside the tiles — slicers filter, sliders move,
spreadsheets take typing, a PDF turns its pages, any tile maximises.

**Scale to fit the window** sits beside the lock: the page zooms as the
window resizes so the same tiles stay framed, for when a dashboard is opened
on a different screen than it was built on. Both settings travel with the
project.

## Getting around a dashboard

A dashboard handed to someone else shouldn't need its tab bar explaining.

**Page Links** (Util) is a strip of buttons, one per page — put one on each
page and it is the way between them. It reads the page list as it draws,
so a page added, renamed, moved or recoloured is on every strip at once.
Show **Every page**, **This page's group** (see below) or **Chosen pages**,
in a row or a column; the page it sits on is highlighted, and a page's tab
colour tints its button. A left-click always goes to the page, selected
or not. To move or resize it, drag it by the gaps between its buttons, or
right-click it for edit mode (a dashed outline) and drag; clicking anywhere
else ends edit mode. Action Buttons on a page work the same way: a
left-click always fires, and a right-click is how to move one.

**Action Button ▸ Go to page** is the same thing a button at a time, with
whatever label you give it. The page is picked from a list, and a rename
follows it.

**Notes go on pages too.** Drag a Note from the visuals list and its
Markdown sits on the page as text, with no title bar — a heading over a row
of charts, a line saying what a slicer is for. Its links open, even on a
locked page. Edit the words on the canvas or in Properties.

**A link can go to a page**, in any Note or report page:
`[See the costs](page:Costs)`. It finds the page by its title, whatever the
capitals; a title with spaces is written `page:Sales%20North`, or
`<page:Sales North>`. Because it goes by title, renaming the page breaks the
link — a Page Links card or a Go to page button follows a rename. In a
report it is clicked in the preview; on paper and in saved HTML it would go
nowhere, so there it prints as the plain words.

**Group the tabs** from a tab's right-click menu ▸ **Group**: pick a group,
or start a **New group…**, where you name it and can give it a colour. A
group's tabs sit together behind a header, with a line in the group's
colour under the run. Click the header to fold them away — the page you are
on stays showing — drag it to move the whole group, and right-click it to
rename it, **change its colour** or ungroup. **Drag a page's tab onto a
group's header, or in among its tabs, to put it in that group** — the header
lights up while you're over it — and drag one out past the group's end to
take it out. A group's colour is its own:
the pages keep theirs. Left on **Automatic**, a group takes the colour of
its first coloured page.
The tab list (right-click the tab bar's `<` `>` arrows) shows each group
under its own heading. The groups travel with the project; which are folded
is up to whoever is looking.

## Input controls

The other half of a dashboard: a node category you *set* rather than compute.
**Slider**, **Number**, **Text**, **Date**, **Toggle** and **Choice** each
carry a caption you write, are typed properly so wires still validate, and
re-run everything downstream when you change them. A control's options can
come from its own input ports — wire a column into a Choice node and its
dropdown is that column's values.

A **Slicer** picks values out of a column — or out of several. Name more than
one column and it becomes a **tree**: regions at the top, their stores
underneath, ticking a region for the whole region and one store to narrow to
it, with a part-filled box on a region only some of whose stores are ticked.
Its **Layout** setting draws the same selection three ways — a checkbox
**list**, **cards** you click, or a **dropdown** that folds the whole picker
behind one button saying what is picked — and **Show row counts** puts the
number of rows behind each value beside it.

A slicer on a page can also drop what it does not need: **Show search box**
and **Show All / None** take either row away, and turning off both leaves
just the values. **Accent colour** gives one slicer its own colour for
ticks, chosen tiles and the dropdown button, so a filter panel of three
reads at a glance; leave it on **Theme** to follow the app. None of these
re-runs the flow — they change the picture, not the filter.

A visual can be the filter too. Set a **Show Plotly** or a **Show Table** to
**On click ▸ select one** (or *select many*) and clicking it filters what it
feeds. On a chart you click a bar or drag a box. On a table you click a
**cell** to keep the rows with that value, a **row's number** to keep the
row, or **Ctrl+click a column header** to keep only that column. A plain
header click still sorts. Set the table's **Select** to *row* and a click
takes the whole row instead; with *select many*, a drag down the table
picks every row it covered. Wire the table's **filtered** output onwards, not
**table**, which stays whole so there is always every row to pick from.
Click the pick again, or press Esc, to let everything back through.

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
for extra render density on a fine-detail chart, `radius=14` to round the
picture's corners instead of leaving them square, and the bare word `fit` to
shrink a chart into the space left on the page instead of bumping it to the
next. The report toolbar's **?** button lists them all with examples.

`radius=` works on any embedded picture — a plotly chart, a matplotlib
figure, a printed web view — because it is applied to the picture rather
than to whatever drew it. The rounded corners are transparent, not white,
so they are still right on tinted paper. It is off by default: a report is
your document, and its pictures should not acquire a house style nobody
asked for.

A **table** takes the same options, each read the way a table means it:
`width=` places it, `rows=50` sets how many rows to show before the
"showing 30 of 4,000" note, `scale=0.8` sets the **text size** (smaller to
get a wide table in, larger for a headline figure — unlike a chart's
`scale`, it goes both ways), `height=200` is a **budget of page** that the
table shows as many rows as will fit inside, and `fit` trims it to the rows
that fit the room left on the page rather than letting it run over. What a
trim costs is never hidden: the table's own "showing N of M rows" says it.
`ratio=` is the one chart-only option — a table has no shape to be redrawn
at, being exactly as tall as its rows. It arrives
carrying whatever conditional formatting its **Show Table** card is showing:
colour scales, data bars, highlighted rows, icon sets, number formats and
hidden columns, re-grounded for white paper. The table stays real text, so
it can be selected in the PDF and can break across a page.

A **web view** — a Show Web View node, or any card that renders HTML —
arrives as a picture of the card, taken by the same browser the card draws
in, at the size the card is set to. The design comes with it: layout, CSS,
colours, web fonts. Resize the card to change how the HTML lays out;
`width=` places the result on the page.

### Web report preview

The report toolbar's **Preview** selector has two targets:

* **Pages** shows the PDF-faithful paginated document. It is the default and
  remains the right view for checking paper size, page breaks, covers and
  running headers or footers.
* **Web** shows the report as a continuously scrolling browser document. It
  uses the same HTML path as the saved HTML file, so browser CSS is applied
  as it will be outside flograph.

When **Web** is selected, a **CSS** tab appears beside the Markdown editor.
CSS is saved with the report page and applies to Web preview and saved HTML;
it does not change the Pages preview or PDF export. The CSS tab includes
starter themes (Clean, Editorial and Slate). Selecting **Insert** adds the
theme at the CSS cursor, so it can be combined with existing rules and edited.

Use **Save snippet...** to store the current stylesheet for reuse. Snippets
are kept in flograph's user data directory as `.css` files and appear in the
starter-theme picker on future report pages.

Plotly outputs in report pages currently remain static pictures, including in
Web preview. Interactive Plotly charts are available on Show Plotly cards;
interactive Plotly report embeds are planned for the browser-native export
target.

An embed written **inside code** — `![[Sales]]` in backticks, or in a
fenced block — is left exactly as typed. That is how a page explains its own
syntax to whoever reads it, rather than quietly turning the example into
the thing it was describing. A ```columns block is a layout, not code, so
embeds inside one still resolve.

**Open Example ▸ Report Visuals** is a worked flow of both: an HTML
dashboard and a formatted table, on the canvas and on the page.

The page prints to **PDF** at 300 dpi; the preview and the PDF are literally
the same document, so they cannot disagree. The report toolbar's **?** button
opens the full embed-syntax reference.

**Links work in the preview**, locked or not: a web or mail link opens in
the browser, and `[the costs](page:Costs)` goes to that page (see *Getting
around a dashboard*). Rest on one to see where it goes.

## Report card

**Viz ▸ Report** is the same Markdown but as a node *inside* the flow,
embedding its own wired inputs. It edits in place on the canvas, has a
right-click Insert menu listing everything embeddable, and tiles onto a
dashboard — rich prose on a dashboard, which a chart tile cannot do.

## Where is this used?

A page names the node it shows, but nothing on the node says which pages
show it. Right-click a node ▸ **Where Is This Used?** lists every place it
appears: each dashboard page that has it as a tile, each report page that
embeds it, and each report card on the canvas that does. Pick one and you
are taken there. A tile is selected on its page, a report page opens with
the embed selected in its source, and a report card is found on the
canvas.

**Used by no page** is an answer too, and on a board that has grown it is
usually the one you are looking for: the chart nobody removed when its page
was redesigned.

Report pages name nodes by *label*, so two nodes with the same name both
count as used by an embed of that name. The list says **shared with 1 other
node of this name** when that happens, because the page itself cannot tell
which of the two you meant. Rename one and the question goes away.

The same answer shows as a tooltip on each node's row in the **Navigator**.

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
