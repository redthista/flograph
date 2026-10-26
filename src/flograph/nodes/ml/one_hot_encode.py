"""One-Hot Encode

Turn a text column into a set of 0/1 columns, one per value — `city` becomes
`city_Leeds`, `city_York`, … — which is how a model that only reads numbers
can use a category.

Leave **Columns** empty to encode every text column. **Drop first** leaves
out one value per column (it is the row where all the others are 0), which a
linear or logistic model needs to avoid two columns saying the same thing;
tree models don't mind either way.

**encoder** remembers which columns were made. Wire it into the **encoder**
input of a second One-Hot Encode — the one on your test or new rows — and it
makes exactly the same columns in the same order, so the model sees what it
was trained on. A value the encoder never saw is, by **Unknown values**,
all zeros (*ignore*) or an error.
"""
NODE = {
    "label": "One-Hot Encode",
    "category": "ML",
    "version": "1.0",
    "inputs": [("table", "dataframe"),
               ("encoder", "object", {"optional": True,
                                      "suggest": ["flograph.ml.one_hot_encode"]})],
    "outputs": [("table", "dataframe"), ("encoder", "object")],
}
PARAMS = [
    {"name": "columns", "type": "columns", "label": "Columns",
     "default": "", "placeholder": "empty = every text column"},
    {"name": "drop_first", "type": "bool", "label": "Drop first",
     "default": False},
    {"name": "handle_unknown", "type": "choice", "label": "Unknown values",
     "options": ["ignore", "error"], "default": "ignore"},
]

_KIND = "flograph.onehot"


def _levels(series):
    values = series.dropna().astype(str).unique().tolist()
    return sorted(values)


def run(ctx, table, encoder=None):
    import pandas as pd

    p = ctx.params
    if encoder is not None:
        if not (isinstance(encoder, dict) and encoder.get("kind") == _KIND):
            raise ValueError("'encoder' takes the encoder output of another "
                             "One-Hot Encode")
        plan = encoder
    else:
        named = [c.strip() for c in str(p["columns"]).split(",") if c.strip()]
        if named:
            missing = [c for c in named if c not in table.columns]
            if missing:
                raise ValueError(f"columns not in table: {missing}")
            columns = named
        else:
            columns = [c for c in table.columns
                       if not pd.api.types.is_numeric_dtype(table[c])
                       and not pd.api.types.is_datetime64_any_dtype(table[c])]
        if not columns:
            raise ValueError("no text columns to encode — name them in "
                             "'Columns'")
        drop = bool(p["drop_first"])
        plan = {"kind": _KIND, "columns": {}}
        for c in columns:
            levels = _levels(table[c])
            plan["columns"][c] = levels[1:] if drop else levels

    missing = [c for c in plan["columns"] if c not in table.columns]
    if missing:
        raise ValueError(f"the encoder was made for columns this table "
                         f"doesn't have: {missing}")

    pieces, made = [], 0
    for c, levels in plan["columns"].items():
        text = table[c].astype("object").where(table[c].notna(), None)
        text = text.map(lambda v: None if v is None else str(v))
        if p["handle_unknown"] == "error" and encoder is not None:
            # "all" includes the level Drop first left out: it is known
            known = set(encoder.get("all", {}).get(c, levels))
            unknown = sorted(set(text.dropna()) - known)
            if unknown:
                raise ValueError(f"{c!r} has values the encoder never saw: "
                                 f"{unknown[:5]}")
        block = pd.DataFrame(
            {f"{c}_{level}": (text == level).astype("int8")
             for level in levels}, index=table.index)
        pieces.append(block)
        made += len(levels)
    if encoder is None:
        plan["all"] = {c: _levels(table[c]) for c in plan["columns"]}

    rest = table.drop(columns=list(plan["columns"]))
    out = pd.concat([rest] + pieces, axis=1)
    ctx.log(f"{len(plan['columns'])} column(s) -> {made} indicator "
            f"column(s)" + (" with the wired encoder" if encoder is not None
                            else ""))
    return {"table": out, "encoder": plan}
