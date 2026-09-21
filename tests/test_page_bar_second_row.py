"""A group's pages on a row of their own (0.1.15 #12).

The bar puts a group's pages in a run behind its header, all on one strip.
Behind a setting, the headers keep the top row to themselves and the pages
of whichever group is open appear on a row beneath it — the shape of a menu
bar, so the top row stays the same handful of names however many pages a
project grows.

The trap this file exists to hold down: Qt moves the selection on when the
*current* tab is hidden, which is exactly what closing a group does. A page
must not change under the user because they folded the bar.
"""
import pytest
from PySide6.QtCore import QPoint, QRect, QSettings, Qt
from flograph.core import NodeRegistry, Page
from flograph.ui import mainwindow as mod
from flograph.ui.dashboard import PageBarHost, PageTabBar
from flograph.ui.dashboard.page_bar import CANVASES, MODEL_PAGE


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def bar(qtbot):
    """A bar with two Sales pages, one ungrouped page and a canvas tab."""
    widget = PageTabBar()
    host = PageBarHost(widget)
    qtbot.addWidget(host)
    for page in (Page(id="p1", title="Sales EU"),
                 Page(id="p2", title="Sales US"),
                 Page(id="p3", title="Ops"),
                 Page(id="c1", title="Flow", kind="canvas")):
        widget.add_page_tab(page)
    widget.set_page_group("p1", "Sales")
    widget.set_page_group("p2", "Sales")
    widget.host = host
    return widget


def top_row(bar) -> list:
    """The tabs actually on the bar, by their text."""
    return [bar.tabText(i) for i in range(bar.count())
            if bar.isTabVisible(i)]


class TestTheTopRow:
    def test_one_row_until_it_is_asked_for(self, bar):
        assert "Sales EU" in top_row(bar)

    def test_a_group_s_pages_leave_it(self, bar):
        bar.set_second_row(True)
        assert "Sales EU" not in top_row(bar)
        assert "Sales US" not in top_row(bar)

    def test_and_stay_off_it_while_the_group_is_open(self, bar):
        """Open means "on the row below", not "in both places"."""
        bar.set_second_row(True)
        bar.set_open_group("Sales")
        assert "Sales EU" not in top_row(bar)

    def test_the_header_stays(self, bar):
        bar.set_second_row(True)
        assert any(text.endswith("Sales  2") for text in top_row(bar))

    def test_a_page_in_no_group_stays_too(self, bar):
        bar.set_second_row(True)
        assert "Ops" in top_row(bar)

    def test_no_chevrons_on_the_headers(self, bar):
        """They said "this folds". With a row below, the highlight says
        which group is open, which is what people actually look at."""
        bar.set_second_row(True)
        assert not any("▸" in text or "▾" in text for text in top_row(bar))

    def test_the_open_group_is_the_lit_one(self, bar):
        bar.add_page_tab(Page(id="p5", title="Costs"))
        bar.set_page_group("p5", "Finance")
        bar.set_second_row(True)
        bar.set_open_group("Sales")
        assert bar._header_lit("Sales") is True
        assert bar._header_lit("Finance") is False

    def test_the_model_tab_lights_up_with_its_canvases(self, bar):
        """It is a real tab rather than a header tab, so it is filled by
        the paint loop instead — but it has to say the same thing."""
        bar.set_second_row(True)
        bar.set_open_group("Sales")
        assert bar._model_lit() is False
        bar.set_open_group(CANVASES)
        assert bar._model_lit() is True

    def test_it_never_lights_up_with_no_canvases_to_head(self, bar):
        bar.remove_page_tab("c1")
        bar.set_second_row(True)
        bar.set_open_group(CANVASES)
        assert bar._model_lit() is False

    def test_on_one_row_every_header_is_lit(self, bar):
        """There the run of tabs under each says the rest."""
        assert bar._header_lit("Sales") is True

    def test_the_model_tab_counts_the_model_canvas_itself(self, bar):
        """One canvas tab, and the model canvas on the row with it."""
        bar.set_second_row(True)
        assert "Models  2" in top_row(bar)

    def test_and_counts_every_canvas_tab_with_it(self, bar):
        bar.add_page_tab(Page(id="c2", title="Second look", kind="canvas"))
        bar.set_second_row(True)
        assert "Models  3" in top_row(bar)

    def test_it_is_a_plain_tab_again_with_no_canvases_to_head(self, bar):
        bar.remove_page_tab("c1")
        bar.set_second_row(True)
        assert "Model" in top_row(bar)

    def test_turning_it_off_puts_them_all_back(self, bar):
        bar.set_second_row(True)
        bar.set_second_row(False)
        assert "Sales EU" in top_row(bar)
        assert "Flow" in top_row(bar)


