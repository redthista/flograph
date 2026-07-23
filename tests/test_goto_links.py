"""Goto/From named links: the derived link set, the topology reads that union
it in, and the ways a link can fail to resolve."""
import json

import pytest

from flograph.core import Graph, NodeRegistry, serialization
from flograph.core.links import (
    UNNAMED, from_problem, link_id, link_label, resolve_links,
)
from flograph.engine.cache_persistence import node_fingerprint
from flograph.engine.scheduler import build_plan

GOTO = "flograph.util.goto"
FROM = "flograph.util.goto_from"
CONST = "flograph.util.constant"
REROUTE = "flograph.util.reroute"


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def linked(registry):
    """const -> goto ...link... from -> reroute"""
    graph = Graph()
    nodes = {}
    for key, type_id in (("const", CONST), ("goto", GOTO),
                         ("from", FROM), ("out", REROUTE)):
        nodes[key] = graph.add_node(registry.instantiate(type_id))
    graph.connect(nodes["const"].id, "value", nodes["goto"].id, "value")
    graph.connect(nodes["from"].id, "value", nodes["out"].id, "value")
    graph.set_param(nodes["goto"].id, "name", "Sales")
    graph.set_param(nodes["from"].id, "source", nodes["goto"].id)
    return graph, nodes


class TestResolution:
    def test_link_resolves_but_is_not_a_connection(self, linked):
        graph, nodes = linked
        assert list(graph.links) == [link_id(nodes["from"].id)]
        assert len(graph.connections) == 2
        link = graph.links[link_id(nodes["from"].id)]
        assert (link.src_node, link.dst_node) == (nodes["goto"].id,
                                                  nodes["from"].id)

    def test_unset_source_makes_no_link(self, registry):
        graph = Graph()
        graph.add_node(registry.instantiate(FROM))
        assert graph.links == {}

    def test_source_pointing_at_a_non_goto_is_ignored(self, registry):
        graph = Graph()
        const = graph.add_node(registry.instantiate(CONST))
        node = graph.add_node(registry.instantiate(FROM))
        graph.set_param(node.id, "source", const.id)
        assert graph.links == {}

    def test_many_froms_share_one_goto(self, linked, registry):
        graph, nodes = linked
        second = graph.add_node(registry.instantiate(FROM))
        graph.set_param(second.id, "source", nodes["goto"].id)
        assert len(graph.links) == 2
        assert graph.successors(nodes["goto"].id) == {nodes["from"].id, second.id}

    def test_from_declared_before_its_goto_still_resolves(self, registry):
        """The load path adds nodes in file order, so resolution can't be
        incremental."""
        graph = Graph()
        node = graph.add_node(registry.instantiate(FROM))
        goto = registry.instantiate(GOTO)
        graph.set_param(node.id, "source", goto.id)
        assert graph.links == {}
        graph.add_node(goto)
        assert list(graph.links) == [link_id(node.id)]


class TestTopology:
    def test_edges_read_through(self, linked):
        graph, nodes = linked
        assert graph.predecessors(nodes["from"].id) == {nodes["goto"].id}
        assert graph.successors(nodes["goto"].id) == {nodes["from"].id}
        assert graph.upstream(nodes["out"].id) == {
            nodes["from"].id, nodes["goto"].id, nodes["const"].id}
        assert nodes["out"].id in graph.downstream(nodes["const"].id)

    def test_input_connection_finds_the_link(self, linked):
        graph, nodes = linked
        conn = graph.input_connection(nodes["from"].id, "value")
        assert conn is not None and conn.src_node == nodes["goto"].id
        # ... but the wire-level view doesn't see it
        assert graph.input_connection(nodes["from"].id, "value",
                                      include_links=False) is None

    def test_topo_order_puts_the_goto_first(self, linked):
        graph, nodes = linked
        order = graph.topo_order()
        assert order.index(nodes["goto"].id) < order.index(nodes["from"].id)

    def test_plan_for_the_from_pulls_in_the_gotos_subtree(self, linked):
        graph, nodes = linked
        plan = build_plan(graph, [nodes["from"].id])
        assert plan == [nodes["const"].id, nodes["goto"].id, nodes["from"].id]

    def test_a_wire_into_the_hidden_end_is_refused(self, linked, registry):
        """The From's input is spoken for by the link, and would_cycle sees
        links, so the graph can't be talked into a loop through one."""
        graph, nodes = linked
        from flograph.core.graph import GraphError
        with pytest.raises(GraphError, match="cycle"):
            graph.connect(nodes["out"].id, "value", nodes["goto"].id, "value")


