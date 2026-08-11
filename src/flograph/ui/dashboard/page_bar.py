"""PageTabBar: the strip under the canvas — "Model" first, one tab per
dashboard page, and a trailing "+" that creates a page.

The bar is a *view* of graph.pages: MainWindow drives it through the sync
API (add_page_tab / remove_page_tab / set_page_title / set_page_order /
select_page) from graph events, and user gestures come back out as request
signals — the bar never touches the graph itself.

Page tabs can be dragged to reorder; "Model" and "+" are pinned to the ends
(see _enforce_pinned), and one drag produces one reorder request."""
from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtCore import QEvent, QObject, Qt, Signal, QTimer
from PySide6.QtGui import QAction, QColor, QContextMenuEvent
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QInputDialog, QMenu, QStyle, QStyleOptionTab,
    QStylePainter, QTabBar,
)

from flograph.core import Page

from .. import theme

_DELAY = 500
_menu_timer: Optional[QTimer] = None

# Tab tinting: the colour is never painted flat, it is laid over the themed
# tab so anything the colour picker returns comes out muted rather than
# garish. Strengths live in theme so tabs and node cards mute by the same
# amount, and are read at paint time so Settings > Canvas reaches them
# without a restart; the selected tab takes the stronger one so selection
# still reads at a glance. Composited by the painter rather than by
# theme.tint() because the base here is drawn by the style, not by us.

# tabData sentinel for the trailing "+" tab. Model's tabData stays None, so the
# three kinds of tab are told apart by data alone — which survives reordering,
# unlike an index.
_PLUS = "\x00plus"


class _MenuGuard(QObject):
    def eventFilter(self, obj, event):
        if isinstance(event, QContextMenuEvent):
            return True
        return super().eventFilter(obj, event)

_guard = _MenuGuard()


