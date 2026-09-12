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

from PySide6.QtCore import QEvent, QRect, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QInputDialog, QMenu, QStyle, QStyleOptionTab,
    QStylePainter, QTabBar, QToolButton,
)

from flograph.core import Page

from .. import theme


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

# tabData prefix for a group's header (AB4): "\x00group:Sales" heads the run
# of tabs in the Sales group. A header is not a page — it is never current,
# never dragged, and a click on it folds its group away.
_HEADER = "\x00group:"


def _header_group(data) -> Optional[str]:
    """The group a header tab heads, or None for any other tab."""
    if isinstance(data, str) and data.startswith(_HEADER):
        return data[len(_HEADER):]
    return None

# The `< >` arrows Qt adds when the tabs no longer fit. Qt owns them and
# names them, so they are looked up rather than kept.
_SCROLL_BUTTONS = ("ScrollLeftButton", "ScrollRightButton")


class PageTabBar(QTabBar):
    add_page_requested = Signal(str)   # "dashboard" | "report"
    rename_page_requested = Signal(str, str)   # page_id, new title
    delete_page_requested = Signal(str)        # page_id
    duplicate_page_requested = Signal(str)     # page_id to duplicate
    reorder_pages_requested = Signal(list)     # page_ids in their new order
    recolor_page_requested = Signal(str, object)  # page_id, "#rrggbb" or None
    set_page_group_requested = Signal(str, str)   # page_id, group ("" = none)
    rename_group_requested = Signal(str, str)     # old, new ("" = ungroup)
    recolor_group_requested = Signal(str, object)  # group, "#rrggbb" or None
    new_group_requested = Signal(str, str, str)   # page_id, name, colour
                                                  # ("" = automatic)
    set_view_mode_requested = Signal(str, bool)   # page_id, locked
    set_fit_to_window_requested = Signal(str, bool)   # page_id, scaling
    export_page_requested = Signal(str)           # page_id (locked reports)
    page_setup_requested = Signal(str)            # page_id (locked reports)
    export_html_requested = Signal(str)           # page_id (locked reports)
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
        # page_id -> scaling to the window, mirrored for the menu tick the
        # same way the lock below is
        self._fits: dict[str, bool] = {}
        # page_id -> locked. Mirrored here only so the context menu can show
        # which mode a page is in; the model stays the source of truth.
        # (Called view_mode in the model — "Locked" is what it says on the
        # menu, since that is what it does to the page.)
        self._view_modes: dict[str, bool] = {}
        # page_id -> "dashboard" | "report"; only the menu needs it, to offer
        # Export PDF on a locked report
        self._kinds: dict[str, str] = {}
        self._fenced: dict[str, bool] = {}   # canvas tabs: a view of a frame
        # page_id -> the group it sits in (AB4), mirrored from the model
        # like the rest; and the groups folded away, which is the bar's own
        # business — how the strip is being looked at, not the project
        self._groups: dict[str, str] = {}
        self._folded: set[str] = set()
        # group -> a colour of its own, mirrored from the model
        self._group_colors: dict[str, str] = {}
        # A press on a group's header, until its release: a click folds the
        # group, a drag moves all of it. Our own drag rather than Qt's — a
        # header is not a tab Qt should make current — so it keeps its
        # state here.
        self._header_drag: Optional[dict] = None
        self.currentChanged.connect(self._on_current_changed)
        self.tabMoved.connect(self._on_tab_moved)
        # A right-click on either arrow lists every tab (AA5). Watched on
        # the two buttons themselves, because a *disabled* arrow — the left
        # one, until you have scrolled — takes the click and drops it, so
        # it never reaches the bar. Two small widgets of the bar's own, not
        # the application: issue 7 is why that difference matters, and
        # test_page_bar_context_menu pins it.
        for name in _SCROLL_BUTTONS:
            button = self.findChild(QToolButton, name)
            if button is not None:
                button.installEventFilter(self)

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
        """Page ids in tab order — Model, "+" and group headers excluded."""
        return [data for i in range(self.count())
                if (data := self.tabData(i)) not in (None, _PLUS)
                and _header_group(data) is None]

    def _is_page(self, index: int) -> bool:
        return (0 <= index < self.count()
                and self.tabData(index) not in (None, _PLUS)
                and _header_group(self.tabData(index)) is None)

    def _is_model(self, index: int) -> bool:
        """The modeling canvas's own tab. tabData is None for it -- but also
        for a miss (tabAt returns -1), so the range check is what tells a
        click on the Model tab from a click on the empty strip beside it."""
        return 0 <= index < self.count() and self.tabData(index) is None

    def current_page_id(self) -> Optional[str]:
        data = self.tabData(self.currentIndex())
        return None if data == _PLUS or _header_group(data) is not None else data

    # ------------------------------------------------------------ sync API

    def add_page_tab(self, page: Page) -> None:
        self._syncing = True
        index = self.insertTab(self._plus_index(), page.title)
        self.setTabData(index, page.id)
        self._syncing = False
        self.set_page_color(page.id, page.color)
        self.set_page_view_mode(page.id, page.view_mode)
        self.set_page_fit_to_window(page.id, page.fit_to_window)
        self._kinds[page.id] = page.kind
        # a canvas tab fenced to a frame is a *view* of a canvas; one without
        # a frame is a canvas of its own, which can be copied (G12)
        self._fenced[page.id] = bool(getattr(page, "frame", ""))
        self._groups[page.id] = page.group or ""
        self._rebuild_groups()

    # -------------------------------------------------------- groups (AB4)

    def set_page_group(self, page_id: str, group: str) -> None:
        group = group or ""
        if self._groups.get(page_id, "") == group:
            return
        self._groups[page_id] = group
        self._rebuild_groups()

    def page_group(self, page_id: str) -> str:
        return self._groups.get(page_id, "")

    def group_names(self) -> list[str]:
        """The groups in use, in the order their sections appear."""
        from flograph.core.page_nav import group_names
        return group_names(self.page_order(), self._groups)

    def is_group_folded(self, group: str) -> bool:
        return group in self._folded

    def set_group_folded(self, group: str, folded: bool) -> None:
        """Fold a group's tabs away behind its header, or bring them back.
        The page being looked at stays showing either way: folding a
        section is tidying the strip, not leaving the page."""
        if folded:
            self._folded.add(group)
        else:
            self._folded.discard(group)
        self._rebuild_groups()

    def _drop_headers(self) -> None:
        """Take every header out. The caller holds _syncing."""
        for i in range(self.count() - 1, -1, -1):
            if _header_group(self.tabData(i)) is not None:
                self.removeTab(i)

    def _header_text(self, group: str) -> str:
        if group in self._folded:
            count = sum(1 for g in self._groups.values() if g == group)
            return f"▸ {group}  {count}"
        return f"▾ {group}"

    def _rebuild_groups(self) -> None:
        """Put a header in front of each run of a group's tabs, and hide the
        tabs of a folded one. Rebuilt whole rather than patched: the bar
        holds a handful of tabs, and a header's place follows from the page
        order alone, so rebuilding is the version that can't drift."""
        was_syncing = self._syncing
        self._syncing = True
        try:
            current = self.current_page_id()
            self._drop_headers()
            self._folded &= {g for g in self._groups.values() if g}
            previous = ""
            i = self._model_index() + 1
            while i < self._plus_index():
                page_id = self.tabData(i)
                group = self._groups.get(page_id, "")
                if group and group != previous:
                    self.insertTab(i, self._header_text(group))
                    self.setTabData(i, _HEADER + group)
                    # disabled, so the mouse wheel and the keyboard step
                    # over it; a click is still ours (mousePressEvent)
                    self.setTabEnabled(i, False)
                    self.setTabToolTip(
                        i, f"{group}: click to "
                        f"{'unfold' if group in self._folded else 'fold away'}"
                        " · drag to move the group"
                        " · right-click to rename or ungroup")
                    i += 1
                previous = group
                self._set_visible(
                    i, not (group in self._folded and page_id != current))
                i += 1
        finally:
            self._syncing = was_syncing
        self.update()

    def _apply_folds(self) -> None:
        """Show the current page's tab even inside a folded group, and put
        away the one that was current before."""
        current = self.current_page_id()
        for i in range(self.count()):
            data = self.tabData(i)
            if data in (None, _PLUS) or _header_group(data) is not None:
                continue
            group = self._groups.get(data, "")
            self._set_visible(
                i, not (group in self._folded and data != current))

    def _set_visible(self, index: int, visible: bool) -> None:
        """setTabVisible, only when it changes something. Qt's own resets
        the bar's pending relayout to "was this a change?", so asking for
        the visibility a tab already has cancels the relayout an insertTab
        had just queued — and a bar not yet on screen then keeps every tab
        rect empty, which is what anything that asks where a tab is sees."""
        if self.isTabVisible(index) != visible:
            self.setTabVisible(index, visible)

    def _blocks(self) -> list:
        """The bar as the units a dragged group moves between: each group
        (its header and pages) and each page in no group, in tab order, as
        [group or None, page ids, extent on the bar]. A group only ever
        lands between two of these, never inside another group's run."""
        blocks: list = []
        for i in range(self._model_index() + 1, self._plus_index()):
            data = self.tabData(i)
            rect = self.tabRect(i) if self.isTabVisible(i) else QRect()
            group = _header_group(data)
            if group is not None:
                blocks.append([group, [], rect])
                continue
            mine = self._groups.get(data, "")
            if mine and blocks and blocks[-1][0] == mine:
                blocks[-1][1].append(data)
                if not rect.isNull():
                    blocks[-1][2] = blocks[-1][2].united(rect)
            else:
                blocks.append([None, [data], rect])
        return blocks

    def _group_drop(self, group: str, x: int) -> list[str]:
        """The page order with `group` moved to where `x` is: before the
        first other block whose middle is past it. Asked on every move of a
        drag — once the group has jumped past a neighbour, that neighbour's
        middle is on the far side of the pointer, so it never jumps back
        and forth, the way a page tab behaves."""
        blocks = self._blocks()
        moving = next((b for b in blocks if b[0] == group), None)
        if moving is None:
            return self.page_order()
        others = [b for b in blocks if b is not moving and not b[2].isNull()]
        at = len(others)
        for n, block in enumerate(others):
            if block[2].center().x() > x:
                at = n
                break
        others.insert(at, moving)
        # blocks with no extent (nothing showing) keep their place at the end
        rest = [b for b in blocks if b is not moving and b[2].isNull()]
        return [p for b in others + rest for p in b[1]]

    def set_group_colors(self, colors: dict) -> None:
        """Told by the window whenever a group's colour changes."""
        self._group_colors = dict(colors)
        self.update()

    def group_color(self, group: str) -> Optional[str]:
        """The group's own colour, or None when it borrows one."""
        return self._group_colors.get(group)

    def _group_color(self, group: str) -> QColor:
        """The group's own colour; failing that the first coloured page in
        it lends the section its colour; otherwise the accent, so a section
        reads as one either way."""
        if self._group_colors.get(group):
            return QColor(self._group_colors[group])
        for page_id in self.page_order():
            if self._groups.get(page_id) == group and page_id in self._colors:
                return QColor(self._colors[page_id])
        return QColor(theme.SELECTION_OUTLINE)

    def set_page_view_mode(self, page_id: str, view_mode: bool) -> None:
        """Told by the window whenever the model changes, so the context
        menu's tick matches the page it was opened on."""
        self._view_modes[page_id] = bool(view_mode)

    def page_view_mode(self, page_id: str) -> bool:
        return self._view_modes.get(page_id, False)

    def set_page_fit_to_window(self, page_id: str, fit: bool) -> None:
        """The same mirror, for the scale-to-window tick."""
        self._fits[page_id] = bool(fit)

    def page_fit_to_window(self, page_id: str) -> bool:
        return self._fits.get(page_id, False)

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
        self._fits.pop(page_id, None)
        self._kinds.pop(page_id, None)
        self._fenced.pop(page_id, None)
        self._groups.pop(page_id, None)
        self._syncing = True
        self.removeTab(index)
        if was_current or self.currentIndex() >= self._plus_index():
            self.setCurrentIndex(self._model_index())
        self._syncing = False
        self._rebuild_groups()   # the last page of a group takes its header
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
            # headers out first, so the targets count pages only
            self._drop_headers()
            for target, page_id in enumerate(order, start=self._model_index() + 1):
                index = self._index_of_page(page_id)
                if index >= 0 and index != target:
                    self.moveTab(index, target)
        finally:
            self._syncing = False
        self._rebuild_groups()

    def select_page(self, page_id: Optional[str]) -> None:
        index = self._model_index() if page_id is None else self._index_of_page(page_id)
        if index >= 0:
            # a page in a folded group (reached from a Go to page button,
            # or the tab list) comes out to be looked at
            self._set_visible(index, True)
            self.setCurrentIndex(index)

    # ------------------------------------------------------------- painting

    def paintEvent(self, event) -> None:
        """Draw the themed tab, lay the page's colour over it at low alpha,
        then the label on top — the shape and the label are separate style
        elements, so the tint can sit between them without hiding the text."""
        painter = QStylePainter(self)
        for i in range(self.count()):
            if not self.isTabVisible(i):
                continue
            data = self.tabData(i)
            group = _header_group(data)
            if group is not None:
                self._paint_header(painter, i, group)
                continue
            option = QStyleOptionTab()
            self.initStyleOption(option, i)
            painter.drawControl(QStyle.CE_TabBarTabShape, option)
            color = self._colors.get(data)
            if color:
                tint = QColor(color)
                tint.setAlphaF(theme.TINT_STRONG if i == self.currentIndex()
                               else theme.TINT_SOFT)
                painter.fillRect(self.tabRect(i), tint)
            painter.drawControl(QStyle.CE_TabBarTabLabel, option)
            member = self._groups.get(data, "") if isinstance(data, str) else ""
            if member:
                # the run of a group's tabs shares a line along the bottom,
                # continuing its header's — that is what makes it a section
                rect = self.tabRect(i)
                painter.fillRect(QRect(rect.left(), rect.bottom() - 1,
                                       rect.width(), 2),
                                 self._muted_group_color(member))

    def _paint_header(self, painter, index: int, group: str) -> None:
        """A group's header, muted the way a coloured tab is: the group's
        colour laid over it at the strength a current tab gets, the name in
        the tabs' own text colour on top — so a loud pick comes out calm,
        and no pale one can make the name hard to read — and the section's
        line beneath."""
        rect = self.tabRect(index)
        painter.save()
        block = self._group_color(group)
        block.setAlphaF(theme.TINT_STRONG)
        painter.fillRect(rect.adjusted(1, 2, -1, 0), block)
        font = QFont(self.font())
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self.palette().color(QPalette.WindowText))
        painter.drawText(rect.adjusted(8, 0, -4, 0),
                         Qt.AlignVCenter | Qt.AlignLeft, self.tabText(index))
        painter.fillRect(QRect(rect.left(), rect.bottom() - 1,
                               rect.width(), 2),
                         self._muted_group_color(group))
        painter.restore()

    def _muted_group_color(self, group: str) -> QColor:
        """The group's colour as a solid line can show it: laid over the
        bar at the current tab's strength. Read at paint time, like the
        tabs' tint, so Settings ▸ Canvas reaches it without a restart."""
        return theme.tint(self.palette().color(self.backgroundRole()),
                          self._group_color(group).name(), theme.TINT_STRONG)

    def tabSizeHint(self, index: int):
        size = super().tabSizeHint(index)
        if _header_group(self.tabData(index)) is not None:
            # painted bold, which the style measured as regular
            size.setWidth(size.width() + 12)
        return size

    # ------------------------------------------------------------ gestures

    def _on_current_changed(self, index: int) -> None:
        if self._syncing or index < 0:
            return
        self._apply_folds()
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

    def eventFilter(self, watched, event) -> bool:
        """Right-clicks on the scroll arrows, the only thing watched. The
        press opens the list; its release and the context-menu event the
        platform sends after it are swallowed, or a second menu follows."""
        kind = event.type()
        if (kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease)
                and event.button() == Qt.RightButton):
            if kind == QEvent.MouseButtonPress:
                where = event.globalPosition().toPoint()
                self._menu_with_the_focus(
                    lambda: self.tab_list_menu().exec(where))
            return True
        if kind == QEvent.ContextMenu:
            return True
        return super().eventFilter(watched, event)

    def _menu_with_the_focus(self, show) -> None:
        """Run one of our right-click menus (`show` opens it and returns
        once it has closed) with this bar holding keyboard focus either side.

        On Wayland (Qt 6.11, found by Dan testing AB4) the context-menu
        event a right press brings is delivered not to the widget under the
        pointer but to whichever widget has *focus*, and only once the press
        handler — and so our whole menu — has returned. It used to land on
        the page below, whose own right-click menu then opened as ours
        closed: a lone greyed-out Paste on a dashboard, a whole edit menu on
        a report's text. With the focus here it arrives at contextMenuEvent
        below, which swallows it. Taken again afterwards because what the
        menu did can move the focus in between — locking a page hands it to
        the page, which is how the first version of this still leaked."""
        self.setFocus(Qt.MouseFocusReason)
        show()
        self.setFocus(Qt.MouseFocusReason)

    def tab_list_menu(self) -> QMenu:
        """Every tab in one list, the current one ticked (AA5). With more
        pages than fit, the arrows step one tab a click — a long way round
        to the page you already know the name of."""
        menu = QMenu(self)
        current = self.currentIndex()
        in_group = False
        for i in range(self.count()):
            data = self.tabData(i)
            if data == _PLUS:
                continue
            group = _header_group(data)
            if group is not None:
                # each section under its own heading (AB4) — and a folded
                # one's pages are still listed, this being the way to them
                menu.addSeparator()
                heading = menu.addAction(group)
                heading.setEnabled(False)
                bold = heading.font()
                bold.setBold(True)
                heading.setFont(bold)
                in_group = True
                continue
            if in_group and not self._groups.get(data, ""):
                menu.addSeparator()
                in_group = False
            action = menu.addAction(self.tabText(i))
            action.setCheckable(True)
            action.setChecked(i == current)
            # by id, not index: the list is only read when it is picked from
            action.triggered.connect(
                lambda _checked=False, page_id=data: self.select_page(page_id))
        return menu

    def mousePressEvent(self, event) -> None:
        index = self.tabAt(event.position().toPoint())
        group = _header_group(self.tabData(index)) if index >= 0 else None
        if group is not None:
            # a header is a switch, not a tab: a click folds (on release, so
            # a drag can move the group instead), right-click is its own
            # menu, and it is never the current tab
            if event.button() == Qt.LeftButton:
                self._header_drag = {"group": group,
                                     "start": event.position().toPoint(),
                                     "moving": False,
                                     "order": self.page_order()}
            elif event.button() == Qt.RightButton:
                where = event.globalPosition().toPoint()
                self._menu_with_the_focus(
                    lambda: self._group_menu(group).exec(where))
            event.accept()
            return
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
                where = event.globalPosition().toPoint()
                self._menu_with_the_focus(
                    lambda: self._show_context_menu(index, page_id, where))
                event.accept()
                return
        # only page tabs are draggable; Model is pinned in place
        self._drag_locked = not self._is_page(index)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        drag = self._header_drag
        if drag is not None:
            pos = event.position().toPoint()
            if not drag["moving"] and (pos - drag["start"]).manhattanLength() \
                    >= QApplication.startDragDistance():
                drag["moving"] = True
                self.setCursor(Qt.ClosedHandCursor)
            if drag["moving"]:
                # the bar moves as the pointer does, like a dragged page tab;
                # the project only hears about it once, on release
                order = self._group_drop(drag["group"], pos.x())
                if order != self.page_order():
                    self.set_page_order(order)
            event.accept()
            return
        if self._drag_locked:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        drag, self._header_drag = self._header_drag, None
        if drag is not None:
            group = drag["group"]
            if drag["moving"]:
                # one reorder request, the same one a dragged page makes, so
                # the window keeps the groups whole and it undoes in one step
                self.unsetCursor()
                if self.page_order() != drag["order"]:
                    self.reorder_pages_requested.emit(self.page_order())
            else:
                self.set_group_folded(group, group not in self._folded)
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self._drag_locked = False
        if self._reorder_pending:
            # one request per drag, not one per swap Qt makes along the way
            self._reorder_pending = False
            self.reorder_pages_requested.emit(self.page_order())
            # Qt drags a page straight past a header, which is not a page
            # and so moves in no order the window keeps — put them back
            self._rebuild_groups()

    def _show_add_menu(self, global_pos) -> None:
        menu, choices = self._add_menu()
        chosen = menu.exec(global_pos)
        if chosen in choices:
            self.add_page_requested.emit(choices[chosen])

    def _add_menu(self) -> tuple:
        """"+" asks what kind of page. A menu rather than buttons: the strip
        is a tab bar, and dashboards stay the one-click-away default by being
        first. A model canvas comes last, after a line — another view of the
        flow for whoever builds it (G12), not a page for anyone reading it.

        Built apart from showing it, like the tab menu, so what is on it can
        be asserted without an exec() that would block the suite."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        choices = {menu.addAction("Dashboard page"): "dashboard",
                   menu.addAction("Report page"): "report"}
        menu.addSeparator()
        choices[menu.addAction("Model canvas")] = "canvas"
        return menu, choices

    def contextMenuEvent(self, event) -> None:
        """Swallow the context-menu event that follows our own right-click.

        The tab menu opens on *press*, so the tab never becomes current
        (relying on tabBarClicked and reselecting flickers). The platform
        then sends a context-menu event on release, which without this
        would open a second menu on top of the one already showing.

        This used to be done by installing an event filter on the
        *QApplication* for half a second after every tab menu. That filter
        saw every event in the process — including the hover and mouse-move
        floods inside the Plotly card's embedded Chromium, each of which had
        to be handed to Python — which made dragging a chart sluggish and
        then segfaulted inside PySide's wrapper bookkeeping. Accepting the
        event on the one widget it is delivered to does the same job, with
        no timer, no global state and nothing to leak.
        """
        event.accept()

    def _show_context_menu(self, index: int, page_id: str, global_pos) -> None:
        self._context_menu(index, page_id).exec(global_pos)

    def _context_menu(self, index: int, page_id: str) -> QMenu:
        """Build the tab's menu without showing it.

        Separate from showing it so what is on the menu can be asserted
        without an exec() that would block the suite forever.
        """
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
        # A canvas tab (G12) is the model canvas, whole or fenced to a frame:
        # nothing on it is laid out to be locked or scaled, and a copy of a
        # view is only another view. What it has is a name, a colour, a
        # place in the bar, and a way to close it.
        canvas_tab = self._kinds.get(page_id) == "canvas"
        if not canvas_tab:
            menu.addAction(lock_action)
        # Only dashboards: a report already sits on a page of a declared
        # size, and how that is fitted is the preview's business.
        if self._kinds.get(page_id) not in ("report", "canvas"):
            fit_action = QAction("Scale to fit the window", self)
            fit_action.setCheckable(True)
            fit_action.setChecked(self._fits.get(page_id, False))
            fit_action.setToolTip(
                "Keep the whole page in view: it zooms as the window "
                "changes size, so the same tiles stay framed instead of a "
                "bigger window revealing empty canvas around them. Zooming "
                "by hand is off while this is on.")
            fit_action.triggered.connect(
                lambda checked: self.set_fit_to_window_requested.emit(
                    page_id, bool(checked)))
            menu.addAction(fit_action)
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
            html_action = QAction("Save HTML…", self)
            html_action.triggered.connect(
                lambda: self.export_html_requested.emit(page_id))
            menu.addAction(html_action)
        menu.addSeparator()
        rename_action = QAction("Rename", self)
        dup_action = QAction("Duplicate", self)
        color_action = QAction("Change colour…", self)
        reset_color_action = (QAction("Reset colour", self)
                              if page_id in self._colors else None)
        del_action = QAction("Close Tab" if canvas_tab else "Delete", self)
        if canvas_tab:
            del_action.setToolTip(
                "Close this tab. The frame and everything in it stay on "
                "the canvas.")
        rename_action.triggered.connect(
            lambda: self._prompt_rename(index, page_id))
        dup_action.triggered.connect(lambda: self.duplicate_page_requested.emit(page_id))
        color_action.triggered.connect(lambda: self._prompt_color(page_id))
        del_action.triggered.connect(lambda: self.delete_page_requested.emit(page_id))
        menu.addAction(rename_action)
        # a canvas of its own can be copied, contents and all; a tab that
        # only *looks at* a frame cannot — a second look is not a copy
        if not (canvas_tab and self._fenced.get(page_id, False)):
            menu.addAction(dup_action)
        menu.addAction(color_action)
        if reset_color_action is not None:
            reset_color_action.triggered.connect(
                lambda: self.recolor_page_requested.emit(page_id, None))
            menu.addAction(reset_color_action)
        menu.addMenu(self._group_submenu(page_id, menu))
        menu.addAction(del_action)
        return menu

    def _group_submenu(self, page_id: str, parent: QMenu) -> QMenu:
        """Group ▸ No group / the groups in use / New group… (AB4).

        Parented to the tab menu when it is made: a submenu only Python
        holds is deleted when this returns, leaving a dead entry behind."""
        sub = QMenu("Group", parent)
        mine = self._groups.get(page_id, "")
        none_action = sub.addAction("No group")
        none_action.setCheckable(True)
        none_action.setChecked(not mine)
        none_action.triggered.connect(
            lambda: self.set_page_group_requested.emit(page_id, ""))
        names = self.group_names()
        if names:
            sub.addSeparator()
        for name in names:
            action = sub.addAction(name)
            action.setCheckable(True)
            action.setChecked(name == mine)
            action.triggered.connect(
                lambda _checked=False, name=name:
                self.set_page_group_requested.emit(page_id, name))
        sub.addSeparator()
        new_action = sub.addAction("New group…")
        new_action.triggered.connect(lambda: self._prompt_new_group(page_id))
        return sub

    def _prompt_new_group(self, page_id: str) -> None:
        """Name the group and, while at it, give it a colour."""
        from . import group_dialog
        dialog = group_dialog.GroupDialog(self)
        if dialog.exec() and dialog.name():
            self.new_group_requested.emit(page_id, dialog.name(),
                                          dialog.colour())

    def _prompt_group_color(self, group: str) -> None:
        color = QColorDialog.getColor(self._group_color(group), self,
                                      f"Colour of {group}")
        if color.isValid():
            self.recolor_group_requested.emit(group, color.name())

    def _group_menu(self, group: str) -> QMenu:
        """A header's own menu: fold, rename, or ungroup."""
        menu = QMenu(self)
        folded = group in self._folded
        fold_action = menu.addAction("Unfold" if folded else "Fold away")
        fold_action.triggered.connect(
            lambda: self.set_group_folded(group, not folded))
        menu.addSeparator()
        rename_action = menu.addAction("Rename group…")
        rename_action.triggered.connect(lambda: self._prompt_rename_group(group))
        color_action = menu.addAction("Change colour…")
        color_action.triggered.connect(lambda: self._prompt_group_color(group))
        if self._group_colors.get(group):
            reset_action = menu.addAction("Reset colour")
            reset_action.setToolTip("Back to the colour of its first "
                                    "coloured page")
            reset_action.triggered.connect(
                lambda: self.recolor_group_requested.emit(group, None))
        ungroup_action = menu.addAction("Ungroup")
        ungroup_action.triggered.connect(
            lambda: self.rename_group_requested.emit(group, ""))
        return menu

    def _prompt_rename_group(self, group: str) -> None:
        name, ok = QInputDialog.getText(self, "Rename group", "Group name:",
                                        text=group)
        name = name.strip()
        if ok and name and name != group:
            if group in self._folded:
                # the fold belongs to the section, whatever it is called
                self._folded.discard(group)
                self._folded.add(name)
            self.rename_group_requested.emit(group, name)

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
        if index >= 0 and _header_group(self.tabData(index)) is not None:
            # the second click of a double-click on a header is a click:
            # passing it on would reach mousePressEvent through Qt anyway
            self.mousePressEvent(event)
            return
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
