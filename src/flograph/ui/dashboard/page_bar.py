"""PageTabBar: the strip under the canvas — "Model" first, one tab per
dashboard page, and a trailing "+" that creates a page.

The bar is a *view* of graph.pages: MainWindow drives it through the sync
API (add_page_tab / remove_page_tab / set_page_title / set_page_order /
select_page) from graph events, and user gestures come back out as request
signals — the bar never touches the graph itself.

Page tabs can be dragged to reorder; "Model" and "+" are pinned to the ends
(see _enforce_pinned), and one drag produces one reorder request — or, when
the tab lands in a different group's section, one move request carrying the
group it joins (see _landing_group)."""
from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtCore import QEvent, QRect, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontMetrics, QPalette
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QInputDialog, QMenu, QStyle, QStyleOptionTab,
    QStylePainter, QTabBar, QToolButton, QWidget,
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
#: The first tab: the model canvas itself. Named here because it is also
#: the header its canvas tabs fold under (G12/G13), which rewrites the text
#: to carry a chevron and a count.
MODEL_TAB = "Model"

_HEADER = "\x00group:"

#: The Model tab's canvases, as a group name — it is a header like any
#: other (G12/G13), so with a second row it opens onto one too. A sentinel
#: rather than MODEL_TAB, since a group of pages may itself be called
#: "Model".
CANVASES = "\x00canvases"

#: The model canvas itself, as an entry on that group's row. It is the one
#: page with no id of its own — `current_page_id()` answers None for it —
#: so the row needs a name to put in a tab's data like any other.
MODEL_PAGE = "\x00model"


def qt_floating_tab(bar):
    """Qt's own floating copy of the tab being dragged, or None.

    Qt draws a dragged tab as a child widget holding a pixmap of it
    (`QMovableTabWidget`). The class is private and comes back through
    PySide as a plain `QWidget`, so it is found by shape instead: the one
    direct child of the bar that is visible and is not a scroll arrow.
    Only ever asked for while a drag is on, when that is the only such
    child there is.
    """
    for child in bar.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
        if isinstance(child, QToolButton) or not child.isVisible():
            continue
        return child
    return None


def keep_floating_tab_with(child, bar, x: int, offset: int) -> None:
    """Move Qt's floating tab to where the pointer has it.

    **`QTabBar` does this in its own `paintEvent`** — the branch that runs
    while a drag is in progress sets the moving widget's geometry instead
    of drawing the tab. A bar that paints its own tabs overrides that
    method and so never runs it, and the floating copy stays frozen at the
    spot it was picked up from while the rest of the bar shuffles around
    it: the tab looks like it never left, and a hole opens where it is
    about to land.

    `offset` is how far the child sat from the pointer when Qt made it, so
    the point the tab was grabbed by stays under the pointer — which needs
    nothing from Qt's private drag offset. Kept on the bar, as Qt keeps it.
    """
    if child is None:
        return
    left = max(0, min(x + offset, bar.width() - child.width()))
    if child.x() != left:
        child.move(left, child.y())


def _header_group(data) -> Optional[str]:
    """The group a header tab heads, or None for any other tab."""
    if isinstance(data, str) and data.startswith(_HEADER):
        return data[len(_HEADER):]
    return None

# The `< >` arrows Qt adds when the tabs no longer fit. Qt owns them and
# names them, so they are looked up rather than kept.
_SCROLL_BUTTONS = ("ScrollLeftButton", "ScrollRightButton")


#: What "+" and every **New ▸** submenu offer, in the order they offer it.
#: One list because the two used to be written out separately, and a kind
#: added to one is a kind missing from the other.
NEW_PAGE_KINDS = (("Dashboard page", "dashboard"),
                  ("Report page", "report"),
                  (None, None),
                  ("Model canvas", "canvas"))


