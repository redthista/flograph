"""App view: dashboard page tabs under the canvas, live tiles, and the
add-tile paths (drop + context-menu helpers).

Settings kept off the real store (avoid polluting the developer's actual
flograph.conf) -- see test_lod_settings.py's fixture of the same name."""
import pandas as pd
import pytest
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsItem, QVBoxLayout

from flograph.core import NodeRegistry, Page, Tile
from flograph.ui import mainwindow as mod
from flograph.ui.commands import AddPageCommand, AddTileCommand
from flograph.ui.dashboard.tile_item import MISSING_NODE, RUN_PROMPT
from flograph.ui.dashboard.visuals_list import TILE_NODE_MIME
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


def add_page(window, page_id="p1", title="Board"):
    window.undo_stack.push(
        AddPageCommand(window.graph, Page(id=page_id, title=title)))
    return window.graph.pages[page_id]


def add_show_table(window, pos=(0, 0)):
    node = window.registry.instantiate("flograph.viz.show_table", pos=pos)
    window.graph.add_node(node)
    return node


def add_tile(window, node, page_id="p1", tile_id="t1", port="table"):
    window.undo_stack.push(AddTileCommand(
        window.graph, page_id, Tile(id=tile_id, node_id=node.id, port=port)))
    return window._dashboard_pages[page_id].scene.tile_items[tile_id]


class TestPageTabs:
    def test_add_page_creates_tab_and_dashboard(self, window):
        window._add_page()
        assert len(window.graph.pages) == 1
        page_id = next(iter(window.graph.pages))
        assert window.graph.pages[page_id].title == "Page 1"
        # Model + page + "+"
        assert window.page_bar.count() == 3
        assert window.page_bar.tabText(1) == "Page 1"
        assert page_id in window._dashboard_pages
        # _add_page selects the new page
        assert (window._canvas_stack.currentWidget()
                is window._dashboard_pages[page_id])

        window.undo_stack.undo()
        assert not window.graph.pages
        assert window.page_bar.count() == 2
        assert window._canvas_stack.currentWidget() is window.view

    def test_rename_updates_tab_and_graph(self, window):
        page = add_page(window)
        window._rename_page(page.id, "Revenue")
        assert window.graph.pages[page.id].title == "Revenue"
        assert window.page_bar.tabText(1) == "Revenue"
        window.undo_stack.undo()
        assert window.page_bar.tabText(1) == "Board"

    def test_delete_page_without_tiles_needs_no_confirm(self, window):
        page = add_page(window)
        window._delete_page(page.id)
        assert not window.graph.pages
        assert window.page_bar.count() == 2

    def test_select_page_switches_stack(self, window):
        page = add_page(window)
        window.page_bar.select_page(page.id)
        assert (window._canvas_stack.currentWidget()
                is window._dashboard_pages[page.id])
        window.page_bar.select_page(None)
        assert window._canvas_stack.currentWidget() is window.view

    def test_dashboard_page_hides_model_only_docks(self, window):
        docks = [window.library_dock, window.properties_dock,
                 window.editor_dock, window.inspector_dock, window.log_dock]
        page = add_page(window)
        assert all(dock.isVisibleTo(window) for dock in docks)

        window.page_bar.select_page(page.id)
        assert not any(dock.isVisibleTo(window) for dock in docks)
        # the page bar itself is the page switcher -- it must stay put
        assert window.page_bar.isVisibleTo(window)

        window.page_bar.select_page(None)
        assert all(dock.isVisibleTo(window) for dock in docks)

    def test_page_bar_position_default_is_top(self, window):
        layout = window.centralWidget().layout()
        assert isinstance(layout, QVBoxLayout)
        assert layout.itemAt(0).widget() is window.page_bar
        assert layout.itemAt(1).widget() is window._dock_host
        assert window.log_dock in window._dock_host.tabifiedDockWidgets(
            window.inspector_dock)

    def test_set_page_bar_position_moves_it_and_preserves_tab_groups(self, window):
        window.set_page_bar_position("bottom")
        layout = window.centralWidget().layout()
        assert isinstance(layout, QVBoxLayout)
        assert layout.itemAt(0).widget() is window._dock_host
        assert layout.itemAt(1).widget() is window.page_bar

        window.set_page_bar_position("top")
        layout = window.centralWidget().layout()
        assert isinstance(layout, QVBoxLayout)
        assert layout.itemAt(0).widget() is window.page_bar
        assert layout.itemAt(1).widget() is window._dock_host

        window.set_page_bar_position("bottom")
        layout = window.centralWidget().layout()
        assert isinstance(layout, QVBoxLayout)
        assert layout.itemAt(0).widget() is window._dock_host
        assert layout.itemAt(1).widget() is window.page_bar

        # switching around never disturbed the pre-existing tab groups
        assert window.log_dock in window._dock_host.tabifiedDockWidgets(
            window.inspector_dock)
        assert window.editor_dock in window._dock_host.tabifiedDockWidgets(
            window.properties_dock)

    def test_page_bar_position_persists_to_settings(self, window):
        window.set_page_bar_position("bottom")
        assert window.settings.value("canvas/page_bar_position") == "bottom"


