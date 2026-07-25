"""DashboardView: the pannable/zoomable viewport over one page's tiles,
accepting drags from the visuals list.

It also renders *fullscreen*: one tile pinned to the whole viewport, resizing
with the window so an embedded Plotly chart or table grows with it. The tile
is laid out in scene coordinates at 1:1 zoom rather than lifted into a
separate window — the content widget stays in its proxy, so nothing is
rebuilt on the way in or out, and painted tiles (KPI) scale up too. The
stored tile *rect* is never touched; only the page's `maximized_tile` says
what is maximized, and the scene is the sole caller of enter/exit here —
turning fullscreen on or off is a model edit (see DashboardScene)."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QKeyEvent

from ..canvas.base_view import ZoomPanGraphicsView
from .dashboard_scene import DashboardScene
from .tile_item import TileItem
from .visuals_list import TILE_NODE_MIME

FS_MARGIN = 6.0  # breathing room between a maximized tile and the viewport


class DashboardView(ZoomPanGraphicsView):
    tile_dropped = Signal(str, QPointF)  # node_id, scene pos
    fullscreen_changed = Signal(bool)    # a tile was maximized / restored

    def __init__(self, scene: DashboardScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setAcceptDrops(True)
        self._fs_tile: Optional[TileItem] = None
        self._fs_restore: Optional[tuple] = None  # (transform, scene centre)

    # --------------------------------------------------------- fullscreen

    @property
    def fullscreen_tile(self) -> Optional[TileItem]:
        return self._fs_tile

    def enter_fullscreen(self, item: TileItem) -> None:
        if not item.can_fullscreen():
            return
        if self._fs_tile is not None:
            self.exit_fullscreen()
        # 1:1 zoom while maximized: scene units are viewport pixels, so the
        # embedded widgets render at their natural resolution instead of
        # through a magnifying transform
        self._fs_restore = (self.transform(),
                            self.mapToScene(self.viewport().rect().center()))
        self.resetTransform()
        self._fs_tile = item
        for other in self.scene().tile_items.values():
            if other is not item:
                other.setVisible(False)
        self._layout_fullscreen()
        self._zoom_updated()
        self.fullscreen_changed.emit(True)

    def exit_fullscreen(self) -> None:
        item, self._fs_tile = self._fs_tile, None
        if item is None:
            return
        scene = self.scene()
        if scene is not None:
            for other in scene.tile_items.values():
                other.setVisible(True)
        item.clear_fullscreen()
        if self._fs_restore is not None:
            transform, center = self._fs_restore
            self._fs_restore = None
            self.setTransform(transform)
            self.centerOn(center)
            self._zoom_updated()
        # A fullscreen restored from the saved file was entered before the
        # view had ever been laid out, so the centre captured then points
        # nowhere useful. Whatever the reason, don't leave the user staring
        # at empty canvas with the tile they were just reading off-screen.
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        if not visible.intersects(item.sceneBoundingRect()):
            self.centerOn(item.sceneBoundingRect().center())
        self.fullscreen_changed.emit(False)

    def _layout_fullscreen(self) -> None:
        """Re-pin the maximized tile to the viewport — on entry, and on every
        resize after, which is what makes the chart grow with the window."""
        if self._fs_tile is None:
            return
        rect = self.mapToScene(self.viewport().rect()).boundingRect()
        rect.adjust(FS_MARGIN, FS_MARGIN, -FS_MARGIN, -FS_MARGIN)
        self._fs_tile.set_fullscreen_rect(rect)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_fullscreen()

    # --------------------------------------------------- navigation gating

    def wheelEvent(self, event) -> None:
        # Zooming or panning while maximized would just slide the tile off
        # the viewport it's pinned to; a wheel over scrollable content (a
        # table, a web view) still belongs to that widget.
        if (self._fs_tile is not None
                and self._scrollable_widget_at(
                    event.position().toPoint()) is None):
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:
        if self._fs_tile is not None and event.button() == Qt.MiddleButton:
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if self._fs_tile is not None:
            if key == Qt.Key_Escape:
                # through the model, like the button: the maximized tile is
                # saved with the project
                self.scene().exit_fullscreen()
                event.accept()
                return
            if key in (Qt.Key_Space, Qt.Key_F):  # no pan, no fit-to-items
                event.accept()
                return
        if not self._proxy_widget_has_focus():
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
