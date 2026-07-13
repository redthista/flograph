"""Dispatches a cached node-output value to the right display widget —
table view for DataFrames/Series, figure canvas for plots, pretty repr for
everything else. Shared by the docked InspectorPanel and popup view windows.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QTableView, QWidget

from .figure_view import FigureView
from .object_view import ObjectView
from .pandas_model import PandasModel


def view_for(value: Any) -> QWidget:
    import sys
    pd = sys.modules.get("pandas")
    if pd is not None and isinstance(value, pd.DataFrame):
        table = QTableView()
        table.setModel(PandasModel(value, parent=table))
        return table
    if pd is not None and isinstance(value, pd.Series):
        table = QTableView()
        table.setModel(PandasModel(value.to_frame(), parent=table))
        return table
    figure_cls = getattr(sys.modules.get("matplotlib.figure"), "Figure", None)
    if figure_cls is not None and isinstance(value, figure_cls):
        view = FigureView()
        view.set_figure(value)
        return view
    view = ObjectView()
    view.set_value(value)
    return view
