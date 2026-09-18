"""Collapsible frames: the model, the collapsed box, its pins and its wires.

Frames had no test file of their own before this — drag, resize, rename and
the carry-your-contents behaviour were all untested — so this covers the
collapse feature and the frame behaviour it leans on.
"""
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QUndoStack
from PySide6.QtWidgets import (QGraphicsSceneHoverEvent,
                               QGraphicsSceneMouseEvent)

from flograph.core import Frame, Graph, NodeRegistry
from flograph.core.node import NodeStatus
from flograph.core.serialization import graph_from_dict, graph_to_dict
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.canvas.frame_item import TITLE_H
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
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", title="Stage"))
        collapse(scene, "f1")
        assert graph.frames["f1"].collapsed is True
        stack.undo()
        assert graph.frames["f1"].collapsed is False
        stack.redo()
        assert graph.frames["f1"].collapsed is True

    def test_update_frame_does_not_clobber_collapsed(self, env):
        """UpdateFrameCommand rewrites (title, rect, color) wholesale on undo.
        Collapse must not ride along in that tuple or an unrelated undo would
        silently expand the frame."""
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", title="Stage"))
        stack.push(UpdateFrameCommand(graph, "f1", title="Renamed"))
        collapse(scene, "f1")
        stack.undo()                      # undo the collapse
        stack.undo()                      # undo the rename
        assert graph.frames["f1"].title == "Stage"
        stack.redo()                      # redo the rename
        assert graph.frames["f1"].collapsed is False
        stack.redo()                      # redo the collapse
        assert graph.frames["f1"].collapsed is True

    def test_collapsing_really_shrinks_the_rect(self, env):
        """The frame claims no canvas it isn't drawing, so a folded box
        cannot absorb or drag whatever it is parked over."""
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(10, 20, 400, 260)))
        collapse(scene, "f1")
        assert graph.frames["f1"].rect == (10, 20, COMPACT_W, COMPACT_MIN_H)
        assert graph.frames["f1"].expanded_size == (400, 260)
        stack.undo()
        assert graph.frames["f1"].rect == (10, 20, 400, 260)
        assert graph.frames["f1"].expanded_size is None

    def test_expanding_restores_the_size_where_it_now_sits(self, env):
        """Position survives the fold, size is restored around it."""
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 400, 260)))
        collapse(scene, "f1")
        graph.update_frame("f1", rect=(900.0, 700.0, COMPACT_W, COMPACT_MIN_H))
        expand(scene, "f1")
        assert graph.frames["f1"].rect == (900.0, 700.0, 400.0, 260.0)

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


def collapse(scene, frame_id):
    """Fold a frame the way the chevron does.

    Not by pushing SetFrameCollapsedCommand bare: the canvas is what works
    out which items are inside, and a command built without that owns
    nothing. Going through the item is the real path and the only one that
    captures membership.
    """
    scene.frame_items[frame_id].toggle_collapsed()


def expand(scene, frame_id):
    scene.frame_items[frame_id].toggle_collapsed()


