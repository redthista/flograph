"""Node discovery UI: the Tab search popup and the persistent library tree."""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFrame, QLineEdit, QListWidget, QListWidgetItem, QMenu, QToolButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from flograph.core import NodeRegistry, NodeSpec
from flograph.ui.favorites import Favorites
from flograph.ui.icons import spec_icon

STAR = "★"
FAVORITE_SECTION = "Favorites"

NODE_TYPE_MIME = "application/x-flograph-node-type"


class NodePalettePopup(QFrame):
    """Blueprint-style Tab popup: fuzzy search, Enter to place."""

    chosen = Signal(str)  # type_id

    def __init__(self, registry: NodeRegistry, favorites: Favorites,
                 parent=None) -> None:
        super().__init__(parent, Qt.Popup)
        self._registry = registry
        self._favorites = favorites
        self._predicate: Optional[Callable[[NodeSpec], bool]] = None
        self._favorites.changed.connect(self._refresh_if_open)
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

    def _refresh_if_open(self) -> None:
        if self.isVisible():
            self._refresh(self._search.text())

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
        favorites = self._favorites
        specs = self._registry.search(query)
        favs = [s for s in specs if favorites.contains(s.type_id)]
        rest = [s for s in specs if not favorites.contains(s.type_id)]
        for spec in favs + rest:
            if self._predicate is not None and not self._predicate(spec):
                continue
            prefix = STAR if favorites.contains(spec.type_id) else ""
            item = QListWidgetItem(
                spec_icon(spec),
                f"{prefix} {spec.label}    ({spec.category})")
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
    right-click user entries to manage them. A pinned Favorites section sits
    on top; Ctrl+Shift+F stars the selected row."""

    USER_SECTION = "User Nodes"
    FAVORITE_SECTION = FAVORITE_SECTION

    add_requested = Signal(str)            # type_id
    new_group_requested = Signal()
    rename_user_node_requested = Signal(str)   # type_id
    delete_user_node_requested = Signal(str)   # type_id
    move_user_node_requested = Signal(str)     # type_id

    def __init__(self, registry: NodeRegistry, favorites: Favorites,
                 parent=None) -> None:
        super().__init__(parent)
        self._registry = registry
        self._favorites = favorites
        self._favorites_only = False
        self._last_query = ""
        self.setHeaderHidden(True)
        # Compact rows: small glyphs, uniform height, no room to grow.
        self.setIconSize(QSize(14, 14))
        self.setUniformRowHeights(True)
        self.setDragEnabled(True)
        self.itemActivated.connect(self._on_activated)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self._favorites.changed.connect(self.reload)
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

        favorites = self._favorites
        fav_specs = [self._registry.get(tid) for tid in favorites.ids()
                     if self._registry.maybe_get(tid) is not None]
        if fav_specs:
            fav_specs.sort(key=lambda s: (s.category, s.label))
            fav_top = self._section(self.FAVORITE_SECTION, marker=STAR)
            fav_top.setData(0, Qt.UserRole + 1, self.FAVORITE_SECTION)
            for spec in fav_specs:
                fav_top.addChild(self._node_item(spec, favorite=False))
            fav_top.setExpanded(True)

        for category in sorted(builtin):
            top = self._section(category)
            for spec in builtin[category]:
                top.addChild(self._node_item(spec, favorite=True))
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
                parent.addChild(self._node_item(spec, favorite=True))
        user_top.setExpanded(True)

        # re-apply whatever search / favorites-only filter was active
        self.filter(self._last_query)

    def _section(self, title: str, marker: str = "") -> QTreeWidgetItem:
        top = QTreeWidgetItem([f"{marker} {title}" if marker else title])
        top.setFlags(top.flags() & ~Qt.ItemIsDragEnabled)
        self.addTopLevelItem(top)
        return top

    def _node_item(self, spec: NodeSpec, favorite: bool) -> QTreeWidgetItem:
        starred = favorite and self._favorites.contains(spec.type_id)
        label = f"{STAR} {spec.label}" if starred else spec.label
        child = QTreeWidgetItem([label])
        child.setIcon(0, spec_icon(spec))
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
        if type_id:
            fav_label = ("Remove from Favorites" if
                         self._favorites.contains(type_id)
                         else "Add to Favorites")
            menu.addAction(fav_label,
                           lambda tid=type_id: self._favorites.toggle(tid))
            menu.addSeparator()
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

    def keyPressEvent(self, event) -> None:
        if (event.modifiers() == (Qt.ControlModifier | Qt.ShiftModifier)
                and event.key() == Qt.Key_F):
            item = self.currentItem()
            type_id = item.data(0, Qt.UserRole) if item else None
            if type_id:
                self._favorites.toggle(type_id)
                return
        super().keyPressEvent(event)

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

    def set_favorites_only(self, on: bool) -> None:
        self._favorites_only = on
        self.filter(self._last_query)

    def filter(self, query: str) -> None:
        """Hide items that don't match query, in place (structure untouched).
        With favorites-only on, every section except Favorites is dropped."""
        self._last_query = query.strip()
        matched = (None if not self._last_query
                   else {spec.type_id
                         for spec in self._registry.search(self._last_query)})
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            if self._favorites_only:
                is_fav_section = (top.data(0, Qt.UserRole + 1)
                                  == self.FAVORITE_SECTION)
                if not is_fav_section and not top.data(0, Qt.UserRole):
                    top.setHidden(True)
                    continue
            self._filter_item(top, matched)

    def _filter_item(self, item: QTreeWidgetItem,
                     matched: Optional[set[str]]) -> bool:
        type_id = item.data(0, Qt.UserRole)
        if type_id:
            visible = matched is None or type_id in matched
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


class LibraryPanel(QWidget):
    """Node Library dock content: a search box above the persistent tree,
    with a favorites-only toggle beside it."""

    def __init__(self, registry: NodeRegistry, favorites: Favorites,
                 parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        bar = QWidget(self)
        bar_layout = QVBoxLayout(bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(2)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search nodes…")
        self.favs_only = QToolButton()
        self.favs_only.setText(STAR)
        self.favs_only.setCheckable(True)
        self.favs_only.setToolTip("Show favorites only")
        self.favs_only.setMaximumWidth(22)
        bar_layout.addWidget(self.search)
        bar_layout.addWidget(self.favs_only, 0, Qt.AlignRight)
        self.tree = LibraryTree(registry, favorites)
        layout.addWidget(bar)
        layout.addWidget(self.tree, 1)
        self.search.textChanged.connect(self.tree.filter)
        self.favs_only.toggled.connect(self.tree.set_favorites_only)
