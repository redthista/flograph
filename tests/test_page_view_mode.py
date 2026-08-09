"""View mode / edit mode for dashboard and report pages.

View mode hides the chrome for *arranging* a page and locks its layout. The
thing it must never do is make the page read-only: a dashboard exists to be
driven, so slicers, spreadsheets, buttons and web views all stay live.
"""
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QGraphicsItem

from flograph.core import Graph, NodeRegistry, Page, Tile
from flograph.core.serialization import graph_from_dict, graph_to_dict
from flograph.ui import mainwindow as mod
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


# ----------------------------------------------------------------- reports

class TestReportViewMode:
    def test_view_mode_hides_the_editor(self, window):
        page = add_page(window, "r1", kind="report")
        page.set_view_mode(True)
        assert page.editor.isHidden()
        assert page._insert_btn.isHidden()

    def test_the_preview_and_export_stay(self, window):
        """Reading a report is exactly when someone wants the PDF."""
        page = add_page(window, "r1", kind="report")
        page.set_view_mode(True)
        assert not page.preview.isHidden()
        assert not page._export_btn.isHidden()

    def test_edit_mode_brings_the_editor_back(self, window):
        page = add_page(window, "r1", kind="report")
        page.set_view_mode(True)
        page.set_view_mode(False)
        assert not page.editor.isHidden()
        assert not page._insert_btn.isHidden()

    def test_the_toggle_asks_the_window_rather_than_acting(self, window,
                                                           qtbot):
        """One concept, not two: the collapse toggle goes through the same
        undoable page setting the tab menu does."""
        page = add_page(window, "r1", kind="report")
        with qtbot.waitSignal(page.view_mode_requested, timeout=1000) as blocker:
            page._mode_btn.click()
        assert blocker.args == ["r1", True]


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
        window._set_page_view_mode("p1", False)   # already in edit mode
        assert window.undo_stack.count() == before
