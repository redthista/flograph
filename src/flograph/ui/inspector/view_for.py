"""Dispatches a cached node-output value to the right display widget —
table view for DataFrames/Series, figure canvas for plots, pretty repr for
everything else. Shared by the docked InspectorPanel and popup view windows.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QTableView, QWidget

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from .figure_view import FigureView
from .object_view import ObjectView
from .pandas_model import PandasModel

FIGURE_ELSEWHERE_MSG = (
    "This node has a canvas card (or dashboard tile) already showing its "
    "figure — see it there, sized properly, instead of a squeezed copy here.")


def is_figure(value: Any) -> bool:
    import sys
    figure_cls = getattr(sys.modules.get("matplotlib.figure"), "Figure", None)
    return figure_cls is not None and isinstance(value, figure_cls)


def view_for(value: Any, embed_figures: bool = True) -> QWidget:
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
    if is_figure(value):
        if not embed_figures:
            label = QLabel(FIGURE_ELSEWHERE_MSG)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet("color: #6b7280; padding: 16px;")
            return label
        view = FigureView()
        view.set_figure(value)
        return view
    view = ObjectView()
    view.set_value(value)
    return view
