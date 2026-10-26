"""Predict

Run a trained model over a table: wire Train Model's **model** in, and the
rows you want predictions for.

**table** comes back with a **Prediction column** added; **predictions** is
the same thing on its own. The table needs the columns the model was trained
on (by name — order doesn't matter, extra columns are ignored).

For a classifier, **probabilities** has one column per class with how sure
the model is of each, and **Add probabilities** puts them on the table too —
useful to rank customers by churn risk rather than just yes/no. For a
regression it is empty. **Round** rounds a regression's predictions to that
many decimals (−1 leaves them alone).
"""
NODE = {
    "label": "Predict",
    "category": "ML",
    "version": "1.0",
    "inputs": [("model", "object", {"suggest": ["flograph.ml.train_model"]}),
               ("table", "dataframe")],
    "outputs": [("table", "dataframe"), ("predictions", "series"),
                ("probabilities", "dataframe")],
}
PARAMS = [
    {"name": "output_column", "type": "string", "label": "Prediction column",
     "default": "prediction"},
    {"name": "probability", "type": "bool", "label": "Add probabilities",
     "default": False},
    {"name": "round", "type": "int", "label": "Round", "default": -1,
     "min": -1, "max": 12},
]


def run(ctx, model, table):
    import pandas as pd

    from flograph.core import mlkit

    p = ctx.params
    if not hasattr(model, "predict"):
        raise ValueError("'model' takes the model output of Train Model")
    columns = list(getattr(model, "feature_names_in_", []))
    if not columns:
        raise ValueError("this model doesn't record its feature columns — "
                         "train it with Train Model")
    missing = [c for c in columns if c not in table.columns]
    if missing:
        raise ValueError(f"the table lacks columns the model was trained on: "
                         f"{missing}")
    name = str(p["output_column"]).strip() or "prediction"

    x = mlkit.matrix(table, columns)
    predicted = pd.Series(model.predict(x), index=table.index, name=name)
    is_classifier = hasattr(model, "classes_")
    if not is_classifier and int(p["round"]) >= 0:
        predicted = predicted.round(int(p["round"]))

    probabilities = pd.DataFrame(index=table.index)
    if is_classifier and hasattr(model, "predict_proba"):
        probabilities = pd.DataFrame(
            model.predict_proba(x), index=table.index,
            columns=[f"p_{c}" for c in model.classes_])

    out = table.copy(deep=False)
    out[name] = predicted
    if p["probability"] and not probabilities.empty:
        for c in probabilities.columns:
            out[c] = probabilities[c]
    ctx.log(f"{len(predicted)} prediction(s)"
            + (f" over {len(model.classes_)} classes" if is_classifier
               else ""))
    return {"table": out, "predictions": predicted,
            "probabilities": probabilities}
