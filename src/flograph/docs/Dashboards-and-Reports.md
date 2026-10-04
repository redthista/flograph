# Dashboards and Reports

The model canvas is one surface. The same graph has two more: a **dashboard
page** for someone who will never open the model, and a **report page** that
prints to PDF. Both pull the same charts and numbers — no export step.

## Cards

Any node can declare `NODE["card"]` and become a live card on the canvas —
the node *is* the chart, not a preview elsewhere. Card kinds shipped today:
`figure`, `webview`, `table_viewer`, `kpi`, `grid`, `slicer`, `button`,
`note`, `control`, `report`, `pagelinks`.

### When a web card comes up blank

A `webview` card — a Plotly chart, a Sankey, a Wiki, an HTML template — is
drawn by Qt WebEngine, which is Chromium. Chromium fails quietly: a page
that will not load and a page whose renderer has been killed both leave a
blank rectangle that looks exactly like a node which produced nothing. The
card now says which happened instead, and a renderer that died is reloaded
once by itself, since one lost to a momentary squeeze comes back.

If a card stays blank and the message does not explain it, start flograph
with **`FLOGRAPH_WEB_LOG=1`** set and reproduce it:

```
Windows:    set FLOGRAPH_WEB_LOG=1 && flograph
Linux/Mac:  FLOGRAPH_WEB_LOG=1 flograph
```

Everything the engine says is written to **`web.log`**, beside the rest of
your flograph settings (Settings ▸ General says where that folder is). It
is off unless you ask for it, it records the engine and nothing about your
data, and each run notes its own process id — which matters when the thing
you are looking into is two copies of flograph open at once.

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

### A row of their own

On a project that has outgrown one strip, **Settings ▸ General ▸ Grouped
pages ▸ Put a group's pages on a second row** splits the bar in two. The
group headers keep the top row to themselves, alongside the pages in no
group, and the pages of whichever group you click appear on a row beneath
it. The top row then stays the same handful of names however many pages the
project grows.

**Every header is filled with its own colour** — a tone of it while the
group is closed, solid while it is open, sized snugly round its name like
any other tab. The chevrons are gone with them: there is nothing to fold
here, and which group you are in is something to see at a glance rather
than read off a small arrow.

The **Model** tab is a header like any other — it has headed the canvas
tabs since they arrived — so clicking it puts them on that row and fills in
the same way, and *only* that: the model canvas itself is the first entry
on the row, so you reach it by clicking it there, exactly as you reach any
other page. It reads **Models**, counting the model canvas among what it
heads.

**Drag a page along the row** to reorder it inside its group; the rest of
the bar stays where it is. The model canvas keeps the front of its row —
the other canvas tabs are views of it.

**Drag a page between the rows to change the group it is in.** The two rows
are what a page's group *is* in this mode — the top row is the pages in no
group, the row below is one group's — so dragging a tab from one to the
other is the plainest way to say where it belongs. Pull a loose page down
onto the row and it joins the group showing there, at the gap you drop it
in; drag one from the row up onto the bar and it leaves its group and takes
the place you put it, between two headers or after the last of them. The
target row marks the gap as you go, and the tab you are holding travels
with the pointer.

A page on the row **right-clicks to its own menu**, the same one its tab
has always had, and right-clicking moves nobody: the menu is about that
page, not a way of going to it. A group's header right-clicks to rename,
recolour or ungroup — with no fold, and no list of the pages the row is
already showing. And the switch itself is on those menus and on the empty
strip past the last tab, as **Pages on a second row**, so the bar can be
put back to one row from the bar rather than from Settings.

**One group is open at a time.** Opening another closes the first, because
two would only be a long strip again, and clicking the open one does
nothing — a header is a switch, and one of them is on.

**Go to a page in no group and the row goes away.** The top row is where
those pages live, so standing on one means there is no group being looked
at, and a row of some other group's pages would only be in the way. Click
any header to bring it back. A project with no groups at all never has a
second row, which is a different thing again: nothing to show rather than
something put away.

