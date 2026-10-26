"""Train/Test Split

Cut a table into two: rows to learn from (**train**) and rows kept back to
check the model on (**test**). A model scored on the rows it learned from
looks better than it is; the test rows are the honest score.

**Test share** is the fraction held back — 0.2 keeps one row in five.
**Seed** fixes which rows: the same seed always makes the same split, so a
re-run compares like with like. Untick **Shuffle** to hold back the *last*
rows instead — what you want for anything in time order, where testing on
the past with a model trained on the future would flatter it.

**Stratify by** a column — usually the class you are predicting — keeps that
column's mix the same in both halves, so a rare class can't end up missing
from the test rows by chance.

Both halves keep the input's columns and row order.
"""
NODE = {
    "label": "Train/Test Split",
    "category": "ML",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("train", "dataframe"), ("test", "dataframe")],
}
PARAMS = [
    {"name": "test_size", "type": "float", "label": "Test share",
     "default": 0.2, "min": 0.01, "max": 0.99},
    {"name": "stratify", "type": "columns", "label": "Stratify by",
     "default": "", "multi": False, "placeholder": "(none)"},
    {"name": "shuffle", "type": "bool", "label": "Shuffle", "default": True},
    {"name": "seed", "type": "int", "label": "Seed", "default": 0},
]


def _held_back(n, share):
    """How many of `n` rows go to test: at least one, and never all."""
    if n < 2:
        return 0
    return min(n - 1, max(1, int(round(n * share))))


def run(ctx, table):
    import numpy as np

    p = ctx.params
    share = float(p["test_size"])
    if not 0 < share < 1:
        raise ValueError("'Test share' must be between 0 and 1")
    if len(table) < 2:
        raise ValueError("need at least two rows to split")
    rng = np.random.default_rng(int(p["seed"]))
    shuffle = bool(p["shuffle"])
    column = str(p.get("stratify", "")).strip()

    if column:
        if column not in table.columns:
            raise ValueError(f"column {column!r} not in table")
        if not shuffle:
            raise ValueError("'Stratify by' needs 'Shuffle' on — holding "
                             "back the last rows can't keep the mix")
        keys = table[column].astype("object").where(table[column].notna(),
                                                    "\x00missing")
        test_at = []
        for _, where in keys.groupby(keys, sort=False).indices.items():
            picked = rng.permutation(where)
            test_at.extend(picked[:_held_back(len(where), share)])
    elif shuffle:
        test_at = rng.permutation(len(table))[:_held_back(len(table), share)]
    else:
        test_at = range(len(table) - _held_back(len(table), share),
                        len(table))

    mask = np.zeros(len(table), dtype=bool)
    mask[list(test_at)] = True
    train, test = table[~mask], table[mask]
    ctx.log(f"{len(train)} train / {len(test)} test rows"
            + (f", stratified by {column}" if column else "")
            + ("" if shuffle else " (last rows held back)"))
    return {"train": train, "test": test}
