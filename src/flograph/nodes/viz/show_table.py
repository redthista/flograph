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
revenue              sort desc                  # the order the table opens in
hide sla                                        # keep a helper column out of view
show region, revenue, product                   # only these, in that order
revenue              tooltip note               # rest on a cell, read a note
```

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

The full rule language is in the **Conditional Formatting** handbook page
(F1), and **Open Example ▸ Conditional Formatting** is a worked flow.

**Sharing a look.** The rules being applied come out on the **style**
output, and a Show Table also *accepts* a style on its **style** input — so
you can wire one table's formatting into another, or feed both from a
**Table Style** node. An incoming style is the base; this card's own rules
box layers on top.
"""
NODE = {
    "label": "Show Table",
    "category": "Viz",
    "version": "1.4",
    "card": "table_viewer",
    "inputs": [("table", "dataframe"),
               ("style", "object", {"optional": True})],
    "outputs": [("table", "dataframe"), ("style", "object")],
}
PARAMS = [
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
                         "sort_dir": ctx.params.get("sort_dir", "")})
    merged = merge_styles(style, own)
    for message in style_report(merged, table):
        ctx.log(f"conditional formatting — {message}")
    return {"table": table, "style": merged}
