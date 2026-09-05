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


class TestColumnNamesOf:
    """`column_names_of` runs on every cache write, including for a fast
    non-pandas node that finishes while a parallel worker is still partway
    through its first `import pandas` — the module is then in `sys.modules`
    without `DataFrame` bound. It must return () there, not raise."""

    def test_returns_columns_for_a_frame(self):
        from flograph.engine.cache import column_names_of
        assert column_names_of(pd.DataFrame({"a": [1], "b": [2]})) == ("a", "b")

    def test_non_frame_is_empty(self):
        from flograph.engine.cache import column_names_of
        assert column_names_of({"style": "x"}) == ()
        assert column_names_of(None) == ()

    def test_half_imported_pandas_does_not_raise(self, monkeypatch):
        import sys
        import types
        from flograph.engine.cache import column_map, column_names_of
        half = types.ModuleType("pandas")            # no DataFrame attribute
        monkeypatch.setitem(sys.modules, "pandas", half)
        assert column_names_of(object()) == ()
        assert column_map({"style": {"rules": []}}) == {}


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


class TestBecameResidentEvent:
    """The notification lazy-open was missing: cards can only heal if
    something tells them a value they are showing as a placeholder has
    actually arrived."""

    def test_fires_once_when_spilled_becomes_resident(self):
        cache = OutputCache()
        seen = []
        cache.became_resident.connect(seen.append)

        cache.set("n1", {"out": 1}, wall_time=0.0)
        assert seen == []                      # set() is born resident
        cache.register_spilled("n2", "proj", 0.0)
        cache.mark_resident("n2", {"out": 2})
        assert seen == ["n2"]

    def test_repeats_and_gone_entries_stay_silent(self):
        cache = OutputCache()
        seen = []
        cache.became_resident.connect(seen.append)
        cache.register_spilled("n2", "proj", 0.0)

        cache.mark_resident("n2", {"out": 2})
        cache.mark_resident("n2", {"out": 2})   # already resident: echo
        cache.mark_resident("gone", {"out": 3}) # evicted since: nobody home
        assert seen == ["n2"]

    def test_warming_a_source_wakes_the_spilled_aliases_below_it(self):
        """The warm path attaches only the blob it read. An alias between a
        producer and a card (a Reroute, or a pass-through Slicer feeding
        another Slicer) owns no blob, so it must come to life — and fire its
        own event — off the back of its source, or the card below it never
        heals and keeps showing 'Run the graph to load…'."""
        cache = OutputCache()
        seen = []
        cache.became_resident.connect(seen.append)
        cache.register_spilled("reader", "proj", 0.0, port_names=("table",))
        cache.register_spilled("reroute", None, 0.0, port_names=("table",),
                               alias_of="reader", alias_port="table")
        cache.register_spilled("chained", None, 0.0, port_names=("table",),
                               alias_of="reroute", alias_port="table")

        frame = object()
        cache.mark_resident("reader", {"table": frame})

        assert seen == ["reader", "reroute", "chained"]
        assert cache.get("reroute").outputs["table"] is frame
        assert cache.get("chained").outputs["table"] is frame


