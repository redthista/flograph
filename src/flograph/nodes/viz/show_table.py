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
hide sla                                        # keep a helper column out of view
```

`scale`, `bar` and `icons` can read their deciding value **from another
column** with a trailing `by revenue` clause, and a highlight can **test
another column** with `product if revenue < 0 => bg red` — the style still
lands in the column(s) named on the left.

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
    "version": "1.2",
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
    {"name": "hide", "type": "columns", "label": "Hide columns", "default": "",
     "placeholder": "columns to keep out of the view"},
    {"name": "width", "type": "int", "label": "Width",
     "default": 420, "min": 260, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 320, "min": 200, "max": 2000, "cosmetic": True},
    # Cosmetic: run() never reads it — the zoom is applied to the card, to
    # the table this node already passed through.
    {"name": "scale", "type": "int", "label": "Scale %",
     "default": 100, "min": 25, "max": 400, "cosmetic": True},
]


def run(ctx, table, style=None):
    from flograph.core.table_format import (
        merge_styles, style_payload, style_report)

    own = style_payload({"format_rules": ctx.params.get("format_rules", ""),
                         "hide": ctx.params.get("hide", "")})
    merged = merge_styles(style, own)
    for message in style_report(merged, table):
        ctx.log(f"conditional formatting — {message}")
    return {"table": table, "style": merged}
