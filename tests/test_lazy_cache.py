"""Opening a project must not read its cached results.

The behaviour these pin came from a real incident: a 14-node project whose
side-car held 2M-row frames cost about 4 GB of resident memory *to open*,
because opening unpickled every valid blob up front. Duplicating such a flow
exhausted the machine before Run had been pressed.

So the contract is: opening reads the manifest and nothing else. Each node is
cached-but-spilled, which is enough for it to count as clean, and its value is
read back only when something actually asks for it. The invariant the engine
leans on — "a node is clean iff its outputs are cached" — is preserved by
making *cached* mean resident or restorable, never absent.

None of this needs a large allocation to test. The decisive tests below
monkeypatch the loader, so "was anything read?" is answerable exactly rather
than by watching a memory figure.
"""
import json

import pandas as pd
import pytest

from flograph.core import Graph, NodeRegistry
from flograph.engine import cache_persistence
from flograph.engine.cache import OutputCache
from flograph.engine.cache_persistence import (
    register_cache, resolve_entries, save_cache,
)


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def make_graph(registry):
    graph = Graph()
    const = registry.instantiate("flograph.util.constant", pos=(0, 0))
    graph.add_node(const)
    return graph, const


def saved_project(registry, tmp_path, value="hello"):
    """A one-node project with its cache written to disk."""
    graph, const = make_graph(registry)
    cache = OutputCache()
    cache.set(const.id, {"value": value}, wall_time=0.01)
    path = tmp_path / "proj.flograph"
    save_cache(graph, cache, path)
    return graph, const, path


class TestOpeningReadsNothing:
    def test_registers_without_loading(self, registry, tmp_path, monkeypatch):
        """The decisive one: with the loader rigged to raise, opening still
        succeeds and every node comes back cached."""
        graph, const, path = saved_project(registry, tmp_path)

        def explode(*args, **kwargs):
            raise AssertionError("opening a project must not read a blob")

        monkeypatch.setattr(cache_persistence, "load_blob", explode)

        fresh = OutputCache()
        registered = register_cache(graph, fresh, path)

        assert registered == [const.id]
        assert fresh.has(const.id), "a spilled entry is still cached"
        assert not fresh.is_resident(const.id)
        assert fresh.total_bytes() == 0, "nothing is being held in memory"
        assert fresh.spilled_bytes() > 0, "but something is cached on disk"

    def test_value_comes_back_on_demand(self, registry, tmp_path):
        graph, const, path = saved_project(registry, tmp_path, value="hello")
        fresh = OutputCache()
        register_cache(graph, fresh, path)

        assert fresh.outputs_for(const.id) == {"value": "hello"}
        assert fresh.is_resident(const.id)
        assert fresh.total_bytes() > 0

    def test_loads_once_and_only_what_was_asked_for(self, registry, tmp_path,
                                                    monkeypatch):
        """Laziness pinned in the other direction: exactly one blob, for
        exactly the node wanted."""
        graph = Graph()
        first = registry.instantiate("flograph.util.constant", pos=(0, 0))
        second = registry.instantiate("flograph.util.constant", pos=(200, 0))
        graph.add_node(first)
        graph.add_node(second)
        cache = OutputCache()
        cache.set(first.id, {"value": "a"}, wall_time=0.01)
        cache.set(second.id, {"value": "b"}, wall_time=0.01)
        path = tmp_path / "proj.flograph"
        save_cache(graph, cache, path)

        reads = []
        real = cache_persistence.load_blob

        def counting(project_path, node_id):
            reads.append(node_id)
            return real(project_path, node_id)

        monkeypatch.setattr(cache_persistence, "load_blob", counting)

        fresh = OutputCache()
        register_cache(graph, fresh, path)
        assert reads == []

        fresh.outputs_for(second.id)
        assert reads == [second.id]

        fresh.outputs_for(second.id)
        assert reads == [second.id], "a resident entry is not read again"

    def test_peek_never_loads(self, registry, tmp_path, monkeypatch):
        """What the canvas uses: show what is in hand, touch no disk."""
        graph, const, path = saved_project(registry, tmp_path)
        monkeypatch.setattr(
            cache_persistence, "load_blob",
            lambda *a, **k: pytest.fail("peek must not read a blob"))

        fresh = OutputCache()
        register_cache(graph, fresh, path)
        assert fresh.peek(const.id) == {}
        assert fresh.get(const.id).outputs == {}


