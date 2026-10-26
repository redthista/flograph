"""What the ML nodes share: choosing features, building a model, scoring it.

Qt-free, and nothing heavy at import: pandas, numpy and scikit-learn are
imported inside the functions, matching the node-script rule, so loading the
node library never needs scikit-learn — only running a node that fits a model
does. The metrics are worked out here with numpy rather than taken from
scikit-learn, so Model Evaluation runs without it and every node that reports
a score (Train Model, Cross-Validation, Model Evaluation) reports the same
one.
"""
from __future__ import annotations

import threading
from typing import Any, Sequence

#: Held while scikit-learn is imported. Nodes run at the same time, and the
#: first import of a package that large, started from several worker threads
#: at once, hands some of them a half-initialised `sklearn` ("cannot import
#: name 'clone' from partially initialized module 'sklearn.base'"). One
#: import at a time costs nothing after the first: it is then a dict lookup.
_SKLEARN_IMPORT = threading.Lock()

TASKS =("auto", "regression", "classification")
ALGORITHMS = ("random forest", "gradient boosting", "linear", "ridge",
              "lasso", "logistic")

#: (task, algorithm) -> (scikit-learn module, class name). A pair missing
#: from here is a combination that doesn't exist, and `build_model` says so.
_MODELS = {
    ("regression", "linear"): ("sklearn.linear_model", "LinearRegression"),
    ("regression", "ridge"): ("sklearn.linear_model", "Ridge"),
    ("regression", "lasso"): ("sklearn.linear_model", "Lasso"),
    ("regression", "random forest"): ("sklearn.ensemble",
                                      "RandomForestRegressor"),
    ("regression", "gradient boosting"): ("sklearn.ensemble",
                                          "GradientBoostingRegressor"),
    ("classification", "logistic"): ("sklearn.linear_model",
                                     "LogisticRegression"),
    ("classification", "ridge"): ("sklearn.linear_model", "RidgeClassifier"),
    ("classification", "random forest"): ("sklearn.ensemble",
                                          "RandomForestClassifier"),
    ("classification", "gradient boosting"): ("sklearn.ensemble",
                                              "GradientBoostingClassifier"),
}
_SEEDED = {"Lasso", "RandomForestRegressor", "GradientBoostingRegressor",
           "LogisticRegression", "RandomForestClassifier",
           "GradientBoostingClassifier", "Ridge", "RidgeClassifier"}


def sklearn_module(name: str):
    """Import a scikit-learn module, or fail saying which package to get —
    the import is `sklearn` but the package is `scikit-learn`, and only the
    second one installs."""
    import importlib

    try:
        with _SKLEARN_IMPORT:
            return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        err = ModuleNotFoundError(
            "this node needs scikit-learn, which isn't installed — install "
            "'scikit-learn' from Tools ▸ Manage Packages…, then run again")
        err.name = "sklearn"
        raise err from exc


def column_list(raw: Any) -> list[str]:
    return [c.strip() for c in str(raw or "").split(",") if c.strip()]


def resolve_task(task: str, target) -> str:
    """`auto` reads the target: text, true/false or categories are classes
    to predict, numbers are a quantity."""
    import pandas as pd

    if task in ("regression", "classification"):
        return task
    if (pd.api.types.is_bool_dtype(target)
            or not pd.api.types.is_numeric_dtype(target)):
        return "classification"
    return "regression"


def features(table, feature_columns: Any, target: str = "",
             exclude: Sequence[str] = ()) -> list[str]:
    """The feature columns: the ones named, or every numeric column that is
    neither the target nor excluded. Raises a message that says what to do
    when a named column is missing or not a number."""
    import pandas as pd

    named = column_list(feature_columns)
    if named:
        missing = [c for c in named if c not in table.columns]
        if missing:
            raise ValueError(f"feature columns not in table: {missing}")
        if target and target in named:
            raise ValueError(f"{target!r} is the target — it can't also be "
                             "a feature")
        text = [c for c in named
                if not (pd.api.types.is_numeric_dtype(table[c])
                        or pd.api.types.is_bool_dtype(table[c]))]
        if text:
            raise ValueError(
                f"feature columns {text} aren't numbers — encode them first "
                "with One-Hot Encode or Label Encode")
        return named
    skip = set(exclude) | ({target} if target else set())
    picked = [c for c in table.columns if c not in skip
              and (pd.api.types.is_numeric_dtype(table[c])
                   or pd.api.types.is_bool_dtype(table[c]))]
    if not picked:
        raise ValueError("no numeric feature columns — name them in "
                         "'Feature columns', or encode text columns first")
    return picked