class TestTheRowBelow:
    def test_a_group_is_open_from_the_start(self, bar):
        """There is no empty state to arrive in: the row is where a
        group's pages live, so one group is always open. The bar starts on
        the model canvas, so that is the group it opens."""
        bar.set_second_row(True)
        assert bar.open_group() == CANVASES

    def test_which_is_the_first_group_when_you_are_in_none(self, bar):
        bar.remove_page_tab("c1")      # nothing heading the model canvas
        bar.set_second_row(True)
        assert bar.open_group() == "Sales"
        assert bar.host.row.page_ids() == ["p1", "p2"]

    def test_it_opens_the_group_you_are_already_in(self, bar):
        bar.add_page_tab(Page(id="p5", title="Costs"))
        bar.set_page_group("p5", "Finance")
        bar.select_page("p5")
        bar.set_second_row(True)
        assert bar.open_group() == "Finance"

    def test_opening_a_group_fills_it_in_bar_order(self, bar):
        bar.set_second_row(True)
        bar.set_open_group("Sales")
        assert bar.host.row.page_ids() == ["p1", "p2"]

    def test_one_group_is_open_at_a_time(self, bar):
        bar.set_second_row(True)
        bar.set_open_group("Sales")
        bar.set_open_group(CANVASES)
        assert bar.open_group() == CANVASES
        assert bar.host.row.page_ids() == [MODEL_PAGE, "c1"]

    def test_the_open_header_cannot_be_clicked_shut(self, bar):
        """A bar that can be left with its pages nowhere is a state
        nobody wants and everybody can reach by accident."""
        bar.set_second_row(True)
        bar.toggle_open_group("Sales")
        bar.toggle_open_group("Sales")
        assert bar.open_group() == "Sales"

    def test_the_row_stays_up(self, bar):
        bar.host.show()
        bar.set_second_row(True)
        assert bar.host.row.isVisible()
        bar.toggle_open_group("Sales")
        assert bar.host.row.isVisible()

    def test_a_project_with_no_groups_has_no_row(self, bar, qtbot):
        """Nothing to show is not the same as something collapsed."""
        plain = PageTabBar()
        host = PageBarHost(plain)
        qtbot.addWidget(host)
        host.show()
        plain.add_page_tab(Page(id="only", title="One page"))
        plain.set_second_row(True)
        assert plain.open_group() == ""
        assert not host.row.isVisible()

    def test_the_row_moves_on_when_its_group_empties(self, bar):
        """The last page leaves Sales, so the row takes another group
        rather than sitting there with nothing in it."""
        bar.set_second_row(True)
        bar.set_open_group("Sales")
        bar.remove_page_tab("p1")
        bar.remove_page_tab("p2")
        assert bar.open_group() == CANVASES
        assert bar.host.row.page_ids() == [MODEL_PAGE, "c1"]

    def test_there_is_no_row_at_all_without_the_setting(self, bar):
        bar.host.show()
        bar.set_open_group("Sales")
        assert bar.open_group() == ""
        assert not bar.host.row.isVisible()

    def test_a_renamed_page_is_renamed_on_it(self, bar):
        bar.set_second_row(True)
        bar.set_open_group("Sales")
        bar.set_page_title("p1", "Sales EMEA")
        assert bar.host.row.tabText(0) == "Sales EMEA"

    def test_a_page_added_to_the_open_group_arrives_on_it(self, bar):
        bar.set_second_row(True)
        bar.set_open_group("Sales")
        bar.add_page_tab(Page(id="p4", title="Sales APAC"))
        bar.set_page_group("p4", "Sales")
        assert "p4" in bar.host.row.page_ids()

    def test_a_deleted_page_leaves_it(self, bar):
        bar.set_second_row(True)
        bar.set_open_group("Sales")
        bar.remove_page_tab("p2")
        assert bar.host.row.page_ids() == ["p1"]


class TestWhatIsShowing:
    """The half that can lose somebody's place."""

    def test_selecting_a_page_opens_the_group_it_is_in(self, bar):
        bar.set_second_row(True)
        bar.select_page("p2")
        assert bar.open_group() == "Sales"

    def test_it_is_current_although_its_tab_is_off_the_row(self, bar):
        """Qt is perfectly happy to keep a hidden tab current — it is only
        *hiding the current tab* that moves the selection on."""
        bar.set_second_row(True)
        bar.select_page("p2")
        assert bar.current_page_id() == "p2"
        assert "Sales US" not in top_row(bar)

    def test_closing_the_group_does_not_change_the_page(self, bar):
        """The trap. Hiding the current tab makes Qt select the next one,
        so the page would change under the user just because they shut a
        group."""
        bar.set_second_row(True)
        bar.select_page("p2")
        bar.set_open_group("")
        assert bar.current_page_id() == "p2"

    def test_nor_does_turning_the_row_on(self, bar):
        bar.select_page("p2")
        bar.set_second_row(True)
        assert bar.current_page_id() == "p2"

    def test_turning_it_on_opens_the_group_you_are_in(self, bar):
        bar.select_page("p1")
        bar.set_second_row(True)
        assert bar.open_group() == "Sales"

    def test_the_row_highlights_the_page_that_is_showing(self, bar):
        bar.set_second_row(True)
        bar.select_page("p2")
        assert bar.host.row.current_page_id() == "p2"

    def test_clicking_the_row_selects_that_page(self, bar):
        bar.set_second_row(True)
        bar.set_open_group("Sales")
        bar.host.row.page_clicked.emit("p2")
        assert bar.current_page_id() == "p2"


class TestClickingIt:
    """Through the mouse, because the methods being right is not the same
    thing as the bar being right."""

    def test_clicking_a_group_header_opens_its_row(self, bar):
        bar.set_second_row(True)
        _click(bar, _index_of(bar, "Sales"))
        assert bar.open_group() == "Sales"
        assert bar.host.row.page_ids() == ["p1", "p2"]

    def test_clicking_it_again_leaves_it_open(self, bar):
        bar.set_second_row(True)
        _click(bar, _index_of(bar, "Sales"))
        _click(bar, _index_of(bar, "Sales"))
        assert bar.open_group() == "Sales"

    def test_clicking_another_swaps_which_is_open(self, bar):
        bar.add_page_tab(Page(id="p5", title="Costs"))
        bar.set_page_group("p5", "Finance")
        bar.set_second_row(True)
        _click(bar, _index_of(bar, "Sales"))
        _click(bar, _index_of(bar, "Finance"))
        assert bar.open_group() == "Finance"

    def test_clicking_model_opens_the_canvases(self, bar):
        bar.set_second_row(True)
        bar.set_open_group("Sales")
        _click(bar, bar._model_index())
        assert bar.open_group() == CANVASES
        assert bar.host.row.page_ids() == [MODEL_PAGE, "c1"]

    def test_and_changes_no_page_doing_it(self, bar):
        """It is a header and only a header here — the same as clicking
        Sales, which opens a row and moves nobody."""
        bar.set_second_row(True)
        bar.select_page("p1")
        _click(bar, bar._model_index())
        assert bar.current_page_id() == "p1"

    def test_the_model_canvas_is_reached_from_the_row(self, bar):
        """Which is the point of it being on there: the header stopped
        being a shortcut to it, so the row has to carry it."""
        bar.set_second_row(True)
        bar.select_page("p1")
        _click(bar, bar._model_index())
        bar.host.row.page_clicked.emit(MODEL_PAGE)
        assert bar.current_page_id() is None

    def test_and_the_row_marks_it_while_you_are_on_it(self, bar):
        bar.set_second_row(True)
        bar.select_page(None)
        assert bar.host.row.current_page_id() == MODEL_PAGE

    def test_a_header_click_folds_nothing_when_there_is_a_row(self, bar):
        """The fold is the one-row bar's way of tidying; with a row below
        it would be a second, invisible state on top of this one."""
        bar.set_second_row(True)
        _click(bar, _index_of(bar, "Sales"))
        assert bar.folded_groups() == set()

    def test_and_still_folds_when_there_is_not(self, bar):
        _click(bar, _index_of(bar, "Sales"))
        assert bar.is_group_folded("Sales")


