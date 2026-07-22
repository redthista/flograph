"""Persist node output caches alongside a .flograph project file.

A side-car directory named "<project>.flograph.cache/" holds one pickle blob
per cached node plus a manifest keyed by a fingerprint of that node's type,
source, and params, folded recursively with every upstream node's
fingerprint — so any change to a node or anything upstream of it invalidates
its entry. This deliberately does not touch the project file's own
SCHEMA_VERSION: the .flograph JSON itself is untouched, only a sibling
directory is added.

Loading is never fatal: a missing manifest, a schema mismatch, a stale
fingerprint, or a corrupt/unpicklable blob just means that node is left
dirty, exactly as if there were no side-car cache at all. Pickling arbitrary
node outputs (DataFrames, matplotlib Figures, ...) is not guaranteed stable
across library/Python versions — every read and write of a blob is wrapped
so one bad node can never block the rest of the save/load.
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
from pathlib import Path
from typing import Any

from flograph.core.graph import Graph

from .cache import OutputCache

CACHE_SCHEMA = 1


def _cache_dir_for(project_path: str | Path) -> Path:
    return Path(str(project_path) + ".cache")


def node_fingerprint(graph: Graph, node_id: str, memo: dict[str, str]) -> str:
    """Recursive hash over a node's type/source/params and every upstream
    node's fingerprint. Identical fingerprint across a save/load round trip
    means "safe to reuse this node's cached output"."""
    if node_id in memo:
        return memo[node_id]
    node = graph.node(node_id)
    upstream_fps = []
    for port in node.spec.inputs:
        conn = graph.input_connection(node_id, port.name)
        if conn is not None:
            upstream_fps.append(node_fingerprint(graph, conn.src_node, memo))
    payload = json.dumps({
        "type_id": node.type_id,
        "source": node.source,
        "params": node.params,
        "upstream": sorted(upstream_fps),
    }, sort_keys=True, default=str)
    fp = hashlib.sha256(payload.encode()).hexdigest()
    memo[node_id] = fp
    return fp


def save_cache(graph: Graph, cache: OutputCache, project_path: str | Path) -> None:
    cache_dir = _cache_dir_for(project_path)
    memo: dict[str, str] = {}
    manifest: dict[str, Any] = {}
    keep_files = set()
    for node_id in graph.topo_order():
        entry = cache.get(node_id)
        if entry is None:
            continue
        try:
            blob = pickle.dumps(entry.outputs, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception:
            continue  # unpicklable output — skip; that node loads dirty next time
        cache_dir.mkdir(parents=True, exist_ok=True)
        blob_name = f"{node_id}.pkl"
        blob_path = cache_dir / blob_name
        tmp_path = cache_dir / f"{blob_name}.tmp"
        tmp_path.write_bytes(blob)
        os.replace(tmp_path, blob_path)
        keep_files.add(blob_name)
        manifest[node_id] = {
            "fingerprint": node_fingerprint(graph, node_id, memo),
            "wall_time": entry.wall_time,
            "timestamp": entry.timestamp,
        }

    if not manifest:
        # nothing cached (e.g. caches were reset) — drop any stale side-car
        if cache_dir.exists():
            for stale in cache_dir.glob("*.pkl"):
                stale.unlink(missing_ok=True)
            (cache_dir / "manifest.json").unlink(missing_ok=True)
            try:
                cache_dir.rmdir()
            except OSError:
                pass  # not empty (unexpected extra files) — leave it alone
        return

    manifest_path = cache_dir / "manifest.json"
    tmp_manifest = cache_dir / "manifest.json.tmp"
    tmp_manifest.write_text(
        json.dumps({"cache_schema": CACHE_SCHEMA, "nodes": manifest}, indent=2))
    os.replace(tmp_manifest, manifest_path)
    for stale in cache_dir.glob("*.pkl"):
        if stale.name not in keep_files:
            stale.unlink(missing_ok=True)


def resolve_entries(
    graph: Graph, project_path: str | Path,
) -> list[tuple[str, dict[str, Any]]]:
    """Cheap half of restoring a cache: read the manifest and keep only the
    entries whose fingerprint still matches the *current* graph — no blobs
    are touched. Returns `[(node_id, meta), ...]` in manifest order; each
    still needs `load_blob` to actually fetch its output. Never raises."""
    cache_dir = _cache_dir_for(project_path)
    manifest_path = cache_dir / "manifest.json"
    if not manifest_path.exists():
        return []
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if manifest.get("cache_schema") != CACHE_SCHEMA:
        return []

    memo: dict[str, str] = {}
    entries = []
    for node_id, meta in manifest.get("nodes", {}).items():
        if node_id not in graph.nodes:
            continue
        try:
            fp = node_fingerprint(graph, node_id, memo)
        except Exception:
            continue
        if fp != meta.get("fingerprint"):
            continue
        entries.append((node_id, meta))
    return entries


def load_blob(project_path: str | Path, node_id: str) -> Any:
    """Expensive half: unpickle one node's cached output. This is the part
    that can take a long time for large DataFrames/figures — callers that
    care about UI responsiveness (see flograph.engine.cache_worker) run this
    off the GUI thread, one node at a time. Raises on any failure; the
    caller decides whether to skip or surface it."""
    cache_dir = _cache_dir_for(project_path)
    return pickle.loads((cache_dir / f"{node_id}.pkl").read_bytes())


def load_cache(graph: Graph, cache: OutputCache, project_path: str | Path) -> list[str]:
    """Restore whatever cache entries are still valid for the *current*
    graph. Returns the ids of nodes that were restored — the caller is
    responsible for marking them clean/DONE and notifying the UI. Never
    raises: any problem just means fewer (or zero) nodes get restored.

    Synchronous end-to-end (resolve + unpickle) — fine for small caches and
    for tests/headless use. The GUI opens a project through
    flograph.engine.cache_worker instead, so unpickling large blobs doesn't
    block the event loop."""
    restored = []
    for node_id, meta in resolve_entries(graph, project_path):
        try:
            outputs = load_blob(project_path, node_id)
        except Exception:
            continue
        cache.set(node_id, outputs, meta.get("wall_time", 0.0))
        restored.append(node_id)
    return restored
