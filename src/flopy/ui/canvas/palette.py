"""Node discovery UI: the Tab search popup and the persistent library tree."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFrame, QLineEdit, QListWidget, QListWidgetItem, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout,
)

from flopy.core import NodeRegistry, NodeSpec

NODE_TYPE_MIME = "application/x-flopy-node-type"


class NodePalettePopup(QFrame):
    """Blueprint-style Tab popup: fuzzy search, Enter to place."""

    chosen = Signal(str)  # type_id

    def __init__(self, registry: NodeRegistry, parent=None) -> None:
        super().__init__(parent, Qt.Popup)
        self._registry = registry
        self._predicate: Optional[Callable[[NodeSpec], bool]] = None
        self.setFixedSize(280, 320)
        self.setFrameShape(QFrame.StyledPanel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search nodes…")
        self._list = QListWidget()
        layout.addWidget(self._search)
        layout.addWidget(self._list, 1)

        self._search.textChanged.connect(self._refresh)
        self._search.returnPressed.connect(self._accept_current)
        self._search.installEventFilter(self)
        self._list.itemActivated.connect(lambda item: self._accept(item))

    def popup_at(self, global_pos: QPoint,
                 predicate: Optional[Callable[[NodeSpec], bool]] = None) -> None:
        self._predicate = predicate
        self._search.clear()
        self._refresh("")
        self.move(global_pos)
        self.show()
        self._search.setFocus()

    def _refresh(self, query: str) -> None:
        self._list.clear()
        for spec in self._registry.search(query):
            if self._predicate is not None and not self._predicate(spec):
                continue
            item = QListWidgetItem(f"{spec.label}    ({spec.category})")
            item.setData(Qt.UserRole, spec.type_id)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)

    def _accept_current(self) -> None:
        self._accept(self._list.currentItem())

    def _accept(self, item: Optional[QListWidgetItem]) -> None:
        if item is not None:
            self.hide()
            self.chosen.emit(item.data(Qt.UserRole))

    def eventFilter(self, obj, event) -> bool:
        if obj is self._search and isinstance(event, QKeyEvent) \
                and event.type() == QKeyEvent.Type.KeyPress:
            if event.key() in (Qt.Key_Down, Qt.Key_Up):
                row = self._list.currentRow()
                delta = 1 if event.key() == Qt.Key_Down else -1
                self._list.setCurrentRow(
                    max(0, min(self._list.count() - 1, row + delta)))
                return True
        return super().eventFilter(obj, event)


class LibraryTree(QTreeWidget):
    """Persistent dock: node types by category; drag onto the canvas or
    double-click to add."""

    add_requested = Signal(str)  # type_id

    def __init__(self, registry: NodeRegistry, parent=None) -> None:
        super().__init__(parent)
        self._registry = registry
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.itemActivated.connect(self._on_activated)
        self.reload()

    def reload(self) -> None:
        self.clear()
        for category, specs in self._registry.categories().items():
            top = QTreeWidgetItem([category])
            top.setFlags(top.flags() & ~Qt.ItemIsDragEnabled)
            self.addTopLevelItem(top)
            for spec in specs:
                child = QTreeWidgetItem([spec.label])
                child.setData(0, Qt.UserRole, spec.type_id)
                child.setToolTip(0, spec.doc or spec.type_id)
                top.addChild(child)
            top.setExpanded(True)

    def _on_activated(self, item: QTreeWidgetItem, column: int) -> None:
        type_id = item.data(0, Qt.UserRole)
        if type_id:
            self.add_requested.emit(type_id)

    def mimeData(self, items) -> QMimeData:
        mime = QMimeData()
        for item in items:
            type_id = item.data(0, Qt.UserRole)
            if type_id:
                mime.setData(NODE_TYPE_MIME, type_id.encode())
                break
        return mime

    def mimeTypes(self) -> list[str]:
        return [NODE_TYPE_MIME]
