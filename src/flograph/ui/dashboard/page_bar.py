"""PageTabBar: the strip under the canvas — "Model" first, one tab per
dashboard page, and a trailing "+" that creates a page.

The bar is a *view* of graph.pages: MainWindow drives it through the sync
API (add_page_tab / remove_page_tab / set_page_title / select_page) from
graph events, and user gestures come back out as request signals — the bar
never touches the graph itself."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QInputDialog, QTabBar

from flograph.core import Page


class PageTabBar(QTabBar):
    add_page_requested = Signal()
    rename_page_requested = Signal(str, str)   # page_id, new title
    delete_page_requested = Signal(str)        # page_id
    current_page_changed = Signal(object)      # page_id, or None for Model

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setExpanding(False)
        self.setDocumentMode(True)
        self.setTabsClosable(True)
        self.setDrawBase(False)
        self._syncing = True
        self.addTab("Model")   # tabData None = the modeling canvas
        self.addTab("+")
        self.setTabToolTip(1, "Add a dashboard page")
        self._strip_close_button(0)
        self._strip_close_button(1)
        self._syncing = False
        self.currentChanged.connect(self._on_current_changed)
        self.tabCloseRequested.connect(self._on_close_requested)

    def _strip_close_button(self, index: int) -> None:
        for side in (QTabBar.LeftSide, QTabBar.RightSide):
            self.setTabButton(index, side, None)

    def _plus_index(self) -> int:
        return self.count() - 1

    def _index_of_page(self, page_id: str) -> int:
        for i in range(1, self._plus_index()):
            if self.tabData(i) == page_id:
                return i
        return -1

    def current_page_id(self) -> Optional[str]:
        return self.tabData(self.currentIndex())

    # ------------------------------------------------------------ sync API

    def add_page_tab(self, page: Page) -> None:
        self._syncing = True
        index = self.insertTab(self._plus_index(), page.title)
        self.setTabData(index, page.id)
        self._syncing = False

    def remove_page_tab(self, page_id: str) -> None:
        index = self._index_of_page(page_id)
        if index < 0:
            return
        was_current = index == self.currentIndex()
        self._syncing = True
        self.removeTab(index)
        if was_current or self.currentIndex() >= self._plus_index():
            self.setCurrentIndex(0)
        self._syncing = False
        self.current_page_changed.emit(self.current_page_id())

    def set_page_title(self, page_id: str, title: str) -> None:
        index = self._index_of_page(page_id)
        if index >= 0:
            self.setTabText(index, title)

    def select_page(self, page_id: Optional[str]) -> None:
        index = 0 if page_id is None else self._index_of_page(page_id)
        if index >= 0:
            self.setCurrentIndex(index)

    # ------------------------------------------------------------ gestures

    def _on_current_changed(self, index: int) -> None:
        if self._syncing or index < 0:
            return
        self.current_page_changed.emit(self.tabData(index))

    def _on_close_requested(self, index: int) -> None:
        page_id = self.tabData(index)
        if page_id is not None:
            self.delete_page_requested.emit(page_id)

    def mousePressEvent(self, event) -> None:
        # handle "+" on press and swallow it so the tab never becomes
        # current — relying on tabBarClicked + reselect flickers
        if self.tabAt(event.position().toPoint()) == self._plus_index():
            self.add_page_requested.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        index = self.tabAt(event.position().toPoint())
        page_id = self.tabData(index) if index >= 0 else None
        if page_id is None:
            super().mouseDoubleClickEvent(event)
            return
        title, ok = QInputDialog.getText(self, "Rename page", "Title:",
                                         text=self.tabText(index))
        if ok and title.strip():
            self.rename_page_requested.emit(page_id, title.strip())
        event.accept()
