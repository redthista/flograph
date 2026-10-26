"""Cross-Validation

A fairer score than one split: cut the rows into **Folds** parts, train on
all but one, score the one left out, and repeat until every part has been
the test once. The spread of the scores says how much luck was in any
single one.

Set the **Target**, **Feature columns**, **Task** and **Algorithm** just as
in Train Model — run two of these side by side with different algorithms to
choose between them before training the one you keep.

**Score** picks what is measured (*auto* is R² for regression, accuracy for
classification). **scores** has one row per fold with every metric;
**summary** has the mean and spread of each. Classification folds keep each
class's share (stratified), so no fold misses a class.

Needs scikit-learn (Tools ▸ Manage Packages…).
"""
NODE = {
    "label": "Cross-Validation",
    "category": "ML",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("scores", "dataframe"), ("summary", "dataframe")],
}
PARAMS = [
    {"name": "target_column", "type": "columns", "label": "Target",
     "default": "", "multi": False},
    {"name": "feature_columns", "type": "columns", "label": "Feature columns",
     "default": "", "placeholder": "empty = every other number column"},
    {"name": "task", "type": "choice", "label": "Task",
     "options": ["auto", "regression", "classification"], "default": "auto"},
    {"name": "algorithm", "type": "choice", "label": "Algorithm",
     "options": ["random forest", "gradient boosting", "linear", "ridge",
                 "lasso", "logistic"], "default": "random forest"},
    {"name": "folds", "type": "int", "label": "Folds",
     "default": 5, "min": 2, "max": 50},
    {"name": "scoring", "type": "choice", "label": "Score",
     "options": ["auto", "R2", "RMSE", "MAE", "MSE", "accuracy", "precision",
                 "recall", "F1"], "default": "auto"},
    {"name": "trees", "type": "int", "label": "Trees",
     "default": 100, "min": 1, "max": 5000,
     "visible_when": {"algorithm": ["random forest", "gradient boosting"]}},
    {"name": "seed", "type": "int", "label": "Seed", "default": 0},
]


def run(ctx, table):
    import pandas as pd

    from flograph.core import mlkit

    p = ctx.params
    target = str(p["target_column"]).strip()
    if not target:
        raise ValueError("no target — set 'Target' to the column to predict")
    if target not in table.columns:
        raise ValueError(f"column {target!r} not in table")
    rows = table[table[target].notna()]
    columns = mlkit.features(rows, p["feature_columns"], target)
    x = mlkit.matrix(rows, columns).to_numpy()
    y = rows[target]
    task = mlkit.resolve_task(p["task"], y)
    folds = int(p["folds"])
    if len(rows) < folds:
        raise ValueError(f"{len(rows)} rows can't make {folds} folds")

    scoring = p["scoring"]
    if scoring == "auto":
        scoring = "accuracy" if task == "classification" else "R2"
    expected = mlkit.metrics(task, [0, 1], [0, 1]).keys()
    if scoring not in expected:
        raise ValueError(f"{scoring!r} isn't a {task} score — pick one of: "
                         + ", ".join(expected))

    selection = mlkit.sklearn_module("sklearn.model_selection")
    if task == "classification":
        smallest = int(y.value_counts().min())
        if smallest < folds:
            raise ValueError(f"the rarest class has {smallest} row(s) — "
                             f"fewer than {folds} folds; lower 'Folds'")
        splitter = selection.StratifiedKFold(folds, shuffle=True,
                                             random_state=int(p["seed"]))
    else:
        splitter = selection.KFold(folds, shuffle=True,
                                   random_state=int(p["seed"]))

    labels = y.to_numpy()
    records = []
    for i, (train, test) in enumerate(splitter.split(x, labels), 1):
        ctx.check_cancelled()
        model = mlkit.build_model(task, p["algorithm"], p["seed"], p["trees"])
        model.fit(x[train], labels[train])
        scores = mlkit.metrics(task, labels[test], model.predict(x[test]))
        records.append({"fold": i, "rows": len(test), **scores})
        ctx.progress(i / folds)

    per_fold = pd.DataFrame(records)
    metric_cols = [c for c in per_fold.columns if c not in ("fold", "rows")]
    summary = pd.DataFrame({
        "metric": metric_cols,
        "mean": [per_fold[c].mean() for c in metric_cols],
        "std": [per_fold[c].std(ddof=0) for c in metric_cols],
        "min": [per_fold[c].min() for c in metric_cols],
        "max": [per_fold[c].max() for c in metric_cols],
    })
    # the chosen score first, so it is the row a Card picks up
    summary = pd.concat([summary[summary.metric == scoring],
                         summary[summary.metric != scoring]],
                        ignore_index=True)
    ctx.log(f"{folds}-fold {p['algorithm']} {task}: {scoring} "
            f"{per_fold[scoring].mean():.3g} ± {per_fold[scoring].std(ddof=0):.3g}")
    return {"scores": per_fold, "summary": summary}