class TestLibraryDockMinimumWidth:
    """The Node Library dock had no floor, so a saved dock_state that ever
    pinned it thin (e.g. from before this floor existed) stayed thin forever
    -- restoreState() can only shrink a dock down to its widget's minimum."""

    def test_library_panel_has_a_minimum_width(self, window):
        assert window.library_panel.minimumWidth() >= 180

    def test_restoring_a_thin_saved_layout_gets_clamped_up(
            self, qtbot, registry):
        first = mod.MainWindow(registry)
        first.confirm_close = False
        qtbot.addWidget(first)
        first.resize(1400, 900)
        first.show()
        qtbot.wait(10)
        first._dock_host.resizeDocks([first.library_dock], [70], Qt.Horizontal)
        qtbot.wait(10)
        first._save_window_state()
        first.close()

        second = mod.MainWindow(registry)
        second.confirm_close = False
        qtbot.addWidget(second)
        second.resize(1400, 900)
        second.show()
        qtbot.wait(10)
        assert second.library_dock.width() >= 180


class TestVisualsPanelToggle:
    def test_defaults_to_collapsed(self, window):
        """A dashboard is for looking at: the page opens as canvas."""
        page = add_page(window)
        widget = window._dashboard_pages[page.id]
        assert not widget._side.isVisibleTo(widget)
        assert widget._toggle_btn.arrowType() == Qt.ArrowType.RightArrow

    def test_toggle_button_restores_and_hides_the_panel(self, window):
        page = add_page(window)
        widget = window._dashboard_pages[page.id]

        widget._toggle_btn.click()
        assert widget._side.isVisibleTo(widget)

        widget._toggle_btn.click()
        assert not widget._side.isVisibleTo(widget)

    def test_set_visuals_visible_updates_arrow_direction(self, window):
        page = add_page(window)
        widget = window._dashboard_pages[page.id]

        widget.set_visuals_visible(False)
        assert widget._toggle_btn.arrowType() == Qt.ArrowType.RightArrow

        widget.set_visuals_visible(True)
        assert widget._toggle_btn.arrowType() == Qt.ArrowType.LeftArrow

    def test_reopening_restores_the_panel_width(self, window, qtbot):
        """Hidden from the start, the splitter must still know how wide the
        panel is -- otherwise it comes back as an unusable sliver."""
        page = add_page(window)
        widget = window._dashboard_pages[page.id]
        widget.resize(1000, 600)
        widget.set_visuals_visible(True)
        qtbot.wait(10)
        assert widget._splitter.sizes()[0] >= 100

    def test_the_toggle_is_per_page(self, window):
        """Opening the panel on one page does not open it on another."""
        first = window._dashboard_pages[add_page(window, "p1").id]
        second = window._dashboard_pages[add_page(window, "p2", "Two").id]
        first.set_visuals_visible(True)
        assert not second._side.isVisibleTo(second)