class PageTabBar(QTabBar):
    add_page_requested = Signal(str)   # "dashboard" | "report"
    rename_page_requested = Signal(str, str)   # page_id, new title
    delete_page_requested = Signal(str)        # page_id
    duplicate_page_requested = Signal(str)     # page_id to duplicate
    reorder_pages_requested = Signal(list)     # page_ids in their new order
    recolor_page_requested = Signal(str, object)  # page_id, "#rrggbb" or None
    set_view_mode_requested = Signal(str, bool)   # page_id, locked
    export_page_requested = Signal(str)           # page_id (locked reports)
    page_setup_requested = Signal(str)            # page_id (locked reports)
    current_page_changed = Signal(object)      # page_id, or None for Model
    model_tab_double_clicked = Signal()        # collapse/restore every panel

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setExpanding(False)
        self.setDocumentMode(True)
        self.setDrawBase(False)
        self.setMovable(True)  # page tabs only; see _enforce_pinned
        self._syncing = True
        self.addTab("Model")   # tabData None = the modeling canvas
        plus = self.addTab("+")
        self.setTabData(plus, _PLUS)
        self.setTabToolTip(plus, "Add a dashboard or report page")
        self._syncing = False
        self._drag_locked = False   # press landed on a tab that can't move
        self._reorder_pending = False
        self._colors: dict[str, str] = {}   # page_id -> "#rrggbb"
        # page_id -> locked. Mirrored here only so the context menu can show
        # which mode a page is in; the model stays the source of truth.
        # (Called view_mode in the model — "Locked" is what it says on the
        # menu, since that is what it does to the page.)
        self._view_modes: dict[str, bool] = {}
        # page_id -> "dashboard" | "report"; only the menu needs it, to offer
        # Export PDF on a locked report
        self._kinds: dict[str, str] = {}
        self.currentChanged.connect(self._on_current_changed)
        self.tabMoved.connect(self._on_tab_moved)

    def _plus_index(self) -> int:
        for i in range(self.count() - 1, -1, -1):
            if self.tabData(i) == _PLUS:
                return i
        return self.count() - 1

    def _model_index(self) -> int:
        for i in range(self.count()):
            if self.tabData(i) is None:
                return i
        return 0

    def _index_of_page(self, page_id: str) -> int:
        for i in range(self.count()):
            if self.tabData(i) == page_id:
                return i
        return -1

    def page_order(self) -> list[str]:
        """Page ids in tab order — Model and "+" excluded."""
        return [data for i in range(self.count())
                if (data := self.tabData(i)) not in (None, _PLUS)]

    def _is_page(self, index: int) -> bool:
        return 0 <= index < self.count() and self.tabData(index) not in (None, _PLUS)

    def _is_model(self, index: int) -> bool:
        """The modeling canvas's own tab. tabData is None for it -- but also
        for a miss (tabAt returns -1), so the range check is what tells a
        click on the Model tab from a click on the empty strip beside it."""
        return 0 <= index < self.count() and self.tabData(index) is None

    def current_page_id(self) -> Optional[str]:
        data = self.tabData(self.currentIndex())
        return None if data == _PLUS else data

    # ------------------------------------------------------------ sync API

    def add_page_tab(self, page: Page) -> None:
        self._syncing = True
        index = self.insertTab(self._plus_index(), page.title)
        self.setTabData(index, page.id)
        self._syncing = False
        self.set_page_color(page.id, page.color)
        self.set_page_view_mode(page.id, page.view_mode)
        self._kinds[page.id] = page.kind

    def set_page_view_mode(self, page_id: str, view_mode: bool) -> None:
        """Told by the window whenever the model changes, so the context
        menu's tick matches the page it was opened on."""
        self._view_modes[page_id] = bool(view_mode)

    def page_view_mode(self, page_id: str) -> bool:
        return self._view_modes.get(page_id, False)

    def set_page_color(self, page_id: str, color: Optional[str]) -> None:
        if color:
            self._colors[page_id] = color
        else:
            self._colors.pop(page_id, None)
        self.update()

    def page_color(self, page_id: str) -> Optional[str]:
        return self._colors.get(page_id)

    def remove_page_tab(self, page_id: str) -> None:
        index = self._index_of_page(page_id)
        if index < 0:
            return
        was_current = index == self.currentIndex()
        self._colors.pop(page_id, None)
        self._view_modes.pop(page_id, None)
        self._kinds.pop(page_id, None)
        self._syncing = True
        self.removeTab(index)
        if was_current or self.currentIndex() >= self._plus_index():
            self.setCurrentIndex(self._model_index())
        self._syncing = False
        self.current_page_changed.emit(self.current_page_id())

    def set_page_title(self, page_id: str, title: str) -> None:
        index = self._index_of_page(page_id)
        if index >= 0:
            self.setTabText(index, title)

    def set_page_order(self, order: Sequence[str]) -> None:
        """Permute the page tabs to match `order` (moveTab keeps the current
        tab current, so the visible page never changes under the user)."""
        self._syncing = True
        try:
            for target, page_id in enumerate(order, start=self._model_index() + 1):
                index = self._index_of_page(page_id)
                if index >= 0 and index != target:
                    self.moveTab(index, target)
        finally:
            self._syncing = False

    def select_page(self, page_id: Optional[str]) -> None:
        index = self._model_index() if page_id is None else self._index_of_page(page_id)
        if index >= 0:
            self.setCurrentIndex(index)

    # ------------------------------------------------------------- painting

    def paintEvent(self, event) -> None:
        """Draw the themed tab, lay the page's colour over it at low alpha,
        then the label on top — the shape and the label are separate style
        elements, so the tint can sit between them without hiding the text."""
        painter = QStylePainter(self)
        for i in range(self.count()):
            option = QStyleOptionTab()
            self.initStyleOption(option, i)
            painter.drawControl(QStyle.CE_TabBarTabShape, option)
            color = self._colors.get(self.tabData(i))
            if color:
                tint = QColor(color)
                tint.setAlphaF(theme.TINT_STRONG if i == self.currentIndex()
                               else theme.TINT_SOFT)
                painter.fillRect(self.tabRect(i), tint)
            painter.drawControl(QStyle.CE_TabBarTabLabel, option)

    # ------------------------------------------------------------ gestures

    def _on_current_changed(self, index: int) -> None:
        if self._syncing or index < 0:
            return
        self.current_page_changed.emit(self.current_page_id())

    def _on_tab_moved(self, from_index: int, to_index: int) -> None:
        if self._syncing:
            return
        self._enforce_pinned()
        self._reorder_pending = True

    def _enforce_pinned(self) -> None:
        """Model stays first, "+" stays last — Qt's drag will happily swap
        them, so shove them back as it happens."""
        self._syncing = True
        try:
            model = self._model_index()
            if model != 0:
                self.moveTab(model, 0)
            plus, last = self._plus_index(), self.count() - 1
            if plus != last:
                self.moveTab(plus, last)
        finally:
            self._syncing = False

    def mousePressEvent(self, event) -> None:
        index = self.tabAt(event.position().toPoint())
        # handle "+" on press and swallow it so the tab never becomes
        # current — relying on tabBarClicked + reselect flickers
        if index == self._plus_index():
            self._show_add_menu(event.globalPosition().toPoint())
            event.accept()
            return
        # right-click: context menu for rename/duplicate/delete
        if event.button() == Qt.RightButton and self._is_page(index):
            page_id = self.tabData(index)
            if page_id is not None:
                self._show_context_menu(index, page_id, event.globalPosition().toPoint())
                event.accept()
                return
        # only page tabs are draggable; Model is pinned in place
        self._drag_locked = not self._is_page(index)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_locked:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self._drag_locked = False
        if self._reorder_pending:
            # one request per drag, not one per swap Qt makes along the way
            self._reorder_pending = False
            self.reorder_pages_requested.emit(self.page_order())

    def _show_add_menu(self, global_pos) -> None:
        """"+" asks what kind of page. A menu rather than two buttons: the
        strip is a tab bar, and dashboards stay the one-click-away default
        by being first."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        choices = {menu.addAction("Dashboard page"): "dashboard",
                   menu.addAction("Report page"): "report"}
        chosen = menu.exec(global_pos)
        if chosen in choices:
            self.add_page_requested.emit(choices[chosen])

    def _show_context_menu(self, index: int, page_id: str, global_pos) -> None:
        global _menu_timer
        app = QApplication.instance()
        app.installEventFilter(_guard)
        try:
            menu = QMenu(self)
            menu.setToolTipsVisible(True)   # off by default in QMenu
            # One tick, not a pair of mutually exclusive ones: the page is
            # either locked or it isn't, and a checkbox says that in half
            # the space two radio-ish entries took.
            locked = self._view_modes.get(page_id, False)
            lock_action = QAction("Locked", self)
            lock_action.setCheckable(True)
            lock_action.setChecked(locked)
            lock_action.setToolTip(
                "Lock the elements on this page in place. They can still be "
                "used — slicers, tables, buttons and charts all keep "
                "working — they just can't be moved, resized or rearranged.")
            # triggered, not toggled: toggled also fires for setChecked above
            lock_action.triggered.connect(
                lambda checked: self.set_view_mode_requested.emit(
                    page_id, bool(checked)))
            menu.addAction(lock_action)
            # A locked report has no toolbar left to export from, so the one
            # surface that is always reachable carries it instead — and the
            # same goes for the setup behind the export, since changing the
            # paper is exactly what someone does on the way to printing.
            if locked and self._kinds.get(page_id) == "report":
                setup_action = QAction("Page Setup…", self)
                setup_action.triggered.connect(
                    lambda: self.page_setup_requested.emit(page_id))
                menu.addAction(setup_action)
                export_action = QAction("Export PDF…", self)
                export_action.triggered.connect(
                    lambda: self.export_page_requested.emit(page_id))
                menu.addAction(export_action)
            menu.addSeparator()
            rename_action = QAction("Rename", self)
            dup_action = QAction("Duplicate", self)
            color_action = QAction("Change colour…", self)
            reset_color_action = (QAction("Reset colour", self)
                                  if page_id in self._colors else None)
            del_action = QAction("Delete", self)
            rename_action.triggered.connect(
                lambda: self._prompt_rename(index, page_id))
            dup_action.triggered.connect(lambda: self.duplicate_page_requested.emit(page_id))
            color_action.triggered.connect(lambda: self._prompt_color(page_id))
            del_action.triggered.connect(lambda: self.delete_page_requested.emit(page_id))
            menu.addAction(rename_action)
            menu.addAction(dup_action)
            menu.addAction(color_action)
            if reset_color_action is not None:
                reset_color_action.triggered.connect(
                    lambda: self.recolor_page_requested.emit(page_id, None))
                menu.addAction(reset_color_action)
            menu.addAction(del_action)
            menu.exec(global_pos)
        finally:
            if _menu_timer is not None:
                _menu_timer.stop()
            _menu_timer = QTimer(self)
            _menu_timer.setSingleShot(True)
            _menu_timer.timeout.connect(lambda: app.removeEventFilter(_guard))
            _menu_timer.start(_DELAY)

    def _prompt_color(self, page_id: str) -> None:
        current = QColor(self._colors.get(page_id) or theme.NODE_HEADER)
        color = QColorDialog.getColor(current, self, "Page colour")
        if color.isValid():
            self.recolor_page_requested.emit(page_id, color.name())

    def _prompt_rename(self, index: int, page_id: str) -> None:
        title, ok = QInputDialog.getText(
            self, "Rename page", "Title:",
            text=self.tabText(index))
        if ok and title.strip():
            self.rename_page_requested.emit(page_id, title.strip())

    def mouseDoubleClickEvent(self, event) -> None:
        index = self.tabAt(event.position().toPoint())
        # the Model tab has no title to rename, so its double-click is free
        # for the thing the canvas underneath it wants: all panels out of
        # the way, and back again
        if self._is_model(index):
            self.model_tab_double_clicked.emit()
            event.accept()
            return
        if not self._is_page(index):
            super().mouseDoubleClickEvent(event)
            return
        page_id = self.tabData(index)
        title, ok = QInputDialog.getText(self, "Rename page", "Title:",
                                         text=self.tabText(index))
        if ok and title.strip():
            self.rename_page_requested.emit(page_id, title.strip())
        event.accept()
