"""Node output caches persisted alongside a .flopy save file: fingerprint
invalidation, round trip, and graceful degradation when the side-car is
missing or stale."""
import pandas as pd
import pytest

from flopy.core import Graph, NodeRegistry
from flopy.engine.cache import OutputCache
from flopy.engine.cache_persistence import (
    load_cache, node_fingerprint, save_cache,
)


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def make_graph(registry):
    graph = Graph()
    const = registry.instantiate("flopy.util.constant", pos=(0, 0))
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
        const = registry.instantiate("flopy.util.constant", pos=(0, 0))
        script = registry.instantiate("flopy.scripting.python_script", pos=(200, 0))
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
        project_path = tmp_path / "proj.flopy"

        save_cache(graph, cache, project_path)
        assert (tmp_path / "proj.flopy.cache" / "manifest.json").exists()

        fresh_cache = OutputCache()
        restored = load_cache(graph, fresh_cache, project_path)
        assert restored == [const.id]
        assert fresh_cache.get(const.id).outputs == {"value": "hello"}

    def test_restores_dataframe_output(self, registry, tmp_path):
        graph, const = make_graph(registry)
        cache = OutputCache()
        df = pd.DataFrame({"a": [1, 2, 3]})
        cache.set(const.id, {"value": df}, wall_time=0.02)
        project_path = tmp_path / "proj.flopy"

        save_cache(graph, cache, project_path)
        fresh_cache = OutputCache()
        restored = load_cache(graph, fresh_cache, project_path)
        assert restored == [const.id]
        pd.testing.assert_frame_equal(fresh_cache.get(const.id).outputs["value"], df)

    def test_stale_after_param_change_not_restored(self, registry, tmp_path):
        graph, const = make_graph(registry)
        cache = OutputCache()
        cache.set(const.id, {"value": "hello"}, wall_time=0.01)
        project_path = tmp_path / "proj.flopy"
        save_cache(graph, cache, project_path)

        graph.set_param(const.id, "value", "edited after save")
        fresh_cache = OutputCache()
        restored = load_cache(graph, fresh_cache, project_path)
        assert restored == []
        assert fresh_cache.get(const.id) is None

    def test_missing_side_car_degrades_to_empty(self, registry, tmp_path):
        graph, const = make_graph(registry)
        fresh_cache = OutputCache()
        restored = load_cache(graph, fresh_cache, tmp_path / "never_saved.flopy")
        assert restored == []

    def test_corrupt_manifest_degrades_to_empty(self, registry, tmp_path):
        graph, const = make_graph(registry)
        project_path = tmp_path / "proj.flopy"
        cache_dir = tmp_path / "proj.flopy.cache"
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
        project_path = tmp_path / "proj.flopy"
        save_cache(graph, cache, project_path)  # must not raise
        cache_dir = tmp_path / "proj.flopy.cache"
        # nothing persisted, no crash, no orphaned manifest
        assert not (cache_dir / "manifest.json").exists()

    def test_reset_cache_prunes_side_car_on_next_save(self, registry, tmp_path):
        graph, const = make_graph(registry)
        cache = OutputCache()
        cache.set(const.id, {"value": "hello"}, wall_time=0.01)
        project_path = tmp_path / "proj.flopy"
        save_cache(graph, cache, project_path)
        cache_dir = tmp_path / "proj.flopy.cache"
        assert (cache_dir / "manifest.json").exists()

        cache.clear()
        save_cache(graph, cache, project_path)
        assert not (cache_dir / "manifest.json").exists()
        assert not cache_dir.exists()
