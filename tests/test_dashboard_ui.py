"""App view: dashboard page tabs under the canvas, live tiles, and the
add-tile paths (drop + context-menu helpers)."""
import pandas as pd
import pytest

from flopy.core import NodeRegistry, Page, Tile
from flopy.ui.commands import AddPageCommand, AddTileCommand
from flopy.ui.dashboard.tile_item import MISSING_NODE, RUN_PROMPT
from flopy.ui.dashboard.visuals_list import TILE_NODE_MIME
from flopy.ui.mainwindow import MainWindow


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
    node = window.registry.instantiate("flopy.viz.show_table", pos=pos)
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
        from flopy.ui.commands import RemoveSelectionCommand
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
        node = window.registry.instantiate("flopy.viz.show_plot", pos=(0, 0))
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

        from flopy.ui.dashboard.dashboard_view import DashboardView

        add_page(window)
        node = window.registry.instantiate("flopy.util.action_button",
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


class TestVisualsList:
    def test_lists_only_tile_able_nodes_and_packs_node_id(self, window):
        add_page(window)
        shown = add_show_table(window)
        plain = window.registry.instantiate("flopy.util.constant", pos=(0, 0))
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
        path = str(tmp_path / "board.flopy")
        window._project_path = path
        assert window._save()

        from flopy.core import Graph
        window._replace_graph(Graph())
        assert not window.graph.pages
        assert not window._dashboard_pages

        assert window.open_path(path, confirm=False)
        assert list(window.graph.pages) == ["p1"]
        assert window.graph.pages["p1"].tiles["t1"].node_id == node.id
        assert "p1" in window._dashboard_pages
        assert "t1" in window._dashboard_pages["p1"].scene.tile_items
        assert window.page_bar.count() == 3
