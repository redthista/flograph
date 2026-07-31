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
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional


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

    def summary(self, port: str) -> str:
        return summarize(self.outputs.get(port))


class OutputCache:
    def __init__(self) -> None:
        self._entries: dict[str, CacheEntry] = {}

    def set(self, node_id: str, outputs: dict[str, Any], wall_time: float,
            alias_of: Optional[str] = None,
            alias_port: Optional[str] = None) -> None:
        memory_bytes = sum(estimate_size(v) for v in outputs.values())
        self._entries[node_id] = CacheEntry(
            outputs=outputs, wall_time=wall_time, memory_bytes=memory_bytes,
            alias_of=alias_of, alias_port=alias_port,
        )

    def get(self, node_id: str) -> Optional[CacheEntry]:
        return self._entries.get(node_id)

    def has(self, node_id: str) -> bool:
        return node_id in self._entries

    def outputs_for(self, node_id: str) -> dict[str, Any]:
        entry = self._entries.get(node_id)
        return entry.outputs if entry else {}

    def total_bytes(self) -> int:
        """What the project is actually holding — each value counted once.

        An alias is skipped only while the entry it shares with is still
        here. That proviso is not pedantry: a frozen Goto keeps its value
        when the node upstream is evicted, and at that point the link is the
        only thing holding the object, so it is the one that has to be
        counted.
        """
        return sum(entry.memory_bytes for entry in self._entries.values()
                   if entry.alias_of is None
                   or entry.alias_of not in self._entries)

    def evict(self, node_id: str) -> None:
        self._entries.pop(node_id, None)

    def clear(self) -> None:
        self._entries.clear()


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