Everything else is where it was. A page on the second row right-clicks to
the same menu as its own tab, the header still drags to move the whole
group — sliding under the pointer as a tab does, over the groups it passes —
and right-clicks to rename, recolour or ungroup, and the page you are
on stays the page you are on when a group closes. Switching the setting off
puts every page back on the one strip, behind a header that folds.

### A model canvas in a group

A canvas tab can go in a group like any other page — **Group ▸** on its
right-click menu, or a drag onto a group's header on the one-row bar. File
the model that feeds the Sales pages under **Sales**, and it sits in that
section, folds away with it and rides its row.

The **Model** tab heads the canvas tabs no group has taken, and only those:
put your last one in a group and Model goes back to being a plain tab with
no chevron, no count and no row of its own. That is the rule throughout —
one header per tab. Take the canvas back out of the group and the Model tab
has it again, back in its run right behind the tab.

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

Branches need not all be the same length. A row that fills two of the four
columns is a two-level path, ending where its data does: `north > store A`
sits beside `south > store B > aisle 1 > shelf 3`, and ticking it keeps
everything under it. Where some rows have a value at a level and others do
not, the empty ones become their own **(blank)** branch you can tick on its
own, rather than disappearing into their parent.

A slicer on a page can also drop what it does not need: **Show search box**
and **Show All / None** take either row away, and turning off both leaves
just the values. **Accent colour** gives one slicer its own colour for
ticks, chosen tiles and the dropdown button, so a filter panel of three
reads at a glance; leave it on **Theme** to follow the app. None of these
re-runs the flow — they change the picture, not the filter.

When a table wants filtering on everything at once, a **Filter Page** saves
building a slicer per column. Wire the table in and every column arrives with
a control of its own: a searchable checklist for categories, a two-handled
slider for numbers, a from/to picker for dates, a *contains* box for anything
too varied to list. Its **filtered** output is the rows that match them all.
Leave columns out with **Exclude columns**, make a checklist pick one value
with **Single-select columns**, and set **Update mode** to *apply* if you
would rather make several changes and then press **Apply** than re-run on
each. What the page has picked shows in its **Filters** box, and clearing
that box clears every filter.

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

### Colour as you type

A report page's Markdown is coloured by what each part does: headings, an
embed's name (bold) and its options, `:::` blocks and their `==` tabs, code
spans and fences (a `columns` block is layout, so what is in it is
coloured as Markdown), links — a `page:` link in its own colour — lists,
quotes and front matter. An embed with a typo stands out because it isn't
coloured like one. The CSS tab is coloured as code: selectors (a `.class`
and a `:hover` picked out), property names and custom properties, numbers
with their units, `!important`, comments, strings, `@` rules, and every
`#hex`, `rgb()` and `hsl()` colour shown on a swatch of itself.
**Double-click a colour** — or right-click it for **Pick Colour…** — to
choose another in the colour dialog (transparency included); it is written
back the way it was written (a hex stays hex, `rgba(…)` stays `rgba(…)`),
and one Undo puts the old one back. The spelling check still runs
over the Markdown. Both follow the app's light or dark theme.

### Problems as you type

A report page's Markdown and CSS are checked as you write. A wavy line marks
what is wrong — **red** for what will go wrong on the page, **amber** for
what may not be what you meant — and resting the pointer on the line says
what. In the Markdown: an embed that names no node, or a port the node
hasn't got; an option nothing reads (`widht=50%`); a `![[` with no `]]`; a
`:::` block never closed, or of a kind there isn't (`::: warning`); `==`
outside a tabs block, or a tabs block with no tabs; a code fence never
closed; a columns block with one column; a link to a page that doesn't
exist; and front matter it can't read. In the CSS (in the Web preview,
where the CSS applies): braces, strings and comments never closed, a
declaration with no `:`, a missing `;` that runs two declarations into
one, and an `@import` or `url(https://…)` — a saved report fetches nothing,
so on a machine without internet those would simply not be there.

Everything wrong with the page — these, and what the preview finds, such as
a chart that hasn't run — is one row under the editor: a dot (red if
anything is an error), how many, and the first of them. Click it for the
whole list, and click a problem to go to its line. With nothing wrong, the
row isn't there. The starter themes and the examples are held to linting
clean, so a mark is worth reading.

