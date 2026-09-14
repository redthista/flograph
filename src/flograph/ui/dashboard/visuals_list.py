"""VisualsList: the flow's tile-able nodes (Show* visuals and Action
Buttons), draggable onto the dashboard page beside it — searchable by name,
filterable by type, and sorted by name or by type."""
from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QTimer, Qt, Signal
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
    # a page with a panel down its side — the nav tree beside the article
    "wiki": "◫",
    "slicer": "⑂",
    # not another square: the tables, the sheet and the picture already
    # carry those, and a fourth would be four marks nobody can tell apart
    # at 9pt
    "control": "⇵",
    "button": "▶",
    # a pilcrow: a paragraph of text, which is all a note is
    "note": "¶",
    # there and back: a way between the pages
    "pagelinks": "⇆",
}

#: What each sort of visual is called where a person picks it: the type
#: filter, the tooltips, and a search (typing "slicer" finds the slicers).
KIND_LABELS = {
    "figure": "Static chart",
    "webview": "Interactive visual",
    "table_viewer": "Table",
    "grid": "Spreadsheet",
    "kpi": "KPI",
    "image": "Image",
    "pdf": "PDF",
    "report": "Report",
    "wiki": "Wiki",
    "slicer": "Slicer",
    "control": "Input control",
    "button": "Button",
    "note": "Note",
    "pagelinks": "Page links",
}

SORT_NAME = "name"
SORT_NAME_DESC = "name_desc"
SORT_KIND = "kind"
#: The sort choices, in the order the panel offers them.
SORT_MODES = {SORT_NAME: "Name A–Z", SORT_NAME_DESC: "Name Z–A",
              SORT_KIND: "Type"}


def kind_label(kind) -> str:
    return KIND_LABELS.get(kind, "Other")


def kind_glyph(kind) -> str:
    return _KIND_GLYPHS.get(kind, "")


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


def sort_nodes(nodes, mode: str = SORT_NAME) -> list:
    """`nodes` in the panel's order. Name A–Z is the default for the reason
    above; Type is there for the long list where the sort of thing wanted
    *is* known — every slicer, say — and keeps names A–Z within each type."""
    from ..canvas.node_item import card_kind
    if mode == SORT_NAME_DESC:
        return sorted(nodes, key=_sort_key, reverse=True)
    if mode == SORT_KIND:
        return sorted(nodes, key=lambda node: (
            kind_label(card_kind(node)).casefold(), *_sort_key(node)))
    return sorted(nodes, key=_sort_key)


class VisualsList(QListWidget):
    #: the search, the type filter or the sort changed, or the list was
    #: rebuilt — whatever shows counts or an empty message re-reads it
    filters_changed = Signal()

    def __init__(self, graph: Graph, engine=None, parent=None) -> None:
        super().__init__(parent)
        self._graph = graph
        self._engine = engine
        # What is being looked for. The type filter works the way a slicer
        # does: the kinds ticked are the ones shown, and nothing ticked
        # shows every kind.
        self._search = ""
        self._kinds: frozenset = frozenset()
        self._sort = SORT_NAME
        self._present: dict = {}   # kind -> how many the flow has
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
        present: dict = {}
        for node in nodes:
            kind = card_kind(node)
            present[kind] = present.get(kind, 0) + 1
        self._present = present
        shown = [node for node in nodes if self._passes(node, card_kind(node))]
        for node in sort_nodes(shown, self._sort):
            kind = card_kind(node)
            item = QListWidgetItem(f"{kind_glyph(kind)} {node.label}".strip())
            item.setData(Qt.UserRole, node.id)
            item.setToolTip(f"{kind_label(kind)}\n"
                            "Drag onto the page to place this visual")
            self.addItem(item)
        self.filters_changed.emit()

    def _passes(self, node, kind) -> bool:
        """Whether a visual survives the type filter and the search. Every
        word typed has to be found, in its name or in its type's name, so
        "sales slicer" narrows rather than widens."""
        if self._kinds and kind not in self._kinds:
            return False
        words = self._search.casefold().split()
        if not words:
            return True
        haystack = f"{node.label} {kind_label(kind)}".casefold()
        return all(word in haystack for word in words)

    # --------------------------------------------------- search and filter

    def set_search(self, text: str) -> None:
        text = str(text or "")
        if text == self._search:
            return
        self._search = text
        self._rebuild()

    def search(self) -> str:
        return self._search

    def set_kinds(self, kinds) -> None:
        """Show only these kinds of visual; empty for every kind."""
        kinds = frozenset(kinds or ())
        if kinds == self._kinds:
            return
        self._kinds = kinds
        self._rebuild()

    def kinds(self) -> frozenset:
        return self._kinds

    def set_sort(self, mode: str) -> None:
        if mode not in SORT_MODES:
            raise ValueError(f"unknown sort {mode!r}")
        if mode == self._sort:
            return
        self._sort = mode
        self._rebuild()

    def sort_mode(self) -> str:
        return self._sort

    def clear_filters(self) -> None:
        """Back to every visual: no search, no type ticked. The sort is a
        way of reading the list, not a filter on it, so it stays."""
        if not self.is_filtered():
            return
        self._search = ""
        self._kinds = frozenset()
        self._rebuild()

    def is_filtered(self) -> bool:
        return bool(self._search.strip()) or bool(self._kinds)

    def kinds_present(self) -> list:
        """(kind, label, count) for each sort of visual the flow has, by
        label — what the type filter offers."""
        return [(kind, kind_label(kind), count)
                for kind, count in sorted(
                    self._present.items(),
                    key=lambda entry: kind_label(entry[0]).casefold())]

    def total_count(self) -> int:
        """How many visuals the flow has, whatever is filtered out."""
        return sum(self._present.values())

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