class TestUnreadableBlob:
    def test_materialize_reports_failure_rather_than_lying(self, registry,
                                                          tmp_path, monkeypatch):
        graph, const, path = saved_project(registry, tmp_path)
        monkeypatch.setattr(
            cache_persistence, "load_blob",
            lambda *a, **k: (_ for _ in ()).throw(OSError("disk gone")))

        fresh = OutputCache()
        register_cache(graph, fresh, path)
        assert fresh.materialize(const.id) is False
        assert not fresh.is_resident(const.id)

    def test_corrupt_blob_does_not_raise(self, registry, tmp_path):
        graph, const, path = saved_project(registry, tmp_path)
        (cache_persistence._cache_dir_for(path) / f"{const.id}.pkl").write_bytes(
            b"not a pickle")

        fresh = OutputCache()
        register_cache(graph, fresh, path)
        assert fresh.materialize(const.id) is False
        assert fresh.outputs_for(const.id) == {}


class TestSavingASpilledCache:
    def test_keeps_every_blob(self, registry, tmp_path, monkeypatch):
        """The trap: the save sweep deletes any .pkl not written this pass, so
        a spilled entry has to be counted as one to keep or saving silently
        destroys the value it points at."""
        graph, const, path = saved_project(registry, tmp_path)
        blob = cache_persistence._cache_dir_for(path) / f"{const.id}.pkl"
        assert blob.exists()

        fresh = OutputCache()
        register_cache(graph, fresh, path)
        monkeypatch.setattr(
            cache_persistence, "load_blob",
            lambda *a, **k: pytest.fail("saving must not read a spilled blob"))
        save_cache(graph, fresh, path)

        assert blob.exists(), "saving deleted the blob a live entry needs"
        assert not fresh.is_resident(const.id), "and it stayed unloaded"

    def test_round_trips_through_a_save(self, registry, tmp_path):
        graph, const, path = saved_project(registry, tmp_path, value="kept")
        fresh = OutputCache()
        register_cache(graph, fresh, path)
        save_cache(graph, fresh, path)

        again = OutputCache()
        register_cache(graph, again, path)
        assert again.outputs_for(const.id) == {"value": "kept"}

    def test_save_as_carries_the_blob_across(self, registry, tmp_path):
        """A spilled entry's blob lives beside the *old* project. Saving
        elsewhere has to bring it along or Save As quietly drops every cached
        result that had not been loaded."""
        graph, const, path = saved_project(registry, tmp_path, value="moved")
        fresh = OutputCache()
        register_cache(graph, fresh, path)

        elsewhere = tmp_path / "copy.flograph"
        save_cache(graph, fresh, elsewhere)

        again = OutputCache()
        register_cache(graph, again, elsewhere)
        assert again.outputs_for(const.id) == {"value": "moved"}


class TestManifestCompatibility:
    def test_schema_1_still_loads(self, registry, tmp_path):
        """Bumping the schema must not throw away everyone's cached work."""
        graph, const, path = saved_project(registry, tmp_path, value="old")
        manifest_path = cache_persistence._cache_dir_for(path) / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["cache_schema"] = 1
        for meta in manifest["nodes"].values():
            meta.pop("bytes", None)      # schema 1 recorded neither
            meta.pop("ports", None)
        manifest_path.write_text(json.dumps(manifest))

        fresh = OutputCache()
        assert register_cache(graph, fresh, path) == [const.id]
        assert fresh.outputs_for(const.id) == {"value": "old"}

    def test_schema_1_falls_back_to_the_file_size(self, registry, tmp_path):
        """With no recorded size, a reopened project would otherwise report
        itself as holding nothing at all."""
        graph, const, path = saved_project(registry, tmp_path)
        manifest_path = cache_persistence._cache_dir_for(path) / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["cache_schema"] = 1
        for meta in manifest["nodes"].values():
            meta.pop("bytes", None)
        manifest_path.write_text(json.dumps(manifest))

        fresh = OutputCache()
        register_cache(graph, fresh, path)
        assert fresh.spilled_bytes() > 0

    def test_unknown_schema_is_still_refused(self, registry, tmp_path):
        graph, const, path = saved_project(registry, tmp_path)
        manifest_path = cache_persistence._cache_dir_for(path) / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["cache_schema"] = 99
        manifest_path.write_text(json.dumps(manifest))

        assert resolve_entries(graph, path) == []


