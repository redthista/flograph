"""Engine tests. pytest-qt provides the Qt event loop glue (qtbot); workers
run on the real thread pool, results arrive via queued signals."""
import pytest
from PySide6.QtCore import QTimer

from flopy.core import Graph, NodeStatus, parse_spec, NodeInstance
from flopy.engine import ExecutionEngine, build_plan

TAGGED = """
NODE = {{
    "label": "{label}",
    "category": "Test",
    "inputs": [("value", "any", {{"optional": True}})],
    "outputs": [("value", "any")],
}}
def run(ctx, value):
    ctx.log("ran")
    return (value or 0) + 1
"""


def tagged_node(label: str) -> NodeInstance:
    return NodeInstance.create(parse_spec(TAGGED.format(label=label), f"test.{label}"))


def make_engine(graph: Graph):
    engine = ExecutionEngine(graph)
    ran: list[str] = []
    engine.node_log.connect(
        lambda nid, line, stream: ran.append(nid) if line == "ran" else None)
    return engine, ran


def wait_run(qtbot, engine, trigger, timeout=5000):
    with qtbot.waitSignal(engine.run_finished, timeout=timeout) as blocker:
        trigger()
    return blocker.args[0]  # ok


@pytest.fixture
def diamond():
    """a -> (b, c) -> d, where d takes only one input port, so: a->b->d and
    a->c (c is a leaf)."""
    graph = Graph()
    a, b, c, d = (tagged_node(x) for x in "abcd")
    for n in (a, b, c, d):
        graph.add_node(n)
    graph.connect(a.id, "value", b.id, "value")
    graph.connect(a.id, "value", c.id, "value")
    graph.connect(b.id, "value", d.id, "value")
    return graph, (a, b, c, d)


def test_build_plan_only_dirty_ancestors(diamond):
    graph, (a, b, c, d) = diamond
    assert build_plan(graph, [d.id]) == [a.id, b.id, d.id]  # c not needed
    graph.mark_clean(a.id)
    graph.mark_clean(b.id)
    assert build_plan(graph, [d.id]) == [d.id]
    assert build_plan(graph, list(graph.nodes)) == [c.id, d.id]


def test_run_all_topological_and_caches(qtbot, diamond):
    graph, (a, b, c, d) = diamond
    engine, ran = make_engine(graph)
    ok = wait_run(qtbot, engine, engine.run_all)
    assert ok
    assert ran.index(a.id) < ran.index(b.id) < ran.index(d.id)
    assert ran.index(a.id) < ran.index(c.id)
    assert len(ran) == 4
    for node in (a, b, c, d):
        assert node.status == NodeStatus.DONE and not node.dirty
    # value flowed: a=1, b=2, d=3
    assert engine.cache.outputs_for(d.id)["value"] == 3


def test_partial_rerun_after_dirty(qtbot, diamond):
    graph, (a, b, c, d) = diamond
    engine, ran = make_engine(graph)
    wait_run(qtbot, engine, engine.run_all)
    ran.clear()
    graph.mark_dirty(b.id)  # like a param change on b
    ok = wait_run(qtbot, engine, engine.run_all)
    assert ok
    assert set(ran) == {b.id, d.id}  # a and c come from cache
    assert engine.cache.outputs_for(d.id)["value"] == 3


def test_error_maps_to_script_line(qtbot):
    graph = Graph()
    node = graph.add_node(NodeInstance.create(parse_spec("""
NODE = {"label": "Boom", "category": "Test",
        "inputs": [], "outputs": [("value", "any")]}
def run(ctx):
    x = 1
    raise ValueError("boom")
""", "test.boom")))
    down = graph.add_node(tagged_node("down"))
    graph.connect(node.id, "value", down.id, "value")

    engine, ran = make_engine(graph)
    failures = []
    engine.node_failed.connect(lambda nid, err: failures.append(err))
    ok = wait_run(qtbot, engine, engine.run_all)
    assert not ok
    assert node.status == NodeStatus.ERROR
    assert "boom" in node.status_message
    assert down.status == NodeStatus.IDLE and down.dirty  # pruned, not run
    assert ran == []
    (error,) = failures
    assert error.script_line == 6
    assert 'raise ValueError("boom")' in error.formatted_tb


