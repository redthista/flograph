"""Per-node output cache.

Values are held by reference (nodes must treat inputs as read-only — see the
node contract). What is handed downstream is guarded wherever that is free:
pandas values as copy-on-write shallow copies, containers rebuilt one level
deep, numpy arrays as read-only views, so a node writing to its input cannot
reach back into the entry cached here — see scheduler._read_only_view.
Invariant maintained by the engine: a node is clean iff its outputs are
cached; dirtying a node evicts its entry.

Some nodes hand their input straight back — Goto, From, Reroute — so several
entries can end up serving one and the same object. Those entries record an
`alias_of`, which is what keeps a single DataFrame from being counted, and
later written to disk, once per hop.

An entry is *resident* (its values are in memory) or *spilled* (its values are
on disk in the project's side-car and it knows how to get them back). Both are
cached, which is what matters: the engine's invariant is "a node is clean iff
its outputs are cached", so a value may never simply vanish, but it is free to
be somewhere slower. A spilled entry carries an empty `outputs`, so the many
readers that only want to show a preview see "nothing to show" and leave the
disk alone; the engine calls `outputs_for`, which brings the value back.

This module stays free of I/O: it decides *what* should be in memory, and a
loader supplied by the caller (see set_loader) knows how to read a blob. That
keeps the policy testable without a filesystem and avoids an import cycle with
cache_persistence.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from flograph.core.events import Event


@dataclass
class CacheEntry:
    outputs: dict[str, Any]
    wall_time: float                    # seconds spent computing
    timestamp: float = field(default_factory=time.time)
    memory_bytes: int = 0                # estimated size of outputs, computed once at cache time
    # The node this entry is re-serving, if it is not carrying a value of its
    # own: the object here *is* the object cached against `alias_of`, under
    # port `alias_port` there. Set by the engine when a node returns its input
    # untouched. `memory_bytes` stays truthful — it describes the value, and
    # the value is real — so the per-node readout still says how big the thing
    # is; it is the project total that has to stop adding it up twice.
    alias_of: Optional[str] = None
    alias_port: Optional[str] = None
    # Whether the values are on disk rather than in `outputs`. An explicit
    # flag, not "blob is None": an alias has no blob of its own even when it
    # is spilled, because it re-serves a value another entry owns.
    spilled: bool = False
    # Set while spilled and not an alias: the project whose side-car holds
    # this entry's blob. `memory_bytes` keeps describing the value while it is
    # away, on the same principle as an alias — the value is real, it is just
    # not here.
    blob: Optional[str] = None
    # Port names, which a spilled entry would otherwise not know: they come
    # from the value, and the value is on disk. Empty for pre-existing
    # side-cars written before the manifest recorded them.
    port_names: tuple[str, ...] = ()
    # {port: column names} for every output that is a DataFrame, on the same
    # principle as `port_names` and for the same reason: the Properties
    # panel's column pickers ask what columns feed a node, and asking the
    # value would mean reading gigabytes off disk to list some strings. So
    # the strings are recorded while the value is in hand and travel in the
    # manifest. None — not {} — for a side-car written before this was
    # recorded: the two have to be told apart, because {} is the honest
    # answer for an entry that carries no frame, while None means "nobody
    # wrote this down" and is the only case worth a disk read.
    column_names: Optional[dict[str, tuple[str, ...]]] = None

    @property
    def resident(self) -> bool:
        """Whether the values are in memory right now."""
        return not self.spilled

    def ports(self) -> tuple[str, ...]:
        return tuple(self.outputs) if self.resident else self.port_names

    def columns(self, port: str) -> Optional[tuple[str, ...]]:
        """This port's column names, or None if they are not known without
        reading the value.

        A resident entry answers from the value. A spilled one answers from
        what the manifest recorded — that is the whole point — and returns
        None only for a side-car written before columns were recorded, so a
        caller can decide whether listing them is worth a disk read."""
        if self.resident:
            return column_names_of(self.outputs.get(port))
        if self.column_names is None:
            return None
        return self.column_names.get(port, ())

    def recorded_columns(self) -> Optional[dict[str, tuple[str, ...]]]:
        """The {port: columns} map to write to the manifest, in whatever
        state this entry is in. None only when a spilled entry never had one
        — carried forward as None rather than {} so a re-save does not claim
        to know that an old side-car's entry has no columns."""
        return column_map(self.outputs) if self.resident else self.column_names

    def summary(self, port: str) -> str:
        if not self.resident:
            return "not loaded"
        return summarize(self.outputs.get(port))


