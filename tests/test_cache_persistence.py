"""Node output caches persisted alongside a .flograph save file: fingerprint
invalidation, round trip, graceful degradation when the side-car is
missing or stale, and compression (schema 3) with backwards compatibility."""
import errno
import json
import pickle
import zlib

import pandas as pd
import pytest

from flograph.core import Graph, NodeRegistry
from flograph.engine.cache import OutputCache
from flograph.engine.cache_persistence import (
    CACHE_SCHEMA, load_blob, load_cache, node_fingerprint, plan_cache_save,
    save_cache, save_failure_text, sidecar_stats, write_cache_plan,
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


class TestFingerprint:
    def test_stable_for_unchanged_node(self, registry):
        graph, const = make_graph(registry)
        fp1 = node_fingerprint(graph, const.id, {})
        fp2 = node_fingerprint(graph, const.id, {})
        assert fp1 == fp2

    def test_changes_with_params(self, registry):
        graph, const = make_graph(registry)
        fp1 = node_fingerprint(graph, const.id, {})
        graph.set_param(const.id, "value", "different")
        fp2 = node_fingerprint(graph, const.id, {})
        assert fp1 != fp2

    def test_changes_propagate_downstream(self, registry):
        graph = Graph()
        const = registry.instantiate("flograph.util.constant", pos=(0, 0))
        script = registry.instantiate("flograph.scripting.python_script", pos=(200, 0))
        graph.add_node(const)
        graph.add_node(script)
        graph.connect(const.id, "value", script.id, "in1")
        fp1 = node_fingerprint(graph, script.id, {})
        graph.set_param(const.id, "value", "changed upstream")
        fp2 = node_fingerprint(graph, script.id, {})
        assert fp1 != fp2, "downstream fingerprint must change when upstream does"


class TestSaveLoadRoundTrip:
    def test_restores_matching_cache(self, registry, tmp_path):
        graph, const = make_graph(registry)
        cache = OutputCache()
        cache.set(const.id, {"value": "hello"}, wall_time=0.01)
        project_path = tmp_path / "proj.flograph"

        save_cache(graph, cache, project_path)
        assert (tmp_path / "proj.flograph.cache" / "manifest.json").exists()

        fresh_cache = OutputCache()
        restored = load_cache(graph, fresh_cache, project_path)
        assert restored == [const.id]
        assert fresh_cache.get(const.id).outputs == {"value": "hello"}

    def test_restores_dataframe_output(self, registry, tmp_path):
        graph, const = make_graph(registry)
        cache = OutputCache()
        df = pd.DataFrame({"a": [1, 2, 3]})
        cache.set(const.id, {"value": df}, wall_time=0.02)
        project_path = tmp_path / "proj.flograph"

        save_cache(graph, cache, project_path)
        fresh_cache = OutputCache()
        restored = load_cache(graph, fresh_cache, project_path)
        assert restored == [const.id]
        pd.testing.assert_frame_equal(fresh_cache.get(const.id).outputs["value"], df)

    def test_stale_after_param_change_not_restored(self, registry, tmp_path):
        graph, const = make_graph(registry)
        cache = OutputCache()
        cache.set(const.id, {"value": "hello"}, wall_time=0.01)
        project_path = tmp_path / "proj.flograph"
        save_cache(graph, cache, project_path)

        graph.set_param(const.id, "value", "edited after save")
        fresh_cache = OutputCache()
        restored = load_cache(graph, fresh_cache, project_path)
        assert restored == []
        assert fresh_cache.get(const.id) is None

    def test_missing_side_car_degrades_to_empty(self, registry, tmp_path):
        graph, const = make_graph(registry)
        fresh_cache = OutputCache()
        restored = load_cache(graph, fresh_cache, tmp_path / "never_saved.flograph")
        assert restored == []

    def test_corrupt_manifest_degrades_to_empty(self, registry, tmp_path):
        graph, const = make_graph(registry)
        project_path = tmp_path / "proj.flograph"
        cache_dir = tmp_path / "proj.flograph.cache"
        cache_dir.mkdir()
        (cache_dir / "manifest.json").write_text("{not json")
        fresh_cache = OutputCache()
        restored = load_cache(graph, fresh_cache, project_path)
        assert restored == []

    def test_unpicklable_output_skipped_without_error(self, registry, tmp_path):
        graph, const = make_graph(registry)
        cache = OutputCache()
        unpicklable = lambda: None  # noqa: E731 — functions aren't picklable
        cache.set(const.id, {"value": unpicklable}, wall_time=0.0)
        project_path = tmp_path / "proj.flograph"
        save_cache(graph, cache, project_path)  # must not raise
        cache_dir = tmp_path / "proj.flograph.cache"
        # nothing persisted, no crash, no orphaned manifest
        assert not (cache_dir / "manifest.json").exists()

    def test_reset_cache_prunes_side_car_on_next_save(self, registry, tmp_path):
        graph, const = make_graph(registry)
        cache = OutputCache()
        cache.set(const.id, {"value": "hello"}, wall_time=0.01)
        project_path = tmp_path / "proj.flograph"
        save_cache(graph, cache, project_path)
        cache_dir = tmp_path / "proj.flograph.cache"
        assert (cache_dir / "manifest.json").exists()

        cache.clear()
        save_cache(graph, cache, project_path)
        assert not (cache_dir / "manifest.json").exists()
        assert not cache_dir.exists()


class TestCompression:
    """Schema 3: blobs are zlib-compressed, the reader sniffs rather than
    trusting anything, and every older era keeps loading."""

    def _saved_project(self, registry, tmp_path, value="hello"):
        graph, const = make_graph(registry)
        cache = OutputCache()
        cache.set(const.id, {"value": value}, wall_time=0.01)
        return graph, const, cache, tmp_path / "proj.flograph"

    def test_blobs_written_compressed_and_round_trip(self, registry, tmp_path):
        graph, const, cache, path = self._saved_project(registry, tmp_path)

        n = save_cache(graph, cache, path)

        assert n == 1
        blob = (tmp_path / "proj.flograph.cache" / f"{const.id}.pkl").read_bytes()
        assert blob[:1] != b"\x80", "a compressed blob must not look like a raw pickle"
        zlib.decompress(blob)   # raises unless it really is a zlib stream
        manifest = json.loads(
            (tmp_path / "proj.flograph.cache" / "manifest.json").read_text())
        assert manifest["cache_schema"] == CACHE_SCHEMA == 3
        assert manifest["nodes"][const.id]["codec"] == "zlib"

        fresh = OutputCache()
        assert load_cache(graph, fresh, path) == [const.id]
        assert fresh.get(const.id).outputs == {"value": "hello"}

    def test_compress_off_writes_a_raw_pickle(self, registry, tmp_path):
        graph, const, cache, path = self._saved_project(registry, tmp_path)

        save_cache(graph, cache, path, compress=False)

        blob = (tmp_path / "proj.flograph.cache" / f"{const.id}.pkl").read_bytes()
        assert blob[:1] == b"\x80"
        manifest = json.loads(
            (tmp_path / "proj.flograph.cache" / "manifest.json").read_text())
        assert manifest["nodes"][const.id]["codec"] == "raw"

        fresh = OutputCache()
        assert load_cache(graph, fresh, path) == [const.id]
        assert fresh.get(const.id).outputs == {"value": "hello"}

    def test_load_blob_reads_both_eras_by_sniffing(self, registry, tmp_path):
        graph, const, cache, path = self._saved_project(registry, tmp_path,
                                                        value="zipped")
        save_cache(graph, cache, path)
        # overwrite with a raw pickle: same side-car, other era
        (tmp_path / "proj.flograph.cache" / f"{const.id}.pkl").write_bytes(
            pickle.dumps({"value": "raw"}, protocol=pickle.HIGHEST_PROTOCOL))
        assert load_blob(path, const.id) == {"value": "raw"}

        graph2, const2, cache2, path2 = self._saved_project(
            registry, tmp_path / "second", value="hello")
        save_cache(graph2, cache2, path2)
        assert load_blob(path2, const2.id) == {"value": "hello"}

    def test_legacy_raw_side_car_still_loads(self, registry, tmp_path):
        """A schema-2 side-car written by an old build: raw pickles, no
        codec field. Backwards compat is the point of the sniff."""
        graph, const = make_graph(registry)
        cache_dir = tmp_path / "proj.flograph.cache"
        cache_dir.mkdir()
        outputs = {"value": "old-era hello"}
        (cache_dir / f"{const.id}.pkl").write_bytes(
            pickle.dumps(outputs, protocol=pickle.HIGHEST_PROTOCOL))
        fp = node_fingerprint(graph, const.id, {})
        (cache_dir / "manifest.json").write_text(json.dumps({
            "cache_schema": 2,
            "nodes": {const.id: {"fingerprint": fp, "wall_time": 0.01,
                                 "bytes": 5, "ports": ["value"]}},
        }))

        fresh = OutputCache()
        restored = load_cache(graph, fresh, tmp_path / "proj.flograph")
        assert restored == [const.id]
        assert fresh.get(const.id).outputs == outputs

    def test_progress_counts_every_planned_entry(self, registry, tmp_path):
        graph, const, cache, path = self._saved_project(registry, tmp_path)
        seen = []

        n = save_cache(graph, cache, path,
                       progress=lambda done, total: seen.append((done, total)))

        assert n == 1
        assert seen[-1] == (1, 1)

    def test_plan_write_split_matches_the_one_call_form(self, registry, tmp_path):
        graph, const, cache, path = self._saved_project(registry, tmp_path)

        plan = plan_cache_save(graph, cache)
        recorded = write_cache_plan(path, plan)

        fresh = OutputCache()
        assert load_cache(graph, fresh, path) == [const.id]
        assert recorded == 1
        assert fresh.get(const.id).outputs == {"value": "hello"}

    def test_plan_skips_env_nodes_and_uncached_nodes(self, registry, tmp_path):
        graph, const = make_graph(registry)     # constant, never run: no entry
        assert plan_cache_save(graph, OutputCache()) == []

    def test_a_write_failure_propagates_rather_than_vanishing(self, registry, tmp_path):
        graph, const, cache, path = self._saved_project(registry, tmp_path)
        # a FILE where the side-car directory goes: mkdir must fail loudly
        (tmp_path / "proj.flograph.cache").write_text("not a directory")

        with pytest.raises(OSError):
            save_cache(graph, cache, path)

    def test_manifest_records_both_sizes_and_stats_sum_them(
            self, registry, tmp_path):
        graph, const, cache, path = self._saved_project(registry, tmp_path,
                                                        value="x" * 5000)
        save_cache(graph, cache, path)
        manifest = json.loads(
            (tmp_path / "proj.flograph.cache" / "manifest.json").read_text())
        entry = manifest["nodes"][const.id]
        assert isinstance(entry["raw_bytes"], int) and entry["raw_bytes"] > 0
        assert isinstance(entry["disk_bytes"], int) and entry["disk_bytes"] > 0
        assert entry["disk_bytes"] < entry["raw_bytes"]     # it compressed

        disk, raw = sidecar_stats(path)
        assert disk == entry["disk_bytes"]
        assert raw == entry["raw_bytes"]

    def test_raw_equals_disk_when_compression_is_off(self, registry, tmp_path):
        graph, const, cache, path = self._saved_project(registry, tmp_path)
        save_cache(graph, cache, path, compress=False)
        manifest = json.loads(
            (tmp_path / "proj.flograph.cache" / "manifest.json").read_text())
        entry = manifest["nodes"][const.id]
        assert entry["codec"] == "raw"
        assert entry["raw_bytes"] == entry["disk_bytes"]

    def test_stats_of_nothing_are_zero(self, tmp_path):
        assert sidecar_stats(tmp_path / "never.flograph") == (0, 0)

    def test_arrow_string_frames_survive_the_compressed_round_trip(
            self, registry, tmp_path):
        """Protocol-5 pickling hands out-of-band column buffers to the
        writer as pickle.PickleBuffer, which has no len() — pandas'
        Arrow-backed strings (normalize_strings' layout) hit it on every
        frame containing text. The sink must take buffers; this used to
        raise inside every dump and silently skip every node."""
        from flograph.engine.frames import normalize_strings

        graph, const = make_graph(registry)
        df = pd.DataFrame({"name": [f"row-{i:04d}" for i in range(500)]})
        cache = OutputCache()
        cache.set(const.id, {"value": normalize_strings(df)}, wall_time=0.01)
        project_path = tmp_path / "proj.flograph"

        n = save_cache(graph, cache, project_path)
        assert n == 1, "an arrow-string frame must not be skipped"

        fresh = OutputCache()
        assert load_cache(graph, fresh, project_path) == [const.id]
        pd.testing.assert_frame_equal(
            fresh.get(const.id).outputs["value"], normalize_strings(df))


class TestSaveFailureText:
    def test_disk_full_gets_its_own_sentence(self):
        exc = OSError(errno.ENOSPC, "No space left on device")
        text = save_failure_text('"/somewhere/proj.flograph"', exc)
        assert "full" in text
        assert "Reset Caches" in text

    def test_quota_full_says_so_too(self):
        exc = OSError(errno.EDQUOT, "Disk quota exceeded")
        assert "full" in save_failure_text("the cached results", exc)

    def test_other_os_errors_report_the_os_reason(self):
        exc = OSError(13, "Permission denied")
        text = save_failure_text('"p.flograph"', exc)
        assert "Permission denied" in text
        assert "full" not in text
