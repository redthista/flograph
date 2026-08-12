"""Find a node by name on the canvas (Ctrl+F).

A strip in the corner of the view rather than a dialog, for the same reason
the code editor's find bar is one: the thing you are searching has to stay
visible while you type. Every keystroke re-ranks the list, and moving
through the list *takes the canvas with it* — the node under the cursor is
selected and centred as you arrow, so finding it and looking at it are the
same gesture rather than two.

That live jumping is only safe because leaving is free: Esc puts the view
back exactly where it was, zoom included, so a search that found nothing
useful costs nothing. Enter is the opposite word — keep this one, close the
bar, leave the node selected and the canvas where the node is.

The bar takes the graph fresh on every keystroke, so nodes added, renamed
or deleted while it is open are simply searched as they now are.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QToolButton, QVBoxLayout,
)

from flograph.core.search import search_nodes

from .. import theme

WIDTH = 260
#: Hits shown before the list starts scrolling. The list is sized to what it
#: actually holds, so three matches are a three-line box and not a slab of
#: empty panel sitting over the canvas.
MAX_ROWS = 8
MARGIN = 12

#: Below this zoom a node is a smudge — flattened by the canvas LOD at 0.35,
#: and its name unreadable well before that. Jumping to a node the user
#: cannot then read is not arriving, so a jump from further out than this
#: zooms in to something legible on the way.
MIN_REVEAL_ZOOM = 0.6
REVEAL_ZOOM = 1.0


class NodeSearchBar(QFrame):
    """Incremental search over the nodes in one canvas."""

    #: node_id — emitted as the highlighted row changes and on accept
    reveal_requested = Signal(str)

    def __init__(self, view) -> None:
        super().__init__(view)
        self._view = view
        self._home: Optional[QPointF] = None
        self._home_zoom = 1.0

        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText("Find node…")
        self._edit.setClearButtonEnabled(True)
        self._edit.textChanged.connect(self._refresh)
        self._edit.returnPressed.connect(self.accept)
        self._edit.installEventFilter(self)

        self._count = QLabel("", self)
        self._count.setStyleSheet(f"color: {theme.NODE_SUBTEXT.name()};")

        close_btn = QToolButton(self)
        close_btn.setText("✕")
        close_btn.setToolTip("Close (Esc)")
        close_btn.clicked.connect(self.cancel)

        self._list = QListWidget(self)
        self._list.setUniformItemSizes(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.currentItemChanged.connect(self._on_current_changed)
        self._list.itemClicked.connect(lambda _item: self.accept())

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(self._edit, 1)
        row.addWidget(self._count)
        row.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.addLayout(row)
        layout.addWidget(self._list)

        self.setFixedWidth(WIDTH)
        self.setFrameShape(QFrame.StyledPanel)
        # The bar floats over the canvas, so it is dressed as canvas
        # furniture (the minimap's neighbours) rather than as a dock widget:
        # left to the desktop palette the list comes out a white slab on a
        # dark graph.
        self.setStyleSheet(
            f"NodeSearchBar {{ background: {theme.NODE_BODY.name()};"
            f" border: 1px solid {theme.NODE_BORDER.name()};"
            f" border-radius: 4px; }}"
            f"QLineEdit {{ background: {theme.CANVAS_BG.name()};"
            f" color: {theme.NODE_TEXT.name()};"
            f" border: 1px solid {theme.NODE_BORDER.name()};"
            f" border-radius: 3px; padding: 2px 4px; }}"
            f"QToolButton {{ color: {theme.NODE_SUBTEXT.name()};"
            f" border: none; }}"
            f"QToolButton:hover {{ color: {theme.NODE_TEXT.name()}; }}")
        theme.style_scroll_area(self._list, self._list_stylesheet(),
                                theme.CANVAS_BG)
        self.hide()

    @staticmethod
    def _list_stylesheet() -> str:
        return (f"QListWidget {{ background: {theme.CANVAS_BG.name()};"
                f" color: {theme.NODE_TEXT.name()};"
                f" border: 1px solid {theme.NODE_BORDER.name()};"
                f" border-radius: 3px; outline: none; }}"
                f"QListWidget::item {{ padding: 1px 3px; }}"
                f"QListWidget::item:selected {{"
                f" background: {theme.SELECTION_OUTLINE.name()};"
                f" color: {theme.CANVAS_BG.name()}; }}")

    # ------------------------------------------------------------- lifecycle

    def open_bar(self) -> None:
        """Show the bar and remember where the canvas was, so Esc can undo
        the whole excursion in one key."""
        self._home = self._view.mapToScene(
            self._view.viewport().rect().center())
        self._home_zoom = self._view.zoom
        self.reposition()
        self.show()
        self.raise_()
        self._edit.setFocus()
        self._edit.selectAll()
        self._refresh(self._edit.text())

    def accept(self) -> None:
        """Keep the current node and close — the canvas stays where the
        search took it."""
        node_id = self.current_node_id()
        if node_id is not None:
            self.reveal_requested.emit(node_id)
        self._close()

    def cancel(self) -> None:
        """Close and put the view back where the search started."""
        if self._home is not None:
            self._view.set_zoom(self._home_zoom)
            self._view.centerOn(self._home)
        self._close()

    def _close(self) -> None:
        self._home = None
        self.hide()
        self._view.setFocus()

    def reposition(self) -> None:
        """Top-left of the viewport: the minimap already owns the top-right,
        and a bar down the bottom would sit under the status readouts."""
        self.move(MARGIN, MARGIN)

    # ---------------------------------------------------------------- search

    def current_node_id(self) -> Optional[str]:
        item = self._list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def matches(self) -> list[str]:
        """Node ids currently listed, best first — for tests and for anything
        that wants the result without the widget."""
        return [self._list.item(row).data(Qt.UserRole)
                for row in range(self._list.count())]

    def _refresh(self, query: str = "") -> None:
        graph = self._view.scene().graph
        # blockSignals: clearing moves the current row through every value on
        # the way down, and each of those would otherwise fly the canvas to a
        # node nobody asked for
        self._list.blockSignals(True)
        self._list.clear()
        for node in search_nodes(graph, query):
            item = QListWidgetItem(node.label)
            item.setData(Qt.UserRole, node.id)
            # the type, because two nodes called "Sales" are told apart by
            # what they are, and a renamed node is otherwise unidentifiable
            item.setToolTip(f"{node.label} — {node.spec.label}")
            self._list.addItem(item)
        self._list.blockSignals(False)
        self._resize_list()
        if self._list.count():
            self._list.setCurrentRow(0)
        self._update_count()

    def _resize_list(self) -> None:
        """Grow the box to the hits, up to MAX_ROWS, and drop it entirely
        when there are none — a search with no answer should not leave an
        empty pane over the canvas."""
        count = self._list.count()
        self._list.setVisible(bool(count))
        if count:
            row_height = self._list.sizeHintForRow(0)
            frame = 2 * self._list.frameWidth() + 2
            self._list.setFixedHeight(
                min(count, MAX_ROWS) * row_height + frame)
        self.adjustSize()

    def _update_count(self) -> None:
        total = self._list.count()
        if not self._edit.text().strip():
            self._count.setText("")
        elif not total:
            self._count.setText("none")
        else:
            self._count.setText(f"{self._list.currentRow() + 1} of {total}")
        found = total or not self._edit.text().strip()
        self._edit.setStyleSheet(
            "" if found else f"color: {theme.WIRE_INVALID.name()};")

    def _on_current_changed(self, current, _previous) -> None:
        self._update_count()
        if current is not None:
            self.reveal_requested.emit(current.data(Qt.UserRole))

    # -------------------------------------------------------------- keyboard

    def _step(self, delta: int) -> None:
        if not self._list.count():
            return
        row = self._list.currentRow() + delta
        # wrap, so walking a short list doesn't dead-end at either edge
        self._list.setCurrentRow(row % self._list.count())

    def eventFilter(self, obj, event) -> bool:
        if obj is self._edit and isinstance(event, QKeyEvent) \
                and event.type() == QKeyEvent.Type.KeyPress:
            if event.key() == Qt.Key_Down:
                self._step(1)
                return True
            if event.key() == Qt.Key_Up:
                self._step(-1)
                return True
            if event.key() == Qt.Key_Escape:
                self.cancel()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Escape:
            self.cancel()
            return
        super().keyPressEvent(event)