class TestCollapsedBox:
    def test_collapsed_box_is_node_sized(self, env):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 400, 260)))
        item = scene.frame_items["f1"]
        assert item.display_size() == (400, 260)
        collapse(scene, "f1")
        assert item.display_size() == (COMPACT_W, COMPACT_MIN_H)
        # and it really occupies only that — no invisible footprint left
        assert item.scene_rect().width() == COMPACT_W
        assert item.expanded_rect().width() == 400

    def test_collapsed_frame_cannot_be_resized(self, env):
        """A resize writes the dragged size into frame.rect, so letting the
        60px box be grabbed would destroy the expanded geometry."""
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 400, 260)))
        item = scene.frame_items["f1"]
        assert item._edge_at(QPointF(400, 260)) == "corner"
        collapse(scene, "f1")
        assert item._edge_at(QPointF(60, 60)) is None
        assert item._edge_at(QPointF(400, 260)) is None

    def test_collapsed_frame_sits_above_nodes(self, env):
        from flograph.ui.canvas.stacking import (COLLAPSED_FRAME_Z, NODE_Z,
                                                 PENDING_WIRE_Z)
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1"))
        item = scene.frame_items["f1"]
        assert item.zValue() < NODE_Z
        collapse(scene, "f1")
        assert COLLAPSED_FRAME_Z <= item.zValue() < PENDING_WIRE_Z
        stack.undo()
        assert item.zValue() < NODE_Z

    def test_run_glyph_makes_way_for_the_chevron(self, env):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1"))
        item = scene.frame_items["f1"]
        assert not item._run_button_rect().isEmpty()
        assert not item._toggle_rect().isEmpty()
        collapse(scene, "f1")
        assert item._run_button_rect().isEmpty()
        assert not item._toggle_rect().isEmpty()

    def test_bounds_cover_the_name_and_status_strip(self, env):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", title="Sales prep"))
        collapse(scene, "f1")
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
        collapse(scene, "f1")
        assert not scene.node_items["in"].isVisible()
        assert scene.node_items["out"].isVisible()
        stack.undo()
        assert scene.node_items["in"].isVisible()

    def test_hidden_node_cannot_be_selected(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        script_node(graph, registry, "in", (50.0, 50.0))
        collapse(scene, "f1")
        scene.node_items["in"].setSelected(True)     # Qt refuses on hidden items
        assert not scene.node_items["in"].isSelected()

    def test_nested_frame_hides_and_restores(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="outer", rect=(0, 0, 400, 300)))
        graph.add_frame(Frame(id="inner", rect=(50, 50, 100, 100)))
        collapse(scene, "outer")
        assert not scene.frame_items["inner"].isVisible()
        stack.undo()
        assert scene.frame_items["inner"].isVisible()

    def test_half_overlapping_frame_is_left_alone(self, env, registry):
        """Full containment, not centre: a frame poking out would take its
        own outside nodes with it."""
        graph, stack, scene = env
        graph.add_frame(Frame(id="outer", rect=(0, 0, 400, 300)))
        graph.add_frame(Frame(id="straddler", rect=(300, 50, 400, 100)))
        collapse(scene, "outer")
        assert scene.frame_items["straddler"].isVisible()

    def test_node_added_to_the_vacated_region_is_not_swallowed(self, env, registry):
        """Membership is captured on the fold, not re-derived: the empty
        region is still ordinary canvas."""
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        script_node(graph, registry, "in", (50.0, 50.0))
        collapse(scene, "f1")
        script_node(graph, registry, "later", (100.0, 100.0))
        assert scene.node_items["later"].isVisible()

    def test_collapsed_frame_knows_its_members(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        script_node(graph, registry, "a", (50.0, 50.0))
        script_node(graph, registry, "b", (80.0, 80.0))
        collapse(scene, "f1")
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
        collapse(scene, "f1")
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
        collapse(scene, "f1")
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
        collapse(scene, "fa")
        collapse(scene, "fb")
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
        collapse(scene, "f1")

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
        collapse(scene, "fa")
        collapse(scene, "fb")

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
        collapse(scene, "f1")
        assert item._crosses_a_collapsed_frame()
        before = len(graph.nodes)
        item.mouseDoubleClickEvent(_FakeDoubleClick())
        assert len(graph.nodes) == before      # no reroute conjured up


class TestMovement:
    def test_dragging_a_collapsed_frame_carries_hidden_members(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        node = script_node(graph, registry, "inner", (50.0, 50.0))
        collapse(scene, "f1")
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
        collapse(scene, "f1")

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
        collapse(scene, "f1")
        item = scene.frame_items["f1"]
        before = scene.connection_items[conn.id].path().pointAtPercent(0.0)
        item.setPos(QPointF(150.0, 120.0))
        scene.frame_item_moved("f1")
        after = scene.connection_items[conn.id].path().pointAtPercent(0.0)
        assert before != after


class TestDragHandle:
    """A frame drags by its title bar and by nothing else.

    It used to drag from anywhere inside its rectangle, which is invisible
    trouble once a frame is bigger than the viewport: its edges are off
    screen, so a press on what looks like empty canvas picks the whole box
    up and slides its contents. Reported on the retail example, where two
    1042x762 frames cover most of the canvas.
    """

    def _press(self, item, pos, button=Qt.LeftButton):
        event = QGraphicsSceneMouseEvent(QEvent.GraphicsSceneMousePress)
        event.setPos(pos)
        event.setScenePos(item.mapToScene(pos))
        event.setButton(button)
        event.setButtons(button)
        event.setModifiers(Qt.NoModifier)
        event.setAccepted(True)      # Qt's own default for a press
        item.mousePressEvent(event)
        return event

    def _frame(self, env, rect=(0.0, 0.0, 600.0, 400.0)):
        graph, _stack, scene = env
        graph.add_frame(Frame(id="f1", title="Stage", rect=rect))
        return scene.frame_items["f1"]

    def test_the_title_bar_drags_it(self, env):
        item = self._frame(env)
        assert item.chrome_at(QPointF(300.0, TITLE_H - 2))

    def test_the_body_does_not(self, env):
        item = self._frame(env)
        assert not item.chrome_at(QPointF(300.0, 200.0))
        assert not item.chrome_at(QPointF(300.0, TITLE_H + 1))

    def test_a_press_on_the_body_is_passed_on(self, env):
        """Ignored, not swallowed — that is what lets the rubber band and
        everything else underneath have it."""
        item = self._frame(env)
        event = self._press(item, QPointF(300.0, 200.0))
        assert not event.isAccepted()

    def test_a_press_on_the_body_starts_no_drag(self, env, registry):
        graph, _stack, scene = env
        item = self._frame(env)
        script_node(graph, registry, "inner", (50.0, 100.0))
        self._press(item, QPointF(300.0, 200.0))
        assert item._dragging is False
        assert item._grabbed == []      # nothing picked up to carry

    def test_a_press_on_the_title_takes_hold(self, env, registry):
        graph, _stack, scene = env
        item = self._frame(env)
        script_node(graph, registry, "inner", (50.0, 100.0))
        self._press(item, QPointF(300.0, 6.0))
        assert item._dragging is True
        assert [n.node.id for n, _offset in item._grabbed] == ["inner"]

    def test_a_right_click_on_the_body_is_passed_on_too(self, env):
        """The frame no longer takes a press it would do nothing with. Note
        this is only the press: the context *menu* is a separate event the
        view routes by itemAt, so right-clicking a frame's body still opens
        the frame's own menu."""
        item = self._frame(env)
        event = self._press(item, QPointF(300.0, 200.0), Qt.RightButton)
        assert not event.isAccepted()

    def test_the_resize_edges_still_work(self, env):
        item = self._frame(env)
        w, h = item._size
        event = self._press(item, QPointF(w - 2, h - 2))
        assert event.isAccepted()
        assert item._resizing is True

    def test_a_collapsed_frame_drags_from_anywhere(self, env, registry):
        """It is a small square standing in for its contents, with its name
        above it rather than a title bar inside it — so it drags like the
        node it is pretending to be."""
        graph, _stack, scene = env
        item = self._frame(env)
        script_node(graph, registry, "inner", (50.0, 100.0))
        collapse(scene, "f1")
        assert item.chrome_at(QPointF(20.0, 40.0))
        self._press(item, QPointF(20.0, 40.0))
        assert item._dragging is True

    def test_the_title_bar_says_it_is_the_handle(self, env):
        item = self._frame(env)
        event = QGraphicsSceneHoverEvent(QEvent.GraphicsSceneHoverMove)
        event.setPos(QPointF(300.0, 6.0))
        item.hoverMoveEvent(event)
        assert item.cursor().shape() == Qt.SizeAllCursor

    # What a rubber band drawn inside a frame comes back with is the other
    # half of "the body is canvas", and it is tested in
    # tests/test_rubber_band_selection.py — through a real drag on a view,
    # which is the only way it can be. The rule used to live in a
    # NodeGraphScene.setSelectionArea override and was tested by calling that
    # override; the function is not virtual, so Qt's rubber band never called
    # it and the tests were the only thing that did.

    def test_the_body_does_not_say_that(self, env):
        item = self._frame(env)
        event = QGraphicsSceneHoverEvent(QEvent.GraphicsSceneHoverMove)
        event.setPos(QPointF(300.0, 200.0))
        item.hoverMoveEvent(event)
        assert item.cursor().shape() == Qt.ArrowCursor


class TestDelete:
    def _folded(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        a = script_node(graph, registry, "a", (50.0, 50.0))
        b = script_node(graph, registry, "b", (120.0, 120.0))
        graph.connect(a.id, "out1", b.id, "in1")
        sink = script_node(graph, registry, "sink", (600.0, 50.0))
        graph.connect(b.id, "out1", sink.id, "in1")
        collapse(scene, "f1")
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


class TestLoadAndCanvasSurface:
    def test_scene_built_over_a_collapsed_graph_hides_members(self, qtbot, registry):
        """The constructor mirrors nodes, then wires, then frames — a frame
        that is already collapsed has to fold on arrival."""
        graph = Graph()
        node = registry.instantiate("flograph.scripting.python_script",
                                    pos=(50.0, 50.0))
        node.id = "inner"
        graph.add_node(node)
        graph.add_frame(Frame(
            id="f1", rect=(0, 0, COMPACT_W, COMPACT_MIN_H), collapsed=True,
            expanded_size=(300.0, 200.0), members=("inner",)))
        stack = QUndoStack()
        scene = NodeGraphScene(graph, stack, registry=registry)
        assert not scene.node_items["inner"].isVisible()
        assert scene.frame_items["f1"].member_ids() == ["inner"]
        stack.clear()

    def test_collapsed_survives_a_save_and_reload(self, qtbot, registry):
        graph = Graph()
        node = registry.instantiate("flograph.scripting.python_script",
                                    pos=(50.0, 50.0))
        node.id = "inner"
        graph.add_node(node)
        graph.add_frame(Frame(
            id="f1", rect=(0, 0, COMPACT_W, COMPACT_MIN_H), collapsed=True,
            expanded_size=(300.0, 200.0), members=("inner",)))
        reloaded = graph_from_dict(graph_to_dict(graph), registry)
        stack = QUndoStack()
        scene = NodeGraphScene(reloaded, stack, registry=registry)
        assert reloaded.frames["f1"].collapsed is True
        assert not scene.node_items["inner"].isVisible()
        stack.clear()

    def test_run_frame_still_finds_hidden_members(self, qtbot, registry):
        """The rect no longer covers them, so the run paths read the
        membership the frame wrote down instead."""
        from flograph.ui.mainwindow import MainWindow
        win = MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        node = registry.instantiate("flograph.scripting.python_script",
                                    pos=(50.0, 50.0))
        node.id = "inner"
        win.graph.add_node(node)
        win.graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200),
                                  title="Prep"))
        assert win._frame_node_ids_by_id("f1") == ["inner"]
        collapse(win.scene, "f1")
        assert win._frame_node_ids_by_id("f1") == ["inner"]
        assert win._frame_node_ids("Prep") == ["inner"]

    def test_lod_hides_the_frame_pins(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        inner = script_node(graph, registry, "inner", (50.0, 50.0))
        sink = script_node(graph, registry, "sink", (600.0, 50.0))
        graph.connect(inner.id, "out1", sink.id, "in1")
        collapse(scene, "f1")
        pin = next(iter(scene._frame_pins.values()))
        assert pin.isVisible()
        scene.set_lod(0.05)                    # well below the threshold
        assert not pin.isVisible()
        scene.set_lod(1.0)
        assert pin.isVisible()

    def test_reveal_key_shows_the_pin_labels(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        inner = script_node(graph, registry, "inner", (50.0, 50.0))
        sink = script_node(graph, registry, "sink", (600.0, 50.0))
        graph.connect(inner.id, "out1", sink.id, "in1")
        collapse(scene, "f1")
        pin = next(iter(scene._frame_pins.values()))
        assert not pin._label_shown()
        scene.set_revealing_port_labels(True)
        assert pin._label_shown()
        scene.set_revealing_port_labels(False)
        assert not pin._label_shown()

    def test_replacing_the_graph_drops_the_pins(self, qtbot, registry):
        """Opening another project while a collapsed frame has pins.

        A pin is a *child* of its frame, so removing the frame takes it out
        of the scene too. _replace_graph suspends the rebuild, so nothing
        pruned _frame_pins on the way through, and the refresh at the end
        then called removeItem on items whose scene was already gone —
        "item's scene (0x0) is different from this scene", four times, and
        a segfault behind it.
        """
        from flograph.core import Graph
        from flograph.ui.mainwindow import MainWindow
        win = MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        inner = registry.instantiate("flograph.scripting.python_script",
                                     pos=(50.0, 50.0))
        sink = registry.instantiate("flograph.scripting.python_script",
                                    pos=(600.0, 50.0))
        win.graph.add_node(inner)
        win.graph.add_node(sink)
        win.graph.connect(inner.id, "out1", sink.id, "in1")
        win.graph.add_frame(Frame(
            id="f1", rect=(0, 0, COMPACT_W, COMPACT_MIN_H), collapsed=True,
            expanded_size=(300.0, 200.0), members=(inner.id,)))
        assert win.scene._frame_pins, "expected a pin for the crossing wire"

        win._replace_graph(Graph())        # File > New, or Open Example
        assert win.scene._frame_pins == {}
        assert win.scene._hidden == {}

    def test_removing_a_frame_drops_its_pins(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        inner = script_node(graph, registry, "inner", (50.0, 50.0))
        sink = script_node(graph, registry, "sink", (600.0, 50.0))
        graph.connect(inner.id, "out1", sink.id, "in1")
        collapse(scene, "f1")
        assert scene._frame_pins
        graph.remove_frame("f1")
        assert scene._frame_pins == {}
        assert scene._hidden == {}
        assert scene.node_items["inner"].isVisible()

    def test_hidden_node_stops_animating(self, env, registry):
        """setVisible alone does not re-derive the QMovie decisions; the
        item has to hear about its own visibility change."""
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        script_node(graph, registry, "inner", (50.0, 50.0))
        item = scene.node_items["inner"]
        calls = []
        item._apply_proxy_visibility = lambda: calls.append(1)
        collapse(scene, "f1")
        assert calls, "hiding a node must re-derive its playback state"


class _FakeDoubleClick:
    def scenePos(self):
        return QPointF(100.0, 100.0)

    def accept(self):
        pass


class TestParkedOverOtherNodes:
    """What a folded frame does to whatever it is sitting on.

    It must never *drag it around*: a drag carries the frame's own members
    and nothing else, and it was carrying bystanders as a side effect,
    which is the bug behind "ctrl-z didn't put them back".

    It no longer pushes them out of the way when it reopens (0.1.15) — see
    `TestReopeningMovesNothingElse`. The consequence, stated plainly
    because it is a real one: a frame reopened over a node now has that
    node inside it, drawn inside it, and folding again takes it in. That is
    what the canvas is showing you before you fold, which is the part that
    makes it fair; the nudge hid the question by shoving the node away
    first, at a price paid everywhere else.
    """

    def _folded_over_bystanders(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        script_node(graph, registry, "inside", (50.0, 50.0))
        script_node(graph, registry, "bystander1", (900.0, 900.0))
        script_node(graph, registry, "bystander2", (960.0, 960.0))
        collapse(scene, "f1")
        # park the little box right on top of them, carrying its own member
        # the way a real drag does
        item = scene.frame_items["f1"]
        graph.update_frame("f1", rect=(880.0, 880.0, COMPACT_W, COMPACT_MIN_H))
        graph.move_node("inside", (930.0, 930.0))
        return graph, stack, scene, item

    def test_what_the_reopened_frame_is_drawn_around_folds_into_it(
            self, env, registry):
        """A node the reopened region covers is inside the frame, and one
        Ctrl+Z is the way back out."""
        graph, stack, scene, item = self._folded_over_bystanders(env, registry)
        expand(scene, "f1")            # region reappears over the bystanders
        assert item.scene_rect().contains(
            scene.node_items["bystander1"].sceneBoundingRect().center())
        collapse(scene, "f1")
        assert "bystander1" in item.member_ids()
        stack.undo()
        assert scene.node_items["bystander1"].isVisible()

    def test_one_it_is_merely_near_is_left_out(self, env, registry):
        """Covered is covered; beside it is not."""
        graph, stack, scene, item = self._folded_over_bystanders(env, registry)
        script_node(graph, registry, "clear_of_it", (5000.0, 5000.0))
        expand(scene, "f1")
        collapse(scene, "f1")
        assert "clear_of_it" not in item.member_ids()
        assert scene.node_items["clear_of_it"].isVisible()

    def test_dragging_it_does_not_carry_what_it_sits_on(self, env, registry):
        """The bug behind 'ctrl-z didn't put them back': the drag moved
        bystanders as a side effect, and that move was a separate undo entry
        from the collapse."""
        graph, stack, scene, item = self._folded_over_bystanders(env, registry)
        nodes, _frames = item.carried_items()
        carried = {i.node.id for i, _off in nodes}
        assert carried == {"inside"}
        assert "bystander1" not in carried and "bystander2" not in carried

    def test_expanding_leaves_the_bystanders_exactly_where_they_are(
            self, env, registry):
        graph, stack, scene, item = self._folded_over_bystanders(env, registry)
        before = {n: graph.nodes[n].pos
                  for n in ("bystander1", "bystander2")}
        expand(scene, "f1")
        assert {n: graph.nodes[n].pos for n in before} == before
        # and its own contents were left exactly where they were
        assert item.scene_rect().contains(
            scene.node_items["inside"].sceneBoundingRect().center())

    def test_one_undo_puts_the_frame_and_the_bystanders_back(self, env, registry):
        graph, stack, scene, item = self._folded_over_bystanders(env, registry)
        before = {n: graph.nodes[n].pos
                  for n in ("bystander1", "bystander2", "inside")}
        expand(scene, "f1")
        stack.undo()
        assert graph.frames["f1"].collapsed is True
        assert {n: graph.nodes[n].pos for n in before} == before

    def test_folding_and_reopening_changes_nothing_at_all(self, env, registry):
        """The ratchet, end to end. Nothing else has moved, so the frame is
        growing back into the space it vacated and the canvas must be
        untouched — not merely restored afterwards, but never disturbed."""
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        script_node(graph, registry, "inside", (50.0, 50.0))
        script_node(graph, registry, "right", (400.0, 20.0))
        script_node(graph, registry, "below", (20.0, 400.0))
        before = {n: graph.nodes[n].pos for n in ("right", "below")}
        for _ in range(3):
            collapse(scene, "f1")
            expand(scene, "f1")
            assert {n: graph.nodes[n].pos for n in before} == before

    def test_a_node_left_of_the_line_never_moves_however_close(self, env,
                                                              registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(400, 400, 300, 200)))
        script_node(graph, registry, "inside", (450.0, 450.0))
        left = script_node(graph, registry, "left", (100.0, 410.0))
        collapse(scene, "f1")
        before = graph.nodes["left"].pos
        expand(scene, "f1")
        assert graph.nodes["left"].pos == before


def _hover(item, pos):
    event = QGraphicsSceneHoverEvent(QEvent.GraphicsSceneHoverMove)
    event.setPos(QPointF(pos))
    item.hoverMoveEvent(event)


class TestSeeingWhereItWouldReopen:
    """Rest on a collapsed frame's chevron and the canvas outlines the
    region it would grow back into.

    It earns its place *because* reopening no longer pushes anything aside
    (see `TestReopeningMovesNothingElse`): what the region lands on is what
    ends up inside the frame, so the question "what am I about to take in?"
    now has consequences, and this is how it gets answered before the click
    rather than after it.
    """

    def _folded(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 620, 380),
                              color="#33415c"))
        add_node(graph, registry, "inside", pos=(40.0, 60.0))
        collapse(scene, "f1")
        # dropped into the space the fold left — what the preview is for
        add_node(graph, registry, "squatter", pos=(300.0, 200.0))
        return graph, stack, scene, scene.frame_items["f1"]

    def test_hovering_the_chevron_outlines_the_region(self, env, registry):
        _graph, _stack, scene, item = self._folded(env, registry)
        assert scene._expand_preview is None
        _hover(item, item._toggle_rect().center())
        assert scene._expand_preview == item.expanded_rect()

    def test_it_covers_what_the_reopen_would_take_in(self, env, registry):
        """The point of it, as a property rather than a rectangle: the node
        sitting in the vacated space is inside what gets outlined."""
        _graph, _stack, scene, item = self._folded(env, registry)
        _hover(item, item._toggle_rect().center())
        squatter = scene.node_items["squatter"].sceneBoundingRect().center()
        assert scene._expand_preview.contains(squatter)

    def test_moving_off_the_chevron_takes_it_away(self, env, registry):
        _graph, _stack, scene, item = self._folded(env, registry)
        _hover(item, item._toggle_rect().center())
        _hover(item, QPointF(item.display_size()[0] - 2, 2))
        assert scene._expand_preview is None

    def test_leaving_the_frame_takes_it_away(self, env, registry):
        _graph, _stack, scene, item = self._folded(env, registry)
        _hover(item, item._toggle_rect().center())
        item.hoverLeaveEvent(QGraphicsSceneHoverEvent(
            QEvent.GraphicsSceneHoverLeave))
        assert scene._expand_preview is None

    def test_clicking_it_takes_it_away(self, env, registry):
        """The region stops being a guess the moment it is real."""
        _graph, _stack, scene, item = self._folded(env, registry)
        _hover(item, item._toggle_rect().center())
        item.toggle_collapsed()
        assert scene._expand_preview is None

    def test_an_expanded_frame_offers_none(self, env, registry):
        """It is already showing you its region; a dashed copy of the edge
        it is drawing would say nothing."""
        graph, _stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 620, 380)))
        add_node(graph, registry, "inside", pos=(40.0, 60.0))
        item = scene.frame_items["f1"]
        _hover(item, item._toggle_rect().center())
        assert scene._expand_preview is None

    def test_it_borrows_the_frames_own_colour(self, env, registry):
        _graph, _stack, scene, item = self._folded(env, registry)
        _hover(item, item._toggle_rect().center())
        assert scene._expand_preview_color.name() == "#33415c"

    def test_it_paints_outside_the_little_box(self, env, registry):
        """Pixels, not state: the region is many times the size of the box,
        so it has to be drawn by the scene — a frame painting it would be
        clipped to its own bounds (see `set_expand_preview`)."""
        _graph, _stack, scene, item = self._folded(env, registry)
        area = QRectF(-20, -20, 700, 460)

        def shot():
            image = QImage(360, 240, QImage.Format_ARGB32)
            image.fill(0xFF1B1E27)
            painter = QPainter(image)
            scene.render(painter, QRectF(image.rect()), area)
            painter.end()
            return image

        before = shot()
        _hover(item, item._toggle_rect().center())
        after = shot()
        assert after != before
        # and in the far corner of the image, a long way outside the 60px
        # box the collapsed frame is drawn as. Counted over a patch rather
        # than read at one point: the outline is dashed, so any single
        # pixel of it may fall in a gap.
        changed = sum(1 for x in range(240, 360) for y in range(160, 240)
                      if after.pixel(x, y) != before.pixel(x, y))
        assert changed > 0, "nothing was drawn outside the collapsed box"