class TestVisualsPanelDefaultIsRemembered:
    def test_a_new_page_follows_the_last_toggle(self, window):
        first = window._dashboard_pages[add_page(window, "p1").id]
        first.set_visuals_visible(True)
        second = window._dashboard_pages[add_page(window, "p2", "Two").id]
        assert second._side.isVisibleTo(second)

    def test_the_window_records_it(self, window):
        assert window.visuals_visible is False
        window._dashboard_pages[add_page(window).id].set_visuals_visible(True)
        assert window.visuals_visible is True

    def test_construction_does_not_overwrite_the_stored_default(self, window):
        """Applying the start state must not look like a user toggle."""
        window.visuals_visible = True
        window._dashboard_pages[add_page(window).id]
        assert window.visuals_visible is True

    def test_it_survives_a_restart(self, window, registry, qtbot):
        window._dashboard_pages[add_page(window).id].set_visuals_visible(True)
        reopened = MainWindow(registry)
        reopened.confirm_close = False
        qtbot.addWidget(reopened)
        assert reopened.visuals_visible is True
        assert reopened._dashboard_pages[
            add_page(reopened, "p2", "Two").id]._side.isVisibleTo(
                reopened._dashboard_pages["p2"])


class TestTiles:
    def test_tile_lifecycle_and_live_update(self, window):
        add_page(window)
        node = add_show_table(window)
        item = add_tile(window, node)
        assert item._placeholder.text() == RUN_PROMPT

        df = pd.DataFrame({"a": [1, 2], "b": [3.0, 4.0]})
        window.engine.cache.set(node.id, {"table": df}, 0.01)
        window.graph.mark_clean(node.id)
        window.engine.node_succeeded.emit(node.id)
        assert item._table_view.model() is not None
        assert item._table_view.model()._df is df
        assert not item._is_stale()

        window.undo_stack.undo()  # remove the tile
        assert not window._dashboard_pages["p1"].scene.tile_items
        window.undo_stack.redo()
        item = window._dashboard_pages["p1"].scene.tile_items["t1"]
        assert item._table_view.model() is not None  # content restored

        window.graph.mark_dirty(node.id)  # evicts cache, content stays shown
        assert item._is_stale()

    def test_deleted_node_leaves_revivable_placeholder(self, window):
        from flograph.ui.commands import RemoveSelectionCommand
        add_page(window)
        node = add_show_table(window)
        item = add_tile(window, node)

        window.undo_stack.push(
            RemoveSelectionCommand(window.graph, [node.id]))
        assert item._placeholder.text() == MISSING_NODE
        assert item._placeholder.isVisibleTo(item._placeholder.parentWidget())

        window.undo_stack.undo()  # node back (cache was evicted on delete)
        assert item._placeholder.text() == RUN_PROMPT
        window.engine.cache.set(
            node.id, {"table": pd.DataFrame({"a": [1]})}, 0.01)
        window.engine.node_succeeded.emit(node.id)
        assert item._table_view.model() is not None

    def test_figure_tile_shows_figure(self, window):
        from matplotlib.figure import Figure
        add_page(window)
        node = window.registry.instantiate("flograph.viz.show_plot", pos=(0, 0))
        window.graph.add_node(node)
        item = add_tile(window, node, port="figure")

        fig = Figure()
        fig.add_subplot(111).plot([1, 2], [3, 4])
        window.engine.cache.set(node.id, {"figure": fig}, 0.01)
        window.engine.node_succeeded.emit(node.id)
        assert item._figure_view is not None
        assert item._figure_view._canvas is not None  # a live FigureCanvas

    def test_button_tile_is_the_bare_button_and_fires(self, qtbot, window,
                                                      monkeypatch):
        """A button tile IS the button — canvas size, painted face, no card
        chrome — and clicks fire only while unselected, like on the canvas."""
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtTest import QTest

        from flograph.ui.dashboard.dashboard_view import DashboardView

        add_page(window)
        node = window.registry.instantiate("flograph.util.action_button",
                                           pos=(0, 0))
        window.graph.add_node(node)
        window.graph.set_param(node.id, "action", "Run whole flow")
        window.graph.set_param(node.id, "clear_cache", False)
        other = add_show_table(window)  # something for the flow to run

        # the drop path sizes button tiles like the canvas node (150x50)
        page = window._dashboard_pages["p1"]
        page.view.tile_dropped.emit(node.id, QPointF(0, 0))
        tile = next(t for t in window.graph.pages["p1"].tiles.values()
                    if t.node_id == node.id)
        assert tile.rect[2:] == (150.0, 50.0)
        item = page.scene.tile_items[tile.id]
        assert not item._proxy.isVisible()  # no mini-window around it

        ran = []
        monkeypatch.setattr(window.engine, "run_targets",
                            lambda targets: ran.append(sorted(targets)))

        view = DashboardView(page.scene)
        qtbot.addWidget(view)
        view.resize(800, 600)
        view.show()
        center = view.mapFromScene(
            item.mapToScene(item.boundingRect().center()))
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, center)
        assert ran == [sorted([node.id, other.id])]

        item.setSelected(True)  # selected: click moves, never fires
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, center)
        assert len(ran) == 1

    def test_drop_path_creates_tile_with_default_port(self, window):
        add_page(window)
        node = add_show_table(window)
        view = window._dashboard_pages["p1"].view
        from PySide6.QtCore import QPointF
        view.tile_dropped.emit(node.id, QPointF(30, 40))
        tiles = window.graph.pages["p1"].tiles
        assert len(tiles) == 1
        tile = next(iter(tiles.values()))
        assert tile.node_id == node.id
        assert tile.port == "table"
        assert tile.rect[:2] == (30.0, 40.0)

    def test_add_to_new_page_is_one_undo_step(self, window):
        node = add_show_table(window)
        window._add_tile_on_new_page(node.id)
        assert len(window.graph.pages) == 1
        page = next(iter(window.graph.pages.values()))
        assert len(page.tiles) == 1
        window.undo_stack.undo()
        assert not window.graph.pages

    def test_table_input_node_can_be_dropped_and_shows_its_dataframe(
            self, window):
        """The Table node (IO folder, card='grid') is a data source, not a
        Show* visual, but it still has a real DataFrame output worth viewing
        on a dashboard — it should drop like any other tile-able node."""
        add_page(window)
        node = window.registry.instantiate("flograph.io.table", pos=(0, 0))
        window.graph.add_node(node)
        view = window._dashboard_pages["p1"].view
        from PySide6.QtCore import QPointF
        view.tile_dropped.emit(node.id, QPointF(0, 0))

        tiles = window.graph.pages["p1"].tiles
        assert len(tiles) == 1
        tile = next(iter(tiles.values()))
        assert tile.port == "table"

        item = window._dashboard_pages["p1"].scene.tile_items[tile.id]
        df = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
        window.engine.cache.set(node.id, {"table": df}, 0.01)
        window.engine.node_succeeded.emit(node.id)
        assert item._table_view is not None
        assert item._table_view.model() is not None
        assert item._table_view.model().rowCount() == 2


