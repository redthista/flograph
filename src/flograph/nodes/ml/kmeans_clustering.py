"""K-Means Clustering

Sort rows into **k** groups of look-alikes — customers who buy alike,
stores that trade alike — without saying in advance what the groups are.

Pick the number columns to compare by in **Columns** (empty = every number
column). **Standardize** puts them on one scale first, so a column measured
in thousands doesn't decide the groups on its own; leave it on unless the
columns already share a unit.

**table** comes back with a **Cluster column** (0 to k−1); **clusters** is
that column alone, ready to feed back in as a feature. **centers** is the
typical row of each group in the columns' own units — read it to name the
groups — with how many rows each holds. The figure squashes the columns down
to two (principal components) and colours each row by its group, so you can
see whether the groups are really apart.

**Seed** fixes the starting guess, so a re-run gives the same groups.

Needs scikit-learn (Tools ▸ Manage Packages…).
"""
NODE = {
    "label": "K-Means Clustering",
    "category": "ML",
    "version": "1.0",
    # an interactive Plotly chart: click a cluster in the legend to hide it
    "card": "webview",
    "inputs": [("table", "dataframe")],
    # the figure first: a card draws its node's first output
    "outputs": [("figure", "object"), ("table", "dataframe"),
                ("clusters", "series"), ("centers", "dataframe")],
}
PARAMS = [
    {"name": "k", "type": "int", "label": "Clusters (k)",
     "default": 3, "min": 2, "max": 100},
    {"name": "columns", "type": "columns", "label": "Columns",
     "default": "", "placeholder": "empty = every number column"},
    {"name": "standardize", "type": "bool", "label": "Standardize",
     "default": True},
    {"name": "output_column", "type": "string", "label": "Cluster column",
     "default": "cluster"},
    {"name": "seed", "type": "int", "label": "Seed", "default": 0},
    {"name": "width", "type": "int", "label": "Width",
     "default": 420, "min": 260, "max": 4000, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 380, "min": 200, "max": 4000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %",
     "default": 100, "min": 25, "max": 400, "cosmetic": True},
]


def run(ctx, table):
    import numpy as np
    import pandas as pd

    from flograph.core import mlkit

    p = ctx.params
    columns = mlkit.features(table, p["columns"])
    x = mlkit.matrix(table, columns).to_numpy()
    k = int(p["k"])
    if len(x) < k:
        raise ValueError(f"{len(x)} rows can't make {k} clusters")

    centre = x.mean(axis=0)
    size = x.std(axis=0)
    size[size == 0] = 1.0
    fit_on = (x - centre) / size if p["standardize"] else x

    cluster = mlkit.sklearn_module("sklearn.cluster")
    model = cluster.KMeans(n_clusters=k, n_init=10,
                           random_state=int(p["seed"]))
    labels = model.fit_predict(fit_on)
    centers = model.cluster_centers_
    if p["standardize"]:
        centers = centers * size + centre

    name = str(p["output_column"]).strip() or "cluster"
    clusters = pd.Series(labels, index=table.index, name=name)
    out = table.copy(deep=False)
    out[name] = clusters
    counts = np.bincount(labels, minlength=k)
    centers_out = pd.DataFrame(centers, columns=columns)
    centers_out.insert(0, name, range(k))
    centers_out.insert(1, "rows", counts)

    # two principal components by SVD, so the picture needs nothing extra
    centred = fit_on - fit_on.mean(axis=0)
    if centred.shape[1] >= 2:
        _, _, vt = np.linalg.svd(centred, full_matrices=False)
        flat = centred @ vt[:2].T
    else:
        flat = np.column_stack([centred[:, 0], np.zeros(len(centred))])
    # one trace per cluster, so the legend names them and a click hides one
    traces = []
    for c in range(k):
        at = labels == c
        traces.append(dict(
            x=flat[at, 0].tolist(), y=flat[at, 1].tolist(),
            name=f"{name} {c} ({int(at.sum())})",
            marker=dict(size=8, opacity=0.8),
            hovertemplate=f"{name} {c}<extra></extra>"))
    fig = mlkit.scatter_figure(
        traces, title=f"{k} clusters over {len(columns)} column(s)",
        xlabel="component 1", ylabel="component 2")

    ctx.log(f"k={k} over {len(columns)} column(s); sizes "
            + ", ".join(str(int(c)) for c in counts))
    return {"table": out, "clusters": clusters, "centers": centers_out,
            "figure": fig}
