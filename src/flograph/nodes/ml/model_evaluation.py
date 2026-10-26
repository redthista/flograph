"""Model Evaluation

How good are the predictions? Compare what actually happened with what the
model said.

Wire one table holding both — Predict's **table** on your test rows is
exactly that — and name the **Actual column** and **Predicted column**. Or
wire the two as series into **actual** and **predicted**.

*Regression* reports MAE (the typical miss), RMSE (the typical miss, with
big misses counting extra), MSE and R² (1 is perfect, 0 is no better than
guessing the average); the figure plots predicted against actual, where a
perfect model sits on the diagonal. *Classification* reports accuracy and
precision / recall / F1 averaged over the classes (**Average**: *macro*
counts every class the same, *weighted* by how common it is), and the
figure is the confusion matrix — **counts** is the same as a table, actual
classes down the side, predictions across. **Normalize** shows each row as
shares of that actual class, which makes a weak class stand out.

*auto* reads the actual values: text or true/false is classification.
"""
NODE = {
    "label": "Model Evaluation",
    "category": "ML",
    "version": "1.0",
    # an interactive Plotly chart: hover a point or a cell for its numbers
    "card": "webview",
    "inputs": [("table", "dataframe", {"optional": True,
                                       "suggest": ["flograph.ml.predict"]}),
               ("actual", "any", {"optional": True}),
               ("predicted", "any", {"optional": True})],
    # the figure first: a card draws its node's first output
    "outputs": [("figure", "object"), ("metrics", "dataframe"),
                ("counts", "dataframe")],
}
PARAMS = [
    {"name": "actual_column", "type": "columns", "label": "Actual column",
     "default": "", "multi": False},
    {"name": "predicted_column", "type": "columns", "label": "Predicted column",
     "default": "prediction", "multi": False},
    {"name": "task", "type": "choice", "label": "Task",
     "options": ["auto", "regression", "classification"], "default": "auto"},
    {"name": "multi_class", "type": "choice", "label": "Average",
     "options": ["macro", "weighted"], "default": "macro"},
    {"name": "normalize", "type": "bool", "label": "Normalize", "default": False},
    {"name": "width", "type": "int", "label": "Width",
     "default": 420, "min": 260, "max": 4000, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 380, "min": 200, "max": 4000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %",
     "default": 100, "min": 25, "max": 400, "cosmetic": True},
]


def _as_series(value, what):
    import pandas as pd

    if isinstance(value, pd.DataFrame):
        if value.shape[1] != 1:
            raise ValueError(f"'{what}' got a table with {value.shape[1]} "
                             "columns — wire one column, or use 'table'")
        return value.iloc[:, 0]
    if isinstance(value, pd.Series):
        return value
    return pd.Series(list(value))


def run(ctx, table=None, actual=None, predicted=None):
    import pandas as pd

    from flograph.core import mlkit

    p = ctx.params
    if actual is not None and predicted is not None:
        y = _as_series(actual, "actual").reset_index(drop=True)
        yhat = _as_series(predicted, "predicted").reset_index(drop=True)
        if len(y) != len(yhat):
            raise ValueError(f"actual has {len(y)} values, predicted "
                             f"{len(yhat)} — they must line up")
    elif table is not None:
        a, b = (str(p["actual_column"]).strip(),
                str(p["predicted_column"]).strip())
        if not a or not b:
            raise ValueError("set 'Actual column' and 'Predicted column'")
        for c in (a, b):
            if c not in table.columns:
                raise ValueError(f"column {c!r} not in table")
        y, yhat = table[a], table[b]
    else:
        raise ValueError("wire a table with both columns, or both 'actual' "
                         "and 'predicted'")

    both = y.notna().to_numpy() & yhat.notna().to_numpy()
    y, yhat = y[both], yhat[both]
    if not len(y):
        raise ValueError("no rows with both an actual and a predicted value")
    task = mlkit.resolve_task(p["task"], y)
    scores = mlkit.metrics(task, y, yhat, p["multi_class"])

    if task == "classification":
        labels, counts = mlkit.confusion(y, yhat)
        shown = counts.div(counts.sum(axis=1).replace(0, 1), axis=0) \
            if p["normalize"] else counts
        fig = mlkit.heatmap(shown.to_numpy(), labels, labels,
                            colorscale="Blues", zmin=0,
                            fmt=".2f" if p["normalize"] else ".0f",
                            title="Confusion matrix", xlabel="predicted",
                            ylabel="actual")
        table_out = shown.reset_index()
        table_out.columns = ["actual"] + [str(c) for c in labels]
    else:
        lo = float(min(y.min(), yhat.min()))
        hi = float(max(y.max(), yhat.max()))
        fig = mlkit.scatter_figure(
            [dict(x=y.astype(float).tolist(), y=yhat.astype(float).tolist(),
                  name="rows", marker=dict(size=7, opacity=0.75),
                  hovertemplate="actual %{x:.4g}<br>predicted %{y:.4g}"
                                "<extra></extra>")],
            title=f"Predicted vs actual (R² {scores['R2']:.3f})",
            xlabel="actual", ylabel="predicted", diagonal=(lo, hi))
        table_out = pd.DataFrame(columns=["actual"])

    ctx.log(f"{task} over {len(y)} rows: "
            + ", ".join(f"{k} {v:.3g}" for k, v in scores.items()))
    return {"metrics": mlkit.metrics_frame(scores), "figure": fig,
            "counts": table_out}
