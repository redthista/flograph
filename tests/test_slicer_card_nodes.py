"""The interactive viz cards: Slicer (checkbox filter that re-runs the
visuals downstream), Card (big painted KPI value) and Table Spec (spec grid
on the canvas)."""
import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QApplication

from flograph.core import Graph, NodeRegistry, Page, Tile
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.dashboard import default_tile_port, default_tile_size
from flograph.ui.mainwindow import MainWindow

REGIONS = {"columns": ["region", "units"],
           "rows": [["north", "10"], ["south", "20"], ["north", "30"]]}


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def env(qtbot, registry):
    graph = Graph()
    stack = QUndoStack()
    scene = NodeGraphScene(graph, stack, registry=registry)
    return graph, stack, scene


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    yield win
    # deterministic teardown: dispose dashboard pages (core events hold
    # strong refs to their scenes) and drain deferred deletions now, while
    # the window is intact — leaving them to a later test's event loop is
    # what flips the suite's pre-existing teardown segfault
    for page in list(win._dashboard_pages.values()):
        page.dispose()
    win.close()
    QApplication.processEvents()


def _add_sliced_flow(win):
    """Table -> Slicer(region) -> Show Table, returning the three nodes."""
    source = win.registry.instantiate("flograph.io.table", pos=(0, 0))
    slicer = win.registry.instantiate("flograph.viz.slicer", pos=(400, 0))
    shown = win.registry.instantiate("flograph.viz.show_table", pos=(800, 0))
    for node in (source, slicer, shown):
        win.graph.add_node(node)
    win.graph.set_param(source.id, "data", json.dumps(REGIONS))
    win.graph.set_param(slicer.id, "column", "region")
    win.graph.connect(source.id, "table", slicer.id, "table")
    win.graph.connect(slicer.id, "table", shown.id, "table")
    return source, slicer, shown


