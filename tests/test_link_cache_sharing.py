"""Goto/From/Reroute nodes share one cached value instead of copying it.

A pass-through node hands its input straight back, so the object it produces
is already in the cache under the node upstream. Before this, every hop was
accounted for, pickled and reloaded as if it were a value of its own: a
DataFrame behind a Goto and two Froms reported four times its size, wrote
four blobs into the side-car cache, and came back from a reopen as four
independent copies. These tests pin down each of those three.
"""
import pandas as pd
import pytest
from flograph.core import Graph, NodeRegistry
from flograph.engine.cache import OutputCache
from flograph.engine.cache_persistence import (
    is_alias, load_cache, restore_aliases, resolve_entries, save_cache,
)
from flograph.engine.cache_worker import CacheLoadRunnable, CacheLoadSignals
from flograph.engine.scheduler import ExecutionEngine

GOTO = "flograph.util.goto"
FROM = "flograph.util.goto_from"
REROUTE = "flograph.util.reroute"
SCRIPT = "flograph.scripting.python_script"

SOURCE = """
NODE = {"label": "Frame", "category": "Test",
        "inputs": [], "outputs": [("result", "any")]}
import pandas as pd
def run(ctx):
    return pd.DataFrame({"a": range(500), "b": range(500)})
"""

BUILDER = """
NODE = {"label": "Copy", "category": "Test",
        "inputs": [("value", "any")], "outputs": [("result", "any")]}
def run(ctx, value):
    return value.copy()
"""


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def run_graph(qtbot, graph):
    """Run every node to completion and hand back the engine."""
    engine = ExecutionEngine(graph)
    with qtbot.waitSignal(engine.run_finished, timeout=20000):
        engine.run_all()
    return engine


@pytest.fixture
def chain(registry):
    """script -> goto ...link... from, plus a second from off the same goto."""
    graph = Graph()
    src = graph.add_node(registry.instantiate(SCRIPT))
    graph.set_code(src.id, SOURCE)
    goto = graph.add_node(registry.instantiate(GOTO))
    first = graph.add_node(registry.instantiate(FROM))
    second = graph.add_node(registry.instantiate(FROM))
    graph.connect(src.id, "result", goto.id, "value")
    graph.set_param(first.id, "source", goto.id)
    graph.set_param(second.id, "source", goto.id)
    return graph, {"src": src, "goto": goto, "first": first, "second": second}


class TestCacheAccounting:
    def test_alias_is_not_counted_twice(self):
        cache = OutputCache()
        frame = pd.DataFrame({"a": range(1000)})
        cache.set("owner", {"result": frame}, 0.0)
        owned = cache.total_bytes()
        cache.set("link", {"value": frame}, 0.0,
                  alias_of="owner", alias_port="result")
        assert cache.total_bytes() == owned

    def test_alias_still_reports_its_own_size(self):
        """The project total stops double-counting; the per-node readout must
        not start lying about how big the value is."""
        cache = OutputCache()
        frame = pd.DataFrame({"a": range(1000)})
        cache.set("owner", {"result": frame}, 0.0)
        cache.set("link", {"value": frame}, 0.0,
                  alias_of="owner", alias_port="result")
        assert cache.get("link").memory_bytes == cache.get("owner").memory_bytes
        assert cache.get("link").memory_bytes > 0

    def test_orphaned_alias_is_counted(self):
        """Once the owner is evicted the link is the only thing holding the
        object, so dropping it from the total would under-report."""
        cache = OutputCache()
        frame = pd.DataFrame({"a": range(1000)})
        cache.set("owner", {"result": frame}, 0.0)
        size = cache.total_bytes()
        cache.set("link", {"value": frame}, 0.0,
                  alias_of="owner", alias_port="result")
        cache.evict("owner")
        assert cache.total_bytes() == size

    def test_a_plain_entry_is_unaffected(self):
        cache = OutputCache()
        cache.set("a", {"value": pd.DataFrame({"x": range(500)})}, 0.0)
        assert cache.get("a").alias_of is None
        assert cache.total_bytes() == cache.get("a").memory_bytes