class TestWarmEntries:
    """warm_entries: the display half of warming. Not a run — nothing is
    dirty, no plan is built; spilled entries come back because something
    visible wants them."""

    def test_brings_an_entry_back_without_a_run(self, qtbot, registry,
                                                tmp_path):
        from flograph.engine import ExecutionEngine

        graph, const, path = saved_project(registry, tmp_path)
        engine = ExecutionEngine(graph)
        register_cache(graph, engine.cache, path)
        assert not engine.cache.is_resident(const.id)

        assert engine.warm_entries([const.id]) is True
        qtbot.waitUntil(lambda: engine.cache.is_resident(const.id),
                        timeout=10000)
        assert engine.cache.outputs_for(const.id) == {"value": "hello"}

    def test_resident_or_absent_entries_need_no_warm(self, registry,
                                                     tmp_path):
        from flograph.engine import ExecutionEngine

        graph, const, path = saved_project(registry, tmp_path)
        engine = ExecutionEngine(graph)
        register_cache(graph, engine.cache, path)
        engine.cache.materialize(const.id)
        assert engine.warm_entries([const.id]) is False     # already here
        assert engine.warm_entries(["never-existed"]) is False

    def test_an_alias_warms_through_its_owner(self, qtbot, registry,
                                              tmp_path):
        """A Reroute re-serving its source owns no blob of its own: warming
        it must warm the owner, after which the alias resolves in memory."""
        from flograph.engine import ExecutionEngine

        graph = Graph()
        const = registry.instantiate("flograph.util.constant", pos=(0, 0))
        dot = registry.instantiate("flograph.util.reroute", pos=(200, 0))
        graph.add_node(const)
        graph.add_node(dot)
        graph.connect(const.id, "value", dot.id, "value")
        cache = OutputCache()
        shared = {"value": "shared object"}
        cache.set(const.id, shared, wall_time=0.01)
        cache.set(dot.id, {"value": shared["value"]}, wall_time=0.01,
                  alias_of=const.id, alias_port="value")
        path = tmp_path / "alias.flograph"
        save_cache(graph, cache, path)

        engine = ExecutionEngine(graph)
        register_cache(graph, engine.cache, path)
        assert engine.warm_entries([dot.id]) is True
        qtbot.waitUntil(lambda: engine.cache.is_resident(const.id),
                        timeout=10000)
        # the alias itself resolves through the resident owner, no disk
        assert engine.cache.outputs_for(dot.id)["value"] == "shared object"

    def test_warming_an_alias_makes_the_alias_itself_resident(
            self, qtbot, registry, tmp_path):
        """The regression: the warm marked only the blob *owner* resident and
        left the alias entry spilled. A card reading the alias — its own, or a
        Slicer one hop downstream — then sat on its "run the graph" placeholder
        while the node showed a full green LED, because _restore_cache had
        already set it DONE. The alias has to come back too, and fire its own
        became_resident so the waiting card is told."""
        from flograph.engine import ExecutionEngine

        graph = Graph()
        const = registry.instantiate("flograph.util.constant", pos=(0, 0))
        dot = registry.instantiate("flograph.util.reroute", pos=(200, 0))
        graph.add_node(const)
        graph.add_node(dot)
        graph.connect(const.id, "value", dot.id, "value")
        cache = OutputCache()
        cache.set(const.id, {"value": "v"}, wall_time=0.01)
        cache.set(dot.id, {"value": "v"}, wall_time=0.01,
                  alias_of=const.id, alias_port="value")
        path = tmp_path / "alias.flograph"
        save_cache(graph, cache, path)

        engine = ExecutionEngine(graph)
        register_cache(graph, engine.cache, path)
        notified = []
        engine.cache.became_resident.connect(notified.append)

        assert engine.warm_entries([dot.id]) is True
        qtbot.waitUntil(lambda: engine.cache.is_resident(dot.id),
                        timeout=10000)
        # resident with nobody having called outputs_for / materialize
        assert engine.cache.get(dot.id).outputs == {"value": "v"}
        assert dot.id in notified, "the alias's own card was never notified"

    def test_a_slicer_over_a_passthrough_can_answer_after_a_warm(
            self, qtbot, registry, tmp_path):
        """The Slicer face of the same bug: the card reads its *upstream*
        value, and when that upstream is a spilled pass-through the warm left
        it empty — so slicer_options returned None and the card showed
        "Run the graph to load slicer values." next to a green LED."""
        from flograph.engine import ExecutionEngine
        from flograph.engine.introspect import slicer_options

        graph = Graph()
        src = registry.instantiate("flograph.io.read_csv", pos=(0, 0))
        dot = registry.instantiate("flograph.util.reroute", pos=(200, 0))
        slicer = registry.instantiate("flograph.viz.slicer", pos=(400, 0))
        graph.add_node(src)
        graph.add_node(dot)
        graph.add_node(slicer)
        graph.connect(src.id, "table", dot.id, "value")
        graph.connect(dot.id, "value", slicer.id, "table")
        graph.set_param(slicer.id, "column", "region")

        frame = pd.DataFrame({"region": ["n", "s", "n", "e"],
                              "value": [1, 2, 3, 4]})
        cache = OutputCache()
        cache.set(src.id, {"table": frame}, wall_time=0.01)
        cache.set(dot.id, {"value": frame}, wall_time=0.01,
                  alias_of=src.id, alias_port="table")
        cache.set(slicer.id, {"table": frame, "selected": []}, wall_time=0.01)
        path = tmp_path / "slicer.flograph"
        save_cache(graph, cache, path)

        engine = ExecutionEngine(graph)
        register_cache(graph, engine.cache, path)
        # what _restore_cache warms for a slicer card: the slicer and the
        # node feeding its table input
        assert engine.warm_entries([slicer.id, dot.id]) is True
        qtbot.waitUntil(lambda: engine.cache.is_resident(dot.id),
                        timeout=10000)
        assert slicer_options(graph, engine.cache, slicer.id) == \
            ["e", "n", "s"]

    def test_a_dud_owner_drops_the_aliases_waiting_on_it(
            self, qtbot, registry, tmp_path, monkeypatch):
        """If the owner's blob will not read, the aliases re-serving it have
        lost their source too: drop them and dirty them so they recompute,
        rather than leaving a card waiting forever."""
        from flograph.engine import ExecutionEngine

        graph = Graph()
        const = registry.instantiate("flograph.util.constant", pos=(0, 0))
        dot = registry.instantiate("flograph.util.reroute", pos=(200, 0))
        graph.add_node(const)
        graph.add_node(dot)
        graph.connect(const.id, "value", dot.id, "value")
        cache = OutputCache()
        cache.set(const.id, {"value": "v"}, wall_time=0.01)
        cache.set(dot.id, {"value": "v"}, wall_time=0.01,
                  alias_of=const.id, alias_port="value")
        path = tmp_path / "alias.flograph"
        save_cache(graph, cache, path)

        engine = ExecutionEngine(graph)
        register_cache(graph, engine.cache, path)
        monkeypatch.setattr(
            cache_persistence, "load_blob",
            lambda *a, **k: (_ for _ in ()).throw(OSError("gone")))

        failed = []
        engine.cache_load_failed.connect(failed.append)
        assert engine.warm_entries([dot.id]) is True
        qtbot.waitUntil(lambda: not engine.cache.has(const.id), timeout=10000)

        assert not engine.cache.has(dot.id), "the orphaned alias was dropped"
        assert set(failed) == {const.id, dot.id}
        assert graph.node(dot.id).dirty and graph.node(const.id).dirty


