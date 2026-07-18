"""Per-node output cache.

Values are held by reference (nodes must treat inputs as read-only — see the
node contract). Invariant maintained by the engine: a node is clean iff its
outputs are cached; dirtying a node evicts its entry.
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

    def summary(self, port: str) -> str:
        return summarize(self.outputs.get(port))


class OutputCache:
    def __init__(self) -> None:
        self._entries: dict[str, CacheEntry] = {}

    def set(self, node_id: str, outputs: dict[str, Any], wall_time: float) -> None:
        memory_bytes = sum(estimate_size(v) for v in outputs.values())
        self._entries[node_id] = CacheEntry(
            outputs=outputs, wall_time=wall_time, memory_bytes=memory_bytes,
        )

    def get(self, node_id: str) -> Optional[CacheEntry]:
        return self._entries.get(node_id)

    def has(self, node_id: str) -> bool:
        return node_id in self._entries

    def outputs_for(self, node_id: str) -> dict[str, Any]:
        entry = self._entries.get(node_id)
        return entry.outputs if entry else {}

    def total_bytes(self) -> int:
        return sum(entry.memory_bytes for entry in self._entries.values())

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
    """Best-effort byte size of a node output, for the status bar memory readout."""
    import sys
    pd = sys.modules.get("pandas")
    if pd is not None:
        if isinstance(value, (pd.DataFrame, pd.Series)):
            return int(value.memory_usage(deep=True).sum())
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
