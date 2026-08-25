"""A frame's own run flags (ideas J2).

The flag lives on the *frame*, not on the nodes inside it. That distinction
is the whole feature: a bulk edit of whatever happened to be in the
rectangle would be a one-off action wearing a checkbox's clothes — a node
dragged in afterwards would run anyway, a node dragged out would stay held,
and the frame would have nothing to show for being set.

So which nodes a flag reaches is worked out afresh whenever a run is built,
from the canvas's own containment rule (frames do not own their contents,
they sit behind them). `RunFlags` is where the two meet.
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Frame, Graph
from flograph.core.graph import GraphError
from flograph.core.serialization import graph_to_dict, graph_from_dict
from flograph.engine.scheduler import RunFlags, build_plan, skipped_summary
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.canvas.node_item import DEACTIVATED_OPACITY
from flograph.ui.commands import SetFrameFlagCommand

from .conftest import make_node


class _FakeCache:
    def __init__(self, cached=()):
        self._cached = set(cached)

    def has(self, node_id: str) -> bool:
        return node_id in self._cached


@pytest.fixture
def framed(chain_graph):
    """The a -> b -> c chain, with an empty frame beside it. What the frame
    holds is supplied per test, because on a real canvas it is a question
    about geometry rather than about the graph."""
    graph, nodes = chain_graph
    frame = graph.add_frame(Frame(id="f1", title="Block"))
    return graph, nodes, frame


# ------------------------------------------------------------- core state

class TestTheFlagLivesOnTheFrame:
    def test_a_new_frame_holds_nothing_back(self, framed):
        graph, nodes, frame = framed
        assert (frame.active, frame.manual) == (True, False)

    def test_the_setter_emits_frame_changed(self, framed):
        graph, nodes, frame = framed
        seen = []
        graph.events.frame_changed.connect(lambda f: seen.append(f.id))
        graph.set_frame_run_flag(frame.id, "manual", True)
        assert seen == [frame.id]
        assert frame.manual is True

    def test_an_unknown_flag_is_refused(self, framed):
        graph, nodes, frame = framed
        with pytest.raises(GraphError):
            graph.set_frame_run_flag(frame.id, "locked", True)

    def test_a_missing_frame_is_refused(self, framed):
        graph, nodes, frame = framed
        with pytest.raises(GraphError):
            graph.set_frame_run_flag("gone", "manual", True)


# --------------------------------------------------------------- the plan

class TestWhatItReaches:
    def test_a_held_frame_holds_what_is_in_it_at_the_time(self, framed):
        """The bug this design replaced: a node put in afterwards ran
        anyway, because the flag had been stamped onto the old contents."""
        graph, nodes, frame = framed
        graph.set_frame_run_flag(frame.id, "manual", True)
        targets = list(graph.nodes)
        # a is inside, and has nothing cached, so its branch goes with it
        flags = RunFlags(graph, {frame.id: [nodes[0].id]})
        assert build_plan(graph, targets, _FakeCache(), (), flags) == []
        # nothing was written to the nodes to achieve that
        assert not any(n.manual for n in nodes)

    def test_a_held_frame_with_a_cached_value_lets_the_rest_run(self, framed):
        graph, nodes, frame = framed
        graph.set_frame_run_flag(frame.id, "manual", True)
        flags = RunFlags(graph, {frame.id: [nodes[0].id]})
        assert build_plan(graph, list(graph.nodes), _FakeCache([nodes[0].id]),
                          (), flags) == [nodes[1].id, nodes[2].id]

    def test_a_node_dragged_out_stops_being_held(self, framed):
        graph, nodes, frame = framed
        graph.set_frame_run_flag(frame.id, "manual", True)
        flags = RunFlags(graph, {frame.id: []})
        assert build_plan(graph, list(graph.nodes), _FakeCache(),
                          (), flags) == [n.id for n in nodes]

    def test_running_the_frame_runs_what_it_holds(self, framed):
        """Aiming at them is exactly what the flag waits for, so Run frame
        works on a frame Run All walks past."""
        graph, nodes, frame = framed
        graph.set_frame_run_flag(frame.id, "manual", True)
        held = [nodes[0].id, nodes[1].id]
        flags = RunFlags(graph, {frame.id: held})
        assert build_plan(graph, held, _FakeCache(), None, flags) == held

    def test_a_disabled_frame_takes_its_branch_out(self, framed):
        graph, nodes, frame = framed
        graph.set_frame_run_flag(frame.id, "active", False)
        flags = RunFlags(graph, {frame.id: [nodes[1].id]})
        assert build_plan(graph, list(graph.nodes), _FakeCache(),
                          (), flags) == [nodes[0].id]

    def test_aiming_at_a_disabled_frame_does_not_override_it(self, framed):
        """Off is off — the same answer a deactivated node gives."""
        graph, nodes, frame = framed
        graph.set_frame_run_flag(frame.id, "active", False)
        flags = RunFlags(graph, {frame.id: [nodes[0].id]})
        assert build_plan(graph, [nodes[0].id], _FakeCache(),
                          None, flags) == []

    def test_a_frame_that_has_gone_is_ignored(self, framed):
        graph, nodes, frame = framed
        flags = RunFlags(graph, {"deleted": [nodes[0].id]})
        assert flags.manual(nodes[0].id) is False

    def test_no_membership_at_all_means_nothing_is_held(self, framed):
        """Headless runs and tests: a node answers for itself."""
        graph, nodes, frame = framed
        graph.set_frame_run_flag(frame.id, "manual", True)
        assert build_plan(graph, list(graph.nodes), _FakeCache(),
                          ()) == [n.id for n in nodes]

    def test_the_summary_counts_a_frame_held_node_as_manual(self, framed):
        graph, nodes, frame = framed
        graph.set_frame_run_flag(frame.id, "manual", True)
        flags = RunFlags(graph, {frame.id: [nodes[0].id]})
        targets = list(graph.nodes)
        cache = _FakeCache([nodes[0].id])
        plan = build_plan(graph, targets, cache, (), flags)
        assert skipped_summary(graph, targets, cache, plan, (),
                               flags) == (0, 0, 0, 1)


# ----------------------------------------------------------- persistence

class TestRoundTrip:
    def test_the_flags_survive_a_save(self, registry, framed):
        graph, nodes, frame = framed
        graph.set_frame_run_flag(frame.id, "manual", True)
        graph.set_frame_run_flag(frame.id, "active", False)
        loaded = graph_from_dict(graph_to_dict(graph), registry)
        assert loaded.frames[frame.id].manual is True
        assert loaded.frames[frame.id].active is False

    def test_a_file_written_before_frames_had_flags_loads_open(
            self, registry, framed):
        graph, nodes, frame = framed
        data = graph_to_dict(graph)
        for entry in data["graph"]["frames"]:
            del entry["active"]
            del entry["manual"]
        loaded = graph_from_dict(data, registry)
        assert loaded.frames[frame.id].active is True
        assert loaded.frames[frame.id].manual is False


# ------------------------------------------------------------------ undo

class TestUndo:
    def test_it_sets_the_frame_and_not_its_contents(self, framed):
        graph, nodes, frame = framed
        stack = QUndoStack()
        stack.push(SetFrameFlagCommand(graph, frame.id, "manual", True,
                                       "run frame only when asked"))
        assert frame.manual is True
        assert not any(n.manual for n in nodes)
        stack.undo()
        assert frame.manual is False
        stack.redo()
        assert frame.manual is True

    def test_disabling_undoes(self, framed):
        graph, nodes, frame = framed
        stack = QUndoStack()
        stack.push(SetFrameFlagCommand(graph, frame.id, "active", False,
                                       "disable frame"))
        assert frame.active is False
        stack.undo()
        assert frame.active is True

    def test_an_unknown_flag_is_refused(self, framed):
        graph, nodes, frame = framed
        with pytest.raises(ValueError):
            SetFrameFlagCommand(graph, frame.id, "frozen", True, "x")

    def test_the_undo_text_is_the_one_it_was_given(self, framed):
        graph, nodes, frame = framed
        cmd = SetFrameFlagCommand(graph, frame.id, "active", False,
                                  "disable frame")
        assert cmd.text() == "disable frame"


# ---------------------------------------------------------------- canvas

@pytest.fixture
def framed_scene(qtbot, registry):
    """One node sitting inside one frame, on a real scene."""
    graph = Graph()
    node = make_node(pos=(60.0, 60.0))
    graph.add_node(node)
    frame = graph.add_frame(Frame(id="f1", title="Block",
                                  rect=(0.0, 0.0, 400.0, 300.0)))
    scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
    return graph, node, frame, scene


class TestTheCanvasShowsIt:
    def test_only_flagged_frames_are_reported_to_the_engine(self,
                                                            framed_scene):
        graph, node, frame, scene = framed_scene
        assert scene.flagged_frame_members() == {}
        graph.set_frame_run_flag(frame.id, "manual", True)
        assert scene.flagged_frame_members() == {frame.id: [node.id]}

    def test_a_node_inside_a_held_frame_wears_the_badge(self, framed_scene):
        graph, node, frame, scene = framed_scene
        item = scene.node_items[node.id]
        assert not item._manual_badge.isVisible()
        graph.set_frame_run_flag(frame.id, "manual", True)
        assert item._manual_badge.isVisible()
        assert item.held_by_frame() is True
        assert "frame" in item.toolTip()

    def test_a_node_dragged_in_afterwards_wears_it_too(self, framed_scene):
        """Exactly what a bulk edit of the contents could not do."""
        graph, node, frame, scene = framed_scene
        graph.set_frame_run_flag(frame.id, "manual", True)
        graph.move_node(node.id, (900.0, 900.0))     # out
        assert not scene.node_items[node.id]._manual_badge.isVisible()
        graph.move_node(node.id, (80.0, 80.0))       # and back in
        assert scene.node_items[node.id]._manual_badge.isVisible()

    def test_clearing_the_frame_flag_clears_the_badge(self, framed_scene):
        graph, node, frame, scene = framed_scene
        graph.set_frame_run_flag(frame.id, "manual", True)
        graph.set_frame_run_flag(frame.id, "manual", False)
        assert not scene.node_items[node.id]._manual_badge.isVisible()

    def test_a_nodes_own_flag_outlives_the_frames(self, framed_scene):
        graph, node, frame, scene = framed_scene
        graph.set_manual(node.id, True)
        graph.set_frame_run_flag(frame.id, "manual", True)
        graph.set_frame_run_flag(frame.id, "manual", False)
        item = scene.node_items[node.id]
        assert item._manual_badge.isVisible()
        assert item.held_by_frame() is False

    def test_a_disabled_frame_fades_what_it_holds(self, framed_scene):
        graph, node, frame, scene = framed_scene
        item = scene.node_items[node.id]
        assert item.opacity() == 1.0
        graph.set_frame_run_flag(frame.id, "active", False)
        assert item.opacity() == pytest.approx(DEACTIVATED_OPACITY)
        graph.set_frame_run_flag(frame.id, "active", True)
        assert item.opacity() == 1.0

    def test_a_node_deactivated_by_hand_stays_faded(self, framed_scene):
        graph, node, frame, scene = framed_scene
        graph.set_active(node.id, False)
        graph.set_frame_run_flag(frame.id, "active", False)
        graph.set_frame_run_flag(frame.id, "active", True)
        assert scene.node_items[node.id].opacity() == pytest.approx(
            DEACTIVATED_OPACITY)

    def test_the_frame_draws_a_marker_only_when_flagged(self, framed_scene):
        graph, node, frame, scene = framed_scene
        item = scene.frame_items[frame.id]
        assert item._marker_rect().isEmpty()
        graph.set_frame_run_flag(frame.id, "manual", True)
        assert not item._marker_rect().isEmpty()
        assert "only when asked" in item.toolTip()

    def test_a_disabled_frame_says_so_on_hover(self, framed_scene):
        graph, node, frame, scene = framed_scene
        graph.set_frame_run_flag(frame.id, "active", False)
        assert "disabled" in scene.frame_items[frame.id].toolTip()

    def test_the_marker_paints_something(self, framed_scene):
        from PySide6.QtGui import QImage, QPainter
        graph, node, frame, scene = framed_scene
        item = scene.frame_items[frame.id]
        inked = {}
        for flag, value in (("manual", True), ("active", False)):
            graph.set_frame_run_flag(frame.id, flag, value)
            image = QImage(48, 48, QImage.Format_ARGB32)
            image.fill(0)
            painter = QPainter(image)
            item._paint_marker(painter)
            painter.end()
            inked[flag] = sum(1 for y in range(48) for x in range(48)
                              if image.pixelColor(x, y).alpha() > 0)
        assert inked["manual"] > 10, inked
        assert inked["active"] > 10, inked

    def test_the_title_moves_over_to_make_room(self, framed_scene):
        graph, node, frame, scene = framed_scene
        item = scene.frame_items[frame.id]
        graph.set_frame_run_flag(frame.id, "manual", True)
        marker = item._marker_rect()
        assert marker.left() > item._toggle_rect().right()
        assert marker.right() < item._run_button_rect().left()