class TestSpilledAliases:
    def test_alias_resolves_through_its_source(self, registry, tmp_path):
        """A pass-through node owns no blob. Spilled, it has to resolve via
        the entry it shares with — and end up holding the *same object*, which
        is what stops one frame being counted and loaded once per hop."""
        graph = Graph()
        const = registry.instantiate("flograph.util.constant", pos=(0, 0))
        reroute = registry.instantiate("flograph.util.reroute", pos=(200, 0))
        graph.add_node(const)
        graph.add_node(reroute)
        graph.connect(const.id, "value", reroute.id, "value")

        frame = pd.DataFrame({"a": [1, 2, 3]})
        cache = OutputCache()
        cache.set(const.id, {"value": frame}, wall_time=0.01)
        cache.set(reroute.id, {"value": frame}, wall_time=0.0,
                  alias_of=const.id, alias_port="value")
        path = tmp_path / "proj.flograph"
        save_cache(graph, cache, path)

        fresh = OutputCache()
        registered = register_cache(graph, fresh, path)
        assert set(registered) == {const.id, reroute.id}
        assert not fresh.is_resident(reroute.id)

        got = fresh.outputs_for(reroute.id)["value"]
        assert got.equals(frame)
        assert got is fresh.outputs_for(const.id)["value"], \
            "the alias and its source must still share one object"

    def test_blob_source_names_the_chain_root(self, registry, tmp_path):
        graph = Graph()
        const = registry.instantiate("flograph.util.constant", pos=(0, 0))
        reroute = registry.instantiate("flograph.util.reroute", pos=(200, 0))
        graph.add_node(const)
        graph.add_node(reroute)
        graph.connect(const.id, "value", reroute.id, "value")
        cache = OutputCache()
        cache.set(const.id, {"value": "v"}, wall_time=0.01)
        cache.set(reroute.id, {"value": "v"}, wall_time=0.0,
                  alias_of=const.id, alias_port="value")
        path = tmp_path / "proj.flograph"
        save_cache(graph, cache, path)

        fresh = OutputCache()
        register_cache(graph, fresh, path)
        assert fresh.blob_source(reroute.id) == const.id
        assert fresh.blob_source(const.id) == const.id

        fresh.outputs_for(const.id)
        assert fresh.blob_source(const.id) is None, "nothing left to read"


