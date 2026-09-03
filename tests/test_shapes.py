"""Whiteboard shapes: the Shape model, its serialization, the three shape
commands, and the scene item that mirrors them."""
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry, Shape
from flograph.core.serialization import graph_from_dict, graph_to_dict
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.canvas.shape_item import ShapeItem
from flograph.ui.canvas.stacking import SHAPE_BACK_Z, SHAPE_FRONT_Z
from flograph.ui.commands import (
    AddShapeCommand, RemoveShapeCommand, RestackCommand, UpdateShapeCommand,
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
    scene = NodeGraphScene(graph, stack, registry=registry)
    yield graph, stack, scene
    stack.clear()


class TestModel:
    def test_defaults(self):
        s = Shape(id="s1")
        assert s.kind == "rect"
        assert s.behind is False and s.hidden is False
        assert s.fill == "" and s.stroke == ""

    def test_add_assigns_stacking_index(self):
        graph = Graph()
        graph.add_shape(Shape(id="a"))
        graph.add_shape(Shape(id="b"))
        assert graph.stacking_order("shape") == ["a", "b"]

    def test_update_rejects_unknown_field(self):
        graph = Graph()
        graph.add_shape(Shape(id="a"))
        with pytest.raises(Exception):
            graph.update_shape("a", nonsense=1)

    def test_update_coerces_rect_to_floats(self):
        graph = Graph()
        graph.add_shape(Shape(id="a"))
        graph.update_shape("a", rect=(1, 2, 3, 4))
        assert graph.shapes["a"].rect == (1.0, 2.0, 3.0, 4.0)

    def test_restack_renumbers(self):
        graph = Graph()
        for i in "abc":
            graph.add_shape(Shape(id=i))
        graph.restack("shape", ["c", "b", "a"])
        assert [graph.shapes[i].z for i in "abc"] == [2, 1, 0]


class TestSerialization:
    def test_round_trip(self, registry):
        graph = Graph()
        graph.add_shape(Shape(
            id="s1", kind="arrow", rect=(10, 20, 100, 50), stroke="#ff0000",
            fill="#00ff00", stroke_width=3.0, dashed=True, text="hi",
            behind=True, hidden=True, flip=True, font_size=14.0,
            text_color="#123456"))
        loaded = graph_from_dict(graph_to_dict(graph), registry)
        got = loaded.shapes["s1"]
        assert (got.kind, got.rect, got.stroke, got.fill, got.stroke_width,
                got.dashed, got.text, got.behind, got.hidden, got.flip,
                got.font_size, got.text_color) == (
            "arrow", (10.0, 20.0, 100.0, 50.0), "#ff0000", "#00ff00", 3.0,
            True, "hi", True, True, True, 14.0, "#123456")

    def test_file_without_shapes_key_loads_clean(self, registry):
        graph = Graph()
        graph.add_shape(Shape(id="s1"))
        payload = graph_to_dict(graph)
        del payload["graph"]["shapes"]
        assert graph_from_dict(payload, registry).shapes == {}


class TestCommands:
    def test_add_remove_undo_redo(self, env):
        graph, stack, _ = env
        stack.push(AddShapeCommand(graph, Shape(id="s1", kind="ellipse")))
        assert "s1" in graph.shapes
        stack.undo()
        assert "s1" not in graph.shapes
        stack.redo()
        assert graph.shapes["s1"].kind == "ellipse"
        stack.push(RemoveShapeCommand(graph, "s1"))
        assert "s1" not in graph.shapes
        stack.undo()
        assert "s1" in graph.shapes

    def test_update_only_touches_named_fields(self, env):
        graph, stack, _ = env
        stack.push(AddShapeCommand(graph, Shape(id="s1")))
        stack.push(UpdateShapeCommand(graph, "s1", label="A", fill="#111111"))
        stack.push(UpdateShapeCommand(graph, "s1", label="B", stroke="#222222"))
        stack.undo()                       # undo the stroke edit
        assert graph.shapes["s1"].fill == "#111111"       # not clobbered
        assert graph.shapes["s1"].stroke == ""

    def test_restack_command(self, env):
        graph, stack, _ = env
        stack.push(AddShapeCommand(graph, Shape(id="a")))
        stack.push(AddShapeCommand(graph, Shape(id="b")))
        stack.push(RestackCommand(graph, "shape", ["b", "a"], text="restack"))
        assert graph.stacking_order("shape") == ["b", "a"]
        stack.undo()
        assert graph.stacking_order("shape") == ["a", "b"]


class TestSceneItem:
    def test_item_created_and_removed(self, env):
        graph, stack, scene = env
        stack.push(AddShapeCommand(graph, Shape(id="s1")))
        assert isinstance(scene.shape_items["s1"], ShapeItem)
        stack.push(RemoveShapeCommand(graph, "s1"))
        assert "s1" not in scene.shape_items

    def test_behind_flag_switches_z_band(self, env):
        graph, stack, scene = env
        stack.push(AddShapeCommand(graph, Shape(id="s1")))
        assert scene.shape_items["s1"].zValue() >= SHAPE_FRONT_Z
        scene.push_shape_style("s1", behind=True)
        assert scene.shape_items["s1"].zValue() < 0
        assert scene.shape_items["s1"].zValue() >= SHAPE_BACK_Z

    def test_hidden_flag_hides_item(self, env):
        graph, stack, scene = env
        stack.push(AddShapeCommand(graph, Shape(id="s1")))
        scene.push_shape_style("s1", hidden=True)
        assert scene.shape_items["s1"].isVisible() is False

    def test_delete_selection_removes_shape(self, env):
        graph, stack, scene = env
        stack.push(AddShapeCommand(graph, Shape(id="s1")))
        scene.shape_items["s1"].setSelected(True)
        scene.delete_selection()
        assert "s1" not in graph.shapes
        stack.undo()
        assert "s1" in graph.shapes

    def test_whole_edge_is_grabbable_for_resize(self, env):
        graph, stack, scene = env
        stack.push(AddShapeCommand(graph, Shape(
            id="s1", kind="rect", rect=(0, 0, 200, 120))))
        item = scene.shape_items["s1"]
        item.setSelected(True)
        # a point halfway along the right edge — not near any corner
        assert item._handle_at(QPointF(200, 60)) == 3      # right-middle handle
        # a point in the dead centre grabs nothing (it moves instead)
        assert item._handle_at(QPointF(100, 60)) is None

    def test_endpoint_drag_commits_rect_and_flip(self, env):
        graph, stack, scene = env
        stack.push(AddShapeCommand(graph, Shape(
            id="s1", kind="line", rect=(0, 0, 100, 100))))
        item = scene.shape_items["s1"]
        item.setSelected(True)
        item._grab = 1            # the far endpoint
        item._press_pos = item.pos()
        item._press_size = (100.0, 100.0)
        item._moved = True
        item._drag_endpoint(QPointF(140, -40))     # swing it above the origin
        item.mouseReleaseEvent(_fake_release())
        s = graph.shapes["s1"]
        assert s.rect[2] > 0 and s.rect[3] > 0     # normalised box
        assert s.flip is True                       # onto the other diagonal


def _fake_release():
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QMouseEvent
    return QMouseEvent(QEvent.GraphicsSceneMouseRelease, QPointF(0, 0),
                       QPointF(0, 0), Qt.LeftButton, Qt.NoButton,
                       Qt.NoModifier)