class TestItsMenus:
    def test_a_row_tab_offers_the_page_s_own_menu(self, bar, monkeypatch):
        """Borrowed from the bar rather than built again, so the two can
        never drift apart."""
        asked = {}
        monkeypatch.setattr(bar, "_show_context_menu",
                            lambda index, page_id, where:
                            asked.update(page_id=page_id))
        bar.set_second_row(True)
        bar.set_open_group("Sales")
        bar.host.row.context_menu_requested.emit("p2", QPoint(0, 0))
        assert asked == {"page_id": "p2"}

    def test_a_header_still_moves_its_whole_group(self, bar):
        """A press on a header starts a group drag whether or not there is
        a second row — the row changes what a *click* does, not a drag."""
        bar.set_second_row(True)
        index = next(i for i in range(bar.count())
                     if bar.tabText(i).endswith("Sales  2"))
        rect = bar.tabRect(index)
        bar.mousePressEvent(_press(rect.center()))
        assert bar._header_drag is not None
        assert bar._header_drag["group"] == "Sales"


def _press(point):
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent, QPointF

    return QMouseEvent(QEvent.MouseButtonPress, QPointF(point), QPointF(point),
                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)


def _release(point):
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent, QPointF

    return QMouseEvent(QEvent.MouseButtonRelease, QPointF(point),
                       QPointF(point), Qt.LeftButton, Qt.NoButton,
                       Qt.NoModifier)


def _click(bar, index):
    """Press and release on a tab — the gesture, not the method behind it.

    Which is the whole point of these: the first cut of this feature had
    every method right and the header click still went to the fold, so
    clicking a group did nothing at all while Model worked.
    """
    point = bar.tabRect(index).center()
    bar.mousePressEvent(_press(point))
    bar.mouseReleaseEvent(_release(point))


def _index_of(bar, text):
    return next(i for i in range(bar.count()) if text in bar.tabText(i))


class TestTheSetting:
    @pytest.fixture
    def window(self, qtbot, registry):
        win = mod.MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def test_off_by_default(self, window):
        assert window.page_tabs_second_row is False
        assert window.page_bar.second_row() is False

    def test_turning_it_on_reaches_the_bar(self, window):
        window.set_page_tabs_second_row(True)
        assert window.page_bar.second_row() is True

    def test_it_is_remembered(self, window, qtbot, registry):
        window.set_page_tabs_second_row(True)
        assert window.settings.value("canvas/page_bar_second_row") is True
        second = mod.MainWindow(registry)
        second.confirm_close = False
        qtbot.addWidget(second)
        assert second.page_bar.second_row() is True

    def test_the_checkbox_drives_it(self, window):
        from PySide6.QtWidgets import QCheckBox

        from flograph.ui.settings_dialog import SettingsDialog

        dlg = SettingsDialog(window, window)
        check = dlg.findChild(QCheckBox, "page_bar_second_row_checkbox")
        assert check is not None and check.isChecked() is False
        check.setChecked(True)
        assert window.page_bar.second_row() is True

    def test_the_row_lives_with_the_bar(self, window):
        """Whatever edge the bar is on, its row is under it — which is what
        the host is for."""
        layout = window.centralWidget().layout()
        assert layout.itemAt(0).widget() is window.page_bar_host
        assert window.page_bar_host.bar is window.page_bar


def _drag_row(row, from_index, to_index):
    """A drag on the second row: Qt moves the tab, the release commits."""
    from PySide6.QtCore import QPointF

    row.moveTab(from_index, to_index)
    point = row.tabRect(to_index).center()
    row.mouseReleaseEvent(_release(point))


class TestDraggingOnTheRow:
    """A page's tab is here and nowhere else now, so this is where it is
    dragged into place."""

    def test_a_drag_reorders_the_group(self, bar, qtbot):
        bar.set_second_row(True)
        bar.set_open_group("Sales")
        with qtbot.waitSignal(bar.reorder_pages_requested) as blocker:
            _drag_row(bar.host.row, 0, 1)
        assert blocker.args[0][:2] == ["p2", "p1"]

    def test_and_leaves_the_rest_of_the_bar_where_it_was(self, bar, qtbot):
        """A group sits where it sat: only its own pages shuffle."""
        bar.set_second_row(True)
        bar.set_open_group("Sales")
        with qtbot.waitSignal(bar.reorder_pages_requested) as blocker:
            _drag_row(bar.host.row, 0, 1)
        assert blocker.args[0] == ["p2", "p1", "p3", "c1"]

    def test_a_drag_that_changes_nothing_asks_for_nothing(self, bar):
        bar.set_second_row(True)
        bar.set_open_group("Sales")
        asked = []
        bar.reorder_pages_requested.connect(asked.append)
        bar.host.row.mouseReleaseEvent(_release(QPoint(0, 0)))
        assert asked == []

    def test_the_model_canvas_cannot_be_dragged_off_the_front(self, bar):
        """It heads its row because the others are views of it."""
        bar.set_second_row(True)
        bar.set_open_group(CANVASES)
        asked = []
        bar.reorder_pages_requested.connect(asked.append)
        _drag_row(bar.host.row, 0, 1)
        assert asked == []
        assert bar.host.row.page_ids()[0] == MODEL_PAGE


