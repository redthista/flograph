"""Spec tab widget for the inspector: a table view over flograph.core.spec's
spec_frame, for DataFrame/Series outputs."""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtWidgets import QTableView, QWidget

from flograph.core.spec import SPEC_COLUMNS, spec_frame  # noqa: F401 — re-export


def is_tabular(value: Any) -> bool:
    """True for DataFrame/Series values — the ones spec_view_for can build a
    spec for. Just a type check, no column stats; safe to call eagerly."""
    import sys
    pd = sys.modules.get("pandas")
    return pd is not None and isinstance(value, (pd.DataFrame, pd.Series))


def spec_view_for(value: Any) -> Optional[QWidget]:
    """A spec table for DataFrame/Series values, None for anything else.
    Building it walks every column (nunique/min/max) — for large tables that
    can be slow, so callers should defer this until the tab is actually
    shown rather than calling it on every selection change."""
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
