"""Show Table

A live preview card: drop it on the canvas and wire a DataFrame into it — it
renders the table directly on the node, scrollable with sortable-by-column
headers. Passes the table through unchanged so you can keep it wired into
further consumers (e.g. a second Show Table, or an export node).

**Conditional formatting.** The card can colour cells by value (a heatmap),
draw in-cell data bars, highlight the cells or rows that pass a test, add
icon sets, reformat numbers, and hide helper columns. Nothing is formatted
by default. Press **Rules…** for the rule manager — a list of what is
applied, with add / edit / remove — or type them straight into
**Conditional formatting**, one per line, `#` for a comment. Rules apply
top to bottom: where two touch the same cell the **later one wins**, so a
`=> bg green` line below a `=> row red` line still turns that cell green.

```
revenue              scale green                # 2- or 3-colour gradient
units                bar blue                   # in-cell data bar
score   >= 90        => bg green, bold          # highlight a cell
status  = fail       => row red                 # highlight the whole row
health               icons traffic              # 3-tier icon set
amount               format $,.0f               # per-column number format
growth iconmap sla: breach=✗ red, ok=✓ green    # icon decided by another column
20*     = 1  => icon ✓ green                    # a tick in every 20xx column
20*     iconmap: 1=✓ green, 0=✗ red             # the same, written as a lookup
status  colormap: fail=red, ok=green            # a fill decided by the value
rating               icons traffic only         # the icon replaces the value
revenue              width 160                  # a fixed column width
region               align centre               # left / right / centre
revenue              label "Revenue (£)"        # header text, data untouched
wrap                                            # long text runs to more lines
height 40                                       # every row 40px tall
status  = late       => row red, height 48      # …or only the rows a test picks
revenue              sort desc                  # the order the table opens in
hide sla                                        # keep a helper column out of view
show region, revenue, product                   # only these, in that order
revenue              tooltip note               # rest on a cell, read a note
trend   spark from jan..dec                     # a row's numbers as a tiny chart
region  spark area teal last from 2024-*        # …beside a value, like an icon
```

**Sparklines.** `spark` draws a row's numbers — read **across the row**
from the columns after `from`: names, a pattern, or a `jan..dec` range —
as a chart the size of a word. Drawn in a column the table doesn't have,
it makes that column (holding the row's latest number, so it still sorts);
drawn in one it has, it sits beside the value like an icon (`left`,
`right`, `above`, `below`, `in`). Add `hide` to put the months out of view,
or `replace` to put the new column where they were. Kinds `line`, `area`,
`step`, `bars`, `winloss`, `dots`; marks `first`, `last`, `high`, `low`,
`points`; plus a colour, `ref mean`, `shared` (one scale for every row),
`smooth`, `thick`, `tall` and a width like `90px`. A blank is a gap, never
a zero, and resting on a spark that stands alone says what it drew. It
prints on a report page as a picture.

`scale`, `bar` and `icons` can read their deciding value **from another
column** with a trailing `by revenue` clause, and a highlight can **test
another column** with `product if revenue < 0 => bg red` — the style still
lands in the column(s) named on the left.

**Mapping a value.** `iconmap` and `colormap` turn a set of values into
icons or fills without a line each. Leave the source column out — nothing
before the colon — and every column the rule draws in reads *its own*
value, which is what a pattern needs: `20* iconmap: 1=✓ green` ticks each
year column on its own numbers, where naming one source would paint that
one column's answer into all of them. A highlight can place an icon too
(`20* = 1 => icon ✓ green`), for a single flag rather than a whole map. An
icon goes in a cell, so it cannot be combined with `row`.

Any format rule can be drawn **instead of** the value by adding `only`
(`units bar blue only`) — Power BI's "bar only" / "icon only". The value is
hidden, not lost: the column still sorts, copies and exports on it.

`width` / `align` / `label` shape the table rather than paint it: a width is
obeyed rather than fitted, alignment beats the dtype's own habit and takes
the header with it, and a label changes the printed header only — rules,
sorting and exports still use the real column name. `wrap` names no columns
(a row is as tall as its tallest cell) and lets long text run on.

**A note that explains a cell.** `revenue tooltip note` puts another
column's value on the cell as a hover note — a sentence about a number
that would make the table worse as a column of its own. Each row reads
its own note, a blank note shows nothing, and the note column keeps
showing until you `hide` it as well. On a report page it becomes the
cell's `title`, so it survives Open in Browser. A cell that is *also* too
narrow for its value shows both: the note, then the full value under it.

**Choosing the columns.** `Hide columns` says what to lose; **Show
columns** says what to keep — and the columns come out **in the order you
picked them**, which is the only way to reorder a table without a Select
Columns node in front of it. The picker appends as you tick, so ticking
Region then Revenue puts Region first; the box is a plain list, so type the
names in any order you like. Leave it empty (the usual case) and every
column shows, in the table's own order. Name both and the keep list is
applied first, then the hidden ones come out of what is left.

Both are a **view**. The table leaving the `table` port is the one that
arrived — every column, in its original order — because this card is a way
of *looking* at a table, not a way of changing one. Put a **Select Columns**
node in front of it when the data itself should change shape.

**A default sort.** Clicking a header sorts the card and forgets; **Sort
by** (with **Direction**) says what order the table *opens* in, and unlike
a click it reaches a dashboard tile and a printed report — which is where
it matters most, because a page has no header to click. Clicking still
wins from then on; the third click clears the sort back to the table's own
order rather than to this one, and the default returns on the next run.
The `sort` rule is the same thing typed, and the dropdown wins over it.

A column whose name has a space just works (`unit price scale green`);
`"quote it"` if the name has a comma or reads like a keyword. A name with
a `*` / `?` is a **pattern** — `20* scale green` heatmaps every year
column, `*_qty bar blue` every quantity column, `hide _tmp_*` every scratch
column.

The same wildcards work on the **value** side: the `=` and `!=` tests
(`status = late* => bg red`) and the keys of a map (`status colormap:
late*=red, ok=green`). `*` is any run of characters, `?` any one, `[abc]`
one of a set, and matching is case-sensitive, as it is for a column. A
value that really contains a `*` goes in `"quotes"`. `contains`, `starts
with` and `ends with` are partial matches already and take the text as
typed; `matches` is a full regular expression.

**Matrix.** Set **Show as** to *matrix* and the card pivots the table
itself — **Rows** down the side, **Columns** across the top, **Values** in
the cells, combined by **Aggregation** — the way a spreadsheet's pivot table
does, with no Pivot node in front of it. Every rule still applies, and a
rule can read the rows *before* the pivot: over a long table of `metric,
quarter, value, status`, the one line `value iconmap status: breach=✗ red,
ok=✓ green` puts on each cell the icon its own row's status decides. Where
several rows build one cell, a highlight fires if **any** of them passes, a
map takes the value **listed first** (write the worst first), and notes are
joined. A rule about the value alone (`value > 90 => bg green`, `value scale
green`) is about each cell, and a scale, bar or icon set is measured across
the whole matrix rather than column by column. The table leaving the
`table` port is the matrix; the columns carrying a rule's verdicts ride
along with it, hidden.

The full rule language is in the **Conditional Formatting** handbook page
(F1), and **Open Example ▸ Conditional Formatting** is a worked flow.

**Sharing a look.** The rules being applied come out on the **style**
output, and a Show Table also *accepts* a style on its **style** input — so
you can wire one table's formatting into another, or feed both from a
**Table Style** node. An incoming style is the base; this card's own rules
box layers on top.

**Click to filter.** Set **On click** to *select one* or *select many*
and the table becomes a filter, the way a Show Plotly chart does: what you
pick is written into **Selected**, everything downstream re-runs, and the
**filtered** output is the table narrowed to it. **table** stays the whole
table, so the card keeps every row there to pick from.

* **Click a cell** to keep the rows holding that value in that column.
  Pick more (Ctrl+click, or drag) and values in one column add up —
  north *or* south — while columns narrow each other: north *and* widget.
* **Click a row's number** to keep that row. Rows add to what the cells
  match.
* **Ctrl+click a column header** to keep only that column; a plain click
  still sorts. A picked column never changes which rows are kept.

Set **Select** to *row* and a click takes the whole row instead: the row
lights up across the table, and only the rows you pick go on. With *select
many*, Ctrl+click adds a row, and dragging down the table picks every row
the drag covered when you let go. Row mode picks rows only, never columns.

Click the one picked cell or row again, press Esc, or right-click ▸ **Clear
Selection** to let every row through. *Select one* keeps only the last
thing clicked. A pick shows every cell it matched, survives a re-run and a
sort, and works the same on a dashboard tile. In matrix mode it filters the
matrix you see.

**Totals.** **Total row** totals every number column — sum, average,
median, min, max, range, count, rows, distinct, std, variance, first, last
or mode — at the bottom, top or both, under **Total label**. The rules box
refines it a column at a time:

```
total sum top "Grand total"     # the dropdown, typed
price     total average         # one column differently
region    total "All regions"   # words instead of a number
profit < 0 => fg red, icon ▼ red, on totals   # rules reach totals via `on`
total => bg #2a3550, bold       # how total rows look
```

A total is never sorted with the rows and never joins a heatmap, bar or
highlight — unless a rule asks with `on totals`. It takes its column's
`format` unless it is a count.

**Grouped.** Set **Show as** to *grouped* and pick **Group by**: rows with
the same value gather under a header row you click to fold, with subtotals
on it, under it, or both (**Subtotals**). Right-click for Expand / Collapse
All Groups. Several columns nest, outermost first.

**Totals in output** writes the totals into the `table` and `filtered`
outputs; off, they are only drawn. See **Totals and groups** in the
Conditional Formatting handbook page.

**The row index.** Off by default — a generated 0, 1, 2… says nothing
on a dashboard. Tick **Show row index** for a table whose index means
something (dates, names), or to click a row's number to pick it. Like the
column lists it is a view: the table leaving the `table` port keeps its
index.
"""
NODE = {
    "label": "Show Table",
    "category": "Viz",
    "version": "1.8",
    "card": "table_viewer",
    "inputs": [("table", "dataframe"),
               ("style", "object", {"optional": True})],
    # "filtered" last, so a flow wired before click-to-filter existed keeps
    # every wire on the port it was on
    "outputs": [("table", "dataframe"), ("style", "object"),
                ("filtered", "dataframe")],
}
_MATRIX = {"mode": ["matrix"]}
_GROUPED = {"mode": ["grouped"]}
# core/table_totals.AGGREGATIONS, written out so the script stands alone
# (a test keeps the two the same)
_TOTALS = ["sum", "average", "median", "min", "max", "range", "count",
           "rows", "distinct", "std", "variance", "first", "last", "mode"]