class OutputCache:
    def __init__(self) -> None:
        self._entries: dict[str, CacheEntry] = {}
        self._loader: Optional[Callable[[str, str], dict[str, Any]]] = None
        # Fired (node_id) when a spilled entry comes back to life. This is
        # the notification the whole lazy-open design was missing: cards are
        # built against a cache where everything is on disk, and without it
        # nothing ever told them when a value they were showing as a
        # placeholder had actually arrived. Fired on the GUI thread — every
        # path that reaches mark_resident ends there.
        self.became_resident = Event()

    def set_loader(
        self, loader: Optional[Callable[[str, str], dict[str, Any]]],
    ) -> None:
        """Supply the "read this node's blob back" function, as
        `loader(project_path, node_id) -> outputs`.

        Injected rather than imported so this module does no I/O and the
        eviction/residency policy can be tested without a filesystem.
        """
        self._loader = loader

    def set(self, node_id: str, outputs: dict[str, Any], wall_time: float,
            alias_of: Optional[str] = None,
            alias_port: Optional[str] = None) -> None:
        memory_bytes = sum(estimate_size(v) for v in outputs.values())
        self._entries[node_id] = CacheEntry(
            outputs=outputs, wall_time=wall_time, memory_bytes=memory_bytes,
            alias_of=alias_of, alias_port=alias_port,
            port_names=tuple(outputs),
            column_names=column_map(outputs),
        )

    def register_spilled(
        self, node_id: str, blob: Optional[str], wall_time: float,
        memory_bytes: int = 0, port_names: tuple[str, ...] = (),
        alias_of: Optional[str] = None, alias_port: Optional[str] = None,
        column_names: Optional[dict[str, tuple[str, ...]]] = None,
    ) -> None:
        """Record that a node's outputs are cached, on disk, and not loaded.

        This is what opening a project does instead of unpickling everything:
        the node counts as clean, nothing is allocated, and the value comes
        back when something actually needs it.

        `blob` is None for an alias, which owns no blob and resolves through
        the entry named by `alias_of` instead.

        `column_names` stays None for a side-car that never recorded them —
        the one case where listing a spilled entry's columns still costs a
        read (see CacheEntry.columns).
        """
        self._entries[node_id] = CacheEntry(
            outputs={}, wall_time=wall_time, memory_bytes=memory_bytes,
            alias_of=alias_of, alias_port=alias_port,
            spilled=True, blob=blob, port_names=tuple(port_names),
            column_names=column_names,
        )

    def mark_resident(self, node_id: str, outputs: dict[str, Any]) -> None:
        """Attach values loaded elsewhere (a pool thread) to a spilled entry.

        A no-op if the entry has gone or has already been recomputed since the
        load started — the fresh value wins, and the stale one is dropped.
        Fires `became_resident` only on a real transition, so late arrivals
        can be told apart from echoes.
        """
        entry = self._entries.get(node_id)
        if entry is None or entry.resident:
            return
        entry.outputs = outputs
        entry.spilled = False
        entry.blob = None
        entry.port_names = tuple(outputs)
        entry.column_names = column_map(outputs)
        if not entry.memory_bytes:
            entry.memory_bytes = sum(estimate_size(v) for v in outputs.values())
        self.became_resident.emit(node_id)
        self._wake_aliases_of(node_id)

    def _wake_aliases_of(self, node_id: str) -> None:
        """A spilled alias owns no blob — it comes to life the instant its
        source does. `materialize` unwinds a chain on demand for the blocking
        path; this is the same unwind for the off-thread warm path, which
        only ever attaches the one entry it read off disk. Without it an
        alias that feeds a card — a Reroute, or a pass-through Slicer, ahead
        of another Slicer — stays a placeholder after its source is warmed,
        because nothing ever told it (or the card below it) that the value
        had arrived. The recursion carries a chain; the object is shared, so
        this allocates nothing.
        """
        source = self._entries.get(node_id)
        if source is None or not source.resident:
            return
        for alias_id, entry in list(self._entries.items()):
            if (entry.resident or entry.alias_of != node_id
                    or entry.alias_port is None
                    or entry.alias_port not in source.outputs):
                continue
            out_port = (entry.port_names[0] if entry.port_names
                        else entry.alias_port)
            self.mark_resident(
                alias_id, {out_port: source.outputs[entry.alias_port]})

    def get(self, node_id: str) -> Optional[CacheEntry]:
        """The entry as it stands. Never touches the disk — a spilled entry
        comes back with empty `outputs`, so callers that only want to show
        what is already in hand degrade to showing nothing, which is the
        honest answer and keeps a project open cheap."""
        return self._entries.get(node_id)

    def has(self, node_id: str) -> bool:
        """Whether the node's outputs are cached — resident *or* spilled.

        Spilled has to count: this is what the engine asks before deciding a
        clean node needs no re-run, and what _blocking_problem asks before
        declaring an upstream produced nothing.
        """
        return node_id in self._entries

    def is_resident(self, node_id: str) -> bool:
        entry = self._entries.get(node_id)
        return entry is not None and entry.resident

    def peek(self, node_id: str) -> dict[str, Any]:
        """Outputs if they happen to be in memory, else empty. Never loads."""
        entry = self._entries.get(node_id)
        return entry.outputs if entry else {}

    def outputs_for(self, node_id: str) -> dict[str, Any]:
        """Outputs, loading them back from disk if they were spilled.

        The engine's accessor: it needs the real value to hand to a node. The
        load is a blocking read, so callers on the GUI thread should have
        warmed the entry first (ExecutionEngine does); this remains correct
        if they did not, just slower.
        """
        entry = self._entries.get(node_id)
        if entry is None:
            return {}
        if not entry.resident:
            self.materialize(node_id)
            entry = self._entries.get(node_id)
            if entry is None:
                return {}
        return entry.outputs

    def materialize(self, node_id: str) -> bool:
        """Bring a spilled entry back into memory. True if it is now resident.

        A failure here is not fatal and must not be silent: the caller drops
        the entry and marks the node dirty, so the result gets recomputed
        rather than reported as missing.

        An alias has no blob of its own — it is re-serving somebody else's
        value — so it resolves through its source, which both keeps the two
        sharing one object (the thing `alias_of` exists to guarantee) and
        avoids reading the same blob twice. Alias chains are walked with an
        explicit stack for the same reason node_fingerprint is: goto -> from
        -> from can be as long as the project is, and a deep one must not
        take the app out on a recursion limit.
        """
        chain: list[str] = []
        current = node_id
        seen: set[str] = set()
        while True:
            entry = self._entries.get(current)
            if entry is None:
                return False
            if entry.resident:
                break
            if entry.alias_of is None or entry.alias_port is None:
                if not self._load_blob_into(current, entry):
                    return False
                break
            if current in seen:
                return False        # a cycle: refuse rather than spin
            seen.add(current)
            chain.append(current)
            current = entry.alias_of

        # Unwind: each alias takes its port from the source now resident.
        for alias_id in reversed(chain):
            entry = self._entries.get(alias_id)
            source = self._entries.get(entry.alias_of) if entry else None
            if entry is None or source is None:
                return False
            if entry.alias_port not in source.outputs:
                return False
            out_port = entry.port_names[0] if entry.port_names else entry.alias_port
            self.mark_resident(alias_id, {out_port: source.outputs[entry.alias_port]})
        return True

    def _load_blob_into(self, node_id: str, entry: CacheEntry) -> bool:
        if self._loader is None or entry.blob is None:
            return False
        try:
            outputs = self._loader(entry.blob, node_id)
        except Exception:
            return False
        if not isinstance(outputs, dict):
            return False
        self.mark_resident(node_id, outputs)
        return True

    def spilled_nodes(self) -> list[str]:
        return [nid for nid, e in self._entries.items() if not e.resident]

    def blob_source(self, node_id: str) -> Optional[str]:
        """Which node's blob has to be read off disk to make `node_id`
        resident, or None if nothing needs reading.

        An alias owns no blob, so the answer for one is its chain's root.
        This is what lets the engine warm a run's inputs on a pool thread and
        then resolve the aliases in memory, rather than discovering the disk
        read halfway through starting a node on the GUI thread.
        """
        seen: set[str] = set()
        current = node_id
        while True:
            entry = self._entries.get(current)
            if entry is None or entry.resident:
                return None
            if entry.alias_of is None:
                return current if entry.blob is not None else None
            if current in seen:
                return None
            seen.add(current)
            current = entry.alias_of

    def total_bytes(self) -> int:
        """What the project is actually holding *in memory*, counted once.

        Spilled entries are excluded: they are cached but they are not held,
        and this number is drawn as a slice of the process's own memory.

        An alias is skipped only while the entry it shares with is still
        here. That proviso is not pedantry: a frozen Goto keeps its value
        when the node upstream is evicted, and at that point the link is the
        only thing holding the object, so it is the one that has to be
        counted.
        """
        return sum(entry.memory_bytes for entry in self._entries.values()
                   if entry.resident and self._counts_toward_total(entry))

    def spilled_bytes(self) -> int:
        """What is cached on disk and not loaded — the memory *not* being
        spent, which is the number worth showing next to the one above."""
        return sum(entry.memory_bytes for entry in self._entries.values()
                   if not entry.resident and self._counts_toward_total(entry))

    def _counts_toward_total(self, entry: CacheEntry) -> bool:
        return (entry.alias_of is None
                or entry.alias_of not in self._entries)

    def heaviest(self, limit: int = 3) -> list[tuple[str, int]]:
        """The nodes holding the most memory, largest first.

        For telling someone whose machine is filling up *which* steps to
        freeze or drop, rather than only that something is. Counted the same
        way as total_bytes, so a value shared down a link chain is credited
        once, to the entry that is really holding it.
        """
        sized = [(node_id, entry.memory_bytes)
                 for node_id, entry in self._entries.items()
                 if entry.resident and self._counts_toward_total(entry)
                 and entry.memory_bytes]
        sized.sort(key=lambda pair: pair[1], reverse=True)
        return sized[:limit]

    def evict(self, node_id: str) -> None:
        self._entries.pop(node_id, None)

    def clear(self) -> None:
        self._entries.clear()


