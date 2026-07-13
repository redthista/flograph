"""The Action Button: port-less canvas control that fires a run/message
action instead of taking part in the data flow."""
import pytest
from PySide6.QtCore import Qt, QPointF
from PySide6.QtWidgets import QGraphicsItem, QMessageBox
from PySide6.QtGui import QUndoStack

from flograph.core import Frame, Graph, NodeRegistry
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


class _FakeMouseEvent:
    """Duck-typed stand-in for a QGraphicsSceneMouseEvent. Covers the members
    the fire path reads plus pos/scenePos/modifiers for the edit-mode resize
    gesture (whose press/move/release branches all return before super())."""

    def __init__(self, button, pos=None, scene_pos=None, modifiers=Qt.NoModifier):
        self._button = button
        self._pos = pos if pos is not None else QPointF(0, 0)
        self._scene_pos = scene_pos if scene_pos is not None else self._pos
        self._modifiers = modifiers
        self.accepted = False

    def button(self):
        return self._button

    def pos(self):
        return self._pos

    def scenePos(self):
        return self._scene_pos

    def modifiers(self):
        return self._modifiers

    def accept(self):
        self.accepted = True


def test_button_is_registered_and_portless(registry):
    spec = registry.get("flograph.util.action_button")
    assert spec.inputs == [] and spec.outputs == []
    assert spec.param("action") is not None
    assert spec.param("targets") is not None


