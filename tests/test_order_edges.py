"""Order edges — the flow port every node carries, and the "run after that
one" dependency a wire between two of them makes.

The point of the design is that an order edge is an ordinary Connection on a
reserved port, so ordering, dirtying, cycle rejection, invalidation and
persistence are all inherited rather than reimplemented. These tests are
mostly proof of that inheritance.
"""
import json

import pytest

from flograph.core import Graph, GraphError, NodeInstance, parse_spec
from flograph.core.datatypes import PortType, can_connect
from flograph.core.script import NodeScriptError
from flograph.core.serialization import graph_from_dict, graph_to_dict
from flograph.engine import build_plan
from flograph.engine.cache_persistence import node_fingerprint
from tests.conftest import PASSTHROUGH, make_node

FLOW = "flow"

REQUIRES = """
NODE = {
    "label": "Requires",
    "category": "Test",
    "inputs": [("table", "dataframe")],
    "outputs": [("n", "number")],
}
def run(ctx, table):
    return {"n": len(table)}
"""


@pytest.fixture
def pair():
    """Two unconnected nodes."""
    graph = Graph()
    a = graph.add_node(make_node())
    b = graph.add_node(make_node())
    return graph, a, b


# ------------------------------------------------------------------ wiring

def test_flow_joins_only_flow():
    assert can_connect(PortType.FLOW, PortType.FLOW)
    assert not can_connect(PortType.FLOW, PortType.ANY)
    assert not can_connect(PortType.ANY, PortType.FLOW)
    assert not can_connect(PortType.FLOW, PortType.OBJECT)


def test_order_edge_is_an_ordinary_connection(pair):
    graph, a, b = pair
    conn, displaced = graph.connect(a.id, FLOW, b.id, FLOW)
    assert displaced is None
    assert graph.connections[conn.id] is conn
    assert graph.order_sources(b.id) == [a.id]
    assert graph.order_sources(a.id) == []


def test_order_edge_orders_the_run(pair):
    graph, a, b = pair
    graph.connect(a.id, FLOW, b.id, FLOW)
    assert graph.topo_order() == [a.id, b.id]
    assert graph.downstream(a.id) == {b.id}
    assert graph.upstream(b.id) == {a.id}


def test_order_edge_carries_no_value_to_a_port(pair):
    """It must never be mistaken for an input: `input_connection` answers
    only with edges that actually hand a value over."""
    graph, a, b = pair
    graph.connect(a.id, FLOW, b.id, FLOW)
    assert graph.input_connection(b.id, FLOW) is None
    assert graph.input_connection(b.id, "value") is None


def test_a_node_may_wait_for_several(pair):
    """Unlike a data input, the flow port displaces nothing: "after A and B"
    is a thing people mean."""
    graph, a, b = pair
    c = graph.add_node(make_node())
    graph.connect(a.id, FLOW, c.id, FLOW)
    graph.connect(b.id, FLOW, c.id, FLOW)
    assert graph.order_sources(c.id) == sorted([a.id, b.id])
    order = graph.topo_order()
    assert order.index(c.id) > max(order.index(a.id), order.index(b.id))


def test_the_same_pair_cannot_be_ordered_twice(pair):
    graph, a, b = pair
    graph.connect(a.id, FLOW, b.id, FLOW)
    with pytest.raises(GraphError):
        graph.connect(a.id, FLOW, b.id, FLOW)
    assert len(graph.connections) == 1


def test_order_edge_cannot_close_a_loop(pair):
    graph, a, b = pair
    graph.connect(a.id, "value", b.id, "value")   # data wire a -> b
    with pytest.raises(GraphError):
        graph.connect(b.id, FLOW, a.id, FLOW)
    with pytest.raises(GraphError):
        graph.connect(a.id, FLOW, a.id, FLOW)


def test_order_edge_goes_when_either_node_does(pair):
    graph, a, b = pair
    graph.connect(a.id, FLOW, b.id, FLOW)
    graph.remove_node(a.id)
    assert graph.connections == {}
    assert graph.order_sources(b.id) == []


def test_flow_port_is_not_a_data_port(pair):
    graph, a, b = pair
    with pytest.raises(GraphError):
        graph.connect(a.id, "value", b.id, FLOW)
    with pytest.raises(GraphError):
        graph.connect(a.id, FLOW, b.id, "value")


# ------------------------------------------------------- dirtying & running

def test_editing_upstream_dirties_across_an_order_edge(pair):
    graph, a, b = pair
    graph.connect(a.id, FLOW, b.id, FLOW)
    graph.mark_clean(a.id)
    graph.mark_clean(b.id)
    graph.set_param(a.id, "value", 3) if a.spec.param("value") else None
    graph.mark_dirty(a.id)
    assert graph.nodes[b.id].dirty


