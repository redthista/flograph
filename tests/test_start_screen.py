"""The start screen (O1): what flograph shows when it opens with no project
named — favourite and recent workflows on the right, New, Open and the
examples on the left — and how each of them gives the canvas back.

Settings kept off the real store (avoid polluting the developer's actual
flograph.conf) -- see test_lod_settings.py's fixture of the same name."""
import os
import time
from datetime import datetime

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest

from flograph.core import Graph, Page
from flograph.core.serialization import save
from flograph.ui import mainwindow as mod
from flograph.ui.commands import AddPageCommand
from flograph.ui.mainwindow import MainWindow
from flograph.ui.start_screen import StartScreen, edited_ago, example_entries


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


def _workflow(tmp_path, name, age_days=0.0):
    """A real, loadable workflow file, last written `age_days` ago."""
    path = tmp_path / f"{name}.flograph"
    save(Graph(), str(path))
    stamp = time.time() - age_days * 86400
    os.utime(path, (stamp, stamp))
    return str(path)


def _remember(window, recent=(), favourites=()):
    window.settings.setValue("recent_files", list(recent))
    window.settings.setValue("favorite_workflows", list(favourites))


def _screen(window) -> StartScreen:
    window.show_start_screen()
    return window._start_screen


def _click(widget):
    """A real click on a widget that was never shown: give it a size, so
    the release lands inside it."""
    widget.resize(400, 40)
    QTest.mouseClick(widget, Qt.LeftButton, pos=QPoint(20, 20))


def _names(screen):
    return [row._path for row in screen.rows()]


class TestShowingIt:
    def test_it_stands_in_for_the_canvas(self, window):
        screen = _screen(window)
        assert window._canvas_stack.currentWidget() is screen
        assert window.start_screen_visible

    def test_a_new_window_is_not_on_it(self, window):
        """Only a launch asks for it — every other MainWindow, and all the
        tests that build one, start on the canvas as they always did."""
        assert not window.start_screen_visible
        assert window._start_screen is None

    def test_the_file_menu_brings_it_back(self, window):
        window.action_start_screen.trigger()
        assert window.start_screen_visible

    def test_the_zoom_readout_still_finds_the_canvas(self, window):
        _screen(window)
        assert window._active_canvas_view() is window.view


class TestWhatItLists:
    def test_recent_workflows_newest_first(self, window, tmp_path):
        a, b = _workflow(tmp_path, "alpha"), _workflow(tmp_path, "beta")
        _remember(window, recent=[b, a])
        screen = _screen(window)
        assert screen.section_titles() == ["RECENT WORKFLOWS"]
        assert _names(screen) == [b, a]

    def test_a_file_that_has_gone_is_left_out(self, window, tmp_path):
        a = _workflow(tmp_path, "alpha")
        _remember(window, recent=[str(tmp_path / "gone.flograph"), a])
        assert _names(_screen(window)) == [a]

    def test_favourites_come_first_and_only_once(self, window, tmp_path):
        a, b = _workflow(tmp_path, "alpha"), _workflow(tmp_path, "beta")
        _remember(window, recent=[a, b], favourites=[b])
        screen = _screen(window)
        assert screen.section_titles() == ["FAVOURITES", "RECENT WORKFLOWS"]
        assert _names(screen) == [b, a]

    def test_each_says_when_it_was_edited(self, window, tmp_path):
        _remember(window, recent=[_workflow(tmp_path, "alpha", age_days=3)])
        row = _screen(window).rows()[0]
        assert row.detail_label.text() == "edited 3 days ago"

    def test_nothing_opened_yet_says_what_to_do(self, window):
        screen = _screen(window)
        assert screen.rows() == []
        assert not screen.empty_label.isHidden()
        assert "example" in screen.empty_label.text()

    def test_the_examples_are_the_file_menu_s(self, window):
        screen = _screen(window)
        titles = [screen.examples.item(i).text()
                  for i in range(screen.examples.count())]
        assert titles == [t for t, _ in example_entries()]
        assert titles == [a.text() for a in window._examples_menu.actions()]

    def test_it_is_current_every_time_it_is_shown(self, window, tmp_path):
        screen = _screen(window)
        assert screen.rows() == []
        _remember(window, recent=[_workflow(tmp_path, "alpha")])
        window.leave_start_screen()
        window.show_start_screen()
        assert len(screen.rows()) == 1