def test_output_type_validation(qtbot):
    graph = Graph()
    node = graph.add_node(NodeInstance.create(parse_spec("""
NODE = {"label": "BadType", "category": "Test",
        "inputs": [], "outputs": [("n", "number")]}
def run(ctx):
    return "not a number"
""", "test.badtype")))
    engine, _ = make_engine(graph)
    failures = []
    engine.node_failed.connect(lambda nid, err: failures.append(err))
    ok = wait_run(qtbot, engine, engine.run_all)
    assert not ok
    assert "output 'n'" in failures[0].message


def test_multi_output_dict_contract(qtbot):
    graph = Graph()
    good = graph.add_node(NodeInstance.create(parse_spec("""
NODE = {"label": "Two", "category": "Test",
        "inputs": [], "outputs": [("x", "number"), ("y", "number")]}
def run(ctx):
    return {"x": 1, "y": 2}
""", "test.two")))
    bad = graph.add_node(NodeInstance.create(parse_spec("""
NODE = {"label": "TwoBad", "category": "Test",
        "inputs": [], "outputs": [("x", "number"), ("y", "number")]}
def run(ctx):
    return {"x": 1, "z": 2}
""", "test.twobad")))
    engine, _ = make_engine(graph)
    failures = []
    engine.node_failed.connect(lambda nid, err: failures.append((nid, err)))
    ok = wait_run(qtbot, engine, engine.run_all)
    assert not ok
    assert engine.cache.outputs_for(good.id) == {"x": 1, "y": 2}
    assert failures[0][0] == bad.id
    assert "missing ['y']" in failures[0][1].message


def test_unconfigured_required_input(qtbot):
    graph = Graph()
    node = graph.add_node(NodeInstance.create(parse_spec("""
NODE = {"label": "Needs", "category": "Test",
        "inputs": [("table", "dataframe")], "outputs": [("value", "any")]}
def run(ctx, table):
    return 1
""", "test.needs")))
    engine, ran = make_engine(graph)
    ok = wait_run(qtbot, engine, engine.run_all)
    assert not ok
    assert node.status == NodeStatus.ERROR
    assert "not configured" in node.status_message
    assert ran == []


def test_stdout_capture_per_node(qtbot):
    graph = Graph()
    node = graph.add_node(NodeInstance.create(parse_spec("""
NODE = {"label": "Printer", "category": "Test",
        "inputs": [], "outputs": [("value", "any")]}
def run(ctx):
    print("hello")
    print("world")
    import sys
    print("warn", file=sys.stderr)
    return 1
""", "test.printer")))
    engine = ExecutionEngine(graph)
    lines = []
    engine.node_log.connect(lambda nid, line, stream: lines.append((nid, line, stream)))
    ok = wait_run(qtbot, engine, engine.run_all)
    assert ok
    assert (node.id, "hello", "stdout") in lines
    assert (node.id, "world", "stdout") in lines
    assert (node.id, "warn", "stderr") in lines


def test_cancellation(qtbot):
    graph = Graph()
    slow = graph.add_node(NodeInstance.create(parse_spec("""
NODE = {"label": "Slow", "category": "Test",
        "inputs": [], "outputs": [("value", "any")]}
def run(ctx):
    import time
    for _ in range(2000):
        time.sleep(0.005)
        ctx.check_cancelled()
    return 1
""", "test.slow")))
    queued = graph.add_node(tagged_node("after"))
    graph.connect(slow.id, "value", queued.id, "value")

    engine, ran = make_engine(graph)
    QTimer.singleShot(100, engine.cancel)
    ok = wait_run(qtbot, engine, engine.run_all)
    assert slow.status == NodeStatus.ERROR
    assert slow.status_message == "cancelled"
    assert slow.dirty
    assert queued.status == NodeStatus.IDLE  # never started
    assert ran == []


def test_dirty_evicts_cache(qtbot, diamond):
    graph, (a, b, c, d) = diamond
    engine, _ = make_engine(graph)
    wait_run(qtbot, engine, engine.run_all)
    assert engine.cache.has(b.id)
    graph.mark_dirty(b.id)
    assert not engine.cache.has(b.id)
    assert not engine.cache.has(d.id)  # downstream evicted too
    assert engine.cache.has(a.id)


def test_run_to_ignores_unrelated(qtbot, diamond):
    graph, (a, b, c, d) = diamond
    engine, ran = make_engine(graph)
    ok = wait_run(qtbot, engine, lambda: engine.run_to(b.id))
    assert ok
    assert set(ran) == {a.id, b.id}
    assert c.status == NodeStatus.IDLE and c.dirty
