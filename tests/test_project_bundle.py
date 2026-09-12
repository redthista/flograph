"""The single-file .flograph bundle: a zip holding project.json plus a
cache/ tree. Covers the sniff, the reader/writer, and the save/open flow
through cache_persistence — carry-over of unloaded blobs, Save As, a save
made during a run, save-without-cache, results a save could not store, what
a reopen could not restore, and folding in a legacy side-car folder.
"""
import json
import threading
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


def _plan_and_write(graph, cache, path, *, prev_path=None, history=None):
    plan = cp.plan_project_save(graph, cache, history or RunHistory())
    return cp.write_project(path, plan, prev_path=prev_path)


def _chain(registry, length=3):
    """constant -> reroute -> reroute ..., every link wired `value`."""
    graph = Graph()
    nodes = [graph.add_node(registry.instantiate("flograph.util.constant"))]
    for i in range(1, length):
        node = graph.add_node(registry.instantiate(
            "flograph.util.reroute", pos=(200 * i, 0)))
        graph.connect(nodes[-1].id, "value", node.id, "value")
        nodes.append(node)
    return graph, nodes


def _rewrite_manifest(path, change):
    """Rewrite the test's own bundle with its manifest passed through
    `change` — the one way to fake a file some other flograph wrote."""
    with zipfile.ZipFile(path) as zin:
        members = [(info, zin.read(info.filename)) for info in zin.infolist()]
    with zipfile.ZipFile(path, "w") as zout:
        for info, data in members:
            if info.filename == container.MANIFEST_MEMBER:
                data = json.dumps(change(json.loads(data))).encode()
            zout.writestr(info, data)


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


class TestSaveDuringARun:
    """Issue 8: a save made mid-run copied the previous file's blobs *and*
    manifest, so a node re-run since came back with its old value under a
    fingerprint that still matched."""

    def test_the_value_reopened_is_the_one_the_run_made(self, tmp_path,
                                                        registry):
        graph, src, dst = _two_node_graph(registry)
        cache = OutputCache()
        cache.set(src.id, {"value": "before the run"}, wall_time=0.01)
        path = tmp_path / "proj.flograph"
        _plan_and_write(graph, cache, path)

        # re-run with the same params — Reset Caches, or a source that
        # changed: same fingerprint, new value — and saved before it ends
        cache.evict(src.id)
        cache.set(src.id, {"value": "after the run"}, wall_time=0.01)
        graph.set_param(dst.id, "value", "edited during run")
        _plan_and_write(graph, cache, path, prev_path=path)

        reloaded = serialization.load(path, registry)
        assert reloaded.nodes[dst.id].params["value"] == "edited during run"
        fresh = OutputCache()
        assert cp.register_cache(reloaded, fresh, path) == [src.id]
        assert fresh.outputs_for(src.id) == {"value": "after the run"}

    def test_a_node_still_being_worked_out_re_runs_rather_than_goes_stale(
            self, tmp_path, registry):
        graph, src, _ = _two_node_graph(registry)
        cache = OutputCache()
        cache.set(src.id, {"value": "old"}, wall_time=0.01)
        path = tmp_path / "proj.flograph"
        _plan_and_write(graph, cache, path)

        cache.evict(src.id)          # dirtied for its re-run, not back yet
        _plan_and_write(graph, cache, path, prev_path=path)

        assert cp.register_cache(graph, OutputCache(), path) == []


class TestSkippedResults:
    def test_a_result_that_cannot_be_stored_is_named(self, tmp_path,
                                                     registry):
        graph, src, dst = _two_node_graph(registry)
        cache = OutputCache()
        cache.set(src.id, {"value": threading.Lock()}, wall_time=0.01)
        cache.set(dst.id, {"value": "fine"}, wall_time=0.01)
        skipped = []
        plan = cp.plan_project_save(graph, cache, RunHistory())

        recorded = cp.write_project(tmp_path / "p.flograph", plan,
                                    skipped=skipped)

        assert recorded == 1
        assert skipped == [src.id]


