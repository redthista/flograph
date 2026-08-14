"""Collapsible frames: the model, the collapsed box, its pins and its wires.

Frames had no test file of their own before this — drag, resize, rename and
the carry-your-contents behaviour were all untested — so this covers the
collapse feature and the frame behaviour it leans on.
"""
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage, QPainter, QUndoStack

from flograph.core import Frame, Graph, NodeRegistry
from flograph.core.node import NodeStatus
from flograph.core.serialization import graph_from_dict, graph_to_dict
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.canvas.node_item import COMPACT_MIN_H, COMPACT_W
from flograph.ui.commands import (SetFrameCollapsedCommand,
                                  UpdateFrameCommand)


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
    # a test-local QUndoStack holding pushed commands can double-free during
    # the conftest GC drain; clear it while graph and scene are still alive
    stack.clear()


class TestModel:
    def test_collapsed_defaults_false(self):
        assert Frame(id="f1").collapsed is False

    def test_collapsed_round_trips_serialization(self, registry):
        graph = Graph()
        graph.add_frame(Frame(id="f1", title="Stage", collapsed=True))
        loaded = graph_from_dict(graph_to_dict(graph), registry)
        assert loaded.frames["f1"].collapsed is True

    def test_old_files_without_the_key_load_expanded(self, registry):
        graph = Graph()
        graph.add_frame(Frame(id="f1", title="Stage"))
        payload = graph_to_dict(graph)
        for entry in payload["graph"]["frames"]:
            del entry["collapsed"]
        assert graph_from_dict(payload, registry).frames["f1"].collapsed is False

    def test_set_frame_collapsed_command_undo_redo(self, env):
        graph, stack, _scene = env
        graph.add_frame(Frame(id="f1", title="Stage"))
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))
        assert graph.frames["f1"].collapsed is True
        stack.undo()
        assert graph.frames["f1"].collapsed is False
        stack.redo()
        assert graph.frames["f1"].collapsed is True

    def test_update_frame_does_not_clobber_collapsed(self, env):
        """UpdateFrameCommand rewrites (title, rect, color) wholesale on undo.
        Collapse must not ride along in that tuple or an unrelated undo would
        silently expand the frame."""
        graph, stack, _scene = env
        graph.add_frame(Frame(id="f1", title="Stage"))
        stack.push(UpdateFrameCommand(graph, "f1", title="Renamed"))
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))
        stack.undo()                      # undo the collapse
        stack.undo()                      # undo the rename
        assert graph.frames["f1"].title == "Stage"
        stack.redo()                      # redo the rename
        assert graph.frames["f1"].collapsed is False
        stack.redo()                      # redo the collapse
        assert graph.frames["f1"].collapsed is True

    def test_collapsing_leaves_rect_expanded(self, env):
        """The collapsed box is derived, not stored: rect stays the expanded
        region so geometric membership keeps resolving."""
        graph, stack, _scene = env
        graph.add_frame(Frame(id="f1", rect=(10, 20, 400, 260)))
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))
        assert graph.frames["f1"].rect == (10, 20, 400, 260)

    def test_source_provenance_round_trips(self, registry):
        graph = Graph()
        graph.add_frame(Frame(id="f1", source="frame.prep",
                              source_fingerprint="abc123"))
        loaded = graph_from_dict(graph_to_dict(graph), registry)
        assert loaded.frames["f1"].source == "frame.prep"
        assert loaded.frames["f1"].source_fingerprint == "abc123"


def add_node(graph, registry, node_id, pos=(0.0, 0.0),
             type_id="flograph.util.constant"):
    node = registry.instantiate(type_id, pos=pos)
    node.id = node_id
    return graph.add_node(node)


