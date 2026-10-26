"""Outlier Detection

Find the rows that don't fit — a sensor spike, a typo'd price, an order
for 10,000 units — before they skew a model or an average.

**Method**:

* *IQR* — a value more than **Threshold** × the interquartile range beyond
  the middle half is out (1.5 is the box-plot rule; 3 only catches the
  extreme). Robust: the outliers can't hide themselves by stretching the
  scale.
* *z-score* — a value more than **Threshold** standard deviations from the
  mean is out (3 is usual).
* *isolation forest* — judges whole rows at once, so it catches a row whose
  values are each ordinary but whose combination is odd. **Contamination**
  is the share of rows you expect to be outliers. Needs scikit-learn.

Leave **Threshold** at 0 for the method's usual value. Leave **Columns**
empty to check every number column; a row is flagged when any of them is out.

**flags** is True on each outlying row. **cleaned** is the table after the
**Action**: *flag only* adds an `outlier` column, *drop* removes the flagged
rows, *clip* pulls each out-of-range value back to the edge of the range
(IQR and z-score only — an isolation forest has no range to clip to).
"""
NODE = {
    "label": "Outlier Detection",
    "category": "ML",
    "version": "1.0",
    "inputs": [("table", "dataframe")],
    "outputs": [("flags", "series"), ("cleaned", "dataframe")],
}
PARAMS = [
    {"name": "method", "type": "choice", "label": "Method",
     "options": ["IQR", "z-score", "isolation forest"], "default": "IQR"},
    {"name": "columns", "type": "columns", "label": "Columns",
     "default": "", "placeholder": "empty = every number column"},
    {"name": "threshold", "type": "float", "label": "Threshold",
     "default": 0.0, "min": 0.0, "max": 100.0,
     "visible_when": {"method": ["IQR", "z-score"]}},
    {"name": "contamination", "type": "float", "label": "Contamination",
     "default": 0.05, "min": 0.001, "max": 0.5,
     "visible_when": {"method": ["isolation forest"]}},
    {"name": "action", "type": "choice", "label": "Action",
     "options": ["flag only", "drop", "clip"], "default": "flag only"},
    {"name": "seed", "type": "int", "label": "Seed", "default": 0,
     "visible_when": {"method": ["isolation forest"]}},
]

_USUAL = {"IQR": 1.5, "z-score": 3.0}


def run(ctx, table):
    import pandas as pd

    from flograph.core import mlkit

    p = ctx.params
    method = p["method"]
    columns = mlkit.features(table, p["columns"])
    action = p["action"]
    bounds = {}

    if method == "isolation forest":
        if action == "clip":
            raise ValueError("an isolation forest has no range to clip to — "
                             "choose 'drop' or 'flag only', or use IQR")
        x = mlkit.matrix(table, columns)
        ensemble = mlkit.sklearn_module("sklearn.ensemble")
        model = ensemble.IsolationForest(
            contamination=float(p["contamination"]),
            random_state=int(p["seed"]))
        flags = pd.Series(model.fit_predict(x) == -1, index=table.index)
    else:
        k = float(p["threshold"]) or _USUAL[method]
        flags = pd.Series(False, index=table.index)
        for c in columns:
            s = table[c].astype(float)
            if method == "IQR":
                q1, q3 = s.quantile(0.25), s.quantile(0.75)
                lo, hi = q1 - k * (q3 - q1), q3 + k * (q3 - q1)
            else:
                mean, sd = s.mean(), s.std(ddof=0)
                lo, hi = mean - k * sd, mean + k * sd
            bounds[c] = (lo, hi)
            flags |= ((s < lo) | (s > hi)).fillna(False)
    flags = flags.astype(bool).rename("outlier")

    if action == "drop":
        cleaned = table[~flags]
    elif action == "clip":
        cleaned = table.copy(deep=False)
        for c, (lo, hi) in bounds.items():
            cleaned[c] = table[c].astype(float).clip(lo, hi)
    else:
        cleaned = table.copy(deep=False)
        cleaned["outlier"] = flags

    ctx.log(f"{method}: {int(flags.sum())} of {len(table)} row(s) outlying "
            f"over {len(columns)} column(s); {action}")
    return {"flags": flags, "cleaned": cleaned}
