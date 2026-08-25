"""Nodes and frames that only run when asked (ideas J1/J2).

A third run flag beside `active` and `frozen`, and easy to mistake for
either. *Deactivate* takes a branch out of every run. *Freeze* pins a value
and stops the node recomputing at all. *Manual* is about who asked: Run All
walks past the node, and so does the re-run a moved slider sets off, but
Run To This Node, Run Selected or an Action Button naming it all fire it
normally.

What happens below a manual node depends on whether it has anything to
give. With a cached value the branch runs off that, exactly as it would
under a pin; with nothing cached the branch is skipped, because there is no
input for it to run on.
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeInstance, NodeStatus, parse_spec
from flograph.core.serialization import graph_to_dict, graph_from_dict
from flograph.engine import ExecutionEngine
from flograph.engine.scheduler import build_plan, skipped_summary
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.commands import SetManualCommand

from .conftest import make_node


class _FakeCache:
    """Just the one question build_plan asks of a cache."""

    def __init__(self, cached=()):
        self._cached = set(cached)

    def has(self, node_id: str) -> bool:
        return node_id in self._cached


# ------------------------------------------------------------- core state

class TestDefaultsAndSetters:
    def test_a_new_node_runs_with_everything_else(self):
        assert make_node().manual is False

    def test_the_setter_emits(self, chain_graph):
        graph, nodes = chain_graph
        seen = []
        graph.events.manual_changed.connect(lambda n, v: seen.append((n, v)))
        graph.set_manual(nodes[0].id, True)
        assert seen == [(nodes[0].id, True)]
        assert nodes[0].manual is True

    def test_neither_direction_dirties(self, chain_graph):
        """Unlike releasing a pin. Taking a node off manual is a statement
        about future runs, not a request to redo the expensive thing."""
        graph, nodes = chain_graph
        graph.mark_clean(nodes[0].id)
        graph.set_manual(nodes[0].id, True)
        assert nodes[0].id not in build_plan(graph, list(graph.nodes))
        graph.set_manual(nodes[0].id, False)
        assert nodes[0].id not in build_plan(graph, list(graph.nodes))


# --------------------------------------------------------------- the plan

class TestRunAllWalksPast:
    def test_a_manual_node_with_a_value_is_skipped_and_the_rest_runs(
            self, chain_graph):
        graph, nodes = chain_graph
        graph.set_manual(nodes[0].id, True)
        cache = _FakeCache([nodes[0].id])
        assert build_plan(graph, list(graph.nodes), cache,
                          asked=()) == [nodes[1].id, nodes[2].id]

    def test_with_nothing_cached_the_branch_below_goes_too(self, chain_graph):
        """No input for the branch to run on, so a row of nodes each
        reporting a missing input is not the useful answer."""
        graph, nodes = chain_graph
        graph.set_manual(nodes[1].id, True)
        assert build_plan(graph, list(graph.nodes), _FakeCache(),
                          asked=()) == [nodes[0].id]

    def test_a_manual_leaf_only_takes_itself_out(self, chain_graph):
        graph, nodes = chain_graph
        graph.set_manual(nodes[2].id, True)
        assert build_plan(graph, list(graph.nodes), _FakeCache(),
                          asked=()) == [nodes[0].id, nodes[1].id]

    def test_clearing_the_flag_puts_it_back(self, chain_graph):
        graph, nodes = chain_graph
        graph.set_manual(nodes[0].id, True)
        graph.set_manual(nodes[0].id, False)
        assert build_plan(graph, list(graph.nodes), _FakeCache(),
                          asked=()) == [n.id for n in nodes]


class TestAimingAtItRunsIt:
    def test_run_to_this_node_fires_it(self, chain_graph):
        """`asked=None` — every caller that predates manual nodes — means
        the targets are the aim, which is true of all of them."""
        graph, nodes = chain_graph
        graph.set_manual(nodes[1].id, True)
        assert build_plan(graph, [nodes[1].id],
                          _FakeCache()) == [nodes[0].id, nodes[1].id]

    def test_run_selected_fires_the_one_named_and_not_the_other(
            self, chain_graph):
        graph, nodes = chain_graph
        graph.set_manual(nodes[0].id, True)
        graph.set_manual(nodes[2].id, True)
        cache = _FakeCache([nodes[0].id])
        plan = build_plan(graph, list(graph.nodes), cache,
                          asked=[nodes[2].id])
        assert plan == [nodes[1].id, nodes[2].id]

    def test_naming_it_beats_having_nothing_cached(self, chain_graph):
        """The case the flag exists for: the first run of the node nobody
        wants fired by accident."""
        graph, nodes = chain_graph
        graph.set_manual(nodes[0].id, True)
        assert build_plan(graph, [n.id for n in nodes], _FakeCache(),
                          asked=[nodes[0].id]) == [n.id for n in nodes]

    def test_deactivating_still_wins(self, chain_graph):
        """Both flags on, and off is off — naming it does not override it."""
        graph, nodes = chain_graph
        graph.set_manual(nodes[0].id, True)
        graph.set_active(nodes[0].id, False)
        assert build_plan(graph, [nodes[0].id], _FakeCache()) == []


# ------------------------------------------------------------ the summary

class TestSkippedSummary:
    def _summary(self, graph, cache, asked):
        targets = list(graph.nodes)
        plan = build_plan(graph, targets, cache, asked)
        return skipped_summary(graph, targets, cache, plan, asked)

    def test_a_held_manual_node_is_counted_as_manual_not_frozen(
            self, chain_graph):
        graph, nodes = chain_graph
        graph.set_manual(nodes[0].id, True)
        cache = _FakeCache([nodes[0].id])
        assert self._summary(graph, cache, ()) == (0, 0, 0, 1)

    def test_the_branch_below_an_unrun_manual_node_counts_too(self,
                                                              chain_graph):
        """Same reading as a deactivated branch: they were left out by that
        one decision, so the count names it."""
        graph, nodes = chain_graph
        graph.set_manual(nodes[1].id, True)
        assert self._summary(graph, _FakeCache(), ()) == (0, 0, 0, 2)

    def test_a_node_that_was_asked_for_is_not_counted(self, chain_graph):
        graph, nodes = chain_graph
        graph.set_manual(nodes[0].id, True)
        assert self._summary(graph, _FakeCache(),
                             [nodes[0].id]) == (0, 0, 0, 0)

    def test_clean_and_manual_are_told_apart(self, chain_graph):
        graph, nodes = chain_graph
        graph.set_manual(nodes[2].id, True)
        graph.mark_clean(nodes[0].id)
        assert self._summary(graph, _FakeCache([nodes[0].id]),
                             ()) == (1, 0, 0, 1)


# ------------------------------------------------------------- the engine

TAGGED = """
NODE = {
    "label": "Tagged",
    "category": "Test",
    "inputs": [("value", "any", {"optional": True})],
    "outputs": [("value", "any")],
}
def run(ctx, value):
    ctx.log("ran")
    return (value or 0) + 1