class TestVisualsList:
    def test_lists_only_tile_able_nodes_and_packs_node_id(self, window):
        add_page(window)
        shown = add_show_table(window)
        plain = window.registry.instantiate("flograph.util.constant", pos=(0, 0))
        window.graph.add_node(plain)

        visuals = window._dashboard_pages["p1"].visuals
        labels = [visuals.item(i).text() for i in range(visuals.count())]
        assert any(shown.label in text for text in labels)
        assert not any(plain.label in text for text in labels)

        mime = visuals.mimeData([visuals.item(0)])
        assert bytes(mime.data(TILE_NODE_MIME)).decode() == shown.id


class TestPersistence:
    def test_save_and_reopen_reproduces_pages(self, window, tmp_path):
        add_page(window)
        node = add_show_table(window)
        add_tile(window, node)
        path = str(tmp_path / "board.flograph")
        window._project_path = path
        assert window._save()

        from flograph.core import Graph
        window._replace_graph(Graph())
        assert not window.graph.pages
        assert not window._dashboard_pages

        assert window.open_path(path, confirm=False)
        assert list(window.graph.pages) == ["p1"]
        assert window.graph.pages["p1"].tiles["t1"].node_id == node.id
        assert "p1" in window._dashboard_pages
        assert "t1" in window._dashboard_pages["p1"].scene.tile_items
        assert window.page_bar.count() == 3


