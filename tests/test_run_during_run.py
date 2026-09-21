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


# Waits on a gate file, then answers with its own param — so a test can hold
# a node mid-run, change what it was asked, and let it finish.
GATED = """
NODE = {
    "label": "Gated",
    "category": "Test",
    "inputs": [],
    "outputs": [("value", "any")],
}
PARAMS = [
    {"name": "pick", "type": "string", "default": "A"},
    {"name": "gate", "type": "string", "default": ""},
]
def run(ctx):
    import pathlib, time
    gate = pathlib.Path(ctx.params["gate"])
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not gate.exists():
        time.sleep(0.005)
    return ctx.params["pick"]
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


class TestAnEditWhileTheRunIsGoing:
    """Dan: "often when quickly changing filters when the model is running
    it doesn't filter correctly."

    Marking a node clean is a claim — *this cached value is what these
    params produce*. A node dispatched with the filter on April and
    finishing after the slicer moved to May has not earned it. The re-run
    the change asked for is deferred until the run in flight ends, and by
    then `build_plan` skips the node for being clean: the chart keeps
    April's numbers, nothing is dirty, and nothing says so.
    """

    def _held(self, qtbot, tmp_path, chain=False):
        """A node held mid-run with its param changed under it, as a slicer
        tick does. Returns once the gate is open and it can finish."""
        gate = tmp_path / "go"
        graph = Graph()
        node = add(graph, GATED, "test.gated", pick="A", gate=str(gate))
        below = add(graph, PASS_THROUGH, "test.pass") if chain else None
        if below is not None:
            wire(graph, node, below)
        engine = ExecutionEngine(graph)
        engine.max_workers = 4
        engine.run_all()
        qtbot.waitUntil(
            lambda: graph.nodes[node.id].status is NodeStatus.RUNNING,
            timeout=15000)
        # the slicer tick: set the param, dirty the subgraph, ask again
        graph.set_param(node.id, "pick", "B")
        graph.mark_dirty(node.id)
        engine.request_run([node.id, *graph.downstream(node.id)])
        gate.write_text("go")
        return graph, engine, node, below

    def _settle(self, qtbot, engine):
        qtbot.waitUntil(lambda: not engine.active and not engine.pending_request,
                        timeout=20000)

    def test_the_node_is_not_marked_clean(self, qtbot, tmp_path):
        graph, engine, node, _ = self._held(qtbot, tmp_path)
        finished = []
        engine.run_finished.connect(
            lambda ok: finished.append(graph.nodes[node.id].dirty))
        qtbot.waitUntil(lambda: bool(finished), timeout=15000)
        assert finished[0] is True

    def test_and_the_deferred_re_run_answers_the_new_question(
            self, qtbot, tmp_path):
        """The whole point: the value ends up matching the param."""
        graph, engine, node, _ = self._held(qtbot, tmp_path)
        self._settle(qtbot, engine)
        assert graph.nodes[node.id].params["pick"] == "B"
        assert engine.cache.outputs_for(node.id)["value"] == "B"
        assert graph.nodes[node.id].dirty is False

    def test_the_stale_result_is_still_cached_on_the_way_past(
            self, qtbot, tmp_path):
        """The nodes below it in this run have to read *something*, and the
        honest something is what its inputs actually produced."""
        graph, engine, node, _ = self._held(qtbot, tmp_path)
        seen = []
        engine.run_finished.connect(
            lambda ok: seen.append(engine.cache.outputs_for(node.id)
                                   .get("value")))
        qtbot.waitUntil(lambda: bool(seen), timeout=15000)
        assert seen[0] == "A"

    def test_a_node_below_a_stale_one_is_left_dirty_too(self, qtbot,
                                                        tmp_path):
        """Staleness walks down the branch as each node completes. Without
        that, the filter re-runs and the chart under it does not."""
        graph, engine, node, below = self._held(qtbot, tmp_path, chain=True)
        finished = []
        engine.run_finished.connect(
            lambda ok: finished.append(graph.nodes[below.id].dirty))
        qtbot.waitUntil(lambda: bool(finished), timeout=15000)
        assert finished[0] is True
        self._settle(qtbot, engine)
        assert engine.cache.outputs_for(below.id)["value"] == "B"
        # and both are clean again afterwards: staleness belongs to the run
        # it happened in, so a set that outlived it would leave everything
        # downstream of that node dirty for the rest of the session
        assert graph.nodes[node.id].dirty is False
        assert graph.nodes[below.id].dirty is False

    def test_an_untouched_node_is_still_marked_clean(self, qtbot, tmp_path):
        """The negative control. Nothing changed under this one, so it has
        earned its claim and must not be left dirty to run for ever."""
        gate = tmp_path / "go"
        gate.write_text("go")
        graph = Graph()
        node = add(graph, GATED, "test.gated", pick="A", gate=str(gate))
        engine = ExecutionEngine(graph)
        with qtbot.waitSignal(engine.run_finished, timeout=15000):
            engine.run_all()
        assert graph.nodes[node.id].dirty is False
        assert engine.cache.outputs_for(node.id)["value"] == "A"

