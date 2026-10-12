"""Date

A calendar picker. The value flows downstream as an ISO "YYYY-MM-DD" string,
which is what pandas comparisons want — `df[df["when"] >= chosen]` works
without any conversion.

Leave "Earliest"/"Latest" blank for an unbounded calendar, or set them to
pin the picker to the range your data actually covers, so nobody can choose
a date that returns nothing.

A blank "Date" means today — that's what the picker shows on a node nobody
has touched yet, so it's what flows downstream too.

**Relative dates.** "Starts on" makes an untouched picker move with the
calendar: today, yesterday, the start of this week, month or year, or a
number of days ago — so a dashboard opened next Monday shows next Monday's
week without anybody editing it. A day picked by hand stays picked; Reset
(Behaviour ▸ Show reset button, or right-click ▸ Reset to Default) goes back
to the moving date.

**No date.** Tick "Allow no date" and the picker can be left empty — it
shows "No date" and emits "" — for an optional "from" that, left empty,
means "from the beginning".

**Bounds from your data.** Wire a date column into "minimum" and "maximum"
and the calendar is pinned to exactly the period your data covers — a
column is reduced to its earliest date for "minimum" and its latest for
"maximum". The chosen date is kept inside that range, so an untouched
picker with "maximum" wired lands on the latest date you actually have,
which is usually the default you wanted.

Two of these make a from/to range for filtering a period — or use a
**Date Range**, which is both in one.
"""
NODE = {
    "label": "Date",
    "category": "Input",
    "version": "1.1",
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
    {"name": "preset", "type": "choice", "label": "Starts on",
     "options": ["fixed", "today", "yesterday", "start of week",
                 "start of month", "start of year", "days ago"],
     "default": "fixed"},
    {"name": "days", "type": "int", "label": "Days ago", "default": 7,
     "min": 0, "max": 36500, "visible_when": {"preset": "days ago"}},
    {"name": "allow_blank", "type": "bool", "label": "Allow no date",
     "default": False},
    {"name": "minimum", "type": "date", "label": "Earliest", "default": ""},
    {"name": "maximum", "type": "date", "label": "Latest", "default": ""},
    {"name": "width", "type": "int", "label": "Width",
     "default": 200, "min": 140, "max": 800, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 84, "min": 56, "max": 600, "cosmetic": True},
]


def run(ctx, minimum=None, maximum=None):
    import datetime

    from flograph.core.controls import as_iso_date, date_value, reduce_bound

    low = as_iso_date(reduce_bound(minimum, high=False)) \
        or str(ctx.params.get("minimum") or "")
    high = as_iso_date(reduce_bound(maximum, high=True)) \
        or str(ctx.params.get("maximum") or "")
    chosen = date_value(ctx.params.get("value"),
                        ctx.params.get("preset", "fixed"),
                        ctx.params.get("days", 0),
                        bool(ctx.params.get("allow_blank", False)))
    if not chosen:
        return {"value": ""}    # "No date": nothing to clamp
    # same clamp the picker applies, so the card and the wire agree
    if low and chosen < low:
        chosen = as_iso_date(low) or chosen
    if high and chosen > high:
        chosen = as_iso_date(high) or chosen
    datetime.date.fromisoformat(chosen)  # never emit an unparseable date
    return {"value": chosen}