def column_names_of(value: Any) -> tuple[str, ...]:
    """A DataFrame's column names, or () for anything else.

    `sys.modules.get("pandas")` rather than an import: this module is on the
    path of every cache write, and pandas must not be dragged in for a flow
    that never touches it (same rule `summarize` follows).

    `getattr(pd, "DataFrame", None)` because a fast non-pandas node can
    finish — and be cached, on this path — while a parallel worker is still
    partway through its first `import pandas`, so the module object exists
    in `sys.modules` without `DataFrame` bound yet."""
    import sys
    frame_cls = getattr(sys.modules.get("pandas"), "DataFrame", None)
    if frame_cls is None or not isinstance(value, frame_cls):
        return ()
    return tuple(str(col) for col in value.columns)


def column_map(outputs: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    """{port: column names} for the ports carrying a DataFrame. Ports with
    no frame are left out — absent means "no columns", which is what
    CacheEntry.columns() reads it as."""
    found = {}
    for port, value in outputs.items():
        names = column_names_of(value)
        if names:
            found[port] = names
    return found


def summarize(value: Any) -> str:
    """One-line description for the inspector header / tooltips."""
    if value is None:
        return "None"
    type_name = type(value).__name__
    try:
        import sys
        pd = sys.modules.get("pandas")
        if pd is not None:
            if isinstance(value, pd.DataFrame):
                return f"{len(value):,} rows × {len(value.columns)} cols"
            if isinstance(value, pd.Series):
                return f"Series · {len(value):,} values · {value.dtype}"
    except Exception:
        pass
    if isinstance(value, (int, float, bool)):
        return f"{type_name} · {value!r}"
    if isinstance(value, str):
        preview = value if len(value) <= 40 else value[:37] + "..."
        return f"str · {preview!r}"
    if isinstance(value, (list, tuple, dict, set)):
        return f"{type_name} · {len(value)} items"
    return type_name


def estimate_size(value: Any) -> int:
    """Best-effort byte size of a node output, for the memory readouts.

    Best-effort is load-bearing: this runs inside the engine's completion
    slot for every node of every run, so an exception here does not merely
    lose a number — it leaves the run unfinished and the Run button
    disabled. Anything it cannot measure is worth zero, never a raise.
    """
    import sys
    try:
        return _measure(value)
    except Exception:
        return 0


def _measure(value: Any) -> int:
    import sys
    pd = sys.modules.get("pandas")
    if pd is not None:
        if isinstance(value, (pd.DataFrame, pd.Series, pd.Index)):
            used = value.memory_usage(deep=True)
            # A DataFrame answers with a Series, one entry per column; a
            # Series and an Index answer with a plain int. Calling .sum() on
            # all three is the obvious way to write this and raises on two
            # of them — which used to wedge any flow containing a groupby.
            return int(used.sum() if hasattr(used, "sum") else used)
    np = sys.modules.get("numpy")
    if np is not None and isinstance(value, np.ndarray):
        return int(value.nbytes)
    if isinstance(value, dict):
        return sys.getsizeof(value) + sum(
            estimate_size(k) + estimate_size(v) for k, v in value.items()
        )
    if isinstance(value, (list, tuple, set)):
        return sys.getsizeof(value) + sum(estimate_size(v) for v in value)
    try:
        return sys.getsizeof(value)
    except Exception:
        return 0
