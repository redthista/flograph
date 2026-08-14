"""Collapsible frames: the model, the collapsed box, its pins and its wires.

Frames had no test file of their own before this — drag, resize, rename and
the carry-your-contents behaviour were all untested — so this covers the
collapse feature and the frame behaviour it leans on.
"""
import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
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
    """The two things a folded frame must never do to whatever it is
    sitting on: absorb it, or drag it around."""

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

    def test_folding_again_does_not_absorb_what_it_sits_on(self, env, registry):
        graph, stack, scene, item = self._folded_over_bystanders(env, registry)
        expand(scene, "f1")            # region reappears over the bystanders
        collapse(scene, "f1")          # and folds again
        assert "bystander1" not in item.member_ids()
        assert "bystander2" not in item.member_ids()
        assert scene.node_items["bystander1"].isVisible()
        assert scene.node_items["bystander2"].isVisible()

    def test_dragging_it_does_not_carry_what_it_sits_on(self, env, registry):
        """The bug behind 'ctrl-z didn't put them back': the drag moved
        bystanders as a side effect, and that move was a separate undo entry
        from the collapse."""
        graph, stack, scene, item = self._folded_over_bystanders(env, registry)
        nodes, _frames = item.carried_items()
        carried = {i.node.id for i, _off in nodes}
        assert carried == {"inside"}
        assert "bystander1" not in carried and "bystander2" not in carried

    def test_expanding_pushes_the_bystanders_clear(self, env, registry):
        graph, stack, scene, item = self._folded_over_bystanders(env, registry)
        before = graph.nodes["bystander1"].pos
        expand(scene, "f1")
        region = item.scene_rect()
        for name in ("bystander1", "bystander2"):
            assert not region.intersects(
                scene.node_items[name].sceneBoundingRect())
        assert graph.nodes["bystander1"].pos != before
        # and its own contents were left exactly where they were
        assert region.contains(
            scene.node_items["inside"].sceneBoundingRect().center())

    def test_one_undo_puts_the_frame_and_the_bystanders_back(self, env, registry):
        graph, stack, scene, item = self._folded_over_bystanders(env, registry)
        before = {n: graph.nodes[n].pos
                  for n in ("bystander1", "bystander2", "inside")}
        expand(scene, "f1")
        stack.undo()
        assert graph.frames["f1"].collapsed is True
        assert {n: graph.nodes[n].pos for n in before} == before

    def test_expanding_leaves_distant_nodes_alone(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 300, 200)))
        script_node(graph, registry, "inside", (50.0, 50.0))
        far = script_node(graph, registry, "far", (5000.0, 5000.0))
        collapse(scene, "f1")
        before = graph.nodes["far"].pos
        expand(scene, "f1")
        assert graph.nodes["far"].pos == before


