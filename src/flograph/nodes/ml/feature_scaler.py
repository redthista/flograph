"""Feature Scaler

Put number columns on one scale, so a model doesn't treat income (in
thousands) as a thousand times more important than age.

**Method**: *standard* makes each column mean 0 and spread 1; *min-max*
squeezes it into 0 to 1; *robust* centres on the median and divides by the
interquartile range, so a few huge values don't squash the rest.

**scaler** comes out holding what was learned — each column's centre and
size. Wire it into the **scaler** input of a second Feature Scaler and that
one scales its table by the *same* numbers instead of learning new ones:
fit on the training rows, then apply to the test rows, so nothing about the
test rows leaks into the model.

Leave **Columns** empty to scale every number column. Other columns pass
through untouched.
"""
NODE = {
    "label": "Feature Scaler",
    "category": "ML",
    "version": "1.0",
    "inputs": [("table", "dataframe"),
               ("scaler", "object", {"optional": True,
                                     "suggest": ["flograph.ml.feature_scaler"]})],
    "outputs": [("scaled", "dataframe"), ("scaler", "object")],
}
PARAMS = [
    {"name": "method", "type": "choice", "label": "Method",
     "options": ["standard", "min-max", "robust"], "default": "standard"},
    {"name": "columns", "type": "columns", "label": "Columns",
     "default": "", "placeholder": "empty = every number column"},
]

_KIND = "flograph.scaler"


def _fit(table, columns, method):
    centre, size = {}, {}
    for c in columns:
        s = table[c].astype(float)
        if method == "min-max":
            lo, hi = s.min(), s.max()
            centre[c], size[c] = lo, hi - lo
        elif method == "robust":
            centre[c] = s.median()
            size[c] = s.quantile(0.75) - s.quantile(0.25)
        else:
            centre[c], size[c] = s.mean(), s.std(ddof=0)
        # a constant column has no size to divide by; leave it centred
        if not size[c] or size[c] != size[c]:
            size[c] = 1.0
    return {"kind": _KIND, "method": method, "columns": list(columns),
            "centre": {c: float(v) for c, v in centre.items()},
            "size": {c: float(v) for c, v in size.items()}}


def run(ctx, table, scaler=None):
    import pandas as pd

    p = ctx.params
    if scaler is not None:
        if not (isinstance(scaler, dict) and scaler.get("kind") == _KIND):
            raise ValueError("'scaler' takes the scaler output of another "
                             "Feature Scaler")
        fitted = scaler
        missing = [c for c in fitted["columns"] if c not in table.columns]
        if missing:
            raise ValueError(f"the scaler was fitted on columns this table "
                             f"doesn't have: {missing}")
    else:
        named = [c.strip() for c in str(p["columns"]).split(",") if c.strip()]
        if named:
            missing = [c for c in named if c not in table.columns]
            if missing:
                raise ValueError(f"columns not in table: {missing}")
            text = [c for c in named
                    if not pd.api.types.is_numeric_dtype(table[c])]
            if text:
                raise ValueError(f"columns {text} aren't numbers")
            columns = named
        else:
            columns = [c for c in table.columns
                       if pd.api.types.is_numeric_dtype(table[c])
                       and not pd.api.types.is_bool_dtype(table[c])]
        if not columns:
            raise ValueError("no number columns to scale")
        fitted = _fit(table, columns, p["method"])

    out = table.copy(deep=False)
    for c in fitted["columns"]:
        out[c] = (table[c].astype(float) - fitted["centre"][c]) \
            / fitted["size"][c]
    ctx.log(f"{fitted['method']} scaling of {len(fitted['columns'])} "
            f"column(s)" + (" with the wired scaler" if scaler is not None
                            else ""))
    return {"scaled": out, "scaler": fitted}
