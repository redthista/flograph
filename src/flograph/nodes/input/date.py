"""Date

A calendar picker. The value flows downstream as an ISO "YYYY-MM-DD" string,
which is what pandas comparisons want — `df[df["when"] >= chosen]` works
without any conversion.

Leave "Earliest"/"Latest" blank for an unbounded calendar, or set them to
pin the picker to the range your data actually covers, so nobody can choose
a date that returns nothing.

A blank "Date" means today — that's what the picker shows on a node nobody
has touched yet, so it's what flows downstream too.

**Bounds from your data.** Wire a date column into "minimum" and "maximum"
and the calendar is pinned to exactly the period your data covers — a
column is reduced to its earliest date for "minimum" and its latest for
"maximum". The chosen date is kept inside that range, so an untouched
picker with "maximum" wired lands on the latest date you actually have,
which is usually the default you wanted.

Two of these make a from/to range for filtering a period.
"""
NODE = {
    "label": "Date",
    "category": "Input",
    "version": "1.0",
    "card": "control",
    "control": "date",
    "inputs": [("minimum", "any", {"optional": True}),
               ("maximum", "any", {"optional": True})],
    "outputs": [("value", "string")],
}
PARAMS = [
    {"name": "caption", "type": "string", "label": "Caption",
     "default": "", "placeholder": "Shown above the picker"},
    {"name": "value", "type": "date", "label": "Date", "default": ""},
    {"name": "minimum", "type": "date", "label": "Earliest", "default": ""},
    {"name": "maximum", "type": "date", "label": "Latest", "default": ""},
    {"name": "width", "type": "int", "label": "Width",
     "default": 200, "min": 140, "max": 600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 84, "min": 56, "max": 400},
]


def run(ctx, minimum=None, maximum=None):
    import datetime

    from flograph.core.controls import as_iso_date, date_value, reduce_bound

    low = as_iso_date(reduce_bound(minimum, high=False)) \
        or str(ctx.params.get("minimum") or "")
    high = as_iso_date(reduce_bound(maximum, high=True)) \
        or str(ctx.params.get("maximum") or "")
    chosen = date_value(ctx.params.get("value"))
    # same clamp the picker applies, so the card and the wire agree
    if low and chosen < low:
        chosen = as_iso_date(low) or chosen
    if high and chosen > high:
        chosen = as_iso_date(high) or chosen
    datetime.date.fromisoformat(chosen)  # never emit an unparseable date
    return {"value": chosen}
