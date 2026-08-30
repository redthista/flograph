"""Persist node output caches as part of a .flograph project file.

By default the project is a **zip bundle** (see `core.container`): the
graph in ``project.json``, and beside it a ``cache/`` tree holding one
pickle blob per cached node — bar the pass-through nodes, which get a
manifest entry pointing at whoever owns the value instead of a blob of
their own — plus ``cache/manifest.json`` keyed by a fingerprint of that
node's type, source, and params, folded recursively with every upstream
node's fingerprint — so any change to a node or anything upstream of it
invalidates its entry. The cache half has its own CACHE_SCHEMA,
independent of the project JSON's SCHEMA_VERSION.

The graph-only ``.flowf`` export (File ▸ Export Workflow) is a plain
``serialization.save`` and never comes through here — it carries no cache
by definition. A project saved by an older flograph keeps a legacy
**side-car directory** ``<project>.flograph.cache/`` with the same manifest
+ blob layout; every reader here takes either shape transparently through
`open_cache_source`, and the first bundled save folds an old side-car in
and removes it.

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
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Optional

from flograph.core import container
from flograph.core.graph import Graph
from flograph.core.serialization import graph_to_dict
from flograph.core.varlinks import uses_env

from .cache import CacheEntry, OutputCache
from .frames import normalize_strings
from .runstats import RunHistory, RunRecord

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


class _CountingSink:
    """`_ZlibSink` without the compressor — for the raw (compress-off) write
    into a bundle member. A zip write stream has no `tell()`, and pickle
    protocol 5 hands out `PickleBuffer`s with no `len()`, so the byte count
    a manifest entry needs is tallied here through a memoryview exactly as
    the compressed path does it.
    """

    __slots__ = ("_fh", "raw_bytes")

    def __init__(self, fh: Any) -> None:
        self._fh = fh
        self.raw_bytes = 0

    def write(self, data: Any) -> None:
        view = memoryview(data)
        self.raw_bytes += view.nbytes
        self._fh.write(view)

    def flush(self) -> None:
        pass


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


def has_sidecar(project_path: str | Path) -> bool:
    """True if a legacy ``<project>.flograph.cache/`` folder sits beside the
    project — what a bundled save is about to fold in and remove."""
    return _cache_dir_for(project_path).is_dir()


def discard_sidecar(project_path: str | Path) -> bool:
    """Remove a legacy side-car folder — its contents live in the bundle
    now, or the user asked for no cache at all. Best effort: a folder we
    cannot delete is cosmetic clutter, not a failed save. True if a folder
    was there to remove."""
    folder = _cache_dir_for(project_path)
    if not folder.is_dir():
        return False
    try:
        shutil.rmtree(folder)
    except OSError:
        return False
    return True


class _DirSource:
    """Cache members read from a legacy side-car folder. Member names are
    relative to the cache root — ``"manifest.json"``, ``"<node>.pkl"`` — so
    the bundle and folder sources are called the same way."""

    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir

    def read_text(self, member: str) -> "str | None":
        try:
            return (self._dir / member).read_text()
        except OSError:
            return None

    def blob_open(self, node_id: str) -> IO[bytes]:
        return open(self._dir / f"{node_id}.pkl", "rb")  # caller catches OSError

    def blob_bytes(self, node_id: str) -> bytes:
        return (self._dir / f"{node_id}.pkl").read_bytes()  # caller catches

    def blob_exists(self, node_id: str) -> bool:
        return (self._dir / f"{node_id}.pkl").exists()

    def blob_disk_size(self, node_id: str) -> int:
        try:
            return (self._dir / f"{node_id}.pkl").stat().st_size
        except OSError:
            return 0

    def total_blob_bytes(self) -> int:
        total = 0
        for blob in self._dir.glob("*.pkl"):
            try:
                total += blob.stat().st_size
            except OSError:
                continue
        return total

    def close(self) -> None:
        pass


class _BundleSource:
    """Cache members read from the ``cache/`` tree inside a .flograph zip
    bundle, without inflating anything but the member asked for."""

    def __init__(self, project_path: str | Path) -> None:
        self._reader = container.BundleReader(project_path)

    def read_text(self, member: str) -> "str | None":
        return self._reader.read_text(f"{container.CACHE_PREFIX}{member}")

    def blob_open(self, node_id: str) -> IO[bytes]:
        member = container.blob_member(node_id)
        if not self._reader.has(member):
            raise FileNotFoundError(member)
        return self._reader.open(member)

    def blob_bytes(self, node_id: str) -> bytes:
        data = self._reader.read_bytes(container.blob_member(node_id))
        if data is None:
            raise FileNotFoundError(node_id)
        return data

    def blob_exists(self, node_id: str) -> bool:
        return self._reader.has(container.blob_member(node_id))

    def blob_disk_size(self, node_id: str) -> int:
        return self._reader.stored_size(container.blob_member(node_id))

    def total_blob_bytes(self) -> int:
        return sum(self._reader.stored_size(m)
                   for m in self._reader.blob_members())

    def close(self) -> None:
        self._reader.close()


def open_cache_source(project_path: str | Path) -> "Any":
    """Read access to a project's cached results, whichever way they are
    stored: the ``cache/`` tree of a zip bundle, or a legacy side-car
    folder. A bundle that will not open (truncated, not really a zip) falls
    back to the folder, exactly as a missing side-car degrades to nothing.
    Always returns something with a ``close()`` — use it and close it."""
    if container.is_bundle(project_path):
        try:
            return _BundleSource(project_path)
        except (OSError, zipfile.BadZipFile):
            pass
    return _DirSource(_cache_dir_for(project_path))


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
    source = open_cache_source(project_path)
    try:
        text = source.read_text("manifest.json")
    finally:
        source.close()
    if text is None:
        return []
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError:
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
    """How much room the cached results take and what they held uncompressed.

    Returns `(bytes on disk, raw bytes recorded)`. The disk figure is the
    stored size of every blob — the ``.pkl`` files of a side-car folder, or
    the ``cache/*.pkl`` members of a bundle — true whatever wrote them; the
    raw figure sums the manifest's per-entry `raw_bytes`, which only entries
    this app wrote since compression know, so a carried-over blob counts
    toward the first number and not the second. The pair is for one line in
    the resource monitor's hover: what the cache costs on the drive, against
    what the same values would have cost raw. Anything unreadable reads as
    zero — a hover line never earns an exception.
    """
    source = open_cache_source(project_path)
    try:
        disk = source.total_blob_bytes()
        text = source.read_text("manifest.json")
    finally:
        source.close()
    try:
        manifest = json.loads(text) if text is not None else {}
    except ValueError:
        return disk, 0
    raw = 0
    for meta in (manifest.get("nodes") or {}).values():
        if isinstance(meta, dict):
            value = meta.get("raw_bytes")
            if isinstance(value, int) and value > 0:
                raw += value
    return disk, raw


RUNS_FILE = "runs.json"


def save_run_history(history: RunHistory, project_path: str | Path) -> None:
    """Write the run records beside the cache, so reopening shows the
    project's previous runs instead of a blank statistics window.

    Lives in the side-car rather than the .flograph file on purpose: it is
    derived data, regenerated by running again, and a run-timing log has no
    business inside a document somebody diffs. Written atomically like the
    manifest; OSError propagates for the caller to weigh (the window's own
    save swallows it — losing a timing log must not fail a completed save).
    """
    cache_dir = _cache_dir_for(project_path)
    payload = {"runs": [record.to_dict() for record in reversed(history.all())]}
    tmp = cache_dir / f"{RUNS_FILE}.tmp"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, cache_dir / RUNS_FILE)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def load_run_history(project_path: str | Path) -> list[RunRecord]:
    """The saved runs, oldest first, or [] when there are none.

    A missing, corrupt, or half-written file is simply "no history" — the
    statistics window degrades to what this session has seen, exactly as it
    always did on a first open. A project saved without its cache carries no
    history at all, by the same reasoning: it is derived data."""
    source = open_cache_source(project_path)
    try:
        text = source.read_text(RUNS_FILE)
    finally:
        source.close()
    if text is None:
        return []
    try:
        payload = json.loads(text)
        records = [RunRecord.from_dict(d)
                   for d in payload.get("runs", [])]
    except (ValueError, TypeError, AttributeError):
        return []
    return [r for r in records if isinstance(r, RunRecord)]


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
    source = open_cache_source(project_path)
    try:
        data = source.blob_bytes(node_id)
    finally:
        source.close()
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
    source = open_cache_source(project_path)
    try:
        for node_id, meta in resolve_entries(graph, project_path):
            alias = meta.get("alias") if is_alias(meta) else None
            if alias is not None:
                # No blob of its own; it resolves through its source, which
                # is registered too and may itself still be spilled.
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
                    memory_bytes=_known_size(meta, source, node_id),
                    port_names=tuple(meta.get("ports") or ()),
                )
            registered.append(node_id)
    finally:
        source.close()
    return registered


def _known_size(meta: dict, source: "Any", node_id: str) -> int:
    """How big a spilled entry is, without reading it.

    Schema 2 records the measured size. Schema 1 does not, so fall back to the
    blob's size on disk — a stat, and a serviceable lower bound: the readouts
    would otherwise report a reopened project as holding nothing at all.
    """
    recorded = meta.get("bytes")
    if isinstance(recorded, int) and recorded > 0:
        return recorded
    return source.blob_disk_size(node_id)


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


# --------------------------------------------------------------------------
# Writing the whole .flograph file
#
# `save_cache` / `write_cache_plan` above still write the legacy side-car
# folder — the headless/test path. The GUI writes a *bundle* through the two
# halves below: `plan_project_save` snapshots the graph, the blob plan and
# the run history on the calling (GUI) thread; `write_project` streams the
# archive out wherever the caller puts it (a pool thread, via
# ui.cache_worker.CacheSaveRunnable). The split is the same one
# plan_cache_save / write_cache_plan make, for the same reason.
# --------------------------------------------------------------------------


@dataclass
class ProjectSavePlan:
    """A save snapshotted away from the live graph and cache.

    `project` is `graph_to_dict` output; `blobs` is a `plan_cache_save`
    plan (empty on a mid-run carry-all save); `runs` is the run-history
    payload. The graph-only export (a `.flowf` file) does not go through
    here — it is a plain `serialization.save`.
    """

    project: dict
    blobs: list[tuple[str, CacheEntry, str, bool]]
    runs: dict
    carry_all: bool = False


def plan_project_save(graph: Graph, cache: OutputCache,
                      history: "RunHistory | None" = None, *,
                      carry_all: bool = False) -> ProjectSavePlan:
    """The cheap, GUI-thread half of a save. Mirrors `plan_cache_save`,
    which it reuses for the blob half.

    `carry_all` (the mid-run save, where the live cache is mid-flight and
    must not be snapshotted) plans no blobs — `write_project` copies every
    one the previous file held instead, re-pickling nothing.
    """
    runs = {"runs": []}
    if history is not None:
        runs = {"runs": [r.to_dict() for r in reversed(history.all())]}
    blobs: list[tuple[str, CacheEntry, str, bool]] = []
    if not carry_all:
        blobs = plan_cache_save(graph, cache)
    return ProjectSavePlan(graph_to_dict(graph), blobs, runs, carry_all)


def write_project(project_path: str | Path, plan: ProjectSavePlan, *,
                  prev_path: "str | Path | None" = None,
                  compress: bool = True, progress: Any = None,
                  carry_all: "bool | None" = None) -> int:
    """Write the whole .flograph bundle, atomically. Returns the number of
    cache entries recorded.

      * `project.json`, then each planned blob streamed out (spilled and
        unchanged ones copied verbatim from `prev_path` — the same path on
        a plain Save, the old path on Save As), then the manifest and run
        history.
      * `carry_all` → every blob is copied from `prev_path` and nothing is
        re-pickled: the mid-run save, matching the old JSON-only mid-run
        behaviour.

    An `OSError` from the writes propagates (a full disk is the user's to
    fix — see the module docstring); anything else while pickling one entry
    skips just that entry, which then loads dirty next open.
    """
    if carry_all is None:
        carry_all = plan.carry_all

    prev = open_cache_source(prev_path) if prev_path is not None else None
    done = 0
    total = _carry_total(prev) if carry_all else len(plan.blobs)

    def tick() -> None:
        nonlocal done
        done += 1
        if progress is not None:
            progress(done, total)

    try:
        with container.BundleWriter(project_path) as writer:
            writer.write_project(plan.project)
            if carry_all:
                manifest = _carry_all_blobs(writer, prev, tick)
            else:
                manifest = _write_planned_blobs(
                    writer, plan.blobs, prev, compress, tick)
            writer.write_manifest(
                {"cache_schema": CACHE_SCHEMA, "nodes": manifest})
            writer.write_runs(plan.runs)
            # Close the previous file *before* BundleWriter.__exit__ does its
            # os.replace: on Windows, replacing a file another handle still
            # has open fails, and `prev` may be reading `project_path`
            # itself on a plain Save.
            if prev is not None:
                prev.close()
                prev = None
            writer.commit()
    finally:
        if prev is not None:
            prev.close()

    discard_sidecar(project_path)
    return len(manifest)


def _carry_total(prev: "Any") -> int:
    """How many manifest entries `prev` holds — the progress total for a
    carry-all save, where nothing is planned up front."""
    if prev is None:
        return 0
    text = prev.read_text("manifest.json")
    if text is None:
        return 0
    try:
        return len(json.loads(text).get("nodes", {}))
    except (ValueError, AttributeError):
        return 0


def _pickle_blob(writer: "container.BundleWriter", node_id: str,
                 outputs: Any, compress: bool) -> tuple[int, int]:
    """Stream one entry's outputs into a bundle member. Returns
    `(raw_bytes, stored_bytes)`. Raises `OSError` on a full disk (the
    caller lets it propagate) and anything else for an unpicklable value
    (the caller skips that entry)."""
    with writer.open_blob(node_id) as dst:
        if compress:
            sink = _ZlibSink(dst)
            try:
                pickle.dump(outputs, sink, protocol=pickle.HIGHEST_PROTOCOL)
            finally:
                dst.write(sink.finish())
            return sink.raw_bytes, sink.out_bytes
        counter = _CountingSink(dst)
        pickle.dump(outputs, counter, protocol=pickle.HIGHEST_PROTOCOL)
        return counter.raw_bytes, counter.raw_bytes


def _copy_spilled(writer: "container.BundleWriter", prev: "Any",
                  node_id: str) -> int:
    """Copy a not-in-memory entry's blob straight into the new bundle,
    never loading it. Returns bytes copied, or -1 if the source blob is
    gone (the node then loads dirty next open). `OSError` from the write
    side — a full disk — propagates."""
    if prev is None:
        return -1
    try:
        src = prev.blob_open(node_id)
    except OSError:
        return -1
    with src:
        return writer.copy_blob(src, node_id)


def _write_planned_blobs(writer: "container.BundleWriter",
                         plan: list[tuple[str, CacheEntry, str, bool]],
                         prev: "Any", compress: bool,
                         tick: "Any") -> dict[str, Any]:
    """The bundle equivalent of write_cache_plan's loop: one manifest entry
    per planned node, its blob either streamed out or (spilled/unchanged)
    copied from the previous file."""
    manifest: dict[str, Any] = {}
    codec = "zlib" if compress else "raw"
    for node_id, entry, fingerprint, frozen in plan:
        base = {
            "fingerprint": fingerprint,
            "wall_time": entry.wall_time,
            "timestamp": entry.timestamp,
            "bytes": entry.memory_bytes,
            "ports": list(entry.ports()),
        }
        alias = _alias_meta(entry, manifest, frozen)
        if alias is not None:
            manifest[node_id] = {**base, "alias": alias}
            tick()
            continue

        if not entry.resident:
            size = _copy_spilled(writer, prev, node_id)
            if size < 0:
                tick()
                continue        # source blob gone — loads dirty next open
            manifest[node_id] = {**base, "disk_bytes": size}
            tick()
            continue

        try:
            raw_bytes, disk_bytes = _pickle_blob(
                writer, node_id, entry.outputs, compress)
        except OSError:
            raise
        except Exception:
            tick()
            continue            # unpicklable output — loads dirty next open
        manifest[node_id] = {**base, "codec": codec,
                             "raw_bytes": raw_bytes, "disk_bytes": disk_bytes}
        tick()
    return manifest


def _carry_all_blobs(writer: "container.BundleWriter", prev: "Any",
                     tick: "Any") -> dict[str, Any]:
    """Copy every blob the previous file held, verbatim, and keep its
    manifest entries — the mid-run save. Nothing is re-pickled."""
    if prev is None:
        return {}
    text = prev.read_text("manifest.json")
    if text is None:
        return {}
    try:
        nodes = json.loads(text).get("nodes", {})
    except (ValueError, AttributeError):
        return {}
    kept: dict[str, Any] = {}
    for node_id, meta in nodes.items():
        if is_alias(meta):
            kept[node_id] = meta
            tick()
            continue
        try:
            src = prev.blob_open(node_id)
        except OSError:
            tick()
            continue            # blob gone — that node loads dirty next open
        with src:
            writer.copy_blob(src, node_id)
        kept[node_id] = meta
        tick()
    return kept
