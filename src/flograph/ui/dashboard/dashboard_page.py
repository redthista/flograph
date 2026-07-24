"""DashboardPage: one dashboard tab — a visuals list beside the page's
infinite canvas. Owns the scene/view pair; dispose() must be called when the
page is removed (core events hold strong refs to both scene and list)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QSplitter, QToolButton, QVBoxLayout, QWidget,
)

from flograph.core import Graph

from .dashboard_scene import DashboardScene
from .dashboard_view import DashboardView
from .visuals_list import VisualsList


class DashboardPage(QWidget):
    # the user opened or closed the visuals panel -- the window remembers it
    # as the starting state for pages made later
    visuals_visibility_changed = Signal(bool)

    def __init__(self, graph: Graph, engine, undo_stack: QUndoStack,
                 page_id: str, parent=None,
                 visuals_visible: bool = False) -> None:
        super().__init__(parent)
        self.page_id = page_id
        self.scene = DashboardScene(graph, engine, undo_stack, page_id,
                                    parent=self)
        self.view = DashboardView(self.scene)
        self.visuals = VisualsList(graph)

        self._side = QWidget()
        side_layout = QVBoxLayout(self._side)
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

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.addWidget(self._side)
        self._splitter.addWidget(self.view)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        # set before anything is hidden: the splitter keeps the width it was
        # given, so reopening the panel restores it rather than a sliver
        self._splitter.setSizes([180, 1000])
        self._visuals_visible = True

        # always-visible strip so the panel can be brought back once
        # hidden -- the toggle itself must live outside what it hides
        self._toggle_btn = QToolButton()
        self._toggle_btn.setArrowType(Qt.ArrowType.LeftArrow)
        self._toggle_btn.setToolTip("Hide visuals panel")
        self._toggle_btn.setAutoRaise(True)
        self._toggle_btn.clicked.connect(
            lambda: self.set_visuals_visible(not self._visuals_visible))
        toggle_strip = QWidget()
        toggle_strip.setFixedWidth(20)
        toggle_layout = QVBoxLayout(toggle_strip)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.addWidget(self._toggle_btn)
        toggle_layout.addStretch(1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toggle_strip)
        layout.addWidget(self._splitter, 1)

        # a dashboard is for looking at, so the page opens as canvas and the
        # visuals panel is asked for -- silently, since nothing has changed yet
        self.set_visuals_visible(visuals_visible, notify=False)

    def set_visuals_visible(self, visible: bool, notify: bool = True) -> None:
        self._visuals_visible = visible
        self._side.setVisible(visible)
        self._toggle_btn.setArrowType(
            Qt.ArrowType.LeftArrow if visible else Qt.ArrowType.RightArrow)
        self._toggle_btn.setToolTip(
            "Hide visuals panel" if visible else "Show visuals panel")
        if notify:
            self.visuals_visibility_changed.emit(visible)

    def dispose(self) -> None:
        self.scene.dispose()
        self.visuals.dispose()
