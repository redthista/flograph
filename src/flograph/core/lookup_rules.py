"""Mapping-directed managed lookups. Imports pandas only when called."""


def enrich(ctx, table, folder, rules):
    import pandas as pd
    import numpy as np
    from .managed_folder import read_table

    source_column = ctx.params.get("source_column", "filename").strip()
    required = ["source_file", "lookup_file", "left_on", "right_on"]
    missing = [c for c in required if c not in rules.columns]
    if missing:
        raise ValueError(f"Lookup rules need columns: {', '.join(required)}; missing {missing}")
    if source_column not in table.columns:
        raise ValueError(f"Source filename column {source_column!r} is missing from the main table")
    if not table.columns.is_unique or not rules.columns.is_unique:
        raise ValueError("Main data and rules must have unique column names")
    result = table.copy(deep=False)
    groups = table.groupby(source_column, sort=False, observed=True, dropna=False).indices
    cache, diagnostics, assigned = {}, [], {}
    covered = np.zeros(len(table), dtype=bool)

    def report(reason, source, lookup, rule, *, row=None, keys=None, columns="", detail=""):
        diagnostics.append({"rule_row": rule, "source_file": source, "lookup_file": lookup,
                            "main_row": row, "key_values": keys, "columns": columns,
                            "reason": reason, "detail": detail})

    def text(value):
        return "" if pd.isna(value) else str(value).strip()

    def names(value):
        return [n.strip() for n in text(value).split(",") if n.strip()]

    for rule_number, rule in enumerate(rules.to_dict("records"), 1):
        ctx.check_cancelled()
        source, filename = text(rule["source_file"]), text(rule["lookup_file"])
        positions = groups.get(source)
        if positions is None:
            report("source_not_found", source, filename, rule_number,
                   detail="No main-table rows have this source filename")
            continue
        covered[positions] = True
        left, right = names(rule["left_on"]), names(rule["right_on"])
        if not left or len(left) != len(right) or len(set(left)) != len(left) or len(set(right)) != len(right):
            report("invalid_join_keys", source, filename, rule_number,
                   detail="Provide the same number of unique comma-separated left and right columns")
            continue
        missing = [c for c in left if c not in table.columns]
        if missing:
            report("missing_main_columns", source, filename, rule_number, columns=", ".join(missing))
            continue
        options = {key: text(rule.get(key, "")) or ctx.params.get(key, default)
                   for key, default in (("encoding", "utf-8"), ("separator", ","), ("sheet", ""))}
        options["format"] = text(rule.get("format", "")) or "auto"
        cache_key = (filename, *options.values())
        if cache_key not in cache:
            try:
                cache[cache_key] = read_table(folder, filename, **options)
            except Exception as exc:
                # A bad lookup is diagnostic data, not a reason to lose the main data.
                cache[cache_key] = exc
        lookup = cache[cache_key]
        if isinstance(lookup, Exception):
            report("missing_lookup_file" if isinstance(lookup, FileNotFoundError) else "lookup_read_error",
                   source, filename, rule_number, detail=str(lookup))
            continue
        if not lookup.columns.is_unique:
            report("duplicate_lookup_columns", source, filename, rule_number)
            continue
        selected = names(rule.get("columns", "")) or [c for c in lookup.columns if c not in right]
        selected = list(dict.fromkeys(c for c in selected if c not in right))
        missing = [c for c in right + selected if c not in lookup.columns]
        if missing:
            report("missing_lookup_columns", source, filename, rule_number, columns=", ".join(missing))
            continue
        missing_keys = lookup[right].isna().any(axis=1) | lookup[right].eq("").any(axis=1)
        if missing_keys.any():
            report("missing_lookup_key", source, filename, rule_number, columns=", ".join(right),
                   detail=f"{int(missing_keys.sum())} lookup rows have incomplete keys and were excluded")
            lookup = lookup.loc[~missing_keys]
        if lookup.duplicated(subset=right).any():
            report("duplicate_lookup_keys", source, filename, rule_number,
                   detail="Lookup keys must be unique; no rows were expanded")
            continue
        # Join only keys plus selected values; integer column ids avoid all suffix collisions.
        payload = lookup[right + selected].copy(deep=False)
        payload.columns = list(range(len(payload.columns)))
        keys = table.iloc[positions][left].copy(deep=False)
        keys.columns = list(range(len(right)))
        marker = len(payload.columns)
        payload = payload.copy(deep=False)
        payload[marker] = np.arange(len(payload))
        try:
            merged = keys.merge(payload, on=list(range(len(right))), how="left", sort=False, validate="many_to_one")
        except (ValueError, TypeError) as exc:
            report("join_error", source, filename, rule_number, detail=str(exc))
            continue
        matched = merged[marker].notna().to_numpy()
        incomplete_main = (keys.isna().any(axis=1) | keys.eq("").any(axis=1)).to_numpy()
        for local in np.flatnonzero(~matched):
            report("missing_main_key" if incomplete_main[local] else "key_not_found", source, filename, rule_number, row=int(positions[local]),
                   keys=tuple(keys.iloc[local]), detail="Main key was not found in this lookup")
        used = merged.loc[matched, marker].to_numpy(dtype=int)
        unused = np.ones(len(lookup), dtype=bool)
        unused[used] = False
        for local in np.flatnonzero(unused):
            report("lookup_key_unused", source, filename, rule_number,
                   keys=tuple(lookup.iloc[local][right]), detail=f"Lookup row {lookup.index[local]} has no matching main row for this source")
        for offset, column in enumerate(selected, len(right)):
            if column in table.columns:
                report("column_already_exists", source, filename, rule_number, columns=str(column),
                       detail="Original main column retained; duplicate lookup column omitted")
                continue
            written = assigned.setdefault(column, np.zeros(len(table), dtype=bool))
            conflict = written[positions] & matched
            if conflict.any():
                report("conflicting_rules", source, filename, rule_number, columns=str(column),
                       detail=f"{int(conflict.sum())} rows already populated by an earlier rule; earlier values retained")
            if column not in result.columns:
                result[column] = pd.Series([pd.NA] * len(result), index=result.index, dtype=object)
            values = merged[offset]
            for local in np.flatnonzero(matched & values.isna().to_numpy()):
                report("empty_lookup_value", source, filename, rule_number, row=int(positions[local]),
                       keys=tuple(keys.iloc[local]), columns=str(column))
            target = matched & ~conflict
            result.iloc[positions[target], result.columns.get_loc(column)] = values.to_numpy()[target]
            written[positions[target]] = True
        ctx.progress(rule_number / max(len(rules), 1))
    for pos in np.flatnonzero(~covered):
        report("no_rule", table.iloc[pos][source_column], "", None, row=int(pos),
               detail="No lookup rule applies to this source filename")
    columns = ["rule_row", "source_file", "lookup_file", "main_row", "key_values", "columns", "reason", "detail"]
    return {"table": result, "diagnostics": pd.DataFrame(diagnostics, columns=columns)}