class TestReopeningMovesNothingElse:
    """0.1.15: reopening a frame does not rearrange the canvas.

    It used to. `plan_nudge` shoved every node and frame at or beyond the
    returning region to the right, recorded how far each went on
    `Frame.nudged`, and `unnudge_plan` took that displacement back off when
    the frame folded again — *wherever the thing had got to since*, which
    its own docstring admitted: "a thing moved somewhere deliberate since
    the expand still slides back by the shift when the frame folds". So a
    node you had placed yourself slid sideways for reasons you could not
    see, and fold/unfold cycles compounded it. That is Dan's "nodes lose
    track of their location and shoot off to the right".

    These are the tests that would have caught it. They are deliberately
    about *positions not changing*, because the whole class of bug is the
    canvas moving something nobody asked it to.
    """

    def _frame_with_neighbours(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 400, 300)))
        script_node(graph, registry, "inside", (40.0, 40.0))
        collapse(scene, "f1")
        # three neighbours in the space the fold vacated and beyond it —
        # each of these used to be displaced
        script_node(graph, registry, "in_the_way", (150.0, 40.0))
        script_node(graph, registry, "beyond", (600.0, 40.0))
        script_node(graph, registry, "below", (40.0, 500.0))
        graph.add_frame(Frame(id="neighbour", rect=(700, 0, 200, 150)))
        script_node(graph, registry, "theirs", (740.0, 40.0))
        return graph, stack, scene

    def _positions(self, graph):
        return ({n: graph.nodes[n].pos for n in graph.nodes},
                {f: graph.frames[f].rect for f in graph.frames
                 if f != "f1"})

    def test_reopening_moves_no_node_and_no_frame(self, env, registry):
        graph, stack, scene = self._frame_with_neighbours(env, registry)
        before = self._positions(graph)
        expand(scene, "f1")
        assert self._positions(graph) == before

    def test_and_folding_it_again_moves_nothing_either(self, env, registry):
        graph, stack, scene = self._frame_with_neighbours(env, registry)
        expand(scene, "f1")
        before = self._positions(graph)
        collapse(scene, "f1")
        assert self._positions(graph)[1] == before[1]

    def test_ten_cycles_leave_the_canvas_where_it_started(self, env, registry):
        """The ratchet. Each fold/unfold used to add another displacement
        that the next fold subtracted from somewhere else."""
        graph, stack, scene = self._frame_with_neighbours(env, registry)
        before = self._positions(graph)
        for _ in range(10):
            expand(scene, "f1")
            collapse(scene, "f1")
        expand(scene, "f1")
        assert self._positions(graph) == before

    def test_a_node_moved_while_the_frame_was_open_keeps_its_place(
            self, env, registry):
        """The exact failure the old docstring owned up to: a deliberate
        move, then a fold, and the node slid by a shift it never had."""
        graph, stack, scene = self._frame_with_neighbours(env, registry)
        expand(scene, "f1")
        graph.move_node("beyond", (1234.0, 567.0))
        collapse(scene, "f1")
        assert graph.nodes["beyond"].pos == (1234.0, 567.0)
        expand(scene, "f1")
        assert graph.nodes["beyond"].pos == (1234.0, 567.0)

    def test_expanding_is_one_undo_step(self, env, registry):
        graph, stack, scene = self._frame_with_neighbours(env, registry)
        before = stack.count()
        expand(scene, "f1")
        assert stack.count() == before + 1
        stack.undo()
        assert graph.frames["f1"].collapsed is True

    def test_nothing_writes_a_displacement_record_any_more(self, env,
                                                           registry):
        """The mechanism, not just the behaviour: the field is gone from
        the model, so nothing can quietly start recording again."""
        graph, stack, scene = self._frame_with_neighbours(env, registry)
        expand(scene, "f1")
        assert not hasattr(graph.frames["f1"], "nudged")

    def test_a_file_written_before_this_still_opens(self, env, registry):
        """Old projects carry a "nudged" key on their frames. It is read
        past, and nothing it says is acted on."""
        graph, stack, scene = self._frame_with_neighbours(env, registry)
        data = graph_to_dict(graph)
        frames = data["graph"]["frames"]
        assert all("nudged" not in f for f in frames)
        frames[0]["nudged"] = [["node", "beyond", 500.0, 0.0, 1100.0, 40.0]]
        reloaded = graph_from_dict(data, registry)
        assert reloaded.nodes["beyond"].pos == (600.0, 40.0)


class TestNestedCollapse:
    """A collapsed frame folded away inside another collapsed frame."""

    def _nest(self, env, registry, inner_first):
        graph, stack, scene = env
        rects = [("inner", (40, 40, 200, 150)), ("outer", (0, 0, 500, 400))]
        for fid, rect in (rects if inner_first else reversed(rects)):
            graph.add_frame(Frame(id=fid, rect=rect))
        script_node(graph, registry, "deep", (70.0, 70.0))    # inside inner
        script_node(graph, registry, "mid", (300.0, 300.0))   # outer only
        sink1 = script_node(graph, registry, "sink1", (900.0, 100.0))
        sink2 = script_node(graph, registry, "sink2", (900.0, 400.0))
        graph.connect("deep", "out1", sink1.id, "in1")
        graph.connect("mid", "out1", sink2.id, "in1")
        return graph, stack, scene

    @pytest.mark.parametrize("inner_first", [True, False])
    def test_pins_land_on_the_box_you_can_see(self, env, registry, inner_first):
        """The owner is the outermost collapsed frame, not whichever one the
        dictionary happened to reach first — that made the same nesting draw
        correctly or not depending on which frame was created first."""
        graph, stack, scene = self._nest(env, registry, inner_first)
        collapse(scene, "inner")
        collapse(scene, "outer")
        assert not scene.frame_items["inner"].isVisible()
        owners = {p.frame_item.frame.id for p in scene._frame_pins.values()}
        assert owners == {"outer"}
        for pin in scene._frame_pins.values():
            assert pin.frame_item.isVisible(), "a pin on a box nobody can see"

    @pytest.mark.parametrize("inner_first", [True, False])
    def test_crossing_wires_stay_drawn(self, env, registry, inner_first):
        graph, stack, scene = self._nest(env, registry, inner_first)
        collapse(scene, "inner")
        collapse(scene, "outer")
        for item in scene.connection_items.values():
            assert item.isVisible()
            for anchor in (item.src_anchor, item.dst_anchor):
                owner = getattr(anchor, "frame_item", None)
                assert owner is None or owner.isVisible()

    def test_expanding_the_outer_gives_the_inner_back_folded(self, env, registry):
        """The inner frame was collapsed before it was buried, and comes back
        that way — its own state is its own."""
        graph, stack, scene = self._nest(env, registry, True)
        collapse(scene, "inner")
        collapse(scene, "outer")
        expand(scene, "outer")
        assert scene.frame_items["inner"].isVisible()
        assert graph.frames["inner"].collapsed is True
        assert not scene.node_items["deep"].isVisible()   # still inside it
        owners = {p.frame_item.frame.id for p in scene._frame_pins.values()}
        assert owners == {"inner"}

    def test_undo_restores_the_nesting(self, env, registry):
        graph, stack, scene = self._nest(env, registry, True)
        collapse(scene, "inner")
        collapse(scene, "outer")
        stack.undo()
        assert graph.frames["outer"].collapsed is False
        assert graph.frames["inner"].collapsed is True
        assert scene.frame_items["inner"].isVisible()


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
            collapse(scene, "f1")
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
        collapse(scene, "f1")
        item.refresh_status()
        assert item._pulse_anim is not None      # collapsed and indeterminate
        stack.undo()
        assert item._pulse_anim is None          # and stopped again on expand