class TestCollapsedBox:
    def test_collapsed_box_is_node_sized(self, env):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 400, 260)))
        item = scene.frame_items["f1"]
        assert item.display_size() == (400, 260)
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))
        assert item.display_size() == (COMPACT_W, COMPACT_MIN_H)
        # the region itself is untouched, which is what keeps membership working
        assert item.scene_rect().width() == 400

    def test_collapsed_frame_cannot_be_resized(self, env):
        """A resize writes the dragged size into frame.rect, so letting the
        60px box be grabbed would destroy the expanded geometry."""
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 400, 260)))
        item = scene.frame_items["f1"]
        assert item._edge_at(QPointF(400, 260)) == "corner"
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))
        assert item._edge_at(QPointF(60, 60)) is None
        assert item._edge_at(QPointF(400, 260)) is None

    def test_collapsed_frame_sits_above_nodes(self, env):
        from flograph.ui.canvas.stacking import (COLLAPSED_FRAME_Z, NODE_Z,
                                                 PENDING_WIRE_Z)
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1"))
        item = scene.frame_items["f1"]
        assert item.zValue() < NODE_Z
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))
        assert COLLAPSED_FRAME_Z <= item.zValue() < PENDING_WIRE_Z
        stack.undo()
        assert item.zValue() < NODE_Z

    def test_run_glyph_makes_way_for_the_chevron(self, env):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1"))
        item = scene.frame_items["f1"]
        assert not item._run_button_rect().isEmpty()
        assert not item._toggle_rect().isEmpty()
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))
        assert item._run_button_rect().isEmpty()
        assert not item._toggle_rect().isEmpty()

    def test_bounds_cover_the_name_and_status_strip(self, env):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", title="Sales prep"))
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))
        item = scene.frame_items["f1"]
        bounds = item.boundingRect()
        assert bounds.top() <= item._name_rect().top()
        assert bounds.bottom() >= item._status_rect().bottom()

    def test_toggle_click_is_undoable(self, env):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1"))
        item = scene.frame_items["f1"]
        item.toggle_collapsed()
        assert graph.frames["f1"].collapsed is True
        stack.undo()
        assert graph.frames["f1"].collapsed is False


class TestAggregateStatus:
    def _frame_with(self, env, registry, statuses):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 400, 260)))
        ids = []
        for i, status in enumerate(statuses):
            node = add_node(graph, registry, f"n{i}", pos=(10.0 * i, 10.0))
            graph.set_status(node.id, status)
            ids.append(node.id)
        item = scene.frame_items["f1"]
        item.set_members(ids)
        return item

    def test_empty_frame_is_idle(self, env):
        graph, _stack, scene = env
        graph.add_frame(Frame(id="f1"))
        status, progress, _stale = scene.frame_items["f1"].aggregate()
        assert status == NodeStatus.IDLE and progress == 0.0

    def test_error_beats_everything(self, env, registry):
        item = self._frame_with(env, registry, [NodeStatus.DONE,
                                                NodeStatus.RUNNING,
                                                NodeStatus.ERROR])
        assert item.aggregate()[0] == NodeStatus.ERROR

    def test_running_beats_queued_and_idle(self, env, registry):
        item = self._frame_with(env, registry, [NodeStatus.DONE,
                                                NodeStatus.QUEUED,
                                                NodeStatus.RUNNING])
        assert item.aggregate()[0] == NodeStatus.RUNNING

    def test_progress_is_the_share_finished(self, env, registry):
        item = self._frame_with(env, registry, [NodeStatus.DONE,
                                                NodeStatus.DONE,
                                                NodeStatus.RUNNING,
                                                NodeStatus.IDLE])
        assert item.aggregate()[1] == pytest.approx(0.5)

    def test_all_done_is_done(self, env, registry):
        item = self._frame_with(env, registry, [NodeStatus.DONE] * 3)
        status, progress, _stale = item.aggregate()
        assert status == NodeStatus.DONE and progress == 1.0

    def test_tooltip_carries_the_counts(self, env, registry):
        item = self._frame_with(env, registry, [NodeStatus.DONE,
                                                NodeStatus.DONE,
                                                NodeStatus.RUNNING])
        item.frame.collapsed = True
        item._refresh_status_tooltip()
        assert "2 of 3 done" in item.toolTip()
        assert "1 running" in item.toolTip()


