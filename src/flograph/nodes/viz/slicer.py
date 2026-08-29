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

**Standalone.** The table input is optional. With nothing wired in, type the
values into "Values (one per line)" and the slicer becomes a plain value
picker — no data needed. Its "table" output is then a one-column table of
whatever is ticked (named after "Column", or "value"), so it can still feed
a Join, or the "options" input of a Choice node, or another Slicer.

**Chaining.** The "selected" output carries the ticked values as a list
whatever the mode, so one picker can drive the options of the next: region
picks a region, and the store slicer beside it only offers that region's
stores.

Values are matched as strings; "Selected values" holds the ticked ones as a
JSON array (a comma-separated list also works when editing by hand).
"""
NODE = {
    "label": "Slicer",
    "category": "Viz",
    "version": "1.0",
    "card": "slicer",
    "inputs": [("table", "dataframe", {"optional": True})],
    "outputs": [("table", "dataframe"), ("selected", "any")],
}
PARAMS = [
    {"name": "column", "type": "columns", "label": "Column",
     "default": "", "multi": False},
    {"name": "mode", "type": "choice", "label": "Selection",
     "options": ["multi", "single"], "default": "multi"},
    {"name": "selected", "type": "string", "label": "Selected values",
     "default": "", "placeholder": 'Ticked values, e.g. ["north", "south"] '
                                   "— blank keeps every row"},
    {"name": "values", "type": "text", "label": "Values (one per line)",
     "default": "", "placeholder": "Used only when no table is connected"},
    {"name": "width", "type": "int", "label": "Width",
     "default": 200, "min": 140, "max": 600},
    {"name": "height", "type": "int", "label": "Height",
     "default": 240, "min": 120, "max": 2000},
]


def run(ctx, table=None):
    import pandas as pd

    from flograph.core.controls import lines_to_values, selected_values

    column = str(ctx.params.get("column", "")).strip()
    selected = selected_values(ctx.params.get("selected", ""))
    if str(ctx.params.get("mode", "multi")).strip() == "single":
        # a hand-edited param could still hold more than one value; single
        # mode only ever honours the first
        selected = selected[:1]

    if table is None:
        # standalone: nothing to filter, so the picker *is* the data. The
        # ticked values become a one-column table, which is what makes an
        # unconnected slicer useful as a source rather than a dead end.
        values = lines_to_values(ctx.params.get("values", ""))
        picked = [v for v in values if v in selected] if selected else values
        name = column or "value"
        ctx.log(f"standalone slicer: {len(picked)} of {len(values)} values")
        return {"table": pd.DataFrame({name: picked}), "selected": picked}

    if not column:
        raise ValueError(
            "no column selected — set 'Column' in the node's properties")
    if column not in table.columns:
        available = ", ".join(str(c) for c in table.columns)
        raise ValueError(f"column {column!r} not in table (has: {available})")

    if not selected:
        return {"table": table, "selected": []}
    filtered = table[table[column].astype(str).isin(selected)]
    ctx.log(f"slicer on {column!r}: kept {len(filtered)} of {len(table)} rows")
    return {"table": filtered, "selected": selected}