class TestNudgePlan:
    """The displacement arithmetic, without a canvas."""

    def plan(self, region, units, gap=20.0):
        from flograph.ui.canvas.scene import plan_nudge
        return plan_nudge(QRectF(*region), [(k, QRectF(*r)) for k, r in units],
                          gap=gap)

    def test_nothing_in_the_way_moves_nothing(self):
        assert self.plan((0, 0, 100, 100), [("a", (500, 500, 50, 50))]) == {}

    def test_something_in_the_way_is_pushed_clear(self):
        plan = self.plan((0, 0, 100, 100), [("a", (80, 10, 50, 50))])
        dx, dy = plan["a"]
        assert dx > 0 and dy == 0            # nearer the right edge
        assert 80 + dx >= 100 + 20           # and clears it by the gap

    def test_everything_goes_right_even_when_down_is_nearer(self):
        """One predictable direction beats a shorter shove nobody can
        anticipate — and a flow reads left to right, so sideways is the way
        that keeps its shape."""
        plan = self.plan((0, 0, 400, 100), [("a", (10, 80, 50, 50))])
        dx, dy = plan["a"]
        assert dx > 0 and dy == 0
        assert 10 + dx >= 400 + 20

    def test_a_push_ripples_to_what_it_hits(self):
        """b is nowhere near the frame, but a lands on it."""
        plan = self.plan((0, 0, 100, 100),
                         [("a", (80, 10, 50, 50)), ("b", (140, 10, 50, 50))])
        assert plan["a"][0] > 0
        assert plan["b"][0] > 0, "b was in a's way and should have moved on"

    def test_a_ripple_also_goes_right(self):
        plan = self.plan((0, 0, 400, 100),
                         [("a", (10, 80, 50, 50)), ("b", (420, 80, 50, 50))])
        assert plan["a"][0] > 0 and plan["a"][1] == 0
        assert plan["b"][0] > 0 and plan["b"][1] == 0

    def test_nothing_is_ever_pushed_downward(self):
        plan = self.plan((0, 0, 400, 400),
                         [("a", (10, 10, 50, 50)), ("b", (10, 200, 50, 50)),
                          ("c", (200, 350, 50, 50))])
        assert all(dy == 0 for _dx, dy in plan.values())
        assert all(dx > 0 for dx, _dy in plan.values())

    def test_a_chain_of_three_all_move(self):
        plan = self.plan((0, 0, 100, 100),
                         [("a", (80, 10, 50, 50)), ("b", (140, 10, 50, 50)),
                          ("c", (200, 10, 50, 50))])
        assert all(plan[k][0] > 0 for k in "abc")

    def test_everything_ends_clear_of_the_region_and_each_other(self):
        units = [("a", (80, 10, 50, 50)), ("b", (140, 10, 50, 50)),
                 ("c", (200, 10, 50, 50))]
        region = QRectF(0, 0, 100, 100)
        plan = self.plan((0, 0, 100, 100), units)
        moved = []
        for key, rect in units:
            dx, dy = plan.get(key, (0.0, 0.0))
            moved.append(QRectF(rect[0] + dx, rect[1] + dy, rect[2], rect[3]))
        for i, rect in enumerate(moved):
            assert not rect.intersects(region)
            for other in moved[i + 1:]:
                assert not rect.intersects(other)