class TestTileFullscreen:
    """Maximizing one tile over the whole page (ideas.md #4): the tile is
    pinned to the viewport in scene coordinates, so it grows with the window
    and the embedded chart/table grows with it.

    Geometry assertions need a *shown* view -- a hidden QAbstractScrollArea
    never lays its viewport out, so a standalone DashboardView on the page's
    scene stands in for the (unshown) MainWindow, as elsewhere in this file."""

    def shown_view(self, window, qtbot, size=(900, 600)):
        from flograph.ui.dashboard.dashboard_view import DashboardView
        view = DashboardView(window._dashboard_pages["p1"].scene)
        qtbot.addWidget(view)
        view.resize(*size)
        view.show()
        qtbot.waitExposed(view)
        return view

    def viewport_rect(self, view):
        return view.mapToScene(view.viewport().rect()).boundingRect()

    def test_fills_the_viewport_and_hides_other_tiles(self, window, qtbot):
        add_page(window)
        node = add_show_table(window)
        item = add_tile(window, node)
        other = add_tile(window, node, tile_id="t2")
        rect_before = window.graph.pages["p1"].tiles["t1"].rect
        view = self.shown_view(window, qtbot)

        view.enter_fullscreen(item)
        assert item.is_fullscreen
        assert view.fullscreen_tile is item
        rect = self.viewport_rect(view)
        assert item._size[0] == pytest.approx(rect.width() - 12.0)
        assert item._size[1] == pytest.approx(rect.height() - 12.0)
        assert item.pos().x() == pytest.approx(rect.left() + 6.0)
        assert item.pos().y() == pytest.approx(rect.top() + 6.0)
        assert not other.isVisible()
        # view state only -- the stored rect and the undo stack are untouched
        assert window.graph.pages["p1"].tiles["t1"].rect == rect_before
        assert not window.undo_stack.canRedo()

        view.toggle_fullscreen(item)
        assert not item.is_fullscreen
        assert view.fullscreen_tile is None
        assert other.isVisible()
        assert (item.pos().x(), item.pos().y(),
                *item._size) == pytest.approx(rect_before)

    def test_window_resize_grows_the_tile(self, window, qtbot):
        add_page(window)
        item = add_tile(window, add_show_table(window))
        view = self.shown_view(window, qtbot)
        view.enter_fullscreen(item)
        before = item._size

        view.resize(1400, 900)
        assert item._size[0] > before[0]
        assert item._size[1] > before[1]
        assert item._size[0] == pytest.approx(
            self.viewport_rect(view).width() - 12.0)
        # the content widget follows the item -- that is what makes an
        # embedded chart or table redraw at the new size
        assert item._proxy.geometry().width() == pytest.approx(
            item._size[0] - 2)

    def test_zoom_is_pinned_at_1_to_1_and_restored_on_exit(self, window, qtbot):
        add_page(window)
        item = add_tile(window, add_show_table(window))
        view = self.shown_view(window, qtbot)
        view.set_zoom(0.5)

        view.enter_fullscreen(item)
        assert view.zoom == pytest.approx(1.0)
        view.exit_fullscreen()
        assert view.zoom == pytest.approx(0.5)

    def test_escape_restores(self, window, qtbot):
        add_page(window)
        item = add_tile(window, add_show_table(window))
        view = self.shown_view(window, qtbot)
        view.enter_fullscreen(item)

        QTest.keyClick(view, Qt.Key_Escape)
        assert not item.is_fullscreen

    def test_wheel_does_not_zoom_while_maximized(self, window, qtbot):
        add_page(window)
        item = add_tile(window, add_show_table(window))
        view = self.shown_view(window, qtbot)
        view.enter_fullscreen(item)

        pos = view.viewport().rect().topLeft() + QPoint(4, 4)  # off the tile
        event = QWheelEvent(
            QPointF(pos), QPointF(view.viewport().mapToGlobal(pos)),
            QPoint(0, 0), QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
            Qt.NoScrollPhase, False)
        QApplication.sendEvent(view.viewport(), event)
        assert view.zoom == pytest.approx(1.0)

    def test_maximized_tile_cannot_be_moved_or_resized(self, window, qtbot):
        add_page(window)
        item = add_tile(window, add_show_table(window))
        self.shown_view(window, qtbot).enter_fullscreen(item)

        assert not item.flags() & QGraphicsItem.ItemIsMovable
        assert item._edge_at(QPointF(*item._size)) is None
        # a model-driven re-sync (undo of someone else's move) is ignored
        window.graph.pages["p1"].tiles["t1"].rect = (5.0, 5.0, 50.0, 50.0)
        item.sync_from_model()
        assert item._size[0] > 50.0

    def test_page_signal_toggles_and_frees_the_page_chrome(self, window):
        add_page(window)
        add_tile(window, add_show_table(window))
        page = window._dashboard_pages["p1"]
        page.set_visuals_visible(True)  # pages open collapsed; open it first

        page.scene.fullscreen_requested.emit("t1")
        assert page.view.fullscreen_tile is page.scene.tile_items["t1"]
        assert not page._side.isVisibleTo(page)
        assert not page._toggle_strip.isVisibleTo(page)

        page.scene.fullscreen_requested.emit("t1")
        assert page.view.fullscreen_tile is None
        assert page._side.isVisibleTo(page)
        assert page._toggle_strip.isVisibleTo(page)

    def test_maximizing_leaves_a_collapsed_panel_collapsed(self, window):
        """Stepping aside is not the user asking for the panel: it must not
        reopen on exit, nor emit the toggle signal that would rewrite the
        state new pages open with."""
        add_page(window)
        add_tile(window, add_show_table(window))
        page = window._dashboard_pages["p1"]
        toggled = []
        page.visuals_visibility_changed.connect(toggled.append)

        page.scene.fullscreen_requested.emit("t1")
        page.view.exit_fullscreen()
        assert not page._side.isVisibleTo(page)
        assert page._toggle_strip.isVisibleTo(page)
        assert page._visuals_visible is False
        assert toggled == []

    def test_tile_added_while_maximized_stays_hidden_until_exit(self, window):
        add_page(window)
        node = add_show_table(window)
        add_tile(window, node)
        page = window._dashboard_pages["p1"]
        page.scene.fullscreen_requested.emit("t1")

        late = add_tile(window, node, tile_id="t2")
        assert not late.isVisible()
        page.view.exit_fullscreen()
        assert late.isVisible()

    def test_deleting_the_maximized_tile_leaves_fullscreen(self, window):
        add_page(window)
        add_tile(window, add_show_table(window))
        page = window._dashboard_pages["p1"]
        page.scene.fullscreen_requested.emit("t1")

        page.scene.remove_tile("t1")
        assert page.view.fullscreen_tile is None
        assert page._toggle_strip.isVisibleTo(page)

    def test_deleting_the_node_keeps_the_restore_affordance(self, window):
        from flograph.ui.commands import RemoveSelectionCommand
        add_page(window)
        node = add_show_table(window)
        item = add_tile(window, node)
        window._dashboard_pages["p1"].scene.fullscreen_requested.emit("t1")

        window.undo_stack.push(
            RemoveSelectionCommand(window.graph, [node.id]))
        assert item.is_fullscreen
        assert item.can_fullscreen()  # the restore glyph is still painted

    def test_title_bar_glyph_and_double_click_toggle(self, window, qtbot):
        add_page(window)
        item = add_tile(window, add_show_table(window))
        view = self.shown_view(window, qtbot)
        requested = []
        view.scene().fullscreen_requested.connect(requested.append)

        glyph = view.mapFromScene(item.mapToScene(
            item._fs_button_rect().center()))
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, glyph)
        title = view.mapFromScene(item.mapToScene(QPointF(30.0, 12.0)))
        QTest.mouseDClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, title)
        assert requested == ["t1", "t1"]

    def test_button_tiles_do_not_maximize(self, window, qtbot):
        add_page(window)
        node = window.registry.instantiate("flograph.util.action_button",
                                           pos=(0, 0))
        window.graph.add_node(node)
        item = add_tile(window, node, port=None)

        assert not item.can_fullscreen()
        view = self.shown_view(window, qtbot)
        view.enter_fullscreen(item)
        assert view.fullscreen_tile is None
