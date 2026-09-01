"""The markdown Note card: port-less display node with special rendering."""
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QUndoStack

from flograph.ui.canvas.node_item import NOTE_PAD

from flograph.core import Graph, NodeRegistry
from flograph.ui.canvas import NodeGraphScene


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
    spec = registry.get("flograph.util.note")
    assert spec.inputs == [] and spec.outputs == []
    assert spec.param("text") is not None
    assert spec.param("width") is not None


def test_note_item_renders_markdown_geometry(env, registry):
    graph, stack, scene = env
    note = graph.add_node(registry.instantiate("flograph.util.note"))
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
    from flograph.core.node import NodeStatus
    from flograph.engine import ExecutionEngine
    graph, stack, scene = env
    note = graph.add_node(registry.instantiate("flograph.util.note"))
    const = graph.add_node(registry.instantiate("flograph.util.constant"))
    engine = ExecutionEngine(graph)
    with qtbot.waitSignal(engine.run_finished, timeout=5000) as blocker:
        engine.run_all()
    assert blocker.args[0]  # ok
    assert note.status == NodeStatus.DONE and not note.dirty
    assert engine.cache.outputs_for(note.id) == {}


def test_note_excluded_from_wire_drop_palette(registry):
    """Zero ports -> never offered when dropping a wire on the canvas."""
    from flograph.core import PortType, can_connect
    note = registry.get("flograph.util.note")
    assert not any(can_connect(PortType.DATAFRAME, p.type)
                   for p in note.inputs)


def test_note_serialization_round_trip(env, registry):
    from flograph.core.serialization import graph_from_dict, graph_to_dict
    graph, stack, scene = env
    note = graph.add_node(registry.instantiate("flograph.util.note"))
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
    note = graph.add_node(registry.instantiate("flograph.util.note"))
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
    note = graph.add_node(registry.instantiate("flograph.util.note"))
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
    note = graph.add_node(registry.instantiate("flograph.util.note"))
    item = scene.node_items[note.id]
    before = graph.node(note.id).params["text"]
    item.start_note_edit()
    item._note_editor_widget.setPlainText("discard me")
    item._finish_note_edit(commit=False)
    assert graph.node(note.id).params["text"] == before
    assert stack.count() == 0  # nothing pushed


def test_note_link_hit_testing(env, registry):
    """note_link_at() reports the href under a point, "" where there is none."""
    graph, stack, scene = env
    note = graph.add_node(registry.instantiate("flograph.util.note"))
    item = scene.node_items[note.id]
    graph.set_param(note.id, "text",
                    "[docs](https://example.com/page)\n\nplain tail line")

    on_link = QPointF(NOTE_PAD + 10, NOTE_PAD + 12)
    assert item.note_link_at(on_link) == "https://example.com/page"

    off_link = QPointF(NOTE_PAD + 3, item.body_height - NOTE_PAD - 4)
    assert item.note_link_at(off_link) == ""


def test_note_link_opens_in_browser(env, registry, monkeypatch):
    graph, stack, scene = env
    note = graph.add_node(registry.instantiate("flograph.util.note"))
    item = scene.node_items[note.id]
    graph.set_param(note.id, "text", "[docs](https://example.com)")

    opened = []
    monkeypatch.setattr(
        "flograph.ui.canvas.node_item.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()))

    item._open_note_link("https://example.com")
    assert opened == ["https://example.com"]

    # a double-click landing on the link opens the editor instead — the
    # deferred open must then do nothing
    opened.clear()
    item.start_note_edit()
    item._open_note_link("https://example.com")
    assert opened == []


class _FakeMouse:
    """Enough of QGraphicsSceneMouseEvent for the Note link handlers."""

    def __init__(self, pos):
        self._pos = pos

    def pos(self):
        return self._pos

    def scenePos(self):
        return self._pos

    def button(self):
        from PySide6.QtCore import Qt
        return Qt.LeftButton

    def modifiers(self):
        from PySide6.QtCore import Qt
        return Qt.NoModifier

    def accept(self):
        pass


def test_note_single_click_opens_link_double_click_edits(env, registry,
                                                         monkeypatch):
    graph, stack, scene = env
    note = graph.add_node(registry.instantiate("flograph.util.note"))
    item = scene.node_items[note.id]
    graph.set_param(note.id, "text", "[docs](https://example.com)")

    deferred = []
    monkeypatch.setattr("flograph.ui.canvas.node_item.QTimer.singleShot",
                        lambda _ms, cb: deferred.append(cb))
    opened = []
    monkeypatch.setattr(
        "flograph.ui.canvas.node_item.QDesktopServices.openUrl",
        lambda url: opened.append(url.toString()))

    on_link = QPointF(NOTE_PAD + 10, NOTE_PAD + 12)

    # single click: press + release, then the deferred open fires
    item.mousePressEvent(_FakeMouse(on_link))
    assert item._note_link_press is not None
    item.mouseReleaseEvent(_FakeMouse(on_link))
    assert item._note_link_press is None
    assert len(deferred) == 1
    deferred.pop()()
    assert opened == ["https://example.com"]

    # double click on the link: the editor opens and the (still-deferred)
    # open must be a no-op
    opened.clear()
    item.mousePressEvent(_FakeMouse(on_link))
    item.mouseReleaseEvent(_FakeMouse(on_link))
    item.mouseDoubleClickEvent(_FakeMouse(on_link))
    assert item._note_editor is not None
    for cb in deferred:
        cb()
    assert opened == []
    item._finish_note_edit(commit=False)


def test_params_panel_text_keeps_cursor_while_typing(qtbot, env, registry):
    """Regression: the param-changed echo must not reset the cursor, or
    typed characters land at the start in reverse order."""
    from PySide6.QtWidgets import QPlainTextEdit
    from flograph.ui.properties.params_panel import ParamsPanel
    graph, stack, scene = env
    note = graph.add_node(registry.instantiate("flograph.util.note"))
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
    # typing is held back until it pauses, so the echo this guards against
    # arrives after the flush rather than after each character
    panel.flush_pending()
    assert graph.node(note.id).params["text"] == "start:abc"
    assert text.toPlainText() == "start:abc"
