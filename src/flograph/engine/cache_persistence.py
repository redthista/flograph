"""Persist node output caches alongside a .flograph project file.

A side-car directory named "<project>.flograph.cache/" holds one pickle blob
per cached node — bar the pass-through nodes, which get a manifest entry
pointing at whoever owns the value instead of a blob of their own — plus a
manifest keyed by a fingerprint of that node's type, source, and params,
folded recursively with every upstream node's fingerprint — so any change to a node or anything upstream of it invalidates
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
    if node.frozen:
        # A frozen node's output is pinned, so it no longer follows from its
        # params or its inputs — it follows from the freeze. Hashing a
        # constant is what lets the pin survive a reopen at all, and it also
        # stops an edit *upstream* of a pin from invalidating the caches
        # below it: those were computed from a value that has not moved, so
        # recomputing them would be work for nothing. Unfreezing restores
        # the real hash, which no longer matches, so the node loads dirty
        # and runs again — exactly what unfreezing is for.
        fp = hashlib.sha256(f"frozen:{node_id}".encode()).hexdigest()
        memo[node_id] = fp
        return fp
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


def freeze_fingerprint(graph: Graph, node_id: str) -> str:
    """What a node's params and inputs hash to *right now*.

    Recorded when a node is frozen and compared afterwards: if it has moved,
    the pinned value no longer reflects what the node would produce, and the
    pin is worth flagging. Deliberately not what node_fingerprint returns for
    a frozen node — that one is a constant, which is the whole point of it.
    """
    memo: dict[str, str] = {}
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
    return hashlib.sha256(payload.encode()).hexdigest()


def stale_frozen(graph: Graph) -> list[str]:
    """Frozen nodes whose params or inputs have changed since they were
    frozen — the pins that are now telling the graph something untrue.

    A pinned source node, which is what freezing is mostly for, can never
    appear here: it has no inputs, so nothing moves under it unless its own
    params are edited. That is deliberate. A warning that fires on every
    frozen node is one nobody reads.
    """
    stale = []
    for node_id, node in graph.nodes.items():
        if not node.frozen or node.frozen_fingerprint is None:
            continue
        try:
            if freeze_fingerprint(graph, node_id) != node.frozen_fingerprint:
                stale.append(node_id)
        except Exception:
            continue      # a broken node is somebody else's error to report
    return stale


def is_alias(meta: dict) -> bool:
    """Does this manifest entry share another node's blob rather than own one?"""
    return isinstance(meta.get("alias"), dict)


def _alias_meta(graph: Graph, node_id: str, entry, manifest: dict):
    """How to rebuild `entry` from another node's blob, or None if it has to
    be written out itself.

    The source must already be in the manifest. save_cache walks in
    topological order, so a link's source has been dealt with by the time the
    link is reached, and a source that was *skipped* — unpicklable, or
    evicted while a frozen link kept its value alive — correctly falls
    through to the link writing its own blob. A frozen node never aliases
    either: its fingerprint is a constant, so it can come back from cache
    when its source cannot, and it must not depend on a blob that will not
    be there.
    """
    if entry.alias_of is None or entry.alias_port is None:
        return None
    if entry.alias_of not in manifest or len(entry.outputs) != 1:
        return None
    if graph.nodes[node_id].frozen:
        return None
    return {"node": entry.alias_of, "port": entry.alias_port,
            "as": next(iter(entry.outputs))}


def restore_aliases(graph: Graph, cache: OutputCache,
                    entries: list[tuple[str, dict[str, Any]]]) -> list[str]:
    """Rebuild the entries that share another node's value, once the blobs
    they point at are in the cache. Returns the ids actually restored.

    Kept separate from the blob loading because that half runs on a pool
    thread and this half must not: it reads the cache the GUI thread owns.
    The entry list is in the order save_cache wrote it, which is topological,
    so a chain (goto -> from -> from) resolves front to back in one pass. An
    alias whose source did not come back is skipped and its node loads dirty,
    exactly as it would have with no side-car cache at all.
    """
    restored = []
    for node_id, meta in entries:
        alias = meta.get("alias")
        if not isinstance(alias, dict) or node_id not in graph.nodes:
            continue
        port, out_port = alias.get("port"), alias.get("as")
        outputs = cache.outputs_for(alias.get("node"))
        # `in`, not `.get() is not None`: None is a value a node may cache
        if out_port is None or port not in outputs:
            continue
        cache.set(node_id, {out_port: outputs[port]},
                  meta.get("wall_time", 0.0),
                  alias_of=alias["node"], alias_port=port)
        restored.append(node_id)
    return restored


def save_cache(graph: Graph, cache: OutputCache, project_path: str | Path) -> None:
    cache_dir = _cache_dir_for(project_path)
    memo: dict[str, str] = {}
    manifest: dict[str, Any] = {}
    keep_files = set()
    for node_id in graph.topo_order():
        entry = cache.get(node_id)
        if entry is None:
            continue
        alias = _alias_meta(graph, node_id, entry, manifest)
        if alias is not None:
            manifest[node_id] = {
                "fingerprint": node_fingerprint(graph, node_id, memo),
                "wall_time": entry.wall_time,
                "timestamp": entry.timestamp,
                "alias": alias,
            }
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
    entries = resolve_entries(graph, project_path)
    for node_id, meta in entries:
        if is_alias(meta):
            continue        # no blob of its own; rebuilt below from its source
        try:
            outputs = load_blob(project_path, node_id)
        except Exception:
            continue
        cache.set(node_id, outputs, meta.get("wall_time", 0.0))
        restored.append(node_id)
    restored.extend(restore_aliases(graph, cache, entries))
    return restored