class TestOpenRestoresWhatCardsShow:
    """The user-visible contract: reopening a flow finds it how it was
    left — data-bearing cards populated, no re-run, nothing pressed."""

    @pytest.fixture(autouse=True)
    def _isolated_settings(self, tmp_path, monkeypatch):
        from PySide6.QtCore import QSettings

        from flograph.ui import mainwindow as mod
        ini_path = str(tmp_path / "settings.ini")
        monkeypatch.setattr(
            mod, "QSettings",
            lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))

    @pytest.fixture(scope="module")
    def reg(self, registry):
        return registry

    def _window(self, qtbot, reg):
        from flograph.ui import mainwindow as mod
        win = mod.MainWindow(reg)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def test_reopening_populates_cards_without_a_run(
            self, qtbot, reg, tmp_path, monkeypatch):
        from flograph.core import serialization
        from flograph.engine import ExecutionEngine
        from flograph.engine.introspect import slicer_options

        csv = tmp_path / "sales.csv"
        csv.write_text("region,value\n" +
                       "".join(f"r{i % 3},{i}\n" for i in range(50)))

        # --- session one: run, save, close
        builder = self._window(qtbot, reg)
        reader = builder.graph.add_node(
            reg.instantiate("flograph.io.read_csv"))
        builder.graph.set_param(reader.id, "path", str(csv))
        slicer = builder.graph.add_node(
            reg.instantiate("flograph.viz.slicer"))
        builder.graph.set_param(slicer.id, "column", "region")
        builder.graph.connect(reader.id, "table", slicer.id, "table")
        with qtbot.waitSignal(builder.engine.run_finished, timeout=30000):
            builder.engine.run_all()
        project = tmp_path / "leftit.flograph"
        serialization.save(builder.graph, project)
        save_cache(builder.graph, builder.engine.cache, project)

        # --- session two: open, and wait — no run, no click
        reopened = self._window(qtbot, reg)
        refreshed = []
        monkeypatch.setattr(reopened, "_on_slicer_node_succeeded",
                            lambda nid: refreshed.append(nid))
        assert reopened.open_path(str(project), confirm=False) is True

        engine = reopened.engine
        qtbot.waitUntil(
            lambda: (engine.cache.is_resident(reader.id)
                     and engine.cache.is_resident(slicer.id)),
            timeout=15000)
        # the canvas slicer card was told its data arrived
        assert slicer.id in refreshed
        # and it can actually answer from the restored upstream value
        assert slicer_options(reopened.graph, engine.cache, slicer.id)
        # ...all without anything having executed
        assert engine.history.latest is None

    def test_report_and_linked_table_cards_come_back_too(
            self, qtbot, reg, tmp_path):
        """The 0.1.12 regression: the warm covered figure/table/slicer/kpi
        cards and nothing else, so a report card reopened blank and a linked
        Table card reopened empty. Both healed only on a re-run — or, for the
        cards that draw a preview, on folding and unfolding them, which is
        what routes back through _refresh_node_card by hand.

        Both kinds read their *inputs* rather than their own output, so this
        pins the sources coming back as well as the cards themselves.
        """
        from flograph.core import serialization

        csv = tmp_path / "sales.csv"
        csv.write_text("region,value\n" +
                       "".join(f"r{i % 3},{i}\n" for i in range(20)))

        builder = self._window(qtbot, reg)
        graph = builder.graph
        reader = graph.add_node(reg.instantiate("flograph.io.read_csv"))
        graph.set_param(reader.id, "path", str(csv))
        chart = graph.add_node(reg.instantiate("flograph.viz.show_plot"))
        graph.connect(reader.id, "table", chart.id, "table")
        linked = graph.add_node(reg.instantiate("flograph.io.table"))
        graph.connect(reader.id, "table", linked.id, "table")
        report = graph.add_node(reg.instantiate("flograph.viz.report_card"))
        graph.connect(chart.id, "figure", report.id, "a")
        graph.set_param(report.id, "text", "# Sales\n\n![[a]]\n")

        with qtbot.waitSignal(builder.engine.run_finished, timeout=30000) as b:
            builder.engine.run_all()
        assert b.args == [True]
        project = tmp_path / "cards.flograph"
        serialization.save(graph, project)
        save_cache(graph, builder.engine.cache, project)

        # --- session two: open, and wait
        reopened = self._window(qtbot, reg)
        assert reopened.open_path(str(project), confirm=False) is True
        engine = reopened.engine
        qtbot.waitUntil(
            lambda: (engine.cache.is_resident(linked.id)
                     and engine.cache.is_resident(report.id)),
            timeout=15000)
        # the report's embed points at the chart, so that has to be back too
        assert engine.cache.is_resident(chart.id)
        assert engine.history.latest is None, "nothing was re-run"

    def test_column_pickers_answer_without_reading_the_frame(
            self, qtbot, reg, tmp_path):
        """A Properties-panel column picker on a just-opened project used to
        come up empty — it walked `entry.outputs`, and a spilled entry's are
        empty by design — so the columns appeared only for nodes whose
        upstream some card had happened to warm for its own sake. That is
        what made it look random.

        The names now travel in the manifest, so the answer costs no read at
        all: the branch here feeds nothing visual and must stay on disk.
        """
        from flograph.core import serialization
        from flograph.engine import upstream_columns

        csv = tmp_path / "sales.csv"
        csv.write_text("region,value\n" +
                       "".join(f"r{i % 3},{i}\n" for i in range(20)))

        builder = self._window(qtbot, reg)
        graph = builder.graph
        reader = graph.add_node(reg.instantiate("flograph.io.read_csv"))
        graph.set_param(reader.id, "path", str(csv))
        grouped = graph.add_node(reg.instantiate("flograph.transform.group_by"))
        graph.connect(reader.id, "table", grouped.id, "table")
        graph.set_param(grouped.id, "by", "region")
        graph.set_param(grouped.id, "values", "value")

        with qtbot.waitSignal(builder.engine.run_finished, timeout=30000) as b:
            builder.engine.run_all()
        assert b.args == [True]
        project = tmp_path / "cols.flograph"
        serialization.save(graph, project)
        save_cache(graph, builder.engine.cache, project)

        reopened = self._window(qtbot, reg)
        assert reopened.open_path(str(project), confirm=False) is True
        engine = reopened.engine

        assert upstream_columns(reopened.graph, engine.cache, grouped.id) == \
            ["region", "value"]
        assert not engine.cache.is_resident(reader.id), \
            "listing columns must not drag the frame off disk"

    def test_reopening_populates_a_slicer_fed_through_a_reroute(
            self, qtbot, reg, tmp_path, monkeypatch):
        """The card reads its *upstream* value, and on a bigger flow that
        upstream is often a pass-through (a Reroute, a chained Slicer) whose
        entry aliases the real producer's blob. Reopening has to light that
        alias up too, or the slicer sits on 'Run the graph to load…' while
        the data behind it is right there."""
        from flograph.core import serialization
        from flograph.engine.introspect import slicer_options

        csv = tmp_path / "sales.csv"
        csv.write_text("region,value\n" +
                       "".join(f"r{i % 3},{i}\n" for i in range(50)))

        builder = self._window(qtbot, reg)
        reader = builder.graph.add_node(
            reg.instantiate("flograph.io.read_csv"))
        builder.graph.set_param(reader.id, "path", str(csv))
        dot = builder.graph.add_node(reg.instantiate("flograph.util.reroute"))
        slicer = builder.graph.add_node(
            reg.instantiate("flograph.viz.slicer"))
        builder.graph.set_param(slicer.id, "column", "region")
        builder.graph.connect(reader.id, "table", dot.id, "value")
        builder.graph.connect(dot.id, "value", slicer.id, "table")
        with qtbot.waitSignal(builder.engine.run_finished, timeout=30000):
            builder.engine.run_all()
        assert builder.engine.cache.get(dot.id).alias_of == reader.id
        project = tmp_path / "reroute.flograph"
        serialization.save(builder.graph, project)
        save_cache(builder.graph, builder.engine.cache, project)

        reopened = self._window(qtbot, reg)
        refreshed = []
        monkeypatch.setattr(reopened, "_on_slicer_node_succeeded",
                            lambda nid: refreshed.append(nid))
        assert reopened.open_path(str(project), confirm=False) is True

        engine = reopened.engine
        qtbot.waitUntil(lambda: engine.cache.is_resident(dot.id), timeout=15000)
        assert slicer.id in refreshed
        assert slicer_options(reopened.graph, engine.cache, slicer.id) == [
            "r0", "r1", "r2"]
        assert engine.history.latest is None
