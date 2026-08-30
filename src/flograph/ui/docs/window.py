"""The documentation window — Help ▸ Documentation, or F1.

Modeless, like the Statistics window and the feature help dialogs it sits
beside: it is read *while* working on a flow, so it must not block the canvas
behind it. A navigation tree on the left (driven by `_Sidebar.md`, the same
file a GitHub wiki uses) and a `DocsBrowser` on the right, with a thin
back / forward / home toolbar over the page.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QSplitter, QToolButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from flograph.core.docpages import sidebar

from .browser import DocsBrowser

_SLUG_ROLE = Qt.UserRole


class DocsWindow(QDialog):
    """Modeless, reused across openings — one window, raised again rather than
    restacked, like the Statistics window it sits beside."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("flograph — Documentation")
        self.setModal(False)
        self.resize(960, 720)

        self.browser = DocsBrowser(self)

        self.nav = QTreeWidget()
        self.nav.setHeaderHidden(True)
        self.nav.setIndentation(12)
        self._slug_items: dict[str, QTreeWidgetItem] = {}
        self._build_nav()
        self.nav.currentItemChanged.connect(self._nav_selected)

        self._back = QToolButton(text="◀", toolTip="Back")
        self._forward = QToolButton(text="▶", toolTip="Forward")
        self._home = QToolButton(text="⌂", toolTip="Home")
        self._back.clicked.connect(self.browser.go_back)
        self._forward.clicked.connect(self.browser.go_forward)
        self._home.clicked.connect(self.browser.go_home)

        bar = QHBoxLayout()
        for btn in (self._back, self._forward, self._home):
            bar.addWidget(btn)
        bar.addStretch(1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addLayout(bar)
        right_layout.addWidget(self.browser, 1)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.nav)
        split.addWidget(right)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([240, 720])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(split)

        self.browser.navigated.connect(self._sync)
        self._sync()

    def show_page(self, slug: str) -> None:
        """Open the window on a particular page — for a future 'help on this'
        entry point."""
        self.browser.show_page(slug)

    # ---------------------------------------------------------------- nav

    def _build_nav(self) -> None:
        def add(parent, entries) -> None:
            for entry in entries:
                item = QTreeWidgetItem(parent, [entry.title])
                if entry.slug:
                    item.setData(0, _SLUG_ROLE, entry.slug)
                    self._slug_items[entry.slug] = item
                else:  # a section header: shown, not a target
                    item.setFlags(Qt.ItemIsEnabled)
                    font = item.font(0)
                    font.setBold(True)
                    item.setFont(0, font)
                add(item, entry.children)

        add(self.nav.invisibleRootItem(), sidebar())
        self.nav.expandAll()

    def _nav_selected(self, item, _previous) -> None:
        if item is None:
            return
        slug = item.data(0, _SLUG_ROLE)
        if slug and slug != self.browser.current_slug():
            self.browser.show_page(slug)

    def _sync(self) -> None:
        self._back.setEnabled(self.browser.can_go_back())
        self._forward.setEnabled(self.browser.can_go_forward())
        item = self._slug_items.get(self.browser.current_slug())
        if item is not None and item is not self.nav.currentItem():
            self.nav.blockSignals(True)
            self.nav.setCurrentItem(item)
            self.nav.blockSignals(False)