class TestTheMenusInThisMode:
    def _texts(self, menu):
        return [action.text() for action in menu.actions()]

    def test_a_header_no_longer_offers_a_fold(self, bar):
        """There is nothing to fold: the row is not a fold and does not
        shut."""
        bar.set_second_row(True)
        texts = self._texts(bar._group_menu("Sales"))
        assert not any("Fold" in t or "Unfold" in t for t in texts)

    def test_nor_a_list_of_the_pages_it_is_already_showing(self, bar):
        bar.set_second_row(True)
        texts = self._texts(bar._group_menu("Sales"))
        assert "Sales EU" not in texts

    def test_it_still_renames_recolours_and_ungroups(self, bar):
        bar.set_second_row(True)
        texts = self._texts(bar._group_menu("Sales"))
        assert "Rename group…" in texts
        assert "Change colour…" in texts
        assert "Ungroup" in texts

    def test_one_row_keeps_both(self, bar):
        texts = self._texts(bar._group_menu("Sales"))
        assert "Fold away" in texts
        assert "Sales EU" in texts

    def test_the_model_menu_drops_its_fold_too(self, bar):
        bar.set_second_row(True)
        texts = self._texts(bar._model_menu())
        assert not any("canvases" in t for t in texts)

    def test_the_row_can_be_turned_on_from_the_bar_itself(self, bar, qtbot):
        """Settings has it too; the bar offers it because the bar is what
        you are looking at when you decide."""
        menu = bar._group_menu("Sales")
        action = next(a for a in menu.actions()
                      if a.text() == "Pages on a second row")
        assert action.isCheckable() and not action.isChecked()
        with qtbot.waitSignal(bar.second_row_requested) as blocker:
            action.setChecked(True)
        assert blocker.args == [True]

    def test_and_off_again_from_the_same_place(self, bar, qtbot):
        bar.set_second_row(True)
        menu = bar._model_menu()
        action = next(a for a in menu.actions()
                      if a.text() == "Pages on a second row")
        assert action.isChecked()
        with qtbot.waitSignal(bar.second_row_requested) as blocker:
            action.setChecked(False)
        assert blocker.args == [False]

    def test_the_empty_strip_offers_it_as_well(self, bar):
        menu, _ = bar._add_menu(view_options=True)
        assert "Pages on a second row" in self._texts(menu)

    def test_but_the_plus_button_does_not(self, bar):
        """"+" means add a page; how the bar is laid out is not a kind of
        page."""
        menu, _ = bar._add_menu()
        assert "Pages on a second row" not in self._texts(menu)

    def test_a_right_click_on_the_row_moves_nobody(self, bar, monkeypatch):
        """The menu is about that page, not a way of going to it."""
        monkeypatch.setattr(bar, "_show_context_menu", lambda *a: None)
        bar.set_second_row(True)
        bar.set_open_group("Sales")
        bar.select_page("p1")
        bar.host.row.context_menu_requested.emit("p2", QPoint(0, 0))
        assert bar.current_page_id() == "p1"


def _move(local, where):
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent, QPointF

    return QMouseEvent(QEvent.MouseMove, QPointF(local), QPointF(where),
                       Qt.NoButton, Qt.LeftButton, Qt.NoModifier)


def _release_at(local, where):
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent, QPointF

    return QMouseEvent(QEvent.MouseButtonRelease, QPointF(local),
                       QPointF(where), Qt.LeftButton, Qt.NoButton,
                       Qt.NoModifier)


def _drag_across(source, start, target, land):
    """Press on `source` at `start`, drag onto `target` at `land`, let go
    there — the gesture that moves a page between the two rows.

    Both points are on their own widget; the pointer is what crosses, since
    Qt keeps a dragged tab inside the bar it started in.
    """
    source.mousePressEvent(_press(start))
    where = target.mapToGlobal(land)
    source.mouseMoveEvent(_move(source.mapFromGlobal(where), where))
    source.mouseReleaseEvent(_release_at(source.mapFromGlobal(where), where))


def _gap(bar, index):
    """A point in the middle of a tab, as a place to drop next to."""
    return bar.tabRect(index).center()


@pytest.fixture
def rows(bar, qtbot):
    """The bar with its row up and Sales open, on screen — a drag between
    the rows is answered from where the tabs are, so they have to be
    somewhere.

    The canvas tab is put where the window keeps it, right behind the
    Model tab that heads it: any drag packs that run back together
    (`_enforce_canvas_run`), so a bar that starts out of order would have
    every drop below also shuffling a tab the drag never touched.
    """
    bar.set_page_order(["c1", "p1", "p2", "p3"])
    bar.set_second_row(True)
    bar.set_open_group("Sales")
    bar.host.resize(700, 70)
    bar.host.show()
    qtbot.waitExposed(bar.host)
    return bar.host