class TestNestedExpand:
    """A frame reopening inside another. The parent is the room, not an
    obstacle: it holds its ground and stretches, rather than being shoved
    aside while the child it contains stays put — which tore the frame in
    half and 'scattered the contents'."""

    def _nested(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="outer", title="Outer", rect=(0, 0, 620, 340)))
        add_node(graph, registry, "o1", pos=(40.0, 60.0))
        add_node(graph, registry, "o2", pos=(460.0, 160.0))
        graph.add_frame(Frame(id="inner", title="Inner",
                              rect=(160, 120, 260, 180)))
        add_node(graph, registry, "i1", pos=(190.0, 170.0))
        add_node(graph, registry, "i2", pos=(310.0, 170.0))
        collapse(scene, "inner")
        return graph, stack, scene

    def test_the_enclosing_frame_is_not_pushed_aside(self, env, registry):
        graph, stack, scene = self._nested(env, registry)
        before = graph.frames["outer"].rect[:2]
        expand(scene, "inner")
        assert graph.frames["outer"].rect[:2] == before

    def test_the_enclosing_frame_stays_put_and_the_inner_one_too(self, env,
                                                                registry):
        graph, stack, scene = self._nested(env, registry)
        expand(scene, "inner")
        assert graph.frames["inner"].rect[:2] == (160.0, 120.0)
        assert graph.nodes["i1"].pos == (190.0, 170.0)
        assert graph.nodes["i2"].pos == (310.0, 170.0)

    def test_siblings_clear_of_the_region_are_not_disturbed(self, env,
                                                           registry):
        graph, stack, scene = self._nested(env, registry)
        expand(scene, "inner")
        assert graph.nodes["o1"].pos == (40.0, 60.0)     # left of the line
        assert graph.nodes["o2"].pos == (460.0, 160.0)   # beyond the region

    def test_a_sibling_in_the_way_is_left_exactly_where_it_is(
            self, env, registry):
        """It used to be shoved right to clear the returning region. A
        frame reopens over its neighbours now (0.1.15) — see
        `TestReopeningMovesNothingElse` for why."""
        graph, stack, scene = self._nested(env, registry)
        # parked in the space the fold vacated, inside the shared parent
        add_node(graph, registry, "squatter", pos=(300.0, 230.0))
        expand(scene, "inner")
        assert graph.nodes["squatter"].pos == (300.0, 230.0)
        assert graph.nodes["o1"].pos == (40.0, 60.0)

    def test_the_parent_grows_to_keep_hold_of_what_it_had(self, env, registry):
        """A node inside the parent, pushed right by the expand, must not be
        left standing outside its own frame."""
        graph, stack, scene = self._nested(env, registry)
        expand(scene, "inner")
        outer = scene.frame_items["outer"].scene_rect()
        for name in ("o1", "o2", "i1", "i2"):
            assert outer.contains(
                scene.node_items[name].sceneBoundingRect().center()), name
        assert outer.contains(scene.frame_items["inner"].scene_rect())

    def test_folding_the_inner_one_again_puts_the_parent_back(self, env,
                                                             registry):
        graph, stack, scene = self._nested(env, registry)
        before = {"outer": graph.frames["outer"].rect,
                  "o1": graph.nodes["o1"].pos, "o2": graph.nodes["o2"].pos}
        expand(scene, "inner")
        collapse(scene, "inner")
        assert graph.frames["outer"].rect == before["outer"]
        assert graph.nodes["o1"].pos == before["o1"]
        assert graph.nodes["o2"].pos == before["o2"]

    def test_one_undo_puts_the_whole_expand_back(self, env, registry):
        graph, stack, scene = self._nested(env, registry)
        before = {"outer": graph.frames["outer"].rect,
                  "o2": graph.nodes["o2"].pos}
        expand(scene, "inner")
        stack.undo()
        assert graph.frames["inner"].collapsed is True
        assert graph.frames["outer"].rect == before["outer"]
        assert graph.nodes["o2"].pos == before["o2"]

    def test_a_frame_merely_parked_on_top_is_not_treated_as_a_parent(
            self, env, registry):
        """Enclosure is containment, not overlap — a folded box dropped on a
        frame it is not inside gets pushed like anything else."""
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        add_node(graph, registry, "inside", pos=(50.0, 50.0))
        collapse(scene, "f1")
        # a big frame overlapping the box but not containing it
        graph.add_frame(Frame(id="over", rect=(30, 30, 400, 300)))
        assert "over" not in scene.enclosing_frames("f1")


class TestWiresFollowAMovingBox:
    """Pinned wires repath from itemChange, so every kind of move is
    covered — not just the drag that happens to call into the scene."""

    def test_setpos_alone_repaths_the_wire(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        src = script_node(graph, registry, "src", (40.0, 40.0))
        dst = script_node(graph, registry, "dst", (600.0, 40.0))
        conn, _ = graph.connect(src.id, "out1", dst.id, "in1")
        collapse(scene, "f1")
        item = scene.frame_items["f1"]
        before = scene.connection_items[conn.id].path().boundingRect()
        item.setPos(item.pos().x() + 250, item.pos().y() + 90)
        after = scene.connection_items[conn.id].path().boundingRect()
        assert after != before, "the wire stayed where the box used to be"

    def test_a_nested_box_carried_along_repaths_too(self, env, registry):
        """The lines lagging until mouse-up: a collapsed frame riding inside
        another is moved by setPos, which the mouse handler never noticed."""
        graph, stack, scene = env
        graph.add_frame(Frame(id="outer", rect=(0, 0, 400, 300)))
        graph.add_frame(Frame(id="inner", rect=(60, 60, 200, 150)))
        src = script_node(graph, registry, "src", (90.0, 100.0))
        dst = script_node(graph, registry, "dst", (700.0, 100.0))
        conn, _ = graph.connect(src.id, "out1", dst.id, "in1")
        collapse(scene, "inner")
        inner = scene.frame_items["inner"]
        before = scene.connection_items[conn.id].path().boundingRect()
        inner.setPos(inner.pos().x() + 120, inner.pos().y())
        after = scene.connection_items[conn.id].path().boundingRect()
        assert after != before


class TestFrameTheSelection:
    """Ctrl+G. A collapsed frame is a box in the flow like any other, so it
    counts towards what gets framed — reading only the nodes meant a
    selection of nothing but frames looked empty, and the new frame landed
    in the middle of the viewport instead of around them."""

    @pytest.fixture
    def window(self, qtbot, registry):
        from flograph.ui.mainwindow import MainWindow
        win = MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def _two_collapsed(self, window, registry):
        graph, scene = window.graph, window.scene
        for i, x in enumerate((500.0, 800.0)):
            graph.add_frame(Frame(id=f"f{i}", rect=(x, 400, 200, 160)))
            node = registry.instantiate("flograph.util.constant",
                                        pos=(x + 20, 440.0))
            node.id = f"n{i}"
            graph.add_node(node)
            collapse(scene, f"f{i}")
        return graph, scene

    def test_it_frames_the_selected_frames(self, window, registry):
        graph, scene = self._two_collapsed(window, registry)
        for fid in ("f0", "f1"):
            scene.frame_items[fid].setSelected(True)
        window._add_frame()
        new_id = next(f for f in graph.frames if f not in ("f0", "f1"))
        new = QRectF(*graph.frames[new_id].rect)
        for fid in ("f0", "f1"):
            assert new.contains(scene.frame_items[fid].sceneBoundingRect()), \
                f"{fid} is outside the frame that was drawn around it"

    def test_it_does_not_land_at_the_viewport_centre(self, window, registry):
        """The actual symptom: 'it adds a frame at a different location'."""
        graph, scene = self._two_collapsed(window, registry)
        for fid in ("f0", "f1"):
            scene.frame_items[fid].setSelected(True)
        window._add_frame()
        new_id = next(f for f in graph.frames if f not in ("f0", "f1"))
        assert graph.frames[new_id].rect[2:] != (400.0, 260.0), \
            "fell through to the nothing-selected default"

    def test_nodes_and_frames_together_are_all_enclosed(self, window, registry):
        graph, scene = self._two_collapsed(window, registry)
        loose = registry.instantiate("flograph.util.constant", pos=(200.0, 90.0))
        loose.id = "loose"
        graph.add_node(loose)
        scene.frame_items["f0"].setSelected(True)
        scene.node_items["loose"].setSelected(True)
        window._add_frame()
        new_id = next(f for f in graph.frames if f not in ("f0", "f1"))
        new = QRectF(*graph.frames[new_id].rect)
        assert new.contains(scene.frame_items["f0"].sceneBoundingRect())
        assert new.contains(scene.node_items["loose"].sceneBoundingRect())

    def test_an_empty_selection_still_uses_the_viewport(self, window, registry):
        graph, scene = self._two_collapsed(window, registry)
        scene.clearSelection()
        window._add_frame()
        new_id = next(f for f in graph.frames if f not in ("f0", "f1"))
        assert graph.frames[new_id].rect[2:] == (400.0, 260.0)


class TestAlignTreatsAFrameLikeANode:
    """Same principle as Ctrl+G: a collapsed frame is a box in the flow, so
    it lines up with the nodes rather than being skipped."""

    @pytest.fixture
    def window(self, qtbot, registry):
        from flograph.ui.mainwindow import MainWindow
        win = MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def _frame_and_node(self, window, registry):
        graph, scene = window.graph, window.scene
        graph.add_frame(Frame(id="f1", rect=(500.0, 400.0, 200.0, 160.0)))
        inside = registry.instantiate("flograph.util.constant",
                                      pos=(520.0, 440.0))
        inside.id = "inside"
        graph.add_node(inside)
        collapse(scene, "f1")
        loose = registry.instantiate("flograph.util.constant",
                                     pos=(200.0, 700.0))
        loose.id = "loose"
        graph.add_node(loose)
        return graph, scene

    def test_a_collapsed_frame_aligns_with_the_nodes(self, window, registry):
        graph, scene = self._frame_and_node(window, registry)
        scene.frame_items["f1"].setSelected(True)
        scene.node_items["loose"].setSelected(True)
        window._align("left")
        assert graph.frames["f1"].rect[0] == 200.0
        assert graph.nodes["loose"].pos[0] == 200.0

    def test_its_hidden_contents_come_with_it(self, window, registry):
        graph, scene = self._frame_and_node(window, registry)
        before = graph.nodes["inside"].pos
        scene.frame_items["f1"].setSelected(True)
        scene.node_items["loose"].setSelected(True)
        window._align("left")
        moved = graph.frames["f1"].rect[0] - 500.0
        assert graph.nodes["inside"].pos == (before[0] + moved, before[1])

    def test_one_undo_puts_the_whole_alignment_back(self, window, registry):
        graph, scene = self._frame_and_node(window, registry)
        before = (graph.frames["f1"].rect, graph.nodes["inside"].pos,
                  graph.nodes["loose"].pos)
        scene.frame_items["f1"].setSelected(True)
        scene.node_items["loose"].setSelected(True)
        window._align("left")
        window.undo_stack.undo()
        assert (graph.frames["f1"].rect, graph.nodes["inside"].pos,
                graph.nodes["loose"].pos) == before

    def test_aligning_nodes_alone_still_works(self, window, registry):
        graph, scene = window.graph, window.scene
        for i, pos in enumerate(((100.0, 100.0), (260.0, 300.0))):
            node = registry.instantiate("flograph.util.constant", pos=pos)
            node.id = f"n{i}"
            graph.add_node(node)
            scene.node_items[f"n{i}"].setSelected(True)
        window._align("left")
        assert graph.nodes["n0"].pos[0] == graph.nodes["n1"].pos[0] == 100.0


class TestAParentThatMustStretch:
    """A frame reopening bigger than the room it is in. The parent is not in
    the way — it is the way — so it stretches rather than being shoved."""

    def _too_big_for_its_parent(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="outer", rect=(0, 0, 600, 400)))
        graph.add_frame(Frame(id="inner", rect=(100, 100, 400, 260)))
        add_node(graph, registry, "i1", pos=(140.0, 150.0))
        collapse(scene, "inner")
        # the parent is shrunk while the child is folded away, so reopening
        # it no longer fits
        graph.update_frame("outer", rect=(0.0, 0.0, 300.0, 220.0))
        return graph, stack, scene

    def test_the_parent_grows_to_hold_it(self, env, registry):
        graph, stack, scene = self._too_big_for_its_parent(env, registry)
        expand(scene, "inner")
        outer = scene.frame_items["outer"].scene_rect()
        assert outer.contains(scene.frame_items["inner"].scene_rect())

    def test_it_grows_from_the_same_corner(self, env, registry):
        """Outwards only — a parent that moved to fit its child would drag
        everything else it holds along with it."""
        graph, stack, scene = self._too_big_for_its_parent(env, registry)
        expand(scene, "inner")
        assert graph.frames["outer"].rect[:2] == (0.0, 0.0)
        assert graph.frames["outer"].rect[2] > 300.0

    def test_folding_again_leaves_it_stretched(self, env, registry):
        """The stretch is not taken back. Reversing it needed a record of
        what the expand did and a rule for applying that record to whatever
        the frame had become since — the machinery that slid things nobody
        had touched, and which went in 0.1.15. A size you can see and drag
        staying as it is beats one that changes behind you; Ctrl+Z still
        takes the whole expand back (`test_one_undo_puts_the_parent_back`).
        """
        graph, stack, scene = self._too_big_for_its_parent(env, registry)
        before = graph.frames["outer"].rect
        expand(scene, "inner")
        grown = graph.frames["outer"].rect
        assert grown[2] > before[2] or grown[3] > before[3]
        collapse(scene, "inner")
        assert graph.frames["outer"].rect == grown

    def test_one_undo_puts_the_parent_back(self, env, registry):
        graph, stack, scene = self._too_big_for_its_parent(env, registry)
        before = graph.frames["outer"].rect
        expand(scene, "inner")
        stack.undo()
        assert graph.frames["outer"].rect == before
        assert graph.frames["inner"].collapsed is True

    def test_a_parent_the_user_has_resized_since_is_not_touched(
            self, env, registry):
        """Nothing goes looking for the stretch to undo, so a size chosen
        afterwards is simply the size."""
        graph, stack, scene = self._too_big_for_its_parent(env, registry)
        expand(scene, "inner")
        graph.update_frame("outer", rect=(0.0, 0.0, 900.0, 700.0))
        collapse(scene, "inner")
        assert graph.frames["outer"].rect == (0.0, 0.0, 900.0, 700.0)

    def test_undoing_a_stretch_cannot_turn_a_frame_inside_out(self, env,
                                                              registry):
        graph, stack, scene = self._too_big_for_its_parent(env, registry)
        expand(scene, "inner")
        graph.update_frame("outer", rect=(0.0, 0.0, 130.0, 70.0))
        collapse(scene, "inner")
        assert graph.frames["outer"].rect[2] >= 120.0
        assert graph.frames["outer"].rect[3] >= 60.0