class TestMatrixWindow:
    """The scrolling grid is pure arithmetic, so it is tested without paint."""

    def _frame(self, env, registry, count, frontier=None):
        graph, _stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 400, 260)))
        ids = []
        for i in range(count):
            node = add_node(graph, registry, f"n{i}", pos=(10.0 * i, 10.0))
            if frontier is not None and i <= frontier:
                graph.set_status(node.id, NodeStatus.DONE)
            ids.append(node.id)
        item = scene.frame_items["f1"]
        item.set_members(ids)
        return item

    def test_small_frame_shows_everything_from_the_start(self, env, registry):
        item = self._frame(env, registry, 6)
        start, shown = item.matrix_layout()
        assert start == 0 and len(shown) == 6

    def test_exactly_nine_still_fits(self, env, registry):
        item = self._frame(env, registry, 9)
        start, shown = item.matrix_layout()
        assert start == 0 and len(shown) == 9

    def test_window_holds_until_the_frontier_passes_the_middle(self, env, registry):
        item = self._frame(env, registry, 20, frontier=3)
        assert item.matrix_layout()[0] == 0

    def test_window_follows_the_frontier_once_past_the_middle(self, env, registry):
        item = self._frame(env, registry, 20, frontier=7)
        start, shown = item.matrix_layout()
        assert start == 3                 # frontier 7 - middle 4
        assert shown[0] == "n3"
        assert len(shown) == 8            # cell 0 spent on the "+3"

    def test_window_clamps_at_the_end(self, env, registry):
        item = self._frame(env, registry, 20, frontier=19)
        start, shown = item.matrix_layout()
        assert start == 12                # 20 - 8, not 19 - 4
        assert shown[-1] == "n19"

    def test_nothing_run_yet_sits_at_the_start(self, env, registry):
        item = self._frame(env, registry, 20)
        assert item.matrix_layout()[0] == 0


def script_node(graph, registry, node_id, pos):
    """A node with one input and one output, for wiring things up."""
    node = registry.instantiate("flograph.scripting.python_script", pos=pos)
    node.id = node_id
    return graph.add_node(node)


class TestHiding:
    def test_member_nodes_hide_and_restore(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        inside = script_node(graph, registry, "in", (50.0, 50.0))
        outside = script_node(graph, registry, "out", (500.0, 50.0))
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))
        assert not scene.node_items["in"].isVisible()
        assert scene.node_items["out"].isVisible()
        stack.undo()
        assert scene.node_items["in"].isVisible()

    def test_hidden_node_cannot_be_selected(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        script_node(graph, registry, "in", (50.0, 50.0))
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))
        scene.node_items["in"].setSelected(True)     # Qt refuses on hidden items
        assert not scene.node_items["in"].isSelected()

    def test_nested_frame_hides_and_restores(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="outer", rect=(0, 0, 400, 300)))
        graph.add_frame(Frame(id="inner", rect=(50, 50, 100, 100)))
        stack.push(SetFrameCollapsedCommand(graph, "outer", True))
        assert not scene.frame_items["inner"].isVisible()
        stack.undo()
        assert scene.frame_items["inner"].isVisible()

    def test_half_overlapping_frame_is_left_alone(self, env, registry):
        """Full containment, not centre: a frame poking out would take its
        own outside nodes with it."""
        graph, stack, scene = env
        graph.add_frame(Frame(id="outer", rect=(0, 0, 400, 300)))
        graph.add_frame(Frame(id="straddler", rect=(300, 50, 400, 100)))
        stack.push(SetFrameCollapsedCommand(graph, "outer", True))
        assert scene.frame_items["straddler"].isVisible()

    def test_node_added_to_the_vacated_region_is_not_swallowed(self, env, registry):
        """Membership is captured on the fold, not re-derived: the empty
        region is still ordinary canvas."""
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        script_node(graph, registry, "in", (50.0, 50.0))
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))
        script_node(graph, registry, "later", (100.0, 100.0))
        assert scene.node_items["later"].isVisible()

    def test_collapsed_frame_knows_its_members(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        script_node(graph, registry, "a", (50.0, 50.0))
        script_node(graph, registry, "b", (80.0, 80.0))
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))
        assert set(scene.frame_items["f1"].member_ids()) == {"a", "b"}
        stack.undo()
        assert scene.frame_items["f1"].member_ids() == []