class TestEngineDetectsPassThrough:
    def test_link_chain_reports_one_value(self, qtbot, chain):
        graph, n = chain
        engine = run_graph(qtbot, graph)
        owner = engine.cache.get(n["src"].id)
        assert engine.cache.total_bytes() == owner.memory_bytes

    def test_every_hop_points_at_the_node_that_owns_it(self, qtbot, chain):
        graph, n = chain
        engine = run_graph(qtbot, graph)
        goto_entry = engine.cache.get(n["goto"].id)
        assert (goto_entry.alias_of, goto_entry.alias_port) == \
            (n["src"].id, "result")
        for key in ("first", "second"):
            entry = engine.cache.get(n[key].id)
            assert (entry.alias_of, entry.alias_port) == (n["goto"].id, "value")

    def test_the_value_really_is_shared(self, qtbot, chain):
        graph, n = chain
        engine = run_graph(qtbot, graph)
        owned = engine.cache.outputs_for(n["src"].id)["result"]
        for key in ("goto", "first", "second"):
            assert engine.cache.outputs_for(n[key].id)["value"] is owned

    def test_reroute_aliases_too(self, qtbot, registry):
        graph = Graph()
        src = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(src.id, SOURCE)
        dot = graph.add_node(registry.instantiate(REROUTE))
        graph.connect(src.id, "result", dot.id, "value")
        engine = run_graph(qtbot, graph)
        assert engine.cache.get(dot.id).alias_of == src.id

    def test_a_node_that_builds_a_new_value_is_not_aliased(self, qtbot, registry):
        """Identity is the test, so anything that actually computes is cached
        normally — including a node whose output merely equals its input."""
        graph = Graph()
        src = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(src.id, SOURCE)
        copy = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(copy.id, BUILDER)
        graph.connect(src.id, "result", copy.id, "value")
        engine = run_graph(qtbot, graph)
        assert engine.cache.get(copy.id).alias_of is None
        assert engine.cache.total_bytes() == (
            engine.cache.get(src.id).memory_bytes
            + engine.cache.get(copy.id).memory_bytes)

    def test_a_frozen_link_owns_its_value(self, qtbot, chain):
        """A pin has to survive its source being edited away, so it must not
        be a reference to something that might not come back."""
        graph, n = chain
        graph.set_frozen(n["goto"].id, True)
        engine = run_graph(qtbot, graph)   # nothing pinned yet, so it runs once
        assert engine.cache.get(n["goto"].id).alias_of is None


