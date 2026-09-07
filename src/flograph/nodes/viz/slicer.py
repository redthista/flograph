"""Slicer

A Power BI/Excel-style interactive filter: pick a column and the card shows
that column's values right on the canvas, with a search box to find values
and Select All / None shortcuts. Ticking values filters the table flowing
through and automatically re-runs everything downstream, so the visuals
that follow stay live. With nothing ticked the table passes through
unfiltered.

**Several columns make a tree.** Name more than one column — "region,
store" — and the card becomes a hierarchy: regions at the top, their stores
underneath. Ticking a region means the whole region (its children fill in),
ticking one store narrows to that store, and a region with only some of its
stores ticked draws a part-filled box. That is Power BI's multi-field
slicer, and it saves wiring three chained slicers to answer one question.

**Layout** picks how the values are drawn, the way Power BI's format pane
does: "list" is the checkbox list (a tree when there is more than one
column), "cards" draws each value as a tile you click, and "dropdown" folds
the whole thing behind a button that says what is picked — for a dashboard
where a slicer should cost one line, not a panel. All three drive the same
selection, so switching between them changes nothing but the picture.

"Selection" switches between the two slicer styles those tools offer:
"multi" is a checkbox list (any number of ticks); "single" is a radio-style
list where picking one value clears any other and clicking it again clears
the selection entirely.

**Standalone.** The table input is optional. With nothing wired in, type the
values into "Values (one per line)" and the slicer becomes a plain value
picker — no data needed. Its "table" output is then a table of whatever is
ticked (its columns named after "Column(s)", or "value"), so it can still
feed a Join, or the "options" input of a Choice node, or another Slicer.
With several columns, write a line as "north > store A".

**Chaining.** The "selected" output carries the ticked values as a list
whatever the mode and however deep the tree — the deepest value of each
selection — so one picker can drive the options of the next: region picks a
region, and the store slicer beside it only offers that region's stores.

Values are matched as strings; "Selected values" holds the ticked ones as a
JSON array (["north", "south"], or [["north", "store A"]] once there is
more than one level; a comma-separated list, with ">" between levels, also
works when editing by hand).
"""
NODE = {
    "label": "Slicer",
    "category": "Viz",
    "version": "1.1",
    "card": "slicer",
    "inputs": [("table", "dataframe", {"optional": True})],
    "outputs": [("table", "dataframe"), ("selected", "any")],
}
PARAMS = [
    {"name": "column", "type": "columns", "label": "Column(s)",
     "default": "", "multi": True,
     "placeholder": "one column, or several for a tree (region, store)"},
    {"name": "mode", "type": "choice", "label": "Selection",
     "options": ["multi", "single"], "default": "multi"},
    {"name": "selected", "type": "string", "label": "Selected values",
     "default": "", "placeholder": 'Ticked values, e.g. ["north", "south"] '
                                   "— blank keeps every row"},
    {"name": "values", "type": "text", "label": "Values (one per line)",
     "default": "", "placeholder": "Used only when no table is connected"},
    # Presentation only — run() reads none of the four below, and dirtying
    # on one would re-filter the table and re-run every visual downstream to
    # produce the exact same rows.
    {"name": "layout", "type": "choice", "label": "Layout",
     "options": ["list", "cards", "dropdown"], "default": "list",
     "cosmetic": True},
    {"name": "show_counts", "type": "bool", "label": "Show row counts",
     "default": False, "cosmetic": True},
    {"name": "width", "type": "int", "label": "Width",
     "default": 200, "min": 140, "max": 600, "cosmetic": True},
    # the floor is 150 for every layout but "dropdown", which is one button
    # and is clamped up by the card when it is not
    {"name": "height", "type": "int", "label": "Height",
     "default": 240, "min": 66, "max": 2000, "cosmetic": True},
]


def run(ctx, table=None):
    import pandas as pd

    from flograph.core.controls import lines_to_values
    from flograph.core.slicer import (leaf_values, matches, normalise,
                                      parse_path, selected_paths,
                                      slicer_columns)

    columns = slicer_columns(ctx.params.get("column", ""))
    picked = normalise(selected_paths(ctx.params.get("selected", "")))
    if str(ctx.params.get("mode", "multi")).strip() == "single":
        # a hand-edited param could still hold more than one selection;
        # single mode only ever honours the first
        picked = picked[:1]

    if table is None:
        # standalone: nothing to filter, so the picker *is* the data. The
        # ticked values become a table, which is what makes an unconnected
        # slicer useful as a source rather than a dead end.
        names = columns or ["value"]
        depth = len(names)
        rows = []
        for line in lines_to_values(ctx.params.get("values", "")):
            path = parse_path(line)[:depth] if depth > 1 else (line,)
            if path and (not picked or matches(path, picked)):
                rows.append(list(path) + [None] * (depth - len(path)))
        ctx.log(f"standalone slicer: {len(rows)} values")
        return {"table": pd.DataFrame(rows, columns=names),
                "selected": leaf_values(tuple(r) for r in rows)}

    if not columns:
        raise ValueError(
            "no column selected — set 'Column(s)' in the node's properties")
    missing = [c for c in columns if c not in table.columns]
    if missing:
        available = ", ".join(str(c) for c in table.columns)
        raise ValueError(
            f"column {missing[0]!r} not in table (has: {available})")

    if not picked:
        return {"table": table, "selected": []}

    # One boolean mask per selected path, OR'd together: a path of fewer
    # values than there are columns is a *prefix*, and keeps every row it
    # prefixes — which is what makes ticking a parent mean "all of it"
    # without its children having to be listed.
    keep = pd.Series(False, index=table.index)
    for path in picked:
        mask = pd.Series(True, index=table.index)
        for column, value in zip(columns, path):
            mask &= table[column].astype(str) == value
        keep |= mask
    filtered = table[keep]
    where = ", ".join(repr(c) for c in columns)
    ctx.log(f"slicer on {where}: kept {len(filtered)} of {len(table)} rows")
    return {"table": filtered, "selected": leaf_values(picked)}
