"""NodeGraphView: the modeling canvas — ZoomPanGraphicsView plus node
drag & drop, the Tab palette, node keyboard shortcuts, minimap, and the
node context menu."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from .base_view import (ZoomPanGraphicsView, edge_scroll_delta,
                        EDGE_SCROLL_TICK_MS)
from .file_drop import resolve_dropped_path
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
    frame_dropped = Signal(str, QPointF)           # component id, scene pos
    files_dropped = Signal(list, QPointF)          # local file paths, scene pos
    node_context_requested = Signal(str, QPoint)   # node_id, global pos
    frame_context_requested = Signal(str, QPoint)  # frame_id, global pos
    # An order edge only: a data wire has never had a menu, and the one this
    # opens is about what an order edge *is*.
    order_context_requested = Signal(str, QPoint)  # conn_id, global pos

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

        # Edge-scroll while anything is being dragged (G3): hold a wire, a
        # node or a frame against a viewport border and the canvas glides
        # that way until the destination is on screen, so wiring or placing
        # two things that are not on screen together no longer means letting
        # go, panning, and starting again.
        self._edge_timer = QTimer(self)
        self._edge_timer.setInterval(EDGE_SCROLL_TICK_MS)
        self._edge_timer.timeout.connect(self._edge_scroll_tick)
        scene.canvas_drag_changed.connect(self._set_edge_scrolling)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.minimap.reposition()
        self.search_bar.reposition()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.minimap.reposition()
        self.search_bar.reposition()

    # ------------------------------------------------------------ edge scroll

    def _set_edge_scrolling(self, active: bool) -> None:
        if active:
            self._edge_timer.start()
        else:
            self._edge_timer.stop()

    def _edge_scroll_tick(self) -> None:
        scene = self.scene()
        if scene is None or not scene.canvas_drag_active:
            # a belt for the signal being missed (scene swapped mid-drag)
            self._edge_timer.stop()
            return
        if self._panning:
            # a middle-drag pan is its own way of reaching the edge; it must
            # never also trigger the drag-a-thing-to-the-border scroll, even
            # if some stale drag state left the timer running
            return
        self.edge_scroll_at(QCursor.pos())

    def edge_scroll_at(self, global_pos: QPoint) -> None:
        """One edge-scroll step as if the cursor were at `global_pos`.

        Split from the timer tick so tests can drive it without moving the
        real cursor. Scrolling alone would strand what is being dragged:
        a pan changes which scene point the cursor means, so each branch
        re-aims at the hand — the wire directly, and a dragged selection by
        feeding the view a synthetic mouse move (see _ride_selection)."""
        viewport = self.viewport()
        cursor = viewport.mapFromGlobal(global_pos)
        delta = edge_scroll_delta(viewport.rect(), cursor)
        if delta.isNull():
            return
        self.scroll_by(delta.x(), delta.y())
        scene = self.scene()
        if scene.wire_drag_active:
            scene.update_wire_drag(self.mapToScene(cursor))
        elif scene.group_drag_active:
            self._ride_selection(cursor)

    def _ride_selection(self, cursor: QPoint) -> None:
        """Keep a dragged selection under the hand after an edge pan.

        Qt moves a movable item to *press position + total cursor travel*,
        recomputed from its press anchor on every real move — so panning
        underneath and nudging the items ourselves would be clobbered (and
        the selection snap back) by the next mouse move. A synthetic move
        through the ordinary event path instead lets Qt do the arithmetic
        with post-pan coordinates: the selection lands where it would have
        had the mouse really carried it there, snapping, carried contents,
        group moves and all."""
        event = QMouseEvent(QEvent.MouseMove,
                            QPointF(cursor), self.mapToGlobal(cursor),
                            Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(self.viewport(), event)

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
        self.center_on_scene(item)
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
        from .connection_item import ConnectionItem
        item = self.itemAt(event.pos())
        scene_pos = self.mapToScene(event.pos())
        if item is None:
            self.add_node_requested.emit(scene_pos, event.globalPos())
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
            # Same split as the drag: the title bar is the frame, the body is
            # canvas. A frame is usually bigger than the screen, so treating
            # its whole rectangle as the frame meant that inside one — which
            # is exactly where you want to add the next node — the canvas
            # menu was unreachable.
            if item.chrome_at(item.mapFromScene(scene_pos)):
                self.frame_context_requested.emit(item.frame.id,
                                                  event.globalPos())
            else:
                self.add_node_requested.emit(scene_pos, event.globalPos())
            event.accept()
            return
        if isinstance(item, ConnectionItem) and item.is_order:
            self.order_context_requested.emit(item.conn.id, event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    # ---------------------------------------------------------- drag & drop

    def _matching_dropped_files(self, mime) -> list[str]:
        """Local paths in `mime` — files or folders — that map to a node."""
        if not mime.hasUrls():
            return []
        local_paths = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
        return [p for p in local_paths if resolve_dropped_path(p)]

    def dragEnterEvent(self, event) -> None:
        from .palette import FRAME_ID_MIME, NODE_TYPE_MIME
        if event.mimeData().hasFormat(NODE_TYPE_MIME) \
                or event.mimeData().hasFormat(FRAME_ID_MIME):
            event.acceptProposedAction()
        elif event.mimeData().hasUrls():
            if self._matching_dropped_files(event.mimeData()):
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            super().dragEnterEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self.scene().clear_drop_hint()
        super().dragLeaveEvent(event)

    def dragMoveEvent(self, event) -> None:
        from .palette import FRAME_ID_MIME, NODE_TYPE_MIME
        if event.mimeData().hasFormat(NODE_TYPE_MIME):
            # light up what this drop would do, so letting go is never a
            # guess: a green wire means splice, a ringed node means replace
            type_id = bytes(event.mimeData().data(NODE_TYPE_MIME)).decode()
            self.scene().set_drop_hint(self.scene().drop_target_at(
                type_id, self.mapToScene(event.position().toPoint())))
            event.acceptProposedAction()
        elif event.mimeData().hasFormat(FRAME_ID_MIME):
            event.acceptProposedAction()
        elif event.mimeData().hasUrls():
            if self._matching_dropped_files(event.mimeData()):
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        from .palette import FRAME_ID_MIME, NODE_TYPE_MIME
        if event.mimeData().hasFormat(NODE_TYPE_MIME):
            type_id = bytes(event.mimeData().data(NODE_TYPE_MIME)).decode()
            scene_pos = self.mapToScene(event.position().toPoint())
            scene: NodeGraphScene = self.scene()
            scene.clear_drop_hint()
            # Alt drops past the aiming: a plain add exactly where released,
            # for parking a node on or beside a wire without touching it.
            target = None if (event.modifiers() & Qt.AltModifier) \
                else scene.drop_target_at(type_id, scene_pos)
            handled = False
            if target is not None:
                kind, obj = target
                if kind == "wire":
                    handled = scene.splice_into_wire(
                        type_id, obj.conn.id, scene_pos)
                else:
                    handled = scene.replace_node_with(type_id, obj.node.id)
            if not handled:
                self.node_dropped.emit(type_id, scene_pos)
            event.acceptProposedAction()
        elif event.mimeData().hasFormat(FRAME_ID_MIME):
            frame_id = bytes(event.mimeData().data(FRAME_ID_MIME)).decode()
            self.frame_dropped.emit(
                frame_id, self.mapToScene(event.position().toPoint()))
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
