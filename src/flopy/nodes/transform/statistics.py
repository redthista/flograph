"""Statistics

Summary statistics per column (KNIME Statistics): count, mean, std,
min/max, quartiles — pandas describe() as a table, one row per statistic.
"""
NODE = {
    "label": "Statistics",
    "category": "Transform",
    "inputs": [("table", "dataframe")],
    "outputs": [("stats", "dataframe")],
}
PARAMS = [
    {"name": "include", "type": "choice", "label": "Columns",
     "options": ["numeric only", "all"], "default": "numeric only"},
]


def run(ctx, table):
    if len(table.columns) == 0:
        raise ValueError("table has no columns")
    include = "all" if ctx.params["include"] == "all" else None
    stats = table.describe(include=include)
    stats.insert(0, "statistic", stats.index)
    stats = stats.reset_index(drop=True)
    ctx.log(f"{len(stats)} statistics over {len(stats.columns) - 1} column(s)")
    return stats