class TestPins:
    def _crossing(self, env, registry, fan_out=1):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        src = script_node(graph, registry, "src", (500.0, 50.0))   # outside
        inner = script_node(graph, registry, "inner", (50.0, 50.0))
        graph.connect(src.id, "out1", inner.id, "in1")
        for i in range(fan_out):
            sink = script_node(graph, registry, f"sink{i}", (600.0, 100.0 * i))
            graph.connect(inner.id, "out1", sink.id, "in1")
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))
        return graph, stack, scene

    def test_one_pin_per_crossing_wire_no_dedupe(self, env, registry):
        """An inner output feeding three outside nodes shows three pins, not
        one — a pin means a wire, so it has a single honest endpoint."""
        _graph, _stack, scene = self._crossing(env, registry, fan_out=3)
        pins = list(scene._frame_pins.values())
        assert len(pins) == 4                      # 1 in + 3 out
        assert sum(1 for p in pins if p.side == "src") == 3
        assert sum(1 for p in pins if p.side == "dst") == 1

    def test_pins_carry_the_inner_node_identity(self, env, registry):
        _graph, _stack, scene = self._crossing(env, registry)
        pin = next(p for p in scene._frame_pins.values() if p.side == "dst")
        assert pin.node_id == "inner"
        assert "in1" in pin.label_text()

    def test_pin_label_is_hidden_at_rest_and_shown_on_hover(self, env, registry):
        _graph, _stack, scene = self._crossing(env, registry)
        pin = next(iter(scene._frame_pins.values()))
        assert not pin._label_shown()
        pin._hover = True
        assert pin._label_shown()

    def test_internal_wire_is_hidden_and_has_no_pin(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        a = script_node(graph, registry, "a", (50.0, 50.0))
        b = script_node(graph, registry, "b", (100.0, 100.0))
        conn, _ = graph.connect(a.id, "out1", b.id, "in1")
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))
        assert scene._frame_pins == {}
        assert not scene.connection_items[conn.id].isVisible()
        stack.undo()
        assert scene.connection_items[conn.id].isVisible()

    def test_wire_between_two_collapsed_frames_gets_a_pin_on_each(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="fa", rect=(0, 0, 200, 200)))
        graph.add_frame(Frame(id="fb", rect=(400, 0, 200, 200)))
        a = script_node(graph, registry, "a", (50.0, 50.0))
        b = script_node(graph, registry, "b", (450.0, 50.0))
        conn, _ = graph.connect(a.id, "out1", b.id, "in1")
        stack.push(SetFrameCollapsedCommand(graph, "fa", True))
        stack.push(SetFrameCollapsedCommand(graph, "fb", True))
        src_pin = scene._frame_pins[(conn.id, "src")]
        dst_pin = scene._frame_pins[(conn.id, "dst")]
        assert src_pin.frame_item.frame.id == "fa"
        assert dst_pin.frame_item.frame.id == "fb"
        item = scene.connection_items[conn.id]
        assert item.isVisible()
        assert item.src_anchor is src_pin and item.dst_anchor is dst_pin

    def test_wires_reanchor_to_real_ports_on_expand(self, env, registry):
        graph, stack, scene = self._crossing(env, registry)
        conn = next(iter(graph.connections.values()))
        item = scene.connection_items[conn.id]
        assert item.src_anchor is not item.src_port \
            or item.dst_anchor is not item.dst_port
        stack.undo()
        assert item.src_anchor is item.src_port
        assert item.dst_anchor is item.dst_port
        assert scene._frame_pins == {}

    def test_pins_stack_down_the_edges(self, env, registry):
        _graph, _stack, scene = self._crossing(env, registry, fan_out=4)
        outputs = sorted((p for p in scene._frame_pins.values()
                          if p.side == "src"), key=lambda p: p.pos().y())
        ys = [p.pos().y() for p in outputs]
        assert ys == sorted(ys) and len(set(ys)) == 4
        assert outputs[0].pos().x() > COMPACT_W    # right edge
        assert ys[-1] > COMPACT_MIN_H              # overflows below the box
        inputs = [p for p in scene._frame_pins.values() if p.side == "dst"]
        assert inputs[0].pos().x() < 0             # left edge

    def test_disconnecting_removes_the_pin(self, env, registry):
        graph, _stack, scene = self._crossing(env, registry)
        conn = next(c for c in graph.connections.values()
                    if c.dst_node == "inner")
        graph.disconnect(conn.id)
        assert (conn.id, "dst") not in scene._frame_pins