class TestDraggingBetweenTheRows:
    """The two rows are what a page's group *is* in this mode — the top row
    is the pages in no group, the row below is one group's. So dragging a
    tab from one to the other is how a page joins a group or leaves it."""

    def test_a_page_dragged_down_joins_the_open_group(self, rows, qtbot):
        with qtbot.waitSignal(rows.bar.move_page_requested) as blocker:
            _drag_across(rows.bar, _gap(rows.bar, _index_of(rows.bar, "Ops")),
                         rows.row, _gap(rows.row, 0))
        order, page_id, group = blocker.args
        assert (page_id, group) == ("p3", "Sales")
        assert order == ["c1", "p3", "p1", "p2"]

    def test_and_lands_where_it_is_let_go_of(self, rows, qtbot):
        with qtbot.waitSignal(rows.bar.move_page_requested) as blocker:
            _drag_across(rows.bar, _gap(rows.bar, _index_of(rows.bar, "Ops")),
                         rows.row, _gap(rows.row, 1))
        assert blocker.args[0] == ["c1", "p1", "p3", "p2"]

    def test_the_group_stays_where_it_was_on_the_bar(self, rows, qtbot):
        """A page joining Sales does not drag Sales anywhere."""
        rows.bar.add_page_tab(Page(id="p5", title="Costs"))
        rows.bar.set_page_group("p5", "Finance")
        with qtbot.waitSignal(rows.bar.move_page_requested) as blocker:
            _drag_across(rows.bar, _gap(rows.bar, _index_of(rows.bar, "Ops")),
                         rows.row, _gap(rows.row, 0))
        assert blocker.args[0] == ["c1", "p3", "p1", "p2", "p5"]

    def test_a_page_dragged_up_leaves_its_group(self, rows, qtbot):
        ops = rows.bar.tabRect(_index_of(rows.bar, "Ops"))
        from PySide6.QtCore import QPoint
        with qtbot.waitSignal(rows.bar.move_page_requested) as blocker:
            _drag_across(rows.row, _gap(rows.row, 0), rows.bar,
                         QPoint(ops.left() + 2, ops.center().y()))
        order, page_id, group = blocker.args
        assert (page_id, group) == ("p1", "")
        assert order.index("p1") < order.index("p3")

    def test_and_the_bar_is_not_also_reordered_by_it(self, rows):
        """One request per drag: the row took the gesture, so the bar's own
        reorder never goes out."""
        asked = []
        rows.bar.reorder_pages_requested.connect(asked.append)
        _drag_across(rows.bar, _gap(rows.bar, _index_of(rows.bar, "Ops")),
                     rows.row, _gap(rows.row, 0))
        assert asked == []

    def test_a_drag_that_stays_on_its_own_row_is_still_a_reorder(
            self, rows, qtbot):
        with qtbot.waitSignal(rows.bar.reorder_pages_requested):
            _drag_row(rows.row, 0, 1)

    def test_the_model_canvas_cannot_be_dragged_off_its_row(self, rows):
        """It is not a page — there is nothing to put on the bar."""
        rows.bar.set_open_group(CANVASES)
        asked = []
        rows.bar.move_page_requested.connect(
            lambda *a: asked.append(a))
        _drag_across(rows.row, _gap(rows.row, 0),
                     rows.bar, _gap(rows.bar, _index_of(rows.bar, "Ops")))
        assert asked == []

    def test_nothing_can_be_dragged_onto_the_canvases_row(self, rows):
        """A dashboard page dropped among the canvases would be saying it
        is a model, which it is not — so the row does not take it and the
        drag is the bar's own, as it was before."""
        rows.bar.set_open_group(CANVASES)
        taken = rows.onto_the_row(
            "p3", rows.row.mapToGlobal(_gap(rows.row, 1)), False)
        assert taken is False

    def test_the_row_marks_where_the_drop_would_land(self, rows):
        assert rows.row._caret is None
        rows.bar.mousePressEvent(
            _press(_gap(rows.bar, _index_of(rows.bar, "Ops"))))
        where = rows.row.mapToGlobal(_gap(rows.row, 1))
        rows.bar.mouseMoveEvent(_move(rows.bar.mapFromGlobal(where), where))
        assert rows.row._caret is not None

    def test_and_takes_the_mark_away_when_the_pointer_leaves(self, rows):
        rows.bar.mousePressEvent(
            _press(_gap(rows.bar, _index_of(rows.bar, "Ops"))))
        where = rows.row.mapToGlobal(_gap(rows.row, 1))
        rows.bar.mouseMoveEvent(_move(rows.bar.mapFromGlobal(where), where))
        back = rows.bar.mapToGlobal(_gap(rows.bar, _index_of(rows.bar, "Ops")))
        rows.bar.mouseMoveEvent(_move(rows.bar.mapFromGlobal(back), back))
        assert rows.row._caret is None

    def test_the_bar_marks_it_too_the_other_way_round(self, rows):
        rows.row.mousePressEvent(_press(_gap(rows.row, 0)))
        where = rows.bar.mapToGlobal(_gap(rows.bar, _index_of(rows.bar, "Ops")))
        rows.row.mouseMoveEvent(_move(rows.row.mapFromGlobal(where), where))
        assert rows.bar._caret is not None


class TestTheOrderADropAsksFor:
    """The arithmetic behind the gesture, which the drag alone cannot pin
    down: where in the whole bar's order a dropped page ends up."""

    def test_joining_a_group_puts_the_page_at_the_place_asked_for(
            self, bar, qtbot):
        bar.set_second_row(True)
        with qtbot.waitSignal(bar.move_page_requested) as blocker:
            bar.drop_into_group("p3", "Sales", 1)
        assert blocker.args[0] == ["p1", "p3", "p2", "c1"]

    def test_past_the_end_of_the_row_is_the_end_of_the_group(self, bar,
                                                             qtbot):
        bar.set_second_row(True)
        with qtbot.waitSignal(bar.move_page_requested) as blocker:
            bar.drop_into_group("p3", "Sales", 99)
        assert blocker.args[0] == ["p1", "p2", "p3", "c1"]

    def test_a_page_already_in_that_group_is_not_moved_by_it(self, bar):
        bar.set_second_row(True)
        asked = []
        bar.move_page_requested.connect(lambda *a: asked.append(a))
        bar.drop_into_group("p1", "Sales", 1)
        assert asked == []

    def test_leaving_a_group_lands_between_the_blocks_on_the_bar(
            self, bar, qtbot):
        """`Ops` is the only loose page; dropping past it puts the page
        after it rather than inside anything."""
        bar.set_second_row(True)
        ops = bar.tabRect(_index_of(bar, "Ops"))
        with qtbot.waitSignal(bar.move_page_requested) as blocker:
            bar.drop_from_row("p1", ops.right() + 20)
        order, page_id, group = blocker.args
        assert (page_id, group) == ("p1", "")
        assert order.index("p1") > order.index("p3")

    def test_a_page_in_no_group_has_nothing_to_leave(self, bar):
        bar.set_second_row(True)
        asked = []
        bar.move_page_requested.connect(lambda *a: asked.append(a))
        bar.drop_from_row("p3", 0)
        assert asked == []


