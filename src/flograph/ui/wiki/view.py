"""`WikiView` — a folder of Markdown pages as a navigable wiki.

A nav tree on the left (from `_Sidebar.md`, the GitHub-wiki convention), a
breadcrumb and back / forward / nav-toggle over the page on the right. The
Help ▸ Documentation window and the Markdown Wiki canvas card both embed
one; the rendering, history and `[[wikilink]]` handling live in
`DocsBrowser`.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QSplitter, QToolButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from flograph.core.docpages import breadcrumb, resolve_wiki_dir, sidebar

from .browser import DocsBrowser

_SLUG_ROLE = Qt.UserRole


class WikiView(QWidget):
    """Signals so an owner (the card) can persist where the reader is."""

    #: the page changed (slug) — a new destination, not a back/forward step
    page_changed = Signal(str)
    #: the nav panel was shown/hidden
    nav_visibility_changed = Signal(bool)

    def __init__(self, parent=None, *, folder: str | None = None,
                 show_nav: bool = True) -> None:
        super().__init__(parent)
        self._dir: Path = resolve_wiki_dir(folder)
        self._last_emitted: str | None = None
        self._slug_items: dict[str, QTreeWidgetItem] = {}

        self.browser = DocsBrowser(self, directory=self._dir)

        self._nav_toggle = QToolButton(text="☰", toolTip="Show / hide the nav panel")
        self._nav_toggle.setCheckable(True)
        self._nav_toggle.toggled.connect(self.set_nav_visible)
        self._back = QToolButton(text="◀", toolTip="Back")
        self._forward = QToolButton(text="▶", toolTip="Forward")
        self._back.clicked.connect(self.browser.go_back)
        self._forward.clicked.connect(self.browser.go_forward)

        self._crumb = QLabel()
        self._crumb.setTextFormat(Qt.RichText)
        self._crumb.linkActivated.connect(
            lambda slug: self.browser.show_page(slug))

        bar = QHBoxLayout()
        bar.setContentsMargins(2, 2, 2, 2)
        for btn in (self._nav_toggle, self._back, self._forward):
            bar.addWidget(btn)
        bar.addSpacing(6)
        bar.addWidget(self._crumb, 1)

        self.nav = QTreeWidget()
        self.nav.setHeaderHidden(True)
        self.nav.setIndentation(12)
        self.nav.currentItemChanged.connect(self._nav_selected)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addLayout(bar)
        right_layout.addWidget(self.browser, 1)

        self._split = QSplitter(Qt.Horizontal)
        self._split.addWidget(self.nav)
        self._split.addWidget(right)
        self._split.setStretchFactor(0, 0)
        self._split.setStretchFactor(1, 1)
        self._split.setSizes([220, 620])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._split)

        self._build_nav()
        self.browser.navigated.connect(self._sync)
        self.set_nav_visible(show_nav)
        self._sync()

    # ------------------------------------------------------------- public

    def set_folder(self, folder: str | None) -> None:
        new_dir = resolve_wiki_dir(folder)
        if new_dir == self._dir:
            return
        self._dir = new_dir
        self._last_emitted = None
        self.browser.set_folder(new_dir)
        self._build_nav()
        self._sync()

    def show_page(self, slug: str) -> None:
        if slug and slug != self.browser.current_slug():
            self.browser.show_page(slug)

    def current_slug(self) -> str | None:
        return self.browser.current_slug()

    def set_nav_visible(self, visible: bool) -> None:
        visible = bool(visible)
        self.nav.setVisible(visible)
        if self._nav_toggle.isChecked() != visible:
            self._nav_toggle.blockSignals(True)
            self._nav_toggle.setChecked(visible)
            self._nav_toggle.blockSignals(False)
        self.nav_visibility_changed.emit(visible)

    def nav_visible(self) -> bool:
        return self._nav_toggle.isChecked()

    # -------------------------------------------------------------- nav

    def _build_nav(self) -> None:
        self.nav.clear()
        self._slug_items.clear()

        def add(parent, entries) -> None:
            for entry in entries:
                item = QTreeWidgetItem(parent, [entry.title])
                if entry.slug:
                    item.setData(0, _SLUG_ROLE, entry.slug)
                    self._slug_items[entry.slug] = item
                else:  # a section header — shown, not selectable
                    item.setFlags(Qt.ItemIsEnabled)
                    font = item.font(0)
                    font.setBold(True)
                    item.setFont(0, font)
                add(item, entry.children)

        add(self.nav.invisibleRootItem(), sidebar(self._dir))
        self.nav.expandAll()

    def _nav_selected(self, item, _previous) -> None:
        if item is None:
            return
        slug = item.data(0, _SLUG_ROLE)
        if slug and slug != self.browser.current_slug():
            self.browser.show_page(slug)

    # ------------------------------------------------------------- sync

    def _sync(self) -> None:
        self._back.setEnabled(self.browser.can_go_back())
        self._forward.setEnabled(self.browser.can_go_forward())
        slug = self.browser.current_slug()

        item = self._slug_items.get(slug)
        if item is not None and item is not self.nav.currentItem():
            self.nav.blockSignals(True)
            self.nav.setCurrentItem(item)
            self.nav.blockSignals(False)

        self._crumb.setText(self._crumb_html(slug))

        if slug and slug != self._last_emitted:
            self._last_emitted = slug
            self.page_changed.emit(slug)

    def _crumb_html(self, slug: str | None) -> str:
        if not slug:
            return ""
        trail = breadcrumb(slug, sidebar(self._dir))
        if not trail:
            page = self.browser._catalog.get(slug)
            return f"<b>{page.title if page else slug}</b>"
        parts = []
        for i, entry in enumerate(trail):
            last = i == len(trail) - 1
            if entry.slug and not last:
                parts.append(f'<a href="{entry.slug}">{entry.title}</a>')
            elif last:
                parts.append(f"<b>{entry.title}</b>")
            else:
                parts.append(entry.title)
        return ' <span style="color:#777">›</span> '.join(parts)
