"""The single-file .flograph bundle: a zip holding project.json plus a
cache/ tree. Covers the sniff, the reader/writer, and the save/open flow
through cache_persistence — carry-over of unloaded blobs, Save As, the
mid-run carry-all save, save-without-cache, and folding in a legacy
side-car folder.
"""
import json
import zipfile

import pandas as pd
import pytest

from flograph.core import Graph, NodeRegistry, container, serialization
from flograph.engine.cache import OutputCache
from flograph.engine.runstats import RunHistory
from flograph.engine import cache_persistence as cp


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def _two_node_graph(registry):
    graph = Graph()
    src = registry.instantiate("flograph.util.constant", pos=(0, 0))
    dst = registry.instantiate("flograph.util.constant", pos=(200, 0))
    graph.add_node(src)
    graph.add_node(dst)
    return graph, src, dst


def _plan_and_write(graph, cache, path, *, prev_path=None, history=None,
                    include_cache=True, carry_all=False):
    plan = cp.plan_project_save(graph, cache, history or RunHistory(),
                                include_cache=include_cache,
                                carry_all=carry_all)
    return cp.write_project(path, plan, prev_path=prev_path)


class TestSniff:
    def test_bundle_vs_json_vs_missing(self, tmp_path, registry):
        graph, src, _ = _two_node_graph(registry)

        bundle = tmp_path / "b.flograph"
        _plan_and_write(graph, OutputCache(), bundle)
        assert container.is_bundle(bundle)

        plain = tmp_path / "p.flograph"
        serialization.save(graph, plain)
        assert not container.is_bundle(plain)

        assert not container.is_bundle(tmp_path / "nope.flograph")


class TestRoundTrip:
    def test_graph_and_cache_come_back(self, tmp_path, registry):
        graph, src, dst = _two_node_graph(registry)
        cache = OutputCache()
        df = pd.DataFrame({"a": [1, 2, 3]})
        cache.set(src.id, {"value": df}, wall_time=0.02)
        path = tmp_path / "proj.flograph"

        assert _plan_and_write(graph, cache, path) == 1

        reloaded = serialization.load(path, registry)
        assert set(reloaded.nodes) == {src.id, dst.id}

        fresh = OutputCache()
        registered = cp.register_cache(reloaded, fresh, path)
        assert registered == [src.id]
        assert not fresh.is_resident(src.id), "opening loads no blob"
        pd.testing.assert_frame_equal(fresh.outputs_for(src.id)["value"], df)

    def test_run_history_rides_along(self, tmp_path, registry):
        from flograph.engine.runstats import RunRecord
        graph, src, _ = _two_node_graph(registry)
        history = RunHistory()
        history.add(RunRecord(wall_time=1.5))
        path = tmp_path / "proj.flograph"
        _plan_and_write(graph, OutputCache(), path, history=history)

        loaded = cp.load_run_history(path)
        assert [r.wall_time for r in loaded] == [1.5]

    def test_reset_cache_still_writes_an_openable_bundle(self, tmp_path,
                                                        registry):
        graph, src, _ = _two_node_graph(registry)
        path = tmp_path / "proj.flograph"
        _plan_and_write(graph, OutputCache(), path)   # nothing cached
        assert container.is_bundle(path)
        assert serialization.load(path, registry).nodes
        assert cp.register_cache(graph, OutputCache(), path) == []


class TestCarryOver:
    def test_unloaded_blob_survives_a_resave_without_being_read(
            self, tmp_path, registry, monkeypatch):
        graph, src, dst = _two_node_graph(registry)
        cache = OutputCache()
        cache.set(src.id, {"value": "kept"}, wall_time=0.01)
        path = tmp_path / "proj.flograph"
        _plan_and_write(graph, cache, path)

        # reopen lazily: the entry is spilled, not resident
        fresh = OutputCache()
        cp.register_cache(graph, fresh, path)
        assert not fresh.is_resident(src.id)

        def boom(*a, **k):
            raise AssertionError("a carry-over save must not unpickle a blob")

        monkeypatch.setattr(cp, "load_blob", boom)
        _plan_and_write(graph, fresh, path, prev_path=path)

        monkeypatch.undo()
        again = OutputCache()
        cp.register_cache(graph, again, path)
        assert again.outputs_for(src.id) == {"value": "kept"}

    def test_save_as_copies_the_cache_to_the_new_file(self, tmp_path,
                                                      registry):
        graph, src, _ = _two_node_graph(registry)
        cache = OutputCache()
        cache.set(src.id, {"value": "here"}, wall_time=0.01)
        first = tmp_path / "first.flograph"
        _plan_and_write(graph, cache, first)

        fresh = OutputCache()
        cp.register_cache(graph, fresh, first)          # spilled
        second = tmp_path / "second.flograph"
        _plan_and_write(graph, fresh, second, prev_path=first)

        moved = OutputCache()
        assert cp.register_cache(graph, moved, second) == [src.id]
        assert moved.outputs_for(src.id) == {"value": "here"}
        # the original is untouched
        assert cp.register_cache(graph, OutputCache(), first) == [src.id]


