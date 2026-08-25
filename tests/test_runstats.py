"""What a run cost: the record the engine keeps, and the arithmetic over it.

Covers the model (engine.runstats) and the engine's side of it — that a run
is recorded at all, that the nodes land in the order they ran with the right
outcomes, that what was skipped is accounted for, and that memory sampling
can be switched off without taking the rest of the record with it.
"""
import time

import pytest

from flograph.core import Graph, NodeRegistry
from flograph.engine.runstats import (HISTORY_LIMIT, NodeRun, ProcessSampler,
                                      RunHistory, RunRecord)
from flograph.engine.scheduler import ExecutionEngine, skipped_summary

SCRIPT = "flograph.scripting.python_script"
CONST = "flograph.util.constant"
REROUTE = "flograph.util.reroute"


def source(label, body, inputs="[]"):
    return (f'NODE = {{"label": "{label}", "category": "T", '
            f'"inputs": {inputs}, "outputs": [("result", "any")]}}\n{body}\n')


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def run(qtbot, engine):
    with qtbot.waitSignal(engine.run_finished, timeout=20000):
        engine.run_all()
    return engine.history.latest


@pytest.fixture
def flow(registry):
    """slow -> fast, plus one node that always fails."""
    graph = Graph()
    slow = graph.add_node(registry.instantiate(SCRIPT))
    graph.set_code(slow.id, source("Slow", (
        "import time\ndef run(ctx):\n    time.sleep(0.12)\n    return 1")))
    fast = graph.add_node(registry.instantiate(SCRIPT))
    graph.set_code(fast.id, source(
        "Fast", "def run(ctx, value):\n    return value + 1",
        inputs='[("value", "any")]'))
    bad = graph.add_node(registry.instantiate(SCRIPT))
    graph.set_code(bad.id, source(
        "Bad", "def run(ctx):\n    raise ValueError('nope')"))
    graph.connect(slow.id, "result", fast.id, "value")
    return graph, {"slow": slow, "fast": fast, "bad": bad}


class TestRecordArithmetic:
    def test_node_time_sums_the_nodes(self):
        record = RunRecord(nodes=[NodeRun("a", "A", wall_time=3.0),
                                  NodeRun("b", "B", wall_time=1.0)])
        assert record.node_time == 4.0

    def test_share_is_of_the_time_in_nodes(self):
        record = RunRecord(nodes=[NodeRun("a", "A", wall_time=3.0),
                                  NodeRun("b", "B", wall_time=1.0)])
        assert record.share(record.nodes[0]) == 0.75

    def test_share_of_an_instant_run_is_zero_not_an_error(self):
        record = RunRecord(nodes=[NodeRun("a", "A", wall_time=0.0)])
        assert record.share(record.nodes[0]) == 0.0

    def test_slowest_and_heaviest_rank_independently(self):
        record = RunRecord(nodes=[
            NodeRun("a", "A", wall_time=9.0, output_bytes=10),
            NodeRun("b", "B", wall_time=1.0, output_bytes=999),
        ])
        assert [n.label for n in record.slowest(1)] == ["A"]
        assert [n.label for n in record.heaviest(1)] == ["B"]

    def test_rss_growth_can_be_negative(self):
        """A node that releases a large intermediate ends smaller than it
        started, and saying so is more useful than clamping it to zero."""
        node = NodeRun("a", "A", rss_start=500, rss_peak=300)
        assert node.rss_growth == -200

    def test_rss_growth_is_zero_when_never_sampled(self):
        assert NodeRun("a", "A", rss_start=500, rss_peak=0).rss_growth == 0

    def test_peak_growth_never_goes_below_zero(self):
        assert RunRecord(rss_start=900, rss_peak=100).peak_growth == 0

    def test_failed_collects_only_failures(self):
        record = RunRecord(nodes=[NodeRun("a", "A", outcome="ok"),
                                  NodeRun("b", "B", outcome="failed"),
                                  NodeRun("c", "C", outcome="cancelled")])
        assert [n.label for n in record.failed] == ["B"]


class TestHistory:
    def test_keeps_the_newest_and_drops_the_rest(self):
        history = RunHistory(limit=3)
        for i in range(5):
            history.add(RunRecord(wall_time=i))
        assert [r.wall_time for r in history.all()] == [4, 3, 2]

    def test_all_is_newest_first(self):
        history = RunHistory()
        first, second = RunRecord(wall_time=1), RunRecord(wall_time=2)
        history.add(first)
        history.add(second)
        assert history.all() == [second, first]
        assert history.latest is second

    def test_latest_of_an_empty_history_is_none(self):
        assert RunHistory().latest is None

    def test_shrinking_the_limit_keeps_the_newest(self):
        history = RunHistory(limit=10)
        for i in range(6):
            history.add(RunRecord(wall_time=i))
        history.set_limit(2)
        assert [r.wall_time for r in history.all()] == [5, 4]

    def test_growing_the_limit_keeps_everything(self):
        history = RunHistory(limit=2)
        for i in range(3):
            history.add(RunRecord(wall_time=i))
        history.set_limit(5)
        history.add(RunRecord(wall_time=9))
        assert len(history) == 3

    def test_the_default_limit_is_the_documented_one(self):
        history = RunHistory()
        for i in range(HISTORY_LIMIT + 5):
            history.add(RunRecord())
        assert len(history) == HISTORY_LIMIT


class TestSampler:
    def test_reads_a_plausible_resident_size(self):
        assert ProcessSampler().rss() > 1_000_000

    def test_a_broken_sampler_answers_zero_forever(self):
        sampler = ProcessSampler()
        sampler._broken = True
        assert sampler.rss() == 0