def test_button_item_is_fixed_size_and_portless(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.util.action_button"))
    item = scene.node_items[node.id]
    assert item.button
    assert not item.input_ports and not item.output_ports
    assert (item.width, item.body_height) == (150.0, 50.0)


def test_button_fires_on_click_when_unselected(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.util.action_button"))
    item = scene.node_items[node.id]
    assert not item.isSelected()

    fired = []
    scene.button_fired.connect(fired.append)
    event = _FakeMouseEvent(Qt.LeftButton)
    item.mousePressEvent(event)

    assert fired == [node.id]
    assert event.accepted


def test_enter_edit_mode_makes_button_movable_and_clears_other_selection(env, registry):
    graph, stack, scene = env
    other = graph.add_node(registry.instantiate("flograph.util.constant"))
    node = graph.add_node(registry.instantiate("flograph.util.action_button"))
    item = scene.node_items[node.id]
    scene.node_items[other.id].setSelected(True)

    item.enter_button_edit()

    assert item._button_edit and item.isSelected()
    assert item.flags() & QGraphicsItem.ItemIsMovable
    # entering edit mode selects the button alone, so a drag can't carry the
    # previously-selected node along (the "moves both" bug)
    assert not scene.node_items[other.id].isSelected()


def test_left_click_in_edit_mode_resizes_instead_of_firing(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.util.action_button"))
    item = scene.node_items[node.id]
    item.enter_button_edit()

    fired = []
    scene.button_fired.connect(fired.append)
    # press on the bottom-right grip → grabs the resize corner, never fires
    corner = QPointF(item.width, item.body_height)
    item.mousePressEvent(_FakeMouseEvent(Qt.LeftButton, pos=corner,
                                         scene_pos=corner))

    assert fired == []
    assert item._resizing_card
    item.mouseReleaseEvent(_FakeMouseEvent(Qt.LeftButton))


def test_resize_in_edit_mode_persists_size(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.util.action_button"))
    item = scene.node_items[node.id]
    item.enter_button_edit()

    start = QPointF(item.width, item.body_height)          # 150, 50
    end = QPointF(item.width + 40, item.body_height + 20)   # 190, 70
    ctrl = Qt.ControlModifier  # bypass grid snapping for a deterministic delta
    item.mousePressEvent(_FakeMouseEvent(Qt.LeftButton, pos=start,
                                         scene_pos=start, modifiers=ctrl))
    item.mouseMoveEvent(_FakeMouseEvent(Qt.LeftButton, scene_pos=end,
                                        modifiers=ctrl))
    item.mouseReleaseEvent(_FakeMouseEvent(Qt.LeftButton, modifiers=ctrl))

    assert (item.width, item.body_height) == (190.0, 70.0)
    assert node.params["width"] == 190
    assert node.params["height"] == 70


def test_move_in_edit_mode_persists_position(env, registry):
    """Dragging the button in edit mode must write the new pos to the model,
    not just slide the on-screen item — otherwise it reloads at its old spot.
    Uses real QGraphicsSceneMouseEvents because the move path crosses super()."""
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QGraphicsSceneMouseEvent

    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.util.action_button"))
    item = scene.node_items[node.id]
    item.enter_button_edit()

    mid = QPointF(item.width / 2, item.body_height / 2)

    def event(kind, scene_pos):
        ev = QGraphicsSceneMouseEvent(kind)
        ev.setButton(Qt.LeftButton)
        ev.setButtons(Qt.LeftButton)
        ev.setPos(mid)
        ev.setScenePos(scene_pos)
        return ev

    assert node.pos == (0.0, 0.0)
    item.mousePressEvent(event(QEvent.GraphicsSceneMousePress,
                               item.scenePos() + mid))
    # the press must arm the group-drag snapshot; the dead _drag_start_positions
    # attribute never committed, so the move was silently lost
    assert item._group_starts is not None
    item.setPos(item.pos().x() + 60, item.pos().y() + 40)  # Qt slides the item
    item.mouseReleaseEvent(event(QEvent.GraphicsSceneMouseRelease,
                                 item.scenePos() + mid))

    assert node.pos == (60.0, 40.0)


def test_click_away_exits_edit_mode(env, registry):
    graph, stack, scene = env
    node = graph.add_node(registry.instantiate("flograph.util.action_button"))
    item = scene.node_items[node.id]
    item.enter_button_edit()
    assert item._button_edit

    # clicking the canvas / another node drops the selection
    item.setSelected(False)

    assert not item._button_edit
    assert not (item.flags() & QGraphicsItem.ItemIsMovable)


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


class TestButtonFiredHandler:
    def test_run_nodes_by_label_clears_cache_and_runs(self, qtbot, window):
        win = window
        target = win.registry.instantiate("flograph.util.constant", pos=(0, 0))
        button = win.registry.instantiate("flograph.util.action_button", pos=(200, 0))
        win.graph.add_node(target)
        win.graph.add_node(button)
        win.graph.set_param(button.id, "targets", target.label)

        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win._on_button_fired(button.id)

        assert not target.dirty

    def test_run_whole_flow_runs_every_node(self, qtbot, window):
        win = window
        a = win.registry.instantiate("flograph.util.constant", pos=(0, 0))
        b = win.registry.instantiate("flograph.util.constant", pos=(0, 100))
        button = win.registry.instantiate("flograph.util.action_button", pos=(200, 0))
        for n in (a, b, button):
            win.graph.add_node(n)
        win.graph.set_param(button.id, "action", "Run whole flow")

        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win._on_button_fired(button.id)

        assert not a.dirty and not b.dirty

    def test_run_frame_targets_geometrically_contained_nodes(self, qtbot, window):
        win = window
        inside = win.registry.instantiate("flograph.util.constant", pos=(10, 10))
        outside = win.registry.instantiate("flograph.util.constant", pos=(900, 900))
        button = win.registry.instantiate("flograph.util.action_button", pos=(500, 0))
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
        button = win.registry.instantiate("flograph.util.action_button", pos=(0, 0))
        win.graph.add_node(button)
        win.graph.set_param(button.id, "action", "Run frame")
        win.graph.set_param(button.id, "frame_title", "no such frame")
        win._on_button_fired(button.id)  # must not raise
        assert not win.engine.active

    def test_show_message_opens_a_markdown_dialog(self, window, monkeypatch):
        win = window
        button = win.registry.instantiate("flograph.util.action_button", pos=(0, 0))
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
