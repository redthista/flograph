# The Table Spreadsheet

The **Table** node (IO) is a spreadsheet you type into on the canvas. What you
type flows out as a table — numbers as numbers, dates as dates — and cells
that start with `=` are formulas. Drag the node onto a dashboard page and the
grid comes with it, still editable.

## The ribbon

Along the top of the grid is a ribbon, laid out like Excel's:

| Tab | What is on it |
| --- | --- |
| **Home** | Paste, cut, copy, *Paste Values*, *Copy + Headers*; Undo/Redo; Insert ▾ / Delete ▾ / Clear; Fill Down, Fill Right, Find, Replace |
| **Rows & Columns** | Insert above/below/left/right, Delete, Move up/down/left/right, select whole rows or columns, use a row as the column names, rename |
| **Data** | Filter, Sort A → Z / Z → A, Clear Filters; the column's **Type** ▾ and its **Dropdown List** |
| **View** | Freeze ▾ (panes, top row, first column, unfreeze), fit column widths, Show Formulas, the full editor |
| **Formulas** | Insert Function ▾ (grouped Maths / Logic / Text), the function reference |

Hover any button for what it does, in a sentence, and its shortcut. On a
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

## Dropdown lists

**Data ▸ Dropdown List…** gives a column a list of values. The current cell of
that column shows a ▾: click it, or press **Alt+Down**, to pick from the list.
Typing still works. **Fill From Column** starts the list from the values
already there. Tick **Only allow values on the list** and anything else turns
red, like a word in a number column.

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

## Formulas and moving things

Inserting or deleting rows and columns keeps formulas pointing at the same
cells, as Excel does: delete row 1 and `=A3` becomes `=A2`; a formula that
pointed into a deleted row shows `#REF!`. Column-name references
(`[@Price]`, `[Total]`) never need rewriting. Moving rows or columns, like
sorting, keeps formulas on their addresses.

**Show Formulas** (**Ctrl+`**) shows every cell's formula instead of its
result, for checking a sheet over.

## Keys

| Action | Key |
| --- | --- |
| Submit held edits | **F9** |
| Edit the cell | **F2**, or just type |
| Commit and move down / up | **Enter** / **Shift+Enter** |
| Clear the selected cells | **Del** |
| Fill down / right | **Ctrl+D** / **Ctrl+R** |
| Paste values only | **Ctrl+Shift+V** |
| Copy with headers | **Ctrl+Shift+C** |
| Select whole rows / columns | **Shift+Space** / **Ctrl+Space** |
| Insert / delete rows (columns when whole columns are selected) | **Ctrl++** / **Ctrl+-** |
| Move rows up/down, columns left/right | **Alt+Shift+arrows** |
| Jump to the edge of the data (Shift: select to it) | **Ctrl+arrows** |
| Find / replace | **Ctrl+F** / **Ctrl+H** |
| Filter this column | **Ctrl+Shift+L** |
| Open a cell's dropdown list | **Alt+Down** |
| Show formulas | **Ctrl+`** |

See also [[Nodes and the Library]] and [[Keyboard Shortcuts]].
