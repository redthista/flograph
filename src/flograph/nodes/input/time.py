"""Time

A time of day — an opening hour, a cut-off, a shift start. It flows
downstream as "HH:MM" on a 24-hour clock, which sorts and compares as text:
`df[df["start"] >= chosen]` works on a column of "HH:MM" strings.
"""
NODE = {
    "label": "Time",
    "category": "Input",
    "version": "1.0",
    "card": "control",
    "control": "time",
    "inputs": [],
    "outputs": [("value", "string")],
}
PARAMS = [
    {"name": "caption", "type": "string", "label": "Caption",
     "default": "", "placeholder": "Shown above the picker"},
    {"name": "value", "type": "string", "label": "Time", "default": "09:00",
     "placeholder": "HH:MM, 24-hour"},
    {"name": "width", "type": "int", "label": "Width",
     "default": 180, "min": 120, "max": 800, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 84, "min": 56, "max": 600, "cosmetic": True},
]


def run(ctx):
    from flograph.core.controls import time_value

    return {"value": time_value(ctx.params.get("value"))}