def matrix(table, columns: Sequence[str]):
    """The feature table as floats, refusing gaps — scikit-learn would
    otherwise fail with a message about NaN that names no column."""
    frame = table[list(columns)].astype(float)
    gaps = [c for c in frame.columns if frame[c].isna().any()]
    if gaps:
        raise ValueError(
            f"columns {gaps} have missing values — fill or drop them first "
            "(Missing Values)")
    return frame


def build_model(task: str, algorithm: str, seed: int = 0, trees: int = 100):
    """A fresh, unfitted scikit-learn estimator for `task` × `algorithm`."""
    key = (task, algorithm)
    if key not in _MODELS:
        options = sorted(a for t, a in _MODELS if t == task)
        raise ValueError(f"{algorithm!r} isn't a {task} algorithm — pick one "
                         f"of: {', '.join(options)}")
    module, name = _MODELS[key]
    cls = getattr(sklearn_module(module), name)
    kwargs: dict[str, Any] = {}
    if name in _SEEDED:
        kwargs["random_state"] = int(seed)
    if name.startswith(("RandomForest", "GradientBoosting")):
        kwargs["n_estimators"] = int(trees)
    if name == "LogisticRegression":
        kwargs["max_iter"] = 1000
    return cls(**kwargs)


def importances(model, columns: Sequence[str]):
    """One row per feature, biggest first: a tree model's importance, or a
    linear model's coefficient size (averaged over classes)."""
    import numpy as np
    import pandas as pd

    if hasattr(model, "feature_importances_"):
        values = np.asarray(model.feature_importances_, dtype=float)
    elif hasattr(model, "coef_"):
        coef = np.atleast_2d(np.asarray(model.coef_, dtype=float))
        values = np.abs(coef).mean(axis=0)
    else:
        values = np.full(len(columns), np.nan)
    out = pd.DataFrame({"feature": list(columns), "importance": values})
    return out.sort_values("importance", ascending=False,
                           ignore_index=True)


def regression_metrics(actual, predicted) -> dict[str, float]:
    import numpy as np

    y = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    err = y - p
    mse = float(np.mean(err ** 2))
    total = float(np.sum((y - y.mean()) ** 2))
    return {
        "MAE": float(np.mean(np.abs(err))),
        "MSE": mse,
        "RMSE": float(np.sqrt(mse)),
        "R2": (1.0 - float(np.sum(err ** 2)) / total) if total else float("nan"),
    }


def confusion(actual, predicted):
    """(labels, counts) — counts[i][j] is how many of label i were
    predicted as label j."""
    import pandas as pd

    a = pd.Series(list(actual), dtype="object").astype(str)
    p = pd.Series(list(predicted), dtype="object").astype(str)
    labels = sorted(set(a) | set(p))
    counts = pd.crosstab(a, p).reindex(index=labels, columns=labels,
                                       fill_value=0)
    return labels, counts


def classification_metrics(actual, predicted,
                           average: str = "macro") -> dict[str, float]:
    """Accuracy, then precision / recall / F1 averaged over the classes —
    `macro` weighs each class the same, `weighted` by how common it is."""
    import numpy as np

    labels, counts = confusion(actual, predicted)
    m = counts.to_numpy(dtype=float)
    support = m.sum(axis=1)
    hits = np.diag(m)
    predicted_n = m.sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        precision = np.where(predicted_n > 0, hits / predicted_n, 0.0)
        recall = np.where(support > 0, hits / support, 0.0)
        f1 = np.where(precision + recall > 0,
                      2 * precision * recall / (precision + recall), 0.0)
    if average == "weighted" and support.sum():
        w = support / support.sum()
    else:
        present = support > 0
        w = present / max(1, present.sum())
    return {
        "accuracy": float(hits.sum() / m.sum()) if m.sum() else float("nan"),
        "precision": float((precision * w).sum()),
        "recall": float((recall * w).sum()),
        "F1": float((f1 * w).sum()),
    }


