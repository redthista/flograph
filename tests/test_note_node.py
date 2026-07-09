"""The markdown Note card: port-less display node with special rendering."""
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


def test_note_is_registered_and_portless(registry):
    spec = registry.get("flopy.util.note")
    assert spec.inputs == [] and spec.outputs == []
    assert spec.param("text") is not None
    assert spec.param("width") is not None


def test_note_item_renders_markdown_geometry(env, registry):
    graph, stack, scene = env
    note = graph.add_node(registry.instantiate("flopy.util.note"))
    item = scene.node_items[note.id]
    assert item.note
    assert not item.input_ports and not item.output_ports
    assert item.width == 280.0

    short_height = item.body_height
    graph.set_param(note.id, "text",
                    "# Title\n\n" + "\n\n".join(["paragraph"] * 12))
    assert item.body_height > short_height  # height follows content

    graph.set_param(note.id, "width", 600)
    assert item.width == 600.0
    graph.set_param(note.id, "width", 10)   # clamped to minimum
    assert item.width == 120.0


def test_note_runs_as_noop_in_engine(qtbot, env, registry):
    from flopy.core.node import NodeStatus
    from flopy.engine import ExecutionEngine
    graph, stack, scene = env
    note = graph.add_node(registry.instantiate("flopy.util.note"))
    const = graph.add_node(registry.instantiate("flopy.util.constant"))
    engine = ExecutionEngine(graph)
    with qtbot.waitSignal(engine.run_finished, timeout=5000) as blocker:
        engine.run_all()
    assert blocker.args[0]  # ok
    assert note.status == NodeStatus.DONE and not note.dirty
    assert engine.cache.outputs_for(note.id) == {}


def test_note_excluded_from_wire_drop_palette(registry):
    """Zero ports -> never offered when dropping a wire on the canvas."""
    from flopy.core import PortType, can_connect
    note = registry.get("flopy.util.note")
    assert not any(can_connect(PortType.DATAFRAME, p.type)
                   for p in note.inputs)


def test_note_serialization_round_trip(env, registry):
    from flopy.core.serialization import graph_from_dict, graph_to_dict
    graph, stack, scene = env
    note = graph.add_node(registry.instantiate("flopy.util.note"))
    graph.set_param(note.id, "text", "# Saved title")
    graph.set_param(note.id, "width", 420)
    graph.set_param(note.id, "height", 300)
    restored = graph_from_dict(graph_to_dict(graph), registry)
    assert restored.nodes[note.id].params["text"] == "# Saved title"
    assert restored.nodes[note.id].params["width"] == 420
    assert restored.nodes[note.id].params["height"] == 300


def test_note_fixed_height(env, registry):
    """height=0 fits the text; a positive height pins the card size."""
    graph, stack, scene = env
    note = graph.add_node(registry.instantiate("flopy.util.note"))
    item = scene.node_items[note.id]
    auto = item.body_height
    graph.set_param(note.id, "height", 400)
    assert item.body_height == 400.0
    graph.set_param(note.id, "height", 10)   # clamped to minimum
    assert item.body_height == 60.0
    graph.set_param(note.id, "height", 0)    # back to fit-text
    assert item.body_height == auto


def test_note_inline_edit_commits_and_is_undoable(env, registry):
    graph, stack, scene = env
    note = graph.add_node(registry.instantiate("flopy.util.note"))
    item = scene.node_items[note.id]
    item.start_note_edit()
    assert item._note_editor_widget is not None
    item._note_editor_widget.setPlainText("# Edited inline")
    item._finish_note_edit(commit=True)
    assert item._note_editor is None
    assert graph.node(note.id).params["text"] == "# Edited inline"
    stack.undo()
    assert graph.node(note.id).params["text"] != "# Edited inline"


def test_note_inline_edit_escape_cancels(env, registry):
    graph, stack, scene = env
    note = graph.add_node(registry.instantiate("flopy.util.note"))
    item = scene.node_items[note.id]
    before = graph.node(note.id).params["text"]
    item.start_note_edit()
    item._note_editor_widget.setPlainText("discard me")
    item._finish_note_edit(commit=False)
    assert graph.node(note.id).params["text"] == before
    assert stack.count() == 0  # nothing pushed


def test_params_panel_text_keeps_cursor_while_typing(qtbot, env, registry):
    """Regression: the param-changed echo must not reset the cursor, or
    typed characters land at the start in reverse order."""
    from PySide6.QtWidgets import QPlainTextEdit
    from flopy.ui.properties.params_panel import ParamsPanel
    graph, stack, scene = env
    note = graph.add_node(registry.instantiate("flopy.util.note"))
    graph.set_param(note.id, "text", "start:")
    panel = ParamsPanel(graph, stack)
    qtbot.addWidget(panel)
    panel.set_node(note.id)
    text = panel.findChild(QPlainTextEdit)
    cursor = text.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    text.setTextCursor(cursor)
    qtbot.keyClicks(text, "abc")
    assert text.toPlainText() == "start:abc"
    assert graph.node(note.id).params["text"] == "start:abc"
