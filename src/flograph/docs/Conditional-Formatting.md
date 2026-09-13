# Conditional Formatting

A **Show Table** card paints itself from a plain-text list of rules — heatmaps,
data bars, traffic-light icons, highlighted cells and rows, per-column number
formats. Nothing is styled until you add a rule, and older projects open
exactly as they were.

Open **Show Table**'s Properties and write into the **Conditional formatting**
box, or press **Rules…** for a guided builder that reads and writes the same
text. The bundled **Open Example ▸ Conditional Formatting** flow shows every
rule type against one small table.

## The rule language

One rule per line. A blank line is skipped; `#` starts a comment — a whole
line, or trailing after a rule (`revenue scale green   # the money column`).
A rule is `columns  verb  argument`:

| verb | example | what it does |
| --- | --- | --- |
| `scale` | `revenue scale green` | 2- or 3-colour heatmap across the column's range |
| `bar` | `units bar blue` | in-cell data bar; a column with negatives splits from the centre |
| `icons` | `score icons traffic` | a 3-tier icon set (`traffic`, `arrows`, `check`), split at the column's thirds — add `reverse` to flip it |
| `iconmap` | `sla iconmap sla: ok=✓ green, breach=✗ red` | an icon per exact value; the glyph is any character or emoji |
| `… => bg / fg / bold` | `score >= 90 => bg green, bold` | highlight the cell when the test passes |
| `… => row <colour>` | `status = fail => row red` | highlight the whole row |
| `icon` (in a `=>`) | `20* = 1 => icon ✓ green` | place one icon where the test passes |
| `iconmap` | `20* iconmap: 1=✓ green` | map a value to an icon — leave the source out to read the column it draws in |
| `colormap` | `status colormap: fail=red, ok=green` | map a value to a fill; the ink is worked out unless you give one |
| `autocolour` | `status autocolour` | every distinct value takes its own colour — nothing named in advance |
| `format` | `amount format $,.0f` | a Python / d3 number format for the column |
| `hide` | `hide helper_col` | keep a column in the data (a rule can still read it) but out of the view |
| `show` | `show region, revenue` | only these columns, in the order named |
| `tooltip` | `revenue tooltip note` | resting on the cell shows the matching value from another column |
| `only` | `units bar blue only` | draw the format **instead of** the value — Power BI's "bar only" / "icon only" |
| `width` | `revenue width 160` | a fixed column width in pixels (`width auto` gives the column back to the content) |
| `align` | `region align right` | `left`, `right` or `centre` — the header follows the column |
| `label` | `revenue label "Revenue (£)"` | the header text to show; the real column name is what every rule, sort and export still uses |
| `wrap` | `wrap` | let long text run onto more lines, growing the rows — the one rule that takes no columns |
| `sort` | `revenue sort desc` | the order the table *opens* in — on the card, in a tile and on paper |

Tests for a highlight: `> < >= <= = !=`, `between 10 20`, `contains`,
`starts with`, `ends with`, `matches` (regex), `is empty`, `is not empty`.

Colours are a preset — `green` `red` `amber` `blue` `grey` `purple` — or a
`#hex`. Scale presets: `green` `blue` `red` `red-green` `red-yellow-green`
`green-yellow-red` `diverging`. In the **Rules…** builder every colour box is
a swatch menu with a **Custom…** entry that opens the system colour picker.

A column name with a space just works (`unit price scale green`). Wrap it in
`"quotes"` if it contains a comma or reads like a keyword.

An `iconmap` glyph can be an emoji — `sla iconmap sla: breach=🔥, ok=✅` — and
the app hunts down a font that can draw it, so the same rules look the same on
Windows, macOS and Linux. If one still shows as a blank space, the machine has
no emoji font at all: install one (Noto Color Emoji, or Twemoji) and reopen the
project.

## Shaping the table

The same rule list sets the table's *layout*, not just its colours:

```
region    width 90
region    align centre
revenue   width 200
revenue   label "Revenue (£)"
note      width 240
wrap
revenue   sort desc
```

A `width` is an instruction, not a hint: the column is set to it and the
content stops having a vote, which is what makes a data bar or an icon
column read properly. `width auto` hands the column back to the auto-fit —
useful for exempting one column from a pattern rule like `FY* width 120`.