class TestAModelInAGroup:
    """A canvas tab used to be the Model tab's and nothing else's: putting
    one in a group gave it two headers, and the two kept pulling it out of
    each other. Now the group has it outright, so a model built for one
    part of a project can be filed with that part's pages."""

    def test_a_canvas_tab_is_offered_a_group(self, bar):
        index = bar._index_of_page("c1")
        texts = [a.text() for a in bar._context_menu(index, "c1").actions()]
        assert "Group" in texts

    def test_and_the_model_tab_stops_counting_it(self, bar):
        bar.set_page_group("c1", "Sales")
        assert bar._canvas_tabs() == []

    def test_it_rides_that_group_s_row(self, bar):
        bar.set_page_group("c1", "Sales")
        bar.set_second_row(True)
        bar.set_open_group("Sales")
        assert bar.host.row.page_ids() == ["p1", "p2", "c1"]

    def test_and_not_the_canvases_row(self, bar):
        bar.set_page_group("c1", "Sales")
        bar.set_second_row(True)
        assert bar.pages_in(CANVASES) == [MODEL_PAGE]

    def test_with_no_canvases_left_the_model_tab_is_plain_again(self, bar):
        """It heads nothing, so it is not a header — there is no row to
        open and nothing to count."""
        bar.set_page_group("c1", "Sales")
        bar.set_second_row(True)
        assert "Model" in top_row(bar)
        assert bar._model_lit() is False

    def test_it_folds_with_its_group_and_not_with_the_model_tab(self, bar):
        bar.set_page_group("c1", "Sales")
        bar.toggle_model_fold()
        assert bar.isTabVisible(bar._index_of_page("c1"))
        bar.set_group_folded("Sales", True)
        assert not bar.isTabVisible(bar._index_of_page("c1"))

    def test_leaving_the_group_gives_it_back_to_the_model_tab(self, bar):
        bar.set_page_group("c1", "Sales")
        bar.set_page_group("c1", "")
        assert bar._canvas_tabs() == [bar._index_of_page("c1")]

    def test_a_drag_onto_a_header_puts_it_in_that_group(self, bar, qtbot):
        """On one row, where a canvas tab is on the bar to be dragged. The
        run it is dragged out of is enforced as the drag happens, so the
        tab being carried has to be let go of — otherwise it would be
        shoved back the moment it left the run and could never reach a
        group at all.

        With a second row there is no drag to make: the canvas tabs are on
        the Models row, not the bar. Its **Group ▸** is the way there, and
        the row borrows the bar's own page menu, so it is on both.
        """
        bar.host.resize(700, 70)
        bar.host.show()
        qtbot.waitExposed(bar.host)
        bar.mousePressEvent(_press(bar.tabRect(bar._index_of_page("c1")).center()))
        header = _index_of(bar, "Sales")
        bar.moveTab(bar._index_of_page("c1"), header + 1)
        with qtbot.waitSignal(bar.move_page_requested) as blocker:
            bar.mouseReleaseEvent(_release(bar.tabRect(header).center()))
        assert blocker.args[1:] == ["c1", "Sales"]

    def test_and_dragging_it_out_puts_it_back_behind_the_model_tab(self, bar):
        """Wherever on the bar it was let go of: it is the Model tab's
        again, and the Model tab's canvases sit right behind it."""
        bar.set_page_order(["c1", "p1", "p2", "p3"])
        bar.set_page_group("c1", "Sales")
        assert bar._with_canvas_run(["p1", "p2", "p3", "c1"], "c1", "") \
            == ["c1", "p1", "p2", "p3"]

    def test_but_one_dropped_into_a_group_stays_where_it_was_dropped(
            self, bar):
        assert bar._with_canvas_run(["p1", "c1", "p2", "p3"], "c1", "Sales") \
            == ["p1", "c1", "p2", "p3"]


class TestTheBarHoldsStill:
    """A relic of the headers, not of the row — but the row is what made
    it obvious, because in this mode clicking a header is what you do all
    day and every click rebuilds them."""

    @pytest.fixture
    def two_groups(self, bar, qtbot):
        bar.add_page_tab(Page(id="p5", title="Costs"))
        bar.set_page_group("p5", "Finance")
        bar.host.resize(700, 70)
        bar.host.show()
        qtbot.waitExposed(bar.host)
        bar.set_second_row(True)
        return bar

    def _widths(self, bar):
        return [(bar.tabText(i), bar.tabRect(i).width())
                for i in range(bar.count()) if bar.isTabVisible(i)]

    def test_a_header_is_measured_as_the_bold_text_it_is(self, two_groups):
        """`insertTab` works a tab's size out there and then, and
        `tabSizeHint` can only tell a header from a page by the data
        `insertTab` has not been handed yet. So a header went on the bar
        measured as regular text and grew by its padding at whatever
        relayout came next."""
        for name in ("Sales", "Finance"):
            index = _index_of(two_groups, name)
            assert two_groups.tabRect(index).width() \
                == two_groups.tabSizeHint(index).width()

    def test_opening_a_group_moves_no_tab_along_the_bar(self, two_groups):
        """Which is what the stale size looked like from the outside: a
        header grew mid-click and shunted everything to its right."""
        before = self._widths(two_groups)
        two_groups.set_open_group("Sales")
        assert self._widths(two_groups) == before
        two_groups.set_open_group("Finance")
        assert self._widths(two_groups) == before

    def test_nor_does_going_to_a_page(self, two_groups):
        before = self._widths(two_groups)
        two_groups.select_page("p5")
        assert self._widths(two_groups) == before
        two_groups.select_page(None)
        assert self._widths(two_groups) == before

    def test_a_header_is_padded_like_every_other_tab(self, two_groups):
        """The bold face is measured, not allowed for with a flat number.
        A fixed allowance is wrong for every string but one — bold costs
        about 2px on a short name and nearly ten on a long one — and it
        all showed up as white space after the name."""
        def slack(index):
            from PySide6.QtGui import QFont, QFontMetrics
            font = QFont(two_groups.font())
            font.setBold(_index_of(two_groups, "Sales") == index
                         or _index_of(two_groups, "Finance") == index)
            return (two_groups.tabRect(index).width()
                    - QFontMetrics(font).horizontalAdvance(
                        two_groups.tabText(index)))

        plain = slack(_index_of(two_groups, "Ops"))
        for name in ("Sales", "Finance"):
            assert abs(slack(_index_of(two_groups, name)) - plain) <= 2


