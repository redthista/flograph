"""DashboardView: the pannable/zoomable viewport over one page's tiles,
accepting drags from the visuals list."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QKeyEvent

from ..canvas.base_view import ZoomPanGraphicsView
from .dashboard_scene import DashboardScene
from .visuals_list import TILE_NODE_MIME


class DashboardView(ZoomPanGraphicsView):
    tile_dropped = Signal(str, QPointF)  # node_id, scene pos

    def __init__(self, scene: DashboardScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setAcceptDrops(True)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if not self._proxy_widget_has_focus():
            key = event.key()
            if key == Qt.Key_Delete or key == Qt.Key_Backspace:
                self.scene().delete_selected_tiles()
                event.accept()
                return
            if key == Qt.Key_F:
                scene = self.scene()
                self.fit_items(scene.selected_tile_items()
                               or list(scene.tile_items.values()))
                event.accept()
                return
        super().keyPressEvent(event)

    # ---------------------------------------------------------- drag & drop

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(TILE_NODE_MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(TILE_NODE_MIME):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat(TILE_NODE_MIME):
            node_id = bytes(event.mimeData().data(TILE_NODE_MIME)).decode()
            self.tile_dropped.emit(
                node_id, self.mapToScene(event.position().toPoint()))
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