_TOTALLED = {"totals": _TOTALS}
PARAMS = [
    {"name": "mode", "type": "choice", "label": "Show as",
     "options": ["table", "grouped", "matrix"], "default": "table"},
    {"name": "group_by", "type": "columns", "label": "Group by",
     "default": "", "placeholder": "outermost first", "visible_when": _GROUPED},
    {"name": "groups_start", "type": "choice", "label": "Groups start",
     "options": ["open", "folded", "outer level open"], "default": "open",
     "visible_when": _GROUPED},
    {"name": "subtotals", "type": "choice", "label": "Subtotals",
     "options": ["on the group row", "under the group", "both", "none"],
     "default": "on the group row", "visible_when": _GROUPED},
    {"name": "matrix_rows", "type": "columns", "label": "Rows", "default": "",
     "placeholder": "what runs down the side", "visible_when": _MATRIX},
    {"name": "matrix_columns", "type": "columns", "label": "Columns",
     "default": "", "placeholder": "what runs across the top",
     "visible_when": _MATRIX},
    {"name": "matrix_values", "type": "columns", "label": "Values",
     "default": "", "placeholder": "empty = every other number",
     "visible_when": _MATRIX},
    {"name": "matrix_agg", "type": "choice", "label": "Aggregation",
     "options": ["sum", "mean", "median", "min", "max", "count", "first"],
     "default": "sum", "visible_when": _MATRIX},
    {"name": "matrix_order", "type": "choice", "label": "Order",
     "options": ["as they appear", "sorted"], "default": "as they appear",
     "visible_when": _MATRIX},
    {"name": "totals", "type": "choice", "label": "Total row",
     "options": ["off"] + _TOTALS, "default": "off"},
    {"name": "totals_at", "type": "choice", "label": "Total row at",
     "options": ["bottom", "top", "both"], "default": "bottom",
     "visible_when": _TOTALLED},
    {"name": "total_label", "type": "string", "label": "Total label",
     "default": "Total", "visible_when": _TOTALLED},
    # Off by default: the totals are a way of looking at the table, and a
    # node downstream summing a column that already holds its own total
    # would count everything twice.
    {"name": "totals_out", "type": "bool", "label": "Totals in output",
     "default": False},
    {"name": "on_click", "type": "choice", "label": "On click",
     "options": ["nothing", "select one", "select many"],
     "default": "nothing"},
    {"name": "select_by", "type": "choice", "label": "Select",
     "options": ["cell", "row"], "default": "cell",
     "visible_when": {"on_click": ["select one", "select many"]}},
    # Written by the card when a cell, row or column is picked. Visible for
    # the reason Show Plotly's Clicked values is: when the filter keeps the
    # wrong rows, the first question is what the card actually sent.
    {"name": "selected", "type": "string", "label": "Selected",
     "default": "",
     "placeholder": 'e.g. {"cells": {"region": ["north"]}} — blank keeps '
                    'every row',
     "visible_when": {"on_click": ["select one", "select many"]}},
    {"name": "format_rules", "type": "text", "label": "Conditional formatting",
     "default": "", "rule_wizard": True,
     "placeholder": "revenue scale green\nscore >= 90 => bg green, bold\n"
                    "status = fail => row red"},
    {"name": "show", "type": "columns", "label": "Show columns",
     "default": "", "placeholder": "only these, in the order picked"},
    {"name": "hide", "type": "columns", "label": "Hide columns", "default": "",
     "placeholder": "columns to keep out of the view"},
    {"name": "sort", "type": "columns", "label": "Sort by", "default": "",
     "multi": False, "placeholder": "the order the table opens in"},
    {"name": "sort_dir", "type": "choice", "label": "Direction",
     "options": ["ascending", "descending"], "default": "ascending"},
    # Off by default: a generated 0, 1, 2… says nothing to the person
    # reading a table, least of all on a dashboard. A table whose index
    # means something (dates, names) ticks it.
    {"name": "row_index", "type": "bool", "label": "Show row index",
     "default": False},
    {"name": "width", "type": "int", "label": "Width",
     "default": 420, "min": 260, "max": 4000, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 320, "min": 200, "max": 4000, "cosmetic": True},
    # Cosmetic: run() never reads it — the zoom is applied to the card, to
    # the table this node already passed through.
    {"name": "scale", "type": "int", "label": "Scale %",
     "default": 100, "min": 25, "max": 400, "cosmetic": True},
]