def wires_anchored_to_hidden(scene):
    """Visible wires whose ends are drawn from something not on the canvas.

    The scatter: a line running off to a box that isn't there. Worth asserting
    as an invariant rather than case by case — any way of reaching this state
    is a bug, whatever produced it.
    """
    def owner_visible(anchor):
        # asked of the item that owns the pin, not of the pin: zooming out
        # flattens cards and hides their ports by design (see _apply_lod),
        # which is not the same thing as a wire trailing off to nothing
        holder = getattr(anchor, "frame_item", None)
        if holder is not None:
            return holder.isVisible()
        item = scene.node_items.get(getattr(anchor, "node_id", None))
        return item is None or item.isVisible()

    bad = []
    for ci in scene.connection_items.values():
        if not ci.isVisible():
            continue
        for side, anchor in (("src", ci.src_anchor), ("dst", ci.dst_anchor)):
            if anchor is not None and not owner_visible(anchor):
                bad.append(f"{ci.conn.src_node}->{ci.conn.dst_node} ({side})")
    return bad


class TestAFrameCarriesWhatItsNestedFramesHold:
    """The two membership rules disagree at the edges — a node counts by its
    centre, a frame by its whole rect — so a nested frame can be carried
    while a node it holds hangs out past the edge and is not."""

    def _overhanging(self, env, registry):
        """A frame folded down to its box, then a frame drawn around that box.

        The outer frame contains the 60px square, so it carries the inner
        frame — but the inner frame's members are still spread out at their
        expanded positions, and one of them is well outside the outer frame.
        That is the only way the two rules can disagree, and it is exactly
        what happens when you fold a row of frames and then draw a frame
        around them.
        """
        graph, stack, scene = env
        graph.add_frame(Frame(id="inner", rect=(300, 100, 240, 140)))
        script_node(graph, registry, "held", (320.0, 140.0))
        script_node(graph, registry, "overhang", (440.0, 140.0))
        graph.connect("held", "out1", "overhang", "in1")
        script_node(graph, registry, "outside", (900.0, 140.0))
        graph.connect("overhang", "out1", "outside", "in1")
        collapse(scene, "inner")
        assert "overhang" in graph.frames["inner"].members
        graph.add_frame(Frame(id="outer", rect=(260, 60, 160, 160)))
        assert "inner" in scene._frame_member_frames(scene.frame_items["outer"])
        return graph, stack, scene

    def test_the_overhanging_node_is_still_a_member(self, env, registry):
        graph, stack, scene = self._overhanging(env, registry)
        collapse(scene, "outer")
        assert "overhang" in graph.frames["outer"].members
        assert "held" in graph.frames["outer"].members

    def test_it_is_hidden_with_the_rest(self, env, registry):
        graph, stack, scene = self._overhanging(env, registry)
        collapse(scene, "outer")
        assert not scene.node_items["overhang"].isVisible()

    def test_dragging_the_box_takes_it_along(self, env, registry):
        """It used to be left behind, so the flow came back scattered
        relative to its own frame."""
        graph, stack, scene = self._overhanging(env, registry)
        collapse(scene, "outer")
        item = scene.frame_items["outer"]
        carried = {n.node.id for n, _off in item.carried_items()[0]}
        assert {"held", "overhang"} <= carried

    def test_no_wire_is_left_pointing_at_a_hidden_box(self, env, registry):
        """The scatter: overhang's wire out was pinned to 'inner', which is
        itself folded away inside 'outer' — a visible line drawn to a box
        that is not on the canvas."""
        graph, stack, scene = self._overhanging(env, registry)
        collapse(scene, "outer")
        assert wires_anchored_to_hidden(scene) == []

    def test_the_owner_of_a_buried_frames_node_is_the_visible_box(
            self, env, registry):
        graph, stack, scene = self._overhanging(env, registry)
        collapse(scene, "outer")
        owner = scene._owner_of("overhang")
        assert owner is not None
        assert scene.frame_items[owner].isVisible()
        assert owner == "outer"


class TestNoScatterWhenFoldingOverFoldedChildren:
    """End to end, the reported sequence: a row of collapsed frames, a frame
    drawn round them, then that frame folded too."""

    def _row_in_a_frame(self, env, registry):
        graph, stack, scene = env
        for i, x in enumerate((100.0, 460.0, 820.0)):
            graph.add_frame(Frame(id=f"f{i}", rect=(x, 200, 280, 180)))
            for j in range(2):
                script_node(graph, registry, f"n{i}{j}",
                            (x + 25 + j * 130, 250.0))
            graph.connect(f"n{i}0", "out1", f"n{i}1", "in1")
        script_node(graph, registry, "down", (1400.0, 250.0))
        graph.connect("n00", "out1", "n10", "in1")
        graph.connect("n10", "out1", "n20", "in1")
        graph.connect("n21", "out1", "down", "in1")
        for i in range(3):
            collapse(scene, f"f{i}")
        graph.add_frame(Frame(id="outer", rect=(40, 134, 900, 260)))
        return graph, stack, scene

    def test_folding_the_surrounding_frame_leaves_no_stray_wires(self, env,
                                                                registry):
        graph, stack, scene = self._row_in_a_frame(env, registry)
        collapse(scene, "outer")
        assert wires_anchored_to_hidden(scene) == []

    def test_every_nested_frame_is_hidden_with_it(self, env, registry):
        graph, stack, scene = self._row_in_a_frame(env, registry)
        collapse(scene, "outer")
        for i in range(3):
            assert not scene.frame_items[f"f{i}"].isVisible()

    def test_every_node_in_every_nested_frame_is_hidden(self, env, registry):
        graph, stack, scene = self._row_in_a_frame(env, registry)
        collapse(scene, "outer")
        for i in range(3):
            for j in range(2):
                assert not scene.node_items[f"n{i}{j}"].isVisible(), f"n{i}{j}"

    def test_expanding_an_inner_frame_leaves_the_others_where_they_were(
            self, env, registry):
        graph, stack, scene = self._row_in_a_frame(env, registry)
        before = {f"f{i}": graph.frames[f"f{i}"].rect for i in (1, 2)}
        expand(scene, "f0")
        assert {f"f{i}": graph.frames[f"f{i}"].rect for i in (1, 2)} == before

    def test_and_puts_its_own_nodes_back_where_they_were(self, env, registry):
        graph, stack, scene = self._row_in_a_frame(env, registry)
        before = {n: graph.nodes[n].pos for n in ("n00", "n01")}
        expand(scene, "f0")
        assert {n: graph.nodes[n].pos for n in before} == before

    def test_the_whole_round_trip_is_clean(self, env, registry):
        graph, stack, scene = self._row_in_a_frame(env, registry)
        before = {n: graph.nodes[n].pos for n in graph.nodes}
        collapse(scene, "outer")
        assert wires_anchored_to_hidden(scene) == []
        expand(scene, "outer")
        assert wires_anchored_to_hidden(scene) == []
        assert {n: graph.nodes[n].pos for n in graph.nodes} == before


class TestANewFrameStacksByContainment:
    """A frame drawn around others has to sit behind them, or it covers them
    and — since a frame takes the click anywhere in its body — they cannot be
    selected at all without sending the new one to the back by hand."""

    @pytest.fixture
    def window(self, qtbot, registry):
        from flograph.ui.mainwindow import MainWindow
        win = MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def _two_frames(self, window):
        graph = window.graph
        for i, x in enumerate((300.0, 700.0)):
            graph.add_frame(Frame(id=f"f{i}", rect=(x, 300, 200, 160)))
        return graph, window.scene

    def test_a_frame_drawn_around_others_goes_behind_them(self, window):
        graph, scene = self._two_frames(window)
        for fid in ("f0", "f1"):
            scene.frame_items[fid].setSelected(True)
        window._add_frame()
        new_id = next(f for f in graph.frames if f not in ("f0", "f1"))
        order = graph.stacking_order("frame")     # back to front
        assert order.index(new_id) < order.index("f0")
        assert order.index(new_id) < order.index("f1")

    def test_and_therefore_draws_below_them(self, window):
        graph, scene = self._two_frames(window)
        for fid in ("f0", "f1"):
            scene.frame_items[fid].setSelected(True)
        window._add_frame()
        new_id = next(f for f in graph.frames if f not in ("f0", "f1"))
        assert (scene.frame_items[new_id].zValue()
                < scene.frame_items["f0"].zValue())

    def test_the_enclosed_frames_are_still_the_ones_you_click(self, window):
        graph, scene = self._two_frames(window)
        for fid in ("f0", "f1"):
            scene.frame_items[fid].setSelected(True)
        window._add_frame()
        # topmost item at a point inside f0 must still be f0
        from flograph.ui.canvas.frame_item import FrameItem
        centre = scene.frame_items["f0"].scene_rect().center()
        hit = [i for i in scene.items(centre) if isinstance(i, FrameItem)]
        assert hit and hit[0] is scene.frame_items["f0"]

    def test_a_frame_drawn_inside_another_stays_in_front_of_it(self, window):
        """The mirror case, and why 'frames go to the back on arrival' is the
        wrong rule — it would make this one the unreachable frame instead."""
        graph, scene = self._two_frames(window)
        graph.add_frame(Frame(id="big", rect=(100.0, 100.0, 900.0, 600.0)))
        window._add_frame_at(QPointF(400.0, 350.0))
        new_id = next(f for f in graph.frames
                      if f not in ("f0", "f1", "big"))
        order = graph.stacking_order("frame")
        assert order.index(new_id) > order.index("big")

    def test_a_frame_enclosing_nothing_arrives_on_top_as_before(self, window):
        graph, scene = self._two_frames(window)
        window._add_frame_at(QPointF(2000.0, 2000.0))
        new_id = next(f for f in graph.frames if f not in ("f0", "f1"))
        order = graph.stacking_order("frame")
        assert order[-1] == new_id

    def test_it_is_one_undo_step(self, window):
        graph, scene = self._two_frames(window)
        for fid in ("f0", "f1"):
            scene.frame_items[fid].setSelected(True)
        window._add_frame()
        assert len(graph.frames) == 3
        window.undo_stack.undo()
        assert set(graph.frames) == {"f0", "f1"}

    def test_undo_restores_the_previous_order(self, window):
        graph, scene = self._two_frames(window)
        before = graph.stacking_order("frame")
        for fid in ("f0", "f1"):
            scene.frame_items[fid].setSelected(True)
        window._add_frame()
        window.undo_stack.undo()
        assert graph.stacking_order("frame") == before