class TestNudgeRespectsFrames:
    def test_expanding_over_a_frame_moves_it_whole(self, env, registry):
        """The 'it stole some of the nodes' report: the neighbour used to sit
        still while its contents were shoved out from under it."""
        graph, stack, scene = env
        graph.add_frame(Frame(id="mine", rect=(0, 0, 300, 200)))
        script_node(graph, registry, "own", (50.0, 50.0))
        collapse(scene, "mine")

        # a neighbour with two nodes, overlapping where 'mine' will reopen
        graph.add_frame(Frame(id="theirs", rect=(200, 40, 260, 180)))
        script_node(graph, registry, "their1", (240.0, 80.0))
        script_node(graph, registry, "their2", (330.0, 120.0))
        before = {n: graph.nodes[n].pos for n in ("their1", "their2")}
        their_rect = graph.frames["theirs"].rect

        expand(scene, "mine")

        # the frame moved, and its nodes went with it by the same amount
        assert graph.frames["theirs"].rect != their_rect
        dx = graph.frames["theirs"].rect[0] - their_rect[0]
        dy = graph.frames["theirs"].rect[1] - their_rect[1]
        for name in ("their1", "their2"):
            assert graph.nodes[name].pos == (before[name][0] + dx,
                                             before[name][1] + dy)
        # so the neighbour still holds exactly what it did
        rect = QRectF(*graph.frames["theirs"].rect)
        held = [n for n in ("their1", "their2")
                if rect.contains(
                    scene.node_items[n].sceneBoundingRect().center())]
        assert held == ["their1", "their2"]

    def test_one_undo_puts_the_neighbouring_frame_back(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="mine", rect=(0, 0, 300, 200)))
        script_node(graph, registry, "own", (50.0, 50.0))
        collapse(scene, "mine")
        graph.add_frame(Frame(id="theirs", rect=(200, 40, 260, 180)))
        script_node(graph, registry, "their1", (240.0, 80.0))
        before_rect = graph.frames["theirs"].rect
        before_pos = graph.nodes["their1"].pos

        expand(scene, "mine")
        stack.undo()
        assert graph.frames["theirs"].rect == before_rect
        assert graph.nodes["their1"].pos == before_pos

    def test_its_own_contents_never_travel_with_a_neighbour(self, env, registry):
        """Frames overlap, and membership is geometric, so a neighbour can
        legally claim nodes belonging to the frame being expanded. Letting
        them travel with it dragged the expanding frame's own contents out
        from under it — and only the ones under the overlap, which looked
        like 'every child but the first'."""
        graph, stack, scene = env
        graph.add_frame(Frame(id="mine", rect=(0, 0, 500, 200)))
        for i in range(4):
            script_node(graph, registry, f"child{i}", (40.0 + i * 110, 60.0))
        collapse(scene, "mine")
        # a neighbour overlapping where 'mine' reopens, so the later
        # children fall inside it too
        graph.add_frame(Frame(id="theirs", rect=(200, 20, 500, 260)))
        script_node(graph, registry, "theirs1", (600.0, 100.0))

        before = {n: graph.nodes[n].pos for n in graph.nodes}
        expand(scene, "mine")
        for i in range(4):
            assert graph.nodes[f"child{i}"].pos == before[f"child{i}"], \
                f"child{i} was dragged along by the overlapping neighbour"
        assert graph.nodes["theirs1"].pos != before["theirs1"]

    def test_collapsing_puts_back_what_expanding_moved(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 400, 300)))
        script_node(graph, registry, "inside", (50.0, 50.0))
        collapse(scene, "f1")
        script_node(graph, registry, "bystander", (100.0, 100.0))
        where = graph.nodes["bystander"].pos

        expand(scene, "f1")
        assert graph.nodes["bystander"].pos != where     # shoved aside
        assert graph.frames["f1"].nudged                 # and written down
        collapse(scene, "f1")
        assert graph.nodes["bystander"].pos == where     # and put back
        assert graph.frames["f1"].nudged == ()           # record spent

    def test_a_node_you_moved_yourself_is_left_alone(self, env, registry):
        """There is no way to tell an arrangement you chose from one we
        imposed except by whether it has changed since."""
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 400, 300)))
        script_node(graph, registry, "inside", (50.0, 50.0))
        collapse(scene, "f1")
        script_node(graph, registry, "bystander", (100.0, 100.0))

        expand(scene, "f1")
        graph.move_node("bystander", (2000.0, 2000.0))   # you put it there
        collapse(scene, "f1")
        assert graph.nodes["bystander"].pos == (2000.0, 2000.0)

    def test_the_put_back_is_one_undo_step(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="f1", rect=(0, 0, 400, 300)))
        script_node(graph, registry, "inside", (50.0, 50.0))
        collapse(scene, "f1")
        script_node(graph, registry, "bystander", (100.0, 100.0))
        expand(scene, "f1")
        shoved = graph.nodes["bystander"].pos

        depth = stack.index()
        collapse(scene, "f1")
        assert stack.index() == depth + 1
        stack.undo()
        assert graph.frames["f1"].collapsed is False
        assert graph.nodes["bystander"].pos == shoved

    def test_a_pushed_frame_is_put_back_with_its_contents(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="mine", rect=(0, 0, 400, 300)))
        script_node(graph, registry, "own", (50.0, 50.0))
        collapse(scene, "mine")
        graph.add_frame(Frame(id="theirs", rect=(150, 40, 260, 180)))
        script_node(graph, registry, "their1", (200.0, 80.0))
        rect_before = graph.frames["theirs"].rect
        pos_before = graph.nodes["their1"].pos

        expand(scene, "mine")
        assert graph.frames["theirs"].rect != rect_before
        collapse(scene, "mine")
        assert graph.frames["theirs"].rect == rect_before
        assert graph.nodes["their1"].pos == pos_before

    def test_its_own_nested_frame_is_not_pushed_away(self, env, registry):
        graph, stack, scene = env
        graph.add_frame(Frame(id="outer", rect=(0, 0, 400, 300)))
        graph.add_frame(Frame(id="inner", rect=(50, 50, 100, 100)))
        script_node(graph, registry, "deep", (70.0, 70.0))
        collapse(scene, "outer")
        assert "inner" in graph.frames["outer"].member_frames
        inner_rect = graph.frames["inner"].rect
        expand(scene, "outer")
        assert graph.frames["inner"].rect == inner_rect


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