class TestSlicerCard:
    def test_item_is_a_resizable_widget_card(self, env, registry):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.viz.slicer"))
        item = scene.node_items[node.id]
        assert item.slicer
        assert item._slicer_list is not None
        assert item._slicer_list.isHidden()  # placeholder until a run

    def test_options_populate_after_a_run(self, qtbot, window):
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        widget = win.scene.node_items[slicer.id]._slicer_list
        texts = [widget.item(i).text() for i in range(widget.count())]
        assert texts == ["north", "south"]

    def test_tick_commits_param_and_reruns_downstream(self, qtbot, window):
        win = window
        _source, slicer, shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()

        widget = win.scene.node_items[slicer.id]._slicer_list
        # ticking "north" commits the selection and auto-runs downstream
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            widget.item(0).setCheckState(Qt.Checked)

        assert json.loads(win.graph.nodes[slicer.id].params["selected"]) \
            == ["north"]
        filtered = win.engine.cache.get(shown.id).outputs["table"]
        assert list(filtered["region"]) == ["north", "north"]
        # untick via undo: the param rolls back and the checks resync
        win.undo_stack.undo()
        assert win.graph.nodes[slicer.id].params["selected"] == ""
        assert widget.item(0).checkState() == Qt.Unchecked

    def test_single_mode_radio_behaviour(self, qtbot, window):
        win = window
        _source, slicer, shown = _add_sliced_flow(win)
        win.graph.set_param(slicer.id, "mode", "single")
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()

        widget = win.scene.node_items[slicer.id]._slicer_list
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            widget.item(0).setCheckState(Qt.Checked)  # "north"
        assert json.loads(win.graph.nodes[slicer.id].params["selected"]) \
            == ["north"]

        # ticking a second value clears the first — only one at a time
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            widget.item(1).setCheckState(Qt.Checked)  # "south"
        assert widget.item(0).checkState() == Qt.Unchecked
        assert json.loads(win.graph.nodes[slicer.id].params["selected"]) \
            == ["south"]
        filtered = win.engine.cache.get(shown.id).outputs["table"]
        assert list(filtered["region"]) == ["south"]

        # clicking the ticked value again clears the selection entirely
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            widget.item(1).setCheckState(Qt.Unchecked)
        assert win.graph.nodes[slicer.id].params["selected"] == ""

    def test_switching_to_single_mode_trims_a_multi_selection(
            self, qtbot, window):
        """Flipping the "Selection" param from multi to single with two
        values already ticked must trim to one — otherwise the card would
        keep showing both ticked while run() (which only honours the first
        in single mode) filters on just one, a silent card/data mismatch."""
        win = window
        _source, slicer, shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        widget = win.scene.node_items[slicer.id]._slicer_list
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            widget.select_all()  # both "north" and "south" ticked
        assert widget.selected_values() == ["north", "south"]

        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.graph.set_param(slicer.id, "mode", "single")

        assert widget.selected_values() == ["north"]
        assert json.loads(win.graph.nodes[slicer.id].params["selected"]) \
            == ["north"]
        filtered = win.engine.cache.get(shown.id).outputs["table"]
        assert list(filtered["region"]) == ["north", "north"]

    def test_search_filter_hides_without_dropping_ticks(self, qtbot, window):
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()

        item = win.scene.node_items[slicer.id]
        widget = item._slicer_list
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            widget.item(0).setCheckState(Qt.Checked)  # tick "north"

        widget.set_filter("south")
        assert widget.item(0).isHidden()  # "north" is filtered out…
        assert widget.item(0).checkState() == Qt.Checked  # …but still ticked
        assert widget.selected_values() == ["north"]  # hidden rows still count

        widget.set_filter("")
        assert not widget.item(0).isHidden()

    def test_filter_survives_the_rerun_a_tick_triggers(self, qtbot, window):
        """Ticking a value re-runs the slicer, which repopulates the list
        from the freshly-cached upstream table (set_slicer_options ->
        set_options -> clear() + rebuild) — an active search must not be
        silently dropped by that rebuild."""
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()

        widget = win.scene.node_items[slicer.id]._slicer_list
        widget.set_filter("north")
        assert widget.item(1).isHidden()  # "south" filtered out

        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            widget.item(0).setCheckState(Qt.Checked)  # tick "north" (visible)

        # the rebuild the tick triggered must not have cleared the filter
        assert widget.item(1).isHidden()
        assert widget.item(0).checkState() == Qt.Checked

    def test_select_all_and_clear_all_respect_the_filter(self, qtbot, window):
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()

        widget = win.scene.node_items[slicer.id]._slicer_list
        widget.set_filter("north")
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            widget.select_all()
        assert widget.selected_values() == ["north"]  # "south" stayed hidden

        widget.set_filter("")
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            widget.clear_all()
        assert widget.selected_values() == []

    def test_toolbar_hides_select_all_in_single_mode(self, qtbot):
        from flograph.ui.slicer_list import SlicerListWidget, SlicerToolbar
        target = SlicerListWidget()
        toolbar = SlicerToolbar(target)
        qtbot.addWidget(toolbar)
        assert not toolbar._select_all.isHidden()
        toolbar.set_mode("single")
        assert toolbar._select_all.isHidden()
        toolbar.set_mode("multi")
        assert not toolbar._select_all.isHidden()

    def test_mode_syncs_to_card_after_a_run(self, qtbot, window):
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        win.graph.set_param(slicer.id, "mode", "single")
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        item = win.scene.node_items[slicer.id]
        assert item._slicer_list._mode == "single"
        assert item._slicer_toolbar._select_all.isHidden()

    def test_toolbar_count_label_tracks_ticks(self, qtbot, window):
        win = window
        _source, slicer, _shown = _add_sliced_flow(win)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        item = win.scene.node_items[slicer.id]
        assert item._slicer_toolbar._count.text() == "0/2"

        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            item._slicer_list.item(0).setCheckState(Qt.Checked)
        assert item._slicer_toolbar._count.text() == "1/2"


