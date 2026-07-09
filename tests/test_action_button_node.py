"""The Action Button: port-less canvas control that fires a run/message
action instead of taking part in the data flow."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox
from PySide6.QtGui import QUndoStack

from flopy.core import Frame, Graph, NodeRegistry
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


class _FakeMouseEvent:
    """Duck-typed stand-in for a QGraphicsSceneMouseEvent, covering only the
    members NodeItem.mousePressEvent reads on the unselected-fire path."""

    def __init__(self, button):
        self._button = button
        self.accepted = False

    def button(self):
        return self._button

    def accept(self):
        self.accepted = True


def test_button_is_registered_and_portless(registry):
    spec = registry.get("flopy.util.action_button")
    assert spec.inputs == [] and spec.outputs == []
    assert spec.param("action") is not None
    assert spec.param("targets") is not None


def test_button_item_is_fixed_size_and_portless(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flopy.util.action_button"))
    item = scene.node_items[node.id]
    assert item.button
    assert not item.input_ports and not item.output_ports
    assert (item.width, item.body_height) == (150.0, 50.0)


def test_button_fires_on_click_when_unselected(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flopy.util.action_button"))
    item = scene.node_items[node.id]
    assert not item.isSelected()

    fired = []
    scene.button_fired.connect(fired.append)
    event = _FakeMouseEvent(Qt.LeftButton)
    item.mousePressEvent(event)

    assert fired == [node.id]
    assert event.accepted


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


class TestButtonFiredHandler:
    def test_run_nodes_by_label_clears_cache_and_runs(self, qtbot, window):
        win = window
        target = win.registry.instantiate("flopy.util.constant", pos=(0, 0))
        button = win.registry.instantiate("flopy.util.action_button", pos=(200, 0))
        win.graph.add_node(target)
        win.graph.add_node(button)
        win.graph.set_param(button.id, "targets", target.label)

        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win._on_button_fired(button.id)

        assert not target.dirty

    def test_run_whole_flow_runs_every_node(self, qtbot, window):
        win = window
        a = win.registry.instantiate("flopy.util.constant", pos=(0, 0))
        b = win.registry.instantiate("flopy.util.constant", pos=(0, 100))
        button = win.registry.instantiate("flopy.util.action_button", pos=(200, 0))
        for n in (a, b, button):
            win.graph.add_node(n)
        win.graph.set_param(button.id, "action", "Run whole flow")

        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win._on_button_fired(button.id)

        assert not a.dirty and not b.dirty

    def test_run_frame_targets_geometrically_contained_nodes(self, qtbot, window):
        win = window
        inside = win.registry.instantiate("flopy.util.constant", pos=(10, 10))
        outside = win.registry.instantiate("flopy.util.constant", pos=(900, 900))
        button = win.registry.instantiate("flopy.util.action_button", pos=(500, 0))
        for n in (inside, outside, button):
            win.graph.add_node(n)
        win.graph.add_frame(Frame(id="f1", title="Zone A", rect=(0, 0, 200, 200)))
        win.graph.set_param(button.id, "action", "Run frame")
        win.graph.set_param(button.id, "frame_title", "Zone A")

        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win._on_button_fired(button.id)

        assert not inside.dirty
        assert outside.dirty

    def test_unknown_frame_title_does_nothing(self, window):
        win = window
        button = win.registry.instantiate("flopy.util.action_button", pos=(0, 0))
        win.graph.add_node(button)
        win.graph.set_param(button.id, "action", "Run frame")
        win.graph.set_param(button.id, "frame_title", "no such frame")
        win._on_button_fired(button.id)  # must not raise
        assert not win.engine.active

    def test_show_message_opens_a_markdown_dialog(self, window, monkeypatch):
        win = window
        button = win.registry.instantiate("flopy.util.action_button", pos=(0, 0))
        win.graph.add_node(button)
        win.graph.set_param(button.id, "action", "Show message")
        win.graph.set_param(button.id, "message", "**hello**")

        shown = {}

        def fake_exec(self):
            shown["title"] = self.windowTitle()
            shown["text"] = self.text()
            shown["format"] = self.textFormat()

        monkeypatch.setattr(QMessageBox, "exec", fake_exec)
        win._on_button_fired(button.id)

        assert shown["text"] == "**hello**"
        assert shown["format"] == Qt.MarkdownText
