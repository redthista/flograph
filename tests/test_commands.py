"""Undo/redo integrity: every command must survive redo -> undo -> redo with
the graph JSON identical at each equivalent point, and the scene must mirror
the graph through it all."""
import pytest
from PySide6.QtGui import QUndoStack

from flopy.core import Graph, NodeRegistry
from flopy.core.serialization import graph_to_dict
from flopy.ui.canvas import NodeGraphScene
from flopy.ui.commands import (
    AddNodeCommand, ConnectCommand, DisconnectCommand, MoveNodesCommand,
    RemoveSelectionCommand, SetCodeCommand, SetParamCommand,
)


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def env(qtbot, registry):
    graph = Graph()
    stack = QUndoStack()
    scene = NodeGraphScene(graph, stack)
    return graph, stack, scene


def snapshot(graph):
    return graph_to_dict(graph)


def assert_undo_redo_stable(stack, graph, before, after):
    """From the 'after' state: undo -> 'before', redo -> 'after', again."""
    for _ in range(2):
        stack.undo()
        assert snapshot(graph) == before
        stack.redo()
        assert snapshot(graph) == after


def build_pipeline(graph, stack, registry):
    const = registry.instantiate("flopy.util.constant", pos=(0, 0))
    script = registry.instantiate("flopy.scripting.python_script", pos=(250, 0))
    stack.push(AddNodeCommand(graph, const))
    stack.push(AddNodeCommand(graph, script))
    stack.push(ConnectCommand(graph, const.id, "value", script.id, "in1"))
    return const, script


def test_add_connect_undo_redo(env, registry):
    graph, stack, scene = env
    empty = snapshot(graph)
    const, script = build_pipeline(graph, stack, registry)
    full = snapshot(graph)

    assert const.id in scene.node_items and script.id in scene.node_items
    assert len(scene.connection_items) == 1

    for _ in range(3):
        stack.undo()
    assert snapshot(graph) == empty
    assert not scene.node_items and not scene.connection_items

    for _ in range(3):
        stack.redo()
    assert snapshot(graph) == full
    assert len(scene.node_items) == 2 and len(scene.connection_items) == 1


def test_remove_connected_node_restores_wires(env, registry):
    graph, stack, scene = env
    const, script = build_pipeline(graph, stack, registry)
    before = snapshot(graph)
    stack.push(RemoveSelectionCommand(graph, [script.id]))
    after = snapshot(graph)
    assert len(graph.nodes) == 1 and not graph.connections
    assert_undo_redo_stable(stack, graph, before, after)
    stack.undo()
    assert len(scene.connection_items) == 1  # wire restored in scene too


def test_connect_displacement_restores_old_wire(env, registry):
    graph, stack, scene = env
    a = registry.instantiate("flopy.util.constant")
    b = registry.instantiate("flopy.util.constant")
    target = registry.instantiate("flopy.scripting.python_script")
    for node in (a, b, target):
        stack.push(AddNodeCommand(graph, node))
    stack.push(ConnectCommand(graph, a.id, "value", target.id, "in1"))
    before = snapshot(graph)
    stack.push(ConnectCommand(graph, b.id, "value", target.id, "in1"))
    after = snapshot(graph)
    assert graph.input_connection(target.id, "in1").src_node == b.id
    assert_undo_redo_stable(stack, graph, before, after)
    stack.undo()
    assert graph.input_connection(target.id, "in1").src_node == a.id


def test_disconnect_undo(env, registry):
    graph, stack, scene = env
    const, script = build_pipeline(graph, stack, registry)
    conn = next(iter(graph.connections.values()))
    before = snapshot(graph)
    stack.push(DisconnectCommand(graph, conn.id))
    after = snapshot(graph)
    assert not graph.connections
    assert_undo_redo_stable(stack, graph, before, after)


def test_move_merge(env, registry):
    graph, stack, scene = env
    node = registry.instantiate("flopy.util.constant", pos=(0, 0))
    stack.push(AddNodeCommand(graph, node))
    index_before = stack.index()
    stack.push(MoveNodesCommand(graph, {node.id: ((0, 0), (10, 0))}))
    stack.push(MoveNodesCommand(graph, {node.id: ((10, 0), (20, 0))}))
    assert node.pos == (20.0, 0.0)
    assert stack.index() == index_before + 1  # merged into one step
    stack.undo()
    assert node.pos == (0.0, 0.0)
    # scene mirrored the moves
    assert scene.node_items[node.id].pos().x() == 0.0


def test_set_param_merge_and_undo(env, registry):
    graph, stack, scene = env
    node = registry.instantiate("flopy.util.constant")
    stack.push(AddNodeCommand(graph, node))
    before = snapshot(graph)
    stack.push(SetParamCommand(graph, node.id, "value", "a"))
    stack.push(SetParamCommand(graph, node.id, "value", "ab"))
    after = snapshot(graph)
    assert node.params["value"] == "ab"
    stack.undo()
    assert snapshot(graph) == before
    stack.redo()
    assert snapshot(graph) == after


def test_set_code_undo_restores_ports_and_wires(env, registry):
    graph, stack, scene = env
    const, script = build_pipeline(graph, stack, registry)
    before = snapshot(graph)
    # new code renames the input port -> the wire from const gets dropped
    new_source = """
NODE = {"label": "Custom", "category": "Scripting",
        "inputs": [("payload", "any", {"optional": True})],
        "outputs": [("out1", "any")]}
def run(ctx, payload):
    return {"out1": payload}
"""
    stack.push(SetCodeCommand(graph, script.id, new_source))
    after = snapshot(graph)
    assert not graph.connections
    assert script.forked and script.spec.input("payload") is not None
    # scene rebuilt the ports
    assert "payload" in scene.node_items[script.id].input_ports

    assert_undo_redo_stable(stack, graph, before, after)
    stack.undo()
    assert not script.forked
    assert len(graph.connections) == 1
    assert "in1" in scene.node_items[script.id].input_ports
