"""Inspector view for matplotlib Figures returned by nodes.

Figures are created worker-side with the OO API (matplotlib.figure.Figure);
the canvas that renders them is created here, on the GUI thread."""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QVBoxLayout, QWidget


class FigureView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._canvas = None
        self._toolbar = None

    def set_figure(self, figure) -> None:
        from matplotlib.backends.backend_qtagg import (
            FigureCanvasQTAgg, NavigationToolbar2QT,
        )
        self.clear()
        self._canvas = FigureCanvasQTAgg(figure)
        self._toolbar = NavigationToolbar2QT(self._canvas, self)
        self._layout.addWidget(self._toolbar)
        self._layout.addWidget(self._canvas, 1)
        # no explicit draw_idle: the canvas draws on expose, and a scheduled
        # draw can fire after deletion when views are swapped quickly

    def clear(self) -> None:
        for widget in (self._toolbar, self._canvas):
            if widget is not None:
                self._layout.removeWidget(widget)
                widget.deleteLater()
        self._canvas = None
        self._toolbar = None