class TestLiveWires:
    def test_dropping_a_wire_on_a_pin_connects_the_inner_node(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        inner = script_node(graph, registry, "inner", (50.0, 50.0))
        sink = script_node(graph, registry, "sink", (600.0, 50.0))
        graph.connect(inner.id, "out1", sink.id, "in1")
        feeder = script_node(graph, registry, "feeder", (600.0, 300.0))
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))

        # the pin standing in for inner's *output* is a live drag source;
        # wire the outside feeder into inner's input the same way the scene
        # would once the drop lands on that pin
        pin = next(p for p in scene._frame_pins.values() if p.side == "src")
        assert pin.node_id == "inner"
        out_port = scene.node_items["feeder"].output_ports["out1"]
        assert scene._wire_valid(out_port, pin) is False   # output to output
        graph.connect(feeder.id, "out1", pin.node_id, "in1")
        assert graph.input_connection("inner", "in1") is not None
        # and the new crossing wire earns a pin of its own
        assert any(p.side == "dst" and p.node_id == "inner"
                   for p in scene._frame_pins.values())

    def test_detaching_from_a_pin_anchors_to_the_visible_source(self, env, registry):
        """Dragging a wire off an input pin continues from its source. When
        that source is folded inside *another* collapsed frame, the preview
        must start at that frame's pin, not at the hidden node's own."""
        graph, stack, scene = env
        graph.add_frame(Frame(id="fa", rect=(0, 0, 200, 200)))
        graph.add_frame(Frame(id="fb", rect=(400, 0, 200, 200)))
        a = script_node(graph, registry, "a", (50.0, 50.0))
        b = script_node(graph, registry, "b", (450.0, 50.0))
        conn, _ = graph.connect(a.id, "out1", b.id, "in1")
        stack.push(SetFrameCollapsedCommand(graph, "fa", True))
        stack.push(SetFrameCollapsedCommand(graph, "fb", True))

        dst_pin = scene._frame_pins[(conn.id, "dst")]
        src_pin = scene._frame_pins[(conn.id, "src")]
        scene.begin_wire_drag(dst_pin)
        assert scene._pending.fixed_port is src_pin
        assert scene._pending.fixed_port is not \
            scene.node_items["a"].output_ports["out1"]
        scene.cancel_wire_drag()

    def test_reroute_insertion_refused_on_a_crossing_wire(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        inner = script_node(graph, registry, "inner", (50.0, 50.0))
        sink = script_node(graph, registry, "sink", (600.0, 50.0))
        conn, _ = graph.connect(inner.id, "out1", sink.id, "in1")
        item = scene.connection_items[conn.id]
        assert not item._crosses_a_collapsed_frame()
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))
        assert item._crosses_a_collapsed_frame()
        before = len(graph.nodes)
        item.mouseDoubleClickEvent(_FakeDoubleClick())
        assert len(graph.nodes) == before      # no reroute conjured up


