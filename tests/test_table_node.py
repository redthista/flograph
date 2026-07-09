"""The Table card: an on-canvas editable spreadsheet with a DataFrame out."""
import json

import pandas as pd
import pytest
from PySide6.QtGui import QUndoStack

from flopy.core import Graph, NodeRegistry
from flopy.ui.canvas import NodeGraphScene


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


def test_table_is_registered_with_one_output(registry):
    spec = registry.get("flopy.io.table")
    assert spec.inputs == []
    assert [p.name for p in spec.outputs] == ["table"]
    assert spec.param("data") is not None
    assert spec.param("width") is not None
    assert spec.param("height") is not None


def test_table_item_embeds_a_grid_widget(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flopy.io.table"))
    item = scene.node_items[node.id]
    assert item.table
    assert item._table_widget is not None
    assert item._table_widget.rowCount() == 2
    assert item._table_widget.columnCount() == 2
    assert list(item.output_ports) == ["table"]
    assert not item.input_ports


def test_table_runs_and_emits_dataframe(qtbot, env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flopy.io.table"))
    graph.set_param(node.id, "data", json.dumps({
        "columns": ["a", "b"],
        "rows": [["1", "2"], ["3", "4"]],
    }))
    from flopy.engine import ExecutionEngine
    engine = ExecutionEngine(graph)
    with qtbot.waitSignal(engine.run_finished, timeout=5000) as blocker:
        engine.run_all()
    assert blocker.args[0]
    out = engine.cache.outputs_for(node.id)["table"]
    assert isinstance(out, pd.DataFrame)
    assert list(out.columns) == ["a", "b"]
    assert out["a"].tolist() == [1, 3]  # numeric coercion


def test_table_keeps_non_numeric_column_as_strings(registry):
    from flopy.core import compile_run
    from tests.conftest import FakeContext

    spec = registry.get("flopy.io.table")
    run = compile_run(spec.source, "test-table")
    params = spec.default_params()
    params["data"] = json.dumps({
        "columns": ["name", "n"],
        "rows": [["north", "1"], ["south", "2"]],
    })
    out = run(FakeContext(params=params))
    assert out["name"].tolist() == ["north", "south"]
    assert out["n"].tolist() == [1, 2]


def test_table_edit_commits_and_is_undoable(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flopy.io.table"))
    item = scene.node_items[node.id]
    grid = item._table_widget
    grid.item(0, 0).setText("hello")
    assert json.loads(graph.node(node.id).params["data"])["rows"][0][0] == "hello"
    stack.undo()
    assert json.loads(graph.node(node.id).params["data"])["rows"][0][0] != "hello"


def test_table_add_and_remove_row_and_column(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flopy.io.table"))
    item = scene.node_items[node.id]

    item._table_add_row()
    data = json.loads(graph.node(node.id).params["data"])
    assert len(data["rows"]) == 3

    item._table_add_column()
    data = json.loads(graph.node(node.id).params["data"])
    assert len(data["columns"]) == 3
    assert all(len(row) == 3 for row in data["rows"])

    item._table_remove_column()
    item._table_remove_row()
    data = json.loads(graph.node(node.id).params["data"])
    assert len(data["columns"]) == 2
    assert len(data["rows"]) == 2


def test_table_wont_remove_last_row_or_column(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flopy.io.table"))
    item = scene.node_items[node.id]
    for _ in range(5):
        item._table_remove_row()
        item._table_remove_column()
    data = json.loads(graph.node(node.id).params["data"])
    assert len(data["rows"]) == 1
    assert len(data["columns"]) == 1


def test_table_resize_updates_width_and_height(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flopy.io.table"))
    item = scene.node_items[node.id]
    graph.set_param(node.id, "width", 500)
    graph.set_param(node.id, "height", 300)
    assert item.width == 500.0
    assert item.body_height == 300.0
    graph.set_param(node.id, "width", 10)   # clamped to minimum
    assert item.width == 220.0


def test_table_serialization_round_trip(env, registry):
    from flopy.core.serialization import graph_from_dict, graph_to_dict
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flopy.io.table"))
    graph.set_param(node.id, "data", json.dumps({
        "columns": ["x"], "rows": [["9"]],
    }))
    restored = graph_from_dict(graph_to_dict(graph), registry)
    assert json.loads(restored.nodes[node.id].params["data"]) == {
        "columns": ["x"], "rows": [["9"]],
    }


def test_table_excluded_from_wire_drop_palette(registry):
    """Zero inputs -> a wire can never be dropped onto this node's input side,
    but its dataframe output should offer as a target for dataframe inputs."""
    from flopy.core import PortType, can_connect
    spec = registry.get("flopy.io.table")
    assert not spec.inputs
    assert can_connect(PortType.DATAFRAME, spec.outputs[0].type)
