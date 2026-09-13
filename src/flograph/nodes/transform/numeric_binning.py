"""Numeric Binning

Cut a numeric column into buckets and add a column that says which bucket
each row falls into — the thing you'd write `pd.cut` / `pd.qcut` for.
Ready-made segments for Group By, a Slicer, or a chart axis: customer
lifetime value into high / medium / low tiers, revenue into bands, a
skewed measure into equal-sized groups.

**Method** decides the bucket shapes. *Fixed width* divides the range into
equal spans; *quantile* splits the rows into equal-sized groups (right
when one band would otherwise swallow the data); *custom edges* bins to
boundaries you name (`0, 100, 250, 500`). *Bins* counts the buckets for
the first two; *Edges* supplies them for the last.

Auto labels are the interval (`(100, 250]`); give comma-separated
**Labels** to name the buckets yourself (`low, medium, high`) — they must
number the same as the bins. Rows that aren't numbers stay unlabelled
(or take the **Missing label** when one is given). **Closed on the right**
makes a bin own its top edge; turn it off for `[100, 250)`.
"""
NODE = {
    "label": "Numeric Binning",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "column", "type": "columns", "label": "Value column",
     "default": "", "multi": False},
    {"name": "method", "type": "choice", "label": "Method",
     "options": ["fixed width", "quantile", "custom edges"],
     "default": "fixed width"},
    {"name": "bins", "type": "int", "label": "Bins", "default": 4, "min": 2},
    {"name": "edges", "type": "string", "label": "Edges", "default": "",
     "placeholder": "e.g. 0, 100, 250, 500"},
    {"name": "labels", "type": "string", "label": "Labels", "default": "",
     "placeholder": "e.g. low, medium, high — one per bin"},
    {"name": "missing_label", "type": "string", "label": "Missing label",
     "default": "", "placeholder": "for rows that aren't numbers"},
    {"name": "output_column", "type": "string", "label": "New column",
     "default": "", "placeholder": "empty = {column}.bin"},
    {"name": "drop_source", "type": "bool", "label": "Drop the value column",
     "default": False},
    {"name": "right", "type": "bool", "label": "Closed on the right",
     "default": True},
]


def _parse_labels(raw):
    text = (raw or "").strip()
    return [part.strip() for part in text.split(",")] if text else None


def _parse_edges(raw):
    text = (raw or "").strip()
    try:
        edges = [float(part.strip()) for part in text.split(",") if part.strip()]
    except ValueError:
        raise ValueError(
            f"'{text}' isn't a list of numbers — put the edges as "
            "comma-separated numbers, e.g. 0, 100, 250, 500")
    if len(edges) < 2:
        raise ValueError(
            "'Edges' needs at least two numbers, e.g. 0, 100, 250, 500")
    if edges != sorted(edges):
        raise ValueError("'Edges' must be in ascending order")
    return edges


def _check_labels(labels, nbins):
    if labels is not None and len(labels) != nbins:
        raise ValueError(
            f"got {len(labels)} labels for {nbins} bins — one label per bin")


def run(ctx, table):
    import pandas as pd

    p = ctx.params
    column = (p.get("column") or "").strip()
    if not column:
        raise ValueError("no column selected — set 'Value column'")
    if column not in table.columns:
        raise ValueError(f"column {column!r} not in table")
    method = p["method"]
    out_name = (p.get("output_column") or "").strip() or f"{column}.bin"

    values = pd.to_numeric(table[column], errors="coerce")
    if values.notna().sum() == 0:
        raise ValueError(
            f"column {column!r} has no values that read as numbers — "
            "convert it to a number type first")
    labels = _parse_labels(p.get("labels"))
    missing = (p.get("missing_label") or "").strip()
    right = bool(p.get("right", True))

    if method == "fixed width":
        nbins = max(2, int(p.get("bins", 4) or 4))
        _check_labels(labels, nbins)
        binned = pd.cut(values, bins=nbins, labels=labels, right=right)
    elif method == "quantile":
        nbins = max(2, int(p.get("bins", 4) or 4))
        _, edges = pd.qcut(values, q=nbins, retbins=True,
                           duplicates="drop")
        if len(edges) < 2:
            raise ValueError(
                f"column {column!r} has too few distinct values to split "
                f"into {nbins} quantile bins")
        nbins = len(edges) - 1
        _check_labels(labels, nbins)
        binned = pd.cut(values, bins=edges, labels=labels,
                        include_lowest=True, right=right)
    elif method == "custom edges":
        edges = _parse_edges(p.get("edges"))
        mn, mx = values.min(), values.max()
        if mn < edges[0] or mx > edges[-1]:
            raise ValueError(
                f"values in {column!r} run from {mn} to {mx}, outside the "
                f"edges {edges[0]}…{edges[-1]} — widen the edges")
        nbins = len(edges) - 1
        _check_labels(labels, nbins)
        binned = pd.cut(values, bins=edges, labels=labels,
                        include_lowest=True, right=right)
    else:  # pragma: no cover - guarded by the choice widget
        raise ValueError(f"unknown method {method!r}")

    if missing:
        binned = binned.cat.add_categories([missing]).fillna(missing)

    result = table.copy(deep=False)
    result[out_name] = binned
    if p.get("drop_source", False) and out_name != column:
        result = result.drop(columns=[column])
    ctx.log(f"binned {column!r} into {nbins} {method} bucket(s) "
            f"→ {out_name!r}")
    return result