def run(ctx, table, style=None):
    from flograph.core.table_format import (
        merge_styles, style_payload, style_report)

    # Named one by one rather than handing over ctx.params whole: the
    # cosmetic width/height/scale are not style, and style_payload should
    # not have to know which of this node's params are and are not.
    own = style_payload({"format_rules": ctx.params.get("format_rules", ""),
                         "show": ctx.params.get("show", ""),
                         "hide": ctx.params.get("hide", ""),
                         "sort": ctx.params.get("sort", ""),
                         "sort_dir": ctx.params.get("sort_dir", ""),
                         "row_index": ctx.params.get("row_index", True),
                         "mode": ctx.params.get("mode", "table"),
                         "group_by": ctx.params.get("group_by", ""),
                         "groups_start": ctx.params.get("groups_start", ""),
                         "subtotals": ctx.params.get("subtotals", ""),
                         "totals": ctx.params.get("totals", "off"),
                         "totals_at": ctx.params.get("totals_at", ""),
                         "total_label": ctx.params.get("total_label", "")})
    merged = merge_styles(style, own)
    if ctx.params.get("mode") == "matrix":
        from flograph.core.matrix import build_matrix, column_list

        # The rules are carried onto the matrix here, on the worker, so the
        # card, the tile and a printed page all draw it with the rule engine
        # they already have — see core/matrix.py.
        built = build_matrix(
            table, rows=column_list(ctx.params.get("matrix_rows")),
            columns=column_list(ctx.params.get("matrix_columns")),
            values=column_list(ctx.params.get("matrix_values")),
            agg=ctx.params.get("matrix_agg") or "sum",
            order=ctx.params.get("matrix_order") or "as they appear",
            style=merged, totals=True)
        for note in built.notes:
            ctx.log(f"matrix — {note}")
        ctx.log(f"matrix: {len(table)} rows -> {len(built.frame)} rows")
        table, merged = built.frame, built.style
    for message in style_report(merged, table):
        ctx.log(f"conditional formatting — {message}")
    # Click to filter: the card writes what was picked into "selected", and
    # the filter below reads it back through the same module the card uses
    # to highlight it — see core/table_picks.py.
    from flograph.core.table_picks import active_picks, describe, filter_frame

    picks = active_picks(ctx.params)
    filtered = table
    if picks:
        filtered, notes = filter_frame(table, picks)
        for note in notes:
            ctx.log(f"selection — {note}")
        ctx.log(f"selection ({describe(picks)}): kept {len(filtered):,} "
                f"of {len(table):,} rows")
    # Total rows and groups (core/table_totals.py). The card lays them out
    # itself; they reach the table port only when Totals in output says so,
    # and then the style says which rows they are, so a card fed this table
    # does not total its own totals.
    from flograph.core.table_format import rules_from_style
    from flograph.core.table_totals import plan_from_rules, with_totals

    plan = plan_from_rules(rules_from_style(merged), table)
    for note in plan.notes:
        ctx.log(f"totals — {note}")
    if ctx.params.get("totals_out") and plan.active:
        grand = merged.get("grand") if isinstance(merged, dict) else None
        table, baked = with_totals(table, plan, grand=grand)
        merged = {**merged, "baked": baked}
        if picks:
            filtered, _ = with_totals(filtered, plan)
        else:
            filtered = table
        ctx.log(f"totals: {len(baked)} total row(s) written into the output")
    return {"table": table, "style": merged, "filtered": filtered}