def metrics(task: str, actual, predicted, average: str = "macro"):
    if task == "classification":
        return classification_metrics(actual, predicted, average)
    return regression_metrics(actual, predicted)


def metrics_frame(scores: dict[str, float]):
    import pandas as pd

    return pd.DataFrame({"metric": list(scores),
                         "value": list(scores.values())})



def plotly_modules():
    """(plotly.graph_objects, the figure lock) — or a message saying what
    to install. Every built-in chart node builds its figures under the one
    lock, because building a Plotly figure is not thread-safe and node
    bodies share the process (see `core.plotly_spec.FIGURE_LOCK`)."""
    try:
        import plotly.graph_objects as go
    except ModuleNotFoundError as exc:
        err = ModuleNotFoundError(
            "this node draws with plotly, which isn't installed — install "
            "'plotly' from Tools ▸ Manage Packages…, then run again")
        err.name = "plotly"
        raise err from exc
    from flograph.core.plotly_spec import FIGURE_LOCK

    return go, FIGURE_LOCK


def heatmap(values, rows: Sequence[str], columns: Sequence[str], *,
            colorscale: str = "RdBu_r", zmin=None, zmax=None,
            annotate: bool = True, fmt: str = ".2f", title: str = "",
            xlabel: str = "", ylabel: str = ""):
    """An annotated grid of `values` as a Plotly figure — one cell per
    row × column, the number written in each when `annotate` and the grid
    is small enough to read. The first row is drawn at the top, as a table
    reads, not at the bottom as a chart would put it."""
    import numpy as np

    go, lock = plotly_modules()
    grid = np.asarray(values, dtype=float)
    rows = [str(r) for r in rows]
    columns = [str(c) for c in columns]
    with lock:
        trace = go.Heatmap(
            z=grid, x=columns, y=rows, colorscale=colorscale, zmin=zmin,
            zmax=zmax, hovertemplate="%{y} × %{x}: %{z:" + fmt + "}"
                                     "<extra></extra>")
        if annotate and grid.size <= 400:
            trace.update(text=[[format(v, fmt) if v == v else "" for v in row]
                               for row in grid],
                         texttemplate="%{text}")
        fig = go.Figure(trace)
        fig.update_layout(title_text=title or None,
                          margin=dict(l=60, r=20, t=50 if title else 20, b=60))
        fig.update_xaxes(title_text=xlabel or None, side="bottom")
        fig.update_yaxes(title_text=ylabel or None, autorange="reversed")
    return fig


def scatter_figure(traces: Sequence[dict], *, title: str = "",
                   xlabel: str = "", ylabel: str = "", diagonal=None):
    """A Plotly scatter of one or more `traces` (each a dict of
    `go.Scatter` arguments), with an optional dashed `(lo, hi)` diagonal —
    the "perfect prediction" line."""
    go, lock = plotly_modules()
    with lock:
        fig = go.Figure()
        for trace in traces:
            fig.add_trace(go.Scatter(mode="markers", **trace))
        if diagonal is not None:
            lo, hi = diagonal
            fig.add_trace(go.Scatter(
                x=[lo, hi], y=[lo, hi], mode="lines", name="perfect",
                line=dict(dash="dash", color="grey"), hoverinfo="skip"))
        fig.update_layout(title_text=title or None,
                          margin=dict(l=60, r=20, t=50 if title else 20, b=50))
        fig.update_xaxes(title_text=xlabel or None)
        fig.update_yaxes(title_text=ylabel or None)
    return fig