`align` beats the column's own habit (numbers right, text left), and the
header moves with it. `label` changes only what is *printed* on the header:
rules, sorting, Ctrl+C and exports all still use the real column name, and
resting the cursor on the header shows it.

`wrap` is the one rule that names no columns. A row is as tall as its
tallest cell, so wrapping is a fact about the table however it is written —
pair it with a `width` on the column you want narrow. Rows grow as they are
scrolled into view, so it costs nothing on a long table.

`sort` names one column and a direction — `asc` / `desc` (or `up` / `down`,
or `a-z` / `z-a`) — and says what order the table is *first shown* in. Like
`wrap` it is a fact about the table rather than about a column, so a second
`sort` line replaces the first rather than adding a tie-break.

It is worth having as a rule rather than as a click because a click reaches
neither of the places that need it: a dashboard tile nobody clicks, and a
printed report, which has no header to click at all. Clicking a header
still wins on the card from then on — and the third click clears the sort
back to the table's own order rather than back to this one, because "clear"
means no sort. The default returns the next time the flow runs.

**Show Table** and **Table Style** both offer it as **Sort by** with a
**Direction**, which is the same rule written for you; where both are set,
the dropdown wins. The row order of the `table` **output** is untouched
either way — sorting here is presentation, and **Sort** is the node that
reorders data.

Layout rules travel the `style` port and print in reports like every other
rule, so a table set up once looks the same on the canvas, on a dashboard
page and in the PDF.

## Row height

Rows are as tall as a line of text unless a rule says otherwise. **`height`**
says otherwise, in two places:

```
height 40                                  # every row 40px tall
status = late    => row #3a1e1e, height 48 # the rows a test picks
score  >= 90     => height 56              # a cell rule works too
```

On a line of its own it is **every row** — taller to give sparklines room,
or shorter (`height 16`) for a compact table of numbers. After `=>` it is
**the rows the test picks**, and it does not matter whether the rule
highlights a cell or the whole row: a row is one height across the table,
so either way the row grows. Where both apply, the picked rows take their
own height. It is pixels on the card, from 12 to 600, and `40px` is read the
same as `40`.

Because a row is one height, **`revenue height 40` is not a rule** — it
reads like a column's height and cannot be one, so it says so and points at
the two spellings that work.

A row is never cut shorter than what it carries: a mark placed `above` or
`below` a value, or a `tall` sparkline, still gets its line. A **sparkline**
standing in a cell, or beside a value, grows to fill the height it is given
— which makes `height` the way to get bigger sparklines.

On a **report page** the rows come out the same height. Qt's rich text has
no row height to set, so each cell of a tall row is given the padding that
makes it that tall; the text sits at the top of the extra room.

## Showing the format instead of the value

Add **`only`** to a `scale`, `bar`, `icons` or `iconmap` rule and the cell
draws the format on its own — no number, no text:

```
status  iconmap only sla: breach=🔥, ok=✅   # the icon is the column
units   bar blue only                       # a bar chart down a column
score   scale green only                    # a plain heatmap block
```

The value is only hidden, never lost: the column still **sorts** on it,
**Ctrl+C** still copies it, and an export still writes it. It works at
either end of the rule (`bar only blue`, `bar blue only`), a `by` clause and
all — and a highlight takes it as a style word, so `score < 0 => bg red,
only` blanks the failing cells and leaves the rest alone.

## Sparklines

A **sparkline** is a row's numbers drawn as a chart the size of a word —
twelve months of sales as one line, in the row they belong to. The numbers
are read **across the row**, from the columns named after `from`:

```
trend    spark from jan..dec                 # every column from jan to dec
trend    spark from q1, q2, q3, q4           # these four, in this order
trend    spark from sales_*                  # every numeric column matching
```

A **range** (`jan..dec`) takes the columns between its two ends in the
table's order, both ends included — reversed if you write it right to left.
A **pattern** takes the numeric columns it matches and never the column
the spark is drawn in, so `sales_total spark from sales_*` reads the months
and not the total. Text columns a pattern or range happens to cross are
left out; a column you name outright is always read.

### Where it goes

The column on the left of `spark` is where it is drawn, and what happens
depends on whether the table has it.