class TestCopyingAFrameTakesItsFrames:
    """Copying a frame copies what is inside it — including any frame inside
    it, folded or not, and whatever those hold. It used to copy only the
    frames you had selected, so the nesting was quietly flattened: you got
    the nodes and the outer frame, and the inner frame was not in the
    clipboard at all."""

    @pytest.fixture
    def window(self, qtbot, registry):
        from flograph.ui.mainwindow import MainWindow
        win = MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def _nested(self, window, registry, fold_inner):
        graph, scene = window.graph, window.scene
        graph.add_frame(Frame(id="outer", title="Outer",
                              rect=(100, 100, 620, 320)))
        graph.add_frame(Frame(id="inner", title="Inner",
                              rect=(160, 170, 280, 180)))
        for nid, pos in (("a", (190.0, 220.0)), ("b", (320.0, 220.0)),
                         ("c", (520.0, 220.0))):
            node = registry.instantiate("flograph.scripting.python_script",
                                        pos=pos)
            node.id = nid
            graph.add_node(node)
        graph.connect("a", "out1", "b", "in1")
        graph.connect("b", "out1", "c", "in1")
        if fold_inner:
            scene.frame_items["inner"].toggle_collapsed()
        scene.clearSelection()
        scene.frame_items["outer"].setSelected(True)
        return graph, scene

    def _paste(self, window, payload):
        before_f, before_n = set(window.graph.frames), set(window.graph.nodes)
        window._insert_payload(payload)
        return ([f for f in window.graph.frames if f not in before_f],
                [n for n in window.graph.nodes if n not in before_n])

    @pytest.mark.parametrize("fold_inner", [False, True])
    def test_the_nested_frame_is_in_the_payload(self, window, registry,
                                                fold_inner):
        self._nested(window, registry, fold_inner)
        payload = window._selection_payload()
        assert {f["title"] for f in payload["frames"]} == {"Outer", "Inner"}

    @pytest.mark.parametrize("fold_inner", [False, True])
    def test_pasting_rebuilds_both_frames(self, window, registry, fold_inner):
        graph, scene = self._nested(window, registry, fold_inner)
        frames, nodes = self._paste(window, window._selection_payload())
        assert len(frames) == 2
        assert len(nodes) == 3

    def test_a_folded_nested_frame_pastes_folded(self, window, registry):
        graph, scene = self._nested(window, registry, True)
        frames, _nodes = self._paste(window, window._selection_payload())
        folded = [graph.frames[f] for f in frames if graph.frames[f].collapsed]
        assert len(folded) == 1 and folded[0].title == "Inner"

    def test_its_membership_points_at_the_copies(self, window, registry):
        """Not at the originals — that would have two frames standing in for
        the same nodes, and hiding one would blank the other."""
        graph, scene = self._nested(window, registry, True)
        frames, nodes = self._paste(window, window._selection_payload())
        folded = next(graph.frames[f] for f in frames
                      if graph.frames[f].collapsed)
        assert len(folded.members) == 2
        assert set(folded.members) <= set(nodes)
        assert not set(folded.members) & {"a", "b", "c"}

    def test_the_copy_keeps_the_size_it_opens_back_to(self, window, registry):
        """Without it a pasted folded frame only knows its 60px box and can
        never open back to anything."""
        graph, scene = self._nested(window, registry, True)
        frames, _nodes = self._paste(window, window._selection_payload())
        folded = next(graph.frames[f] for f in frames
                      if graph.frames[f].collapsed)
        assert folded.expanded_size == (280.0, 180.0)

    def test_the_copies_contents_are_hidden_like_the_original(self, window,
                                                              registry):
        graph, scene = self._nested(window, registry, True)
        frames, nodes = self._paste(window, window._selection_payload())
        folded = next(graph.frames[f] for f in frames
                      if graph.frames[f].collapsed)
        for nid in folded.members:
            assert not scene.node_items[nid].isVisible()

    def test_expanding_the_copy_gives_its_nodes_back(self, window, registry):
        graph, scene = self._nested(window, registry, True)
        frames, _nodes = self._paste(window, window._selection_payload())
        copy_id = next(f for f in frames if graph.frames[f].collapsed)
        members = list(graph.frames[copy_id].members)
        offsets = {nid: (graph.nodes[nid].pos[0]
                         - graph.frames[copy_id].rect[0],
                         graph.nodes[nid].pos[1]
                         - graph.frames[copy_id].rect[1])
                   for nid in members}
        scene.frame_items[copy_id].toggle_collapsed()
        assert graph.frames[copy_id].collapsed is False
        for nid in members:
            assert scene.node_items[nid].isVisible()
            now = (graph.nodes[nid].pos[0] - graph.frames[copy_id].rect[0],
                   graph.nodes[nid].pos[1] - graph.frames[copy_id].rect[1])
            assert now == offsets[nid]

    def test_the_original_is_untouched_by_the_paste(self, window, registry):
        graph, scene = self._nested(window, registry, True)
        before = tuple(graph.frames["inner"].members)
        self._paste(window, window._selection_payload())
        assert tuple(graph.frames["inner"].members) == before
        assert graph.frames["inner"].collapsed is True

    def test_wires_inside_the_nested_frame_come_too(self, window, registry):
        graph, scene = self._nested(window, registry, True)
        before = len(graph.connections)
        self._paste(window, window._selection_payload())
        assert len(graph.connections) == before + 2

    def test_three_deep_nesting_survives(self, window, registry):
        graph, scene = window.graph, window.scene
        graph.add_frame(Frame(id="l1", title="L1", rect=(0, 0, 700, 400)))
        graph.add_frame(Frame(id="l2", title="L2", rect=(60, 60, 540, 280)))
        graph.add_frame(Frame(id="l3", title="L3", rect=(120, 120, 380, 160)))
        node = registry.instantiate("flograph.scripting.python_script",
                                    pos=(160.0, 170.0))
        node.id = "deep"
        graph.add_node(node)
        scene.frame_items["l3"].toggle_collapsed()
        scene.clearSelection()
        scene.frame_items["l1"].setSelected(True)
        frames, nodes = self._paste(window, window._selection_payload())
        assert len(frames) == 3 and len(nodes) == 1
        folded = next(graph.frames[f] for f in frames
                      if graph.frames[f].collapsed)
        assert list(folded.members) == nodes

    def test_a_frame_naming_a_nested_frame_repoints_at_the_copy(self, window,
                                                               registry):
        graph, scene = window.graph, window.scene
        graph.add_frame(Frame(id="outer", title="Outer", rect=(0, 0, 600, 360)))
        graph.add_frame(Frame(id="inner", title="Inner", rect=(60, 60, 300, 200)))
        node = registry.instantiate("flograph.scripting.python_script",
                                    pos=(100.0, 110.0))
        node.id = "n1"
        graph.add_node(node)
        scene.frame_items["inner"].toggle_collapsed()
        scene.frame_items["outer"].toggle_collapsed()   # holds a folded frame
        scene.clearSelection()
        scene.frame_items["outer"].setSelected(True)
        frames, _nodes = self._paste(window, window._selection_payload())
        copy_outer = next(graph.frames[f] for f in frames
                          if graph.frames[f].title == "Outer")
        assert len(copy_outer.member_frames) == 1
        assert copy_outer.member_frames[0] in frames
        assert copy_outer.member_frames[0] != "inner"

    def test_an_old_clipboard_fragment_without_frame_ids_still_pastes(
            self, window, registry):
        graph, scene = window.graph, window.scene
        payload = {
            "flograph/clipboard": 1, "nodes": [], "connections": [],
            "frames": [{"title": "Legacy", "rect": [0, 0, 300, 200],
                        "color": "#33415c", "collapsed": False}],
        }
        frames, _nodes = self._paste(window, payload)
        assert len(frames) == 1
        assert graph.frames[frames[0]].title == "Legacy"


class TestComponentsCanNestToo:
    """Saving a frame to the library goes through the same payload, so a
    component can now hold frames of its own — which the update path has to
    account for or it leaves the old nesting standing beside the new copy."""

    @pytest.fixture
    def window(self, qtbot, registry, tmp_path, monkeypatch):
        from flograph.ui.mainwindow import MainWindow
        (tmp_path / "frames").mkdir()
        monkeypatch.setattr("flograph.paths.user_frames_dir",
                            lambda: tmp_path / "frames")
        win = MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def _nested_instance(self, window, registry):
        graph, scene = window.graph, window.scene
        graph.add_frame(Frame(id="outer", title="Outer",
                              rect=(100, 100, 600, 340)))
        graph.add_frame(Frame(id="inner", title="Inner",
                              rect=(160, 170, 300, 200)))
        for nid, pos in (("a", (200.0, 220.0)), ("b", (330.0, 220.0))):
            node = registry.instantiate("flograph.scripting.python_script",
                                        pos=pos)
            node.id = nid
            graph.add_node(node)
        graph.connect("a", "out1", "b", "in1")
        scene.frame_items["inner"].toggle_collapsed()
        scene.clearSelection()
        scene.frame_items["outer"].setSelected(True)
        return graph, scene

    def test_only_the_selected_frame_is_the_root(self, window, registry):
        self._nested_instance(window, registry)
        payload = window._selection_payload()
        roots = [f["title"] for f in payload["frames"] if f["root"]]
        assert roots == ["Outer"]

    def test_the_nested_frame_is_not_a_root(self, window, registry):
        self._nested_instance(window, registry)
        payload = window._selection_payload()
        inner = next(f for f in payload["frames"] if f["title"] == "Inner")
        assert inner["root"] is False
        assert inner["collapsed"] is True

    def test_updating_an_instance_replaces_the_nesting_rather_than_doubling_it(
            self, window, registry, monkeypatch):
        from flograph.core import user_frames
        graph, scene = self._nested_instance(window, registry)
        payload = window._selection_payload()
        from flograph.paths import user_frames_dir
        component_id = user_frames.write_user_frame(
            user_frames_dir(), None, "Nested", payload)
        from flograph.ui.commands import SetFrameSourceCommand
        window.undo_stack.push(SetFrameSourceCommand(
            graph, "outer", component_id, user_frames.content_hash(payload)))
        before_frames = len(graph.frames)
        before_nodes = len(graph.nodes)
        window._update_component_instance("outer")
        assert len(graph.frames) == before_frames
        assert len(graph.nodes) == before_nodes

    def test_the_rebuilt_instance_still_holds_a_folded_frame(self, window,
                                                            registry):
        from flograph.core import user_frames
        from flograph.paths import user_frames_dir
        graph, scene = self._nested_instance(window, registry)
        payload = window._selection_payload()
        component_id = user_frames.write_user_frame(
            user_frames_dir(), None, "Nested2", payload)
        from flograph.ui.commands import SetFrameSourceCommand
        window.undo_stack.push(SetFrameSourceCommand(
            graph, "outer", component_id, user_frames.content_hash(payload)))
        window._update_component_instance("outer")
        folded = [f for f in graph.frames.values() if f.collapsed]
        assert len(folded) == 1 and folded[0].title == "Inner"


