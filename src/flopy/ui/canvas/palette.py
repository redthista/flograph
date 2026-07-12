"""Node discovery UI: the Tab search popup and the persistent library tree."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFrame, QLineEdit, QListWidget, QListWidgetItem, QMenu, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
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
    """Persistent dock: built-in node types by category, plus a User Nodes
    section (grouped by folder). Drag onto the canvas or double-click to add;
    right-click user entries to manage them."""

    USER_SECTION = "User Nodes"

    add_requested = Signal(str)            # type_id
    new_group_requested = Signal()
    rename_user_node_requested = Signal(str)   # type_id
    delete_user_node_requested = Signal(str)   # type_id
    move_user_node_requested = Signal(str)     # type_id

    def __init__(self, registry: NodeRegistry, parent=None) -> None:
        super().__init__(parent)
        self._registry = registry
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.itemActivated.connect(self._on_activated)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.reload()

    def reload(self) -> None:
        self.clear()
        builtin: dict[str, list[NodeSpec]] = {}
        user: dict[Optional[str], list[NodeSpec]] = {}
        for spec in self._registry.all():
            if spec.builtin:
                builtin.setdefault(spec.category, []).append(spec)
            else:
                user.setdefault(spec.group or None, []).append(spec)

        for category in sorted(builtin):
            top = self._section(category)
            for spec in builtin[category]:
                top.addChild(self._node_item(spec))
            top.setExpanded(True)

        user_top = self._section(self.USER_SECTION)
        user_top.setData(0, Qt.UserRole + 1, self.USER_SECTION)  # section marker
        for group in sorted(user, key=lambda g: (g is not None, g or "")):
            specs = user[group]
            parent = user_top
            if group is not None:
                parent = QTreeWidgetItem([group])
                parent.setFlags(parent.flags() & ~Qt.ItemIsDragEnabled)
                user_top.addChild(parent)
                parent.setExpanded(True)
            for spec in specs:
                parent.addChild(self._node_item(spec))
        user_top.setExpanded(True)

    def _section(self, title: str) -> QTreeWidgetItem:
        top = QTreeWidgetItem([title])
        top.setFlags(top.flags() & ~Qt.ItemIsDragEnabled)
        self.addTopLevelItem(top)
        return top

    def _node_item(self, spec: NodeSpec) -> QTreeWidgetItem:
        child = QTreeWidgetItem([spec.label])
        child.setData(0, Qt.UserRole, spec.type_id)
        child.setToolTip(0, spec.doc or spec.type_id)
        return child

    def _on_activated(self, item: QTreeWidgetItem, column: int) -> None:
        type_id = item.data(0, Qt.UserRole)
        if type_id:
            self.add_requested.emit(type_id)

    def _on_context_menu(self, pos: QPoint) -> None:
        item = self.itemAt(pos)
        menu = QMenu(self)
        type_id = item.data(0, Qt.UserRole) if item else None
        is_user_node = bool(type_id) and type_id.startswith("user.")
        if is_user_node:
            menu.addAction("Rename…",
                           lambda: self.rename_user_node_requested.emit(type_id))
            menu.addAction("Move to group…",
                           lambda: self.move_user_node_requested.emit(type_id))
            menu.addAction("Delete",
                           lambda: self.delete_user_node_requested.emit(type_id))
            menu.addSeparator()
        menu.addAction("New group…", self.new_group_requested.emit)
        menu.exec(self.viewport().mapToGlobal(pos))

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

    def filter(self, query: str) -> None:
        """Hide items that don't match query, in place (structure untouched)."""
        query = query.strip()
        if not query:
            self._set_all_visible()
            return
        matched = {spec.type_id for spec in self._registry.search(query)}
        for i in range(self.topLevelItemCount()):
            self._filter_item(self.topLevelItem(i), matched)

    def _filter_item(self, item: QTreeWidgetItem, matched: set[str]) -> bool:
        type_id = item.data(0, Qt.UserRole)
        if type_id:
            visible = type_id in matched
            item.setHidden(not visible)
            return visible
        any_visible = False
        for i in range(item.childCount()):
            if self._filter_item(item.child(i), matched):
                any_visible = True
        item.setHidden(not any_visible)
        if any_visible:
            item.setExpanded(True)
        return any_visible

    def _set_all_visible(self) -> None:
        def _show(item: QTreeWidgetItem) -> None:
            item.setHidden(False)
            for i in range(item.childCount()):
                _show(item.child(i))
        for i in range(self.topLevelItemCount()):
            _show(self.topLevelItem(i))


class LibraryPanel(QWidget):
    """Node Library dock content: a search box above the persistent tree."""

    def __init__(self, registry: NodeRegistry, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search nodes…")
        self.tree = LibraryTree(registry)
        layout.addWidget(self.search)
        layout.addWidget(self.tree, 1)
        self.search.textChanged.connect(self.tree.filter)
