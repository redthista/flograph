"""Tests for scripts/flopy_to_flograph.py — the one-shot .flopy -> .flograph
project migrator. The script is standalone (not part of the package), so we
load it by path."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from flograph.core.serialization import load

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "flopy_to_flograph.py"


@pytest.fixture(scope="module")
def converter():
    spec = importlib.util.spec_from_file_location("flopy_to_flograph", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _legacy_project() -> dict:
    """An old-format project with a builtin flopy.* node and a user.* node."""
    return {
        "flopy_version": "0.1.0",
        "schema": 1,
        "graph": {
            "nodes": [
                {"id": "a", "type": "flopy.util.constant", "pos": [0, 0],
                 "params": {"value": "hi"}, "code": None, "label": None},
                {"id": "b", "type": "user.mygroup.custom", "pos": [200, 0],
                 "params": {}, "code": None, "label": None},
            ],
            "connections": [],
            "frames": [],
        },
    }


def test_convert_project_data_rewrites_only_builtin_ids(converter):
    data, rewritten = converter.convert_project_data(_legacy_project())
    assert rewritten == 1
    types = [n["type"] for n in data["graph"]["nodes"]]
    assert "flograph.util.constant" in types      # builtin re-prefixed
    assert "user.mygroup.custom" in types          # user id untouched
    assert "flograph_version" in data and "flopy_version" not in data


def test_convert_file_writes_flograph_sibling(converter, tmp_path):
    src = tmp_path / "proj.flopy"
    src.write_text(json.dumps(_legacy_project()))

    out_path, rewritten = converter.convert_file(src)

    assert out_path == tmp_path / "proj.flograph"
    assert out_path.exists()
    assert rewritten == 1
    assert src.exists()  # original kept by default


def test_converted_file_loads_through_serialization(converter, tmp_path, registry):
    src = tmp_path / "proj.flopy"
    src.write_text(json.dumps(_legacy_project()))
    out_path, _ = converter.convert_file(src)

    graph = load(out_path, registry)
    # the builtin now resolves to a real spec (not a broken placeholder)
    assert graph.nodes["a"].type_id == "flograph.util.constant"
    assert not graph.nodes["a"].spec.broken


def test_convert_file_renames_cache_sidecar(converter, tmp_path):
    src = tmp_path / "proj.flopy"
    src.write_text(json.dumps(_legacy_project()))
    cache = tmp_path / "proj.flopy.cache"
    cache.mkdir()
    (cache / "manifest.json").write_text("{}")

    out_path, _ = converter.convert_file(src)

    new_cache = tmp_path / "proj.flograph.cache"
    assert new_cache.is_dir()
    assert (new_cache / "manifest.json").exists()
    assert not cache.exists()


def test_delete_original_removes_source(converter, tmp_path):
    src = tmp_path / "proj.flopy"
    src.write_text(json.dumps(_legacy_project()))
    converter.convert_file(src, delete_original=True)
    assert not src.exists()
    assert (tmp_path / "proj.flograph").exists()


def test_stem_containing_flopy_only_swaps_suffix(converter, tmp_path):
    src = tmp_path / "flopy.flopy"
    src.write_text(json.dumps(_legacy_project()))
    out_path, _ = converter.convert_file(src)
    assert out_path.name == "flopy.flograph"
