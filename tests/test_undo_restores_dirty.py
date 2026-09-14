"""A node brought back by undo — or by a redo — runs again.

Deleting a node evicts its outputs from the engine's cache, but undo
restores the very object that was deleted, dirty flag and all. A node that
had run came back clean with nothing cached: Run All skipped it, and every
node downstream waited for an output that never came, so nothing ran until
Reset Caches. Found by Dan on the retail example."""
import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry
from flograph.engine import ExecutionEngine
from flograph.ui.commands import AddNodeCommand, RemoveSelectionCommand

#: generous: a busy machine running the whole suite in parallel is slow
RUN_TIMEOUT_MS = 15000


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def _run_all(qtbot, engine) -> list:
    ran = []
    engine.node_succeeded.connect(ran.append)
    with qtbot.waitSignal(engine.run_finished, timeout=RUN_TIMEOUT_MS):
        engine.run_all()
    engine.node_succeeded.disconnect(ran.append)
    return ran


def test_undoing_a_delete_lets_run_all_run_again(qtbot, registry):
    graph = Graph()
    stack = QUndoStack()
    source = graph.add_node(registry.instantiate("flograph.io.table"))
    after = graph.add_node(registry.instantiate("flograph.io.table"))
    graph.connect(source.id, "table", after.id, "table")
    engine = ExecutionEngine(graph)
    assert set(_run_all(qtbot, engine)) == {source.id, after.id}
    assert not graph.nodes[source.id].dirty

    stack.push(RemoveSelectionCommand(graph, [source.id]))
    assert engine.cache.get(source.id) is None      # its outputs went
    stack.undo()

    assert graph.nodes[source.id].dirty
    assert graph.nodes[after.id].dirty
    assert set(_run_all(qtbot, engine)) == {source.id, after.id}
    assert not graph.nodes[after.id].dirty


def test_redoing_an_add_brings_the_node_back_dirty(qtbot, registry):
    graph = Graph()
    stack = QUndoStack()
    node = registry.instantiate("flograph.io.table")
    stack.push(AddNodeCommand(graph, node))
    engine = ExecutionEngine(graph)
    assert _run_all(qtbot, engine) == [node.id]
    assert not graph.nodes[node.id].dirty

    stack.undo()
    stack.redo()
    assert graph.nodes[node.id].dirty
    assert _run_all(qtbot, engine) == [node.id]