"""


@pytest.fixture
def engine_chain():
    """a -> b, plus an unrelated c, on a real engine, with a record of what
    actually ran.

    c is there so that a run whose only interesting node is manual still has
    something to do: a plan that comes out empty returns without starting a
    run at all, which is how the engine has always treated a Run All with
    nothing dirty, and there would be no run_finished to wait for.
    """
    graph = Graph()
    a, b, c = (NodeInstance.create(parse_spec(TAGGED, "test.tagged"))
               for _ in range(3))
    for node in (a, b, c):
        graph.add_node(node)
    graph.connect(a.id, "value", b.id, "value")
    engine = ExecutionEngine(graph)
    ran: list[str] = []
    engine.node_log.connect(
        lambda nid, line, stream: ran.append(nid) if line == "ran" else None)
    return graph, (a, b, c), engine, ran


def _run(qtbot, engine, trigger, timeout=5000):
    with qtbot.waitSignal(engine.run_finished, timeout=timeout) as blocker:
        trigger()
    return blocker.args[0]


class TestRunningForReal:
    def test_run_all_leaves_a_manual_node_alone(self, qtbot, engine_chain):
        graph, (a, b, c), engine, ran = engine_chain
        graph.set_manual(a.id, True)
        assert _run(qtbot, engine, engine.run_all)
        assert ran == [c.id]        # b had no input, so it went too

    def test_run_to_fires_it(self, qtbot, engine_chain):
        graph, (a, b, c), engine, ran = engine_chain
        graph.set_manual(a.id, True)
        assert _run(qtbot, engine, lambda: engine.run_to(a.id))
        assert ran == [a.id]

    def test_once_it_has_run_the_rest_runs_off_its_value(self, qtbot,
                                                         engine_chain):
        graph, (a, b, c), engine, ran = engine_chain
        graph.set_manual(a.id, True)
        _run(qtbot, engine, lambda: engine.run_to(a.id))
        ran.clear()
        assert _run(qtbot, engine, engine.run_all)
        assert set(ran) == {b.id, c.id}
        assert engine.cache.has(a.id)

    def test_the_reactive_rerun_walks_past_it_too(self, qtbot, engine_chain):
        """A slider moving must not fire the node that costs money."""
        graph, (a, b, c), engine, ran = engine_chain
        graph.set_manual(a.id, True)
        assert _run(qtbot, engine,
                    lambda: engine.request_run([a.id, b.id, c.id]))
        assert ran == [c.id]

    def test_an_action_button_naming_it_fires_it(self, qtbot, engine_chain):
        """What run_targets does for a button's explicit list."""
        graph, (a, b, c), engine, ran = engine_chain
        graph.set_manual(a.id, True)
        assert _run(qtbot, engine,
                    lambda: engine.run_targets([a.id, b.id]))
        assert ran == [a.id, b.id]

    def test_the_run_record_says_how_many_it_held_back(self, qtbot,
                                                       engine_chain):
        graph, (a, b, c), engine, ran = engine_chain
        graph.set_manual(a.id, True)
        _run(qtbot, engine, engine.run_all)
        assert engine.history.latest.skipped_manual == 2

    def test_a_skipped_manual_node_is_not_left_looking_queued(
            self, qtbot, engine_chain):
        graph, (a, b, c), engine, ran = engine_chain
        graph.set_manual(a.id, True)
        _run(qtbot, engine, engine.run_all)
        assert graph.node(a.id).status is not NodeStatus.QUEUED
        assert graph.node(a.id).status is not NodeStatus.RUNNING


