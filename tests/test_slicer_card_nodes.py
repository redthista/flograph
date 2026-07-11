"""The interactive viz cards: Slicer (checkbox filter that re-runs the
visuals downstream), Card (big painted KPI value) and Table Spec (spec grid
on the canvas)."""
import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QUndoStack

from flopy.core import Graph, NodeRegistry
from flopy.ui.canvas import NodeGraphScene
from flopy.ui.mainwindow import MainWindow

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
    return win


def _add_sliced_flow(win):
    """Table -> Slicer(region) -> Show Table, returning the three nodes."""
    source = win.registry.instantiate("flopy.io.table", pos=(0, 0))
    slicer = win.registry.instantiate("flopy.viz.slicer", pos=(400, 0))
    shown = win.registry.instantiate("flopy.viz.show_table", pos=(800, 0))
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
        node = graph.add_node(registry.instantiate("flopy.viz.slicer"))
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


class TestKpiCard:
    def test_value_lands_on_the_item_after_a_run(self, qtbot, window):
        win = window
        source = win.registry.instantiate("flopy.io.table", pos=(0, 0))
        card = win.registry.instantiate("flopy.viz.card", pos=(400, 0))
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
        node = graph.add_node(registry.instantiate("flopy.viz.card"))
        item = scene.node_items[node.id]
        item.set_card_value(1234567)
        assert item._kpi_text() == "1,234,567"
        graph.set_param(node.id, "format", ",.2f")
        assert item._kpi_text() == "1,234,567.00"
        item.set_card_value("n/a")  # non-numeric value with a numeric format
        assert item._kpi_text() == "n/a"

    def test_caption_falls_back_to_aggregation_of_column(self, env, registry):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate("flopy.viz.card"))
        graph.set_param(node.id, "column", "units")
        item = scene.node_items[node.id]
        assert item._kpi_label() == "Sum of units"
        graph.set_param(node.id, "label", "Total units")
        assert item._kpi_label() == "Total units"


class TestTableSpecCard:
    def test_spec_lands_on_the_table_viewer_card(self, qtbot, window):
        win = window
        source = win.registry.instantiate("flopy.io.table", pos=(0, 0))
        spec = win.registry.instantiate("flopy.viz.table_spec", pos=(400, 0))
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
