"""NodeGraphView: the modeling canvas — ZoomPanGraphicsView plus node
drag & drop, the Tab palette, node keyboard shortcuts, minimap, and the
node context menu."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QKeyEvent

from .base_view import ZoomPanGraphicsView
from .file_drop import resolve_dropped_file
from .scene import NodeGraphScene
from .stacking import layer_action_for

# Hold this to see every port's name. Q because the canvas has already spent
# F (frame), Tab (palette), Space (pan), Delete/Backspace and the arrows, and
# because a letter next to nothing important is cheap to hold with the left
# hand while the right one is on the mouse.
DEFAULT_REVEAL_PORTS_KEY = Qt.Key_Q


class NodeGraphView(ZoomPanGraphicsView):
    add_node_requested = Signal(QPointF, QPoint)   # scene pos, global pos
    palette_requested = Signal(QPointF, QPoint)    # scene pos, global pos
    node_dropped = Signal(str, QPointF)            # type_id, scene pos
    files_dropped = Signal(list, QPointF)          # local file paths, scene pos
    node_context_requested = Signal(str, QPoint)   # node_id, global pos
    frame_context_requested = Signal(str, QPoint)  # frame_id, global pos

    def __init__(self, scene: NodeGraphScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setAcceptDrops(True)
        # Held-key port-name reveal. A bare key rather than a modifier: Alt
        # is the menu bar's on both Linux and Windows, so binding it here
        # means either swallowing that or having the menu bar flicker into
        # focus on every tap. The main window is the sole writer.
        self.reveal_ports_key = DEFAULT_REVEAL_PORTS_KEY
        self._reveal_held = False

        from .minimap import Minimap
        self.minimap = Minimap(self)
        self.minimap.show()

        from .node_search import NodeSearchBar
        self.search_bar = NodeSearchBar(self)
        self.search_bar.reveal_requested.connect(self.go_to_node)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.minimap.reposition()
        self.search_bar.reposition()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.minimap.reposition()
        self.search_bar.reposition()

    # -------------------------------------------------------------- find/goto

    def open_search(self) -> None:
        """Ctrl+F, or Edit > Find Node…"""
        self.search_bar.open_bar()

    def go_to_node(self, node_id: str) -> bool:
        """Select one node and bring the view to it.

        Zoomed far out the centring alone lands on a flattened smudge (the
        canvas drops node detail below its LOD threshold), so a jump from
        further out than MIN_REVEAL_ZOOM zooms back in to something
        readable. Closer in, the zoom is left alone — the user chose it.
        """
        from .node_search import MIN_REVEAL_ZOOM, REVEAL_ZOOM
        scene: NodeGraphScene = self.scene()
        item = scene.node_items.get(node_id)
        if item is None:
            return False
        if not item.isVisible():
            # Search resolves against the graph, so a node folded inside a
            # collapsed frame is findable — but centring on it would park the
            # view on empty canvas with nothing selected (Qt ignores
            # setSelected on a hidden item). Show the box holding it instead.
            owner = scene._owner_of(node_id)
            frame_item = scene.frame_items.get(owner) if owner else None
            if frame_item is not None:
                item = frame_item
        scene.clearSelection()
        item.setSelected(True)
        if self.zoom < MIN_REVEAL_ZOOM:
            self.set_zoom(REVEAL_ZOOM)
        self.centerOn(item)
        return True

    # ------------------------------------------------------------ keyboard

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._proxy_widget_has_focus():
            # A note editor or table cell is focused inside an embedded
            # widget — let it handle keys (backspace, arrows, letters)
            # instead of hijacking them as canvas shortcuts.
            super().keyPressEvent(event)
            return
        key = event.key()
        # Before everything else, and only on a bare press: holding it with a
        # modifier down is somebody reaching for a different shortcut.
        # isAutoRepeat is mandatory — X11 and Wayland synthesise release/press
        # pairs while a key is held, so without it a hold reads as a stutter.
        if (key == self.reveal_ports_key and not event.isAutoRepeat()
                and not event.modifiers()):
            self._set_reveal_held(True)
            event.accept()
            return
        if key == Qt.Key_Tab:
            cursor_pos = self.mapFromGlobal(self.cursor().pos())
            if not self.viewport().rect().contains(cursor_pos):
                cursor_pos = self.viewport().rect().center()
            self.palette_requested.emit(
                self.mapToScene(cursor_pos), self.mapToGlobal(cursor_pos))
            event.accept()
            return
        if key == Qt.Key_Delete or key == Qt.Key_Backspace:
            self.scene().delete_selection()
            event.accept()
            return
        if key == Qt.Key_F:
            self.frame_content()
            event.accept()
            return
        if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            self._nudge_selection(key, 10.0 if not event.modifiers() & Qt.ShiftModifier else 1.0)
            event.accept()
            return
        action = layer_action_for(event)
        if action is not None and self.scene().restack_selection(action):
            event.accept()
            return
        super().keyPressEvent(event)  # space-pan lives in the base view

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == self.reveal_ports_key and not event.isAutoRepeat():
            self._set_reveal_held(False)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _set_reveal_held(self, held: bool) -> None:
        if held == self._reveal_held:
            return
        self._reveal_held = held
        self.scene().set_revealing_port_labels(held)

    def set_reveal_ports_key(self, key: int) -> None:
        """Rebind the hold-to-reveal key. Ends any reveal in progress, since
        the release of the old key will never be recognised."""
        self._set_reveal_held(False)
        self.reveal_ports_key = key

    # The key-release that ends a reveal can be swallowed outright — a popup
    # takes focus, the pointer leaves, the window deactivates with the key
    # still down — and the names would then stay up with nothing holding
    # them. Same three belts space-pan wears, for the same reason.

    def focusOutEvent(self, event) -> None:
        self._set_reveal_held(False)
        super().focusOutEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_reveal_held(False)
        super().leaveEvent(event)

    def changeEvent(self, event) -> None:
        if (event.type() == QEvent.ActivationChange
                and not self.isActiveWindow()):
            self._set_reveal_held(False)
        super().changeEvent(event)

    def _nudge_selection(self, key, step: float) -> None:
        scene: NodeGraphScene = self.scene()
        items = scene.selected_node_items()
        if not items:
            return
        dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(key, 0.0)
        dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(key, 0.0)
        moves = {}
        for item in items:
            old = (item.pos().x(), item.pos().y())
            moves[item.node.id] = (old, (old[0] + dx, old[1] + dy))
        scene.push_move_command(moves)

    def frame_content(self) -> None:
        """F: fit the selection (or everything) in view.

        Everything *visible*: nodes folded inside a collapsed frame would
        otherwise pull the fit out over a region showing nothing. Frames
        count too, or a canvas holding only collapsed ones fits to nothing.
        """
        scene: NodeGraphScene = self.scene()
        selected = scene.selected_node_items()
        if selected:
            self.fit_items(selected)
            return
        self.fit_items([item for item in (*scene.node_items.values(),
                                          *scene.frame_items.values())
                        if item.isVisible()])

    # --------------------------------------------------------- context menu

    def contextMenuEvent(self, event) -> None:
        from .node_item import NodeItem, PortItem
        from .frame_item import FrameItem
        item = self.itemAt(event.pos())
        if item is None:
            self.add_node_requested.emit(
                self.mapToScene(event.pos()), event.globalPos())
            event.accept()
            return
        if isinstance(item, PortItem):
            item = item.node_item
        if isinstance(item, NodeItem):
            if item.button:
                # Right-click on an Action Button enters edit mode (move/resize)
                # rather than opening the node context menu.
                item.enter_button_edit()
                event.accept()
                return
            self.node_context_requested.emit(item.node.id, event.globalPos())
            event.accept()
            return
        if isinstance(item, FrameItem):
            self.frame_context_requested.emit(item.frame.id, event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    # ---------------------------------------------------------- drag & drop

    def _matching_dropped_files(self, mime) -> list[str]:
        """Local file paths in `mime` that map to a known reader node."""
        if not mime.hasUrls():
            return []
        local_paths = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
        return [p for p in local_paths if resolve_dropped_file(p)]

    def dragEnterEvent(self, event) -> None:
        from .palette import NODE_TYPE_MIME
        if event.mimeData().hasFormat(NODE_TYPE_MIME):
            event.acceptProposedAction()
        elif event.mimeData().hasUrls():
            if self._matching_dropped_files(event.mimeData()):
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        from .palette import NODE_TYPE_MIME
        if event.mimeData().hasFormat(NODE_TYPE_MIME):
            event.acceptProposedAction()
        elif event.mimeData().hasUrls():
            if self._matching_dropped_files(event.mimeData()):
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        from .palette import NODE_TYPE_MIME
        if event.mimeData().hasFormat(NODE_TYPE_MIME):
            type_id = bytes(event.mimeData().data(NODE_TYPE_MIME)).decode()
            self.node_dropped.emit(
                type_id, self.mapToScene(event.position().toPoint()))
            event.acceptProposedAction()
        elif event.mimeData().hasUrls():
            paths = self._matching_dropped_files(event.mimeData())
            if paths:
                self.files_dropped.emit(
                    paths, self.mapToScene(event.position().toPoint()))
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            super().dropEvent(event)
