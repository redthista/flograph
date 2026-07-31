"""DashboardView: the pannable/zoomable viewport over one page's tiles,
accepting drags from the visuals list.

It also renders *fullscreen*, one tile filling the page, by one of two
routes. A tile that scrolls — a spreadsheet, a data table, a report — is
maximized into a **native overlay**: a plain widget laid over the viewport,
outside the graphics scene entirely. A widget inside a QGraphicsProxyWidget
cannot scroll by blitting, so every notch of the wheel re-renders the whole
visible grid, and the cost grows with the window: measured at 1440p, 26 ms
a scroll against 2.4 ms for the same grid as a native widget. On a page
built for typing data in, that is the difference between usable and not.
The overlay binds a *second* view to the tile's own model rather than
moving the tile's widget, so nothing is re-parented and both stay in step
by themselves.

Everything else — a KPI (painted), a figure (its own resolution handling in
the proxy), a Plotly view (a web engine that dislikes re-parenting) — is
still pinned in scene coordinates at 1:1 zoom, where it was already fine.

Either way the stored tile *rect* is never touched; only the page's
`maximized_tile` says what is maximized, and the scene is the sole caller of
enter/exit here — turning fullscreen on or off is a model edit (see
DashboardScene)."""
from __future__ import annotations

from typing import Optional

import shiboken6 as shiboken
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QKeyEvent, QPalette
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMenu, QToolButton,
                               QVBoxLayout, QWidget)

from .. import theme
from ..canvas.base_view import ZoomPanGraphicsView
from ..canvas.stacking import add_layer_menu, layer_action_for
from .dashboard_scene import DashboardScene
from .tile_item import TileItem
from .visuals_list import TILE_NODE_MIME

FS_MARGIN = 6.0  # breathing room between a maximized tile and the viewport
OVERLAY_TITLE_H = 28


class FullscreenOverlay(QWidget):
    """A maximized tile's content as a real widget over the viewport.

    Owns nothing but its chrome: the content comes from the tile and is
    thrown away with the overlay, while the model it reads stays with the
    tile. Escape restores — but only when nothing underneath wanted it
    first, which is what keeps Escape cancelling a half-typed cell.
    """

    def __init__(self, title: str, content: QWidget, on_restore,
                 parent=None) -> None:
        super().__init__(parent)
        self._on_restore = on_restore
        # A plain QWidget subclass paints no background of its own, and
        # setting a stylesheet does *not* change that unless the widget is
        # told to honour it — a stylesheet without WA_StyledBackground is
        # silently ignored for the background and also suppresses the
        # autoFillBackground path, leaving the widget fully transparent.
        # That is what showed the canvas straight through the title bar and
        # the toolbar. Palette first, so the fill stands on its own, and the
        # attribute so the stylesheet is honoured too.
        palette = self.palette()
        palette.setColor(QPalette.Window, theme.NODE_BODY)
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"FullscreenOverlay {{ background: {theme.NODE_BODY.name()}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(4)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        label = QLabel(title)
        label.setStyleSheet(
            f"color: {theme.NODE_TEXT.name()}; font-weight: 600;")
        restore = QToolButton(text="✕")
        restore.setAutoRaise(True)
        restore.setToolTip("Restore (Esc)")
        restore.clicked.connect(lambda: self._on_restore())
        bar.addWidget(label)
        bar.addStretch(1)
        bar.addWidget(restore)

        layout.addLayout(bar)
        layout.addWidget(content, 1)
        self.content = content

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # reached only if no child consumed it, so a cell editor still gets
        # its own Escape to cancel with
        if event.key() == Qt.Key_Escape:
            self._on_restore()
            event.accept()
            return
        super().keyPressEvent(event)


