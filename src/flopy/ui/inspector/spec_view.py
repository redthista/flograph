"""KNIME-style table spec: one row per column of a DataFrame — its dtype,
null count and value domain — so a table's shape can be read at a glance
without scanning the data itself."""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtWidgets import QTableView, QWidget

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


def spec_view_for(value: Any) -> Optional[QWidget]:
    """A spec table for DataFrame/Series values, None for anything else."""
    import sys
    pd = sys.modules.get("pandas")
    if pd is None:
        return None
    if isinstance(value, pd.Series):
        value = value.to_frame()
    if not isinstance(value, pd.DataFrame):
        return None
    from .pandas_model import PandasModel
    view = QTableView()
    view.setModel(PandasModel(spec_frame(value), parent=view))
    view.verticalHeader().setVisible(False)  # row numbers mean nothing here
    return view