### Web report preview

The report toolbar's **Preview** selector has two targets:

* **Web** shows the report as a continuously scrolling browser document —
  where a new report page opens. It uses the same HTML path as the saved
  HTML file, so browser CSS is applied as it will be outside flograph. It
  fills the width of the window, as the saved HTML does in a browser;
  printed from a browser, it goes back onto the page's paper and margins.
  **Web Layout ▾** on its toolbar sets a narrower reading column, a sidebar
  and a top bar — see *Web layout* below.
* **Pages** shows the PDF-faithful paginated document: the right view for
  checking paper size, page breaks, covers and running headers or footers.
  **Page Setup…** is on its toolbar; in Web it is at the bottom of Web
  Layout ▾, since paper only matters once the page is printed.

A page keeps the preview it was saved with, so a report saved on Pages
opens on Pages.

**Live**, beside the Preview selector, decides when the preview catches up
with your typing. On (the default), it follows the editor as you type. Off,
it waits: an **⟳ Update preview** button appears, lit when there is
something new to show, and **Ctrl+Enter** in the editor does the same.
Switch it off for a very large page, where every keystroke would otherwise
wait on a full re-render. Your text is still saved as you type, and a run
of the flow still refreshes the preview. The choice is saved with the page.

When **Web** is selected, a **CSS** tab appears beside the Markdown editor.
CSS is saved with the report page and applies to Web preview and saved HTML;
it does not change the Pages preview or PDF export. The CSS tab includes
starter themes (Clean, Editorial and Slate). Selecting **Insert** adds the
theme at the CSS cursor, so it can be combined with existing rules and edited.

Use **Save snippet...** to store the current stylesheet for reuse. Snippets
are kept in flograph's user data directory as `.css` files and appear in the
starter-theme picker on future report pages.

**Live charts and tables.** Add `|live` to an embed and, in Web preview and
in **Save HTML…** (and a Save Report node saving HTML), it becomes the real
thing. `![[Revenue|live]]` is the Plotly chart itself — hover for values,
zoom, pan, click the legend to hide a series. `![[Sales|live]]` is a browser
table:

* it carries every row (up to 5,000) and scrolls in a box `rows=` tall
  (`rows=12` for a short box), rather than stopping at "showing 30 of …"
  the way paper has to. `rows=all` drops the box: the whole table runs
  down the page — and on paper, prints every row rather than the first 30;
* the grand total stays in sight while the box scrolls — pinned under the
  headings, or to the bottom of the box, wherever the table puts it;
* click a column heading to sort by it, and again to reverse;
* a **grouped** table folds: click a group's row to close or open it, or
  use **Expand all** / **Collapse all** above the table. Groups start the
  way the table's `groups` rule says (open, closed, first);
* **column headings** fold too: click a heading over its columns to fold
  them to one — its stub, summary or kept column, as on the card — and
  again to open them. They start as the `heading` rule says, and
  **Expand all** / **Collapse all** fold columns and rows together;
* hover a cell for its column name and value;
* `![[Sales|search]]` is a live table with a search box over it — it
  filters the rows, opening any group with a match, and says how many rows
  it found.

A live chart's toolbar (it appears when you point at the chart) has a
**full screen** button at its right-hand end: the chart is redrawn to fill
the screen — or the preview, inside flograph — and **Esc** puts it back.

Live is opt-in, one embed at a time, so a report nobody has touched saves
the same HTML it always did. The page is one file with **nothing to fetch**
— no CDN, no web fonts, no folder beside it — so it opens the same on a
machine with no internet: the chart library is the one that ships with
plotly, written into the file once, and only when a chart on the page is
live.

