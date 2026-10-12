"""Date & Time

A date and a time of day in one picker, for a moment rather than a day —
"since this morning's release", "up to the cut-off". It flows downstream as
ISO "YYYY-MM-DDTHH:MM", which pandas compares against a datetime column
as it is: `df[df["logged"] >= chosen]`.

A blank value means midnight today.
"""
NODE = {
    "label": "Date & Time",
    "category": "Input",
    "version": "1.0",
    "card": "control",
    "control": "datetime",
    "inputs": [],
    "outputs": [("value", "string")],
}
PARAMS = [
    {"name": "caption", "type": "string", "label": "Caption",
     "default": "", "placeholder": "Shown above the picker"},
    {"name": "value", "type": "string", "label": "Date and time",
     "default": "", "placeholder": "YYYY-MM-DDTHH:MM — blank is midnight today"},
    {"name": "width", "type": "int", "label": "Width",
     "default": 220, "min": 160, "max": 800, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 84, "min": 56, "max": 600, "cosmetic": True},
]


def run(ctx):
    from flograph.core.controls import datetime_value

    return {"value": datetime_value(ctx.params.get("value"))}
