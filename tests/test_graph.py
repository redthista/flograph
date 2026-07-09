import pytest

from flopy.core import Graph, GraphError, NodeStatus, parse_spec
from tests.conftest import PASSTHROUGH, make_node

TYPED = """
NODE = {
    "label": "Typed",
    "category": "Test",
    "inputs": [("table", "dataframe")],
    "outputs": [("n", "number")],
}
def run(ctx, table):
    return len(table)
"""


def test_add_and_remove_node():
    graph = Graph()
    node = make_node()
    graph.add_node(node)
    assert node.id in graph.nodes
    with pytest.raises(GraphError):
        graph.add_node(node)  # duplicate id
    removed, conns = graph.remove_node(node.id)
    assert removed is node and conns == []
    assert node.id not in graph.nodes


def test_remove_node_returns_connections(chain_graph):
    graph, (a, b, c) = chain_graph
    _, removed = graph.remove_node(b.id)
    assert len(removed) == 2
    assert not graph.connections


def test_connect_validates_ports_and_types():
    graph = Graph()
    src = make_node()  # outputs value: any
    dst = graph.add_node(make_node(TYPED, "test.typed"))
    graph.add_node(src)
    # any -> dataframe is allowed
    graph.connect(src.id, "value", dst.id, "table")
    with pytest.raises(GraphError, match="no output port"):
        graph.connect(src.id, "nope", dst.id, "table")
    with pytest.raises(GraphError, match="no input port"):
        graph.connect(src.id, "value", dst.id, "nope")
    # number -> dataframe is rejected
    other = graph.add_node(make_node(TYPED, "test.typed"))
    with pytest.raises(GraphError, match="cannot connect"):
        graph.connect(dst.id, "n", other.id, "table")


def test_input_port_displacement():
    graph = Graph()
    a, b, c = make_node(), make_node(), make_node()
    for n in (a, b, c):
        graph.add_node(n)
    first, displaced = graph.connect(a.id, "value", c.id, "value")
    assert displaced is None
    second, displaced = graph.connect(b.id, "value", c.id, "value")
    assert displaced == first
    assert list(graph.connections.values()) == [second]


def test_cycle_rejection(chain_graph):
    graph, (a, b, c) = chain_graph
    assert graph.would_cycle(c.id, a.id)
    assert graph.would_cycle(a.id, a.id)  # self-loop
    with pytest.raises(GraphError, match="cycle"):
        graph.connect(c.id, "value", a.id, "value")


def test_topo_order_diamond():
    graph = Graph()
    a, b, c, d = (make_node() for _ in range(4))
    for n in (a, b, c, d):
        graph.add_node(n)
    graph.connect(a.id, "value", b.id, "value")
    graph.connect(a.id, "value", c.id, "value")
    graph.connect(b.id, "value", d.id, "value")
    # d has one input; c -> d displaced b -> d, so wire b->d then check subset
    order = graph.topo_order()
    assert order.index(a.id) < order.index(b.id) < order.index(d.id)
    assert order.index(a.id) < order.index(c.id)
    # induced subgraph
    sub = graph.topo_order(subset=[d.id, b.id, a.id])
    assert sub == [a.id, b.id, d.id]


def test_dirty_propagation(chain_graph):
    graph, (a, b, c) = chain_graph
    for n in (a, b, c):
        graph.mark_clean(n.id)
    events = []
    graph.events.dirty_changed.connect(lambda nid, dirty: events.append((nid, dirty)))
    graph.mark_dirty(b.id)
    assert graph.nodes[b.id].dirty and graph.nodes[c.id].dirty
    assert not graph.nodes[a.id].dirty
    assert (b.id, True) in events and (c.id, True) in events
    # re-marking already-dirty nodes emits nothing new
    events.clear()
    graph.mark_dirty(b.id)
    assert events == []


def test_set_param_marks_downstream_dirty():
    graph = Graph()
    node = graph.add_node(make_node("""
NODE = {"label": "P", "category": "T", "inputs": [], "outputs": [("value", "any")]}
PARAMS = [{"name": "x", "type": "int", "default": 1}]
def run(ctx):
    return ctx.params["x"]
""", "test.param"))
    down = graph.add_node(make_node())
    graph.connect(node.id, "value", down.id, "value")
    graph.mark_clean(node.id)
    graph.mark_clean(down.id)
    graph.set_param(node.id, "x", 5)
    assert graph.nodes[node.id].dirty and graph.nodes[down.id].dirty
    with pytest.raises(GraphError, match="no param"):
        graph.set_param(node.id, "nope", 1)


def test_set_code_drops_invalid_connections(chain_graph):
    graph, (a, b, c) = chain_graph
    removed = graph.set_code(b.id, """
NODE = {"label": "Renamed", "category": "Test",
        "inputs": [("something_else", "any")],
        "outputs": [("value", "any")]}
def run(ctx, something_else):
    return something_else
""")
    # input port 'value' vanished -> a->b dropped; output kept -> b->c stays
    assert len(removed) == 1
    assert removed[0].src_node == a.id
    assert len(graph.connections) == 1
    assert graph.nodes[b.id].forked


def test_restore_spec_reverses_fork(chain_graph):
    graph, (a, b, c) = chain_graph
    old_spec = b.spec
    graph.set_code(b.id, PASSTHROUGH.replace('"Pass"', '"Forked"'))
    assert b.forked and b.label == "Forked"
    graph.restore_spec(b.id, None, old_spec)
    assert not b.forked and b.label == "Pass"


def test_status_events():
    graph = Graph()
    node = graph.add_node(make_node())
    seen = []
    graph.events.status_changed.connect(lambda *args: seen.append(args))
    graph.set_status(node.id, NodeStatus.RUNNING)
    graph.set_status(node.id, NodeStatus.ERROR, "boom")
    assert seen == [
        (node.id, NodeStatus.RUNNING, ""),
        (node.id, NodeStatus.ERROR, "boom"),
    ]
