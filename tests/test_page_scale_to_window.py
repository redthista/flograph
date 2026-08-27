"""Scale to fit the window: a dashboard page that zooms itself so the same
tiles stay framed whatever size the window is.

The screen a dashboard is opened on is rarely the screen it was built on,
and until now a bigger window just revealed more empty canvas around the
tiles. This is per page, saved with the project, and independent of the
lock — a page being built can scale too.
"""
import pytest
from PySide6.QtCore import QSettings

from flograph.core import Graph, NodeRegistry, Page, Tile
from flograph.core.serialization import graph_from_dict, graph_to_dict
from flograph.ui import mainwindow as mod
from flograph.ui.canvas.base_view import ZOOM_MAX
from flograph.ui.commands import (
    AddPageCommand, AddTileCommand, SetPageFitToWindowCommand,
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


def add_page(window, page_id="p1"):
    window.undo_stack.push(AddPageCommand(
        window.graph, Page(id=page_id, title="Board")))
    return window._dashboard_pages[page_id]


def add_tile(window, tile_id="t1", rect=(0.0, 0.0, 300.0, 200.0),
             page_id="p1"):
    node = window.registry.instantiate("flograph.viz.card", pos=(0, 0))
    window.graph.add_node(node)
    window.undo_stack.push(AddTileCommand(
        window.graph, page_id,
        Tile(id=tile_id, node_id=node.id, port="value", rect=rect)))
    return window._dashboard_pages[page_id].scene.tile_items[tile_id]


def fit_now(page):
    """Skip the settle timer — the coalescing is tested on its own."""
    page.view._fit_timer.stop()
    page.view._fit_page()


# ------------------------------------------------------------------- model

class TestModel:
    def test_pages_do_not_scale_by_default(self):
        assert Page(id="p").fit_to_window is False

    def test_the_setter_emits_page_changed(self):
        graph = Graph()
        graph.add_page(Page(id="p"))
        seen = []
        graph.events.page_changed.connect(seen.append)
        graph.set_page_fit_to_window("p", True)
        assert graph.page("p").fit_to_window is True
        assert [p.id for p in seen] == ["p"]

    def test_false_means_stop_scaling_not_unchanged(self):
        graph = Graph()
        graph.add_page(Page(id="p", fit_to_window=True))
        graph.set_page_fit_to_window("p", False)
        assert graph.page("p").fit_to_window is False

    def test_it_round_trips_through_a_saved_project(self, registry):
        graph = Graph()
        graph.add_page(Page(id="p", fit_to_window=True))
        loaded = graph_from_dict(graph_to_dict(graph), registry)
        assert loaded.pages["p"].fit_to_window is True

    def test_a_file_written_before_this_existed_does_not_scale(self,
                                                               registry):
        graph = Graph()
        graph.add_page(Page(id="p"))
        raw = graph_to_dict(graph)
        del raw["graph"]["pages"][0]["fit_to_window"]
        assert graph_from_dict(raw, registry).pages["p"].fit_to_window is False

    def test_the_command_undoes(self):
        graph = Graph()
        graph.add_page(Page(id="p"))
        command = SetPageFitToWindowCommand(graph, "p", True)
        command.redo()
        assert graph.page("p").fit_to_window is True
        command.undo()
        assert graph.page("p").fit_to_window is False


# -------------------------------------------------------------- the fitting

class TestTheFit:
    """A view of its own rather than the window's: a page widget inside the
    window's layout ignores resize(), and this is all about what happens
    when the viewport changes size."""

    def _view(self, qtbot, registry, tiles=((0.0, 0.0, 300.0, 200.0),),
              size=(600, 400)):
        from PySide6.QtGui import QUndoStack

        from flograph.engine import ExecutionEngine
        from flograph.ui.dashboard.dashboard_scene import DashboardScene
        from flograph.ui.dashboard.dashboard_view import DashboardView

        graph = Graph()
        graph.add_page(Page(id="p1", title="Board"))
        for i, rect in enumerate(tiles):
            node = registry.instantiate("flograph.viz.card", pos=(0, 0))
            graph.add_node(node)
            graph.add_tile("p1", Tile(id=f"t{i}", node_id=node.id,
                                      port="value", rect=rect))
        engine = ExecutionEngine(graph)
        scene = DashboardScene(graph, engine, QUndoStack(), "p1")
        view = DashboardView(scene)
        qtbot.addWidget(view)
        # shown, unlike most of the suite: a hidden widget banks a resize
        # rather than passing it to its viewport, and the viewport's size is
        # the whole subject here
        view.show()
        self._resize(view, *size)
        return graph, scene, view

    @staticmethod
    def _resize(view, width, height):
        from PySide6.QtWidgets import QApplication
        view.resize(width, height)
        QApplication.processEvents()

    def _fit_now(self, view):
        """Skip the settle timer — the coalescing is tested on its own."""
        view._fit_timer.stop()
        view._fit_page()

    def _framed(self, view):
        visible = view.mapToScene(view.viewport().rect()).boundingRect()
        return visible.contains(view.scene().itemsBoundingRect())

    def test_turning_it_on_frames_the_whole_page(self, qtbot, registry):
        _graph, _scene, view = self._view(
            qtbot, registry,
            tiles=((0.0, 0.0, 300.0, 200.0), (400.0, 300.0, 300.0, 200.0)),
            size=(500, 400))
        view.set_fit_to_window(True)
        self._fit_now(view)
        assert self._framed(view)

    def test_a_bigger_window_zooms_in_rather_than_showing_more_canvas(
            self, qtbot, registry):
        _graph, _scene, view = self._view(qtbot, registry, size=(500, 400))
        view.set_fit_to_window(True)
        self._fit_now(view)
        small = view.zoom
        self._resize(view, 1000, 800)
        self._fit_now(view)
        assert view.zoom > small
        assert self._framed(view)

    def test_a_smaller_window_zooms_out_to_keep_it_all(self, qtbot, registry):
        _graph, _scene, view = self._view(
            qtbot, registry, tiles=((0.0, 0.0, 900.0, 700.0),),
            size=(1000, 800))
        view.set_fit_to_window(True)
        self._fit_now(view)
        big = view.zoom
        self._resize(view, 400, 300)
        self._fit_now(view)
        assert view.zoom < big
        assert self._framed(view)

    def test_a_resize_asks_for_a_refit_rather_than_doing_one_per_step(
            self, qtbot, registry):
        """Dragging a window edge delivers a stream of resize events; the
        refit waits for the stream to stop."""
        _graph, _scene, view = self._view(qtbot, registry)
        view.set_fit_to_window(True)
        view._fit_timer.stop()
        self._resize(view, 640, 480)
        assert view._fit_timer.isActive()

    def test_nothing_is_queued_while_it_is_off(self, qtbot, registry):
        _graph, _scene, view = self._view(qtbot, registry)
        view._fit_timer.stop()
        self._resize(view, 640, 480)
        assert not view._fit_timer.isActive()

    def test_the_refit_really_does_arrive(self, qtbot, registry):
        _graph, _scene, view = self._view(qtbot, registry, size=(400, 300))
        view.set_fit_to_window(True)
        qtbot.waitUntil(lambda: not view._fit_timer.isActive(), timeout=2000)
        assert self._framed(view)

    def test_a_tiny_page_does_not_zoom_past_the_ceiling(self, qtbot,
                                                        registry):
        """fitInView answers with whatever the arithmetic gives it, and a
        220x120 KPI in a big window is well past what any other zoom in the
        app may reach."""
        _graph, _scene, view = self._view(
            qtbot, registry, tiles=((0.0, 0.0, 220.0, 120.0),),
            size=(1600, 1000))
        view.set_fit_to_window(True)
        self._fit_now(view)
        assert view.zoom == pytest.approx(ZOOM_MAX)

    def test_moving_a_tile_refits(self, qtbot, registry):
        graph, _scene, view = self._view(
            qtbot, registry,
            tiles=((0.0, 0.0, 300.0, 200.0), (400.0, 0.0, 300.0, 200.0)))
        view.set_fit_to_window(True)
        self._fit_now(view)
        graph.update_tile("p1", "t1", rect=(1400.0, 900.0, 300.0, 200.0))
        assert view._fit_timer.isActive()
        self._fit_now(view)
        assert self._framed(view)

    def test_a_maximized_tile_is_left_alone(self, qtbot, registry):
        """It is pinned to the viewport, not to the scene — refitting under
        it would only slide it off."""
        _graph, scene, view = self._view(
            qtbot, registry, tiles=((0.0, 0.0, 420.0, 320.0),), size=(800, 600))
        view.set_fit_to_window(True)
        self._fit_now(view)
        view.enter_fullscreen(scene.tile_items["t0"])
        before = view.zoom
        self._fit_now(view)
        assert view.zoom == before

    def test_an_empty_page_does_not_try(self, qtbot, registry):
        _graph, _scene, view = self._view(qtbot, registry, tiles=())
        view.set_fit_to_window(True)
        self._fit_now(view)
        assert view.zoom == pytest.approx(1.0)


# ------------------------------------------------------- what it turns off

class TestNavigationWhileScaling:
    def _scaled(self, window):
        page = add_page(window)
        add_tile(window)
        page.view.resize(600, 400)
        page.set_fit_to_window(True)
        fit_now(page)
        return page

    def test_zooming_by_hand_is_off(self, window):
        """It would fight the next resize, and "why did my zoom snap back?"
        has no good answer."""
        page = self._scaled(window)
        zoom = page.view.zoom
        page.view.set_zoom(1.0)
        assert page.view.zoom == zoom

    def test_the_indicator_says_so(self, window):
        page = self._scaled(window)
        window.page_bar.select_page("p1")
        window._set_page_fit_to_window("p1", True)
        assert not window._zoom_indicator.isEnabled()

    def test_switching_it_off_gives_navigation_back(self, window):
        page = self._scaled(window)
        page.set_fit_to_window(False)
        assert page.view.navigation_locked is False
        assert page.view.zoom  # whatever it was fitted to, kept

    def test_a_locked_page_stays_locked_when_scaling_stops(self, window):
        """Two modes share the one navigation lock, so neither may clear the
        other's."""
        page = self._scaled(window)
        page.set_view_mode(True)
        page.set_fit_to_window(False)
        assert page.view.navigation_locked is True

    def test_a_scaled_page_stays_locked_when_the_lock_comes_off(self, window):
        page = self._scaled(window)
        page.set_view_mode(True)
        page.set_view_mode(False)
        assert page.view.navigation_locked is True
        assert page.view.fit_to_window() is True


# --------------------------------------------------------------- the window

class TestWindowWiring:
    def test_the_menu_offers_it_and_ticks_it(self, window):
        add_page(window)
        window._set_page_fit_to_window("p1", True)
        menu = window.page_bar._context_menu(0, "p1")
        entry = next(a for a in menu.actions()
                     if a.text() == "Scale to fit the window")
        assert entry.isCheckable() and entry.isChecked()

    def test_a_report_page_is_not_offered_it(self, window):
        """A report already sits on a page of a declared size."""
        window.undo_stack.push(AddPageCommand(
            window.graph, Page(id="r1", title="Doc", kind="report")))
        menu = window.page_bar._context_menu(0, "r1")
        assert not any(a.text() == "Scale to fit the window"
                       for a in menu.actions())

    def test_the_menu_reaches_the_model_and_the_widget(self, window):
        page = add_page(window)
        window.page_bar.set_fit_to_window_requested.emit("p1", True)
        assert window.graph.pages["p1"].fit_to_window is True
        assert page.fit_to_window() is True

    def test_it_is_undoable(self, window):
        page = add_page(window)
        window.page_bar.set_fit_to_window_requested.emit("p1", True)
        window.undo_stack.undo()
        assert window.graph.pages["p1"].fit_to_window is False
        assert page.fit_to_window() is False

    def test_asking_for_what_it_already_is_adds_no_step(self, window):
        add_page(window)
        before = window.undo_stack.count()
        window._set_page_fit_to_window("p1", False)
        assert window.undo_stack.count() == before

    def test_a_page_saved_scaling_opens_that_way(self, window):
        window.undo_stack.push(AddPageCommand(
            window.graph, Page(id="p9", title="B", fit_to_window=True)))
        assert window._dashboard_pages["p9"].fit_to_window() is True
