"""View mode / edit mode for dashboard and report pages.

View mode hides the chrome for *arranging* a page and locks its layout. The
thing it must never do is make the page read-only: a dashboard exists to be
driven, so slicers, spreadsheets, buttons and web views all stay live.
"""
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import (
    QContextMenuEvent, QKeyEvent, QMouseEvent, QUndoStack, QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication, QGraphicsItem, QGraphicsView, QMenu,
)

from flograph.core import Graph, NodeRegistry, Page, Tile
from flograph.core.serialization import graph_from_dict, graph_to_dict
from flograph.ui import mainwindow as mod
from flograph.ui.dashboard import dashboard_view
from flograph.ui.commands import (
    AddPageCommand, AddTileCommand, SetPageViewModeCommand,
)
from flograph.ui.mainwindow import MainWindow


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
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


def send_wheel(view, dx: int = 0, dy: int = -120, modifiers=Qt.NoModifier):
    """A wheel tick over the middle of the view, the way the widget would
    receive one."""
    pos = QPointF(view.viewport().rect().center())
    event = QWheelEvent(
        pos, QPointF(view.viewport().mapToGlobal(pos.toPoint())),
        QPoint(0, 0), QPoint(dx, dy),
        Qt.NoButton, modifiers, Qt.NoScrollPhase, False)
    QApplication.sendEvent(view.viewport(), event)


def visible_rect(view):
    return view.mapToScene(view.viewport().rect()).boundingRect()


def add_page(window, page_id="p1", kind="dashboard"):
    window.undo_stack.push(AddPageCommand(
        window.graph, Page(id=page_id, title="Board", kind=kind)))
    return window._dashboard_pages[page_id]


# ------------------------------------------------------------------- model

class TestPageViewModeModel:
    def test_pages_start_in_edit_mode(self):
        assert Page(id="p").view_mode is False

    def test_setter_emits_page_changed(self):
        graph = Graph()
        graph.add_page(Page(id="p"))
        seen = []
        graph.events.page_changed.connect(seen.append)
        graph.set_page_view_mode("p", True)
        assert graph.page("p").view_mode is True
        assert [p.id for p in seen] == ["p"]

    def test_false_means_edit_not_unchanged(self):
        graph = Graph()
        graph.add_page(Page(id="p", view_mode=True))
        graph.set_page_view_mode("p", False)
        assert graph.page("p").view_mode is False

    def test_round_trips_through_a_saved_project(self):
        graph = Graph()
        graph.add_page(Page(id="p", title="Board", view_mode=True))
        graph.add_page(Page(id="q", title="Other"))
        reloaded = graph_from_dict(graph_to_dict(graph), NodeRegistry())
        assert reloaded.page("p").view_mode is True
        assert reloaded.page("q").view_mode is False

    def test_a_file_written_before_view_mode_loads_as_edit(self):
        """Older projects have no such key, and they were all being edited."""
        graph = Graph()
        graph.add_page(Page(id="p"))
        payload = graph_to_dict(graph)
        for entry in payload["graph"]["pages"]:
            entry.pop("view_mode", None)
        assert graph_from_dict(payload, NodeRegistry()).page("p").view_mode is False

    def test_command_undoes(self):
        graph = Graph()
        graph.add_page(Page(id="p"))
        stack = QUndoStack()
        stack.push(SetPageViewModeCommand(graph, "p", True))
        assert graph.page("p").view_mode is True
        stack.undo()
        assert graph.page("p").view_mode is False
        stack.clear()

    def test_duplicating_a_page_keeps_the_mode(self, window):
        add_page(window)
        window.graph.set_page_view_mode("p1", True)
        from flograph.ui.commands import DuplicatePageCommand
        window.undo_stack.push(DuplicatePageCommand(window.graph, "p1"))
        copies = [p for p in window.graph.pages.values() if p.id != "p1"]
        assert copies and all(p.view_mode for p in copies)


# --------------------------------------------------------------- dashboard

