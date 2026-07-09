"""The Show Figure card: an on-canvas live preview for figure-typed wires."""
import pytest
from PySide6.QtGui import QUndoStack

from flopy.core import Graph, NodeRegistry, PortType, can_connect
from flopy.ui.canvas import NodeGraphScene
from flopy.ui.mainwindow import MainWindow


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


def test_show_figure_is_registered_with_passthrough_ports(registry):
    spec = registry.get("flopy.viz.show_figure")
    assert [p.name for p in spec.inputs] == ["figure"]
    assert [p.name for p in spec.outputs] == ["figure"]
    assert spec.inputs[0].type == PortType.FIGURE
    assert spec.outputs[0].type == PortType.FIGURE
    assert can_connect(PortType.FIGURE, spec.inputs[0].type)
    assert spec.param("width") is not None
    assert spec.param("height") is not None


def test_show_figure_runs_as_passthrough(registry):
    from flopy.core import compile_run
    from tests.conftest import FakeContext

    spec = registry.get("flopy.viz.show_figure")
    run = compile_run(spec.source, "test-show-figure")
    sentinel = object()
    out = run(FakeContext(params=spec.default_params()), figure=sentinel)
    assert out == {"figure": sentinel}


def test_show_figure_item_embeds_a_figure_view_with_placeholder(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flopy.viz.show_figure"))
    item = scene.node_items[node.id]
    assert item.figure_card
    assert item._figure_view is not None
    assert item._figure_placeholder is not None
    assert item._figure_placeholder.isVisible()
    assert item._figure_view.isHidden()
    assert list(item.input_ports) == ["figure"]
    assert list(item.output_ports) == ["figure"]


def test_show_figure_set_figure_swaps_placeholder_for_canvas(env, registry):
    from matplotlib.figure import Figure

    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flopy.viz.show_figure"))
    item = scene.node_items[node.id]

    fig = Figure()
    fig.add_subplot().plot([1, 2, 3])
    item.set_figure(fig)
    assert item._figure_view.isVisible()
    assert item._figure_placeholder.isHidden()

    item.set_figure(None)
    assert item._figure_view.isHidden()
    assert item._figure_placeholder.isVisible()


def test_show_figure_resize_updates_width_and_height(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flopy.viz.show_figure"))
    item = scene.node_items[node.id]
    graph.set_param(node.id, "width", 600)
    graph.set_param(node.id, "height", 400)
    assert item.width == 600.0
    assert item.body_height == 400.0
    graph.set_param(node.id, "width", 10)  # clamped to minimum
    assert item.width == 260.0


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


def test_running_the_graph_pushes_the_figure_onto_the_canvas_card(qtbot, window):
    import json

    win = window
    plot = win.registry.instantiate("flopy.viz.plot", pos=(0, 0))
    show = win.registry.instantiate("flopy.viz.show_figure", pos=(300, 0))
    table = win.registry.instantiate("flopy.io.table", pos=(-300, 0))
    win.graph.add_node(table)
    win.graph.add_node(plot)
    win.graph.add_node(show)
    win.graph.set_param(table.id, "data", json.dumps({
        "columns": ["x", "y"], "rows": [["1", "2"], ["2", "4"], ["3", "9"]],
    }))
    win.graph.connect(table.id, "table", plot.id, "table")
    win.graph.connect(plot.id, "figure", show.id, "figure")

    item = win.scene.node_items[show.id]
    assert item._figure_placeholder.isVisible()

    with qtbot.waitSignal(win.engine.run_finished, timeout=20000) as blocker:
        win.engine.run_all()

    assert blocker.args[0], "run finished with a node failure"
    assert item._figure_view.isVisible()
    assert item._figure_placeholder.isHidden()
