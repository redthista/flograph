"""Concurrent execution: several nodes in flight, and what must stay true
while they are.

The rendezvous nodes below are the load-bearing trick. A node writes a marker
file, waits for its peers' markers to appear, and fails if they never do —
so the run can only succeed if the nodes really were running at the same
time. Timing is not asserted anywhere: a sleep long enough to "prove"
overlap on an idle machine proves nothing on a busy one, and a test that
measures wall clocks fails for reasons that have nothing to do with the
scheduler.
"""
import pytest

from flograph.core import Graph, NodeInstance, NodeStatus, parse_spec
from flograph.engine import ExecutionEngine

# Writes its marker and waits for the others to appear.
#
# The marker is removed only when the wait *fails*, and that asymmetry is the
# whole design. Removing it on success too would race: the first node to spot
# its peer would take its own marker away again before the second node looked,
# so neither could reliably finish. Leaving it on failure would be worse in
# the other direction — a serial run's timed-out node would leave a marker
# behind for the next one to find, and the negative control would pass on a
# meeting that never happened.
RENDEZVOUS = """
NODE = {
    "label": "Rendezvous",
    "category": "Test",
    "inputs": [],
    "outputs": [("value", "any")],
}
PARAMS = [
    {"name": "dir", "type": "string", "default": ""},
    {"name": "peers", "type": "int", "default": 2},
    {"name": "timeout", "type": "float", "default": 10.0},
    {"name": "chatter", "type": "int", "default": 0},
]
def run(ctx):
    import pathlib, time
    folder = pathlib.Path(ctx.params["dir"])
    marker = folder / (ctx.node_id + ".here")
    marker.write_text("here")
    deadline = time.monotonic() + float(ctx.params["timeout"])
    while time.monotonic() < deadline:
        if len(list(folder.glob("*.here"))) >= int(ctx.params["peers"]):
            for _ in range(int(ctx.params["chatter"])):
                print(ctx.node_id)
                time.sleep(0.001)
            return 1
        time.sleep(0.005)
    marker.unlink(missing_ok=True)
    raise RuntimeError("no peer arrived - these nodes did not overlap")
"""

# Announces itself on the way in and out, for the tests that care about who
# was on the floor when.
MARKED = """
NODE = {
    "label": "Marked",
    "category": "Test",
    "inputs": [("value", "any", {"optional": True})],
    "outputs": [("value", "any")],
}
PARAMS = [{"name": "hold", "type": "float", "default": 0.05}]
def run(ctx, value=None):
    import time
    ctx.log("enter")
    time.sleep(float(ctx.params["hold"]))
    ctx.log("leave")
    return (value or 0) + 1
"""

EXCLUSIVE = """
NODE = {
    "label": "Exclusive",
    "category": "Test",
    "inputs": [],
    "outputs": [("value", "any")],
    "exclusive": True,
}
PARAMS = [{"name": "hold", "type": "float", "default": 0.05}]
def run(ctx):
    import time
    ctx.log("enter")
    time.sleep(float(ctx.params["hold"]))
    ctx.log("leave")
    return 1
"""