class TestRestoreReport:
    """Issue 8: what a reopen could not restore, and where it starts."""

    def test_nothing_to_say_when_everything_came_back(self, tmp_path,
                                                      registry):
        graph, nodes = _chain(registry)
        cache = OutputCache()
        for node in nodes:
            cache.set(node.id, {"value": 1}, wall_time=0.01)
        path = tmp_path / "chain.flograph"
        _plan_and_write(graph, cache, path)

        restored = cp.register_cache(graph, OutputCache(), path)
        report = cp.restore_report(graph, path, restored)

        assert len(restored) == 3
        assert (report.cached, report.stale, report.starts) == (3, [], [])
        assert not report.unreadable

    def test_an_edit_upstream_is_named_where_it_starts(self, tmp_path,
                                                       registry):
        graph, (const, middle, last) = _chain(registry)
        cache = OutputCache()
        for node in (const, middle, last):
            cache.set(node.id, {"value": 1}, wall_time=0.01)
        path = tmp_path / "chain.flograph"
        _plan_and_write(graph, cache, path)

        graph.set_param(const.id, "value", "changed since the save")
        restored = cp.register_cache(graph, OutputCache(), path)
        report = cp.restore_report(graph, path, restored)

        assert restored == []
        assert report.cached == 3
        assert set(report.stale) == {const.id, middle.id, last.id}
        assert report.starts == [const.id]

    def test_the_start_is_found_through_a_node_that_was_never_cached(
            self, tmp_path, registry):
        graph, (const, middle, last) = _chain(registry)
        cache = OutputCache()
        cache.set(const.id, {"value": 1}, wall_time=0.01)
        cache.set(last.id, {"value": 1}, wall_time=0.01)   # middle: never
        path = tmp_path / "chain.flograph"
        _plan_and_write(graph, cache, path)

        graph.set_param(const.id, "value", "changed since the save")
        report = cp.restore_report(
            graph, path, cp.register_cache(graph, OutputCache(), path))

        assert set(report.stale) == {const.id, last.id}
        assert report.starts == [const.id]

    def test_a_manifest_from_a_newer_flograph_is_unreadable_not_stale(
            self, tmp_path, registry):
        graph, nodes = _chain(registry, length=2)
        cache = OutputCache()
        for node in nodes:
            cache.set(node.id, {"value": 1}, wall_time=0.01)
        path = tmp_path / "chain.flograph"
        _plan_and_write(graph, cache, path)
        _rewrite_manifest(path, lambda m: {**m, "cache_schema": 999})

        restored = cp.register_cache(graph, OutputCache(), path)
        report = cp.restore_report(graph, path, restored)

        assert restored == []
        assert report.unreadable
        assert report.cached == 2 and report.stale == []

    def test_no_cache_in_the_file_is_nothing_to_report(self, tmp_path,
                                                       registry):
        graph, _ = _chain(registry, length=2)
        path = tmp_path / "bare.flograph"
        _plan_and_write(graph, OutputCache(), path)

        report = cp.restore_report(graph, path, [])

        assert report == cp.RestoreReport()


class TestWorkflowExport:
    def test_flowf_is_plain_json_the_graph_loads_from(self, tmp_path,
                                                      registry):
        # Export is a plain serialization.save; a .flowf round-trips the
        # graph and carries no cache.
        graph, src, dst = _two_node_graph(registry)
        p = tmp_path / "wf.flowf"
        serialization.save(graph, p)
        assert not container.is_bundle(p)
        json.loads(p.read_text())
        reloaded = serialization.load(p, registry)
        assert set(reloaded.nodes) == {src.id, dst.id}
        assert cp.register_cache(reloaded, OutputCache(), p) == []


class TestUserNodeCache:
    """A project that carries a custom node's script inside it (see
    `serialization._portable_code`) still restores that node's cached
    output — the cache fingerprint is over the node's source, and the
    embedded copy is byte-identical to the library it came from."""

    SAMPLE = (
        'NODE = {"label": "Read CSV", "category": "IO", "inputs": [],\n'
        '        "outputs": [("value", "string")]}\n'
        'PARAMS = [{"name": "value", "type": "string", "default": "x"}]\n'
        'def run(ctx):\n    return ctx.params["value"]\n'
    )

    def _graph_with_cached_user_node(self, reg, type_id):
        graph = Graph()
        node = reg.instantiate(type_id)
        graph.add_node(node)
        cache = OutputCache()
        cache.set(node.id, {"value": "computed once"}, wall_time=0.03)
        return graph, node, cache

    def test_cache_survives_on_a_machine_that_has_the_user_node(
            self, tmp_path, registry):
        from flograph.core import user_nodes
        nodes_dir = tmp_path / "nodes"
        nodes_dir.mkdir()
        type_id = user_nodes.write_user_node(
            nodes_dir, "grp", "My Node", self.SAMPLE)
        reg = NodeRegistry()
        reg.load_builtins()
        reg.load_user_nodes(nodes_dir)

        graph, node, cache = self._graph_with_cached_user_node(reg, type_id)
        path = tmp_path / "proj.flograph"
        assert _plan_and_write(graph, cache, path) == 1

        reloaded = serialization.load(path, reg)
        assert not reloaded.node(node.id).forked  # relinked to the library
        fresh = OutputCache()
        assert cp.register_cache(reloaded, fresh, path) == [node.id]
        assert fresh.outputs_for(node.id) == {"value": "computed once"}

    def test_cache_survives_to_a_machine_without_the_user_node(
            self, tmp_path, registry):
        from flograph.core import user_nodes
        nodes_dir = tmp_path / "nodes"
        nodes_dir.mkdir()
        type_id = user_nodes.write_user_node(
            nodes_dir, "grp", "My Node", self.SAMPLE)
        author = NodeRegistry()
        author.load_builtins()
        author.load_user_nodes(nodes_dir)

        graph, node, cache = self._graph_with_cached_user_node(author, type_id)
        path = tmp_path / "proj.flograph"
        _plan_and_write(graph, cache, path)

        recipient = NodeRegistry()
        recipient.load_builtins()  # no load_user_nodes
        reloaded = serialization.load(path, recipient)
        fresh = OutputCache()
        assert cp.register_cache(reloaded, fresh, path) == [node.id]
        assert fresh.outputs_for(node.id) == {"value": "computed once"}


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