class PageTabBar(QTabBar):
    add_page_requested = Signal(str)   # "dashboard" | "report"
    rename_page_requested = Signal(str, str)   # page_id, new title
    delete_page_requested = Signal(str)        # page_id
    duplicate_page_requested = Signal(str)     # page_id to duplicate
    reorder_pages_requested = Signal(list)     # page_ids in their new order
    # a dragged tab that lands in another group, or out of its own:
    # page_ids in their new order, the page, the group it is now in ("" none)
    move_page_requested = Signal(list, str, str)
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
    # the bar's own contents changed (tabs, titles, colours, which group is
    # open) — what a second row rebuilds itself from; see page_rows
    bar_changed = Signal()
    # Settings ▸ General has this too; the bar offers it because the bar is
    # where you are when you want it (#12)
    second_row_requested = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setExpanding(False)
        self.setDocumentMode(True)
        self.setDrawBase(False)
        self.setMovable(True)  # page tabs only; see _enforce_pinned
        self._syncing = True
        self.addTab(MODEL_TAB)  # tabData None = the modeling canvas
        plus = self.addTab("+")
        self.setTabData(plus, _PLUS)
        self.setTabToolTip(plus, "Add a dashboard or report page")
        self._syncing = False
        self._drag_locked = False   # press landed on a tab that can't move
        self._reorder_pending = False
        # the page tab a press landed on, until its release: which tab a
        # drag is carrying, so its drop can say what group it landed in
        self._dragged: Optional[str] = None
        # while a page tab is dragged into another group, that group — its
        # header is lit, saying where the drop will put it
        self._drop_hint: Optional[str] = None
        # Where a press landed, and the page Qt is currently carrying
        # under the pointer. See `_floating` — a painted bar has to leave
        # that tab's slot empty, or the tab is on the bar twice.
        self._press_at = None
        self._floating: Optional[str] = None
        # Qt's floating copy of it, and how far it sat from the pointer
        # when Qt made it — see keep_floating_tab_with
        self._float_child = None
        self._float_offset = 0
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
        # Whether a canvas tab only *looks at* a canvas something else owns
        # (a frame's fenced view, or a box's canvas, G13) — so closing it
        # loses nothing — or is the canvas, so removing it deletes what is on
        # it. Box ownership lives on the frame, which the bar never sees, so
        # the window answers; the default knows only about fenced tabs.
        self.canvas_tab_is_view = lambda page_id: self._fenced.get(
            page_id, False)
        # Canvas tabs (G12/G13) are the Model tab's own group: it is the
        # header, so they fold away under it rather than under a header tab
        # repeating a name the bar already carries. Bar state, not saved —
        # the same as a group's fold.
        self._model_folded = False
        # page_id -> the group it sits in (AB4), mirrored from the model
        # like the rest; and the groups folded away, which is the bar's own
        # business — how the strip is being looked at, not the project
        self._groups: dict[str, str] = {}
        self._folded: set[str] = set()
        # Settings ▸ Canvas: the group headers keep the top row and their
        # pages go on a row beneath (see page_rows). The open group is the
        # bar's own business, like a fold, and starts closed — a project
        # remembers which groups were folded, not which one you were last
        # looking into.
        self._second_row = False
        self._open_group = ""
        # group -> a colour of its own, mirrored from the model
        self._group_colors: dict[str, str] = {}
        # A press on a group's header, until its release: a click folds the
        # group, a drag moves all of it. Our own drag rather than Qt's — a
        # header is not a tab Qt should make current — so it keeps its
        # state here.
        self._header_drag: Optional[dict] = None
        # a press that landed on the Model tab with a second row below it,
        # until its release — see mousePressEvent
        self._model_press = False
        # Set by PageBarHost when there is a second row: called while a
        # page tab is dragged and again when it is dropped, with the page,
        # where the pointer is, and whether this is the drop. It answers
        # whether the *row* is taking the gesture — so a page dragged onto
        # the row joins the open group there and is never also a reorder
        # of this bar. None when the bar stands on its own.
        self.handover = None
        self._handing_over = False
        # where a page dragged off the row would land on this bar, while
        # the pointer is over it
        self._caret: Optional[int] = None
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

    # ------------------------------------------------ the second row (#12)

    def second_row(self) -> bool:
        return self._second_row

    def set_second_row(self, on: bool) -> None:
        """Turn the second row on or off.

        Switching it on opens the group the current page is in — or the
        first group there is — so the row arrives showing something rather
        than empty. There is always one open while there is one to open;
        see toggle_open_group.
        """
        on = bool(on)
        if on == self._second_row:
            return
        self._second_row = on
        self._open_group = self._pick_open_group() if on else ""
        self._rebuild_groups()

    def open_group(self) -> str:
        """The group whose pages are on the second row, "" for none."""
        return self._open_group if self._second_row else ""

    def set_open_group(self, group: str) -> None:
        """Open a group onto the second row — or close it, with ""."""
        if not self._second_row or group == self._open_group:
            return
        self._open_group = group
        self._rebuild_groups()

    def toggle_open_group(self, group: str) -> None:
        """What clicking a header does: open that group.

        Clicking the open one again does **nothing**. The row is not a
        thing to collapse — it is where a group's pages live, and a bar
        that can be left with its pages nowhere is a bar with a state in
        it that nobody wants and everybody can reach by accident. One
        group at a time: the headers are a row of switches, and one of
        them is on.

        The row does close, but not from here — going to a page that is
        in **no** group closes it, because then there is no group being
        looked at and a row of some other group's pages is just in the
        way. See `_on_current_changed`.
        """
        self.set_open_group(group)

    def _groups_available(self) -> list:
        """Every group with pages in it, in bar order — the Model tab's
        canvases among them, since it is a header too."""
        seen: list = []
        for page_id in self.page_order():
            group = self._group_of(page_id)
            if group and group not in seen:
                seen.append(group)
        return seen

    def _pick_open_group(self) -> str:
        """Which group the row shows when it has to choose for itself: the
        one holding the page you are on, failing that the first there is.
        Nothing only when the project has no groups at all, and then there
        is no row rather than an empty one."""
        mine = self._group_of(self.current_page_id())
        if mine:
            return mine
        available = self._groups_available()
        return available[0] if available else ""

    def _group_of(self, page_id) -> str:
        """The group a page belongs to for the second row's purposes —
        which for a canvas tab, and for the model canvas itself, is the
        Model tab that heads them."""
        if page_id is None or page_id == MODEL_PAGE:
            # the model canvas: in its own group while there is one, so
            # that turning the row on while looking at it opens the group
            # it is in, like any other page
            return CANVASES if self._canvas_tabs() else ""
        group = self._groups.get(page_id, "")
        if group:
            # a canvas tab that has been put in a group is that group's:
            # one header each, and this is the one holding it
            return group
        if self._kinds.get(page_id) == "canvas":
            return CANVASES
        return ""

    def pages_in(self, group: str) -> list:
        """The page ids in `group`, in bar order.

        The canvases' row leads with the model canvas itself. Clicking
        **Models** opens the row and nothing else, exactly as clicking any
        other header does — so the canvas it used to jump to has to be on
        the row to still be reachable, and being there makes it one of the
        things the header holds rather than a special case of the header.
        """
        pages = [page_id for page_id in self.page_order()
                 if self._group_of(page_id) == group]
        if group == CANVASES:
            return [MODEL_PAGE] + pages
        return pages

    def page_title(self, page_id: str) -> str:
        if page_id == MODEL_PAGE:
            return "Model canvas"
        index = self._index_of_page(page_id)
        return self.tabText(index) if index >= 0 else ""

    def reorder_within_group(self, order: list) -> None:
        """A group's pages in a new order among themselves, from a drag on
        the second row.

        The rest of the bar does not move: each of the group's places in
        the whole order takes the next page from `order`, so a group sits
        where it sat and only its own pages shuffle. Sent on as the same
        reorder request a drag on the bar makes, so the window keeps the
        groups whole and it undoes in one step.
        """
        wanted = [page_id for page_id in order
                  if self._index_of_page(page_id) >= 0]
        if not wanted:
            return
        group = self._group_of(wanted[0])
        remaining = list(wanted)
        full = []
        for page_id in self.page_order():
            if self._group_of(page_id) == group and remaining:
                full.append(remaining.pop(0))
            else:
                full.append(page_id)
        if full != self.page_order():
            self.reorder_pages_requested.emit(full)

    def page_colors(self) -> dict:
        return dict(self._colors)

    def open_group_color(self):
        """The open group's colour as the row should draw it."""
        group = self.open_group()
        if not group:
            return None
        if group == CANVASES:
            return theme.SELECTION_OUTLINE
        return self._group_color(group).name()

    def show_page_menu(self, page_id: str, where) -> None:
        """The page menu, for a row that has no index of its own."""
        index = self._index_of_page(page_id)
        if index >= 0:
            self._menu_with_the_focus(
                lambda: self._show_context_menu(index, page_id, where))

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

    def folded_groups(self) -> set:
        """The sections folded away right now — what the project saves."""
        return set(self._folded)

    def set_folded_groups(self, groups) -> None:
        """Fold exactly these sections and unfold the rest — a project
        being opened. One call rather than a `set_group_folded` each,
        because each rebuilds the whole bar."""
        wanted = {str(g) for g in groups if g}
        if wanted == self._folded:
            return
        self._folded = wanted
        self._rebuild_groups()

    def model_folded(self) -> bool:
        return self._model_folded

    def set_model_folded(self, folded: bool) -> None:
        """The Model tab's own fold over its canvas tabs, set outright.
        `toggle_model_fold` is the gesture; this is the restore."""
        folded = bool(folded)
        if folded == self._model_folded:
            return
        self._model_folded = folded
        self._rebuild_groups()

    def _drop_headers(self) -> None:
        """Take every header out. The caller holds _syncing."""
        for i in range(self.count() - 1, -1, -1):
            if _header_group(self.tabData(i)) is not None:
                self.removeTab(i)

    def _header_text(self, group: str) -> str:
        count = sum(1 for g in self._groups.values() if g == group)
        if self._second_row:
            # No chevron. It was there to say "this folds", and with a row
            # below it would be saying what the header's own highlight
            # already says — which is the thing a person actually looks at
            # to find the group they are in. The count stays: the pages are
            # never on this row to be counted by eye.
            return f"{group}  {count}"
        if group in self._folded:
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
            if self._second_row and self._open_group and self._open_group not in (
                    self._groups_available()):
                # the open group has gone — its last page left it, it was
                # renamed, the project was closed. The row takes another
                # rather than emptying: see toggle_open_group.
                self._open_group = self._pick_open_group()
            self._drop_headers()
            self._folded &= {g for g in self._groups.values() if g}
            previous = ""
            i = self._model_index() + 1
            while i < self._plus_index():
                page_id = self.tabData(i)
                group = self._groups.get(page_id, "")
                if group and group != previous:
                    # Empty first, then the data, then the text. A tab's
                    # size hint is worked out by `insertTab` there and
                    # then, and `tabSizeHint` below can only tell a header
                    # from a page by its data — which `insertTab` has not
                    # been given yet. So a header went on the bar measured
                    # as a plain tab and stayed 12px narrow until something
                    # else happened to refresh the layout, at which point
                    # it grew and shunted every tab to its right along.
                    # Setting the text *after* the data measures it once,
                    # right, and it never moves again.
                    self.insertTab(i, "")
                    self.setTabData(i, _HEADER + group)
                    self.setTabText(i, self._header_text(group))
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
                self._set_visible(i, self._shown(page_id, current))
                i += 1
            self._apply_model_fold()
            # Hiding the tab that was current makes Qt move the selection
            # to the next visible one — so the page would change under the
            # user just because its group closed. Put it back: a hidden tab
            # is allowed to be current, it is only the *hiding* Qt reacts
            # to, and _syncing keeps all of this off the wire.
            if current is not None and self.current_page_id() != current:
                index = self._index_of_page(current)
                if index >= 0:
                    self.setCurrentIndex(index)
        finally:
            self._syncing = was_syncing
        self.update()
        self.bar_changed.emit()

    # ------------------------------------------ the Model tab as a header

    def _canvas_tabs(self) -> list[int]:
        """The indexes of the canvas tabs **the Model tab heads** — every
        one that no group has taken.

        A canvas tab used to be the Model tab's and nothing else's. Putting
        one in a group gave it two headers, and two headers claiming one
        tab is how it kept being pulled back out of whichever had it last.
        The answer to that is not that it cannot be done: it is that only
        one header has it. A canvas tab in a group is that group's — it
        sits in that section, folds with it and rides its row — and one in
        no group is the Model tab's, exactly as before. Which is what this
        answers, and why everything that asks "are these mine" asks here.
        """
        return [i for i in range(self.count())
                if self._heads_model(self.tabData(i))]

    def _heads_model(self, page_id) -> bool:
        """Whether the Model tab is this tab's header: a canvas tab that no
        group has taken."""
        return (self._kinds.get(page_id) == "canvas"
                and not self._groups.get(page_id, ""))

    def _model_chevron_rect(self) -> QRect:
        """The part of the Model tab that folds its canvases away. A zone
        rather than the whole tab: clicking Model still means "show me the
        model canvas", which is what it has always meant."""
        rect = self.tabRect(self._model_index())
        return QRect(rect.left(), rect.top(), 18, rect.height())

    def _apply_model_fold(self) -> None:
        """Say on the Model tab how many canvas tabs it heads and whether
        they are folded away.

        The label only: which tabs are on show is decided once, in the loop
        above, so this can never overrule a group's own fold. The caller
        holds _syncing.
        """
        canvases = self._canvas_tabs()
        index = self._model_index()
        if not canvases:
            if self.tabText(index) != MODEL_TAB:
                self.setTabText(index, MODEL_TAB)
            return
        if self._second_row:
            # A header like any other here, so no chevron — the highlight
            # says which one is open. Plural when it heads more than one
            # canvas, because that is what the tab is then a way into: the
            # word is doing the work the chevron used to.
            open_here = self._open_group == CANVASES
            # The count is what the row holds, so the model canvas counts
            # itself — it is the first thing on it. Always plural, then:
            # with no canvas tabs to head there is no row and no header,
            # and this branch is not reached at all.
            text = f"{MODEL_TAB}s  {len(canvases) + 1}"
        else:
            open_here = not self._model_folded
            text = (f"▸ {MODEL_TAB}  {len(canvases)}" if self._model_folded
                    else f"▾ {MODEL_TAB}")
        if self.tabText(index) != text:
            self.setTabText(index, text)
        self.setTabToolTip(
            index,
            f"The model canvas. Click the chevron to "
            f"{'fold away' if open_here else 'show'} its "
            f"{len(canvases)} canvas tab(s).")

    def _model_menu(self) -> QMenu:
        """The Model tab's own menu: the canvas tabs it heads, and the fold.

        The Model tab is a group header like any other (G12/G13), so it
        answers a right-click the same way — here is what is in it, go
        straight to one — without the canvases having to be on show."""
        menu = QMenu(self)
        canvases = self._canvas_tabs()
        if canvases and not self._second_row:
            self._add_page_entries(menu, [self.tabData(i) for i in canvases])
            menu.addSeparator()
            fold_action = menu.addAction(
                "Show the canvases" if self._model_folded
                else "Fold the canvases away")
            fold_action.triggered.connect(self.toggle_model_fold)
            menu.addSeparator()
        # New is here even with no canvas tabs to head, which is why this
        # no longer returns an empty menu early: the Model tab is the one
        # tab a project always has, so it is the one place a right-click
        # can always be relied on to offer a page
        menu.addMenu(self._new_page_submenu(menu))
        self._add_row_toggle(menu)
        return menu

    def toggle_model_fold(self) -> None:
        """Fold the canvas tabs away under the Model tab, or bring them
        back. Nothing about the pages changes — this is the bar tidying
        itself, like folding a group."""
        if not self._canvas_tabs():
            return
        self._model_folded = not self._model_folded
        self._rebuild_groups()

    def _folded_away(self, page_id) -> bool:
        """Whether a fold is currently putting this page's tab away — its
        section's fold, or the Model tab's over the canvas tabs it heads
        (G12/G13).

        **One decision, both folds, in one place.** Deciding it twice meant
        the later one winning: it first pulled a grouped canvas tab back
        onto the bar, and then — because only one of the two copies knew
        about the Model tab — dragging a page to reorder it unfolded every
        canvas mid-drag, since a drag changes which tab is current and that
        runs `_apply_folds` (0.1.15 #11).
        """
        if self._second_row:
            # the top row is headers and ungrouped pages, and stays that
            # way whether or not the group is open — an open group's pages
            # are on the row beneath it, not in both places
            return bool(self._group_of(page_id))
        group = self._groups.get(page_id, "")
        if group and group in self._folded:
            return True
        return self._model_folded and self._heads_model(page_id)

    def _shown(self, page_id, current) -> bool:
        """Whether this page's tab belongs on the top row as things stand.

        A page in a folded group still comes out while it is the one being
        looked at — that is what makes a fold a way of *tidying* the bar
        rather than of losing a page. With a second row it does not: it is
        on that row, and a tab on both rows would be the bar saying the
        same thing twice. Qt keeps a hidden tab current perfectly well
        (only *hiding the current tab* moves the selection on, which
        `_rebuild_groups` puts back), so nothing is lost by leaving it off.
        """
        if not self._folded_away(page_id):
            return True
        return page_id == current and not self._second_row

    def _apply_folds(self) -> None:
        """Show the current page's tab even inside a folded group, and put
        away the one that was current before."""
        current = self.current_page_id()
        for i in range(self.count()):
            data = self.tabData(i)
            if data in (None, _PLUS) or _header_group(data) is not None:
                continue
            self._set_visible(i, self._shown(data, current))

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

    def _landing_group(self, page_id: str, x: Optional[int] = None) -> str:
        """The group a dragged page tab belongs in, read from where it now
        sits on the bar — what the header and the line under a section say.

        With the pointer over a group's header (`x`, on the bar), it is in
        that group: Qt has already slid the tab to the header's near side
        by then, so where it sits can't say so. Right after a header, or
        between two of a group's tabs, it is in that group too: dropped
        onto a section is dropped into it, folded or not. Just past a group's last tab it stays in the group only if it
        was already there, so a page can still be put down beside a group
        without joining it. Anywhere else it is in no group, which is how
        a page is dragged out of one.

        Neighbours are the tabs on show: a folded group's pages are hidden
        behind its header, and a tab dropped next to that header is next
        to the group whichever side of the hidden ones Qt put it. A canvas
        tab lands like any other — the Model tab heads the ones no group
        has taken, and a drag is one of the ways a group takes one.
        """
        mine = self._groups.get(page_id, "")
        index = self._index_of_page(page_id)
        if index < 0:
            return mine
        if x is not None:
            for i in range(self.count()):
                over = _header_group(self.tabData(i))
                rect = self.tabRect(i)
                if (over is not None and self.isTabVisible(i)
                        and rect.left() <= x <= rect.right()):
                    return over

        def neighbour(step: int):
            i = index + step
            while 0 <= i < self.count() and not self.isTabVisible(i):
                i += step
            return self.tabData(i) if 0 <= i < self.count() else None

        left, right = neighbour(-1), neighbour(1)
        heads = _header_group(left)
        if heads is not None:
            return heads
        before = self._groups.get(left, "") if isinstance(left, str) else ""
        after = self._groups.get(right, "") if isinstance(right, str) else ""
        if before and (before == after or before == mine):
            return before
        return ""

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
        order = [b for b in blocks if b is not moving]
        # A block with nothing showing — canvas tabs folded under the Model
        # tab, or any group's pages once they are on a row of their own —
        # **keeps its place**. It used to be swept to the end, on the
        # grounds that a drag can't be aimed at something invisible; but a
        # drag is not aimed at it, it is aimed *past* it, and a page nobody
        # touched has no business moving. With a second row that stopped
        # being a corner case: every grouped page is off the top row, so
        # every header drag rewrote the order behind them.
        at = last = None
        for n, block in enumerate(order):
            if block[2].isNull():
                continue
            if at is None and block[2].center().x() > x:
                at = n
            last = n
        if at is None:
            at = len(order) if last is None else last + 1
        order.insert(at, moving)
        return [p for b in order for p in b[1]]

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
        reads as one either way.

        A section made now settles its Automatic colour when it is made
        (`MainWindow._set_page_group`), so the middle branch is what a
        project saved before that still reaches — and only until somebody
        gives the group a colour of its own.
        """
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
        self.bar_changed.emit()

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
            self.bar_changed.emit()

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
        if page_id == MODEL_PAGE:
            page_id = None      # the row's name for "the model canvas"
        if self._second_row:
            # reached from a Go to page button, the tab list or the row
            # itself: open the group it is in, so the bar shows where the
            # window has just gone — and close the row for a page in no
            # group, since there is then no group being looked at.
            self.set_open_group(self._group_of(page_id))
        index = self._model_index() if page_id is None else self._index_of_page(page_id)
        if index >= 0:
            if not self._second_row:
                # a page in a folded group comes out to be looked at
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
            if data is not None and data == self._floating:
                continue    # Qt is drawing it under the pointer
            group = _header_group(data)
            if group is not None:
                if group != self._dragged_header():
                    self._paint_header(painter, i, group)
                # else: drawn last, where the pointer has it
                continue
            option = QStyleOptionTab()
            self.initStyleOption(option, i)
            painter.drawControl(QStyle.CE_TabBarTabShape, option)
            if self._is_model(i) and self._model_lit():
                # The Model tab heads the canvases, but it is a real tab
                # rather than one of the header tabs _paint_header draws —
                # so it has to be filled here to say it is the open one,
                # the same way a group's header says it. In the accent,
                # which is the colour the row below draws its line in.
                # composited rather than laid on at full strength: the
                # accent is a bright colour where a group's own is dark,
                # and an open Model tab twice as loud as an open group
                # would be saying something louder than "this one"
                painter.fillRect(
                    self.tabRect(i).adjusted(1, 2, -1, 0),
                    theme.tint(self.palette().color(self.backgroundRole()),
                               theme.SELECTION_OUTLINE.name(),
                               theme.TINT_STRONG))
            tint = theme.page_tint(
                self._colors.get(data),
                theme.TINT_STRONG if i == self.currentIndex()
                else theme.TINT_SOFT)
            if tint is not None:
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
        self._paint_dragged_header(painter)
        self._paint_caret(painter)

    def set_drop_caret(self, x) -> None:
        """Mark where a page dragged off the second row would land, `x`
        being on this bar — or take the mark away, with None.

        Snapped to the gap it would take rather than drawn under the
        pointer: the gap is the answer, and a line through the middle of a
        tab asks which side of it was meant.
        """
        at = None if x is None else self._caret_at(int(x))
        if at == self._caret:
            return
        self._caret = at
        self.update()

    def _caret_at(self, x: int) -> int:
        """The gap between the tabs on show that `x` falls in, as an edge
        to draw on. Past the last one it is that tab's far edge; before the
        first it is the Model tab's, since nothing lands in front of that."""
        last = None
        for i in range(self._model_index() + 1, self._plus_index()):
            if not self.isTabVisible(i):
                continue
            rect = self.tabRect(i)
            if rect.center().x() > x:
                return rect.left()
            last = rect
        if last is not None:
            return last.right()
        return self.tabRect(self._model_index()).right()

    def _paint_caret(self, painter) -> None:
        if self._caret is None:
            return
        painter.fillRect(QRect(self._caret - 1, 2, 3, self.height() - 2),
                         theme.SELECTION_OUTLINE)

    def _dragged_header(self) -> Optional[str]:
        """The group whose header is being dragged right now, if one is."""
        drag = self._header_drag
        return drag["group"] if drag is not None and drag["moving"] else None

    def _paint_dragged_header(self, painter) -> None:
        """The header being dragged, drawn where the pointer has it.

        A header is moved by a drag of our own rather than Qt's — it is
        not a tab Qt should make current — so nothing was making it
        follow the pointer: it stayed in its slot while the bar reordered
        around it, and the only sign a drag was happening was the other
        groups jumping. A page tab has slid under the pointer since Qt
        wrote `QTabBar`, and a header is dragged the same way, so it
        should look the same way (Dan).

        Drawn last so it passes over its neighbours, like Qt's own
        floating tab — and drawn by `_paint_header`, so a dragged header
        is the same header, not a second drawing of one to keep in step.
        """
        group = self._dragged_header()
        if group is None:
            return
        index = next((i for i in range(self.count())
                      if _header_group(self.tabData(i)) == group), -1)
        if index < 0 or not self.isTabVisible(index):
            return
        self._paint_header(painter, index, group,
                           self._header_float_rect(index))

    def _header_float_rect(self, index: int) -> QRect:
        """Where a dragged header is drawn: held by the point it was
        picked up by, and kept on the bar, as Qt keeps a dragged tab."""
        rect = self.tabRect(index)
        drag = self._header_drag
        left = max(0, min(drag["at"] - drag["grab"],
                          self.width() - rect.width()))
        return QRect(left, rect.top(), rect.width(), rect.height())

    def _paint_header(self, painter, index: int, group: str,
                      rect: Optional[QRect] = None) -> None:
        """A group's header, muted the way a coloured tab is: the group's
        colour laid over it at the strength a current tab gets, the name in
        the tabs' own text colour on top — so a loud pick comes out calm,
        and no pale one can make the name hard to read — and the section's
        line beneath.

        `rect` overrides where it goes, which is how a dragged one is put
        under the pointer instead of in its slot.
        """
        floating = rect is not None
        if rect is None:
            rect = self.tabRect(index)
        painter.save()
        if floating:
            # Passing *over* its neighbours rather than sitting on the
            # bar, so it needs ground of its own: a header is filled with
            # a tone of its colour, and a tone is see-through — the tab
            # underneath read straight through the one being dragged.
            painter.fillRect(rect, self.palette().color(
                self.backgroundRole()))
        lit = self._header_lit(group)
        block = self._group_color(group)
        # The open header is filled *solid*; every other header is the
        # usual wash. Opacity, not strength or hue: one group has to be
        # picked out of a row of them whose colours are all different, and
        # a saturated green at half strength still shouts louder than a
        # blue at full — so trying to say it by tinting harder says
        # nothing. Filled against washed is the same difference whatever
        # the colours are.
        # Every header is filled with its own colour. With a row below,
        # the open one is filled *solid* and the rest are a tone of theirs
        # — the difference is the same whatever the colours are, which
        # tinting harder could never manage: a saturated green at half
        # strength still shouts louder than a blue at full.
        block.setAlphaF(theme.TINT_STRONG if not self._second_row
                        else (1.0 if lit else theme.TINT_SOFT))
        painter.fillRect(rect.adjusted(1, 2, -1, 0), block)
        if group == self._drop_hint:
            # a page tab is being dragged in: outline the section it joins
            painter.setPen(self._group_color(group))
            painter.drawRect(rect.adjusted(1, 2, -2, -1))
        font = QFont(self.font())
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(self.palette().color(QPalette.WindowText))
        # Centred, like every other tab's label. It used to be pinned to
        # the left, which only reads as deliberate when the tab is snug
        # round the name — with any slack at all the name sits left and
        # the gap piles up after it.
        painter.drawText(rect, Qt.AlignCenter, self.tabText(index))
        if not self._second_row:
            # the line under a header continues under its run of tabs, and
            # is what makes the run read as a section. With a row below
            # there is no run to underline — the fill says the colour.
            painter.fillRect(QRect(rect.left(), rect.bottom() - 1,
                                   rect.width(), 2),
                             self._muted_group_color(group))
        painter.restore()

    def _model_lit(self) -> bool:
        """Whether the Model tab is drawn as the open one — it heads the
        canvas tabs, and with a row below they are on it."""
        return (self._second_row and self._open_group == CANVASES
                and bool(self._canvas_tabs()))

    def _header_lit(self, group: str) -> bool:
        """Whether a header is drawn lit.

        With a row below, only the open one is: the headers are a row of
        switches and one of them is on, which is the whole of what the
        chevrons used to say — and a highlight is what a person actually
        looks at to find the group they are in. On one row they are all
        lit, because there the run of tabs beneath each says the rest.
        """
        return not self._second_row or group == self._open_group

    def _muted_group_color(self, group: str) -> QColor:
        """The group's colour as a solid line can show it: laid over the
        bar at the current tab's strength. Read at paint time, like the
        tabs' tint, so Settings ▸ Canvas reaches it without a restart."""
        return theme.tint(self.palette().color(self.backgroundRole()),
                          self._group_color(group).name(), theme.TINT_STRONG)

    def _bold_extra(self, text: str) -> int:
        """What this text costs in bold over the regular face the style
        measured it in.

        Measured, not allowed for. A flat allowance is wrong for every
        string but one: bold costs about 2px on `Sales  2` and nearly 10
        on a long name, so a fixed 12 left a short header padded out with
        white space on the right — where all of it lands, the name being
        drawn from the left — while a long one had none to spare.
        """
        bold = QFont(self.font())
        bold.setBold(True)
        return max(0, QFontMetrics(bold).horizontalAdvance(text)
                   - QFontMetrics(self.font()).horizontalAdvance(text))

    def tabSizeHint(self, index: int):
        size = super().tabSizeHint(index)
        if _header_group(self.tabData(index)) is not None:
            # painted bold, which the style measured as regular. Only the
            # difference is added, so a header carries the same padding
            # round its name as every other tab on the bar.
            size.setWidth(size.width() + self._bold_extra(self.tabText(index)))
        return size

    # ------------------------------------------------------------ gestures

    def _on_current_changed(self, index: int) -> None:
        if self._syncing or index < 0:
            return
        self._apply_folds()
        if self._dragged is None:
            # not while a press is in flight — see _follow_page_with_the_row
            self._follow_page_with_the_row()
        self.current_page_changed.emit(self.current_page_id())

    def _follow_page_with_the_row(self) -> None:
        """Put the second row on the group of the page being looked at —
        or take the row away, when that page is in no group.

        Clicking a tab on the top row never comes through `select_page`:
        Qt makes it current and the window hears about it afterwards. So
        both ways of arriving at a page end up here.

        Only a *page* moves the row. Clicking a header opens its group
        without changing the page, and a header is never the current tab,
        so it never reaches here.

        Called at the **end of a gesture**, not the moment a tab becomes
        current. Qt makes a tab current on the *press*, and a press on a
        page in no group may yet turn into a drag onto the row — closing
        the row there would pull it out from under the drag that was
        aiming at it.
        """
        if self._second_row:
            self.set_open_group(self._group_of(self.current_page_id()))

    def _on_tab_moved(self, from_index: int, to_index: int) -> None:
        if self._syncing:
            return
        self._enforce_pinned()
        self._enforce_canvas_run()
        self._reorder_pending = True
        self._show_drop_hint()

    def _show_drop_hint(self, x: Optional[int] = None) -> None:
        """Light the header of the group a dragged tab would join, so where
        a drop puts it is seen before letting go. Nothing is lit for a tab
        staying in its group, or leaving one for none."""
        page_id = self._dragged
        hint = None
        if (page_id is not None and not self._handing_over
                and (self._reorder_pending or x is not None)):
            group = self._landing_group(page_id, x)
            if group and group != self._groups.get(page_id, ""):
                hint = group
        if hint != self._drop_hint:
            self._drop_hint = hint
            self.update()

    def _enforce_canvas_run(self) -> None:
        """Canvas tabs stay together, right after the Model tab that heads
        them (G12/G13).

        A drag reorders them among themselves: one dragged out of the run is
        shoved back into it, and a page dragged into the run lands past it.
        The same "put it back as it happens" the pinned tabs get, for the
        same reason — the bar is telling you what belongs to what, and a tab
        that can wander says the opposite.

        The tab being dragged right now is let go of, or a canvas tab could
        never be dragged into a group: it would be shoved back into the run
        the moment it left it. Where it ends up is settled on release, by
        the group it landed in — and if that is none, `_with_canvas_run`
        puts it back in the run there.
        """
        canvases = [self.tabData(i) for i in self._canvas_tabs()
                    if self.tabData(i) != self._dragged]
        if not canvases:
            return
        self._syncing = True
        try:
            for target, page_id in enumerate(canvases,
                                             start=self._model_index() + 1):
                index = self._index_of_page(page_id)
                if index >= 0 and index != target:
                    self.moveTab(index, target)
        finally:
            self._syncing = False

    def _with_canvas_run(self, order: list, page_id=None,
                         group=None) -> list:
        """`order` with the canvas tab this drag was carrying back in the
        run the Model tab heads, if that is where it now belongs.

        The Model tab's canvases sit right behind it, so a canvas tab
        dragged out of a group is the Model tab's again and goes back into
        the run wherever on the bar it was let go of. One dragged *into* a
        group is that group's and stays where it was dropped. `group` is
        what this drag has just decided, which the mirror cannot know until
        the window answers.

        Only the dragged tab moves. Putting every stray canvas tab back in
        the run would be the bar tidying something nobody touched, on every
        drag — and the order a drag asks for should hold no more than the
        drag did.
        """
        if page_id is None or self._kinds.get(page_id) != "canvas":
            return list(order)
        mine = group if group is not None else self._groups.get(page_id, "")
        if mine:
            return list(order)
        rest = [pid for pid in order if pid != page_id]
        at = 0
        while at < len(rest) and self._heads_model(rest[at]):
            at += 1
        rest.insert(at, page_id)
        return rest

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

    def _note_floating(self, event) -> None:
        """Take note once Qt has picked the pressed tab up.

        **Qt draws a dragged tab itself**, as a child widget holding a
        pixmap of it (`QMovableTabWidget`), and its own `paintEvent`
        answers by *not* drawing that tab in the bar — the floating copy
        is the tab. A bar that paints its own tabs has to do the same, or
        the tab is on the bar twice: once under the pointer and once, left
        behind, in the slot it is being dragged out of.

        Qt starts that at `startDragDistance` past the press, so this
        asks the same question in the same way rather than guessing from
        the first swap — a tab slides some way before it passes a
        neighbour, and the ghost was there for all of it.

        **Known limit:** Qt grabs that pixmap by asking the *style* for a
        whole `CE_TabBarTab`, which is the one path that misses this
        painting — so a page's colour is not on the tab while it is off
        the ground. Two ways round it were tried and both are worse. A
        `QProxyStyle` on the bar never runs: with the application
        stylesheet on, `bar.style()` is a `QStyleSheetStyle` that does not
        hand `CE_TabBarTab` down — and a proxy *takes ownership* of the
        style it is handed, so `QProxyStyle(bar.style())` makes a tab bar
        the owner of the whole application's style and segfaults when the
        bar goes. Drawing the floating tab here instead, with Qt's copy
        hidden, puts it in the right place but not its label: under the
        stylesheet `CE_TabBarTabLabel` lays the text out from the tab's
        own geometry rather than from the rect it is given. A tab that
        travels correctly and says what it is beats a tinted one that
        does neither.
        """
        if self._press_at is None or self._floating is not None:
            return
        moved = (event.position().toPoint() - self._press_at).manhattanLength()
        if moved > QApplication.startDragDistance():
            self._floating = self._dragged
            self._float_child = qt_floating_tab(self)
            if self._float_child is not None:
                self._float_offset = (self._float_child.x()
                                      - event.position().toPoint().x())
            self.update()

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
        the page, which is how the first version of this still leaked.

        The focus is only half of it. This bar runs along the top of the
        window, so its menus drop *over* the Library dock and the canvas,
        and the leftover event can be handed to one of those at a position
        genuinely inside it — which no geometric guard can tell from a
        right-click made there. So the moment the menu closed is recorded
        too, and those widgets refuse a context menu for an instant
        afterwards. See ui/menu_guard."""
        from .. import menu_guard
        self.setFocus(Qt.MouseFocusReason)
        show()
        self.setFocus(Qt.MouseFocusReason)
        menu_guard.menu_closed()

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
                where = event.position().toPoint()
                self._header_drag = {"group": group,
                                     "start": where,
                                     "moving": False,
                                     "order": self.page_order(),
                                     # so the header can slide under the
                                     # pointer, the way a tab does
                                     "grab": where.x() - self.tabRect(
                                         index).left(),
                                     "at": where.x()}
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
        # right-click on the Model tab: what it heads, and the fold — the
        # same answer a group header gives (G12/G13). Offered whether or
        # not it heads anything, because its menu now also makes a page.
        if event.button() == Qt.RightButton and index == self._model_index():
            where = event.globalPosition().toPoint()
            self._menu_with_the_focus(lambda: self._model_menu().exec(where))
            event.accept()
            return
        # right-click on the empty strip past the last tab: there is no tab
        # to talk about, so the menu is the one thing there is to do here —
        # and the one place the bar's own layout belongs on a menu
        if event.button() == Qt.RightButton and index < 0:
            self._show_add_menu(event.globalPosition().toPoint(), True)
            event.accept()
            return
        # With a second row the Model tab is a header like any other, and
        # *only* a header: the click opens its row and does nothing else,
        # the way clicking a group's header does. The model canvas is the
        # first thing on that row (see pages_in), so it is one of the
        # things the header holds rather than a special case of it.
        # Acted on at release, like every other header.
        self._model_press = (event.button() == Qt.LeftButton
                             and index == self._model_index()
                             and self._second_row
                             and bool(self._canvas_tabs()))
        if self._model_press:
            event.accept()
            return
        # one row: the chevron folds the canvas tabs away (G12/G13), and
        # the rest of the tab still means "show me the model canvas"
        if (event.button() == Qt.LeftButton and index == self._model_index()
                and not self._second_row
                and self._canvas_tabs()
                and self._model_chevron_rect().contains(
                    event.position().toPoint())):
            self.toggle_model_fold()
            event.accept()
            return
        # only page tabs are draggable; Model is pinned in place
        self._drag_locked = not self._is_page(index)
        self._dragged = (self.tabData(index)
                         if event.button() == Qt.LeftButton
                         and self._is_page(index) else None)
        self._press_at = (event.position().toPoint()
                          if self._dragged is not None else None)
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
                drag["at"] = pos.x()
                order = self._group_drop(drag["group"], pos.x())
                if order != self.page_order():
                    self.set_page_order(order)
                self.update()   # the header itself follows the pointer
            event.accept()
            return
        if self._drag_locked:
            event.accept()
            return
        super().mouseMoveEvent(event)
        if self._dragged is not None and event.buttons() & Qt.LeftButton:
            self._note_floating(event)
            keep_floating_tab_with(self._float_child, self,
                                   event.position().toPoint().x(),
                                   self._float_offset)
            # The row below first: a tab dragged down onto it is going
            # there, and lighting a header on the way would be this bar
            # answering a question the pointer has already left.
            self._handing_over = self._hand_over(self._dragged, event)
            # after Qt's own move, so the tabs are where this drag put them
            self._show_drop_hint(None if self._handing_over
                                 else event.position().toPoint().x())

    def mouseReleaseEvent(self, event) -> None:
        drag, self._header_drag = self._header_drag, None
        model_press, self._model_press = self._model_press, False
        if drag is not None:
            group = drag["group"]
            if drag["moving"]:
                # one reorder request, the same one a dragged page makes, so
                # the window keeps the groups whole and it undoes in one step
                self.unsetCursor()
                # Put the header back in its slot. Unconditionally, because
                # the drag is over either way: a drop that changed the order
                # is repainted by the reorder coming back from the window,
                # but one that came to nothing sends nothing — and the last
                # thing painted was the header under the pointer, so it sat
                # there, dropped where it was let go of instead of snapping
                # into its place (Dan).
                self.update()
                if self.page_order() != drag["order"]:
                    self.reorder_pages_requested.emit(self.page_order())
            elif self._second_row:
                # with a row below, the header is that row's switch — the
                # fold is what the *one-row* bar does instead
                self.toggle_open_group(group)
            else:
                self.set_group_folded(group, group not in self._folded)
            event.accept()
            return
        if model_press:
            self.toggle_open_group(CANVASES)
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self._drag_locked = False
        dragged, self._dragged = self._dragged, None
        self._press_at = None
        if self._floating is not None:
            self._floating = None
            self.update()
        if self._drop_hint is not None:
            self._drop_hint = None
            self.update()
        handing_over, self._handing_over = self._handing_over, False
        self._float_child = None
        if handing_over and self._hand_over(dragged, event, True):
            # the row took it: one request, and it was the row's. Qt will
            # have shuffled the tab about on the way down, so put the bar
            # back the way the window last left it and let the move that
            # is now in flight redraw it.
            self._reorder_pending = False
            self._rebuild_groups()
            event.accept()
            return
        over_header = (dragged is not None and self._landing_group(
            dragged, event.position().toPoint().x())
            != self._landing_group(dragged))
        if self._reorder_pending or over_header:
            # one request per drag, not one per swap Qt makes along the way
            self._reorder_pending = False
            group = (self._landing_group(dragged,
                                         event.position().toPoint().x())
                     if dragged is not None else None)
            order = self._with_canvas_run(self.page_order(), dragged, group)
            if group is not None and group != self._groups.get(dragged, ""):
                # dropped into a group, or out of its own: one request for
                # the place and the group both, so it is one undo step
                self.move_page_requested.emit(order, dragged, group)
            else:
                self.reorder_pages_requested.emit(order)
            # Qt drags a page straight past a header, which is not a page
            # and so moves in no order the window keeps — put them back
            self._rebuild_groups()
        # the gesture is over, whatever it was: now the row can follow
        self._follow_page_with_the_row()

    def drop_from_row(self, page_id: str, x: int) -> None:
        """A page dragged off the second row and dropped on this bar.

        Which is how a page **leaves** its group: the top row is where the
        pages in no group live, so putting one there is saying it is in
        none. It takes the place under the pointer, among the headers and
        loose pages already on the row — `_blocks` is what those are, so a
        page can be put down between two groups without landing inside
        either.
        """
        if page_id == MODEL_PAGE or self._index_of_page(page_id) < 0:
            return
        if not self._group_of(page_id):
            return      # already in no group: there is nothing to leave
        blocks = [[group, [p for p in pages if p != page_id], rect]
                  for group, pages, rect in self._blocks()]
        at = len(blocks)
        for n, block in enumerate(blocks):
            if not block[2].isNull() and block[2].center().x() > x:
                at = n
                break
        blocks.insert(at, [None, [page_id], QRect()])
        order = [p for block in blocks for p in block[1]]
        self.move_page_requested.emit(
            self._with_canvas_run(order, page_id, ""), page_id, "")

    def drop_into_group(self, page_id: str, group: str, at: int) -> None:
        """A page dragged off this bar and dropped on the second row: it
        joins the group that row is showing, `at` places along it.

        The group keeps its place on the bar — its pages go back where its
        pages were, one longer — so a page joining Sales does not drag
        Sales anywhere.
        """
        if not group or group == CANVASES or self._index_of_page(page_id) < 0:
            return
        if self._group_of(page_id) == group:
            return
        members = [p for p in self.pages_in(group)
                   if p not in (MODEL_PAGE, page_id)]
        members.insert(max(0, min(int(at), len(members))), page_id)
        order: list = []
        placed = False
        for other in self.page_order():
            if other == page_id:
                continue
            if self._group_of(other) == group:
                if not placed:
                    order.extend(members)
                    placed = True
                continue
            order.append(other)
        if not placed:
            order.extend(members)
        self.move_page_requested.emit(
            self._with_canvas_run(order, page_id, group), page_id, group)

    def _hand_over(self, page_id, event, dropped: bool = False) -> bool:
        """Ask the host whether the second row is taking this drag."""
        if self.handover is None or not page_id:
            return False
        return bool(self.handover(page_id,
                                  event.globalPosition().toPoint(), dropped))

    def _show_add_menu(self, global_pos, view_options: bool = False) -> None:
        """"+" opens its menu on press like every other menu on this bar, so
        it goes through the same guard as the rest: the focus held either
        side of it, and the moment it closed recorded for whatever it was
        covering."""
        menu, choices = self._add_menu(view_options)
        chosen = None

        def show() -> None:
            nonlocal chosen
            chosen = menu.exec(global_pos)

        self._menu_with_the_focus(show)
        if chosen in choices:
            self.add_page_requested.emit(choices[chosen])

    def _add_menu(self, view_options: bool = False) -> tuple:
        """"+" asks what kind of page. A menu rather than buttons: the strip
        is a tab bar, and dashboards stay the one-click-away default by being
        first. A model canvas comes last, after a line — another view of the
        flow for whoever builds it (G12), not a page for anyone reading it.

        Built apart from showing it, like the tab menu, so what is on it can
        be asserted without an exec() that would block the suite."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        choices = {}
        for label, kind in NEW_PAGE_KINDS:
            if label is None:
                menu.addSeparator()
                continue
            choices[menu.addAction(label)] = kind
        if view_options:
            # only on the strip's own menu: "+" means *add a page*, and how
            # the bar is laid out is not one of the kinds it offers
            self._add_row_toggle(menu)
        return menu, choices

    def _add_row_toggle(self, menu: QMenu) -> None:
        """**Pages on a second row**, on the menus of the bar itself.

        The same switch as Settings ▸ General ▸ Grouped pages, put where
        you are when you want it: the thing you are looking at when you
        decide the bar should be one row or two is the bar.
        """
        menu.addSeparator()
        action = menu.addAction("Pages on a second row")
        action.setCheckable(True)
        action.setChecked(self._second_row)
        action.setToolTip(
            "Group headers on the top row, the open group's pages beneath")
        action.toggled.connect(self.second_row_requested.emit)

    def _new_page_submenu(self, parent: QMenu) -> QMenu:
        """**New ▸** on every menu the bar opens.

        The same three kinds "+" offers, reachable from wherever the
        pointer already is — "+" lives at one end of a strip that can be
        scrolled, and the answer to "how do I add a page here" should not
        be "go and find the button".

        Parented to the menu it is put on: a submenu only Python holds is
        deleted when this returns, leaving a dead entry behind — the same
        trap `_group_submenu` names.
        """
        sub = QMenu("New", parent)
        for label, kind in NEW_PAGE_KINDS:
            if label is None:
                sub.addSeparator()
                continue
            sub.addAction(label).triggered.connect(
                lambda _checked=False, kind=kind:
                self.add_page_requested.emit(kind))
        return sub

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
        # New first, then a line: making a page is what a right-click on a
        # tab bar is for in every other application, and the entries below
        # are all about the one tab under the pointer
        menu.addMenu(self._new_page_submenu(menu))
        menu.addSeparator()
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
        # "Close Tab" only where closing is all it does. A canvas of its own
        # takes its nodes with it, which is a delete and says so.
        view_tab = canvas_tab and self.canvas_tab_is_view(page_id)
        del_action = QAction("Close Tab" if view_tab else "Delete", self)
        if view_tab:
            del_action.setToolTip(
                "Close this tab. The frame and everything in it stay on "
                "the canvas.")
        elif canvas_tab:
            del_action.setToolTip(
                "Delete this canvas and the nodes on it. Undo brings them "
                "back.")
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
        # A canvas tab is offered a group like any other page. The Model
        # tab is its header only while nothing else is (see _canvas_tabs):
        # put it in Sales and it is Sales's, which is how a model built for
        # one part of a project is filed with the pages for that part.
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

    def _group_page_ids(self, group: str) -> list:
        """The pages of a group, in bar order."""
        return [self.tabData(i) for i in range(self.count())
                if self._is_page(i)
                and self._groups.get(self.tabData(i), "") == group]

    def _add_page_entries(self, menu: QMenu, page_ids: list) -> None:
        """List pages in a menu, the current one ticked — the same entries
        the tab list builds, so picking a page is one gesture wherever the
        list was opened from."""
        current = self.current_page_id()
        for page_id in page_ids:
            index = self._index_of_page(page_id)
            if index < 0:
                continue
            action = menu.addAction(self.tabText(index))
            action.setCheckable(True)
            action.setChecked(page_id == current)
            # by id, not index: the list is only read when it is picked from
            action.triggered.connect(
                lambda _checked=False, pid=page_id: self.select_page(pid))

    def _group_menu(self, group: str) -> QMenu:
        """A header's own menu: what is in the group, then fold, rename or
        ungroup.

        The pages come first because a folded section's whole point is not
        having to open it — right-click, read the list, pick one, and
        `select_page` brings that one out to be looked at.
        """
        menu = QMenu(self)
        if not self._second_row:
            # With a row below, both of these are answers to questions the
            # bar is no longer asking: the pages are on show a row down
            # rather than needing to be picked out of a list, and there is
            # nothing to fold — the row is not a fold and does not shut.
            self._add_page_entries(menu, self._group_page_ids(group))
            if not menu.isEmpty():
                menu.addSeparator()
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
        menu.addSeparator()
        menu.addMenu(self._new_page_submenu(menu))
        self._add_row_toggle(menu)
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