class TestRunningAgainstASpilledUpstream:
    """The integration that matters: a reopened project's values are on disk,
    and a run has to get them back — off the GUI thread, before the first node
    starts, and without _blocking_problem deciding the upstream produced
    nothing."""

    def build(self, tmp_path):
        from flograph.core import Graph, NodeInstance
        from flograph.core.script import parse_spec

        graph = Graph()
        source = graph.add_node(NodeInstance.create(parse_spec("""
NODE = {"label": "Source", "category": "Test",
        "inputs": [], "outputs": [("value", "any")]}
def run(ctx):
    return 21
""", "test.source")))
        double = graph.add_node(NodeInstance.create(parse_spec("""
NODE = {"label": "Double", "category": "Test",
        "inputs": [("value", "any")], "outputs": [("value", "any")]}
def run(ctx, value):
    return value * 2
""", "test.double")))
        graph.connect(source.id, "value", double.id, "value")
        return graph, source, double

    def test_a_spilled_input_is_warmed_and_the_run_succeeds(self, qtbot, tmp_path):
        from flograph.engine.scheduler import ExecutionEngine

        graph, source, double = self.build(tmp_path)
        cache = OutputCache()
        cache.set(source.id, {"value": 21}, wall_time=0.01)
        path = tmp_path / "proj.flograph"
        save_cache(graph, cache, path)

        engine = ExecutionEngine(graph)
        register_cache(graph, engine.cache, path)
        graph.mark_clean(source.id)
        assert not engine.cache.is_resident(source.id)

        with qtbot.waitSignal(engine.run_finished, timeout=5000) as blocker:
            engine.run_targets([double.id])

        assert blocker.args == [True], "the run must not have failed"
        assert engine.cache.outputs_for(double.id)["value"] == 42
        assert engine.cache.is_resident(source.id), "the input was warmed"

    def test_blocking_problem_treats_spilled_as_present(self, tmp_path):
        """A spilled upstream must not read as 'did not produce output' — that
        is the check that would turn a lazy open into a broken project."""
        from flograph.engine.scheduler import ExecutionEngine

        graph, source, double = self.build(tmp_path)
        cache = OutputCache()
        cache.set(source.id, {"value": 21}, wall_time=0.01)
        path = tmp_path / "proj.flograph"
        save_cache(graph, cache, path)

        engine = ExecutionEngine(graph)
        register_cache(graph, engine.cache, path)
        assert engine._blocking_problem(double.id) is None

    def test_an_unreadable_input_dirties_the_node_instead_of_lying(
            self, qtbot, tmp_path, monkeypatch):
        """A blob that will not read must send its node dirty so it
        recomputes. Handing the flow a missing input and calling the result an
        answer is the one outcome that would be worse than an error."""
        from flograph.engine.scheduler import ExecutionEngine

        graph, source, double = self.build(tmp_path)
        cache = OutputCache()
        cache.set(source.id, {"value": 21}, wall_time=0.01)
        path = tmp_path / "proj.flograph"
        save_cache(graph, cache, path)

        engine = ExecutionEngine(graph)
        register_cache(graph, engine.cache, path)
        graph.mark_clean(source.id)
        monkeypatch.setattr(
            cache_persistence, "load_blob",
            lambda *a, **k: (_ for _ in ()).throw(OSError("gone")))

        reported = []
        engine.cache_load_failed.connect(reported.append)
        with qtbot.waitSignal(engine.run_finished, timeout=5000):
            engine.run_targets([double.id])

        assert reported == [source.id]
        assert not engine.cache.has(source.id), "the dud entry was dropped"
        assert graph.node(source.id).dirty, "so it will be recomputed"

        # And the recompute genuinely works: rerunning produces the answer.
        with qtbot.waitSignal(engine.run_finished, timeout=5000):
            engine.run_targets([double.id])
        assert engine.cache.outputs_for(double.id)["value"] == 42


class TestAccounting:
    def test_spilled_is_not_counted_as_held(self):
        cache = OutputCache()
        cache.register_spilled("n1", "proj", wall_time=0.0, memory_bytes=1000)
        assert cache.total_bytes() == 0
        assert cache.spilled_bytes() == 1000
        assert cache.heaviest() == [], "you cannot free what you are not holding"

    def test_becomes_held_once_loaded(self):
        cache = OutputCache()
        cache.set_loader(lambda project, node_id: {"value": "x"})
        cache.register_spilled("n1", "proj", wall_time=0.0, memory_bytes=1000)
        cache.materialize("n1")
        assert cache.spilled_bytes() == 0
        assert cache.total_bytes() == 1000
        assert cache.heaviest() == [("n1", 1000)]

    def test_ports_are_known_while_spilled(self):
        cache = OutputCache()
        cache.register_spilled("n1", "proj", wall_time=0.0,
                               port_names=("table", "count"))
        assert cache.get("n1").ports() == ("table", "count")
        assert cache.get("n1").summary("table") == "not loaded"
