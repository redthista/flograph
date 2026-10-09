# The Table Spreadsheet

The **Table** node (IO) is a spreadsheet you type into on the canvas. What you
type flows out as a table — numbers as numbers, dates as dates — and cells
that start with `=` are formulas. Drag the node onto a dashboard page and the
grid comes with it, still editable.

## The ribbon

Along the top of the grid is a ribbon, laid out like Excel's:

| Tab | What is on it |
| --- | --- |
| **Home** | Paste, cut, copy, *Paste Values*, *Paste Special*, *Copy + Headers*; Undo/Redo; Insert ▾ / Delete ▾ / Clear; Fill Down, Fill Right, Find & Select ▾, Replace |
| **Rows & Columns** | Insert above/below/left/right, Delete, Move up/down/left/right, select whole rows or columns, use a row as the column names, rename |
| **Data** | Filter, Sort A → Z / Z → A, Custom Sort…, Clear Filters; Conditional formatting and its rules; the Total Row; the column's **Type** ▾, its **Dropdown List**, **Text to Columns** and **Remove Duplicates**; **Validation** and **Next Problem** |
| **Review** | **New Note**, Delete Note, Next Note; Next Problem, select the problem cells or the cells with notes |
| **View** | Freeze ▾ (panes, top row, first column, unfreeze), fit column widths, Show Formulas, the full editor |
| **Formulas** | Insert Function ▾ (grouped Maths / Logic / Text), the function reference |