class TestLeavingIt:
    def test_opening_a_recent_workflow(self, window, tmp_path):
        a = _workflow(tmp_path, "alpha")
        _remember(window, recent=[a])
        _click(_screen(window).rows()[0])
        assert window._project_path == a
        assert not window.start_screen_visible

    def test_new_workflow(self, window):
        _screen(window).new_button.click()
        assert not window.start_screen_visible

    def test_an_example(self, window):
        screen = _screen(window)
        item = screen.examples.item(0)
        screen.examples.itemClicked.emit(item)
        assert not window.start_screen_visible
        assert window.graph.nodes            # the example really loaded

    def test_the_empty_canvas(self, window):
        screen = _screen(window)
        assert screen.leave_button.text() == "Start on an Empty Canvas"
        screen.leave_button.click()
        assert window._canvas_stack.currentWidget() is window.view

    def test_back_to_the_project_it_was_opened_from(self, window, tmp_path):
        a = _workflow(tmp_path, "alpha")
        window.open_path(a, confirm=False)
        assert _screen(window).leave_button.text() == "Back to alpha"

    def test_choosing_a_page(self, window):
        window.undo_stack.push(
            AddPageCommand(window.graph, Page(id="p1", title="Board")))
        _screen(window)
        window.page_bar.select_page("p1")
        assert not window.start_screen_visible

    def test_leaving_returns_to_the_page_it_came_from(self, window):
        window.undo_stack.push(
            AddPageCommand(window.graph, Page(id="p1", title="Board")))
        window.page_bar.select_page("p1")
        _screen(window).leave_button.click()
        assert (window._canvas_stack.currentWidget()
                is window._dashboard_pages["p1"])


def _open_docks(window):
    return [dock for dock in window._model_docks if not dock.isHidden()]


def _add_board(window):
    window.undo_stack.push(
        AddPageCommand(window.graph, Page(id="p1", title="Board")))


class TestTheDocks:
    """The panels step aside while it shows, the way a dashboard page puts
    them away, and come back exactly as they were."""

    def test_they_are_put_away_while_it_shows(self, window):
        assert _open_docks(window)
        _screen(window)
        assert _open_docks(window) == []
        assert not any(strip.isVisibleTo(window)
                       for strip in window._edge_strips.values())

    def test_they_come_back_when_it_goes(self, window):
        before = _open_docks(window)
        _screen(window).leave_button.click()
        assert _open_docks(window) == before

    def test_opening_a_workflow_brings_them_back(self, window, tmp_path):
        before = _open_docks(window)
        _screen(window)
        window.open_path(_workflow(tmp_path, "alpha"), confirm=False)
        assert _open_docks(window) == before

    def test_a_dock_closed_before_stays_closed(self, window):
        window.log_dock.close()
        before = _open_docks(window)
        _screen(window).leave_button.click()
        assert _open_docks(window) == before
        assert window.log_dock.isHidden()

    def test_by_way_of_a_dashboard_page(self, window):
        before = _open_docks(window)
        _add_board(window)
        _screen(window)
        window.page_bar.select_page("p1")
        assert _open_docks(window) == []          # a board has none either
        window.page_bar.select_page(None)
        assert _open_docks(window) == before

    def test_opened_from_a_dashboard_page_it_goes_back_to_one(self, window):
        before = _open_docks(window)
        _add_board(window)
        window.page_bar.select_page("p1")
        _screen(window).leave_button.click()
        assert _open_docks(window) == []
        window.page_bar.select_page(None)
        assert _open_docks(window) == before

    def test_hide_all_panels_leaves_them_put_away(self, window):
        _screen(window)
        window.toggle_all_panels()
        assert _open_docks(window) == []

    def test_quitting_from_it_keeps_them_for_next_time(self, window,
                                                       registry, qtbot):
        """saveState() carries visibility: saved while the screen had them
        hidden, the next launch would open with every panel gone."""
        before = [dock.objectName() for dock in _open_docks(window)]
        _screen(window)
        window._save_window_state()
        assert _open_docks(window) == []           # still put away
        again = MainWindow(registry)
        again.confirm_close = False
        qtbot.addWidget(again)
        assert [dock.objectName() for dock in _open_docks(again)] == before

    def test_quitting_from_a_dashboard_page_keeps_them_too(self, window,
                                                           registry, qtbot):
        before = [dock.objectName() for dock in _open_docks(window)]
        _add_board(window)
        window.page_bar.select_page("p1")
        window._save_window_state()
        again = MainWindow(registry)
        again.confirm_close = False
        qtbot.addWidget(again)
        assert [dock.objectName() for dock in _open_docks(again)] == before


