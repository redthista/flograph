"""DashboardPage: one dashboard tab — a visuals list beside the page's
infinite canvas. Owns the scene/view pair; dispose() must be called when the
page is removed (core events hold strong refs to both scene and list)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSplitter, QVBoxLayout, QWidget

from flograph.core import Graph

from .dashboard_scene import DashboardScene
from .dashboard_view import DashboardView
from .visuals_list import VisualsList


class DashboardPage(QWidget):
    def __init__(self, graph: Graph, engine, undo_stack: QUndoStack,
                 page_id: str, parent=None) -> None:
        super().__init__(parent)
        self.page_id = page_id
        self.scene = DashboardScene(graph, engine, undo_stack, page_id,
                                    parent=self)
        self.view = DashboardView(self.scene)
        self.visuals = VisualsList(graph)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(6, 6, 4, 6)
        side_layout.setSpacing(4)
        header = QLabel("Visuals")
        header.setStyleSheet("font-weight: bold;")
        side_layout.addWidget(header)
        side_layout.addWidget(self.visuals, 1)
        hint = QLabel("Drag a visual onto the page.")
        hint.setStyleSheet("color: #6b7280; font-size: 8pt;")
        hint.setWordWrap(True)
        side_layout.addWidget(hint)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(side)
        splitter.addWidget(self.view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([180, 1000])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    def dispose(self) -> None:
        self.scene.dispose()
        self.visuals.dispose()
