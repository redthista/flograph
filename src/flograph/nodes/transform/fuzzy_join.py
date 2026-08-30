"""Fuzzy Join

Join two tables on columns that *nearly* match — company names with and
without "Ltd", addresses typed two ways, product titles from two systems.
For each left row it finds the best-scoring right row above the **threshold**
and merges them; unmatched left rows come through with blank right columns
when **Keep unmatched** is on.

Scoring uses rapidfuzz. Pick a **scorer**:

    ratio            — plain edit-distance similarity
    partial_ratio    — best matching substring (good for "ACME" vs "ACME Corp")
    token_sort_ratio — word order ignored ("John Smith" vs "Smith, John")
    token_set_ratio  — extra words ignored

The added `match_score` column (0–100) shows how close each match was, so you
can eyeball the borderline ones. Needs the `rapidfuzz` package.
"""
NODE = {
    "label": "Fuzzy Join",
    "category": "Transform",
    "version": "1.0",
    "inputs": [("left", "dataframe"), ("right", "dataframe")],
    "outputs": [("joined", "dataframe"), ("unmatched", "dataframe")],
}
PARAMS = [
    {"name": "left_on", "type": "columns", "label": "Left column",
     "default": "", "multi": False},
    {"name": "right_on", "type": "columns", "label": "Right column",
     "default": "", "multi": False},
    {"name": "scorer", "type": "choice", "label": "Scorer",
     "options": ["ratio", "partial_ratio", "token_sort_ratio",
                 "token_set_ratio"], "default": "token_sort_ratio"},
    {"name": "threshold", "type": "int", "label": "Threshold (0–100)",
     "default": 85, "min": 0, "max": 100},
    {"name": "case_insensitive", "type": "bool", "label": "Ignore case",
     "default": True},
    {"name": "keep_unmatched", "type": "bool", "label": "Keep unmatched left rows",
     "default": True},
    {"name": "suffix", "type": "string", "label": "Right-column suffix",
     "default": "_right", "placeholder": "for name clashes"},
]


def run(ctx, left, right):
    import pandas as pd
    from rapidfuzz import fuzz, process, utils

    p = ctx.params
    lcol = (p.get("left_on") or "").strip()
    rcol = (p.get("right_on") or "").strip()
    if not lcol or not rcol:
        raise ValueError("set both 'Left column' and 'Right column'")
    if lcol not in left.columns:
        raise ValueError(f"left column {lcol!r} not in the left table")
    if rcol not in right.columns:
        raise ValueError(f"right column {rcol!r} not in the right table")

    scorer = {
        "ratio": fuzz.ratio,
        "partial_ratio": fuzz.partial_ratio,
        "token_sort_ratio": fuzz.token_sort_ratio,
        "token_set_ratio": fuzz.token_set_ratio,
    }[p["scorer"]]
    threshold = float(p.get("threshold", 85))
    processor = utils.default_process if p.get("case_insensitive", True) else None

    right_keys = right[rcol].astype("string").fillna("").tolist()
    left_keys = left[lcol].astype("string").fillna("").tolist()

    suffix = p.get("suffix") or "_right"
    clashes = set(left.columns) & set(right.columns)
    right_renamed = right.rename(
        columns={c: f"{c}{suffix}" for c in clashes})
    right_cols = list(right_renamed.columns)

    matched_rows = []
    unmatched_idx = []
    total = len(left_keys)
    for i, key in enumerate(left_keys):
        if i % 200 == 0:
            ctx.check_cancelled()
            ctx.progress(i / max(total, 1))
        best = process.extractOne(
            key, right_keys, scorer=scorer, processor=processor,
            score_cutoff=threshold) if key else None
        lrow = left.iloc[i].to_dict()
        if best is None:
            unmatched_idx.append(i)
            if p.get("keep_unmatched", True):
                row = dict(lrow)
                row["match_score"] = pd.NA
                for c in right_cols:
                    row.setdefault(c, pd.NA)
                matched_rows.append(row)
        else:
            _, score, ridx = best
            row = dict(lrow)
            row.update(right_renamed.iloc[ridx].to_dict())
            row["match_score"] = round(float(score), 1)
            matched_rows.append(row)

    ctx.progress(1.0)
    ordered = list(left.columns) + [
        c for c in right_cols if c not in left.columns] + ["match_score"]
    joined = pd.DataFrame(matched_rows).reindex(columns=ordered)
    unmatched = left.iloc[unmatched_idx].reset_index(drop=True)
    ctx.log(f"matched {total - len(unmatched_idx)} / {total} left rows "
            f"(threshold {threshold:g})")
    return {"joined": joined, "unmatched": unmatched}
