"""Drop Output: a node that drops its value once the nodes reading it are
done (Power BI's "Enable load").

The node runs as usual and stays green; its value is evicted after its last
reader in the run finishes, it is never saved, and it comes back — by
running again — only when a run needs it: a reader that has to re-run, or
somebody aiming at the node itself to look at it.
"""
from __future__ import annotations

import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeInstance, NodeStatus, Page, Tile, parse_spec
from flograph.core.drop_output import (can_drop_output, readers,
                                       settled_on_open)
from flograph.core.serialization import graph_from_dict, graph_to_dict
from flograph.engine import ExecutionEngine
from flograph.engine.scheduler import build_plan
from flograph.ui.commands import (SetFrozenCommand, SetDropOutputCommand,
                                  SetManualCommand)

SOURCE = """
NODE = {"label": "Src", "category": "Test", "inputs": [],
        "outputs": [("table", "any")]}
PARAMS = [{"name": "value", "type": "int", "default": 3}]
def run(ctx):
    ctx.log("ran")
    return {"table": [ctx.params["value"]]}
"""

DOUBLE = """
NODE = {"label": "Double", "category": "Test",
        "inputs": [("table", "any")], "outputs": [("table", "any")]}
PARAMS = [{"name": "factor", "type": "int", "default": 2}]
def run(ctx, table):
    ctx.log("ran")
    return {"table": table * ctx.params["factor"]}
"""

BOOM = """
NODE = {"label": "Boom", "category": "Test",
        "inputs": [("table", "any")], "outputs": [("table", "any")]}
def run(ctx, table):
    raise ValueError("boom")
"""

CARD = """
NODE = {"label": "Card", "category": "Test", "card": "table_viewer",
        "inputs": [("table", "any")], "outputs": [("table", "any")]}
def run(ctx, table):
    return {"table": table}
"""


def _node(source, type_id="t.x"):
    return NodeInstance.create(parse_spec(source, type_id))


@pytest.fixture
def chain():
    """src (Drop Output on) -> mid -> tail, on a real engine."""
    graph = Graph()
    src, mid, tail = _node(SOURCE, "t.src"), _node(DOUBLE), _node(DOUBLE)
    for node in (src, mid, tail):
        graph.add_node(node)
    graph.connect(src.id, "table", mid.id, "table")
    graph.connect(mid.id, "table", tail.id, "table")
    graph.set_drop_output(src.id, True)
    engine = ExecutionEngine(graph)
    ran: list[str] = []
    engine.node_log.connect(
        lambda nid, line, stream: ran.append(nid) if line == "ran" else None)
    return graph, (src, mid, tail), engine, ran


def _run(qtbot, engine, trigger=None, timeout=5000):
    with qtbot.waitSignal(engine.run_finished, timeout=timeout) as blocker:
        (trigger or engine.run_all)()
    return blocker.args[0]


class TestRunning:
    def test_the_value_goes_once_read_and_the_node_stays_green(
            self, qtbot, chain):
        graph, (src, mid, tail), engine, ran = chain
        assert _run(qtbot, engine)
        assert ran == [src.id, mid.id, tail.id]
        assert not engine.cache.has(src.id)
        assert engine.cache.has(mid.id) and engine.cache.has(tail.id)
        assert src.released and not src.dirty
        assert src.status == NodeStatus.DONE

    def test_run_all_again_does_nothing(self, qtbot, chain):
        graph, (src, mid, tail), engine, ran = chain
        _run(qtbot, engine)
        ran.clear()
        engine.run_all()                  # nothing dirty: no run starts
        assert not engine.active and ran == []

    def test_a_reader_that_must_rerun_brings_it_back(self, qtbot, chain):
        graph, (src, mid, tail), engine, ran = chain
        _run(qtbot, engine)
        ran.clear()
        graph.set_param(mid.id, "factor", 3)
        assert _run(qtbot, engine)
        assert ran == [src.id, mid.id, tail.id]
        assert engine.cache.outputs_for(tail.id)["table"] == [3] * 6
        assert not engine.cache.has(src.id) and src.released

    def test_aiming_at_it_runs_it_and_keeps_it_to_look_at(self, qtbot, chain):
        graph, (src, mid, tail), engine, ran = chain
        _run(qtbot, engine)
        ran.clear()
        assert _run(qtbot, engine, lambda: engine.run_to(src.id))
        assert ran == [src.id]
        assert engine.cache.has(src.id) and not src.released

    def test_a_chain_of_them_comes_back_whole(self, qtbot, chain):
        graph, (src, mid, tail), engine, ran = chain
        graph.set_drop_output(mid.id, True)
        _run(qtbot, engine)
        assert not engine.cache.has(src.id) and not engine.cache.has(mid.id)
        ran.clear()
        graph.set_param(tail.id, "factor", 5)
        assert _run(qtbot, engine)
        assert ran == [src.id, mid.id, tail.id]

    def test_a_failed_reader_still_lets_it_go(self, qtbot):
        graph = Graph()
        src, boom = _node(SOURCE, "t.src"), _node(BOOM, "t.boom")
        graph.add_node(src)
        graph.add_node(boom)
        graph.connect(src.id, "table", boom.id, "table")
        graph.set_drop_output(src.id, True)
        engine = ExecutionEngine(graph)
        assert _run(qtbot, engine) is False
        assert not engine.cache.has(src.id)

    def test_a_node_with_two_readers_waits_for_both(self, qtbot, chain):
        graph, (src, mid, tail), engine, ran = chain
        other = _node(DOUBLE)
        graph.add_node(other)
        graph.connect(src.id, "table", other.id, "table")
        seen = []
        engine.node_succeeded.connect(
            lambda nid: seen.append((nid, engine.cache.has(src.id))))
        _run(qtbot, engine)
        # still held when the first reader finished, gone after the second
        firsts = [held for nid, held in seen if nid in (mid.id, other.id)]
        assert firsts[0] is True
        assert not engine.cache.has(src.id)

    def test_turning_it_off_after_a_run_frees_it_now(self, qtbot, chain):
        graph, (src, mid, tail), engine, ran = chain
        graph.set_drop_output(src.id, False)
        _run(qtbot, engine)
        assert engine.cache.has(src.id)
        graph.set_drop_output(src.id, True)
        assert not engine.cache.has(src.id) and src.released

    def test_dirtying_it_clears_released(self, qtbot, chain):
        graph, (src, mid, tail), engine, ran = chain
        _run(qtbot, engine)
        graph.set_param(src.id, "value", 9)
        assert not src.released and src.dirty