**Maps work offline too.** A Plotly geo map (`scatter_geo`, `choropleth`)
is drawn on a file of country outlines, which plotly would fetch from its
CDN every time. flograph ships the standard outlines (every `geo.scope`, at
plotly's default `resolution` of 110) and puts the ones a map needs into
its page — on the card, in the report's picture, and live in a saved web
page — so a map draws with no network. The finer outlines for
`resolution=50` are a Web Library, **Plotly map outlines — fine detail**:
install it once from **Tools ▸ Web Libraries** (or from files, on a machine
that can't download) and it is used from then on. A map that needs outlines
that aren't installed says so in the report's problems rather than fetching
them. The one kind of map that cannot work offline is a **tile map**
(`scatter_map`, `density_map`, …): its street or satellite tiles come from
a tile server, so it stays the picture flograph drew, even with `|live`. The chart's
picture stays in the file too: it is what a mail client that runs no
scripts shows, and what the page prints, so a printed page matches the
PDF. The Pages preview and the PDF are unchanged by any of this.

Eight of the CSS tab's starter themes are made for live pages:

* **Compact** — dense, hairline rules, numbers that line up.
* **Dashboard** — every chart and table on a card; a quote becomes the
  headline insight.
* **Midnight** — a dark control room.
* **Ledger** — the financial broadsheet: warm paper, serif headings,
  tables ruled only above, below and under their headings (booktabs),
  totals underlined twice as an accountant would, figures in columns.
* **Terminal** — the trading desk: near-black, monospace, amber for what
  matters, a grid table where every figure has its own box, panel
  headings, a search box that is a `>` prompt, and a top bar of
  numbered function keys. The densest of them.
* **Aurora** — the showpiece: frosted-glass panels over a night sky of
  colour, gradient headings, a lit pill for the open tab, a glowing total
  row — with tables kept tight and high-contrast for reading numbers.
* **Studio** — Midnight's layout in Ledger's colours: every chart and
  table on a panel, small capital headings, dense tables, on warm paper
  with a teal accent. No gradients or glow — modern, simple and
  functional.
* **Swiss** — the International Typographic Style: white paper, black
  type and one signal red; heavy grotesk headings, every section numbered
  under a thick black rule, a quote set large as a pull quote, tables
  ruled in black with no fills, square corners and no shadows. On a phone
  the columns of a ```` ```columns ```` block stack.

They theme the live charts as well — a dark page gets dark charts, a map
loses its white ground — through variables any stylesheet can set:
`--fg-chart-paper`, `--fg-chart-plot`, `--fg-chart-ink`,
`--fg-chart-grid`, `--fg-chart-font`, and `--fg-chart-colors`, a comma
list that recolours the series: a colour the chart took from its palette
becomes the theme's colour in the same place, and one a chart set on
purpose is left alone. They also give every chart the same wide shape
(`--chart-shape`); delete that line to keep each chart's own.

#### Sections that fold, and tabs

Two blocks give a web page its shape. A **details** block is a section the
reader opens with a click — the method, the small print, the full table:

```text
::: details How this was worked out
Anything goes in here, embeds and columns too.
:::
```

`|open` after the title (`::: details Assumptions|open`) starts it open. A
**tabs** block shows one part at a time; `==` and a name starts each part:

```text
::: tabs Region
== North
![[North sales|live]]
== South
![[South sales|live]]
:::
```

Blocks nest, a block can hold a ```columns block, and a column can hold a
block. The tab block's name (*Region*) is optional — it is what the page's
address calls it. Type `:::` and a letter for the list. On **paper** — the
Pages preview, the PDF — there is nothing to click, so a section prints
whole under its title in bold, and every tab prints one after another under
its name. A live chart in a tab that isn't showing is drawn when the tab is
opened.

#### Web layout

**Web Layout ▾** on the Web preview's toolbar shapes the page around the
report, and is saved with it (each choice is one undo step):

* **Sidebar of headings** — the page's headings down the left, folding by
  branch and following the heading you are reading. *Shown*, or *Hidden
  behind a button* (☰) until the reader wants it; whoever reads it can
  open and close it, and their browser remembers. **Heading levels listed**
  is *Auto* — every level there is — or a depth from 1 to 6. On a narrow
  window it slides over the page.
* **Top bar of the top-level sections** — the page's title and its
  sections across the top, marking the one you are in. With the sidebar
  as well, **Only what is under the top bar's section** (in the Sidebar
  menu, on by default) splits the work the way a documentation site does:
  the bar lists the sections, and the sidebar lists only the one being
  read: its own heading first, so its page is always a click away, and
  the headings inside it beneath. On the opening page, which is in no
  section, it lists them all. **Drop-down of
  each section's headings** gives each section in the bar a menu of the
  headings inside it, indented by level (as deep as **Heading levels
  listed** says): point at the section, or click its ▾ on a touch screen.
  The section's name still goes to the section, and a section with nothing
  inside it stays a plain link.
* **Pages** — one page at a time, like a website, gone between from the
  top bar, the sidebar or both (so it needs one of them):
  * *One per top-level section* — a section and everything under it. A
    section is the biggest heading used more than once, so one `#` title
    over a `##` per region makes a page per region.
  * *One per heading* — every heading the sidebar lists is a page of its
    own: pick one and you see only what is under it, down to the next
    heading. A heading with nothing of its own lists the pages inside it.
    A heading inside a tab, a folding section or a column stays on the
    page it is part of.

  Anything above the first section — the title, an introduction — is the
  first page, reached from its entry in the sidebar or the title in the top
  bar, so a page you pick shows that page and nothing else. Tick
  **Previous / Next at the foot of each page** (in the same menu, off to
  start with) to end every page on **← Previous** and **Next →** links.
* **Text width** — **The theme's width** (the default: each starter theme
  holds its page to about 1,200 pixels, and with no theme it is the whole
  window), **The whole window** whatever the theme says, or a column held
  to 1400, 1100 or 820 pixels. The choice wins over the theme's own width.