# ----------------------------------------------------------- persistence

class TestRoundTrip:
    def test_the_flag_survives_a_save(self, registry, chain_graph):
        graph, nodes = chain_graph
        graph.set_manual(nodes[1].id, True)
        loaded = graph_from_dict(graph_to_dict(graph), registry)
        assert loaded.node(nodes[1].id).manual is True
        assert loaded.node(nodes[0].id).manual is False

    def test_a_file_written_before_this_existed_loads_harmlessly(
            self, registry, chain_graph):
        graph, nodes = chain_graph
        data = graph_to_dict(graph)
        for entry in data["graph"]["nodes"]:
            del entry["manual"]
        loaded = graph_from_dict(data, registry)
        assert all(not n.manual for n in loaded.nodes.values())


# ---------------------------------------------------------------- canvas

@pytest.fixture
def scene(qtbot, registry):
    graph = Graph()
    node = make_node()
    graph.add_node(node)
    sc = NodeGraphScene(graph, QUndoStack(), registry=registry)
    return graph, node, sc.node_items[node.id]


class TestOnTheCanvas:
    def test_the_badge_shows_only_when_manual(self, scene):
        graph, node, item = scene
        assert not item._manual_badge.isVisible()
        graph.set_manual(node.id, True)
        assert item._manual_badge.isVisible()
        graph.set_manual(node.id, False)
        assert not item._manual_badge.isVisible()

    def test_the_badge_actually_paints_something(self, scene):
        from PySide6.QtGui import QImage, QPainter
        graph, node, item = scene
        graph.set_manual(node.id, True)
        badge = item._manual_badge
        rect = badge.boundingRect()
        image = QImage(int(rect.width()) + 4, int(rect.height()) + 4,
                       QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        painter.translate(2 - rect.left(), 2 - rect.top())
        badge.paint(painter, None)
        painter.end()
        inked = sum(1 for y in range(image.height())
                    for x in range(image.width())
                    if image.pixelColor(x, y).alpha() > 0)
        assert inked > 20, f"the play glyph drew {inked} pixels"

    def test_it_says_so_on_hover(self, scene):
        graph, node, item = scene
        graph.set_manual(node.id, True)
        assert "Manual" in item.toolTip()

    def test_badges_do_not_overlap(self, scene):
        graph, node, item = scene
        graph.set_manual(node.id, True)
        graph.set_locked(node.id, True)
        gap = abs(item._lock_badge.pos().x() - item._manual_badge.pos().x())
        assert gap >= item._lock_badge.W

    def test_state_from_disk_is_applied_when_the_item_is_built(self, qtbot,
                                                               registry):
        graph = Graph()
        node = make_node()
        node.manual = True
        graph.add_node(node)
        sc = NodeGraphScene(graph, QUndoStack(), registry=registry)
        assert sc.node_items[node.id]._manual_badge.isVisible()


# ------------------------------------------------------------------ undo

class TestUndo:
    def test_it_undoes(self, chain_graph):
        graph, nodes = chain_graph
        stack = QUndoStack()
        stack.push(SetManualCommand(graph, nodes[0].id, True))
        assert nodes[0].manual is True
        stack.undo()
        assert nodes[0].manual is False
        stack.redo()
        assert nodes[0].manual is True

    def test_the_command_is_named_for_what_it_did(self, chain_graph):
        graph, nodes = chain_graph
        assert SetManualCommand(graph, nodes[0].id, True).text() == (
            "run node only when asked")
        assert SetManualCommand(graph, nodes[0].id, False).text() == (
            "run node with the rest")