class TestEngineRecords:
    def test_a_run_is_recorded(self, qtbot, flow):
        graph, _ = flow
        engine = ExecutionEngine(graph)
        record = run(qtbot, engine)
        assert record is not None
        assert len(engine.history) == 1

    def test_nodes_appear_in_the_order_they_ran(self, qtbot, flow):
        graph, n = flow
        engine = ExecutionEngine(graph)
        record = run(qtbot, engine)
        order = [x.node_id for x in record.nodes]
        assert order.index(n["slow"].id) < order.index(n["fast"].id)

    def test_a_failure_is_recorded_rather_than_dropped(self, qtbot, flow):
        graph, n = flow
        engine = ExecutionEngine(graph)
        record = run(qtbot, engine)
        assert [x.label for x in record.failed] == ["Bad"]
        assert record.ok is False

    def test_timings_and_output_sizes_are_captured(self, qtbot, flow):
        graph, n = flow
        engine = ExecutionEngine(graph)
        record = run(qtbot, engine)
        slow = next(x for x in record.nodes if x.node_id == n["slow"].id)
        assert slow.wall_time >= 0.1
        assert slow.output_bytes > 0
        assert slow.summary                      # "int · 1", etc.

    def test_started_offsets_are_monotonic(self, qtbot, flow):
        graph, _ = flow
        engine = ExecutionEngine(graph)
        record = run(qtbot, engine)
        offsets = [x.started for x in record.nodes]
        assert offsets == sorted(offsets)
        assert offsets[0] >= 0

    def test_wall_time_covers_the_whole_run(self, qtbot, flow):
        graph, _ = flow
        engine = ExecutionEngine(graph)
        record = run(qtbot, engine)
        assert record.wall_time >= record.node_time

    def test_a_second_run_records_what_it_skipped(self, qtbot, flow):
        graph, _ = flow
        engine = ExecutionEngine(graph)
        run(qtbot, engine)
        record = run(qtbot, engine)      # only the failing node is still dirty
        assert record.skipped_clean == 2
        assert len(engine.history) == 2

    def test_a_frozen_node_is_counted_as_frozen(self, qtbot, flow):
        graph, n = flow
        engine = ExecutionEngine(graph)
        run(qtbot, engine)
        graph.set_frozen(n["slow"].id, True)
        graph.mark_dirty(n["slow"].id)
        record = run(qtbot, engine)
        assert record.skipped_frozen == 1

    def test_a_deactivated_branch_is_counted_as_deactivated(self, qtbot, flow):
        graph, n = flow
        engine = ExecutionEngine(graph)
        graph.set_active(n["slow"].id, False)
        record = run(qtbot, engine)
        # the node itself and everything below it
        assert record.skipped_inactive == 2

    def test_run_recorded_fires_with_the_record(self, qtbot, flow):
        graph, _ = flow
        engine = ExecutionEngine(graph)
        seen = []
        engine.run_recorded.connect(seen.append)
        record = run(qtbot, engine)
        assert seen == [record]

    def test_nothing_to_run_records_nothing(self, qtbot, flow):
        graph, _ = flow
        engine = ExecutionEngine(graph)
        run(qtbot, engine)
        for node in graph.nodes.values():
            graph.mark_clean(node.id)
        engine.run_all()                 # returns immediately, no signal
        assert len(engine.history) == 1

    def test_sampling_can_be_switched_off(self, qtbot, flow):
        graph, _ = flow
        engine = ExecutionEngine(graph)
        engine.sampling_enabled = False
        record = run(qtbot, engine)
        assert record.nodes                       # still recorded
        assert all(x.rss_peak == x.rss_start for x in record.nodes)

    def test_sampling_catches_a_held_allocation(self, qtbot, registry):
        """The point of sampling: a node whose output is tiny but which held
        something enormous while it ran."""
        graph = Graph()
        node = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(node.id, source("Spike", """
import time
def run(ctx):
    hog = bytearray(220 * 1024 * 1024)
    time.sleep(0.4)
    total = len(hog)
    del hog
    return total
"""))
        engine = ExecutionEngine(graph)
        record = run(qtbot, engine)
        spike = record.nodes[0]
        assert spike.output_bytes < 1000          # it returned an int
        assert spike.rss_growth > 100 * 1024 ** 2  # but it cost far more


class TestSkippedSummary:
    def test_an_untouched_graph_skips_nothing(self, registry):
        graph = Graph()
        node = graph.add_node(registry.instantiate(CONST))
        clean, frozen, inactive, manual = skipped_summary(
            graph, [node.id], None, [node.id])
        assert (clean, frozen, inactive, manual) == (0, 0, 0, 0)

    def test_a_node_out_of_the_plan_counts_as_clean(self, registry):
        graph = Graph()
        node = graph.add_node(registry.instantiate(CONST))
        assert skipped_summary(graph, [node.id], None, []) == (1, 0, 0, 0)

    def test_deactivation_carries_its_descendants(self, registry):
        graph = Graph()
        const = graph.add_node(registry.instantiate(CONST))
        dot = graph.add_node(registry.instantiate(REROUTE))
        graph.connect(const.id, "value", dot.id, "value")
        graph.set_active(const.id, False)
        assert skipped_summary(graph, [dot.id], None, []) == (0, 0, 2, 0)

    def test_only_the_targets_ancestry_is_considered(self, registry):
        """Running one node must not report every unrelated node in the
        project as something it skipped."""
        graph = Graph()
        wanted = graph.add_node(registry.instantiate(CONST))
        graph.add_node(registry.instantiate(CONST))     # elsewhere entirely
        assert skipped_summary(
            graph, [wanted.id], None, [wanted.id]) == (0, 0, 0, 0)