class TestKpiCard:
    def test_value_lands_on_the_item_after_a_run(self, qtbot, window):
        win = window
        source = win.registry.instantiate("flograph.io.table", pos=(0, 0))
        card = win.registry.instantiate("flograph.viz.card", pos=(400, 0))
        for node in (source, card):
            win.graph.add_node(node)
        win.graph.set_param(source.id, "data", json.dumps(REGIONS))
        win.graph.set_param(card.id, "column", "units")
        win.graph.connect(source.id, "table", card.id, "table")

        item = win.scene.node_items[card.id]
        assert not item._kpi_has_value
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        assert item._kpi_has_value
        assert item._kpi_value == 60
        assert item._kpi_text() == "60"

    def test_text_honours_format_and_defaults(self, env, registry):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.viz.card"))
        item = scene.node_items[node.id]
        item.set_card_value(1234567)
        assert item._kpi_text() == "1,234,567"
        graph.set_param(node.id, "format", ",.2f")
        assert item._kpi_text() == "1,234,567.00"
        item.set_card_value("n/a")  # non-numeric value with a numeric format
        assert item._kpi_text() == "n/a"

    def test_caption_falls_back_to_aggregation_of_column(self, env, registry):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flograph.viz.card"))
        graph.set_param(node.id, "column", "units")
        item = scene.node_items[node.id]
        assert item._kpi_label() == "Sum of units"
        graph.set_param(node.id, "label", "Total units")
        assert item._kpi_label() == "Total units"


def _add_tile(win, page_id: str, node, at=(0.0, 0.0)) -> Tile:
    width, height = default_tile_size(node)
    tile = Tile(id=f"tile-{node.id}", node_id=node.id,
                port=default_tile_port(node),
                rect=(at[0], at[1], width, height))
    win.graph.add_tile(page_id, tile)
    return tile


class TestDashboardTiles:
    def _page(self, win) -> str:
        page = Page(id="p1", title="Page 1")
        win.graph.add_page(page)  # mainwindow builds the DashboardPage
        return page.id

    def test_kpi_tile_paints_the_cached_value(self, qtbot, window):
        win = window
        source = win.registry.instantiate("flograph.io.table", pos=(0, 0))
        card = win.registry.instantiate("flograph.viz.card", pos=(400, 0))
        for node in (source, card):
            win.graph.add_node(node)
        win.graph.set_param(source.id, "data", json.dumps(REGIONS))
        win.graph.set_param(card.id, "column", "units")
        win.graph.connect(source.id, "table", card.id, "table")

        page_id = self._page(win)
        tile = _add_tile(win, page_id, card)
        item = win._dashboard_pages[page_id].scene.tile_items[tile.id]
        assert not item._kpi_has_value
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        assert item._kpi_has_value
        assert item._kpi_value == 60

    def test_slicer_tile_ticks_filter_and_rerun_downstream(
            self, qtbot, window):
        win = window
        _source, slicer, shown = _add_sliced_flow(win)
        page_id = self._page(win)
        tile = _add_tile(win, page_id, slicer)
        item = win._dashboard_pages[page_id].scene.tile_items[tile.id]

        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        widget = item._slicer_widget
        texts = [widget.item(i).text() for i in range(widget.count())]
        assert texts == ["north", "south"]

        # ticking on the dashboard commits the param and re-runs downstream
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            widget.item(1).setCheckState(Qt.Checked)
        assert json.loads(win.graph.nodes[slicer.id].params["selected"]) \
            == ["south"]
        filtered = win.engine.cache.get(shown.id).outputs["table"]
        assert list(filtered["region"]) == ["south"]
        # the canvas card's checkboxes follow the same param
        canvas_list = win.scene.node_items[slicer.id]._slicer_list
        assert canvas_list.selected_values() == ["south"]
        # undo unticks the tile without emitting a new commit
        win.undo_stack.undo()
        assert widget.selected_values() == []


class TestTableSpecCard:
    def test_spec_lands_on_the_table_viewer_card(self, qtbot, window):
        win = window
        source = win.registry.instantiate("flograph.io.table", pos=(0, 0))
        spec = win.registry.instantiate("flograph.viz.table_spec", pos=(400, 0))
        for node in (source, spec):
            win.graph.add_node(node)
        win.graph.set_param(source.id, "data", json.dumps(REGIONS))
        win.graph.connect(source.id, "table", spec.id, "table")

        item = win.scene.node_items[spec.id]
        assert item.table_viewer  # reuses the whole Show Table card path
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_all()
        model = item._table_viewer_view.model()
        assert model is not None
        assert model.rowCount() == 2  # one spec row per source column
