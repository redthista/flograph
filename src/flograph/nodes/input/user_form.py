"""User Form

Collect one record on the canvas or a dashboard. Values reach the flow only
when Submit is pressed; the latest submitted entry is returned as a dict.
"""
NODE = {
    "label": "User Form",
    "category": "Input",
    "version": "1.0",
    "card": "form",
    "inputs": [("fields", "any", {"optional": True})],
    "outputs": [("entry", "object")],
}
PARAMS = [
    {"name": "caption", "type": "string", "label": "Caption",
     "default": ""},
    {"name": "submit_label", "type": "string", "label": "Submit label",
     "default": "Submit"},
    {"name": "reset_label", "type": "string", "label": "Reset label",
     "default": "Reset"},
    {"name": "load_targets", "type": "text", "label": "Load targets",
     "default": "", "placeholder": "Node labels or a frame title"},
    {"name": "load_clear_cache", "type": "bool", "label": "Reload targets",
     "default": True},
    {"name": "fields", "type": "text", "label": "Fields",
     "default": "", "placeholder": "name|type|label|default[|options]"},
    {"name": "value", "type": "text", "label": "Submitted values",
     "default": "", "hidden": True},
    {"name": "width", "type": "int", "label": "Width",
     "default": 360, "min": 220, "max": 960, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 320, "min": 160, "max": 1600, "cosmetic": True},
]


def run(ctx, fields=None):
    from flograph.core.form import parse_entry, schema_from_upstream

    schema = schema_from_upstream(fields, ctx.params.get("fields", ""))
    raw = ctx.params.get("value", "")
    if raw in (None, ""):
        return {"entry": {}}
    return {"entry": parse_entry(raw, schema)}