class TestPickingATabUp:
    """Qt draws a dragged tab **itself**, as a child widget holding a
    pixmap of it, and its own paintEvent answers by leaving that tab out
    of the bar. A bar that paints its own tabs has to do the same, or the
    tab is on the bar twice: one under the pointer and one left behind in
    the slot it is being dragged out of (Dan, with a screenshot of two
    Attritions)."""

    def _drag_by(self, widget, start, dx):
        widget.mousePressEvent(_press(start))
        at = QPoint(start.x() + dx, start.y())
        where = widget.mapToGlobal(at)
        widget.mouseMoveEvent(_move(widget.mapFromGlobal(where), where))
        return at

    def test_a_press_alone_picks_nothing_up(self, rows):
        rows.bar.mousePressEvent(
            _press(_gap(rows.bar, _index_of(rows.bar, "Ops"))))
        assert rows.bar._floating is None

    def test_nor_does_a_twitch(self, rows):
        """Qt waits for `startDragDistance` before it picks a tab up, so
        this has to wait for exactly the same thing — a tab slides some
        way before it passes a neighbour, and the ghost was there for all
        of it."""
        self._drag_by(rows.bar, _gap(rows.bar, _index_of(rows.bar, "Ops")), 2)
        assert rows.bar._floating is None

    def test_but_a_real_drag_does(self, rows):
        self._drag_by(rows.bar, _gap(rows.bar, _index_of(rows.bar, "Ops")), 40)
        assert rows.bar._floating == "p3"

    def test_and_the_bar_stops_drawing_it(self, rows):
        from PySide6.QtGui import QPixmap

        bar = rows.bar
        rect = bar.tabRect(_index_of(bar, "Ops"))

        def slot():
            pix = QPixmap(bar.size())
            bar.render(pix)
            return pix.copy(rect).toImage()

        before = slot()
        bar._floating = "p3"
        assert slot() != before

    def test_letting_go_puts_it_back(self, rows):
        start = _gap(rows.bar, _index_of(rows.bar, "Ops"))
        at = self._drag_by(rows.bar, start, 40)
        rows.bar.mouseReleaseEvent(_release(at))
        assert rows.bar._floating is None

    def test_the_row_picks_its_own_tabs_up_the_same_way(self, rows):
        self._drag_by(rows.row, _gap(rows.row, 1), 40)
        assert rows.row._floating == "p2"
        rows.row.mouseReleaseEvent(_release(_gap(rows.row, 1)))
        assert rows.row._floating is None

    def test_and_leaves_their_slots_empty_the_same_way(self, rows):
        from PySide6.QtGui import QPixmap

        row = rows.row
        rect = row.tabRect(1)

        def slot():
            pix = QPixmap(row.size())
            row.render(pix)
            return pix.copy(rect).toImage()

        before = slot()
        row._floating = "p2"
        assert slot() != before

    def _slide(self, widget, index, steps=8, step=-8):
        """A real drag, and where Qt's floating copy of the tab sits at
        each step of it."""
        from PySide6.QtTest import QTest

        from flograph.ui.dashboard.page_bar import qt_floating_tab

        start = widget.tabRect(index).center()
        QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
        places = []
        for n in range(steps):
            QTest.mouseMove(widget, QPoint(start.x() + n * step, start.y()))
            child = qt_floating_tab(widget)
            if child is not None:
                places.append(child.x())
        QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier,
                           QPoint(start.x() + steps * step, start.y()))
        return places

    def test_the_floating_tab_follows_the_pointer(self, rows):
        """`QTabBar` moves it in its **own paintEvent** — the branch that
        runs during a drag sets the moving widget's geometry instead of
        drawing the tab. A bar that paints its own tabs overrides that
        method and so never runs it: the copy stays frozen where it was
        picked up while the rest of the bar shuffles around it, so the
        tab looks like it never left and a hole opens where it will land
        (Dan: "original location stays fully visible and then a blank
        space shows where it would be dropped")."""
        places = self._slide(rows.row, 1)
        assert len(places) >= 2
        assert places[-1] < places[0]

    def test_and_so_does_the_one_on_the_bar_above(self, rows):
        places = self._slide(rows.bar, _index_of(rows.bar, "Ops"))
        assert len(places) >= 2
        assert places[-1] < places[0]

    def test_it_is_kept_on_the_bar(self, rows):
        """Dragged off the end it stops at the edge, as Qt keeps it."""
        places = self._slide(rows.row, 1, steps=20, step=-20)
        assert min(places) >= 0


class TestDraggingAGroupHeader:
    """A header is moved by a drag of our own rather than Qt's — it is not
    a tab Qt should make current — so nothing was making it follow the
    pointer. It sat in its slot while the bar reordered around it, and the
    only sign a drag was happening was the other groups jumping. A page
    tab has slid under the pointer since Qt wrote `QTabBar`, and a header
    is dragged the same way, so it should look the same way (Dan)."""

    def _press_header(self, bar, name):
        start = bar.tabRect(_index_of(bar, name)).center()
        bar.mousePressEvent(_press(start))
        return start

    def _move_to(self, bar, at):
        where = bar.mapToGlobal(at)
        bar.mouseMoveEvent(_move(bar.mapFromGlobal(where), where))

    def test_a_press_alone_lifts_nothing(self, rows):
        self._press_header(rows.bar, "Sales")
        assert rows.bar._dragged_header() is None

    def test_nor_does_a_twitch(self, rows):
        start = self._press_header(rows.bar, "Sales")
        self._move_to(rows.bar, QPoint(start.x() + 2, start.y()))
        assert rows.bar._dragged_header() is None

    def test_but_a_real_drag_lifts_it(self, rows):
        start = self._press_header(rows.bar, "Sales")
        self._move_to(rows.bar, QPoint(start.x() + 40, start.y()))
        assert rows.bar._dragged_header() == "Sales"

    def test_and_it_slides_under_the_pointer(self, rows):
        """Held by the point it was picked up by — which is the whole
        claim, and the only one a moving header can be held to: its
        *slot* travels too as the bar reorders under the drag, so "it
        ended up further right" is true of a header that never left."""
        bar = rows.bar
        start = self._press_header(bar, "Sales")
        grab = bar._header_drag["grab"]
        for dx in (20, 32, 44):
            self._move_to(bar, QPoint(start.x() + dx, start.y()))
            left = bar._header_float_rect(_index_of(bar, "Sales")).left()
            assert left == start.x() + dx - grab
        bar.mouseReleaseEvent(_release(QPoint(start.x() + 44, start.y())))

    def test_it_is_kept_on_the_bar(self, rows):
        bar = rows.bar
        start = self._press_header(bar, "Sales")
        self._move_to(bar, QPoint(start.x() + 4000, start.y()))
        rect = bar._header_float_rect(_index_of(bar, "Sales"))
        assert rect.left() >= 0
        assert rect.right() <= bar.width()
        bar.mouseReleaseEvent(_release(QPoint(start.x() + 4000, start.y())))

    def test_the_bar_stops_drawing_it_in_its_slot(self, rows, monkeypatch):
        """Drawn once, where the pointer has it — or it is on the bar
        twice, which is the ghost being fixed a row below. Counted rather
        than looked at: the floating header passes *over* its old slot on
        a short drag, so a picture of that slot changes either way."""
        from PySide6.QtGui import QPixmap

        bar = rows.bar
        drawn = []
        original = bar._paint_header

        def spy(painter, index, group, rect=None):
            drawn.append((group, rect))
            return original(painter, index, group, rect)

        monkeypatch.setattr(bar, "_paint_header", spy)
        start = self._press_header(bar, "Sales")
        self._move_to(bar, QPoint(start.x() + 40, start.y()))
        drawn.clear()
        bar.render(QPixmap(bar.size()))
        sales = [rect for group, rect in drawn if group == "Sales"]
        assert len(sales) == 1
        assert sales[0] is not None      # the floating one, not the slot
        bar.mouseReleaseEvent(_release(QPoint(start.x() + 40, start.y())))

    def test_letting_go_puts_it_down(self, rows):
        start = self._press_header(rows.bar, "Sales")
        self._move_to(rows.bar, QPoint(start.x() + 40, start.y()))
        rows.bar.mouseReleaseEvent(_release(QPoint(start.x() + 40, start.y())))
        assert rows.bar._dragged_header() is None

    def test_a_floating_header_is_not_see_through(self, rows):
        """It passes over its neighbours, and a header is filled with a
        *tone* of its colour — so without ground of its own the tab
        underneath reads straight through the one being dragged."""
        from PySide6.QtGui import QPainter, QPixmap

        bar = rows.bar
        index = _index_of(bar, "Sales")
        rect = bar.tabRect(index)

        def painted(ground):
            pix = QPixmap(rect.size())
            pix.fill(ground)
            painter = QPainter(pix)
            bar._paint_header(painter, index, "Sales",
                              QRect(0, 0, rect.width(), rect.height()))
            painter.end()
            return pix.toImage()

        assert painted(Qt.red) == painted(Qt.green)

    def test_letting_go_puts_the_header_back_in_its_slot(self, rows,
                                                         monkeypatch):
        """A drop that changes the order gets repainted by the reorder
        coming back from the window. One that comes to nothing sends
        nothing — and the last thing painted was the header under the
        pointer, so it stayed there (Dan). Asking to repaint is the claim
        here: rendering by hand would paint the resting bar either way,
        since by then the drag is over."""
        bar = rows.bar
        start = self._press_header(bar, "Sales")
        self._move_to(bar, QPoint(start.x() + 20, start.y()))
        self._move_to(bar, start)          # back where it started
        assert bar.page_order() == ["c1", "p1", "p2", "p3"]
        repaints = []
        monkeypatch.setattr(bar, "update", lambda *a: repaints.append(a))
        asked = []
        bar.reorder_pages_requested.connect(asked.append)
        bar.mouseReleaseEvent(_release(start))
        assert asked == []                 # nothing moved, nothing to ask
        assert repaints                    # but the header is put down

    def test_a_header_drag_never_moves_the_pages_it_passes_over(self, rows):
        """A block with nothing showing keeps its place. It used to be
        swept to the end of the order, on the grounds that a drag can't
        be aimed at something invisible — but a drag is aimed *past* it,
        not at it. On one row that only bit folded canvas tabs; with a
        second row every grouped page is off the top row, so every header
        drag quietly rewrote the order behind them."""
        bar = rows.bar
        assert bar.page_order() == ["c1", "p1", "p2", "p3"]
        start = self._press_header(bar, "Sales")
        for dx in (20, 60, 90):
            self._move_to(bar, QPoint(start.x() + dx, start.y()))
            assert bar.page_order()[0] == "c1"    # never dragged along
        bar.mouseReleaseEvent(_release(QPoint(start.x() + 90, start.y())))
        assert bar.page_order() == ["c1", "p3", "p1", "p2"]


