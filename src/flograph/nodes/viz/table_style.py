"""Table Style

Holds a set of conditional-formatting rules and emits them on its **Style**
output — wire that into one or more **Show Table** cards to give them all
the same look from one place. It has no data input: **Show Table** already
carries its own rules box, so this node is only worth reaching for when a
style is shared across several tables, or a long rule list would clutter a
Show Table's properties.

Press **Rules…** for the manager, or write one rule per line (`#` for a
comment). Rules apply top to bottom — a later rule wins where two touch the
same cell:

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

`scale`, `bar` and `icons` can take their deciding value **from another
column** with a trailing `by` clause, and a highlight can **test another
column** with an `if` clause — the style still lands in the column(s) on
the left:

```
product   scale green by revenue                # shade Product by revenue
product   bar blue by units
product   icons traffic by score
product   if revenue < 0 => bg red              # flag Product when revenue < 0
product   if status = closed => row grey         # whole row, tested on status
```

Colours are a preset name (`green`, `red`, `amber`, `blue`, `grey`) or a
`#hex`. Scales: `green`, `blue`, `red`, `red-green`, `red-yellow-green`,
`diverging`. A column name with a space just works; `"quote it"` if it has
a comma or reads like a keyword. A name with a `*` / `?` is a **pattern**
that selects every matching column (`20* scale green`). Several rules can
target one column (a data bar *and* an icon).

Anything wrong with a rule — a typo, a column the table doesn't have — is
reported on the **Show Table** that applies it, where the data is.
"""
NODE = {
    "label": "Table Style",
    "category": "Viz",
    "version": "1.1",
    "inputs": [],
    "outputs": [("style", "object")],
}
PARAMS = [
    {"name": "format_rules", "type": "text", "label": "Rules",
     "default": "", "rule_wizard": True,
     "placeholder": "revenue scale green\nscore >= 90 => bg green, bold\n"
                    "status = fail => row red"},
    {"name": "hide", "type": "string", "label": "Hide columns", "default": "",
     "placeholder": "columns the Show Table should keep out of view"},
]


def run(ctx):
    from flograph.core.table_format import style_payload

    payload = style_payload(ctx.params)
    kinds = ", ".join(sorted({r["mode"].replace("_", " ")
                              for r in payload["rules"]})) or "none"
    ctx.log(f"{len(payload['rules'])} rule(s): {kinds}"
            + (f"; {len(payload['errors'])} not understood "
               "(reported on the Show Table)" if payload["errors"] else ""))
    return {"style": payload}