class TestANodeBelongsToOneFrame:
    """The rule that keeps nesting coherent: a node a folded frame wrote down
    is *that* frame's, and anything else reaches it only by containing that
    frame.

    Geometric membership has to be blind to visibility, so a folded frame's
    own contents travel with it. Blind also meant a second frame drawn near
    where those hidden nodes were left standing claimed them as well — two
    frames recording the same node, whichever you opened showing it while the
    other still believed it held it, and dictionary order deciding which one
    owned it. Found by fuzzing sequences of collapse/expand/copy/group.
    """

    def _folded_over_another_frames_region(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="keeper", rect=(100, 100, 300, 200)))
        script_node(graph, registry, "held1", (140.0, 150.0))
        script_node(graph, registry, "held2", (260.0, 150.0))
        collapse(scene, "keeper")
        # a second frame drawn over the region the folded one vacated — its
        # hidden members are still recorded at positions inside this rect
        graph.add_frame(Frame(id="latecomer", rect=(80, 80, 400, 300)))
        return graph, stack, scene

    def test_the_latecomer_does_not_claim_them_directly(self, env, registry):
        """Geometrically it covers where they are recorded, so the old rule
        adopted them outright. They belong to the frame that wrote them
        down; this one may only reach them by carrying that frame."""
        graph, stack, scene = self._folded_over_another_frames_region(
            env, registry)
        direct = scene._frame_members(scene.frame_items["latecomer"])
        assert "held1" not in direct and "held2" not in direct

    def test_it_claims_them_through_the_frame_that_holds_them(self, env,
                                                              registry):
        """It contains the folded frame, so it carries it — and the nodes
        come with the frame, not separately."""
        graph, stack, scene = self._folded_over_another_frames_region(
            env, registry)
        collapse(scene, "latecomer")
        assert "keeper" in graph.frames["latecomer"].member_frames
        # transitive membership still reaches them
        assert {"held1", "held2"} <= set(graph.frames["latecomer"].members)

    def test_a_frame_that_does_not_contain_the_holder_gets_nothing(
            self, env, registry):
        graph, stack, scene = self._folded_over_another_frames_region(
            env, registry)
        # sits over where the hidden nodes are recorded, but not over the box
        graph.update_frame("latecomer", rect=(120.0, 120.0, 320.0, 220.0))
        collapse(scene, "latecomer")
        assert graph.frames["latecomer"].members == ()
        assert graph.frames["latecomer"].member_frames == ()

    def test_no_two_unrelated_frames_record_the_same_node(self, env, registry):
        graph, stack, scene = self._folded_over_another_frames_region(
            env, registry)
        graph.update_frame("latecomer", rect=(120.0, 120.0, 320.0, 220.0))
        collapse(scene, "latecomer")
        claims: dict = {}
        for fid, frame in graph.frames.items():
            if not frame.collapsed:
                continue
            for nid in frame.members:
                assert nid not in claims, (
                    f"{nid} is claimed by both {claims.get(nid)} and {fid}")
                claims[nid] = fid

    def test_opening_one_does_not_strand_the_other(self, env, registry):
        """The symptom: expand one frame and the node appears, while the
        other still believes it is holding it — so folding that one hides a
        node it does not own."""
        graph, stack, scene = self._folded_over_another_frames_region(
            env, registry)
        graph.update_frame("latecomer", rect=(120.0, 120.0, 320.0, 220.0))
        collapse(scene, "latecomer")
        expand(scene, "keeper")
        for nid in ("held1", "held2"):
            assert scene.node_items[nid].isVisible()

    def test_a_buried_frame_is_not_claimed_by_a_third_frame(self, env,
                                                            registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="inner", rect=(200, 200, 240, 160)))
        script_node(graph, registry, "n1", (240.0, 240.0))
        collapse(scene, "inner")
        graph.add_frame(Frame(id="owner", rect=(160, 160, 200, 200)))
        collapse(scene, "owner")
        assert "inner" in graph.frames["owner"].member_frames
        # a third frame drawn over the same area must reach it only through
        # 'owner' — never adopt it directly, which would have two frames
        # holding the same box
        graph.add_frame(Frame(id="third", rect=(140, 140, 400, 300)))
        direct = scene._frame_member_frames(scene.frame_items["third"])
        assert "inner" not in direct
        assert "owner" in direct

    def test_everything_comes_back_when_it_is_all_opened(self, env, registry):
        """The end-to-end version: whatever the sequence, opening every frame
        must put every node back on the canvas."""
        graph, stack, scene = self._folded_over_another_frames_region(
            env, registry)
        collapse(scene, "latecomer")
        for _ in range(6):
            folded = [f for f, fr in graph.frames.items()
                      if fr.collapsed and scene.frame_items[f].isVisible()]
            if not folded:
                break
            expand(scene, sorted(folded)[0])
        assert all(item.isVisible() for item in scene.node_items.values())


# --------------------------------------------------------------- invariants

def frame_invariants(win):
    """Every way the canvas can be left incoherent by frame operations.

    Written as one checker rather than as separate assertions because the
    interesting failures are *combinations* — collapse, then group, then
    paste, then undo — and any of them can leave the canvas wrong in a way
    the individual operation's own tests would never look for. Returns a list
    of human-readable failures, empty when the canvas is sound.
    """
    graph, scene = win.graph, win.scene
    bad = []

    if set(graph.nodes) != set(scene.node_items):
        bad.append("node_items out of step with graph.nodes")
    if set(graph.frames) != set(scene.frame_items):
        bad.append("frame_items out of step with graph.frames")
    if set(graph.connections) != set(scene.connection_items):
        bad.append("connection_items out of step with graph.connections")

    for fid, frame in graph.frames.items():
        for nid in frame.members:
            if nid not in graph.nodes:
                bad.append(f"frame {fid} names missing node {nid}")
        for other in frame.member_frames:
            if other not in graph.frames:
                bad.append(f"frame {fid} names missing frame {other}")
        if fid in frame.member_frames:
            bad.append(f"frame {fid} contains itself")

    def holds(outer_id, inner_id, seen=None):
        seen = seen if seen is not None else set()
        if outer_id in seen:
            return False
        seen.add(outer_id)
        frame = graph.frames.get(outer_id)
        if frame is None:
            return False
        return (inner_id in frame.member_frames
                or any(holds(s, inner_id, seen) for s in frame.member_frames))

    # two folded frames may both name a node only when one contains the
    # other; that overlap is what transitive membership is
    claims: dict = {}
    for fid, frame in graph.frames.items():
        if not frame.collapsed:
            continue
        for nid in frame.members:
            prev = claims.get(nid)
            if prev is not None and not (holds(prev, fid) or holds(fid, prev)):
                bad.append(f"node {nid} held by unrelated {prev} and {fid}")
            claims[nid] = fid

    # nothing is lost: a hidden node must be accounted for by a folded frame
    # you can actually see
    for nid, item in scene.node_items.items():
        if item.isVisible():
            continue
        owner = scene._owner_of(nid)
        if owner is None:
            bad.append(f"node {nid} is hidden and nothing owns it")
        elif owner not in scene.frame_items:
            bad.append(f"node {nid} owned by missing frame {owner}")
        elif not scene.frame_items[owner].isVisible():
            bad.append(f"node {nid} owned by hidden frame {owner}")

    for fid, frame in graph.frames.items():
        if not scene.frame_items[fid].isVisible():
            continue
        if frame.collapsed:
            for nid in frame.members:
                if nid in scene.node_items and scene.node_items[nid].isVisible():
                    bad.append(f"{fid} is folded but member {nid} is showing")
        elif frame.members or frame.member_frames:
            bad.append(f"expanded frame {fid} still records members")

    # no visible wire is drawn from something that is not on the canvas.
    # Asked of the item that owns the anchor, not of the pin: zooming out
    # flattens cards and hides their ports by design, which is not the same
    # thing as a wire trailing off to a box that is not there.
    def owner_visible(anchor):
        holder = getattr(anchor, "frame_item", None)
        if holder is not None:
            return holder.isVisible()
        item = scene.node_items.get(getattr(anchor, "node_id", None))
        return item is None or item.isVisible()

    for ci in scene.connection_items.values():
        if not ci.isVisible():
            continue
        for side in ("src_anchor", "dst_anchor"):
            anchor = getattr(ci, side)
            if anchor is not None and not owner_visible(anchor):
                bad.append(f"wire {ci.conn.src_node}->{ci.conn.dst_node} "
                           f"{side} is not on the canvas")
    return bad


class TestFrameSequences:
    """Sequences of frame operations, checked against the invariants after
    every step.

    Every frame bug reported so far survived the tests for the operation that
    caused it and only showed up in combination — collapse then group then
    paste then undo. Fixed seeds rather than random ones so a failure is
    reproducible and the suite is deterministic; the same driver was run over
    400 seeds by hand, which is where the last of them was found.
    """

    @pytest.fixture
    def window(self, qtbot, registry):
        from flograph.ui.mainwindow import MainWindow
        win = MainWindow(registry)
        win.confirm_close = False
        # deleting a folded frame asks first; a modal offscreen never returns
        win.scene.confirm_collapsed_delete = lambda *a, **k: True
        qtbot.addWidget(win)
        return win

    def _build(self, win, registry):
        from flograph.core import Graph
        win._replace_graph(Graph())
        win.undo_stack.clear()
        win.scene.confirm_collapsed_delete = lambda *a, **k: True
        graph = win.graph
        graph.add_frame(Frame(id="outer", title="Outer", rect=(80, 80, 700, 380)))
        graph.add_frame(Frame(id="inner", title="Inner", rect=(150, 160, 320, 200)))
        graph.add_frame(Frame(id="side", title="Side", rect=(860, 80, 300, 200)))
        for nid, pos in (("a", (190.0, 210.0)), ("b", (330.0, 210.0)),
                         ("c", (560.0, 210.0)), ("d", (900.0, 130.0)),
                         ("e", (1300.0, 130.0))):
            node = registry.instantiate("flograph.scripting.python_script",
                                        pos=pos)
            node.id = nid
            graph.add_node(node)
        for src, dst in (("a", "b"), ("b", "c"), ("c", "d"), ("d", "e")):
            graph.connect(src, "out1", dst, "in1")

    # --- the operations, each returning a label or None if not applicable

    def _visible_frames(self, win):
        return sorted(f for f in win.graph.frames
                      if win.scene.frame_items[f].isVisible())

    def _toggle(self, win, rng, want_collapsed):
        pool = [f for f in self._visible_frames(win)
                if win.graph.frames[f].collapsed is want_collapsed]
        if not pool:
            return None
        fid = rng.choice(pool)
        win.scene.frame_items[fid].toggle_collapsed()
        return ("expand" if want_collapsed else "collapse") + f"({fid})"

    def _copy_paste(self, win, rng):
        if len(win.graph.frames) > 10 or len(win.graph.nodes) > 30:
            return None
        pool = self._visible_frames(win)
        if not pool:
            return None
        fid = rng.choice(pool)
        win.scene.clearSelection()
        win.scene.frame_items[fid].setSelected(True)
        payload = win._selection_payload()
        if payload is None:
            return None
        win._insert_payload(payload)
        return f"copy_paste({fid})"

    def _group(self, win, rng):
        pool = self._visible_frames(win)
        if len(pool) < 2 or len(win.graph.frames) > 10:
            return None
        picked = rng.sample(pool, 2)
        win.scene.clearSelection()
        for fid in picked:
            win.scene.frame_items[fid].setSelected(True)
        win._add_frame()
        return f"group({picked})"

    def _delete(self, win, rng):
        pool = self._visible_frames(win)
        if not pool:
            return None
        fid = rng.choice(pool)
        win.scene.clearSelection()
        win.scene.frame_items[fid].setSelected(True)
        win.scene.delete_selection()
        return f"delete({fid})"

    def _save_load(self, win, rng):
        from flograph.core.serialization import graph_from_dict, graph_to_dict
        win._replace_graph(graph_from_dict(graph_to_dict(win.graph),
                                           win.registry))
        return "save_load"

    def _undo(self, win, rng):
        if not win.undo_stack.canUndo():
            return None
        win.undo_stack.undo()
        return "undo"

    def _redo(self, win, rng):
        if not win.undo_stack.canRedo():
            return None
        win.undo_stack.redo()
        return "redo"

    def _run(self, win, registry, seed, steps=18):
        import random
        ops = [lambda w, r: self._toggle(w, r, False),
               lambda w, r: self._toggle(w, r, True),
               self._copy_paste, self._group, self._delete,
               self._save_load, self._undo, self._redo]
        rng = random.Random(seed)
        self._build(win, registry)
        history: list = []
        for _ in range(steps):
            label = rng.choice(ops)(win, rng)
            if label is None:
                continue
            history.append(label)
            bad = frame_invariants(win)
            assert not bad, (f"seed {seed} after {' -> '.join(history)}:\n  "
                             + "\n  ".join(sorted(set(bad))))
        return history

    @pytest.mark.parametrize("seed", range(8))
    def test_a_sequence_of_frame_operations_stays_coherent(self, window,
                                                           registry, seed):
        self._run(window, registry, seed)

    @pytest.mark.parametrize("seed", range(4))
    def test_opening_every_frame_puts_every_node_back(self, window, registry,
                                                      seed):
        """The 'losing nodes' check, end to end. However tangled the sequence,
        unfolding everything has to leave every node on the canvas."""
        self._run(window, registry, seed)
        expected = set(window.graph.nodes)
        for _ in range(40):
            folded = [f for f in self._visible_frames(window)
                      if window.graph.frames[f].collapsed]
            if not folded:
                break
            window.scene.frame_items[sorted(folded)[0]].toggle_collapsed()
            assert not frame_invariants(window)
        assert set(window.graph.nodes) == expected
        hidden = sorted(n for n in expected
                        if not window.scene.node_items[n].isVisible())
        assert not hidden, f"still hidden with every frame open: {hidden}"


