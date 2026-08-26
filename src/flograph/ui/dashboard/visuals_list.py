"""VisualsList: the flow's tile-able nodes (Show* visuals and Action
Buttons), draggable onto the dashboard page beside it."""
from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QTimer, Qt
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem

from flograph.core import Graph

TILE_NODE_MIME = "application/x-flograph-tile-node"

#: Where the hover preview sits relative to the row it belongs to.
_OFFSET = QPoint(10, -6)

#: The mark in front of each row, saying what sort of visual it is.
#:
#: Geometric shapes rather than emoji, and deliberately: the emoji this
#: used to carry (📈 📊 🔢) live outside the Basic Multilingual Plane, and
#: on a machine whose UI font has no emoji coverage they paint *nothing* —
#: the rows came out indented by a space that wasn't there. Every glyph
#: below is BMP and comes with the ordinary sans fonts. Qt is no help in
#: spotting the difference: QFontMetrics.inFont() answers True for glyphs
#: it then declines to draw, so a candidate has to be painted and its ink
#: counted (see TestVisualGlyphs).
_KIND_GLYPHS = {
    "figure": "◔",
    "webview": "◉",
    "table_viewer": "▦",
    "grid": "▤",
    "kpi": "∑",
    "image": "▣",
    # a page with a folded corner: a document, not another square
    "pdf": "◱",
    "report": "☰",
    "slicer": "⑂",
    # not another square: the tables, the sheet and the picture already
    # carry those, and a fourth would be four marks nobody can tell apart
    # at 9pt
    "control": "⇵",
    "button": "▶",
}

def _sort_key(node) -> tuple:
    """One flat alphabetical run, case-blind.

    This was briefly grouped by kind — charts, then tables, then the
    furniture — on the theory that a long list is read by looking for the
    *sort* of thing wanted. In use it isn't: you know the name of the
    visual you are placing, and grouping means knowing which group it falls
    in before you can find it. The glyph still says what each row is, which
    is the part of grouping that was actually earning its keep. The node id
    breaks ties so two visuals sharing a name hold a stable order.
    """
    return (node.label.casefold(), node.id)


class VisualsList(QListWidget):
    def __init__(self, graph: Graph, engine=None, parent=None) -> None:
        super().__init__(parent)
        self._graph = graph
        self._engine = engine
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

        # hovering a row shows what the visual looks like, once the cursor
        # has settled — see visual_preview for why it waits
        from .visual_preview import HOVER_DELAY_MS
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._popup = None
        self._hover_item = None
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(HOVER_DELAY_MS)
        self._hover_timer.timeout.connect(self._show_preview)
        self.itemEntered.connect(self._on_item_entered)
        if self.verticalScrollBar() is not None:
            self.verticalScrollBar().valueChanged.connect(
                lambda _value: self._hide_preview())

        events = graph.events
        self._event_subs = [
            (events.node_added, self._on_nodes_changed),
            (events.node_removed, self._on_nodes_changed),
            (events.label_changed, self._on_nodes_changed),
        ]
        for event, callback in self._event_subs:
            event.connect(callback)
        self._rebuild()

    def dispose(self) -> None:
        """Core events hold strong refs — disconnect on page removal."""
        for event, callback in self._event_subs:
            event.disconnect(callback)
        self._event_subs = []
        self._hide_preview()
        if self._popup is not None:
            self._popup.deleteLater()
            self._popup = None

    def _on_nodes_changed(self, *args) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        from ..canvas.node_item import card_kind
        from .tile_item import is_tile_able
        self._hide_preview()
        self.clear()
        nodes = [node for node in self._graph.nodes.values()
                 if is_tile_able(node)]
        for node in sorted(nodes, key=_sort_key):
            glyph = _KIND_GLYPHS.get(card_kind(node), "")
            item = QListWidgetItem(f"{glyph} {node.label}".strip())
            item.setData(Qt.UserRole, node.id)
            item.setToolTip("Drag onto the page to place this visual")
            self.addItem(item)

    # ------------------------------------------------------- hover preview

    def _on_item_entered(self, item: QListWidgetItem) -> None:
        if item is self._hover_item and self._popup is not None \
                and self._popup.isVisible():
            return
        self._hide_preview()
        self._hover_item = item
        self._hover_timer.start()

    def _hide_preview(self) -> None:
        self._hover_timer.stop()
        self._hover_item = None
        if self._popup is not None:
            self._popup.hide()

    def _preview_node(self):
        """The node the pending preview is for, or None if the row it was
        started for has since gone (a rename rebuilds the whole list)."""
        if self._hover_item is None or self._engine is None:
            return None
        if self.row(self._hover_item) < 0:
            return None
        return self._graph.nodes.get(self._hover_item.data(Qt.UserRole))

    def _show_preview(self) -> None:
        node = self._preview_node()
        if node is None or not self.isVisible():
            return
        from .visual_preview import (
            DRAWING, VisualPreviewPopup, preview, slow_to_draw,
        )
        if self._popup is None:
            self._popup = VisualPreviewPopup(self)
        item = self._hover_item
        if slow_to_draw(node):
            # up before the picture is asked for: taking a Plotly chart's
            # snapshot runs the browser, and the first of a session is slow
            # enough that a popup appearing afterwards would look like a
            # hang rather than a preview
            self._popup.show_message(DRAWING)
            self._place_popup(item)
            self._popup.repaint()
        pixmap, message = preview(self._graph, self._engine, node,
                                  ratio=self.devicePixelRatioF() or 1.0)
        if self._hover_item is not item:
            return  # the cursor moved on while the chart was being drawn
        if pixmap is not None:
            self._popup.show_pixmap(pixmap)
        else:
            self._popup.show_message(message)
        self._place_popup(item)

    def _place_popup(self, item: QListWidgetItem) -> None:
        """Beside the row, not under the cursor: the panel is narrow and a
        popup over the list would cover the rows being scanned."""
        rect = self.visualItemRect(item)
        self._popup.move_onto_screen(
            self.viewport().mapToGlobal(rect.topRight()) + _OFFSET)
        self._popup.show()
        self._popup.raise_()

    def leaveEvent(self, event) -> None:
        self._hide_preview()
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:
        self._hide_preview()
        super().hideEvent(event)

    def mousePressEvent(self, event) -> None:
        # a press is the start of a drag onto the page; the preview has done
        # its job and would only follow the cursor around
        self._hide_preview()
        super().mousePressEvent(event)

    def wheelEvent(self, event) -> None:
        self._hide_preview()
        super().wheelEvent(event)

    def mimeData(self, items) -> QMimeData:
        mime = QMimeData()
        for item in items:
            node_id = item.data(Qt.UserRole)
            if node_id:
                mime.setData(TILE_NODE_MIME, node_id.encode())
                break
        return mime

    def mimeTypes(self) -> list[str]:
        return [TILE_NODE_MIME]
