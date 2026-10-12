"""Input Panel

A whole page of filters in one card — slicers, sliders, a date window, tick
boxes — that all talk to each other, the way the slicers on a Power BI page
do. Wire a table into "data"; each field filters it on a column; the
"filtered" output is the rows every field lets through, ready for charts,
cards and tables.

    Region   = slicer region
    Product  = slicer product
    Channel  = choice channel style=buttons
    Price    = between price step=5
    Ordered  = date range order_date
    Customer = text customer contains
    In stock = toggle in_stock

Each line is `Label = shape [column] [comparison] [option=value …]`:

* **shape** — slicer (a tick list with search and row counts), choice,
  multi, slider, number, between, date, date range, text, toggle, time,
  datetime or colour: the same controls the Input category has, drawn the
  same way.
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

**Fields filter each other.** "Cascade" says how:

* **each other** (the default) — every slicer, choice and multi offers the
  values the *other* fields leave, with counts to match: pick North and the
  Product slicer shows North's products; pick Gadget and Region shows only
  the regions that sell it. Sliders and date windows keep their column's
  whole span, so nothing you set is moved under you.
* **top to bottom** — each field sees only what the fields above it left,
  ranges included.
* **off** — every field sees the whole table.

**Apply on the panel.** Set Behaviour ▸ Apply changes to "with ✓ on the
control" and the panel gets Apply and Reset buttons along its bottom: set
every field, press Apply, and the flow runs once.

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
    "version": "1.1",
    "card": "control",
    "control": "panel",
    "inputs": [("data", "dataframe", {"optional": True})],
    "outputs": [("filtered", "dataframe"), ("values", "any"),
                ("filters", "any")],
}
PARAMS = [
    {"name": "caption", "type": "string", "label": "Caption",
     "default": "", "placeholder": "Shown above the fields"},
    # "Set Up Fields…" beside it opens the setup wizard (ui/panel_wizard),
    # which writes these same lines
    {"name": "fields", "type": "text", "label": "Fields", "default": "",
     "wizard": "panel",
     "placeholder": "Region = slicer region\nPrice = between price\n"
                    "Ordered = date range order_date"},
    # every field's stored value, as JSON {name: value} — the one value the
    # control host writes, so Apply/Reset/undo work on the whole panel
    {"name": "value", "type": "text", "label": "Values", "default": "",
     "hidden": True},
    {"name": "cascade", "type": "choice", "label": "Fields filter",
     "options": ["each other", "top to bottom", "off"],
     "default": "each other"},
    {"name": "publish", "type": "bool", "label": "Fields are variables",
     "default": True},
    {"name": "layout", "type": "choice", "label": "Layout",
     "options": ["stacked", "row", "2 columns", "3 columns"],
     "default": "stacked", "cosmetic": True},
    {"name": "width", "type": "int", "label": "Width",
     "default": 300, "min": 160, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 320, "min": 80, "max": 4000, "cosmetic": True},
]


def run(ctx, data=None):
    from flograph.core.input_panel import (blank_required, parse_fields,
                                           parse_values, run_panel)

    fields, problems = parse_fields(ctx.params.get("fields"))
    if problems:
        raise ValueError("; ".join(problems))
    stored = parse_values(ctx.params.get("value"))
    filtered, values, filters, _contexts = run_panel(
        fields, stored, data, ctx.params.get("cascade", "each other"))
    missing = blank_required(fields, values)
    if missing:
        raise ValueError(f"not configured: {', '.join(missing)} "
                         f"{'is' if len(missing) == 1 else 'are'} required")
    for flt in filters:
        ctx.log(f"{flt['column']} {flt['op']} {flt['value']!r}")
    if data is not None:
        ctx.log(f"{len(filtered):,} of {len(data):,} rows pass")
    return {"filtered": filtered, "values": values, "filters": filters}
