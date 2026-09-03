"""Show Table

A live preview card: drop it on the canvas and wire a DataFrame into it — it
renders the table directly on the node, scrollable with sortable-by-column
headers. Passes the table through unchanged so you can keep it wired into
further consumers (e.g. a second Show Table, or an export node).

**Conditional formatting.** The card can colour cells by value (a heatmap),
draw in-cell data bars, highlight the cells or rows that pass a test, add
icon sets, reformat numbers, and hide helper columns. Nothing is formatted
by default. Write the rules in **Conditional formatting** — one per line,
`#` for a comment — or press **Build a rule…** for a guided dialog.

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

A column whose name has a space just works (`unit price scale green`);
`"quote it"` if the name has a comma or reads like a keyword.

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