Hover any button for what it does, in a sentence, and its shortcut. Under the ribbon is the **formula bar**: the selected cell's name and what it holds as written (`=[@Units]*[@Price]`, not its result) — type there to edit it, or click **fx** for every function. **Open Full Editor…** is also on the right-click menu of the node and of every cell, row number and column header. On a
canvas card the ribbon is one line of icons to leave the grid room; in the
full editor (**View ▸ Full Editor**, or the card's expand button) and on a
wide dashboard tile each group has labelled buttons and its name underneath.
Double-click a tab to fold the ribbon down to its tabs; click a tab to open
it again.

## Right-click

Every part of the grid has its own menu, grouped under small headings:

- **a cell** — clipboard, insert/delete, clear, fill, sort and filter by this
  value, the column's type and dropdown list, find, freeze.
- **a row number** — insert above/below, delete, move up/down, clear, use the
  row as column names, freeze the top row.
- **a column header** — sort, filter, insert left/right, delete, move,
  rename, type, dropdown list, fit width, freeze the first column.

Right-click outside the selection and the selection moves there first, as in
Excel; inside it, the menu acts on all of it. The labels say how many: *Delete
3 Rows*.

## Selecting

Click a column header or a row number to select it; drag across headers, or
Shift/Ctrl-click, for several. A command acts on what is selected: select
three rows and **Insert Rows Above** adds three. With whole rows selected,
column commands mean the column of the current cell (and the other way
round), so selecting a row and inserting a column adds one column, not one per
cell.

### Find & Select

**Home ▸ Find & Select ▾** (or right-click a cell ▸ **Select**) picks cells
for you:

- **Go To…** (**Ctrl+G**) jumps to what you type — `B4`, a range `B2:D10`,
  whole columns `B:D`, whole rows `3:5`, a row number, or a column's name —
  or to a column picked from the list.
- **Go To Special…** selects every cell of one kind: formulas, constants
  (values typed in), blanks, errors, problem cells (the red ones), the
  *current region* (the block of data around the current cell) or the last
  cell with data. Formulas and constants can be narrowed to numbers, text,
  TRUE/FALSE or errors.
- **Select Formulas / Constants / Blanks / Errors / Problem Cells** do the
  same in one click.

With more than one cell selected these look only inside the selection;
with one, at the whole table. Rows a filter hides are left out. A note by
the cell says how many were found.

**Ctrl+Enter** puts what you have typed into *every* selected cell, as one
undo step, and stays where it is. Together with **Select Blanks** it fills
the gaps in a column in two steps: select the blanks, type `0` (or `n/a`,
or `=B2*2` — a formula shifts for each cell), press Ctrl+Enter.

## The fill handle

The selection has a blue outline with a small square at its bottom-right
corner. Drag the square down, up, left or right: a dashed outline shows where
the fill goes and a tooltip shows what lands in the last cell. Let go and it
fills, as one undo step, the way Excel does:

- **formulas** copy with their references shifted (`=A1*2` → `=A2*2`, …);
- **two or more numbers** carry on their step (1, 3 → 5, 7); a lone number
  is copied — hold **Ctrl** as you let go to count on by 1 instead;
- **dates** go on a day at a time, or by the step of the dates selected;
- **text ending in a number** counts on (`Item 1` → `Item 2`, `Q08` → `Q09`);
- **day and month names** carry on round the week or year (`Mon`, `Tue`, …);
- anything else repeats.

Drag past the last row or column and the table grows to take the fill. Near
the edge of the grid it scrolls. **Esc** cancels a fill mid-drag. With panes
frozen, the outline and the handle work on the frozen cells too: fill down
from a frozen column, or across out of it into the rest of the table.

## Dragging rows and columns

Select whole rows or columns (click their numbers or names), then drag one
of the selected headers. The pointer becomes a hand, a blue line — through
the header strip, with a marker at its end — shows where they will land, and they move there when you let go — still selected, so you
can drag again. Formulas keep their addresses, as after a sort. A drag that
starts on a header that isn't selected selects a range instead, as before.

## Holding edits until Submit

On a big flow, a Table near the start means every edit re-runs everything
after it. Turn off **Auto-apply** (the ⚡ button on the ribbon's tab strip, or
set **Apply edits** to *submit* in Properties) and edits are *held*:

- the flow keeps using the table as it was last submitted, and nothing is
  marked out of date;
- an amber strip under the ribbon says how many changes are waiting, with
  **Discard** and **Submit** beside it;
- **Submit** (**F9**, as Excel's *Calculate Now*) sends them in as one undo
  step and re-runs what depends on the table; **Discard** goes back to the
  submitted table (Undo brings the edits back).

Held edits are saved with the project and undo like any other edit. Running
the flow while edits are held says so in the status bar. Turning Auto-apply
back on submits whatever is waiting.

## Number formats

A column's format is how its values *read*, never what they are — the cell,
its formulas and what the Table sends on keep the full value, and the
formula bar and the cell editor show it as it is. Excel's rule, so a format
can be changed at any time without losing anything.

- **Home ▸ Number**: **Format ▾** lists General, Number, Currency, Percent,
  Scientific and the date styles, each with a sample; the quick buttons set
  Currency (in your computer's currency), Percent and Thousands, and show
  more or fewer decimal places.
- **Format Cells…** (**Ctrl+1**, or right-click ▸ Number Format): decimal
  places, the thousands separator, the currency symbol, how negatives look
  (`-1,234.10`, `(1,234.10)`, or either in red) and how dates are written,
  with a live sample taken from the column.
- A formatted column takes what its format looks like: type `£1,200` into a
  currency column and it stores 1200, `25%` into a percent column stores
  0.25, `(40)` stores -40.

Halves round away from zero, as in Excel: 2.5 at no decimals reads 3.

## The Total Row

**Data ▸ Total Row** (**Ctrl+Shift+T**) puts a row of totals under the grid,
as Excel's tables have. Each column chooses its own — **None, Sum, Average,
Median, Min, Max, Range, Count, Rows, Distinct, Std, Variance, First, Last,
Mode** — from **Data ▸ Total ▾**, the column header's right-click menu, or
by clicking the total itself. Turned on for the first time, the last
number column gets a Sum.

- With a filter on, a total counts only the rows the filter shows (Excel's
  SUBTOTAL), and its tooltip says so.
- A total in the column's units (a sum or average of money) is shown in the
  column's number format; a count is just a count.
- It is a view: the table the node sends on has no total row, and Show
  Table's own totals are unaffected.

## Conditional formatting

The Table uses **Show Table's rule system** — the same language, the same
**Rules…** builder, the same colour scales, data bars, icon sets and
highlights — so a rule written for one works in the other. See
[[Conditional Formatting]] for the full language.

- **Data ▸ Conditional ▾** (or right-click a cell or column header ▸
  Conditional Formatting) offers Excel's presets for the selected columns:
  **Colour Scale**, **Data Bar**, **Icon Set**, and **Highlight Cells**
  (greater than, less than, between, equal to, contains, blank…) with a
  fill, bold, or the whole row. Each preset adds one rule line.
- **Manage Rules…** lists every rule to add, edit, reorder and remove.
- The rules live in the node's **Conditional formatting** box in
  Properties, one per line — type them there directly if you prefer:

```
Units  scale red-yellow-green
Total  bar blue
Status = Late => row red
Band = High => bg green, bold
```

Rules only paint the grid: values, formulas and what the Table sends on are
untouched, and changing a rule re-runs nothing. Lower lines win where two
rules touch the same cell. Show Table's layout rules (widths, sorting,
totals) are left to Show Table — the grid has its own.

## Dropdown lists

**Data ▸ Dropdown List…** gives a column a list of values. The current cell of
that column shows a ▾: click it, or press **Alt+Down**, to pick from the list.
Typing still works. **Fill From Column** starts the list from the values
already there. Tick **Only allow values on the list** and anything else turns
red, like a word in a number column.

## Data validation

**Data ▸ Validation…** (or right-click a cell or a column header) says what a
column will take, as Excel's Data Validation does:

| Allow | For example |
|---|---|
| **Whole number** | between 1 and 100 |
| **Decimal number** | greater than 0 |
| **Date** | on or after `today`, between `today-7` and `today+7`, before 2027-01-01 |
| **Text length** | at most 10 characters, exactly 6 |
| **Any value** | no limit — for *Required* on its own, or just a hint |

- **Required** — a row with anything in it must fill this cell. Wholly
  empty rows are left alone.
- **Hint when selected** shows beside a cell of the column when you select
  it.
- **Error message** replaces the generated explanation.
- **When a value breaks the rule**: *Flag it red* keeps the value (it still
  flows on) and its tooltip says what is wrong; *Turn it away* sends a
  typed value back into the cell to fix, with the reason beside it — **Esc**
  leaves the cell as it was. Paste and fill are never turned away, as in
  Excel; what they bring in is flagged.

The foot of the dialog says the rule in words and how many cells already
break it. **Data ▸ Next Problem** steps through every red cell and formula
error, saying what is wrong with each. The rule only checks typed values,
never a formula's result — that is what conditional formatting is for.

## Notes

Right-click a cell ▸ **New Note…** (or **Shift+F2**, or **Review ▸ New
Note**) to write a note on it — why a figure is what it is, who to ask,
what still needs checking. A small red corner marks the cell; rest the
pointer on it to read the note. **Edit Note…** changes it, **Delete Note**
takes it off every selected cell, and **Next Note** steps through them all.
**Find & Select ▸ Select Notes** selects every cell that has one.

A note stays with its cell: sort the table, move or insert rows and
columns, and it goes where the cell goes; delete the row or column and the
note goes with it. Notes are saved with the table and undo like any edit.
They are for people — a note never changes the value and is not part of
what the Table sends on.

## Freeze panes

**View ▸ Freeze ▾**: *Freeze Panes* keeps the rows above and the columns left
of the selected cell in place; *Top Row* and *First Column* do the obvious.
The frozen part does not scroll at all — the rest scrolls beside it, so no
row is ever hidden underneath. The freeze is saved with the table.

## Sort and filter

Every column header has a ▾. It opens Excel's sort-and-filter box: sort the
table by the column, or tick the values to show (with how many rows hold
each, and a search box). A filtered column's ▾ turns blue. **Filtering only
hides rows in the grid** — the Table still sends every row on. To filter what
flows on, put a **Filter Rows** node after it. Sorting does reorder the table
itself (Undo puts it back).

### Sorting by several columns

**Data ▸ Custom Sort…** (also on a cell's and a column header's right-click
menu, and the ⇅ in the ▾ box) opens Excel's Sort dialog. Each line is a
*level*: **Sort by** Region, **then by** Total, **then by** Ordered. Rows
are put in order by the first level; where rows tie on it, the next level
decides, and so on down.

- The **Order** list speaks the column's type: *Smallest to Largest* for a
  number, *Oldest to Newest* for a date, *A to Z* for text.
- A column with a **dropdown list** can also sort in the list's own order —
  North, South, East, West rather than alphabetical (Excel's custom list).
  Values not on the list come after the listed ones.
- **Add Level** puts a new line under the selected one, **Copy Level**
  duplicates it, the arrows move it up (it then counts for more) or down.
- Blank cells always go last, whichever way round.
- The dialog remembers its levels for the next time it opens on that grid,
  and the whole sort is one undo step — **Undo Sort** works too.

### Splitting a column

**Data ▸ Text to Columns…** (or right-click ▸ Text to Columns…) splits the
current column into several, Excel's wizard in one dialog:

- **At a character** — comma, semicolon, tab, space, or your own under
  *Other* (a `|`, or ` - `). *Treat repeated separators as one* reads
  `Ann  Lee` as two parts, not three; *Keep "quoted, text" together* keeps
  `"Smith, Jr"` in one piece. The dialog picks the separator most rows
  contain to start with.
- **At fixed positions** — *Break after characters* `2, 6` turns
  `GB-LON-0042` into `GB`, `-LON`, `-0042`.

The new columns go to the right of the original. Unless *Keep the original
column* is ticked, the first part replaces it (the column becomes plain
text — its type, format, list and rule are cleared). *Names* takes the new
columns' names, separated by commas; the preview shows the first rows as
they will land. One undo step; formulas and notes move along with the
columns, and a formula's `[@Name]` follows a renamed column.

### Removing duplicates

**Data ▸ Remove Duplicates…** (or right-click ▸ Remove Duplicates…) takes
out rows that repeat an earlier one. Tick the columns that make two rows
"the same" — all of them, or just *Region* and *Item* — and the dialog says
how many rows will go and which. The first row of each set stays.

Rows are compared by what their cells show, ignoring case and spaces at
either end: `North` and `north ` match, and so do `2` and `2.0`. With a
filter on, only the rows shown are compared and removed. **Select Them**
selects the duplicates instead, to look at before anything goes. Removing
is one undo step; formulas and notes adjust as for any deleted row.

## Functions

About a hundred of Excel's functions, grouped on the ribbon's **Formulas ▸
Insert Function** list and in the **Function Reference**, each with what it
does and an example:

| Group | Functions |
| --- | --- |
| Maths | SUM, AVERAGE, MIN, MAX, COUNT, ROUND, ROUNDUP/ROUNDDOWN, INT, PRODUCT, SUMPRODUCT, MEDIAN, STDEV, LARGE/SMALL, RANK, LOG, … |
| Conditional | SUMIF(S), COUNTIF(S), AVERAGEIF(S), MAXIFS, MINIFS, COUNTBLANK |
| Lookup | VLOOKUP, XLOOKUP, HLOOKUP, INDEX, MATCH, CHOOSE |
| Logic | IF, IFS, SWITCH, IFERROR, IFNA, AND/OR/NOT/XOR, ISBLANK, ISNUMBER, ISERROR, … |
| Text | CONCAT, TEXTJOIN, SUBSTITUTE, FIND, SEARCH, REPLACE, TEXT, VALUE, PROPER, LEFT/MID/RIGHT, … |
| Date | TODAY, NOW, DATE, YEAR/MONTH/DAY, WEEKDAY, WEEKNUM, EDATE, EOMONTH, DAYS, DATEDIF, NETWORKDAYS |

Criteria work as in Excel: `5`, `"North"`, `">100"`, `"<>done"`, `"N*"`
(`*` and `?` are wildcards), `">=2026-01-01"`. As in Excel, VLOOKUP's
fourth argument defaults to an approximate match — put `FALSE` there for an
exact one, or use XLOOKUP, which is exact by default.

Dates are kept as text (`2026-10-07`) and do sums like Excel's: `=[@Due]+7`
is a week later, `=[@End]-[@Start]` the days between, and two dates compare
as dates whichever way they are written.

## Paste Special

**Home ▸ Paste Special…** (**Ctrl+Alt+V**, or right-click a cell) pastes
with choices, as Excel's dialog does:

- **Paste** — *Formulas and values* brings formulas along, adjusted to
  where they land (what plain Paste does); *Values only* brings what the
  copied cells showed. A copy from outside the app is only values.
- **Operation** — *Add*, *Subtract*, *Multiply* or *Divide* the copied
  numbers into the numbers already in the cells. To raise every price by
  10%: type `1.1` in a spare cell, copy it, select the prices, Multiply.
  One copied cell works across the whole selection. Text is left alone; a
  formula stays live (`=B2*C2` becomes `=(B2*C2)*1.1`); Add and Subtract
  move a date on by that many days; an empty cell counts as 0 for Add and
  Subtract and stays empty for Multiply and Divide.
- **Skip blanks** — where a copied cell is empty, keep what is under it.
- **Transpose** — the copied rows land as columns. **Paste Transposed** on
  the right-click menu does just this in one click.

A sentence says what the choices will do and a preview shows the first
cells as they will be, the changed ones highlighted (hover one for what it
was). The paste is one undo step.

## Formulas and moving things

Inserting or deleting rows and columns keeps formulas pointing at the same
cells, as Excel does: delete row 1 and `=A3` becomes `=A2`; a formula that
pointed into a deleted row shows `#REF!`. Column-name references
(`[@Price]`, `[Total]`) never need rewriting. Moving rows or columns, like
sorting, keeps formulas on their addresses.

**Show Formulas** (**Ctrl+`**) shows every cell's formula instead of its
result, for checking a sheet over.

### Big tables

A typed edit only works out again the formulas that depend on that cell, so
a table of tens of thousands of rows stays quick to type into. A column of
`SUMIF([Region], [@Region], [Total])`, `COUNTIF` or `VLOOKUP`/`XLOOKUP`/
`MATCH` with an exact match is worked out in a few passes over the column,
not one per row — 20,000 rows of SUMIF take under a second, where they took
fourteen.

## Keys

| Action | Key |
| --- | --- |
| Submit held edits | **F9** |
| Edit the cell | **F2**, or just type |
| Commit and move down / up | **Enter** / **Shift+Enter** |
| Clear the selected cells | **Del** |
| Fill down / right | **Ctrl+D** / **Ctrl+R** |
| Paste values only | **Ctrl+Shift+V** |
| Paste Special | **Ctrl+Alt+V** |
| Copy with headers | **Ctrl+Shift+C** |
| Select whole rows / columns | **Shift+Space** / **Ctrl+Space** |
| Insert / delete rows (columns when whole columns are selected) | **Ctrl++** / **Ctrl+-** |
| Move rows up/down, columns left/right | **Alt+Shift+arrows** |
| Jump to the edge of the data (Shift: select to it) | **Ctrl+arrows** |
| Find / replace | **Ctrl+F** / **Ctrl+H** |
| Go To | **Ctrl+G** |
| New or edit a note | **Shift+F2** |
| Type into every selected cell | **Ctrl+Enter** |
| Filter this column | **Ctrl+Shift+L** |
| Open a cell's dropdown list | **Alt+Down** |
| Format cells (number format) | **Ctrl+1** |
| Total Row on / off | **Ctrl+Shift+T** |
| Show formulas | **Ctrl+`** |

See also [[Nodes and the Library]] and [[Keyboard Shortcuts]].
