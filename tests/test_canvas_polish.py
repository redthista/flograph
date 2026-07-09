"""M7: reroute insertion, frames, alignment, wire-drop palette plumbing."""
import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QUndoStack

from flopy.core import Frame, Graph, NodeRegistry
from flopy.core.serialization import graph_to_dict
from flopy.ui.canvas import FrameItem, NodeGraphScene
from flopy.ui.commands import AddFrameCommand, RemoveFrameCommand, UpdateFrameCommand
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


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


class TestReroute:
    def test_insert_reroute_splits_wire(self, env, registry):
        graph, stack, scene = env
        a = graph.add_node(registry.instantiate("flopy.util.constant"))
        b = graph.add_node(registry.instantiate("flopy.scripting.python_script"))
        conn, _ = graph.connect(a.id, "value", b.id, "in1")
        before = graph_to_dict(graph)

        scene.insert_reroute(conn, QPointF(100, 50))
        reroutes = [n for n in graph.nodes.values()
                    if n.type_id == "flopy.util.reroute"]
        assert len(reroutes) == 1
        assert len(graph.connections) == 2
        assert conn.id not in graph.connections
        # compact item rendering
        item = scene.node_items[reroutes[0].id]
        assert item.compact and item.width < 40

        # single undo step restores the original wire
        stack.undo()
        assert graph_to_dict(graph) == before

    def test_reroute_passes_value_through_engine(self, qtbot, env, registry):
        from flopy.engine import ExecutionEngine
        graph, stack, scene = env
        a = graph.add_node(registry.instantiate("flopy.util.constant"))
        graph.set_param(a.id, "kind", "int")
        graph.set_param(a.id, "value", "7")
        b = graph.add_node(registry.instantiate("flopy.scripting.python_script"))
        conn, _ = graph.connect(a.id, "value", b.id, "in1")
        scene.insert_reroute(conn, QPointF(0, 0))

        engine = ExecutionEngine(graph)
        with qtbot.waitSignal(engine.run_finished, timeout=5000):
            engine.run_all()
        assert engine.cache.outputs_for(b.id)["out1"] == 7


class TestFrames:
    def test_frame_commands_round_trip(self, env):
        graph, stack, scene = env
        frame = Frame(id="f1", title="Stage", rect=(0, 0, 300, 200))
        stack.push(AddFrameCommand(graph, frame))
        assert "f1" in graph.frames and "f1" in scene.frame_items

        stack.push(UpdateFrameCommand(graph, "f1", title="Renamed",
                                      rect=(10, 10, 400, 250)))
        assert graph.frames["f1"].title == "Renamed"
        stack.undo()
        assert graph.frames["f1"].title == "Stage"
        assert graph.frames["f1"].rect == (0, 0, 300, 200)

        stack.push(RemoveFrameCommand(graph, "f1"))
        assert "f1" not in graph.frames and "f1" not in scene.frame_items
        stack.undo()
        assert "f1" in graph.frames and "f1" in scene.frame_items

    def test_frame_serialization_round_trip(self, env, registry):
        from flopy.core.serialization import graph_from_dict
        graph, stack, scene = env
        graph.add_frame(Frame(id="f2", title="T", rect=(5, 5, 100, 80),
                              color="#112233"))
        data = graph_to_dict(graph)
        restored = graph_from_dict(data, registry)
        assert restored.frames["f2"].color == "#112233"

    def test_delete_selection_includes_frames(self, env):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f3"))
        scene.frame_items["f3"].setSelected(True)
        scene.delete_selection()
        assert "f3" not in graph.frames
        stack.undo()
        assert "f3" in graph.frames


class TestAlignment:
    def test_align_left_and_distribute(self, window):
        reg = window.registry
        nodes = [reg.instantiate("flopy.util.constant", pos=(x, y))
                 for x, y in ((0, 0), (50, 100), (120, 260))]
        for n in nodes:
            window.graph.add_node(n)
        for item in window.scene.node_items.values():
            item.setSelected(True)

        window._align("left")
        assert all(n.pos[0] == 0 for n in nodes)

        window._align("dist_v")
        ys = sorted(n.pos[1] for n in nodes)
        assert ys[1] - ys[0] == pytest.approx(ys[2] - ys[1])

        window.undo_stack.undo()  # distribute
        window.undo_stack.undo()  # align
        assert nodes[1].pos == (50.0, 100.0)


class TestWireDropPalette:
    def test_wire_drop_offers_compatible_and_connects(self, window):
        reg = window.registry
        src = reg.instantiate("flopy.io.read_csv", pos=(0, 0))
        window.graph.add_node(src)
        port_item = window.scene.node_items[src.id].output_ports["table"]

        window._on_wire_dropped(port_item, QPointF(300, 0))
        # popup should be filtered to nodes with a dataframe-compatible input
        labels = [window._palette_popup._list.item(i).text()
                  for i in range(window._palette_popup._list.count())]
        assert any("Filter Rows" in l for l in labels)
        assert not any("Read CSV" in l for l in labels)  # no inputs
        window._palette_popup.hide()

        window._add_node_from_palette("flopy.transform.filter_rows")
        assert len(window.graph.nodes) == 2
        assert len(window.graph.connections) == 1
        conn = next(iter(window.graph.connections.values()))
        assert conn.src_node == src.id and conn.dst_port == "table"
        # one undo step for add+connect
        window.undo_stack.undo()
        assert len(window.graph.nodes) == 1 and not window.graph.connections
