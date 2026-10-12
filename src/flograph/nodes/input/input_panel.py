"""Input Panel

Several input fields in one card — a filter panel for a dashboard, built by
writing one line per field. Wire a table into "data" and each field can
filter it on a column: the panel's "filtered" output is the rows every
field lets through.

    Region   = choice region
    City     = choice city
    Price    = between price step=5
    Ordered  = date range order_date
    Customer = text customer contains
    In stock = toggle in_stock
    Top N    = number min=1 max=50 default=10

Each line is `Label = shape [column] [comparison] [option=value …]`:

* **shape** — choice, multi, slider, number, between, date, date range,
  text, toggle, time, datetime or colour: the same controls the Input
  category has, drawn the same way.
* **column** — the column of "data" the field filters on. Leave it out and
  the field is just a value (read it from "values", or as a variable).
* **comparison** — how it filters: `>=` `<=` `>` `<` `=` for a number or a
  date (`>=` unless you say), `contains` `startswith` `=` for text
  (`contains`). A choice matches exactly, a multi keeps any ticked value, a
  between or a date range keeps the window, a toggle keeps rows where the
  column is true while it is on.
* **options** — `step=5` `decimals=2` `min=0` `max=100` `default=10`
  `style=buttons` `all=no` `required=yes` `help="…"` `placeholder="…"`
  `options=a|b|c` (for a choice with no column) `name=…` (see below).

**Nothing set filters nothing.** A new panel passes every row: a choice
starts on "(All)", a multi with nothing ticked, a slider and a date at the
end of their column's range, a between and a date range on the whole range.
Each field narrows the table only once someone uses it.

**One field narrows the next** — with "Cascade" on (the default), each
field's options come from the rows the fields above it left, so City only
offers the picked Region's cities. A field's bounds follow its column too.

**Using the picks elsewhere.**
* "values" is a dict of every field's value, keyed by name — the label made
  into an identifier ("In stock" is `in_stock`), or `name=` on the line.
* Tick "Fields are variables" and each field is also `${name}` anywhere in
  the flow (with Behaviour ▸ Variable name as a prefix, if you set one:
  `f` makes them `${f_region}`, `${f_price}`, …).
* "filters" describes the filters the panel applied. Wire it into an
  **Apply Filters** node to filter a second table by the same picks — the
  orders table by the customers panel, say.

Like every control it can hold changes until Apply (Behaviour ▸ Apply
changes), so a reader can set five fields and run once.
"""
NODE = {
    "label": "Input Panel",
    "category": "Input",
    "version": "1.0",
    "card": "control",
    "control": "panel",
    "inputs": [("data", "dataframe", {"optional": True})],
    "outputs": [("filtered", "dataframe"), ("values", "any"),
                ("filters", "any")],
}
PARAMS = [
    {"name": "caption", "type": "string", "label": "Caption",
     "default": "", "placeholder": "Shown above the fields"},
    {"name": "fields", "type": "text", "label": "Fields", "default": "",
     "placeholder": "Region = choice region\nPrice = between price\n"
                    "Ordered = date range order_date"},
    # every field's stored value, as JSON {name: value} — the one value the
    # control host writes, so Apply/Reset/undo work on the whole panel
    {"name": "value", "type": "text", "label": "Values", "default": "",
     "hidden": True},
    {"name": "cascade", "type": "bool", "label": "Cascade", "default": True},
    {"name": "publish", "type": "bool", "label": "Fields are variables",
     "default": True},
    {"name": "layout", "type": "choice", "label": "Layout",
     "options": ["stacked", "row", "2 columns", "3 columns"],
     "default": "stacked", "cosmetic": True},
    {"name": "width", "type": "int", "label": "Width",
     "default": 300, "min": 160, "max": 800, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 320, "min": 80, "max": 600, "cosmetic": True},
]


def run(ctx, data=None):
    from flograph.core.input_panel import (blank_required, parse_fields,
                                           parse_values, run_panel)

    fields, problems = parse_fields(ctx.params.get("fields"))
    if problems:
        raise ValueError("; ".join(problems))
    stored = parse_values(ctx.params.get("value"))
    filtered, values, filters, _contexts = run_panel(
        fields, stored, data, bool(ctx.params.get("cascade", True)))
    missing = blank_required(fields, values)
    if missing:
        raise ValueError(f"not configured: {', '.join(missing)} "
                         f"{'is' if len(missing) == 1 else 'are'} required")
    for flt in filters:
        ctx.log(f"{flt['column']} {flt['op']} {flt['value']!r}")
    if data is not None:
        ctx.log(f"{len(filtered):,} of {len(data):,} rows pass")
    return {"filtered": filtered, "values": values, "filters": filters}
