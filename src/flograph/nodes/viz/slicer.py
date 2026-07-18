"""Slicer

A Power BI/Excel-style interactive filter: pick a column and the card shows
that column's values right on the canvas, with a search box to find values
and Select All / None shortcuts. Ticking values filters the table flowing
through and automatically re-runs everything downstream, so the visuals
that follow stay live. With nothing ticked the table passes through
unfiltered.

"Selection" switches between the two slicer styles those tools offer:
"multi" is a checkbox list (any number of ticks); "single" is a radio-style
list where picking one value clears any other and clicking it again clears
the selection entirely.

Values are matched as strings; "Selected values" holds the ticked ones as a
JSON array (a comma-separated list also works when editing by hand).
"""
NODE = {
    "label": "Slicer",
    "category": "Viz",
    "card": "slicer",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "column", "type": "columns", "label": "Column",
     "default": "", "multi": False},
    {"name": "mode", "type": "choice", "label": "Selection",
     "options": ["multi", "single"], "default": "multi"},
    {"name": "selected", "type": "string", "label": "Selected values",
     "default": "", "placeholder": 'Ticked values, e.g. ["north", "south"] '
                                   "— blank keeps every row"},
    {"name": "width", "type": "int", "label": "Width",
     "default": 200, "min": 140, "max": 600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 240, "min": 120, "max": 2000},
]


def _selected_values(raw):
    """The ticked values as strings: a JSON array normally (the card widget
    writes that), falling back to a comma-separated list for hand edits."""
    import json
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(v) for v in parsed]
        return [str(parsed)]
    except ValueError:
        return [part.strip() for part in raw.split(",") if part.strip()]


def run(ctx, table):
    column = str(ctx.params.get("column", "")).strip()
    if not column:
        raise ValueError(
            "no column selected — set 'Column' in the node's properties")
    if column not in table.columns:
        available = ", ".join(str(c) for c in table.columns)
        raise ValueError(f"column {column!r} not in table (has: {available})")

    selected = _selected_values(ctx.params.get("selected", ""))
    if str(ctx.params.get("mode", "multi")).strip() == "single":
        # a hand-edited param could still hold more than one value; single
        # mode only ever honours the first
        selected = selected[:1]
    if not selected:
        return {"table": table}
    filtered = table[table[column].astype(str).isin(selected)]
    ctx.log(f"slicer on {column!r}: kept {len(filtered)} of {len(table)} rows")
    return {"table": filtered}