class TestDashboardViewMode:
    def _tile(self, window, page_id="p1"):
        node = window.registry.instantiate("flograph.viz.show_table",
                                           pos=(0, 0))
        window.graph.add_node(node)
        tile = Tile(id="t1", node_id=node.id, port="table")
        window.undo_stack.push(AddTileCommand(window.graph, page_id, tile))
        return window._dashboard_pages[page_id].scene.tile_items["t1"]

    def test_view_mode_hides_the_visuals_panel(self, window):
        page = add_page(window)
        page.set_visuals_visible(True)
        page.set_view_mode(True)
        # isHidden(), not isVisible(): these tests never show the window
        # (see test_dashboard_ui.py), so isVisible() is False regardless
        assert page._side.isHidden()
        assert page._toggle_strip.isHidden()

    def test_leaving_view_mode_puts_the_panel_back(self, window):
        page = add_page(window)
        page.set_visuals_visible(True)
        page.set_view_mode(True)
        page.set_view_mode(False)
        assert not page._side.isHidden()

    def test_tiles_stop_moving_and_resizing(self, window):
        page = add_page(window)
        item = self._tile(window)
        page.set_view_mode(True)
        assert item.layout_locked()
        assert not item.flags() & QGraphicsItem.ItemIsMovable
        assert not item.flags() & QGraphicsItem.ItemIsSelectable
        # no resize edge anywhere on the tile, including over the grip
        w, h = item._size
        from PySide6.QtCore import QPointF
        assert item._edge_at(QPointF(w - 2, h - 2)) is None

    def test_contents_stay_live(self, window):
        """The whole point: a locked dashboard is still meant to be driven,
        so the embedded widget is untouched."""
        page = add_page(window)
        item = self._tile(window)
        page.set_view_mode(True)
        assert item._proxy.isEnabled()   # still takes input
        assert item._proxy.isVisible()   # graphics items ignore window mapping

    def test_unlocking_restores_move_and_resize(self, window):
        page = add_page(window)
        item = self._tile(window)
        page.set_view_mode(True)
        page.set_view_mode(False)
        assert not item.layout_locked()
        assert item.flags() & QGraphicsItem.ItemIsMovable

    def test_a_tile_added_while_locked_arrives_locked(self, window):
        """Undoing a delete on a view-mode page must not leave one movable
        tile on an otherwise locked page."""
        page = add_page(window)
        page.set_view_mode(True)
        assert self._tile(window).layout_locked()

    def test_view_mode_stops_accepting_dropped_tiles(self, window):
        page = add_page(window)
        page.set_view_mode(True)
        assert not page.view.acceptDrops()
        page.set_view_mode(False)
        assert page.view.acceptDrops()

    def test_a_page_saved_in_view_mode_opens_that_way(self, window):
        window.undo_stack.push(AddPageCommand(
            window.graph, Page(id="p9", title="B", view_mode=True)))
        assert window._dashboard_pages["p9"].view_mode() is True


