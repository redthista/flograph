"""Date Range

A from/to pair of dates in one control — the shape a "this period" filter
wants: `df[df["when"].between(start, end)]`. Both flow downstream as ISO
"YYYY-MM-DD" strings, on the `start` and `end` outputs.

The dropdown above the two pickers offers windows that move with the
calendar — last 7, 30 or 90 days, this month, last month, year to date, or
the whole range — so a dashboard opened next week shows next week's "last
30 days" without anybody editing it. Pick a date in either box and it
becomes a fixed (custom) range until you choose a window again. A fresh
control starts on the last 30 days.

**Bounds from your data.** Wire a date column into "minimum" and "maximum"
and the pickers are pinned to the period your data covers; "whole range" is
then exactly that period.

As a variable (Behaviour ▸ Variable name, say `period`) it publishes
`${period_start}`, `${period_end}`, and `${period}` as the pair.
"""
NODE = {
    "label": "Date Range",
    "category": "Input",
    "version": "1.0",
    "card": "control",
    "control": "date_range",
    "inputs": [("minimum", "any", {"optional": True}),
               ("maximum", "any", {"optional": True})],
    "outputs": [("start", "string"), ("end", "string")],
}
PARAMS = [
    {"name": "caption", "type": "string", "label": "Caption",
     "default": "", "placeholder": "Shown above the pickers"},
    # a window's name ("last 30 days") or a picked pair ["2026-01-01",
    # "2026-03-31"] — one param, because the host writes exactly one value
    {"name": "value", "type": "string", "label": "Range",
     "default": "last 30 days",
     "placeholder": 'last 30 days — or ["2026-01-01", "2026-03-31"]'},
    {"name": "minimum", "type": "date", "label": "Earliest", "default": ""},
    {"name": "maximum", "type": "date", "label": "Latest", "default": ""},
    {"name": "width", "type": "int", "label": "Width",
     "default": 300, "min": 220, "max": 800, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 110, "min": 84, "max": 600, "cosmetic": True},
]


def run(ctx, minimum=None, maximum=None):
    from flograph.core.controls import (as_iso_date, date_range_values,
                                        reduce_bound)

    low = as_iso_date(reduce_bound(minimum, high=False)) \
        or as_iso_date(ctx.params.get("minimum"))
    high = as_iso_date(reduce_bound(maximum, high=True)) \
        or as_iso_date(ctx.params.get("maximum"))
    _preset, start, end = date_range_values(ctx.params.get("value"), low, high)
    return {"start": start, "end": end}