class TestRunningAFrameReachesItsFrames:
    """"Run frame" targets exactly what dragging the frame would carry — so a
    frame folded inside it runs like the nodes it stands for would."""

    @pytest.fixture
    def window(self, qtbot, registry):
        from flograph.ui.mainwindow import MainWindow
        win = MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def _node(self, window, registry, nid, pos):
        node = registry.instantiate("flograph.scripting.python_script", pos=pos)
        node.id = nid
        return window.graph.add_node(node)

    def _folded_child_reaching_outside(self, window, registry):
        """A folded sub-frame whose members are recorded outside the parent —
        the shape a plain sweep of the rectangle misses."""
        graph, scene = window.graph, window.scene
        graph.add_frame(Frame(id="inner", rect=(300, 100, 300, 160)))
        self._node(window, registry, "held", (330.0, 150.0))
        self._node(window, registry, "overhang", (520.0, 150.0))
        scene.frame_items["inner"].toggle_collapsed()
        graph.add_frame(Frame(id="outer", rect=(260, 60, 160, 160)))
        self._node(window, registry, "loose", (280.0, 100.0))
        return graph, scene

    def test_it_reaches_the_nodes_of_a_folded_child(self, window, registry):
        graph, scene = self._folded_child_reaching_outside(window, registry)
        targets = set(window._nodes_of(graph.frames["outer"]))
        assert {"held", "overhang", "loose"} == targets

    def test_it_does_not_run_another_frames_hidden_nodes(self, window,
                                                         registry):
        """The sweep has to be blind to visibility, and blind meant it picked
        up nodes some other folded frame had left lying under this rect."""
        graph, scene = window.graph, window.scene
        graph.add_frame(Frame(id="other", rect=(100, 100, 300, 200)))
        self._node(window, registry, "theirs1", (140.0, 150.0))
        self._node(window, registry, "theirs2", (260.0, 150.0))
        scene.frame_items["other"].toggle_collapsed()
        graph.add_frame(Frame(id="mine", rect=(120, 120, 320, 220)))
        self._node(window, registry, "ours", (300.0, 250.0))
        assert set(window._nodes_of(graph.frames["mine"])) == {"ours"}

    def test_a_folded_frame_runs_everything_it_stands_for(self, window,
                                                          registry):
        graph, scene = self._folded_child_reaching_outside(window, registry)
        scene.frame_items["outer"].toggle_collapsed()
        targets = set(window._nodes_of(graph.frames["outer"]))
        assert {"held", "overhang", "loose"} == targets

    def test_the_plain_case_is_unchanged(self, window, registry):
        graph, scene = window.graph, window.scene
        graph.add_frame(Frame(id="f1", rect=(100, 100, 400, 240)))
        self._node(window, registry, "a", (140.0, 150.0))
        self._node(window, registry, "b", (300.0, 150.0))
        self._node(window, registry, "outside", (900.0, 150.0))
        assert set(window._nodes_of(graph.frames["f1"])) == {"a", "b"}

    def test_run_by_title_agrees(self, window, registry):
        graph, scene = self._folded_child_reaching_outside(window, registry)
        graph.update_frame("outer", title="Stage One")
        assert set(window._frame_node_ids("Stage One")) == {
            "held", "overhang", "loose"}

    def test_the_nodes_really_execute(self, qtbot, window, registry):
        """Not just the target list — the engine actually runs them."""
        graph, scene = self._folded_child_reaching_outside(window, registry)
        for nid in ("held", "overhang", "loose"):
            assert graph.nodes[nid].dirty
        with qtbot.waitSignal(window.engine.run_finished, timeout=30000):
            window._on_frame_run_requested("outer")
        for nid in ("held", "overhang", "loose"):
            assert not graph.nodes[nid].dirty, f"{nid} was never run"

    def test_a_node_outside_is_left_alone_by_the_run(self, qtbot, window,
                                                     registry):
        graph, scene = self._folded_child_reaching_outside(window, registry)
        self._node(window, registry, "elsewhere", (2000.0, 2000.0))
        with qtbot.waitSignal(window.engine.run_finished, timeout=30000):
            window._on_frame_run_requested("outer")
        assert graph.nodes["elsewhere"].dirty


class TestRunIsAlwaysOnTheFrameMenu:
    """The run glyph in the title bar is a shortcut, not a substitute. It is
    gone while the frame is folded, and on an expanded frame holding folded
    ones it is easy to miss — hiding the menu entry left no way in that could
    be found."""

    @pytest.fixture
    def window(self, qtbot, registry):
        from flograph.ui.mainwindow import MainWindow
        win = MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def _menu_entries(self, window, monkeypatch, frame_id):
        """Open the frame menu without a real popup and read its actions."""
        from PySide6.QtWidgets import QMenu
        from flograph.ui import mainwindow as mw
        seen: dict = {}

        class _Peek(QMenu):
            def exec(self, *args):
                seen["labels"] = [(a.text(), a.isEnabled())
                                  for a in self.actions()]
                return None

        monkeypatch.setattr(mw, "QMenu", _Peek)
        window._show_frame_menu(frame_id, QPoint(0, 0))
        return seen.get("labels", [])

    def _nested(self, window, registry, fold_inner):
        graph, scene = window.graph, window.scene
        graph.add_frame(Frame(id="outer", rect=(100, 100, 600, 340)))
        graph.add_frame(Frame(id="inner", rect=(160, 170, 300, 200)))
        for nid, pos in (("a", (200.0, 220.0)), ("b", (330.0, 220.0))):
            node = registry.instantiate("flograph.scripting.python_script",
                                        pos=pos)
            node.id = nid
            graph.add_node(node)
        if fold_inner:
            scene.frame_items["inner"].toggle_collapsed()
        return graph, scene

    @pytest.mark.parametrize("fold_inner", [False, True])
    def test_an_expanded_frame_offers_run(self, window, registry, monkeypatch,
                                          fold_inner):
        self._nested(window, registry, fold_inner)
        labels = [text for text, _on in
                  self._menu_entries(window, monkeypatch, "outer")]
        assert "Run frame" in labels

    def test_a_folded_frame_still_offers_run(self, window, registry,
                                             monkeypatch):
        graph, scene = self._nested(window, registry, True)
        scene.frame_items["outer"].toggle_collapsed()
        labels = [text for text, _on in
                  self._menu_entries(window, monkeypatch, "outer")]
        assert "Run frame" in labels

    def test_it_is_enabled_when_the_frame_holds_nodes(self, window, registry,
                                                      monkeypatch):
        self._nested(window, registry, True)
        entries = dict(self._menu_entries(window, monkeypatch, "outer"))
        assert entries["Run frame"] is True

    def test_it_is_greyed_when_the_frame_is_empty(self, window, registry,
                                                  monkeypatch):
        window.graph.add_frame(Frame(id="empty", rect=(900, 900, 300, 200)))
        entries = dict(self._menu_entries(window, monkeypatch, "empty"))
        assert entries["Run frame"] is False

    def test_choosing_it_runs_the_frame(self, window, registry, monkeypatch):
        from PySide6.QtWidgets import QMenu
        from flograph.ui import mainwindow as mw
        self._nested(window, registry, True)

        class _Pick(QMenu):
            def exec(self, *args):
                return next(a for a in self.actions()
                            if a.text() == "Run frame")

        monkeypatch.setattr(mw, "QMenu", _Pick)
        fired: list = []
        monkeypatch.setattr(type(window), "_on_frame_run_requested",
                            lambda self, fid: fired.append(fid))
        window._show_frame_menu("outer", QPoint(0, 0))
        assert fired == ["outer"]


class TestFoldingDoesNotAffectExecution:
    """Collapse is a view state. The engine schedules from graph.nodes and
    graph.connections, neither of which folding touches, so a folded flow
    runs exactly as the open one does — same targets, same dependencies,
    and therefore the same concurrency.

    Asserted as "the engine sees no difference" rather than by timing a run.
    Whether two nodes actually overlap is covered by the rendezvous tests in
    test_engine_parallel.py, and repeating that here would only add another
    thread-pool-sensitive test to the suite for a claim that follows.
    """

    @pytest.fixture
    def window(self, qtbot, registry):
        from flograph.ui.mainwindow import MainWindow
        win = MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def _two_branches(self, window, registry):
        """A frame holding two independent chains, one nested a level deeper."""
        graph, scene = window.graph, window.scene
        graph.add_frame(Frame(id="stage", rect=(100, 100, 620, 340)))
        graph.add_frame(Frame(id="pair", rect=(160, 170, 380, 200)))
        for nid, pos in (("a1", (200.0, 220.0)), ("a2", (330.0, 220.0)),
                         ("b1", (200.0, 300.0)), ("b2", (330.0, 300.0))):
            node = registry.instantiate("flograph.scripting.python_script",
                                        pos=pos)
            node.id = nid
            graph.add_node(node)
        graph.connect("a1", "out1", "a2", "in1")
        graph.connect("b1", "out1", "b2", "in1")
        return graph, scene

    def _plan(self, window, targets):
        from flograph.engine.scheduler import build_plan
        return build_plan(window.graph, sorted(targets), window.engine.cache)

    def test_folding_changes_neither_the_nodes_nor_the_wires(self, window,
                                                            registry):
        graph, scene = self._two_branches(window, registry)
        before = (set(graph.nodes),
                  {(c.src_node, c.src_port, c.dst_node, c.dst_port)
                   for c in graph.connections.values()})
        scene.frame_items["pair"].toggle_collapsed()
        scene.frame_items["stage"].toggle_collapsed()
        after = (set(graph.nodes),
                 {(c.src_node, c.src_port, c.dst_node, c.dst_port)
                  for c in graph.connections.values()})
        assert before == after

    def test_running_the_frame_targets_the_same_nodes_either_way(self, window,
                                                                 registry):
        graph, scene = self._two_branches(window, registry)
        open_targets = set(window._nodes_of(graph.frames["stage"]))
        scene.frame_items["pair"].toggle_collapsed()
        assert set(window._nodes_of(graph.frames["stage"])) == open_targets
        scene.frame_items["stage"].toggle_collapsed()
        assert set(window._nodes_of(graph.frames["stage"])) == open_targets
        assert open_targets == {"a1", "a2", "b1", "b2"}

    def test_the_execution_plan_is_identical_folded(self, window, registry):
        graph, scene = self._two_branches(window, registry)
        targets = window._nodes_of(graph.frames["stage"])
        before = self._plan(window, targets)
        scene.frame_items["pair"].toggle_collapsed()
        scene.frame_items["stage"].toggle_collapsed()
        assert self._plan(window, targets) == before

    def test_the_branches_stay_independent_when_folded(self, window, registry):
        """What concurrency actually rests on: nothing about folding
        introduces a dependency between the two chains."""
        graph, scene = self._two_branches(window, registry)
        scene.frame_items["pair"].toggle_collapsed()
        scene.frame_items["stage"].toggle_collapsed()
        upstream: dict = {nid: set() for nid in graph.nodes}
        for conn in graph.connections.values():
            upstream[conn.dst_node].add(conn.src_node)
        assert upstream["b1"] == set()          # nothing gates the second
        assert upstream["a1"] == set()          # nor the first
        assert upstream["a2"] == {"a1"}
        assert upstream["b2"] == {"b1"}