class TestDirty:
    def test_choosing_a_source_dirties_the_from(self, registry):
        graph = Graph()
        goto = graph.add_node(registry.instantiate(GOTO))
        node = graph.add_node(registry.instantiate(FROM))
        for n in graph.nodes.values():
            graph.mark_clean(n.id)
        graph.set_param(node.id, "source", goto.id)
        assert graph.nodes[node.id].dirty

    def test_deleting_the_goto_dirties_the_from(self, linked):
        graph, nodes = linked
        for n in list(graph.nodes.values()):
            graph.mark_clean(n.id)
        graph.remove_node(nodes["goto"].id)
        assert graph.links == {}
        assert graph.nodes[nodes["from"].id].dirty
        assert graph.nodes[nodes["out"].id].dirty  # and everything past it

    def test_renaming_a_link_is_cosmetic(self, linked):
        graph, nodes = linked
        for n in graph.nodes.values():
            graph.mark_clean(n.id)
        graph.set_param(nodes["goto"].id, "name", "Renamed")
        assert not any(n.dirty for n in graph.nodes.values())
        assert link_label(graph.nodes[nodes["goto"].id]) == "Renamed"

    def test_fingerprint_folds_across_the_link(self, linked):
        graph, nodes = linked
        before = node_fingerprint(graph, nodes["out"].id, {})
        graph.set_param(nodes["const"].id, "value", "changed")
        assert node_fingerprint(graph, nodes["out"].id, {}) != before


class TestProblems:
    def test_no_goto_selected(self, registry):
        graph = Graph()
        node = graph.add_node(registry.instantiate(FROM))
        assert from_problem(graph, node.id) == "not configured: no Goto selected"

    def test_dangling_source(self, linked):
        graph, nodes = linked
        graph.remove_node(nodes["goto"].id)
        assert "no longer exists" in from_problem(graph, nodes["from"].id)

    def test_loop_is_refused_and_explained(self, registry):
        graph = Graph()
        goto = graph.add_node(registry.instantiate(GOTO))
        node = graph.add_node(registry.instantiate(FROM))
        mid = graph.add_node(registry.instantiate(REROUTE))
        graph.connect(node.id, "value", mid.id, "value")
        graph.connect(mid.id, "value", goto.id, "value")
        graph.set_param(node.id, "source", goto.id)
        assert graph.links == {}
        assert "loop" in from_problem(graph, node.id)
        assert len(graph.topo_order()) == 3  # and the graph stays runnable

    def test_removing_the_blocking_wire_resolves_the_link(self, registry):
        """The real edges are an input to the cycle check, so wiring changes
        have to re-derive too."""
        graph = Graph()
        goto = graph.add_node(registry.instantiate(GOTO))
        node = graph.add_node(registry.instantiate(FROM))
        mid = graph.add_node(registry.instantiate(REROUTE))
        graph.connect(node.id, "value", mid.id, "value")
        conn, _ = graph.connect(mid.id, "value", goto.id, "value")
        graph.set_param(node.id, "source", goto.id)
        assert graph.links == {}

        graph.disconnect(conn.id)
        assert list(graph.links) == [link_id(node.id)]
        assert from_problem(graph, node.id) is None

    def test_a_displacing_connect_leaves_the_links_acyclic(self, registry):
        """connect() drops the displaced wire mid-flight, which can unblock a
        link that the wire arriving in its place blocks again. The link set
        has to come from the settled state, not that transient — a cyclic
        `graph.links` would make every later run raise."""
        graph = Graph()
        goto = graph.add_node(registry.instantiate(GOTO))
        node = graph.add_node(registry.instantiate(FROM))
        mid = graph.add_node(registry.instantiate(REROUTE))
        sink = graph.add_node(registry.instantiate(REROUTE))
        graph.connect(node.id, "value", mid.id, "value")
        graph.connect(mid.id, "value", sink.id, "value")
        blocking, _ = graph.connect(sink.id, "value", goto.id, "value")
        graph.set_param(node.id, "source", goto.id)
        assert graph.links == {}  # the loop through sink blocks it

        # displaces `blocking` — which frees the link — but closes the loop
        # again itself, one node earlier
        graph.connect(mid.id, "value", goto.id, "value")
        assert blocking.id not in graph.connections
        assert graph.links == {}
        graph.topo_order()  # must not raise

    def test_a_healthy_link_has_no_problem(self, linked):
        graph, nodes = linked
        assert from_problem(graph, nodes["from"].id) is None

    def test_non_from_nodes_have_no_opinion(self, linked):
        graph, nodes = linked
        assert from_problem(graph, nodes["goto"].id) is None

    def test_unnamed_goto_label(self, registry):
        graph = Graph()
        goto = graph.add_node(registry.instantiate(GOTO))
        assert link_label(goto) == UNNAMED


class TestPersistence:
    def test_links_are_derived_not_saved(self, linked, tmp_path, registry):
        graph, nodes = linked
        path = tmp_path / "p.flograph"
        serialization.save(graph, path)
        saved = json.loads(path.read_text())
        assert len(saved["graph"]["connections"]) == 2  # links absent
        loaded = serialization.load(path, registry)
        assert list(loaded.links) == [link_id(nodes["from"].id)]
        assert loaded.predecessors(nodes["from"].id) == {nodes["goto"].id}

    def test_resolve_links_is_a_pure_function_of_the_graph(self, linked):
        graph, _ = linked
        assert resolve_links(graph) == graph.links