BOOM = """
NODE = {
    "label": "Boom",
    "category": "Test",
    "inputs": [],
    "outputs": [("value", "any")],
}
def run(ctx):
    raise ValueError("boom")
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


def wait_run(qtbot, engine, trigger, timeout=30000):
    with qtbot.waitSignal(engine.run_finished, timeout=timeout) as blocker:
        trigger()
    return blocker.args[0]  # ok


class TestNodesReallyOverlap:
    def test_independent_nodes_run_at_the_same_time(self, qtbot, tmp_path):
        graph = Graph()
        for i in range(2):
            add(graph, RENDEZVOUS, f"test.rv{i}", dir=str(tmp_path), peers=2)
        engine = ExecutionEngine(graph)
        engine.max_workers = 4      # not auto: a single-core box would be 1

        problems = []
        engine.node_failed.connect(
            lambda nid, err: problems.append(err.message))
        assert wait_run(qtbot, engine, engine.run_all), problems
        assert all(n.status is NodeStatus.DONE for n in graph.nodes.values())

    def test_one_worker_still_runs_them_one_at_a_time(self, qtbot, tmp_path):
        """The negative control. Same graph, same nodes — with a single
        worker neither can ever meet the other, so both must fail. Without
        this, the test above would pass on a scheduler that had quietly
        stopped being concurrent."""
        graph = Graph()
        for i in range(2):
            add(graph, RENDEZVOUS, f"test.rv{i}", dir=str(tmp_path), peers=2,
                timeout=0.4)
        engine = ExecutionEngine(graph)
        engine.max_workers = 1

        assert not wait_run(qtbot, engine, engine.run_all)
        assert all(n.status is NodeStatus.ERROR for n in graph.nodes.values())

    def test_the_worker_limit_is_respected(self, qtbot, tmp_path):
        """Three nodes, two workers: the third waits. It also proves the
        limit is a limit and not a target — nobody starts a fourth."""
        graph = Graph()
        for i in range(3):
            add(graph, MARKED, f"test.m{i}", hold=0.05)
        engine = ExecutionEngine(graph)
        engine.max_workers = 2

        seen = []
        engine.node_started.connect(
            lambda *_: seen.append(len(engine.running_nodes)))
        assert wait_run(qtbot, engine, engine.run_all)
        assert max(seen) <= 2
        assert len(seen) == 3


class TestDependenciesStillHold:
    def test_a_chain_runs_in_order_however_many_workers(self, qtbot):
        graph = Graph()
        a = add(graph, MARKED, "test.a")
        b = add(graph, MARKED, "test.b")
        c = add(graph, MARKED, "test.c")
        graph.connect(a.id, "value", b.id, "value")
        graph.connect(b.id, "value", c.id, "value")
        engine = ExecutionEngine(graph)
        engine.max_workers = 8

        events = []
        engine.node_log.connect(
            lambda nid, line, stream: events.append((nid, line)))
        assert wait_run(qtbot, engine, engine.run_all)

        # Each link waits for the one before it: nothing enters before its
        # predecessor has left.
        assert events.index((b.id, "enter")) > events.index((a.id, "leave"))
        assert events.index((c.id, "enter")) > events.index((b.id, "leave"))
        # and the values really were threaded through, not run on stale input
        assert engine.cache.outputs_for(c.id)["value"] == 3

    def test_a_node_never_starts_beside_its_own_ancestor(self, qtbot):
        graph = Graph()
        a = add(graph, MARKED, "test.a")
        b = add(graph, MARKED, "test.b")
        graph.connect(a.id, "value", b.id, "value")
        engine = ExecutionEngine(graph)
        engine.max_workers = 8

        overlaps = []
        engine.node_started.connect(
            lambda nid, *_: overlaps.append((nid, engine.running_nodes)))
        assert wait_run(qtbot, engine, engine.run_all)
        started_with = dict(overlaps)
        assert a.id not in started_with[b.id] - {b.id}


class TestExclusiveNodes:
    def test_an_exclusive_node_has_the_floor_to_itself(self, qtbot):
        graph = Graph()
        # Two ahead of it and two behind, so it is reached with work already
        # in flight and with more waiting — the case where the barrier has to
        # do something.
        add(graph, MARKED, "test.before0", hold=0.05)
        add(graph, MARKED, "test.before1", hold=0.05)
        alone = add(graph, EXCLUSIVE, "test.alone", hold=0.05)
        add(graph, MARKED, "test.after0", hold=0.05)
        add(graph, MARKED, "test.after1", hold=0.05)
        engine = ExecutionEngine(graph)
        engine.max_workers = 4

        snapshots = []
        engine.node_started.connect(
            lambda nid, *_: snapshots.append(engine.running_nodes))
        assert wait_run(qtbot, engine, engine.run_all)

        # It never started beside anyone...
        for running in snapshots:
            if alone.id in running:
                assert running == frozenset({alone.id})
        # ...and nobody started beside it.
        assert not any(alone.id in running and len(running) > 1
                       for running in snapshots)
        # The others did overlap, or the graph proved nothing.
        assert max(len(running) for running in snapshots) > 1

    def test_an_instance_can_opt_out_of_its_script(self, qtbot):
        """A node whose code says exclusive, told otherwise on the canvas."""
        graph = Graph()
        first = add(graph, EXCLUSIVE, "test.x0", hold=0.05)
        second = add(graph, EXCLUSIVE, "test.x1", hold=0.05)
        for node in (first, second):
            node.exclusive_override = False
        engine = ExecutionEngine(graph)
        engine.max_workers = 4

        snapshots = []
        engine.node_started.connect(
            lambda nid, *_: snapshots.append(engine.running_nodes))
        assert wait_run(qtbot, engine, engine.run_all)
        assert max(len(running) for running in snapshots) == 2

    def test_an_instance_can_opt_in(self, qtbot):
        graph = Graph()
        add(graph, MARKED, "test.m0", hold=0.05)
        alone = add(graph, MARKED, "test.m1", hold=0.05)
        add(graph, MARKED, "test.m2", hold=0.05)
        alone.exclusive_override = True
        engine = ExecutionEngine(graph)
        engine.max_workers = 4

        snapshots = []
        engine.node_started.connect(
            lambda nid, *_: snapshots.append(engine.running_nodes))
        assert wait_run(qtbot, engine, engine.run_all)
        assert not any(alone.id in running and len(running) > 1
                       for running in snapshots)


class TestFailureAndCancellation:
    def test_a_failure_prunes_its_own_branch_and_leaves_the_rest(self, qtbot):
        graph = Graph()
        boom = add(graph, BOOM, "test.boom")
        after = add(graph, MARKED, "test.after")
        graph.connect(boom.id, "value", after.id, "value")
        bystander = add(graph, MARKED, "test.bystander")
        engine = ExecutionEngine(graph)
        engine.max_workers = 4

        assert not wait_run(qtbot, engine, engine.run_all)
        assert graph.node(boom.id).status is NodeStatus.ERROR
        assert graph.node(after.id).status is NodeStatus.IDLE
        # The branch that had nothing to do with it still ran to completion.
        assert graph.node(bystander.id).status is NodeStatus.DONE
        assert engine.cache.has(bystander.id)

    def test_cancel_stops_every_node_in_flight(self, qtbot):
        graph = Graph()
        for i in range(3):
            add(graph, PATIENT, f"test.p{i}")
        engine = ExecutionEngine(graph)
        engine.max_workers = 3

        def trigger():
            engine.run_all()
            # Every worker is dispatched before control returns, so by here
            # all three are on the floor.
            assert len(engine.running_nodes) == 3
            engine.cancel()

        wait_run(qtbot, engine, trigger)
        assert not engine.running_nodes
        assert not engine.active
        assert not any(n.status is NodeStatus.RUNNING
                       for n in graph.nodes.values())

    def test_the_engine_is_reusable_after_a_concurrent_run(self, qtbot):
        graph = Graph()
        for i in range(3):
            add(graph, MARKED, f"test.m{i}", hold=0.01)
        engine = ExecutionEngine(graph)
        engine.max_workers = 3

        assert wait_run(qtbot, engine, engine.run_all)
        for node in graph.nodes.values():
            graph.mark_dirty(node.id)
        assert wait_run(qtbot, engine, engine.run_all)
        assert all(n.status is NodeStatus.DONE for n in graph.nodes.values())


class TestOutputIsNotCrossWired:
    def test_each_print_reaches_the_node_that_printed_it(self, qtbot, tmp_path):
        """`print()` rebinds a process-wide stream, so two nodes printing at
        once are exactly where output goes to the wrong node. The rendezvous
        guarantees they overlap while doing it."""
        graph = Graph()
        for i in range(3):
            add(graph, RENDEZVOUS, f"test.rv{i}", dir=str(tmp_path), peers=3,
                chatter=40)
        engine = ExecutionEngine(graph)
        engine.max_workers = 4

        lines = []
        engine.node_log.connect(
            lambda nid, line, stream: lines.append((nid, line, stream)))
        assert wait_run(qtbot, engine, engine.run_all)

        printed = [(nid, line) for nid, line, stream in lines
                   if stream == "stdout"]
        assert len(printed) == 3 * 40
        # each node printed its own id, so anything misrouted shows up here
        assert all(nid == line for nid, line in printed)


class TestTheBundledExample:
    """12_parallel_branches exists to show branches overlapping. If it ever
    stops doing that it is still a flow that runs and every other test would
    still pass, while the one thing it is for had quietly gone."""

    def test_it_actually_runs_its_branches_together(self, qtbot):
        import importlib.resources

        from flograph.core import NodeRegistry, serialization

        registry = NodeRegistry()
        registry.load_builtins()
        path = (importlib.resources.files("flograph.templates")
                / "12_parallel_branches.flograph")
        graph = serialization.load(str(path), registry)
        engine = ExecutionEngine(graph)
        engine.max_workers = 6

        assert wait_run(qtbot, engine, engine.run_all)
        record = engine.history.latest
        # Six independent branches: every one of them should get a worker.
        assert record.peak_concurrency == 6
        assert record.overlap > 0
        # and the chain inside a branch still held
        assert record.wall_time < record.node_time


class TestRunStatistics:
    def test_a_concurrent_run_records_what_it_overlapped(self, qtbot, tmp_path):
        graph = Graph()
        for i in range(2):
            add(graph, RENDEZVOUS, f"test.rv{i}", dir=str(tmp_path), peers=2)
        engine = ExecutionEngine(graph)
        engine.max_workers = 4

        assert wait_run(qtbot, engine, engine.run_all)
        record = engine.history.latest
        assert record is not None
        assert record.peak_concurrency == 2
        assert all(run.concurrent == 2 for run in record.nodes)
        # Their recorded windows intersect — which they must, since neither
        # could return until it had seen the other. Not a wall-clock
        # assertion: the rendezvous is what makes the overlap certain, and
        # this only checks the record kept an honest note of it.
        first, second = record.nodes
        assert second.started < first.finished
        assert first.started < second.finished

    def test_a_serial_run_reports_no_overlap(self, qtbot):
        graph = Graph()
        a = add(graph, MARKED, "test.a")
        b = add(graph, MARKED, "test.b")
        graph.connect(a.id, "value", b.id, "value")
        engine = ExecutionEngine(graph)
        engine.max_workers = 4

        assert wait_run(qtbot, engine, engine.run_all)
        record = engine.history.latest
        assert record.peak_concurrency == 1
        assert record.overlap == 0
        # a chain is recorded in the order it ran
        assert [run.node_id for run in record.nodes] == [a.id, b.id]
