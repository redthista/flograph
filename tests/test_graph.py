import pytest

from flograph.core import Graph, GraphError, NodeStatus, parse_spec
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


# ------------------------------------------------------------- spare ports

SPARE_STACK = """
NODE = {
    "label": "Stack",
    "category": "Test",
    "inputs": [
        ("top", "dataframe"),
        ("more", "dataframe", {"optional": True, "spare": True}),
    ],
    "outputs": [("n", "number")],
}
def run(ctx, **inputs):
    return 0
"""


def _spare_pair(graph):
    src = graph.add_node(make_node())
    dst = graph.add_node(make_node(SPARE_STACK, "test.stack"))
    return src, dst


def test_wire_on_spare_grows_a_port_and_leaves_a_new_spare():
    graph = Graph()
    src, dst = _spare_pair(graph)
    conn, _ = graph.connect(src.id, "value", dst.id, "more")
    # the wire is recorded under the permanent name it created
    assert conn.dst_port == "in2"
    grown = dst.spec.input("in2")
    assert grown is not None and grown.optional and not grown.spare
    # and the invitation is back: an unconnected trailing spare, still last
    spare = dst.spec.input("more")
    assert spare is not None and spare.spare
    assert dst.spec.inputs[-1].name == "more"
    assert graph.input_connection(dst.id, "more") is None


def test_second_wire_reuses_no_name_and_grows_again():
    graph = Graph()
    src, dst = _spare_pair(graph)
    second_src = graph.add_node(make_node())
    graph.connect(src.id, "value", dst.id, "more")
    conn, displaced = graph.connect(second_src.id, "value", dst.id, "more")
    assert conn.dst_port == "in3"
    assert displaced is None  # each wire landed on a fresh port


def test_growing_twice_lists_each_port_once():
    """The second growth is handed [in2, in3] while the spec already
    carries in2 from the first. Splicing onto the grown spec listed in2
    twice, and a duplicate name is not merely untidy: the canvas keys its
    pins by name, so the pair collapsed into one entry and stranded the
    loser at the node's origin as a stray dot above the node."""
    graph = Graph()
    src, dst = _spare_pair(graph)
    for _ in range(4):
        graph.connect(graph.add_node(make_node()).id, "value",
                      dst.id, "more")
    names = [p.name for p in dst.spec.inputs]
    assert names == ["top", "in2", "in3", "in4", "in5", "more"]
    assert len(names) == len(set(names))


def test_reloading_grown_ports_does_not_double_them():
    """apply_spec/restore_spec re-adopt the extras onto a freshly parsed
    spec; re-adopting the same list must be a no-op, not another splice."""
    graph = Graph()
    src, dst = _spare_pair(graph)
    graph.connect(src.id, "value", dst.id, "more")
    before = [p.name for p in dst.spec.inputs]
    for _ in range(3):
        dst.adopt_extra_inputs(dst.extra_inputs)
    assert [p.name for p in dst.spec.inputs] == before


def test_refused_wire_does_not_grow_the_node():
    graph = Graph()
    src, dst = _spare_pair(graph)
    typed = graph.add_node(make_node(TYPED, "test.typed2"))
    with pytest.raises(GraphError):
        graph.connect(typed.id, "n", dst.id, "more")  # number -> dataframe
    assert [p.name for p in dst.spec.inputs] == ["top", "more"]
    with pytest.raises(GraphError):
        graph.connect(dst.id, "n", dst.id, "more")  # cycle
    assert [p.name for p in dst.spec.inputs] == ["top", "more"]


def test_disconnect_leaves_the_grown_port_in_place():
    """Undo of a connect does not shrink the node back — a leftover empty
    slot costs nothing and shrinking under the user's cursor would."""
    graph = Graph()
    src, dst = _spare_pair(graph)
    conn, _ = graph.connect(src.id, "value", dst.id, "more")
    graph.disconnect(conn.id)
    assert dst.spec.input("in2") is not None


def test_fork_keeps_grown_ports_and_their_wires():
    graph = Graph()
    src, dst = _spare_pair(graph)
    graph.connect(src.id, "value", dst.id, "more")
    dropped = graph.set_code(
        dst.id, SPARE_STACK.replace('"Stack"', '"Stack forked"'))
    assert dropped == []
    assert dst.spec.input("in2") is not None
    assert graph.input_connection(dst.id, "in2") is not None
    assert dst.spec.inputs[-1].name == "more"


def test_growing_marks_dirty_and_announces_the_ports_changed():
    from flograph.core import NodeStatus

    graph = Graph()
    src, dst = _spare_pair(graph)
    seen = []
    graph.events.code_changed.connect(seen.append)
    graph.connect(src.id, "value", dst.id, "more")
    assert seen == [dst.id]
    assert dst.dirty and dst.status is NodeStatus.IDLE