class DashboardView(ZoomPanGraphicsView):
    tile_dropped = Signal(str, QPointF)  # node_id, scene pos
    fullscreen_changed = Signal(bool)    # a tile was maximized / restored

    def __init__(self, scene: DashboardScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setAcceptDrops(True)
        self._fs_tile: Optional[TileItem] = None
        self._fs_restore: Optional[tuple] = None  # (transform, scene centre)
        self._fs_overlay: Optional[FullscreenOverlay] = None

    # --------------------------------------------------------- fullscreen

    @property
    def fullscreen_tile(self) -> Optional[TileItem]:
        return self._fs_tile

    @property
    def fullscreen_overlay(self) -> Optional[FullscreenOverlay]:
        """The native overlay, when this tile's kind uses one and it is
        still alive."""
        return self._live_overlay()

    def _live_overlay(self) -> Optional[FullscreenOverlay]:
        """The overlay, or None once Qt has destroyed it underneath us.

        The overlay is a child of the viewport, so anything that tears the
        page down — deleting the page, closing the project — deletes it
        through C++ without going through exit_fullscreen. The Python
        wrapper survives that and looks perfectly ordinary; touching it
        raises "Internal C++ object already deleted", and since the next
        thing to touch it is resizeEvent, that lands as an unhandled error
        in the middle of removing a page. Ask whether the object is still
        there rather than assuming, and forget it once it is not.
        """
        overlay = self._fs_overlay
        if overlay is not None and not shiboken.isValid(overlay):
            self._fs_overlay = None
            return None
        return overlay

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

        content = item.fullscreen_widget()
        if content is not None:
            # out of the scene entirely — see the module docstring for why
            # onto the viewport, not the view: the viewport's rect is exactly
            # the area the scene would have filled
            self._fs_overlay = FullscreenOverlay(
                item.fullscreen_title(), content,
                self._restore_from_overlay, self.viewport())
            item.set_fullscreen_overlaid()
            item.setVisible(False)
        self._layout_fullscreen()
        if self._fs_overlay is not None:
            self._fs_overlay.show()
            self._fs_overlay.raise_()
            content.setFocus()
        self._zoom_updated()
        self.fullscreen_changed.emit(True)

    def _restore_from_overlay(self) -> None:
        """Escape or the overlay's close button. Goes through the model like
        every other way out, so the maximized tile saved with the project
        stays the truth."""
        scene = self.scene()
        if scene is not None:
            scene.exit_fullscreen()

    def exit_fullscreen(self) -> None:
        item, self._fs_tile = self._fs_tile, None
        overlay, self._fs_overlay = self._live_overlay(), None
        if overlay is not None:
            overlay.hide()
            overlay.setParent(None)
            overlay.deleteLater()
        if item is None:
            return
        scene = self.scene()
        if scene is not None:
            for other in scene.tile_items.values():
                other.setVisible(True)
        item.setVisible(True)
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
        overlay = self._live_overlay()
        if overlay is not None:
            overlay.setGeometry(self.viewport().rect())
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
        # While the native overlay is up the page is not being edited, it is
        # being read and typed into. Delete must never reach the tiles: the
        # only reason a Delete arrives here is that a grid below chose not to
        # take it, and "clear the cell" failing must not become "delete the
        # tile".
        if not self._proxy_widget_has_focus() and self._fs_overlay is None:
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
            action = layer_action_for(event)
            if action is not None and self.scene().restack_selection(action):
                event.accept()
                return
        super().keyPressEvent(event)

    # --------------------------------------------------------- context menu

    def contextMenuEvent(self, event) -> None:
        """Right-click a tile for its layer actions. Right-click selects
        first (adding to the selection when Ctrl or Shift is held), so the
        menu always acts on what the user is looking at — and a right-click
        on an Action Button still can't fire it."""
        item = self._tile_at(event.pos())
        if item is None or self._fs_tile is not None:
            super().contextMenuEvent(event)
            return
        if not item.isSelected():
            if not event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
                self.scene().clearSelection()
            item.setSelected(True)
        menu = QMenu(self)
        layer_actions = add_layer_menu(menu)
        browser_action = None
        node = self._browsable_node(item)
        if node is not None:
            menu.addSeparator()
            browser_action = menu.addAction("Open in Browser")
        chosen = menu.exec(event.globalPos())
        if chosen in layer_actions:
            self.scene().restack_selection(layer_actions[chosen])
        elif browser_action is not None and chosen is browser_action:
            from ..browser import open_node_from
            scene = self.scene()
            open_node_from(self, node, scene.engine.cache.get(node.id))
        event.accept()

    def _browsable_node(self, item: TileItem):
        """The node behind a webview tile that has something to open, else
        None. A dashboard is where the tile is *smallest*, so handing the
        page to a full browser window matters more here than on the canvas."""
        from ..browser import can_open
        from ..canvas.node_item import card_kind
        scene = self.scene()
        node = scene.graph.nodes.get(item.tile.node_id)
        if node is None or card_kind(node) != "webview":
            return None
        entry = scene.engine.cache.get(node.id)
        return node if can_open(node, entry) else None

    def _tile_at(self, pos) -> Optional[TileItem]:
        for item in self.items(pos):
            while item is not None and not isinstance(item, TileItem):
                item = item.parentItem()
            if item is not None:
                return item
        return None

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