class TestCarryAll:
    def test_mid_run_save_keeps_blobs_and_updates_the_graph(self, tmp_path,
                                                            registry):
        graph, src, dst = _two_node_graph(registry)
        cache = OutputCache()
        cache.set(src.id, {"value": "v1"}, wall_time=0.01)
        path = tmp_path / "proj.flograph"
        _plan_and_write(graph, cache, path)

        # graph changes, cache is "mid-flight" — carry everything, pickle
        # nothing
        graph.set_param(dst.id, "value", "edited during run")
        plan = cp.plan_project_save(graph, cache, RunHistory(), carry_all=True)
        assert plan.blobs == []
        cp.write_project(path, plan, prev_path=path, carry_all=True)

        reloaded = serialization.load(path, registry)
        assert reloaded.nodes[dst.id].params["value"] == "edited during run"
        fresh = OutputCache()
        assert cp.register_cache(reloaded, fresh, path) == [src.id]


class TestWithoutCache:
    def test_off_writes_plain_json_and_drops_the_sidecar(self, tmp_path,
                                                         registry):
        graph, src, _ = _two_node_graph(registry)
        cache = OutputCache()
        cache.set(src.id, {"value": "x"}, wall_time=0.01)
        path = tmp_path / "proj.flograph"
        _plan_and_write(graph, cache, path)             # bundle first
        assert container.is_bundle(path)

        # now a save with the box off
        assert _plan_and_write(graph, cache, path, include_cache=False) == 0
        assert not container.is_bundle(path)
        json.loads(path.read_text())                    # it's plain JSON
        assert cp.register_cache(graph, OutputCache(), path) == []

    def test_off_removes_a_legacy_sidecar_folder(self, tmp_path, registry):
        graph, src, _ = _two_node_graph(registry)
        cache = OutputCache()
        cache.set(src.id, {"value": "x"}, wall_time=0.01)
        path = tmp_path / "proj.flograph"
        cp.save_cache(graph, cache, path)               # legacy folder
        assert (tmp_path / "proj.flograph.cache").is_dir()

        serialization.save(graph, path)
        _plan_and_write(graph, cache, path, include_cache=False)
        assert not (tmp_path / "proj.flograph.cache").exists()


class TestFoldsInLegacySidecar:
    def test_first_bundled_save_absorbs_and_removes_the_folder(self, tmp_path,
                                                              registry):
        graph, src, _ = _two_node_graph(registry)
        cache = OutputCache()
        cache.set(src.id, {"value": "legacy"}, wall_time=0.01)
        path = tmp_path / "proj.flograph"
        serialization.save(graph, path)
        cp.save_cache(graph, cache, path)               # old folder layout
        folder = tmp_path / "proj.flograph.cache"
        assert folder.is_dir()
        assert cp.has_sidecar(path)

        # a lazy reopen registers the folder's entry as spilled, then a
        # bundled save folds it in
        fresh = OutputCache()
        cp.register_cache(graph, fresh, path)
        _plan_and_write(graph, fresh, path, prev_path=path)

        assert container.is_bundle(path)
        assert not folder.exists()
        restored = OutputCache()
        assert cp.register_cache(graph, restored, path) == [src.id]
        assert restored.outputs_for(src.id) == {"value": "legacy"}


class TestDegrades:
    def test_a_truncated_bundle_opens_to_an_empty_cache(self, tmp_path,
                                                        registry):
        graph, src, _ = _two_node_graph(registry)
        cache = OutputCache()
        cache.set(src.id, {"value": "x"}, wall_time=0.01)
        path = tmp_path / "proj.flograph"
        _plan_and_write(graph, cache, path)

        raw = bytearray(path.read_bytes())
        path.write_bytes(raw[:len(raw) // 2])          # chop it in half

        # not fatal: no entries restored, no exception
        assert cp.resolve_entries(graph, path) == []
        assert cp.sidecar_stats(path) == (0, 0)


class TestContainerPrimitives:
    def test_writer_discards_tmp_when_not_committed(self, tmp_path):
        path = tmp_path / "x.flograph"
        try:
            with container.BundleWriter(path) as w:
                w.write_project({"schema": 1})
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert not path.exists()
        assert not path.with_name("x.flograph.tmp").exists()

    def test_blobs_are_stored_not_deflated(self, tmp_path, registry):
        graph, src, _ = _two_node_graph(registry)
        cache = OutputCache()
        cache.set(src.id, {"value": "x" * 5000}, wall_time=0.01)
        path = tmp_path / "proj.flograph"
        _plan_and_write(graph, cache, path)
        with zipfile.ZipFile(path) as zf:
            blob = zf.getinfo(container.blob_member(src.id))
            assert blob.compress_type == zipfile.ZIP_STORED
            project = zf.getinfo(container.PROJECT_MEMBER)
            assert project.compress_type == zipfile.ZIP_DEFLATED