class TestALockedPageIsNotACanvas:
    """Locked, a dashboard page *is* the dashboard: tiles, and the things
    inside them. Unlocked it is that plus the tools for arranging it. So the
    viewport stops behaving like an infinite canvas — no zoom, no pan, no
    wheel, no rubber band, no bars, no context menu — while everything
    embedded in the tiles goes on taking input."""

    def _page(self, window, tile_h: float = 2000.0, view_h: int = 300):
        page = add_page(window)
        node = window.registry.instantiate("flograph.viz.card", pos=(0, 0))
        window.graph.add_node(node)
        window.undo_stack.push(AddTileCommand(
            window.graph, "p1",
            Tile(id="t1", node_id=node.id, port="value",
                 rect=(0.0, 0.0, 300.0, tile_h))))
        page.view.resize(400, view_h)
        return page

    def test_locking_a_page_freezes_its_view(self, window):
        page = add_page(window)
        assert page.view.navigation_locked is False
        page.set_view_mode(True)
        assert page.view.navigation_locked is True
        page.set_view_mode(False)
        assert page.view.navigation_locked is False

    def test_the_wheel_does_not_zoom(self, window):
        page = self._page(window)
        page.set_view_mode(True)
        before = page.view.zoom
        send_wheel(page.view)
        assert page.view.zoom == before

    def test_the_wheel_does_not_scroll_either(self, window):
        """Tried scrolling first, on the reasoning that a finished page is a
        document. It isn't: the page is where it was put, and a wheel moving
        it at all is the same surprise the zoom was."""
        page = self._page(window)
        page.set_view_mode(True)
        before = visible_rect(page.view)
        send_wheel(page.view, dy=-120)
        send_wheel(page.view, dy=120)
        assert visible_rect(page.view) == before

    def test_the_wheel_still_zooms_while_unlocked(self, window):
        page = self._page(window)
        before = page.view.zoom
        send_wheel(page.view)
        assert page.view.zoom != before

    def test_a_middle_drag_does_not_pan(self, window):
        page = self._page(window)
        page.set_view_mode(True)
        before = visible_rect(page.view)
        press = QMouseEvent(QEvent.MouseButtonPress, QPointF(200, 150),
                            QPointF(200, 150), Qt.MiddleButton,
                            Qt.MiddleButton, Qt.NoModifier)
        page.view.mousePressEvent(press)
        move = QMouseEvent(QEvent.MouseMove, QPointF(60, 40),
                           QPointF(60, 40), Qt.NoButton, Qt.MiddleButton,
                           Qt.NoModifier)
        page.view.mouseMoveEvent(move)
        assert visible_rect(page.view) == before

    def test_a_middle_drag_pans_again_once_unlocked(self, window):
        page = self._page(window)
        page.set_view_mode(True)
        page.set_view_mode(False)
        before = visible_rect(page.view)
        press = QMouseEvent(QEvent.MouseButtonPress, QPointF(200, 150),
                            QPointF(200, 150), Qt.MiddleButton,
                            Qt.MiddleButton, Qt.NoModifier)
        page.view.mousePressEvent(press)
        move = QMouseEvent(QEvent.MouseMove, QPointF(60, 40),
                           QPointF(60, 40), Qt.NoButton, Qt.MiddleButton,
                           Qt.NoModifier)
        page.view.mouseMoveEvent(move)
        assert visible_rect(page.view) != before

    def test_space_starts_no_pan(self, window):
        page = self._page(window)
        page.set_view_mode(True)
        page.view.keyPressEvent(QKeyEvent(
            QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier))
        assert page.view.dragMode() == QGraphicsView.NoDrag

    def test_there_is_no_rubber_band(self, window):
        page = self._page(window)
        page.set_view_mode(True)
        assert page.view.dragMode() == QGraphicsView.NoDrag
        page.set_view_mode(False)
        assert page.view.dragMode() == QGraphicsView.RubberBandDrag

    def test_set_zoom_is_refused(self, window):
        page = self._page(window)
        page.view.set_zoom(2.0)
        page.set_view_mode(True)
        page.view.set_zoom(1.0)
        assert page.view.zoom == pytest.approx(2.0)

    def test_fit_is_refused(self, window):
        """F on a locked page would rearrange the view as surely as the
        wheel."""
        page = self._page(window)
        page.set_view_mode(True)
        before = page.view.zoom
        page.view.fit_items(list(page.scene.tile_items.values()))
        assert page.view.zoom == before

    def test_the_scroll_bars_go_with_it(self, window):
        page = self._page(window)
        page.view.set_scrollbars_enabled(True)
        page.set_view_mode(True)
        assert page.view.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        page.set_view_mode(False)
        assert page.view.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded

    def test_the_window_preference_cannot_put_them_back(self, window):
        """The window pushes the preference at every view whenever it
        changes, including at pages with no navigation to offer."""
        page = self._page(window)
        page.set_view_mode(True)
        page.view.set_scrollbars_enabled(True)
        assert page.view.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        page.set_view_mode(False)
        assert page.view.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded

    def test_the_zoom_indicator_says_so(self, window):
        page = self._page(window)
        window.page_bar.select_page("p1")
        assert window._zoom_indicator.isEnabled()
        window._set_page_view_mode("p1", True)
        assert not window._zoom_indicator.isEnabled()
        assert "locked" in window._zoom_indicator.toolTip()
        window._set_page_view_mode("p1", False)
        assert window._zoom_indicator.isEnabled()

    def test_a_scrollable_tile_still_gets_the_wheel(self, window,
                                                    monkeypatch):
        """The lock is about the viewport, not the contents: a wheel over a
        table or a web view is that widget's, and the page still does not
        move under it."""
        page = self._page(window)
        page.set_view_mode(True)
        seen: list = []
        monkeypatch.setattr(page.view, "_scrollable_widget_at",
                            lambda pos: seen.append(pos) or page.view)
        before = visible_rect(page.view)
        send_wheel(page.view, dy=-120)
        assert seen                              # asked before the lock did
        assert visible_rect(page.view) == before

    def test_the_canvas_is_untouched_by_any_of_it(self, window):
        """Only the locked page is frozen — the model canvas is still a
        canvas."""
        page = self._page(window)
        page.set_view_mode(True)
        assert window.view.navigation_locked is False
        assert window.view.dragMode() == QGraphicsView.RubberBandDrag