class TestPersistence:
    def test_one_blob_for_the_whole_chain(self, qtbot, chain, tmp_path):
        graph, n = chain
        engine = run_graph(qtbot, graph)
        project = tmp_path / "p.flograph"
        save_cache(graph, engine.cache, project)
        blobs = list((tmp_path / "p.flograph.cache").glob("*.pkl"))
        assert [b.stem for b in blobs] == [n["src"].id]

    def test_the_links_are_still_in_the_manifest(self, qtbot, chain, tmp_path):
        graph, n = chain
        engine = run_graph(qtbot, graph)
        project = tmp_path / "p.flograph"
        save_cache(graph, engine.cache, project)
        entries = dict(resolve_entries(graph, project))
        assert set(entries) == {n[k].id for k in n}
        assert not is_alias(entries[n["src"].id])
        assert all(is_alias(entries[n[k].id])
                   for k in ("goto", "first", "second"))

    def test_reload_shares_one_object(self, qtbot, chain, tmp_path):
        graph, n = chain
        engine = run_graph(qtbot, graph)
        project = tmp_path / "p.flograph"
        save_cache(graph, engine.cache, project)

        fresh = OutputCache()
        restored = load_cache(graph, fresh, project)
        assert set(restored) == {n[k].id for k in n}
        owned = fresh.outputs_for(n["src"].id)["result"]
        for key in ("goto", "first", "second"):
            assert fresh.outputs_for(n[key].id)["value"] is owned
        assert fresh.total_bytes() == fresh.get(n["src"].id).memory_bytes

    def test_reloaded_values_are_intact(self, qtbot, chain, tmp_path):
        graph, n = chain
        engine = run_graph(qtbot, graph)
        project = tmp_path / "p.flograph"
        save_cache(graph, engine.cache, project)
        fresh = OutputCache()
        load_cache(graph, fresh, project)
        frame = fresh.outputs_for(n["second"].id)["value"]
        assert len(frame) == 500
        assert list(frame.columns) == ["a", "b"]

    def test_a_frozen_link_gets_its_own_blob(self, qtbot, chain, tmp_path):
        graph, n = chain
        graph.set_frozen(n["goto"].id, True)
        engine = run_graph(qtbot, graph)
        project = tmp_path / "p.flograph"
        save_cache(graph, engine.cache, project)
        blobs = {b.stem for b in (tmp_path / "p.flograph.cache").glob("*.pkl")}
        assert n["goto"].id in blobs

    def test_an_alias_whose_source_is_gone_is_skipped(self, qtbot, chain, tmp_path):
        """Losing a blob means those nodes load dirty — never an exception."""
        graph, n = chain
        engine = run_graph(qtbot, graph)
        project = tmp_path / "p.flograph"
        save_cache(graph, engine.cache, project)
        (tmp_path / "p.flograph.cache" / f"{n['src'].id}.pkl").unlink()

        fresh = OutputCache()
        assert load_cache(graph, fresh, project) == []
        assert fresh.total_bytes() == 0

    def test_restore_aliases_is_idempotent(self, qtbot, chain, tmp_path):
        graph, n = chain
        engine = run_graph(qtbot, graph)
        project = tmp_path / "p.flograph"
        save_cache(graph, engine.cache, project)
        fresh = OutputCache()
        load_cache(graph, fresh, project)
        entries = resolve_entries(graph, project)
        again = restore_aliases(graph, fresh, entries)
        assert set(again) == {n[k].id for k in ("goto", "first", "second")}
        assert fresh.total_bytes() == fresh.get(n["src"].id).memory_bytes

    def test_a_frozen_link_survives_a_reload_on_its_own(self, qtbot, chain, tmp_path):
        """The interaction worth pinning down: a frozen node's fingerprint is
        a constant, so it can come back when its source cannot. That only
        holds because it kept a blob of its own."""
        graph, n = chain
        graph.set_frozen(n["goto"].id, True)
        engine = run_graph(qtbot, graph)
        project = tmp_path / "p.flograph"
        save_cache(graph, engine.cache, project)
        # move the source out from under the pin, as an upstream edit would
        (tmp_path / "p.flograph.cache" / f"{n['src'].id}.pkl").unlink()

        fresh = OutputCache()
        restored = load_cache(graph, fresh, project)
        assert n["goto"].id in restored
        assert len(fresh.outputs_for(n["goto"].id)["value"]) == 500

    def test_the_gui_load_path_composes(self, qtbot, chain, tmp_path):
        """The blob loader runs off-thread and skips the links; the aliases
        are rebuilt afterwards on the GUI thread. Both halves in that order
        are what MainWindow._restore_cache does."""
        graph, n = chain
        engine = run_graph(qtbot, graph)
        project = tmp_path / "p.flograph"
        save_cache(graph, engine.cache, project)

        entries = resolve_entries(graph, project)
        fresh = OutputCache()
        signals = CacheLoadSignals()
        signals.entry_loaded.connect(
            lambda nid, outputs, wall: fresh.set(nid, outputs, wall))
        CacheLoadRunnable(str(project), entries, signals).run()
        assert [nid for nid, _ in entries if fresh.has(nid)] == [n["src"].id]

        assert set(restore_aliases(graph, fresh, entries)) == \
            {n[k].id for k in ("goto", "first", "second")}
        owned = fresh.outputs_for(n["src"].id)["result"]
        assert fresh.outputs_for(n["second"].id)["value"] is owned

    def test_a_none_output_still_round_trips(self, qtbot, registry, tmp_path):
        """`port in outputs` rather than a truthiness check: None is a value a
        node is allowed to cache, and the link has to carry it."""
        graph = Graph()
        src = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(src.id, '''
NODE = {"label": "Nothing", "category": "Test",
        "inputs": [], "outputs": [("result", "any")]}
def run(ctx):
    return None
''')
        dot = graph.add_node(registry.instantiate(REROUTE))
        graph.connect(src.id, "result", dot.id, "value")
        engine = run_graph(qtbot, graph)
        project = tmp_path / "p.flograph"
        save_cache(graph, engine.cache, project)
        fresh = OutputCache()
        assert dot.id in load_cache(graph, fresh, project)
        assert fresh.outputs_for(dot.id) == {"value": None}