class TestPlan:
    def test_order_edges_are_not_readers(self):
        graph = Graph()
        a, b = _node(SOURCE, "t.src"), _node(DOUBLE)
        graph.add_node(a)
        graph.add_node(b)
        graph.connect(a.id, "flow", b.id, "flow")
        assert readers(graph, a.id) == set()

    def test_run_all_leaves_a_released_node_alone(self, chain):
        graph, (src, mid, tail), engine, ran = chain
        for node in (src, mid, tail):
            graph.mark_clean(node.id)
        src.released = True

        class _Cache:
            def has(self, nid):
                return nid != src.id
        assert build_plan(graph, list(graph.nodes), _Cache(), asked=()) == []


class TestReopen:
    def test_restored_readers_vouch_for_it(self, chain):
        graph, (src, mid, tail), engine, ran = chain
        assert settled_on_open(graph, [mid.id, tail.id]) == [src.id]

    def test_not_if_a_reader_was_not_restored(self, chain):
        graph, (src, mid, tail), engine, ran = chain
        assert settled_on_open(graph, [tail.id]) == []

    def test_a_chain_settles_through(self, chain):
        graph, (src, mid, tail), engine, ran = chain
        graph.set_drop_output(mid.id, True)
        assert set(settled_on_open(graph, [tail.id])) == {src.id, mid.id}

    def test_a_leaf_has_nothing_to_vouch_for_it(self, chain):
        graph, (src, mid, tail), engine, ran = chain
        graph.set_drop_output(tail.id, True)
        assert tail.id not in settled_on_open(graph, [mid.id])

    def test_round_trips_and_released_is_not_saved(self, chain, registry):
        graph, (src, mid, tail), engine, ran = chain
        src.released = True
        data = graph_to_dict(graph)
        entries = {e["id"]: e for e in data["graph"]["nodes"]}
        assert entries[src.id]["drop_output"] is True
        assert "drop_output" not in entries[mid.id]
        back = graph_from_dict(data, registry)
        assert back.nodes[src.id].drop_output is True
        assert back.nodes[src.id].released is False


class TestWhoMayDrop:
    def test_a_card_always_keeps(self):
        graph = Graph()
        card = _node(CARD, "t.card")
        graph.add_node(card)
        assert not can_drop_output(graph, card)

    def test_a_node_on_a_dashboard_always_keeps(self, chain):
        graph, (src, mid, tail), engine, ran = chain
        assert can_drop_output(graph, mid)
        graph.add_page(Page(id="p1", title="Board"))
        graph.add_tile("p1", Tile(id="t1", node_id=mid.id, port="table"))
        assert not can_drop_output(graph, mid)

    def test_a_node_without_outputs_has_nothing_to_drop(self):
        graph = Graph()
        sink = _node("""
NODE = {"label": "Sink", "category": "Test",
        "inputs": [("x", "any")], "outputs": []}
def run(ctx, x):
    return {}
""", "t.sink")
        graph.add_node(sink)
        assert not can_drop_output(graph, sink)


class TestOneChoice:
    @pytest.fixture
    def setup(self):
        graph = Graph()
        node = _node(DOUBLE)
        graph.add_node(node)
        return graph, node, QUndoStack()

    def test_dropping_clears_freeze_and_manual_and_undo_restores(
            self, setup):
        graph, node, stack = setup
        node.frozen, node.manual = True, True
        stack.push(SetDropOutputCommand(graph, node.id, True))
        assert (not node.drop_output, node.frozen, node.manual) == (
            False, False, False)
        stack.undo()
        assert (not node.drop_output, node.frozen, node.manual) == (
            True, True, True)

    @pytest.mark.parametrize("command, attr", [
        (SetFrozenCommand, "frozen"), (SetManualCommand, "manual")])
    def test_freeze_and_manual_stop_dropping(self, setup, command,
                                                    attr):
        graph, node, stack = setup
        graph.set_drop_output(node.id, True)
        stack.push(command(graph, node.id, True))
        assert getattr(node, attr) and not node.drop_output
        stack.undo()
        assert not getattr(node, attr) and node.drop_output


class TestCanvas:
    def test_badge_and_tooltip(self, qtbot, registry):
        from flograph.ui import theme
        from flograph.ui.canvas import NodeGraphScene
        graph = Graph()
        node = _node(DOUBLE)
        graph.add_node(node)
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        item = scene.node_items[node.id]
        assert not item._drop_badge.isVisible()
        graph.set_drop_output(node.id, True)
        assert item._drop_badge.isVisible()
        assert item._drop_badge.colour == theme.NODE_SUBTEXT
        assert "Drop Output is on" in item.toolTip()
        graph.set_released(node.id, True)
        assert item._drop_badge.colour == theme.status_color(NodeStatus.DONE)
        assert "output dropped" in item.toolTip()
        # a paragraph, so it is broken into lines rather than one long one
        assert item.toolTip().startswith("<qt>") and "<br>" in item.toolTip()
