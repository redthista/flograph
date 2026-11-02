"""The Run Flow node uses the headless runner and returns a named output."""
import subprocess
import sys

import pytest

from flograph.core import Graph, NodeRegistry, compile_run, serialization
from flograph.engine.cache import OutputCache
from flograph.engine.cache_persistence import save_cache
from tests.conftest import FakeContext


@pytest.fixture(scope="module")
def registry():
    value = NodeRegistry()
    value.load_builtins()
    return value


def _child_project(tmp_path, registry, value=42):
    graph = Graph()
    producer = graph.add_node(
        registry.instantiate("flograph.scripting.python_script"))
    graph.set_code(producer.id, '''
NODE = {"label": "Make value", "category": "Scripting", "version": "1.0",
        "inputs": [], "outputs": [("result", "number")]}
def run(ctx):
    return {"result": %d}
''' % value)
    output = graph.add_node(
        registry.instantiate("flograph.scripting.flow_output"))
    graph.set_param(output.id, "name", "answer")
    graph.connect(producer.id, "result", output.id, "value")
    project = tmp_path / "child.flograph"
    serialization.save(graph, project)
    return project, graph, producer, output


def _save_cached_output(project, graph, producer, output, value):
    cache = OutputCache()
    cache.set(producer.id, {"result": value}, 0.0)
    cache.set(output.id, {"value": value}, 0.0,
              alias_of=producer.id, alias_port="result")
    save_cache(graph, cache, project)


def _run_node(registry, ctx):
    spec = registry.get("flograph.scripting.run_flow")
    return compile_run(spec.source, "test-run-flow")(ctx)


def test_headless_runner_captures_a_named_flow_output(tmp_path, registry):
    project, _, _, _ = _child_project(tmp_path, registry)
    captured = tmp_path / "answer.pkl"
    result = subprocess.run(
        [sys.executable, "-m", "flograph", "run", str(project),
         "--capture-output", "answer", "--capture-file", str(captured)],
        capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr
    import pickle
    with captured.open("rb") as stream:
        assert pickle.load(stream) == 42


def test_run_flow_returns_the_named_child_output(tmp_path, registry):
    project, _, _, _ = _child_project(tmp_path, registry)
    params = registry.get("flograph.scripting.run_flow").default_params()
    params.update(project=str(project), output="answer")
    ctx = FakeContext(params=params)

    result = _run_node(registry, ctx)

    assert result == {"value": 42}
    assert any("2/2 nodes completed" in line for line in ctx.logs)


def test_run_flow_reports_a_missing_child_output(tmp_path, registry):
    project, _, _, _ = _child_project(tmp_path, registry)
    params = registry.get("flograph.scripting.run_flow").default_params()
    params.update(project=str(project), output="missing")

    with pytest.raises(RuntimeError, match="status 1"):
        _run_node(registry, FakeContext(params=params))


def test_run_flow_uses_current_saved_output_unless_always_run_is_set(
        tmp_path, registry):
    project, graph, producer, output = _child_project(tmp_path, registry)
    _save_cached_output(project, graph, producer, output, 41)
    params = registry.get("flograph.scripting.run_flow").default_params()
    params.update(project=str(project), output="answer")

    cached_context = FakeContext(params=params)
    assert _run_node(registry, cached_context) == {"value": 41}
    assert any("using saved output" in line for line in cached_context.logs)

    params["always_run"] = True
    fresh_context = FakeContext(params=params)
    assert _run_node(registry, fresh_context) == {"value": 42}
    assert any("2/2 nodes completed" in line for line in fresh_context.logs)


def test_run_flow_recomputes_when_the_saved_output_is_stale(tmp_path, registry):
    project, graph, producer, output = _child_project(tmp_path, registry)
    _save_cached_output(project, graph, producer, output, 41)
    graph.set_code(producer.id, '''
NODE = {"label": "Make value", "category": "Scripting", "version": "1.0",
        "inputs": [], "outputs": [("result", "number")]}
def run(ctx):
    return {"result": 43}
''')
    serialization.save(graph, project)
    params = registry.get("flograph.scripting.run_flow").default_params()
    params.update(project=str(project), output="answer")
    ctx = FakeContext(params=params)

    assert _run_node(registry, ctx) == {"value": 43}
    assert any("2/2 nodes completed" in line for line in ctx.logs)


def test_run_flow_stops_a_child_that_exceeds_its_timeout(tmp_path, registry):
    graph = Graph()
    producer = graph.add_node(
        registry.instantiate("flograph.scripting.python_script"))
    graph.set_code(producer.id, '''
import time
NODE = {"label": "Slow", "category": "Scripting", "version": "1.0",
        "inputs": [], "outputs": [("result", "number")]}
def run(ctx):
    time.sleep(10)
    return {"result": 42}
''')
    output = graph.add_node(
        registry.instantiate("flograph.scripting.flow_output"))
    graph.set_param(output.id, "name", "answer")
    graph.connect(producer.id, "result", output.id, "value")
    project = tmp_path / "slow-child.flograph"
    serialization.save(graph, project)
    params = registry.get("flograph.scripting.run_flow").default_params()
    params.update(project=str(project), output="answer", timeout=1)

    with pytest.raises(TimeoutError, match="exceeded its 1s timeout"):
        _run_node(registry, FakeContext(params=params))


def test_run_flow_reads_only_the_tail_of_a_verbose_child_log(tmp_path, registry):
    graph = Graph()
    producer = graph.add_node(
        registry.instantiate("flograph.scripting.python_script"))
    graph.set_code(producer.id, '''
NODE = {"label": "Make value", "category": "Scripting", "version": "1.0",
        "inputs": [], "outputs": [("result", "number")]}
def run(ctx):
    for _ in range(8000):
        ctx.log("x" * 100)
    return {"result": 42}
''')
    output = graph.add_node(
        registry.instantiate("flograph.scripting.flow_output"))
    graph.set_param(output.id, "name", "answer")
    graph.connect(producer.id, "result", output.id, "value")
    project = tmp_path / "verbose-child.flograph"
    serialization.save(graph, project)
    params = registry.get("flograph.scripting.run_flow").default_params()
    params.update(project=str(project), output="answer")
    ctx = FakeContext(params=params)

    assert _run_node(registry, ctx) == {"value": 42}
    assert len(ctx.logs) < 800


def test_flow_output_requires_a_name(registry):
    spec = registry.get("flograph.scripting.flow_output")
    run = compile_run(spec.source, "test-flow-output")

    with pytest.raises(ValueError, match="set a name"):
        run(FakeContext(params={"name": ""}), value=42)

    assert run(FakeContext(params={"name": "answer"}), value=42) == {
        "value": 42}
