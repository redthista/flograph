"""A second row of tabs, for the pages inside a group.

The tab bar puts a group's pages in a run behind a header, all on one
strip. That is fine for two groups of three; it is not fine for the bar a
real project grows, where the strip scrolls and finding a page means
reading sideways. So, behind a setting: **the group headers keep the top
row to themselves, and the pages of whichever group is open appear on a
row beneath it.**

Which is the shape of a menu bar, and reads like one — the top row is the
same handful of names however many pages a project has, and the row below
it changes as you pick between them. The Model tab is a header like any
other here (it always was: G12/G13 made it the head of the canvas tabs),
so clicking it puts the canvases on the second row.

Two widgets:

* `GroupRowBar` — the second row itself. A plain tab bar of page tabs,
  no headers, no "+". It is a *view*: a click asks the window to select
  that page, exactly as clicking the page's own tab would, and a
  right-click borrows the tab bar's own page menu rather than growing a
  second one to keep in step.
* `PageBarHost` — the two stacked, and the one thing that can see both:
  a page dragged from one row to the other goes through it. `MainWindow`
  keeps talking to the `PageTabBar` it always had; only the widget that
  goes in the layout changes, so nothing else about the window has to
  know this exists.

**A page moves between the rows by being dragged between them.** The two
rows are what a page's group *is* now — the top row is the pages in no
group, a second row is one group's pages — so dragging a tab from one to
the other is the plainest way to say where it belongs, and it is the one
the bar already reads for everything else. Qt keeps a dragged tab inside
its own bar, so what crosses is the pointer: the source asks the host on
every move whether the other row would take the drop, the target draws a
caret in the gap it would land in, and on release the host turns it into
the same `move_page_requested` a drag along one row makes — one request,
one undo step.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QSizePolicy, QStyle, QStyleOptionTab, QStylePainter, QTabBar,
    QVBoxLayout, QWidget,
)

from .. import theme

#: The model canvas's name on a row, and the canvases as a group — both
#: imported lazily everywhere else to keep this module off page_bar's
#: import, but needed here by value.
_MODEL_PAGE = "\x00model"
CANVASES = "\x00canvases"


class GroupRowBar(QTabBar):
    """The pages of the open group, on a row of their own."""

    page_clicked = Signal(str)                    # page_id
    context_menu_requested = Signal(str, object)  # page_id, global position
    reordered = Signal(list)                      # page_ids in their new order

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setExpanding(False)
        self.setDocumentMode(True)
        self.setDrawBase(False)
        # A page's tab is here and nowhere else now, so this is where it
        # is dragged into place. One request per drag, not one per swap Qt
        # makes on the way — the bar above has the same rule.
        self.setMovable(True)
        self._dragging = False
        self.tabMoved.connect(self._on_tab_moved)
        self.setUsesScrollButtons(True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._colors: dict[str, str] = {}
        self._accent: Optional[str] = None   # the open group's own colour
        # Set by PageBarHost, exactly as it sets the bar's: asked on every
        # move of a drag, and again on the drop, whether the row above is
        # taking this one. See the module docstring.
        self.handover = None
        self._handing_over = False
        self._pressed: Optional[str] = None
        self._press_at = None
        # The page Qt is carrying under the pointer: left out of this
        # paint, since Qt draws it itself — and moved along with the
        # pointer here, since Qt does *that* in the paintEvent this class
        # overrides. See page_bar.keep_floating_tab_with.
        self._floating: Optional[str] = None
        self._float_child = None
        self._float_offset = 0
        # where a page dragged down from the bar would land
        self._caret: Optional[int] = None
        self.setVisible(False)

    # ------------------------------------------------------------ contents

    def set_pages(self, pages, colors: dict, accent: Optional[str]) -> None:
        """Show `pages` — (page_id, title) in bar order — and nothing else.

        Rebuilt whole on every change, like the headers on the bar above:
        the row holds one group's pages, and working out which tab to patch
        costs more than making them again.
        """
        keep = self.current_page_id()
        self._colors = dict(colors)
        self._accent = accent
        self.blockSignals(True)
        try:
            while self.count():
                self.removeTab(0)
            for page_id, title in pages:
                index = self.addTab(title)
                self.setTabData(index, page_id)
            if keep is not None:
                self.select(keep)
        finally:
            self.blockSignals(False)
        self.update()

    def _on_tab_moved(self, from_index: int, to_index: int) -> None:
        self._dragging = True

    def pinned(self) -> Optional[str]:
        """A page that may not be dragged out of first place — the model
        canvas, which heads its row because it is what the others are
        views of."""
        first = self.tabData(0) if self.count() else None
        return first if first == _MODEL_PAGE else None

    def current_page_id(self) -> Optional[str]:
        index = self.currentIndex()
        return self.tabData(index) if index >= 0 else None

    def page_ids(self) -> list:
        return [self.tabData(i) for i in range(self.count())]

    def insert_index(self, x: int) -> int:
        """How many of the group's pages a drop at `x` goes after — the
        place on the row, counted in pages rather than tabs so the pinned
        model canvas is not one of them."""
        at = 0
        for i in range(self.count()):
            if self.tabData(i) == _MODEL_PAGE:
                continue
            if self.tabRect(i).center().x() < x:
                at += 1
        return at

    def set_drop_caret(self, x) -> None:
        """Mark the gap a page dragged down from the bar would land in, or
        take the mark away with None."""
        at = None if x is None else self._caret_at(int(x))
        if at == self._caret:
            return
        self._caret = at
        self.update()

    def _caret_at(self, x: int) -> int:
        last = None
        for i in range(self.count()):
            if self.tabData(i) == _MODEL_PAGE:
                continue
            rect = self.tabRect(i)
            if rect.center().x() > x:
                return rect.left()
            last = rect
        if last is not None:
            return last.right()
        return self.tabRect(0).right() if self.count() else 0

    def select(self, page_id: Optional[str]) -> None:
        """Make `page_id`'s tab current, if the row is showing it.

        Silent: the row follows the window rather than driving it, and a
        selection echoed back as a click would be a loop.
        """
        for i in range(self.count()):
            if self.tabData(i) == page_id:
                self.blockSignals(True)
                self.setCurrentIndex(i)
                self.blockSignals(False)
                return

    # ------------------------------------------------------------ painting

    def paintEvent(self, event) -> None:
        """The same three passes the bar above uses — shape, the page's own
        colour laid over it, label on top — plus the open group's line
        along the bottom, which is what ties the row to the header that
        opened it."""
        painter = QStylePainter(self)
        for i in range(self.count()):
            if self.tabData(i) == self._floating is not None:
                continue    # Qt is drawing it under the pointer
            option = QStyleOptionTab()
            self.initStyleOption(option, i)
            painter.drawControl(QStyle.CE_TabBarTabShape, option)
            tint = theme.page_tint(
                self._colors.get(self.tabData(i)),
                theme.TINT_STRONG if i == self.currentIndex()
                else theme.TINT_SOFT)
            if tint is not None:
                painter.fillRect(self.tabRect(i), tint)
            painter.drawControl(QStyle.CE_TabBarTabLabel, option)
        if self.count():
            line = theme.tint(self.palette().color(self.backgroundRole()),
                              self._accent or theme.SELECTION_OUTLINE,
                              theme.TINT_STRONG)
            painter.fillRect(QRect(0, self.height() - 2, self.width(), 2), line)
        if self._caret is not None:
            painter.fillRect(QRect(self._caret - 1, 0, 3, self.height() - 2),
                             QColor(theme.SELECTION_OUTLINE))

    # ------------------------------------------------------------ gestures

    def _hand_over(self, page_id, event, dropped: bool = False) -> bool:
        """Ask the host whether the row above is taking this drag."""
        if self.handover is None or not page_id:
            return False
        return bool(self.handover(page_id,
                                  event.globalPosition().toPoint(), dropped))

    def mouseMoveEvent(self, event) -> None:
        from .page_bar import keep_floating_tab_with, qt_floating_tab

        super().mouseMoveEvent(event)
        if self._pressed is not None and event.buttons() & Qt.LeftButton:
            at = event.position().toPoint()
            if (self._floating is None and self._press_at is not None
                    and (at - self._press_at).manhattanLength()
                    > QApplication.startDragDistance()):
                self._floating = self._pressed
                self._float_child = qt_floating_tab(self)
                if self._float_child is not None:
                    self._float_offset = self._float_child.x() - at.x()
                self.update()
            keep_floating_tab_with(self._float_child, self, at.x(),
                                   self._float_offset)
            self._handing_over = self._hand_over(self._pressed, event)

    def mouseReleaseEvent(self, event) -> None:
        pressed, self._pressed = self._pressed, None
        handing_over, self._handing_over = self._handing_over, False
        self._press_at = None
        self._float_child = None
        if self._floating is not None:
            self._floating = None
            self.update()
        super().mouseReleaseEvent(event)
        if handing_over and self._hand_over(pressed, event, True):
            # dragged up onto the bar: the page is leaving this group, so
            # whatever Qt did to the tabs on the way out is not a reorder
            # of the group — the move now in flight redraws the row anyway
            self._dragging = False
            return
        if not self._dragging:
            return
        self._dragging = False
        order = self.page_ids()
        if _MODEL_PAGE in order and order[0] != _MODEL_PAGE:
            # The model canvas was dragged out of first place, or something
            # was dragged over it. It heads its row — the others are views
            # of it — so it goes back to the front and the drag counts as
            # whatever it did to the rest.
            self.blockSignals(True)
            self.moveTab(order.index(_MODEL_PAGE), 0)
            self.blockSignals(False)
            order = self.page_ids()
        self.reordered.emit([page_id for page_id in order
                             if page_id != _MODEL_PAGE])

    def mousePressEvent(self, event) -> None:
        index = self.tabAt(event.position().toPoint())
        page_id = self.tabData(index) if index >= 0 else None
        if page_id is None:
            super().mousePressEvent(event)
            return
        if event.button() == Qt.RightButton:
            self.context_menu_requested.emit(
                page_id, event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self._pressed = page_id
            self._press_at = event.position().toPoint()
            self.page_clicked.emit(page_id)


class PageBarHost(QWidget):
    """The tab bar, and under it the second row when one is wanted.

    The host owns no state of its own: which group is open is the bar's
    business (it is the bar's headers that open one), and the row is
    refilled from the bar whenever the bar says it has changed. That keeps
    one source of truth for what a project's pages are, which is the same
    reason the bar itself is only ever a view of `graph.pages`.
    """

    def __init__(self, bar, parent=None) -> None:
        super().__init__(parent)
        self.bar = bar
        self.row = GroupRowBar(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(bar)
        layout.addWidget(self.row)
        bar.bar_changed.connect(self.refresh)
        bar.current_page_changed.connect(self._follow)
        self.row.page_clicked.connect(self._row_clicked)
        self.row.reordered.connect(self._row_reordered)
        self.row.context_menu_requested.connect(self._row_menu)
        # each row asks the host about the other one; the host is the only
        # thing that can see both
        bar.handover = self.onto_the_row
        self.row.handover = self.onto_the_bar
        self.refresh()

    # ------------------------------------------------------------- the row

    def refresh(self) -> None:
        """Fill the row from whatever the bar is showing now."""
        group = self.bar.open_group()
        if not self.bar.second_row() or not group:
            self.row.setVisible(False)
            return
        pages = [(page_id, self.bar.page_title(page_id))
                 for page_id in self.bar.pages_in(group)]
        self.row.set_pages(pages, self.bar.page_colors(),
                           self.bar.open_group_color())
        self.row.setVisible(bool(pages))
        self._follow(self.bar.current_page_id())

    def _follow(self, page_id) -> None:
        """Keep the row's own highlight on whichever page is showing.

        Unconditionally: a row that is not on screen yet still has to be
        right when it arrives, and asking whether it is visible answers
        "no" for any widget whose window has not been shown.
        """
        from .page_bar import MODEL_PAGE

        self.row.select(MODEL_PAGE if page_id is None else page_id)

    def _row_clicked(self, page_id: str) -> None:
        self.bar.select_page(page_id)

    def _row_reordered(self, order: list) -> None:
        """A drag on the row asks the window to reorder, exactly as a drag
        on the bar does — the row holds one group's pages, so the rest of
        the bar's order has to be left alone around them."""
        self.bar.reorder_within_group(order)

    def _row_menu(self, page_id: str, where) -> None:
        """A page's menu, the bar's own — so the row cannot drift from it."""
        self.bar.show_page_menu(page_id, where)

    # ------------------------------------------------- from row to row

    def onto_the_row(self, page_id: str, where, dropped: bool) -> bool:
        """A page dragged off the top row. Over the second row it joins
        the group that row is showing, at the place it is let go of.

        Which is what the top row *means* here — the pages in no group —
        so dragging one down is saying it belongs to the group on show,
        and there is no dialog to go through to say it.

        Answers whether the row is taking the gesture, so the bar knows
        not to also treat it as a reorder of its own. `dropped` is the
        release; before that this only paints the caret.
        """
        group = self.bar.open_group()
        if (not group or group == CANVASES
                or not self._over(self.row, where)):
            self.row.set_drop_caret(None)
            return False
        x = self.row.mapFromGlobal(where).x()
        self.row.set_drop_caret(None if dropped else x)
        if dropped:
            self.bar.drop_into_group(page_id, group,
                                     self.row.insert_index(x))
        return True

    def onto_the_bar(self, page_id: str, where, dropped: bool) -> bool:
        """A page dragged off the second row and onto the bar above: it
        leaves its group and takes the place it is let go of.

        The model canvas is not one — it has no page of its own to put
        anywhere, and it heads its row.
        """
        if page_id == _MODEL_PAGE or not self._over(self.bar, where):
            self.bar.set_drop_caret(None)
            return False
        x = self.bar.mapFromGlobal(where).x()
        self.bar.set_drop_caret(None if dropped else x)
        if dropped:
            self.bar.drop_from_row(page_id, x)
        return True

    @staticmethod
    def _over(widget, where) -> bool:
        """Whether a global point is on this widget.

        `isVisible()` is deliberately not asked: it answers no for any
        widget whose window has not been shown yet, and a row with no
        group open has no tabs for a drop to land among anyway — which
        `onto_the_row` checks by asking what is open.
        """
        return widget.rect().contains(widget.mapFromGlobal(where))
