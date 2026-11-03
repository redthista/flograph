"""Lookup Chooser

Enrich each row using the lookup filename in that row. Connect your data
table and a Managed Folder, choose Filename column, then set Left columns
and Right columns. For multiple keys, enter comma-separated names in the
same order, e.g. product,region on the left and sku,area on the right.

Each distinct lookup file is read once per run. This is a left join: every
input row remains in its original order; unmatched keys get empty lookup
values. Lookup keys must be unique within each file, so a lookup cannot
accidentally multiply your rows. Missing/blank filenames or missing files
stop with an explanation. Existing main columns are retained and duplicate right join keys omitted.

Connect rules to apply multiple lookups per source file. Rules columns are
source_file, lookup_file, left_on, right_on, and optional columns (blank =
all lookup value columns). Optional rule columns encoding, separator, sheet
and format override the node defaults for mixed file types. The diagnostics
output explains incomplete matches.
"""
NODE = {
    "label": "Lookup Chooser", "category": "Transform", "version": "1.2",
    "inputs": [("table", "dataframe"),
               ("rules", "dataframe", {"optional": True}),
               ("folder", "object", {"suggest": ["flograph.io.managed_folder"]})],
    "outputs": [("table", "dataframe"), ("diagnostics", "dataframe")],
}
PARAMS = [
    {"name": "source_column", "type": "columns", "multi": False,
     "label": "Source filename column (with rules)", "default": "filename"},
    {"name": "columns", "type": "string", "label": "Columns to return (optional)",
     "default": "", "placeholder": "empty = all lookup values; otherwise comma-separated"},
    {"name": "filename_column", "type": "columns", "multi": False,
     "label": "Filename column", "default": "", "placeholder": "e.g. lookup_file"},
    {"name": "left_on", "type": "columns", "label": "Left columns (data)",
     "default": "", "placeholder": "product, region"},
    {"name": "right_on", "type": "string", "label": "Right columns (lookup)",
     "default": "", "placeholder": "sku, area — same order as left columns"},
    {"name": "separator", "type": "string", "label": "CSV separator", "default": ","},
    {"name": "sheet", "type": "string", "label": "Excel sheet (empty = first)", "default": ""},
    {"name": "encoding", "type": "string", "default": "utf-8"},
]


def run(ctx, table, folder, rules=None):
    import pandas as pd
    from flograph.core.managed_folder import ManagedFolder, read_table
    if not isinstance(folder, ManagedFolder):
        raise TypeError("Connect a Managed Folder to folder")
    if rules is not None:
        from flograph.core.lookup_rules import enrich
        return enrich(ctx, table, folder, rules)
    filename_column = ctx.params.get("filename_column", "").strip()
    left = [c.strip() for c in ctx.params.get("left_on", "").split(",") if c.strip()]
    right = [c.strip() for c in ctx.params.get("right_on", "").split(",") if c.strip()]
    if not filename_column or filename_column not in table.columns:
        raise ValueError("Choose a Filename column that exists in the data table")
    if not left or not right or len(left) != len(right):
        raise ValueError("Set Left columns and Right columns with the same number of comma-separated names")
    if len(set(left)) != len(left) or len(set(right)) != len(right):
        raise ValueError("Each join column must be listed only once")
    missing = [c for c in left if c not in table.columns]
    if missing:
        raise ValueError(f"Left columns missing from the data table: {missing}")
    filenames = table[filename_column]
    if not all(isinstance(n, str) and n.strip() for n in filenames):
        raise ValueError("Every row needs a non-blank lookup filename in Filename column")
    if table.empty:
        return {"table": table.copy(deep=False), "diagnostics": pd.DataFrame()}
    ordinal = "__flograph_lookup_row__"
    while ordinal in table.columns:
        ordinal += "_"
    pieces = []
    diagnostics = []
    groups = table.groupby(filename_column, sort=False, observed=True).indices
    names = list(groups)
    for i, name in enumerate(names):
        ctx.check_cancelled()
        lookup = read_table(folder, name, separator=ctx.params.get("separator", ","),
                            sheet=ctx.params.get("sheet", ""), encoding=ctx.params.get("encoding", "utf-8"))
        missing = [c for c in right if c not in lookup.columns]
        if missing:
            raise ValueError(f"Right columns missing from {name!r}: {missing}")
        if lookup.duplicated(subset=right).any():
            raise ValueError(f"Lookup keys in {name!r} are not unique; remove duplicates or add more join columns")
        selected = [c.strip() for c in ctx.params.get("columns", "").split(",") if c.strip()]
        if selected:
            missing = [c for c in selected if c not in lookup.columns]
            if missing:
                raise ValueError(f"Columns to return missing from {name!r}: {missing}")
        else:
            selected = [c for c in lookup.columns if c not in right]
        selected = [c for c in selected if c not in right and c not in table.columns]
        lookup = lookup[list(dict.fromkeys(right + selected))]
        while ordinal in lookup.columns:
            ordinal += "_"
        positions = groups[name]
        rows = table.iloc[positions].copy(deep=False)
        rows[ordinal] = positions
        indicator = ordinal + "_match"
        while indicator in rows.columns or indicator in lookup.columns:
            indicator += "_"
        joined = rows.merge(lookup, how="left", left_on=left, right_on=right,
                            suffixes=("", "_lookup"), validate="many_to_one", sort=False,
                            indicator=indicator)
        for _, failed in joined.loc[joined[indicator] == "left_only"].iterrows():
            diagnostics.append({"main_row": int(failed[ordinal]), "lookup_file": name,
                                "key_values": tuple(failed[c] for c in left), "reason": "key_not_found"})
        joined = joined.drop(columns=indicator)
        # Keep the ordering helper out of user columns and consistent across files.
        order = joined.pop(ordinal).to_numpy()
        joined = joined.drop(columns=[c for c in right if c not in table.columns], errors="ignore")
        pieces.append((joined, order))
        ctx.progress((i + 1) / len(names))
    import numpy as np
    order = np.concatenate([p[1] for p in pieces])
    combined = pd.concat([p[0] for p in pieces], ignore_index=True, sort=False)
    permutation = np.argsort(order, kind="stable")
    combined = combined.iloc[permutation]
    combined.index = table.index.take(order[permutation])
    ctx.log(f"Applied {len(names)} lookup file(s) to {len(table)} rows")
    return {"table": combined, "diagnostics": pd.DataFrame(diagnostics, columns=["main_row", "lookup_file", "key_values", "reason"])}