class TestALockedPageHasNoContextMenu:
    """Right-clicking a finished dashboard should do nothing at all. Passing
    the event up instead was showing the main window's own dock-and-toolbar
    menu — the "menu of whatever is underneath" appearing over a locked
    page."""

    def _page(self, window, locked=True):
        page = add_page(window)
        node = window.registry.instantiate("flograph.viz.card", pos=(0, 0))
        window.graph.add_node(node)
        window.undo_stack.push(AddTileCommand(
            window.graph, "p1",
            Tile(id="t1", node_id=node.id, port="value",
                 rect=(0.0, 0.0, 300.0, 200.0))))
        page.view.resize(600, 400)
        page.set_view_mode(locked)
        return page

    def _right_click(self, view, pos=QPoint(40, 40)):
        event = QContextMenuEvent(QContextMenuEvent.Mouse, pos,
                                  view.viewport().mapToGlobal(pos))
        view.contextMenuEvent(event)
        return event

    def _watch_menus(self, monkeypatch) -> list:
        """Menus that were actually shown. A QMenu subclass swapped into the
        module, not a patched QMenu.exec: exec is a C++ slot, the patch does
        not take, and the test hangs on a real popup instead of failing."""
        opened: list = []

        class _Recorder(QMenu):
            def exec(self, *args):
                opened.append([a.text() for a in self.actions()])
                return None
        monkeypatch.setattr(dashboard_view, "QMenu", _Recorder)
        return opened

    def test_a_locked_page_shows_nothing_and_keeps_the_event(self, window,
                                                             monkeypatch):
        page = self._page(window)
        opened = self._watch_menus(monkeypatch)
        event = self._right_click(page.view, QPoint(60, 60))
        assert not opened
        assert event.isAccepted()

    def test_not_even_over_a_tile(self, window, monkeypatch):
        page = self._page(window)
        opened = self._watch_menus(monkeypatch)
        centre = page.view.mapFromScene(
            page.scene.tile_items["t1"].sceneBoundingRect().center())
        self._right_click(page.view, centre)
        assert not opened

    def test_empty_space_on_an_unlocked_page_shows_nothing_either(
            self, window, monkeypatch):
        """The same leak, unlocked: there is no page-level menu, so the
        event must stop here rather than becoming the window's."""
        page = self._page(window, locked=False)
        opened = self._watch_menus(monkeypatch)
        # top-left of a view centred on the scene origin, so it is well
        # clear of the tile at (0, 0)
        event = self._right_click(page.view, QPoint(6, 6))
        assert not opened
        assert event.isAccepted()

    def test_a_tile_on_an_unlocked_page_still_has_its_menu(self, window,
                                                           monkeypatch):
        page = self._page(window, locked=False)
        opened = self._watch_menus(monkeypatch)
        centre = page.view.mapFromScene(
            page.scene.tile_items["t1"].sceneBoundingRect().center())
        self._right_click(page.view, centre)
        assert opened


class TestLockedPageCursor:
    """The cursor is a promise. On a locked page it may only change shape
    where something will actually happen — which rules out the title bar,
    whose four-way move cursor was offering a drag view mode had removed."""

    def _tile(self, window):
        node = window.registry.instantiate("flograph.viz.card", pos=(0, 0))
        window.graph.add_node(node)
        window.undo_stack.push(AddTileCommand(
            window.graph, "p1",
            Tile(id="t1", node_id=node.id, port="value",
                 rect=(0.0, 0.0, 300.0, 200.0))))
        return window._dashboard_pages["p1"].scene.tile_items["t1"]

    def test_the_title_bar_offers_a_move_while_unlocked(self, window):
        add_page(window)
        item = self._tile(window)
        item._apply_edge_cursor(QPointF(120, 6))
        assert item.cursor().shape() == Qt.SizeAllCursor

    def test_the_title_bar_offers_nothing_once_locked(self, window):
        page = add_page(window)
        item = self._tile(window)
        page.set_view_mode(True)
        item._apply_edge_cursor(QPointF(120, 6))
        assert not item.hasCursor()

    def test_the_body_offers_nothing_either(self, window):
        page = add_page(window)
        item = self._tile(window)
        page.set_view_mode(True)
        item._apply_edge_cursor(QPointF(120, 120))
        assert not item.hasCursor()

    def test_the_corner_offers_nothing_once_locked(self, window):
        page = add_page(window)
        item = self._tile(window)
        page.set_view_mode(True)
        w, h = item._size
        item._apply_edge_cursor(QPointF(w - 3, h - 3))
        assert not item.hasCursor()

    def test_the_maximize_glyph_still_does(self, window):
        """It is still live on a locked page, so it still says so."""
        page = add_page(window)
        item = self._tile(window)
        page.set_view_mode(True)
        assert item.can_fullscreen()
        item._apply_edge_cursor(item._fs_button_rect().center())
        assert item.cursor().shape() == Qt.PointingHandCursor

    def test_unlocking_brings_the_move_cursor_back(self, window):
        page = add_page(window)
        item = self._tile(window)
        page.set_view_mode(True)
        page.set_view_mode(False)
        item._apply_edge_cursor(QPointF(120, 6))
        assert item.cursor().shape() == Qt.SizeAllCursor


