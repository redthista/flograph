"""Diff Tables

Compare two versions of the same table on a set of key columns and split the
difference into **added** (keys only in *new*), **removed** (keys only in
*old*), **changed** (keys in both, some non-key value differs) and
**unchanged**. The `summary` output is a one-row table with the four counts.

The **changed** frame carries every compared column twice — `col__old` and
`col__new` — so a downstream Show Table reads as a before/after list. Set
**Compare columns** to limit which non-key columns count as a change (blank =
all columns the two tables share).

Use it on last-night's and tonight's snapshot to find exactly what moved:
price changes, status flips, new or retired records.
"""
NODE = {
    "label": "Diff Tables",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("old", "dataframe"), ("new", "dataframe")],
    "outputs": [
        ("added", "dataframe"),
        ("removed", "dataframe"),
        ("changed", "dataframe"),
        ("unchanged", "dataframe"),
        ("summary", "dataframe"),
    ],
}
PARAMS = [
    {"name": "keys", "type": "columns", "label": "Key columns",
     "default": "", "placeholder": "id  (comma separated)"},
    {"name": "compare", "type": "columns", "label": "Compare columns",
     "default": "", "placeholder": "empty = all shared non-key columns"},
]


def _cols(raw):
    return [c.strip() for c in (raw or "").split(",") if c.strip()]


def run(ctx, old, new):
    import pandas as pd

    keys = _cols(ctx.params.get("keys"))
    if not keys:
        raise ValueError("no key columns — set 'Key columns' to the column(s) "
                         "that identify a row across both tables")
    for side, df in (("old", old), ("new", new)):
        missing = [k for k in keys if k not in df.columns]
        if missing:
            raise ValueError(f"key column(s) {missing} not in the {side} table")

    if old.duplicated(keys).any() or new.duplicated(keys).any():
        raise ValueError("the key columns are not unique — a diff needs one "
                         "row per key on each side")

    compare = _cols(ctx.params.get("compare"))
    shared = [c for c in old.columns if c in new.columns and c not in keys]
    if compare:
        unknown = [c for c in compare if c not in shared]
        if unknown:
            raise ValueError(f"compare column(s) {unknown} are not shared "
                             f"non-key columns (shared: {shared or 'none'})")
        shared = compare

    o = old.set_index(keys, drop=False)
    n = new.set_index(keys, drop=False)
    o_keys, n_keys = o.index, n.index

    added = new[n_keys.isin(o_keys) == False].reset_index(drop=True)   # noqa: E712
    removed = old[o_keys.isin(n_keys) == False].reset_index(drop=True)  # noqa: E712

    both = o_keys.intersection(n_keys)
    changed_rows = []
    unchanged_keys = []
    for key in both:
        orow, nrow = o.loc[key], n.loc[key]
        diffs = {}
        for c in shared:
            ov, nv = orow[c], nrow[c]
            same = (ov == nv) or (pd.isna(ov) and pd.isna(nv))
            if not same:
                diffs[c] = (ov, nv)
        if diffs:
            rec = {k: nrow[k] for k in keys}
            for c in shared:
                rec[f"{c}__old"] = orow[c]
                rec[f"{c}__new"] = nrow[c]
            rec["_changed"] = ", ".join(diffs)
            changed_rows.append(rec)
        else:
            unchanged_keys.append(key)

    changed_cols = list(keys)
    for c in shared:
        changed_cols += [f"{c}__old", f"{c}__new"]
    changed_cols.append("_changed")
    changed = pd.DataFrame(changed_rows, columns=changed_cols)

    unchanged = (n.loc[unchanged_keys].reset_index(drop=True)
                 if unchanged_keys else new.iloc[0:0].reset_index(drop=True))

    summary = pd.DataFrame([{
        "added": len(added), "removed": len(removed),
        "changed": len(changed), "unchanged": len(unchanged),
    }])
    ctx.log(f"+{len(added)}  -{len(removed)}  ~{len(changed)}  "
            f"={len(unchanged)}")
    return {"added": added, "removed": removed, "changed": changed,
            "unchanged": unchanged, "summary": summary}
