"""Running fewer nodes at once when the machine is running out.

The point is not to be clever about memory — it is that "the tool got
slower" is an outcome anybody can live with, and "the tool froze my
computer" is not. A flow may be handed to someone who did not build it and
cannot act on advice about worker counts; a throttle needs them to
understand nothing at all.

Nothing here allocates anything. The engine's memory probe is swappable, so
any pressure can be simulated on a machine under none.
"""
import pytest

from flograph.core import Graph, NodeInstance
from flograph.core.node import NodeStatus
from flograph.core.script import parse_spec
from flograph.engine import pressure
from flograph.engine.scheduler import ExecutionEngine

GB = 1024 ** 3


def probe(total_gb, free_gb):
    total = total_gb * GB
    available = int(free_gb * GB)
    return lambda: (total - available, total, available)


CALM_BOX = probe(32, 20)        # plenty free
TIGHT_BOX = probe(32, 3)        # 90% used, 3 GB left
CRITICAL_BOX = probe(32, 0.5)   # half a gig left


def counting_node(type_id):
    return NodeInstance.create(parse_spec("""
NODE = {"label": "Work", "category": "Test",
        "inputs": [], "outputs": [("value", "any")]}
def run(ctx):
    return 1
""", type_id))


class TestWorkerCap:
    """The pure half — a table, no engine, no machine."""

    def test_calm_leaves_the_limit_alone(self):
        assert pressure.worker_cap(8, pressure.CALM) == 8

    def test_tight_halves_it(self):
        assert pressure.worker_cap(8, pressure.TIGHT) == 4

    def test_critical_runs_one_at_a_time(self):
        assert pressure.worker_cap(8, pressure.CRITICAL) == 1

    @pytest.mark.parametrize("base", [1, 2, 3, 8, 32])
    @pytest.mark.parametrize("level", [pressure.CALM, pressure.TIGHT,
                                       pressure.CRITICAL])
    def test_it_is_never_zero(self, base, level):
        """The defect this exists for. A limit of 0 is not "run slowly": the
        dispatch loop starts nothing, finds nothing running, decides the run
        is over and reports success having executed none of the plan."""
        assert pressure.worker_cap(base, level) >= 1

    def test_a_chosen_number_survives_a_merely_busy_machine(self):
        assert pressure.worker_cap(4, pressure.TIGHT, explicit=True) == 4

    def test_but_not_a_critical_one(self):
        assert pressure.worker_cap(4, pressure.CRITICAL, explicit=True) == 1


class TestPressureLevel:
    def test_a_big_machine_with_room_is_calm(self):
        assert pressure.pressure_level(12 * GB, 128 * GB, 116 * GB) == pressure.CALM

    def test_a_busy_small_machine_is_tight(self):
        assert pressure.pressure_level(29 * GB, 32 * GB, 3 * GB) == pressure.TIGHT

    def test_nearly_nothing_left_is_critical(self):
        assert pressure.pressure_level(
            31 * GB, 32 * GB, 512 * 1024 ** 2) == pressure.CRITICAL

    def test_critical_is_absolute_not_proportional(self):
        """A terabyte box with 400 MB left is in as much trouble as a laptop
        with 400 MB left, and its ratio does not say so."""
        total = 1024 * GB
        assert pressure.pressure_level(
            total - 400 * 1024 ** 2, total, 400 * 1024 ** 2) == pressure.CRITICAL

    def test_no_reading_is_calm_not_a_crash(self):
        assert pressure.pressure_level(0, 0, 0) == pressure.CALM

    def test_it_settles_rather_than_flapping(self):
        """Free memory wanders. Crossing back and forth must not re-decide
        the worker count every second."""
        total = 32 * GB
        level = pressure.CALM
        changes = 0
        for free_gb in (4.9, 4.7, 5.0, 4.6, 5.1, 4.8):
            new = pressure.pressure_level(
                total - int(free_gb * GB), total, int(free_gb * GB), level)
            if new != level:
                changes += 1
            level = new
        assert changes == 1


class TestTheEngineActuallyThrottles:
    def engine_for(self, graph, probe_fn):
        engine = ExecutionEngine(graph)
        engine.memory_adapt = True      # conftest turns it off suite-wide
        engine.memory_probe = probe_fn
        return engine

    def test_a_calm_machine_runs_the_full_width(self):
        engine = self.engine_for(Graph(), CALM_BOX)
        engine._poll_pressure()
        assert engine.worker_limit() == engine._base_workers()

    def test_a_tight_machine_runs_fewer(self):
        engine = self.engine_for(Graph(), TIGHT_BOX)
        engine._poll_pressure()
        assert engine.worker_limit() < engine._base_workers()
        assert engine.worker_limit() >= 1

    def test_a_critical_machine_runs_one(self):
        engine = self.engine_for(Graph(), CRITICAL_BOX)
        engine._poll_pressure()
        assert engine.worker_limit() == 1

    def test_a_chosen_worker_count_is_honoured_while_merely_busy(self):
        engine = self.engine_for(Graph(), TIGHT_BOX)
        engine.max_workers = 4
        engine._poll_pressure()
        assert engine.worker_limit() == 4

    def test_the_off_switch_works(self):
        engine = self.engine_for(Graph(), CRITICAL_BOX)
        engine.memory_adapt = False
        engine._poll_pressure()
        assert engine.worker_limit() == engine._base_workers()

    def test_a_broken_probe_does_not_throttle_or_raise(self):
        """A platform that will not report memory must not be read as a
        machine with none left — that would run everything one at a time
        forever, for no reason."""
        engine = self.engine_for(Graph(), lambda: (0, 0, 0))
        engine._poll_pressure()
        assert engine.worker_limit() == engine._base_workers()


class TestARunStillRuns:
    """The whole thing is worthless if throttling loses work."""

    def build(self, count=3):
        graph = Graph()
        for i in range(count):
            graph.add_node(counting_node(f"test.work{i}"))
        return graph

    def run(self, qtbot, engine):
        with qtbot.waitSignal(engine.run_finished, timeout=5000) as blocker:
            engine.run_all()
        return blocker.args[0]

    def test_every_node_runs_on_a_critical_machine(self, qtbot):
        graph = self.build()
        engine = ExecutionEngine(graph)
        engine.memory_adapt = True
        engine.memory_probe = CRITICAL_BOX

        assert self.run(qtbot, engine) is True
        assert all(n.status is NodeStatus.DONE for n in graph.nodes.values())
        assert all(engine.cache.has(nid) for nid in graph.nodes)

    def test_a_zero_limit_cannot_report_a_run_it_did_not_do(self, qtbot,
                                                            monkeypatch):
        """The regression test for the silent-success defect, forced directly
        rather than waiting for a policy that would produce it: with a limit
        of 0 the dispatch loop starts nothing, sees nothing running, and the
        tail of _dispatch concludes the run is finished — successfully."""
        monkeypatch.setattr(pressure, "worker_cap", lambda *a, **k: 0)
        graph = self.build()
        engine = ExecutionEngine(graph)
        engine.memory_adapt = True
        engine.memory_probe = CRITICAL_BOX

        assert engine.worker_limit() >= 1, "a limit of 0 must be impossible"
        assert self.run(qtbot, engine) is True
        assert all(n.status is NodeStatus.DONE for n in graph.nodes.values())