class TestGoingToAPageInNoGroup:
    """The top row is the pages in no group. Go to one of those and there
    is no group being looked at, so a row of some other group's pages is
    just in the way — it goes (Dan)."""

    def test_clicking_it_takes_the_row_away(self, rows):
        assert rows.bar.open_group() == "Sales"
        _click(rows.bar, _index_of(rows.bar, "Ops"))
        assert rows.bar.open_group() == ""

    def test_and_the_row_itself_goes_with_it(self, rows):
        _click(rows.bar, _index_of(rows.bar, "Ops"))
        rows.refresh()
        assert rows.row.isVisible() is False

    def test_no_header_is_lit_then(self, rows):
        _click(rows.bar, _index_of(rows.bar, "Ops"))
        assert rows.bar._header_lit("Sales") is False
        assert rows.bar._model_lit() is False

    def test_a_header_brings_it_back(self, rows):
        _click(rows.bar, _index_of(rows.bar, "Ops"))
        _click(rows.bar, _index_of(rows.bar, "Sales"))
        assert rows.bar.open_group() == "Sales"
        assert rows.row.page_ids() == ["p1", "p2"]

    def test_going_to_a_grouped_page_brings_it_back_too(self, rows):
        _click(rows.bar, _index_of(rows.bar, "Ops"))
        rows.bar.select_page("p2")
        assert rows.bar.open_group() == "Sales"

    def test_the_model_canvas_still_opens_its_own_row(self, rows):
        """It is in a group — the one the Model tab heads."""
        _click(rows.bar, _index_of(rows.bar, "Ops"))
        rows.bar.select_page(None)
        assert rows.bar.open_group() == CANVASES

    def test_a_header_click_leaves_the_page_where_it_is(self, rows):
        """Which is why a header never closes the row: it is not a page,
        it is never current, and it changes nobody."""
        _click(rows.bar, _index_of(rows.bar, "Ops"))
        _click(rows.bar, _index_of(rows.bar, "Sales"))
        assert rows.bar.current_page_id() == "p3"
        assert rows.bar.open_group() == "Sales"

    def test_dragging_one_onto_the_row_does_not_shut_it_first(self, rows,
                                                              qtbot):
        """Qt makes a tab current on the *press*, so answering the row
        there pulled it out from under the very drag aiming at it. The
        row is settled when the gesture ends, not when it starts."""
        with qtbot.waitSignal(rows.bar.move_page_requested) as blocker:
            _drag_across(rows.bar, _gap(rows.bar, _index_of(rows.bar, "Ops")),
                         rows.row, _gap(rows.row, 0))
        assert blocker.args[1:] == ["p3", "Sales"]

    def test_turning_the_row_on_still_shows_one(self, rows, qtbot):
        """Even standing on a page in no group. Switching a thing on and
        seeing nothing happen is no way to learn what it does — the row
        closing is something you arrive at, not something you start in."""
        widget = PageTabBar()
        host = PageBarHost(widget)
        qtbot.addWidget(host)
        for page in (Page(id="q1", title="Sales EU"),
                     Page(id="q2", title="Loose")):
            widget.add_page_tab(page)
        widget.set_page_group("q1", "Sales")
        widget.select_page("q2")
        widget.set_second_row(True)
        assert widget.open_group() == "Sales"
