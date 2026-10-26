"""Train Model

Teach a model to predict one column from the others, and hand the trained
model on as a value — wire **model** into Predict to use it on new rows.

Name the **Target** — the column to predict. **Feature columns** are what it
learns from; leave them empty to use every other number column. Text columns
have to be turned into numbers first (One-Hot Encode or Label Encode), and
gaps filled (Missing Values) — the node says so rather than guessing.

**Task**: *regression* predicts a quantity (a price, a count); *classification*
predicts a class (churned or not, a product type). *auto* reads the target:
text or true/false is classification, numbers are regression.

**Algorithm**: *random forest* and *gradient boosting* are strong first
choices that need no scaling; *linear*, *ridge* and *lasso* (regression) and
*logistic* (classification) are simple and explainable, and do best on
scaled features. **Trees** sets how many trees the forest or boosting uses.

**metrics** scores the model on the rows it learned from — a flattering
number. For an honest one, train on a Train/Test Split's **train** rows and
score the **test** rows with Predict and Model Evaluation. **importances**
ranks the features by how much the model leans on them.

Needs scikit-learn (Tools ▸ Manage Packages…).
"""
NODE = {
    "label": "Train Model",
    "category": "ML",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("model", "object"), ("metrics", "dataframe"),
                ("importances", "dataframe")],
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
    {"name": "trees", "type": "int", "label": "Trees",
     "default": 100, "min": 1, "max": 5000,
     "visible_when": {"algorithm": ["random forest", "gradient boosting"]}},
    {"name": "seed", "type": "int", "label": "Seed", "default": 0},
]


def run(ctx, table):
    from flograph.core import mlkit

    p = ctx.params
    target = str(p["target_column"]).strip()
    if not target:
        raise ValueError("no target — set 'Target' to the column to predict")
    if target not in table.columns:
        raise ValueError(f"column {target!r} not in table")
    rows = table[table[target].notna()]
    if len(rows) < 2:
        raise ValueError(f"{target!r} has fewer than two values to learn from")

    columns = mlkit.features(rows, p["feature_columns"], target)
    x = mlkit.matrix(rows, columns)
    y = rows[target]
    task = mlkit.resolve_task(p["task"], y)
    model = mlkit.build_model(task, p["algorithm"], p["seed"], p["trees"])

    ctx.progress(0.1)
    model.fit(x, y)
    ctx.progress(0.9)
    scores = mlkit.metrics(task, y, model.predict(x))
    ctx.log(f"{p['algorithm']} {task} on {len(rows)} rows × "
            f"{len(columns)} feature(s); training "
            + ", ".join(f"{k} {v:.3g}" for k, v in scores.items()))
    return {"model": model,
            "metrics": mlkit.metrics_frame(scores),
            "importances": mlkit.importances(model, columns)}