def test_running_the_dependent_pulls_its_prerequisite_in(pair):
    graph, a, b = pair
    graph.connect(a.id, FLOW, b.id, FLOW)
    assert build_plan(graph, [b.id]) == [a.id, b.id]


def test_deactivating_the_prerequisite_holds_the_dependent_back(pair):
    """An order edge is a real dependency, not a hint: switching the node
    off takes what waits on it with it, exactly as a data wire does."""
    graph, a, b = pair
    graph.connect(a.id, FLOW, b.id, FLOW)
    graph.set_active(a.id, False)
    assert build_plan(graph, list(graph.nodes)) == []


def test_an_unconnected_required_input_still_blocks():
    """The flow port is optional and invisible to the blocking check: a node
    ordered after another still needs its own inputs wired."""
    graph = Graph()
    a = graph.add_node(make_node())
    b = graph.add_node(make_node(REQUIRES, "test.requires"))
    graph.connect(a.id, FLOW, b.id, FLOW)
    from flograph.engine.scheduler import ExecutionEngine
    engine = ExecutionEngine(graph)
    assert "table" in (engine._blocking_problem(b.id) or "")


def test_order_edge_is_in_the_cache_fingerprint(pair):
    """A node ordered after a step that writes a file is stale when that
    step changes — nothing was handed over, but the dependency is real."""
    graph, a, b = pair
    graph.connect(a.id, FLOW, b.id, FLOW)
    before = node_fingerprint(graph, b.id, {})
    graph.node(a.id).params["value"] = "moved"
    assert node_fingerprint(graph, b.id, {}) != before


SLOW_THEN_FAST = """
NODE = {{
    "label": "{label}",
    "category": "Test",
    "inputs": [],
    "outputs": [("value", "any")],
}}
def run(ctx):
    import time
    time.sleep({sleep})
    ctx.log("ran")
    return {{"value": 1}}
"""


def test_a_real_run_waits_for_the_prerequisite(qtbot):
    """The end of the whole feature: two nodes with nothing between them,
    and the slow one still finishes first because an order edge says so.

    The prerequisite sleeps; without the edge the engine would start both at
    once and the quick one would report first.
    """
    from flograph.engine import ExecutionEngine

    graph = Graph()
    slow = graph.add_node(NodeInstance.create(parse_spec(
        SLOW_THEN_FAST.format(label="slow", sleep=0.25), "test.slow")))
    quick = graph.add_node(NodeInstance.create(parse_spec(
        SLOW_THEN_FAST.format(label="quick", sleep=0), "test.quick")))
    graph.connect(slow.id, FLOW, quick.id, FLOW)

    finished: list[str] = []
    engine = ExecutionEngine(graph)
    engine.node_log.connect(
        lambda nid, line, stream: finished.append(nid) if line == "ran"
        else None)
    with qtbot.waitSignal(engine.run_finished, timeout=10_000):
        engine.run_targets(list(graph.nodes))
    assert finished == [slow.id, quick.id]


# ----------------------------------------------------------------- the file

def test_order_edge_survives_a_round_trip(registry):
    graph = Graph()
    const = graph.add_node(registry.instantiate("flograph.util.constant"))
    script = graph.add_node(
        registry.instantiate("flograph.scripting.python_script"))
    graph.connect(const.id, FLOW, script.id, FLOW)
    data = graph_to_dict(graph)
    restored = graph_from_dict(json.loads(json.dumps(data)), registry)
    assert restored.order_sources(script.id) == [const.id]
    assert graph_to_dict(restored) == data


def test_order_edge_to_a_node_that_no_longer_loads(registry):
    """The placeholder must not sprout a data port named 'flow'."""
    graph = Graph()
    const = graph.add_node(registry.instantiate("flograph.util.constant"))
    broken = NodeInstance.create(parse_spec(PASSTHROUGH, "test.gone"))
    broken.code_override = None
    graph.add_node(broken)
    graph.connect(const.id, FLOW, broken.id, FLOW)
    restored = graph_from_dict(json.loads(json.dumps(graph_to_dict(graph))),
                               registry)
    spec = restored.nodes[broken.id].spec
    assert spec.broken
    assert [p.name for p in spec.inputs] == []
    assert restored.order_sources(broken.id) == [const.id]


# --------------------------------------------------------------- the script

def test_a_script_cannot_declare_a_flow_port():
    source = PASSTHROUGH.replace('("value", "any", {"optional": True})',
                                 '("flow", "any")')
    with pytest.raises(NodeScriptError, match="reserved"):
        parse_spec(source, "test.claims_flow")


def test_a_script_cannot_declare_the_flow_type():
    source = PASSTHROUGH.replace('("value", "any")', '("value", "flow")')
    with pytest.raises(NodeScriptError, match="not a script's to declare"):
        parse_spec(source, "test.claims_flow_type")
