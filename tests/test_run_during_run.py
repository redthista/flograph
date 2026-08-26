"""A manual run landing while another is in flight (J3). It used to be a
silent no-op — the click did nothing, nothing said so. Its nodes now join
the plan in flight: independent branches run alongside on the pool, and a
joined node with ancestors still to finish simply waits for them, exactly
as it would have had it been planned with the run at the start."""
import pytest

from flograph.core import Graph, NodeInstance, NodeStatus, parse_spec
from flograph.engine import ExecutionEngine

SLOW = """
NODE = {
    "label": "Slow",
    "category": "Test",
    "inputs": [],
    "outputs": [("value", "any")],
}
PARAMS = [{"name": "hold", "type": "float", "default": 0.05}]
def run(ctx):
    import time
    time.sleep(float(ctx.params["hold"]))
    return 1
"""

FAST = """
NODE = {
    "label": "Fast",
    "category": "Test",
    "inputs": [],
    "outputs": [("value", "any")],
}
def run(ctx):
    return 1
"""

PASS_THROUGH = """
NODE = {
    "label": "Pass",
    "category": "Test",
    "inputs": [("value", "any")],
    "outputs": [("value", "any")],
}
def run(ctx, value):
    return value
"""

PATIENT = """
NODE = {
    "label": "Patient",
    "category": "Test",
    "inputs": [],
    "outputs": [("value", "any")],
}
def run(ctx):
    import time
    for _ in range(2000):
        ctx.check_cancelled()
        time.sleep(0.005)
    return 1
"""


def add(graph: Graph, source: str, type_id: str, **params) -> NodeInstance:
    node = NodeInstance.create(parse_spec(source, type_id))
    node.params.update(params)
    graph.add_node(node)
    return node


def wire(graph: Graph, src: NodeInstance, dst: NodeInstance) -> None:
    graph.connect(src.id, "value", dst.id, "value")


@pytest.fixture
def busy(qtbot):
    """An engine with one slow node already running, and two independent
    bystanders."""
    graph = Graph()
    slow = add(graph, SLOW, "test.slow", hold=0.4)
    fast = add(graph, FAST, "test.fast")
    other = add(graph, FAST, "test.other")
    engine = ExecutionEngine(graph)
    engine.max_workers = 4
    engine.run_targets([slow.id])
    assert engine.active
    assert graph.nodes[slow.id].status is NodeStatus.RUNNING
    yield graph, engine, slow, fast, other


class TestJoiningARun:
    def test_an_independent_branch_runs_alongside(self, qtbot, busy):
        """The point of the pool: a second click does not queue behind the
        first run, it shares it."""
        graph, engine, slow, fast, _other = busy
        engine.run_targets([fast.id])
        assert graph.nodes[fast.id].status is NodeStatus.RUNNING
        assert graph.nodes[slow.id].status is NodeStatus.RUNNING

        finishes = []
        engine.run_finished.connect(lambda ok: finishes.append(ok))
        qtbot.waitUntil(lambda: len(finishes) >= 1, timeout=15000)
        assert graph.nodes[fast.id].status is NodeStatus.DONE
        assert graph.nodes[slow.id].status is NodeStatus.DONE
        assert not engine.active

    def test_a_joined_node_waits_for_its_in_flight_ancestor(self, qtbot):
        """Sharing the floor is for independent work. Downstream of a node
        still running, joining means waiting on it — the same Kahn
        bookkeeping a planned node would have had."""
        graph = Graph()
        slow = add(graph, SLOW, "test.slow", hold=0.4)
        after = add(graph, PASS_THROUGH, "test.after")
        wire(graph, slow, after)
        engine = ExecutionEngine(graph)
        engine.max_workers = 4
        engine.run_targets([slow.id])
        assert graph.nodes[slow.id].status is NodeStatus.RUNNING

        engine.run_targets([after.id])
        assert graph.nodes[after.id].status is NodeStatus.QUEUED
        assert graph.nodes[slow.id].status is NodeStatus.RUNNING

        finishes = []
        engine.run_finished.connect(lambda ok: finishes.append(ok))
        qtbot.waitUntil(lambda: len(finishes) >= 1, timeout=15000)
        assert graph.nodes[after.id].status is NodeStatus.DONE
        assert graph.nodes[slow.id].status is NodeStatus.DONE

    def test_what_is_already_running_is_not_replanned(self, qtbot, busy):
        graph, engine, slow, _fast, _other = busy
        joined = []
        engine.run_joined.connect(joined.append)
        total = engine._plan_total
        engine.run_targets([slow.id])       # the very node in flight
        assert joined == []
        assert engine._plan_total == total

    def test_the_join_is_announced(self, qtbot, busy):
        graph, engine, _slow, fast, _other = busy
        joined = []
        engine.run_joined.connect(joined.append)
        engine.run_targets([fast.id])
        assert joined == [[fast.id]]

    def test_joined_starts_report_the_extended_total(self, qtbot, busy):
        """The total grows as joins land, and each start reports the total
        as it stands when that node starts — an upper bound that moves is
        the honest version of one that lies."""
        graph, engine, _slow, fast, other = busy
        seen = []
        engine.node_started.connect(
            lambda nid, index, total: seen.append((nid, total)))
        engine.run_targets([fast.id])
        engine.run_targets([other.id])
        qtbot.waitUntil(
            lambda: graph.nodes[other.id].status is NodeStatus.DONE,
            timeout=15000)
        totals = {nid: total for nid, total in seen}
        assert totals[fast.id] == 2     # slow was in flight, fast joined
        assert totals[other.id] == 3    # other joined after fast

    def test_cancel_takes_joined_nodes_back_off(self, qtbot):
        """Stop means stop: joined nodes leave the plan like planned ones,
        and a joined node still running stops at its next checkpoint."""
        graph = Graph()
        patient = add(graph, PATIENT, "test.patient")
        joiner = add(graph, PATIENT, "test.joiner")
        engine = ExecutionEngine(graph)
        engine.max_workers = 2
        engine.run_targets([patient.id])
        engine.run_targets([joiner.id])
        assert graph.nodes[joiner.id].status is NodeStatus.RUNNING
        with qtbot.waitSignal(engine.run_finished, timeout=15000):
            engine.cancel()
        qtbot.wait(200)
        assert not engine.active
        assert graph.nodes[joiner.id].status is not NodeStatus.DONE

    def test_reactive_survival_still_works_alongside(self, qtbot, busy):
        """The reactive path waits out a run and fires after; joining must
        not have taken that turn away from it."""
        graph, engine, _slow, fast, _other = busy
        engine.request_run([fast.id])
        qtbot.waitUntil(
            lambda: graph.nodes[fast.id].status is NodeStatus.DONE,
            timeout=15000)