class TestTheChrome:
    """The page tabs and the run buttons belong to a flow; the start screen
    has none on show."""

    def test_the_page_tabs_step_aside(self, window):
        _screen(window)
        assert window.page_bar.isHidden()
        window.leave_start_screen()
        assert not window.page_bar.isHidden()

    def test_the_run_buttons_step_aside(self, window):
        bar = window._title_bar
        _screen(window)
        assert bar._run_btn.isHidden() and bar._reset_btn.isHidden()
        window.leave_start_screen()
        assert not bar._run_btn.isHidden()
        assert not bar._reset_btn.isHidden()

    def test_the_selection_pair_comes_back_as_it_was(self, window):
        bar = window._title_bar
        bar.on_selection(2)
        _screen(window)
        assert bar._run_sel_btn.isHidden()
        window.leave_start_screen()
        assert not bar._run_sel_btn.isHidden()

    def test_the_run_keys_do_nothing_while_it_shows(self, window):
        _screen(window)
        assert not window.action_run.isEnabled()
        assert not window.action_reset_caches.isEnabled()
        window.leave_start_screen()
        assert window.action_run.isEnabled()
        assert window.action_reset_caches.isEnabled()

    def test_opening_a_workflow_brings_them_all_back(self, window, tmp_path):
        _screen(window)
        window.open_path(_workflow(tmp_path, "alpha"), confirm=False)
        assert not window.page_bar.isHidden()
        assert not window._title_bar._run_btn.isHidden()
        assert window.action_run.isEnabled()


class TestSearching:
    def test_rows_that_do_not_match_are_hidden(self, window, tmp_path):
        a, b = _workflow(tmp_path, "alpha"), _workflow(tmp_path, "beta")
        _remember(window, recent=[a, b])
        screen = _screen(window)
        screen.search.setText("ALP")
        assert [row.isHidden() for row in screen.rows()] == [False, True]

    def test_a_section_with_nothing_left_hides_its_heading(self, window,
                                                           tmp_path):
        a, b = _workflow(tmp_path, "alpha"), _workflow(tmp_path, "beta")
        _remember(window, recent=[a], favourites=[b])
        screen = _screen(window)
        screen.search.setText("alpha")
        headings = [h for h, _ in screen._headings]
        assert [h.isHidden() for h in headings] == [True, False]

    def test_no_match_says_so(self, window, tmp_path):
        _remember(window, recent=[_workflow(tmp_path, "alpha")])
        screen = _screen(window)
        screen.search.setText("zebra")
        assert "zebra" in screen.empty_label.text()
        assert not screen.empty_label.isHidden()


class TestTheStar:
    def test_starring_moves_a_row_to_favourites(self, window, tmp_path,
                                                qtbot):
        a, b = _workflow(tmp_path, "alpha"), _workflow(tmp_path, "beta")
        _remember(window, recent=[a, b])
        screen = _screen(window)
        screen.rows()[1]._star_btn.click()
        qtbot.waitUntil(lambda: screen.section_titles()
                        == ["FAVOURITES", "RECENT WORKFLOWS"])
        assert _names(screen) == [b, a]
        assert window.is_favorite_workflow(b)


class TestTheSetting:
    def test_on_unless_turned_off(self, window):
        assert window.start_screen_on_launch is True

    def test_turning_it_off_is_remembered(self, window):
        window.set_start_screen_on_launch(False)
        assert window.settings.value("start/show_on_launch",
                                     type=bool) is False
        assert window.start_screen_on_launch is False


class TestEditedAgo:
    NOW = datetime(2026, 9, 11, 12, 0).timestamp()

    @pytest.mark.parametrize("seconds, expected", [
        (20, "edited just now"),
        (60, "edited 1 minute ago"),
        (5 * 60, "edited 5 minutes ago"),
        (3600, "edited 1 hour ago"),
        (5 * 3600, "edited 5 hours ago"),
        (30 * 3600, "edited yesterday"),
        (4 * 86400, "edited 4 days ago"),
    ])
    def test_recent_edits(self, seconds, expected):
        assert edited_ago(self.NOW - seconds, self.NOW) == expected

    def test_past_a_month_it_is_the_date(self):
        then = datetime(2026, 7, 2, 9, 0).timestamp()
        assert edited_ago(then, self.NOW) == "edited on 2 Jul 2026"

    def test_a_clock_that_ran_backwards_is_just_now(self):
        assert edited_ago(self.NOW + 60, self.NOW) == "edited just now"
