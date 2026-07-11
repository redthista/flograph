"""KNIME-style table spec: one row per column of a DataFrame — its dtype,
null count and value domain — so a table's shape can be read at a glance
without scanning the data itself. Qt-free on purpose: both the inspector's
Spec tab and the Table Spec node build on this."""
from __future__ import annotations

SPEC_COLUMNS = ["column", "type", "non-null", "unique", "min", "max"]


def spec_frame(df):
    """One row per column of df: dtype, non-null count, unique count and
    (for orderable columns) the min/max domain. Every cell is a string —
    this is a display table, not data."""
    import pandas as pd

    rows = []
    for i in range(len(df.columns)):
        col = df.iloc[:, i]
        row = {
            "column": str(df.columns[i]),
            "type": str(col.dtype),
            "non-null": f"{int(col.notna().sum()):,} / {len(col):,}",
            "unique": "", "min": "", "max": "",
        }
        try:
            row["unique"] = f"{col.nunique():,}"
        except TypeError:  # unhashable cells (lists, dicts)
            pass
        try:
            if col.notna().any():
                row["min"], row["max"] = str(col.min()), str(col.max())
        except TypeError:  # unorderable / mixed-type cells
            pass
        rows.append(row)
    return pd.DataFrame(rows, columns=SPEC_COLUMNS)
