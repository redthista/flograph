"""Spec tab widget for the inspector: a table view over flopy.core.spec's
spec_frame, for DataFrame/Series outputs."""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtWidgets import QTableView, QWidget

from flopy.core.spec import SPEC_COLUMNS, spec_frame  # noqa: F401 — re-export


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
