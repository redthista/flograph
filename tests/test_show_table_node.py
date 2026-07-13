"""The Show Table card: an on-canvas live preview for dataframe-typed wires."""
import pandas as pd
import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry, PortType, can_connect
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.mainwindow import MainWindow


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


def test_show_table_is_registered_with_passthrough_ports(registry):
    spec = registry.get("flograph.viz.show_table")
    assert [p.name for p in spec.inputs] == ["table"]
    assert [p.name for p in spec.outputs] == ["table"]
    assert spec.inputs[0].type == PortType.DATAFRAME
    assert spec.outputs[0].type == PortType.DATAFRAME
    assert can_connect(PortType.DATAFRAME, spec.inputs[0].type)
    assert spec.param("width") is not None
    assert spec.param("height") is not None


def test_show_table_runs_as_passthrough(registry):
    from flograph.core import compile_run
    from tests.conftest import FakeContext

    spec = registry.get("flograph.viz.show_table")
    run = compile_run(spec.source, "test-show-table")
    sentinel = object()
    out = run(FakeContext(params=spec.default_params()), table=sentinel)
    assert out == {"table": sentinel}


def test_show_table_item_embeds_a_table_view_with_placeholder(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.viz.show_table"))
    item = scene.node_items[node.id]
    assert item.table_viewer
    assert item._table_viewer_view is not None
    assert item._table_viewer_placeholder is not None
    assert item._table_viewer_placeholder.isVisible()
    assert item._table_viewer_view.isHidden()
    assert list(item.input_ports) == ["table"]
    assert list(item.output_ports) == ["table"]


def test_show_table_set_table_data_swaps_placeholder_for_grid(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.viz.show_table"))
    item = scene.node_items[node.id]

    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    item.set_table_data(df)
    assert item._table_viewer_view.isVisible()
    assert item._table_viewer_placeholder.isHidden()
    assert item._table_viewer_view.model().rowCount() == 2

    item.set_table_data(None)
    assert item._table_viewer_view.isHidden()
    assert item._table_viewer_placeholder.isVisible()


def test_show_table_resize_updates_width_and_height(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.viz.show_table"))
    item = scene.node_items[node.id]
    graph.set_param(node.id, "width", 600)
    graph.set_param(node.id, "height", 400)
    assert item.width == 600.0
    assert item.body_height == 400.0
    graph.set_param(node.id, "width", 10)  # clamped to minimum
    assert item.width == 260.0


def test_show_table_scale_param_zooms_the_embedded_view(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.viz.show_table"))
    item = scene.node_items[node.id]
    proxy = item._table_viewer_proxy
    assert proxy.scale() == 1.0

    graph.set_param(node.id, "scale", 200)
    rect = item._table_viewer_proxy_rect()
    assert proxy.scale() == 2.0
    # the widget gets half the logical pixels; the transform doubles them
    # back, so the card footprint is unchanged but content draws 2x larger
    assert proxy.size().width() == pytest.approx(rect.width() / 2)
    assert proxy.size().height() == pytest.approx(rect.height() / 2)

    graph.set_param(node.id, "scale", 5)  # clamped to 25%
    assert proxy.scale() == 0.25


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


def test_running_the_graph_pushes_the_table_onto_the_canvas_card(qtbot, window):
    import json

    win = window
    show = win.registry.instantiate("flograph.viz.show_table", pos=(300, 0))
    table = win.registry.instantiate("flograph.io.table", pos=(-300, 0))
    win.graph.add_node(table)
    win.graph.add_node(show)
    win.graph.set_param(table.id, "data", json.dumps({
        "columns": ["x", "y"], "rows": [["1", "2"], ["2", "4"], ["3", "9"]],
    }))
    win.graph.connect(table.id, "table", show.id, "table")

    item = win.scene.node_items[show.id]
    assert item._table_viewer_placeholder.isVisible()

    with qtbot.waitSignal(win.engine.run_finished, timeout=20000) as blocker:
        win.engine.run_all()

    assert blocker.args[0], "run finished with a node failure"
    assert item._table_viewer_view.isVisible()
    assert item._table_viewer_placeholder.isHidden()
    assert item._table_viewer_view.model().rowCount() == 3