**A column the table doesn't have becomes one.** `trend spark from
jan..dec` adds a `trend` column with the spark standing in it on its own.
The column holds the row's **latest number** underneath, so sorting it
sorts by the most recent value and copying it copies that number. Place it
with `show`, name it with `label`, size it with `width` — it is a column
like any other.

**A column the table has keeps its value, and the spark sits beside it** —
the way an icon does. That is how a region's name gets its trend right
next to it:

```
region   spark area teal from jan..dec          # left of the name
region   spark right from jan..dec              # after it
region   spark below tall from jan..dec         # on a line of its own
revenue  spark in from jan..dec                 # instead of the value
```

`left` is the default beside a value; `right`, `above`, `below` and `in`
work as they do for [icons](#showing-the-format-instead-of-the-value).
Name a place on a **new** column and its latest number shows beside the
spark.

### The columns it reads

Leave the months showing, or say otherwise at the end of the line:

```
trend    spark from jan..dec hide        # the months are hidden
trend    spark from jan..dec replace     # hidden, and trend goes where they were
```

Hidden is a view, like `hide`: the months are still in the table leaving
the card, and every other rule can still read them.

### How it's drawn

Everything goes between `spark` and `from`, in any order:

| Word | What it does |
| --- | --- |
| `line` `area` `step` `bars` `winloss` `dots` | The kind. `line` is the default. `bars` grow from zero, so a negative hangs below; `winloss` shows only up or down. |
| `blue` `green` `red` `amber` `orange` `yellow` `purple` `teal` `pink` `grey` `white`, or `#hex` | The colour. |
| `negative red` | The colour of a bar below zero. |
| `first` `last` `high` `low` `ends` `points` | Marks. A dot on that point — or, on bars, that bar coloured. Each can take a colour of its own: `high green low red`. `points` marks every value. |
| `ref mean` `ref median` `ref 100` | A dashed reference line. |
| `shared` | One scale for the whole column. Without it each row is scaled to its own numbers, which shows every row's **shape** as clearly as it can; with it the lines can be compared by **height** too. |
| `smooth` | A curve through the points. It never rises above the highest point or dips below the lowest — at this size the height *is* the number. |
| `thick` | A heavier line and bigger dots. |
| `tall` | Twice the height — the row grows to fit. |
| `90px` | A fixed width. Beside a value a spark is 64px; standing alone it takes the column's width. |

```
trend    spark bars green negative red ref 0 from m01..m12
region   spark area teal smooth last high green low red right from 2024-*
change   spark winloss from wk_* replace
```

A **blank is a gap**, never a zero — a month nobody reported is not a
month that sold nothing — and a row with fewer than two numbers draws
nothing. Resting on a spark that stands on its own says what it drew:
where it started, where it ended, and its high and low, each with the
column it came from.

