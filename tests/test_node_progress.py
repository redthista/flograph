"""ctx.progress() end to end: throttling in the run context, the engine
putting a fraction on the model, and the model keeping it out of the file."""
import json

from flograph.core import Graph, NodeInstance, NodeStatus, parse_spec
from flograph.core.registry import NodeRegistry
from flograph.core.serialization import graph_to_dict, graph_from_dict
from flograph.engine import ExecutionEngine
from flograph.engine.context import (
    PROGRESS_MIN_INTERVAL, CancellationToken, RunContext,
)


def make_context():
    """A RunContext whose progress emits land in a list."""
    seen: list[float] = []
    ctx = RunContext(
        node_id="n1", params={}, token=CancellationToken(),
        log=lambda *a: None, progress=lambda nid, f: seen.append(f),
    )
    return ctx, seen


# ------------------------------------------------------------- throttling

def test_progress_is_throttled_but_always_lands_the_finish():
    ctx, seen = make_context()
    for i in range(1000):
        ctx.progress(i / 1000)
    ctx.progress(1.0)
    # a percentage point apart at most, so ~100 of the 1000 get through
    assert 1 < len(seen) <= 102
    assert seen[0] == 0.0     # the first call is never suppressed
    assert seen[-1] == 1.0    # and neither is the finish


def test_progress_clamps_and_ignores_a_repeated_finish():
    ctx, seen = make_context()
    ctx.progress(-5)
    ctx.progress(17)
    ctx.progress(1.0)
    assert seen == [0.0, 1.0]


def test_a_slow_drip_still_ticks_on_the_time_branch(monkeypatch):
    """Increments below the step threshold would otherwise never show."""
    ctx, seen = make_context()
    clock = [1000.0]
    monkeypatch.setattr("flograph.engine.context.time.monotonic",
                        lambda: clock[0])
    ctx.progress(0.5)
    ctx.progress(0.5001)          # too small, too soon
    assert seen == [0.5]
    clock[0] += PROGRESS_MIN_INTERVAL + 0.01
    ctx.progress(0.5002)          # still tiny, but long enough ago
    assert seen == [0.5, 0.5002]


def test_a_loop_that_restarts_its_count_is_not_frozen():
    """Distance, not advance: a ring stuck at the old high-water mark while
    a second pass runs underneath it would read as hung."""
    ctx, seen = make_context()
    ctx.progress(0.9)
    ctx.progress(0.1)
    assert seen == [0.9, 0.1]


def test_progress_without_a_sink_is_a_no_op():
    ctx = RunContext(node_id="n1", params={}, token=CancellationToken(),
                     log=lambda *a: None)
    ctx.progress(0.5)  # headless / direct run() calls must not blow up


# ------------------------------------------------------------------ engine

REPORTER = """
NODE = {"label": "Reporter", "category": "Test",
        "inputs": [], "outputs": [("value", "any")]}
def run(ctx):
    for i in range(10):
        ctx.progress(i / 10)
    return 1
"""


def test_engine_puts_progress_on_the_model_and_clears_it(qtbot):
    graph = Graph()
    node = graph.add_node(NodeInstance.create(parse_spec(REPORTER, "test.rep")))
    seen: list[float] = []
    graph.events.progress_changed.connect(lambda nid, f: seen.append(f))

    engine = ExecutionEngine(graph)
    with qtbot.waitSignal(engine.run_finished, timeout=5000):
        engine.run_all()

    assert max(seen) >= 0.9
    # nothing left behind for the LED to keep drawing after the run
    assert node.progress == 0.0
    assert seen[-1] == 0.0
    assert node.status == NodeStatus.DONE


def test_node_started_carries_its_place_in_the_plan(qtbot):
    graph = Graph()
    first = graph.add_node(NodeInstance.create(parse_spec(REPORTER, "test.rep")))
    second = graph.add_node(NodeInstance.create(parse_spec("""
NODE = {"label": "After", "category": "Test",
        "inputs": [("value", "any")], "outputs": [("value", "any")]}
def run(ctx, value):
    return value
""", "test.after")))
    graph.connect(first.id, "value", second.id, "value")

    engine = ExecutionEngine(graph)
    starts: list[tuple[str, int, int]] = []
    engine.node_started.connect(lambda nid, i, n: starts.append((nid, i, n)))
    with qtbot.waitSignal(engine.run_finished, timeout=5000):
        engine.run_all()

    assert starts == [(first.id, 1, 2), (second.id, 2, 2)]


def test_progress_reaches_the_engine_signal(qtbot):
    graph = Graph()
    node = graph.add_node(NodeInstance.create(parse_spec(REPORTER, "test.rep")))
    engine = ExecutionEngine(graph)
    seen: list[tuple[str, float]] = []
    engine.node_progress.connect(lambda nid, f: seen.append((nid, f)))
    with qtbot.waitSignal(engine.run_finished, timeout=5000):
        engine.run_all()
    assert seen and all(nid == node.id for nid, _ in seen)


def test_cancel_leaves_no_fraction_behind(qtbot):
    from PySide6.QtCore import QTimer

    graph = Graph()
    node = graph.add_node(NodeInstance.create(parse_spec("""
NODE = {"label": "Slow", "category": "Test",
        "inputs": [], "outputs": [("value", "any")]}
def run(ctx):
    import time
    for i in range(2000):
        ctx.progress(i / 2000)
        time.sleep(0.005)
        ctx.check_cancelled()
    return 1
""", "test.slow")))
    engine = ExecutionEngine(graph)
    QTimer.singleShot(100, engine.cancel)
    with qtbot.waitSignal(engine.run_finished, timeout=5000):
        engine.run_all()
    assert node.status == NodeStatus.ERROR
    assert node.progress == 0.0


# ----------------------------------------------------------- serialization

def test_progress_is_runtime_only(tmp_path):
    graph = Graph()
    node = graph.add_node(NodeInstance.create(parse_spec(REPORTER, "test.rep")))
    graph.set_progress(node.id, 0.5)
    data = graph_to_dict(graph)
    assert "progress" not in json.dumps(data)

    registry = NodeRegistry()
    registry.register(node.spec)
    reloaded = graph_from_dict(data, registry)
    assert reloaded.node(node.id).progress == 0.0
