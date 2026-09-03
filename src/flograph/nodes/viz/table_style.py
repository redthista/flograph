"""Table Style

Decides how a **Show Table** card looks — without touching the data. Wire
this node's **Style** output into Show Table's **Style** input and the grid
picks up colour scales, in-cell data bars, highlighted cells, whole-row
flags and icon sets. The table flowing out of Show Table is unchanged; this
is presentation only, the same split as **Plotly Style** for charts.

Connect the same table into this node's optional **table** input too and the
column picker fills itself in and unknown column names are flagged.

**Quick rule** — the fastest path: pick one or more columns, pick *Format
as*, and the extra fields for that mode appear.

  * **Colour scale** shades each cell by where its value sits in the
    column's range — a heatmap.
  * **Data bars** draw a bar in the cell, proportional to the value; a
    column with negatives grows bars both ways from zero.
  * **Highlight** colours the cells (or whole rows) that pass a test —
    `> 90`, `contains fail`, `between 10 20`, `= closed`.
  * **Icons** put a 3-tier glyph (🔴 🟡 🟢, arrows, ✅ ➖ ❌) beside the
    value, split at the column's thirds.

**More rules** takes one rule per line for anything past a single quick
rule. `#` starts a comment.

```
revenue              scale green                # 2- or 3-colour gradient
margin               scale red-yellow-green
units                bar blue                   # in-cell data bar
score   >= 90        => bg green, bold          # highlight a cell
status  contains fail => bg red
status  = closed     => row grey                # highlight the whole row
health               icons traffic              # 3-tier icon set
amount               format $,.0f               # per-column number format
```

Colours are a preset name (`green`, `red`, `amber`, `blue`, `grey`) or a
`#hex`. Scales: `green`, `blue`, `red`, `red-green`, `red-yellow-green`,
`diverging`. When two rules touch the same cell the later one wins.
"""
NODE = {
    "label": "Table Style",
    "category": "Viz",
    "version": "1.0",
    "inputs": [("table", "dataframe", {"optional": True})],
    "outputs": [("style", "object")],
}
PARAMS = [
    {"name": "cf_columns", "type": "columns", "label": "Format column(s)",
     "default": "", "placeholder": "pick one or more columns"},
    {"name": "cf_mode", "type": "choice", "label": "Format as",
     "options": ["off", "colour scale", "data bars", "highlight", "icons"],
     "default": "off", "unset_label": "off"},
    {"name": "cf_scale", "type": "choice", "label": "Colours",
     "options": ["green", "red to green", "white to red", "blue", "diverging"],
     "default": "green", "visible_when": {"cf_mode": ["colour scale"]}},
    {"name": "cf_bar_color", "type": "choice", "label": "Bar colour",
     "options": ["blue", "green", "orange", "purple"], "default": "blue",
     "visible_when": {"cf_mode": ["data bars"]}},
    {"name": "cf_test", "type": "string", "label": "When value",
     "default": "", "placeholder": "> 90     contains fail     = closed",
     "visible_when": {"cf_mode": ["highlight"]}},
    {"name": "cf_fill", "type": "choice", "label": "Highlight",
     "options": ["red", "amber", "green", "grey", "blue"], "default": "red",
     "visible_when": {"cf_mode": ["highlight"]}},
    {"name": "cf_scope", "type": "choice", "label": "Apply to",
     "options": ["cell", "whole row"], "default": "cell",
     "visible_when": {"cf_mode": ["highlight"]}},
    {"name": "cf_icons", "type": "choice", "label": "Icon set",
     "options": ["traffic lights", "arrows", "check / cross"],
     "default": "traffic lights", "visible_when": {"cf_mode": ["icons"]}},
    {"name": "format_rules", "type": "text", "label": "More rules",
     "default": "", "insert_columns": "inline",
     "placeholder": "revenue scale green\nscore >= 90 => bg green, bold\n"
                    "status contains fail => row red"},
]


def run(ctx, table=None):
    from flograph.core.table_format import rules_from_params

    rules = rules_from_params(ctx.params)
    if table is not None and rules:
        known = {str(c) for c in table.columns}
        missing = sorted({c for r in rules for c in r.columns} - known)
        if missing:
            ctx.log("columns not in the table — those rules do nothing: "
                    + ", ".join(missing))
    kinds = ", ".join(sorted({r.mode.replace("_", " ") for r in rules})) or "none"
    ctx.log(f"{len(rules)} rule(s): {kinds}")
    return {"style": [r.to_dict() for r in rules]}
