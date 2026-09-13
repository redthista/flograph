"""AsOf Join

Time-based merge: for each row of the left table, take the closest row of the
right table by timestamp instead of by equality — the "latest reading no later
than this moment" join that `pd.merge_asof` and SQL ASOF joins do. The classic
use is matching events against a reference series (trades to FX rates, sensor
readings to config snapshots), where an exact-key join finds nothing because
the two clocks never line up.

Both tables are sorted by their timestamp column automatically (and it is
logged if the order had to change), so input order does not matter. **By**
adds equality keys that must also match — one asof join per key value, e.g.
match each trade to its own symbol's rate series. **Tolerance** caps how far a
match may reach (`30s`, `1d`, or a plain number for numeric clocks); rows with
no match in range get NaN for the right-side columns.
"""
NODE = {
    "label": "AsOf Join",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("left", "dataframe"), ("right", "dataframe")],
    "outputs": [("joined", "dataframe")],
}
PARAMS = [
    {"name": "left_on", "type": "columns", "label": "Left timestamp column",
     "default": "", "multi": False,
     "placeholder": "the time column in the left table"},
    {"name": "right_on", "type": "columns", "label": "Right timestamp column",
     "default": "", "multi": False,
     "placeholder": "empty = same name as the left one"},
    {"name": "direction", "type": "choice", "label": "Direction",
     "options": ["backward", "forward", "nearest"], "default": "backward"},
    {"name": "tolerance", "type": "string", "label": "Tolerance",
     "default": "", "placeholder": "e.g. 30s, 1d — empty = no limit"},
    {"name": "by", "type": "columns", "label": "By (equality keys)",
     "default": "", "multi": True,
     "placeholder": "comma separated; must match on both sides"},
    {"name": "suffixes_left", "type": "string", "label": "Left suffix",
     "default": "_left"},
    {"name": "suffixes_right", "type": "string", "label": "Right suffix",
     "default": "_right"},
]


def _col(raw):
    return (raw or "").strip()


def _as_time(series, side, col):
    """Timestamp columns may arrive as strings; convert them once so the
    merge runs on real datetimes. Numeric clocks pass through untouched."""
    import pandas as pd

    if pd.api.types.is_datetime64_any_dtype(series) \
            or pd.api.types.is_numeric_dtype(series):
        return series
    conv = pd.to_datetime(series, errors="coerce")
    if not conv.notna().any():
        raise ValueError(f"{side} timestamp column {col!r} is neither numeric"
                         " nor parseable as dates")
    return conv


def _sort_for_asof(frame, key):
    """merge_asof demands sorted keys; a stable sort on our own copy keeps the
    contract (inputs untouched) while making input order irrelevant."""
    before = list(frame.index)
    frame.sort_values(key, kind="stable", inplace=True)
    return list(frame.index) != before


def _tolerance(raw, kind):
    raw = (raw or "").strip()
    if not raw:
        return None
    import pandas as pd

    if kind in "Mm":
        try:
            return pd.Timedelta(raw)
        except (ValueError, TypeError):
            raise ValueError(f"tolerance {raw!r} is not a duration — try 30s,"
                             " 5m or 1d") from None
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"tolerance {raw!r} is neither a duration nor a"
                         " number") from None
    return int(value) if kind in "iu" else value


def run(ctx, left, right):
    import pandas as pd

    p = ctx.params
    l_on = _col(p.get("left_on"))
    if not l_on:
        raise ValueError("no left timestamp column — set 'Left timestamp"
                         " column'")
    r_on = _col(p.get("right_on")) or l_on
    by = [c.strip() for c in (p.get("by") or "").split(",") if c.strip()]

    for frame, side, col in ((left, "left", l_on), (right, "right", r_on)):
        if col not in frame.columns:
            raise ValueError(f"{side} timestamp column {col!r} not in the"
                             f" {side} table")
    missing = [c for c in by if c not in left.columns or c not in right.columns]
    if missing:
        raise ValueError(f"'By' column(s) {missing} missing from a side")

    left_s = left.copy(deep=False)
    left_s[l_on] = _as_time(left[l_on], "left", l_on)
    right_s = right.copy(deep=False)
    right_s[r_on] = _as_time(right[r_on], "right", r_on)

    moved_l = _sort_for_asof(left_s, [l_on])
    moved_r = _sort_for_asof(right_s, [r_on])
    tol = _tolerance(p.get("tolerance"), left_s[l_on].dtype.kind)

    kwargs = {
        "left_on": l_on,
        "right_on": r_on,
        "direction": p.get("direction") or "backward",
        "suffixes": (_col(p.get("suffixes_left")) or "_left",
                     _col(p.get("suffixes_right")) or "_right"),
    }
    if by:
        kwargs["by"] = by
    if tol is not None:
        kwargs["tolerance"] = tol

    joined = pd.merge_asof(left_s, right_s, **kwargs)
    detail = f"asof {kwargs['direction']} on {l_on!r}/{r_on!r}"
    if by:
        detail += f" by {', '.join(by)}"
    if tol is not None:
        detail += f" ±{tol}"
    if moved_l or moved_r:
        detail += " (sorted)"
    ctx.log(f"{detail} -> {len(joined)} rows")
    return joined