A spark prints on a **report page** as a picture, in colours darkened
enough to read on white, and in **Open in Browser** and exported HTML too.
In a [matrix](#a-matrix-rules-before-and-after-the-pivot) the columns the
pivot made are there to read: `trend spark from *` over a matrix of months
draws each row's months.

**Open Example ▸ Table Sparklines** is a worked flow: sparklines in columns
of their own, beside a value, on their own scale and on a shared one, with
row heights — on the canvas, a dashboard page and a report page.

## Order of application

Rules compose **top to bottom, and a later line wins** any attribute it sets —
including a single-cell highlight beating an earlier whole-row one. So a
`=> bg green` line placed below a `=> row red` line turns that one cell green
on an otherwise-red row. Several rules can target the same column (a data bar
*and* an icon, say).

## Mapping a value

Three near-identical `=>` lines, one per value, is the long way round:

```
status    colormap: breach=red, watch=amber, ok=green
sla       iconmap: 1=✓ green, 0=✗ red
```

`colormap` fills the cell and picks readable ink for it; give a second
colour (`ok=green white`) to choose the ink yourself. `iconmap` places a
glyph. Both take `only` to draw the format *instead of* the value —
`status colormap only: fail=red` is a status block with no word in it.

**Leave the source column out** — nothing before the colon — and each
column the rule draws in reads *its own* value. That is the only spelling
that means anything under a [[#column-patterns|pattern]]: `20* iconmap:
1=✓ green` ticks each year column on its own numbers, where naming one
source column would paint that column's answer into all of them. Name a
source (`product colormap severity: high=red`) when the decision really
does come from somewhere else.

For a single flag rather than a whole map, a highlight can place an icon:

```
20*    = 1 => icon ✓ green
```

An icon goes in a cell, so it cannot be combined with `row` — name the
columns on the left instead.

## Colouring by category, with nothing named

A `colormap` has to be written out, so it can only colour values somebody
has already seen. When the point is that you *haven't* — a status column
from a system that invents new ones, a site list that grows — point
`autocolour` at the column instead:

```
status    autocolour                 # a lozenge each, from the default palette
owner     autocolour vivid           # one of the chart palettes
region    autocolour earth fill      # flood the cell instead
product   autocolour cool text       # colour the text and nothing else
product   autocolour by severity     # categories read from another column
```

Every distinct value in the column gets its own colour. The palettes are
the same ones `Visual Style` and `Plotly Style` offer — `mixed` (the
default), `cool`, `warm`, `vivid`, `earth`, `grey` — so a table
auto-coloured beside a chart of the same categories reads as one picture.

Three things worth knowing:

**The colours are handed out in sorted order**, not in the order the
values turn up. A new row arriving at the top would otherwise repaint the
whole column, and a colour you cannot learn is worth less than one nobody
picked. Add a category in the middle of the alphabet and only the ones
after it shift.

**A pill is the default**, because that is the shape a category wants: a
lozenge round each value, rather than a column flooded with one of eight
saturated chart colours. `fill` and `text` ask for the other two, and
`text` colours are lifted until they are readable against the card —
several palette colours are darker than the grid, since they were built to
be grounds with text on top rather than the text itself.

**More values than the palette has colours and it wraps.** That is honest
rather than good: a column of two hundred categories cannot be told apart
by colour whatever anyone does. If that is the column, it probably wants a
`scale` or a `sort`, not a colour per value.

## Deciding on another column

A `scale`, `bar` or `icons` rule can take its deciding value from a **different
column** with a trailing `by` (or `from`) clause. The style still lands in the
columns on the left; the named column's own min / max / thirds drive it:

```
product   scale green by revenue      # shade the Product label by its revenue
product   bar blue    by units        # bar length reads units, drawn in Product
product   icons traffic by score
```

A highlight tests another column with an `if` (or `when`) clause:

```
product   if revenue < 0   => bg red         # flag the Product cell
product   if status = closed => row grey      # whole row, tested on status
```

Name the helper column in a `hide` line to keep it out of the view.

## Choosing the columns, and their order

`hide` is subtractive — name what to lose. `show` is the other half: name
what to **keep**, and they appear **in the order you named them**.

```
hide sla                            # drop one helper column
show region, revenue, product       # only these three, in that order
show 20*                            # every year column and nothing else
show region, revenue
hide revenue                        # keep-list first, then hide from it
```

The order is the point as much as the choice is: a `show` line is the only
way to reorder a table's columns without a **Select Columns** node in front
of it. Name none of them — the usual case — and every column shows, in the
table's own order.

Both are a **view**. The frame leaving the card's `table` port is the one
that arrived, every column of it, in its original order, because a Show
Table is a way of *looking* at a table rather than a way of changing one.
Put a **Select Columns** node upstream when the data itself should change
shape.

Naming a column the table does not have is reported on the Show Table
rather than leaving a gap where it would have been.

## Column patterns

A column entry containing `*` or `?` is a glob that selects **every matching
column** (case-sensitive):

```
FY*        scale green        # every fiscal-year column, one rule
*_qty      bar blue
hide _tmp_*                   # every scratch column
```

A pattern that matches nothing is reported on the Show Table, next to the data.

## A note that explains a cell

Some numbers need a sentence, and giving that sentence a column of its own
makes the table worse. `tooltip` puts it on the cell instead:

```
revenue   tooltip note          # rest on a revenue cell, read the note
revenue   tip note              # the short spelling
revenue   tooltip by note       # the `by` clause, if that is the habit
```

Every row reads its own note. A blank note is no note — the cell says
nothing rather than showing an empty popup.

The note column **keeps showing** unless you also hide it:

```
revenue   tooltip note
hide note
```

That is deliberate. A note column usually is a helper, but `hide` already
says so out loud, and a rule that quietly removed a column it never
mentioned is the sort of kindness people then have to work out how to
undo.

On a **report page** the note becomes the cell's `title`, so it is there
when the page is opened in a browser or exported as HTML. On paper it
prints as nothing, which is the honest answer — paper has no hover.

If the column is genuinely a keyword to you — a table with a column
actually called `tip` — quote it: `"tip" scale green`.

## Reading a value that did not fit

A column is fitted to its content and then clamped, so a long value is cut
short with an ellipsis. Hover it and the whole value appears — no rule, no
setting, and only on the cells that were actually cut. A cell you can read
in full says nothing, because a tooltip on every cell is what stops anyone
reading the ones that matter.

It counts what the formatting took: a cell carrying a mark beside its value,
or wearing a lozenge, has less room for text and so is cut sooner. A cell
whose value has been *replaced* — `only`, or a decoration placed `in` —
offers nothing, since its value was not shortened, it was deliberately not
shown. A `wrap`ping table offers nothing either: wrapping exists so that
nothing is cut.

**A cell can have both** — a note, and a value too wide for its column.
There is one tooltip, so it shows both: the note first, because that is
the thing somebody deliberately wrote, then the full value quoted
underneath. Showing either alone would lose the other, and losing the
value would put the papercut back on exactly the cells someone cared
enough to annotate.

## A matrix: rules before and after the pivot

Set a Show Table's **Show as** to *matrix* and it pivots the table itself:
**Rows** down the side, **Columns** across the top, **Values** in the
cells, combined by **Aggregation**. No Pivot node in front of it, and every
rule still applies.

What makes it worth having is that a rule can read the rows **before** the
pivot. A table that used to need a checker column beside every value, only
there to feed an icon, becomes one long table and one line:

```
# metric | quarter | value | status | note        (one row per metric and quarter)
value   iconmap status: breach=✗ red, watch=! amber, ok=✓ green
value   tooltip note
value   if status = breach => bold
```

Each cell gets what its own rows decide. The column a rule reads (`status`,
`note`) doesn't need to be in the matrix, and isn't; it is carried along
with the values, hidden. Where several rows build one cell:

| rule | the cell gets |
| --- | --- |
| a highlight (`if status = breach`) | the style, if **any** of its rows passes |
| a map (`iconmap`, `colormap`) | the value **listed first** in the map — write the worst first |
| a note (`tooltip`) | every row's note, each once |
| `scale` / `bar` / `icons` `by` a column | that column, aggregated like the values |

A rule about the value alone — `value > 90 => bg green`, `value scale
green` — is about each **cell**, so it tests the aggregated number. A
`scale`, `bar` or icon set is then measured across the **whole matrix**,
the way a heatmap of a pivot is read, rather than one column at a time.
Rules naming the row columns (`region bold`) work as they always did.

Some things have nowhere to go in a matrix, and are left out with a note in
the log saying so: a rule drawing in a column the pivot used up (`status
colormap …` — carry it through the value instead), a `sort` or `label` on
the value (there is a column per quarter now), and `autocolour` by another
column, whose colours are picked per column and wouldn't agree across the
matrix. The table leaving the `table` port is the matrix, with the carried
columns in it.

## Sharing one look across tables

The rules a Show Table applies come out on its **style** output, and a Show
Table also *accepts* a **style** input — so one table's formatting wires
straight into another. The **Table Style** node (Viz) is a bare rules holder
with no data input, for a look shared across several tables. An incoming style
is the base; the receiving card's own rule box layers on top.

Errors — a bad line, a column the table lacks, a pattern that matches nothing —
are always reported on the **Show Table** that *applies* the style, never where
it was typed.

## Where it works

Conditional formatting applies to the **Show Table** card and to table tiles on
a [[Dashboards and Reports|dashboard]]. It is skipped above 200,000 rows (the
per-cell pass is Python-level and nobody heatmaps a million rows). The **Table**
grid and **Plotly Table** have their own, separate styling.

`sort` is the exception to the row cap: it is one vectorised sort rather
than a per-cell pass, so it still applies to a table too big to heatmap.