# ----------------------------------------------------------------- reports

class TestReportViewMode:
    def test_locking_hides_the_editor_and_the_whole_toolbar(self, window):
        """Every control on that strip is for writing the report, so the
        strip goes rather than being emptied."""
        page = add_page(window, "r1", kind="report")
        page.set_view_mode(True)
        assert page.editor.isHidden()
        assert page._toolbar.isHidden()

    def test_the_preview_stays(self, window):
        page = add_page(window, "r1", kind="report")
        page.set_view_mode(True)
        assert not page.preview.isHidden()

    def test_unlocking_brings_the_editor_and_toolbar_back(self, window):
        page = add_page(window, "r1", kind="report")
        page.set_view_mode(True)
        page.set_view_mode(False)
        assert not page.editor.isHidden()
        assert not page._toolbar.isHidden()

    def test_the_report_toolbar_carries_no_lock(self, window):
        """It used to, which put the control that *removes the toolbar* on
        the toolbar — usable exactly once, with the way back on the tab menu
        regardless. One door in, the same door out."""
        page = add_page(window, "r1", kind="report")
        assert not hasattr(page, "_mode_btn")

    def test_the_tab_menu_still_locks_it(self, window, qtbot):
        """The one surface locking lives on, and the only one that is still
        there once the page is locked."""
        page = add_page(window, "r1", kind="report")
        window.page_bar.set_view_mode_requested.emit("r1", True)
        assert window.graph.page("r1").view_mode is True
        assert page.view_mode() is True
        window.undo_stack.undo()
        assert window.graph.page("r1").view_mode is False
        assert page.view_mode() is False


# ------------------------------------------------------------ window wiring

class TestWindowWiring:
    def test_setting_the_mode_is_undoable_and_reaches_the_widget(self, window):
        page = add_page(window)
        window._set_page_view_mode("p1", True)
        assert window.graph.page("p1").view_mode is True
        assert page.view_mode() is True
        window.undo_stack.undo()
        assert window.graph.page("p1").view_mode is False
        assert page.view_mode() is False

    def test_the_tab_bar_tracks_the_mode_for_its_menu(self, window):
        add_page(window)
        window._set_page_view_mode("p1", True)
        assert window.page_bar.page_view_mode("p1") is True

    def test_setting_the_same_mode_adds_no_undo_step(self, window):
        add_page(window)
        before = window.undo_stack.count()
        window._set_page_view_mode("p1", False)   # already unlocked
        assert window.undo_stack.count() == before


# --------------------------------------------------------- the tab's menu

class TestPageTabMenu:
    """The menu is built in _show_context_menu, which blocks on exec(). These
    drive the pieces it reads and emits rather than opening it."""

    def test_one_checkable_lock_entry_reflects_the_page(self, window):
        add_page(window)
        assert window.page_bar.page_view_mode("p1") is False
        window._set_page_view_mode("p1", True)
        assert window.page_bar.page_view_mode("p1") is True

    def test_the_bar_knows_a_page_s_kind(self, window):
        """Export PDF is offered on a locked *report*, so the menu has to
        know which pages are reports."""
        add_page(window, "p1", kind="dashboard")
        add_page(window, "r1", kind="report")
        assert window.page_bar._kinds["p1"] == "dashboard"
        assert window.page_bar._kinds["r1"] == "report"

    def test_export_from_the_menu_reaches_the_window(self, window,
                                                     monkeypatch):
        add_page(window, "r1", kind="report")
        window._set_page_view_mode("r1", True)
        called = []
        monkeypatch.setattr(window, "_export_report_pdf", called.append)
        # no connect here: the window wires this in its constructor, and
        # that wiring is the thing under test
        window.page_bar.export_page_requested.emit("r1")
        assert called == ["r1"]

    def test_removing_a_page_forgets_its_menu_state(self, window):
        add_page(window, "r1", kind="report")
        window._set_page_view_mode("r1", True)
        window.page_bar.remove_page_tab("r1")
        assert "r1" not in window.page_bar._kinds
        assert "r1" not in window.page_bar._view_modes