class TestMovement:
    def test_dragging_a_collapsed_frame_carries_hidden_members(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        node = script_node(graph, registry, "inner", (50.0, 50.0))
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))
        item = scene.frame_items["f1"]

        item._press_pos = item.pos()
        item._grabbed = [(scene.node_items["inner"],
                          scene.node_items["inner"].pos() - item.pos())]
        item._grabbed_frames = []
        item.setPos(QPointF(100.0, 80.0))
        scene.push_frame_move("f1", item.pos(), item._size,
                              {"inner": ((50.0, 50.0), (150.0, 130.0))})
        assert graph.nodes["inner"].pos == (150.0, 130.0)
        assert graph.frames["f1"].rect[:2] == (100.0, 80.0)
        stack.undo()                       # one macro, both back
        assert graph.nodes["inner"].pos == (50.0, 50.0)
        assert graph.frames["f1"].rect[:2] == (0.0, 0.0)

    def test_nested_frames_travel_with_their_parent(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="outer", rect=(0, 0, 400, 300)))
        graph.add_frame(Frame(id="inner", rect=(50, 50, 100, 100)))
        outer = scene.frame_items["outer"]
        _nodes, nested_items = outer.carried_items()
        assert [i.frame.id for i, _ in nested_items] == ["inner"]
        scene.push_frame_move("outer", QPointF(30.0, 30.0), outer._size, {},
                              {"inner": (80.0, 80.0, 100.0, 100.0)})
        assert graph.frames["inner"].rect[:2] == (80.0, 80.0)
        stack.undo()
        assert graph.frames["inner"].rect[:2] == (50.0, 50.0)

    def test_multi_selection_drag_carries_hidden_members(self, env, registry):
        """A collapsed frame's contents cannot be selected, so the group drag
        has to carry them explicitly or they get left behind."""
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        script_node(graph, registry, "inner", (50.0, 50.0))
        loose = script_node(graph, registry, "loose", (700.0, 700.0))
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))

        scene.frame_items["f1"].setSelected(True)
        scene.node_items["loose"].setSelected(True)
        starts = scene.begin_group_drag()
        assert "inner" in starts["carried"]
        # Qt would move the selected items; do that part by hand. The frame
        # is flagged as dragging, so its own itemChange snaps it to the grid —
        # take the delta from where it actually lands, not from what we asked.
        scene.frame_items["f1"].setPos(QPointF(40.0, 25.0))
        scene.node_items["loose"].setPos(QPointF(740.0, 725.0))
        landed = scene.frame_items["f1"].pos()
        loose_landed = scene.node_items["loose"].pos()
        scene.commit_group_move(starts)
        assert graph.nodes["inner"].pos == (50.0 + landed.x(),
                                            50.0 + landed.y())
        assert graph.nodes["loose"].pos == (loose_landed.x(), loose_landed.y())
        stack.undo()
        assert graph.nodes["inner"].pos == (50.0, 50.0)

    def test_crossing_wires_repath_after_a_frame_move(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        inner = script_node(graph, registry, "inner", (50.0, 50.0))
        sink = script_node(graph, registry, "sink", (600.0, 50.0))
        conn, _ = graph.connect(inner.id, "out1", sink.id, "in1")
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))
        item = scene.frame_items["f1"]
        before = scene.connection_items[conn.id].path().pointAtPercent(0.0)
        item.setPos(QPointF(150.0, 120.0))
        scene.frame_item_moved("f1")
        after = scene.connection_items[conn.id].path().pointAtPercent(0.0)
        assert before != after


