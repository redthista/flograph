"""Persist node output caches alongside a .flograph project file.

A side-car directory named "<project>.flograph.cache/" holds one pickle blob
per cached node — bar the pass-through nodes, which get a manifest entry
pointing at whoever owns the value instead of a blob of their own — plus a
manifest keyed by a fingerprint of that node's type, source, and params,
folded recursively with every upstream node's fingerprint — so any change to a node or anything upstream of it invalidates
its entry. This deliberately does not touch the project file's own
SCHEMA_VERSION: the .flograph JSON itself is untouched, only a sibling
directory is added.

Blobs written since CACHE_SCHEMA 3 are zlib-compressed (level 1, from
measurement — see ideas_archived.md #16), and say so in a per-entry
"codec" field. Reading never trusts the manifest on this point: the first
byte of a pickle at protocol 2+ is always 0x80 and a zlib stream's never
is, so `load_blob` sniffs and decompresses only when it must. That is what
keeps every era of side-car readable forever — raw pickles from before
compression existed, compressed blobs from after, and the mixed directory
a project gets when the setting was off for a while and is on again.

Loading is never fatal: a missing manifest, a schema mismatch, a stale
fingerprint, or a corrupt/unpicklable blob just means that node is left
dirty, exactly as if there were no side-car cache at all. Pickling arbitrary
node outputs (DataFrames, matplotlib Figures, ...) is not guaranteed stable
across library/Python versions — every read and write of a blob is wrapped
so one bad node can never block the rest of the save/load. An *OSError*
from the write path (the disk filled up) is deliberately not swallowed:
that failure is the user's to fix, and silent is the worst way to lose
their work — see save_cache/write_cache_plan and K2.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import pickle
import shutil
import zlib
from pathlib import Path
from typing import Any, Optional

from flograph.core.graph import Graph
from flograph.core.varlinks import uses_env

from .cache import CacheEntry, OutputCache
from .frames import normalize_strings

CACHE_SCHEMA = 3
# Schema 2 adds "bytes" and "ports" per node, which is what lets a project
# open without unpickling anything. Schema 1 side-cars are still read: they
# simply do not know how big an entry is until it is loaded, and discarding
# somebody's cached work over a missing size would be a poor trade.
# Schema 3 adds "codec" per entry and starts writing compressed blobs; the
# reader sniffs rather than trusting it (see the module docstring), so even
# so the field earns its place by making a side-car self-describing.
SUPPORTED_SCHEMAS = (1, 2, 3)

# zlib level 1, chosen by measurement over levels 6/9 and lzma: string-heavy
# frames — most of what caches hold — drop to ~40% of raw for a few percent
# of the pickle time, float blocks barely shrink for any codec but cost
# level 9 occasional seconds for nothing, and lzma's ratio edge is paid for
# with a 4x slower read on every project open. See ideas_archived.md #16.
CACHE_COMPRESS_LEVEL = 1


class _ZlibSink:
    """A file-object stand-in that pickle.dump can stream compressed into.

    Streaming, not pickle.dumps()-then-compress(): building the whole blob
    in memory first doubles the cost of the largest thing in the project at
    the moment it is least affordable — the same reason the raw write was
    streamed before compression arrived. pickle needs only `.write()` (and
    calls `.flush()`, which mid-stream has nothing to do); `finish()` emits
    the compressor's tail once the pickler is done.

    While it goes it tallies what passed through on both sides — `raw_bytes`
    in, `out_bytes` out — which is how a manifest entry comes to know both
    its uncompressed and its stored size without anyone ever holding the
    uncompressed form in memory for the sake of a number.
    """

    __slots__ = ("_fh", "_compressor", "raw_bytes", "out_bytes")

    def __init__(self, fh: Any) -> None:
        self._fh = fh
        self._compressor = zlib.compressobj(CACHE_COMPRESS_LEVEL)
        self.raw_bytes = 0
        self.out_bytes = 0

    def write(self, data: Any) -> None:
        # Protocol-5 pickling hands its out-of-band buffers to write() as
        # pickle.PickleBuffer — not bytes — and pandas' Arrow-backed string
        # columns go exactly that way, so every frame with text in it lands
        # here. A PickleBuffer speaks the buffer protocol but has no len(),
        # so measure through a memoryview and feed the compressor the same;
        # anything that cannot even be viewed is a genuine failure and
        # raises, which the caller treats as one uncacheable node.
        view = memoryview(data)
        self.raw_bytes += view.nbytes
        chunk = self._compressor.compress(view)
        if chunk:
            self._fh.write(chunk)
            self.out_bytes += len(chunk)

    def flush(self) -> None:
        pass

    def finish(self) -> bytes:
        tail = self._compressor.flush()
        if tail:
            self.out_bytes += len(tail)
        return tail


def save_failure_text(what: str, exc: BaseException) -> str:
    """One line for a dialog when writing to disk failed.

    A disk-full save is its own sentence: "OSError: [Errno 28] No space
    left on device" is accurate and still leaves somebody googling whether
    their flow is broken. Shared by both writers that can fail this way —
    the project JSON on the GUI thread and the cache blobs on the pool
    thread — so the wording cannot drift between them.
    """
    if isinstance(exc, OSError) and exc.errno in (errno.ENOSPC, errno.EDQUOT):
        return (f"The disk holding {what} is full. Free some space "
                f"(Reset Caches releases this project's cached results) "
                f"and try again.")
    detail = (exc.strerror if isinstance(exc, OSError) and exc.strerror
              else str(exc))
    return f"{what.capitalize()} could not be written: {detail}"


def _cache_dir_for(project_path: str | Path) -> Path:
    return Path(str(project_path) + ".cache")


def node_fingerprint(graph: Graph, node_id: str, memo: dict[str, str]) -> str:
    """Hash over a node's type/source/params and every upstream node's
    fingerprint. Identical fingerprint across a save/load round trip means
    "safe to reuse this node's cached output".

    Iterative, with an explicit stack, rather than the obvious recursion:
    the walk is as deep as the graph is long, so a chain of more than about
    a thousand nodes hit Python's recursion limit and raised — and since
    this runs inside both `save_cache` and `resolve_entries`, that meant a
    deep enough project could not be saved or reopened at all.
    """
    if node_id in memo:
        return memo[node_id]
    # (node, its parents already fingerprinted?) — a node is pushed twice:
    # once to discover its parents, once to be hashed after they are done.
    stack: list[tuple[str, bool]] = [(node_id, False)]
    while stack:
        current, resolved = stack.pop()
        if current in memo:
            continue
        _fingerprint_one(graph, current, resolved, memo, stack)
    return memo[node_id]


def _fingerprint_one(graph: Graph, node_id: str, resolved: bool,
                     memo: dict[str, str],
                     stack: list[tuple[str, bool]]) -> None:
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
        memo[node_id] = hashlib.sha256(f"frozen:{node_id}".encode()).hexdigest()
        return
    # Port order, and one entry per *connected* port, so two ports fed by the
    # same node still contribute twice — as the recursive version did.
    parents = []
    for port in node.spec.inputs:
        conn = graph.input_connection(node_id, port.name)
        if conn is not None:
            parents.append(conn.src_node)
    # A `${name}` reference is a real dependency with no port to hang off, so
    # the by-port walk above cannot see it. Without this, a node whose param
    # reads "${region}" hashes identically whichever region is selected — and
    # the engine would serve the cached frame for the wrong one. The values
    # themselves are not hashed: the Variables node's own fingerprint covers
    # them, and folding it in here is what makes the dependency transitive.
    parents.extend(graph.var_sources(node_id))
    # An order edge is a dependency too, and portless in the same way. A node
    # told to run after a step that writes a file is stale the moment that
    # step changes, even though nothing was handed to it directly — that is
    # the reason to have drawn the edge at all.
    parents.extend(graph.order_sources(node_id))
    if not resolved:
        pending = [p for p in parents if p not in memo]
        if pending:
            stack.append((node_id, True))
            stack.extend((p, False) for p in pending)
            return
    payload = json.dumps({
        "type_id": node.type_id,
        "source": node.source,
        "params": node.params,
        "upstream": sorted(memo[p] for p in parents),
    }, sort_keys=True, default=str)
    memo[node_id] = hashlib.sha256(payload.encode()).hexdigest()


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
    for src in (*graph.var_sources(node_id),   # portless — see _fingerprint_one
                *graph.order_sources(node_id)):
        upstream_fps.append(node_fingerprint(graph, src, memo))
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


def _alias_meta(entry: CacheEntry, manifest: dict, frozen: bool) -> Optional[dict]:
    """How to rebuild `entry` from another node's blob, or None if it has to
    be written out itself.

    The source must already be in the manifest. write_cache_plan walks in
    topological order, so a link's source has been dealt with by the time
    the link is reached, and a source that was *skipped* — unpicklable, or
    evicted while a frozen link kept its value alive — correctly falls
    through to the link writing its own blob. A frozen node never aliases
    either: its fingerprint is a constant, so it can come back from cache
    when its source cannot, and it must not depend on a blob that will not
    be there.

    Takes the node's `frozen` flag rather than the graph: by the time this
    runs the plan has already been snapshotted away from it (see
    plan_cache_save), and one boolean is all it needed.
    """
    if entry.alias_of is None or entry.alias_port is None:
        return None
    # `ports()`, not `entry.outputs`: a spilled entry has no outputs in hand
    # and reading them would mean loading the very blob this save is trying
    # to avoid touching.
    ports = entry.ports()
    if entry.alias_of not in manifest or len(ports) != 1:
        return None
    if frozen:
        return None
    return {"node": entry.alias_of, "port": entry.alias_port, "as": ports[0]}


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


def _carry_blob_over(source_project: str | None, cache_dir: Path,
                     blob_name: str) -> bool:
    """Make sure a spilled entry's blob exists in `cache_dir`. True on success.

    Usually a no-op, because the entry was spilled from this same project. On
    Save As it is a file copy — which is what keeps "save the project
    somewhere else" from quietly discarding every cached result that had not
    been loaded, at a cost that is disk-to-disk rather than through memory.
    """
    if source_project is None:
        return False
    source = _cache_dir_for(source_project) / blob_name
    target = cache_dir / blob_name
    try:
        if target.exists() and source.exists() and source.samefile(target):
            return True
        if not source.exists():
            return False
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = cache_dir / f"{blob_name}.tmp"
        shutil.copyfile(source, tmp)
        os.replace(tmp, target)
        return True
    except OSError:
        return False


def plan_cache_save(
    graph: Graph, cache: OutputCache,
) -> list[tuple[str, CacheEntry, str, bool]]:
    """The cheap half of saving a cache: walk the graph once on the calling
    thread and snapshot what each cached entry needs written — its id, its
    entry object, its fingerprint, and whether its node is frozen.

    Splitting this from write_cache_plan is what lets a long save run off
    the GUI thread (ui.cache_worker's CacheSaveRunnable hands it a plan):
    from here on the worker touches only the snapshot and the filesystem,
    never the graph or the cache, so editing and running continue while the
    blobs pickle themselves out. Entries are held by reference; their
    outputs are read-only by contract — the same guarantee serving them to
    downstream nodes relies on.

    A `${env}` node is left out entirely, for the same reason it always was:
    see the comment in the loop.
    """
    plan: list[tuple[str, CacheEntry, str, bool]] = []
    memo: dict[str, str] = {}
    for node_id in graph.topo_order():
        node = graph.nodes[node_id]
        entry = cache.get(node_id)
        if entry is None:
            continue
        if uses_env(node):
            # A node reading `${env:...}` is never persisted. Its fingerprint
            # cannot include the secret without putting a hash of it in a
            # file beside the project, and leaving the secret out would let a
            # value computed from the old one come back after the .env
            # changed. Recomputing it on reopen costs one run and is right
            # both ways.
            continue
        plan.append((node_id, entry,
                     node_fingerprint(graph, node_id, memo), node.frozen))
    return plan


def write_cache_plan(project_path: str | Path,
                     plan: list[tuple[str, CacheEntry, str, bool]],
                     progress: Any = None,
                     compress: bool = True) -> int:
    """The expensive half: pickle every planned blob out and write the
    manifest. Returns how many entries were recorded.

    Runs wherever the caller put it — the GUI thread through save_cache, or
    a pool thread through CacheSaveRunnable. Touches nothing but `plan` and
    the filesystem. `progress(done, total)` fires once per planned entry,
    whatever became of it — written, carried over, aliased, skipped — so a
    bar that reaches its end means "looked at everything", not "wrote
    everything".

    An OSError from the writes propagates: a disk filling up is the user's
    to fix, and losing their work silently is the worst outcome (see the
    module docstring). Any other exception while pickling one entry skips
    just that entry — unpicklable output loads dirty next time, as ever.
    """
    total = len(plan)
    done = 0

    def tick() -> None:
        nonlocal done
        done += 1
        if progress is not None:
            progress(done, total)

    cache_dir = _cache_dir_for(project_path)
    manifest: dict[str, Any] = {}
    keep_files = set()
    codec = "zlib" if compress else "raw"
    for node_id, entry, fingerprint, frozen in plan:
        alias = _alias_meta(entry, manifest, frozen)
        if alias is not None:
            manifest[node_id] = {
                "fingerprint": fingerprint,
                "wall_time": entry.wall_time,
                "timestamp": entry.timestamp,
                "bytes": entry.memory_bytes,
                "ports": list(entry.ports()),
                "alias": alias,
            }
            tick()
            continue

        blob_name = f"{node_id}.pkl"
        if not entry.resident:
            # The value is on disk and has not been loaded. Move the *file*,
            # never the value: reading a blob back only to write out what we
            # just read would undo the whole point of not loading it. The
            # entry must still join keep_files, or the sweep at the end of
            # this function deletes the blob a live entry depends on. Its
            # bytes are whatever era wrote it — no "codec" here; the reader
            # sniffs rather than trusting the manifest anyway.
            if not _carry_blob_over(entry.blob, cache_dir, blob_name):
                tick()
                continue    # source blob gone — that node loads dirty next time
            keep_files.add(blob_name)
            # The blob's stored size is one stat away and worth recording —
            # it feeds the on-disk total in the resource monitor's hover.
            # Its raw size stays unknown without unpickling, which is the
            # one thing this save exists to avoid; the entry simply has no
            # raw_bytes, and totals built from the manifest skip it.
            try:
                carried_bytes = (cache_dir / blob_name).stat().st_size
            except OSError:
                carried_bytes = 0
            manifest[node_id] = {
                "fingerprint": fingerprint,
                "wall_time": entry.wall_time,
                "timestamp": entry.timestamp,
                "bytes": entry.memory_bytes,
                "ports": list(entry.ports()),
                "disk_bytes": carried_bytes,
            }
            tick()
            continue

        cache_dir.mkdir(parents=True, exist_ok=True)
        blob_path = cache_dir / blob_name
        tmp_path = cache_dir / f"{blob_name}.tmp"
        raw_bytes = disk_bytes = 0
        try:
            # Streamed, not pickle.dumps() then write_bytes(): building the
            # whole blob in memory first doubles the cost of the largest
            # thing in the project at the moment it is least affordable.
            # Compressed goes through _ZlibSink so streaming survives —
            # and tallies both sizes as a side effect of going by.
            with open(tmp_path, "wb") as fh:
                if compress:
                    sink = _ZlibSink(fh)
                    try:
                        pickle.dump(entry.outputs, sink,
                                    protocol=pickle.HIGHEST_PROTOCOL)
                    finally:
                        fh.write(sink.finish())
                    raw_bytes, disk_bytes = sink.raw_bytes, sink.out_bytes
                else:
                    pickle.dump(entry.outputs, fh,
                                protocol=pickle.HIGHEST_PROTOCOL)
                    raw_bytes = disk_bytes = fh.tell()
        except OSError:
            tmp_path.unlink(missing_ok=True)
            raise
        except Exception:
            # unpicklable output — skip; that node loads dirty next time
            tmp_path.unlink(missing_ok=True)
            tick()
            continue
        os.replace(tmp_path, blob_path)
        keep_files.add(blob_name)
        manifest[node_id] = {
            "fingerprint": fingerprint,
            "wall_time": entry.wall_time,
            "timestamp": entry.timestamp,
            "bytes": entry.memory_bytes,
            "ports": list(entry.ports()),
            "codec": codec,
            "raw_bytes": raw_bytes,
            "disk_bytes": disk_bytes,
        }
        tick()

    if not manifest:
        # nothing cached (e.g. caches were reset) — drop any stale side-car
        if cache_dir.exists():
            for stale in cache_dir.glob("*.pkl"):
                stale.unlink(missing_ok=True)
            for stale in cache_dir.glob("*.pkl.tmp"):
                stale.unlink(missing_ok=True)
            (cache_dir / "manifest.json").unlink(missing_ok=True)
            try:
                cache_dir.rmdir()
            except OSError:
                pass  # not empty (unexpected extra files) — leave it alone
        return 0

    manifest_path = cache_dir / "manifest.json"
    tmp_manifest = cache_dir / "manifest.json.tmp"
    tmp_manifest.write_text(
        json.dumps({"cache_schema": CACHE_SCHEMA, "nodes": manifest}, indent=2))
    os.replace(tmp_manifest, manifest_path)
    for stale in cache_dir.glob("*.pkl"):
        if stale.name not in keep_files:
            stale.unlink(missing_ok=True)
    # A crash mid-write leaves the .tmp behind — the *.pkl sweep above can
    # never match it, and without this it sits there forever.
    for stale in cache_dir.glob("*.pkl.tmp"):
        stale.unlink(missing_ok=True)
    return len(manifest)


def save_cache(graph: Graph, cache: OutputCache, project_path: str | Path,
               progress: Any = None, compress: bool = True) -> int:
    """Plan and write in one call, on the calling thread.

    The form tests and headless tools use; the GUI splits the two halves so
    the expensive one runs off the UI thread with progress to show for it.
    Returns the number of entries recorded."""
    return write_cache_plan(project_path, plan_cache_save(graph, cache),
                            progress=progress, compress=compress)


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
    if manifest.get("cache_schema") not in SUPPORTED_SCHEMAS:
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


def sidecar_stats(project_path: str | Path) -> tuple[int, int]:
    """How much room the side-car takes and what it held uncompressed.

    Returns `(bytes on disk, raw bytes recorded)`. The disk figure is the
    size of every blob file — true whatever wrote them; the raw figure sums
    the manifest's per-entry `raw_bytes`, which only entries this app wrote
    since compression know, so a carried-over blob counts toward the first
    number and not the second. The pair is for one line in the resource
    monitor's hover: what the cache costs on the drive, against what the
    same values would have cost raw. Anything unreadable reads as zero —
    a hover line never earns an exception.
    """
    cache_dir = _cache_dir_for(project_path)
    disk = 0
    for blob in cache_dir.glob("*.pkl"):
        try:
            disk += blob.stat().st_size
        except OSError:
            continue
    try:
        manifest = json.loads((cache_dir / "manifest.json").read_text())
    except (OSError, ValueError):
        return disk, 0
    raw = 0
    for meta in (manifest.get("nodes") or {}).values():
        if isinstance(meta, dict):
            value = meta.get("raw_bytes")
            if isinstance(value, int) and value > 0:
                raw += value
    return disk, raw


def load_blob(project_path: str | Path, node_id: str) -> Any:
    """Expensive half: unpickle one node's cached output. This is the part
    that can take a long time for large DataFrames/figures — callers that
    care about UI responsiveness (see flograph.engine.cache_worker) run this
    off the GUI thread, one node at a time. Raises on any failure; the
    caller decides whether to skip or surface it.

    The first byte says how the blob is stored, so every era reads forever:
    a pickle at protocol 2+ always starts with 0x80 and a zlib stream never
    does. Old side-cars written raw before compression existed, compressed
    blobs since schema 3, and the mixed directory a project accumulates when
    the setting was toggled — all one code path, and no trust placed in a
    manifest that may be older or newer than its blobs."""
    cache_dir = _cache_dir_for(project_path)
    data = (cache_dir / f"{node_id}.pkl").read_bytes()
    if data[:1] != b"\x80":
        data = zlib.decompress(data)
    return pickle.loads(data)


def load_outputs(project_path: str | Path, node_id: str) -> Any:
    """`load_blob` plus storage normalisation — the function to hand to
    OutputCache.set_loader.

    Normalising here rather than in the cache keeps engine.cache free of both
    I/O and pandas, and puts the conversion exactly where old blobs come back:
    a value written months ago carries whatever layout pandas used then, and
    on real project caches the Python-string layout costs two-thirds more
    memory than the Arrow one for identical data.
    """
    return normalize_strings(load_blob(project_path, node_id))


def register_cache(graph: Graph, cache: OutputCache,
                   project_path: str | Path) -> list[str]:
    """Register every still-valid cache entry *without loading anything*.

    The counterpart to load_cache, and what opening a project should do. It
    reads one JSON file and allocates nothing: each node is recorded as
    cached-but-spilled, which is enough for it to count as clean, and its
    value is fetched only when something actually asks for it.

    The difference is not marginal. On a 14-node project whose side-car holds
    2M-row frames, load_cache costs about 4 GB of resident memory before the
    user has pressed anything; this costs a directory read.
    """
    cache.set_loader(load_outputs)
    project = str(project_path)
    registered = []
    for node_id, meta in resolve_entries(graph, project_path):
        alias = meta.get("alias") if is_alias(meta) else None
        if alias is not None:
            # No blob of its own; it resolves through its source, which is
            # registered too and may itself still be spilled.
            if alias.get("node") is None or alias.get("as") is None:
                continue
            cache.register_spilled(
                node_id, None, meta.get("wall_time", 0.0),
                memory_bytes=meta.get("bytes", 0) or 0,
                port_names=tuple(meta.get("ports") or (alias["as"],)),
                alias_of=alias["node"], alias_port=alias.get("port"),
            )
        else:
            cache.register_spilled(
                node_id, project, meta.get("wall_time", 0.0),
                memory_bytes=_known_size(meta, project_path, node_id),
                port_names=tuple(meta.get("ports") or ()),
            )
        registered.append(node_id)
    return registered


def _known_size(meta: dict, project_path: str | Path, node_id: str) -> int:
    """How big a spilled entry is, without reading it.

    Schema 2 records the measured size. Schema 1 does not, so fall back to the
    blob's size on disk — a stat, and a serviceable lower bound: the readouts
    would otherwise report a reopened project as holding nothing at all.
    """
    recorded = meta.get("bytes")
    if isinstance(recorded, int) and recorded > 0:
        return recorded
    try:
        return (_cache_dir_for(project_path) / f"{node_id}.pkl").stat().st_size
    except OSError:
        return 0


def load_cache(graph: Graph, cache: OutputCache, project_path: str | Path) -> list[str]:
    """Restore whatever cache entries are still valid for the *current*
    graph. Returns the ids of nodes that were restored — the caller is
    responsible for marking them clean/DONE and notifying the UI. Never
    raises: any problem just means fewer (or zero) nodes get restored.

    Synchronous end-to-end (resolve + unpickle) — fine for small caches and
    for tests/headless use. The GUI opens a project through `register_cache`
    instead, which loads nothing up front."""
    cache.set_loader(load_outputs)
    restored = []
    entries = resolve_entries(graph, project_path)
    for node_id, meta in entries:
        if is_alias(meta):
            continue        # no blob of its own; rebuilt below from its source
        try:
            outputs = load_outputs(project_path, node_id)
        except Exception:
            continue
        cache.set(node_id, outputs, meta.get("wall_time", 0.0))
        restored.append(node_id)
    restored.extend(restore_aliases(graph, cache, entries))
    return restored