* **Keep the view in the page address** (on) — the page, each tab not on its
  first part, each section opened or closed, and the heading being read
  are written into the address as the reader goes:
  `report.html#page=costs&tab.region=south&open=method&at=travel`. Copy
  the address and whoever opens it lands in the same place. A plain
  `#heading` link works too — every heading has an id made from its words
  — and opens whatever tab, section or page hides it. Going to another page
  of a paged site is a step the browser's **Back** button undoes.

Printed from the browser, everything prints: every tab, every page, every
section open, and no bars. A page with no blocks and the default layout
saves exactly the HTML it always did.

#### Title, heading and icon — and front matter

**Web Layout ▾ → Title, heading and icon…** sets what the browser's tab
(and a bookmark) calls the page, the name at the left of the top bar, and
the tab's icon — an emoji or a letter or two, drawn into the page itself,
so it needs no file and no network. Left empty, each is the page's title.

All of it — and every Web Layout setting — can also be written at the top
of the page's text as **front matter**, the block static-site generators
use, which wins over the menu:

```text
---
title: Q3 Sales Review
icon: 📊
heading: Sales review
sidebar: open
top bar: yes
pages: headings
width: reading
---
```

The words it takes: `title`, `heading`, `icon`; `sidebar` (open, closed,
off); `depth` (auto or 1–6); `top bar`, `menus`, `split`, `pager`,
`share` (yes / no); `pages` (off, sections, headings); `width` (theme,
full, wide, medium, reading, or a number of pixels — `full` is the whole
window over the theme's width). A value it cannot read is
ignored. The block is taken off before the page is drawn, so it never
shows — not on the web page, the Pages preview or the PDF. It only counts
when it is the very first thing on the page and every line in it is a
`name: value`, so a report that just starts with a rule keeps it.

Every starter theme in the CSS tab dresses the bars, tabs, sections and
drop-downs in its own way: **Compact** keeps them tight and hairline,
**Dashboard** makes them cards with a segmented tab control, **Midnight**
gives dark glass bars and lit tabs, **Editorial** turns a folding section
into a margin note with small-caps tabs, **Ledger** rules them like a
newspaper and opens sections with a plus, **Terminal** squares them off
with `[+]` sections and function-key sections, **Aurora** frosts them and
lights the open tab, **Studio** sets them on paper panels with a teal mark, and **Clean** and **Slate** tint them to match. A stylesheet of your own can set `--fg-accent`,
`--fg-nav-bg`, `--fg-nav-ink`, `--fg-nav-muted`, `--fg-nav-line`,
`--fg-nav-hover`, `--fg-nav-font`, `--fg-side-w` (the sidebar's width) and
`--fg-top-h` (the top bar's height, set on `html.fg-has-top`), or style
`.fg-side`, `.fg-top`, `.fg-tabbar`, `details.fg-details`, `.fg-drop` and
`.fg-pager` directly.

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

**The preview catches up; the editor never waits.** The preview redraws
when you pause typing, and on a page holding a lot of data that takes a
moment — so it is laid out in the background. Keep typing while it works;
a sliding stripe and **Updating preview…** over the preview show it is
behind, and the new pages appear
when they are ready.

**Links work in the preview**, locked or not: a web or mail link opens in
the browser, and `[the costs](page:Costs)` goes to that page (see *Getting
around a dashboard*). Rest on one to see where it goes.

**A report remembers how you were reading it.** Ctrl+wheel zooms the paper,
and the **▦** button lays the sheets left to right so several sit side by
side instead of stacking in one column — and both are saved with the page,
so it opens that way next time and for whoever you hand the file to. That
matters most on a **locked** page: locking takes the whole toolbar away, so
a report that did not remember this could never be *set up* to open two-up,
only left that way until it was closed. Spin the wheel as much as you like
— the whole spin undoes in one step.

### Saving a report from the flow

**Save HTML…** and **Export PDF…** save a report when you click them. To save
one every time the flow runs, add a **Save Report** node (IO) and choose the
page in its **Report** setting. It runs after every node the page embeds, so
the charts in the file are the ones this run drew. It runs again whenever one
of them changes, or the page's text does.

**If the report has errors** decides what happens when something on the
page is wrong: a chart that failed, one left over from an earlier run, or an
embed that names no node. **Don't save** (the default) fails the node and
says what was wrong, because the report would have a gap in it. **Save
anyway** writes the file with the gaps marked, and lists each one in the
node's log. It still saves when a chart fails in the same run.

**Save to** can hold `{page}`, `{date}`, `{time}` and `{datetime}`, as well
as `${name}` flow variables. For example, `reports/{page} {date}.pdf` keeps
one file a day. **If the file exists** can be set to Overwrite, Add a number
or Fail. The node's `path` output is the file it wrote, so you can wire it to
a node that sends or uploads the file. Tick **Output the HTML** and the `html`
output carries the web version as well, for either format. With that ticked,
**Save to** can be left empty and nothing is written to disk.

Reports are drawn by the window, so a headless run cannot save one. The node
fails there and says why.

## Report card

**Viz ▸ Report** is the same Markdown but as a node *inside* the flow,
embedding its own wired inputs. It edits in place on the canvas, has a
right-click Insert menu listing everything embeddable, and tiles onto a
dashboard — rich prose on a dashboard, which a chart tile cannot do.

## Spell check

A report page's source, a Report card and a **Note** underline words that
are not words while you write them, with corrections on a right-click.
There is nothing to install and nothing to download: flograph carries its
own dictionary, so it works on a machine that allows neither.

**Only while you are writing.** The marks live on the editor and nowhere
else — a locked page, the preview beside it, the printed PDF, the exported
HTML and a Note nobody is editing are never marked up. Nothing a reader
sees carries a squiggle.

**British by default.** Settings ▸ General ▸ Writing switches the
dictionary between **British (UK)** — which marks *color* and *organize* —
and **American (US)**, which marks *colour* and *organise*. Everything the
two share is the same list either way. The same page turns the check off.

**What it does not check.** An `![[embed]]`, a `[[wiki link]]`, a
`${variable}`, `inline code`, a fenced code block, a URL, an email
address, a file path and an HTML tag are all machinery rather than prose,
and are left alone — as is any word with a digit in it, so `col_2` and
`q1sales` are not typos. The CSS box on a report page is not prose either.

**Your own words.** Right-click an underlined word ▸ **Add “…” to my
dictionary** and it stops being marked, everywhere, at once. Those words
are **yours, not the project's** — the same column names, product names
and surnames follow you from one flow to the next, and a `.flograph` you
send somebody does not teach their spell check anything. They live in a
plain `dictionary.txt` beside the rest of your flograph settings, one
word per line. Settings ▸ General ▸ Writing ▸ **My dictionary ▸ Edit
words…** shows the list, says where the file is, and takes a pasted batch
of column names in one go.

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