class TestDelete:
    def _folded(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        a = script_node(graph, registry, "a", (50.0, 50.0))
        b = script_node(graph, registry, "b", (120.0, 120.0))
        graph.connect(a.id, "out1", b.id, "in1")
        sink = script_node(graph, registry, "sink", (600.0, 50.0))
        graph.connect(b.id, "out1", sink.id, "in1")
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))
        return graph, stack, scene

    def test_expanded_frame_delete_leaves_its_nodes(self, env, registry):
        """Unchanged behaviour: deleting an open frame has never removed the
        nodes inside it."""
        graph, _stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        script_node(graph, registry, "a", (50.0, 50.0))
        scene.delete_items([], [], ["f1"])
        assert "f1" not in graph.frames
        assert "a" in graph.nodes

    def test_collapsed_frame_delete_takes_its_members(self, env, registry):
        graph, stack, scene = self._folded(env, registry)
        scene.delete_items([], [], ["f1"])
        assert "f1" not in graph.frames
        assert "a" not in graph.nodes and "b" not in graph.nodes
        assert "sink" in graph.nodes          # outside, untouched

    def test_undo_restores_members_still_hidden(self, env, registry):
        """The macro pushes the frame before the nodes, because undo runs it
        backwards: the other order re-adds the frame while its members are
        still gone, so it folds around nothing and they come back visible
        sitting on top of the box."""
        graph, stack, scene = self._folded(env, registry)
        scene.delete_items([], [], ["f1"])
        stack.undo()
        assert graph.frames["f1"].collapsed is True
        assert "a" in graph.nodes and "b" in graph.nodes
        assert set(scene.frame_items["f1"].member_ids()) == {"a", "b"}
        assert not scene.node_items["a"].isVisible()
        assert not scene.node_items["b"].isVisible()

    def test_undo_restores_the_crossing_wire(self, env, registry):
        graph, stack, scene = self._folded(env, registry)
        before = len(graph.connections)
        scene.delete_items([], [], ["f1"])
        stack.undo()
        assert len(graph.connections) == before
        assert scene._frame_pins            # and it is pinned to the box again

    def test_it_is_one_undo_step(self, env, registry):
        graph, stack, scene = self._folded(env, registry)
        depth = stack.index()
        scene.delete_items([], [], ["f1"])
        assert stack.index() == depth + 1

    def test_confirm_returning_false_deletes_nothing(self, env, registry):
        graph, stack, scene = self._folded(env, registry)
        scene.confirm_collapsed_delete = lambda titles, count: False
        scene.delete_items([], [], ["f1"])
        assert "f1" in graph.frames and "a" in graph.nodes

    def test_confirm_is_told_what_goes(self, env, registry):
        graph, stack, scene = self._folded(env, registry)
        seen = {}

        def confirm(titles, count):
            seen["titles"], seen["count"] = titles, count
            return True

        scene.confirm_collapsed_delete = confirm
        scene.delete_items([], [], ["f1"])
        assert seen["count"] == 2
        assert seen["titles"] == ["Frame"]

    def test_expanded_frame_never_asks(self, env, registry):
        graph, _stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        script_node(graph, registry, "a", (50.0, 50.0))
        scene.confirm_collapsed_delete = lambda *a: pytest.fail("asked")
        scene.delete_items([], [], ["f1"])
        assert "f1" not in graph.frames


class _FakeDoubleClick:
    def scenePos(self):
        return QPointF(100.0, 100.0)

    def accept(self):
        pass


class TestPainting:
    """paint() is where the geometry actually runs; render it for real."""

    def _render(self, scene):
        image = QImage(400, 300, QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        scene.render(painter)
        painter.end()
        return image

    @pytest.mark.parametrize("members", [0, 1, 9, 25])
    @pytest.mark.parametrize("collapsed", [False, True])
    def test_frame_renders(self, env, registry, members, collapsed):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", title="Sales prep and cleanup",
                              rect=(0, 0, 400, 260)))
        ids = []
        for i in range(members):
            node = add_node(graph, registry, f"n{i}", pos=(10.0 * i, 10.0))
            graph.set_status(node.id, NodeStatus.DONE if i % 2 else
                             NodeStatus.RUNNING)
            ids.append(node.id)
        item = scene.frame_items["f1"]
        item.set_members(ids)
        if collapsed:
            stack.push(SetFrameCollapsedCommand(graph, "f1", True))
        self._render(scene)     # must not raise
        item.set_members([])    # stop any pulse before teardown
        item._stop_pulse()

    def test_running_frame_pulses_only_while_collapsed(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 400, 260)))
        node = add_node(graph, registry, "n0", pos=(10.0, 10.0))
        graph.set_status(node.id, NodeStatus.RUNNING)
        item = scene.frame_items["f1"]
        item.set_members([node.id])
        assert item._pulse_anim is None          # expanded: no animation
        stack.push(SetFrameCollapsedCommand(graph, "f1", True))
        item.refresh_status()
        assert item._pulse_anim is not None      # collapsed and indeterminate
        stack.undo()
        assert item._pulse_anim is None          # and stopped again on expand
