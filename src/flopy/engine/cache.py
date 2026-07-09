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

    def summary(self, port: str) -> str:
        return summarize(self.outputs.get(port))


class OutputCache:
    def __init__(self) -> None:
        self._entries: dict[str, CacheEntry] = {}

    def set(self, node_id: str, outputs: dict[str, Any], wall_time: float) -> None:
        self._entries[node_id] = CacheEntry(outputs=outputs, wall_time=wall_time)

    def get(self, node_id: str) -> Optional[CacheEntry]:
        return self._entries.get(node_id)

    def has(self, node_id: str) -> bool:
        return node_id in self._entries

    def outputs_for(self, node_id: str) -> dict[str, Any]:
        entry = self._entries.get(node_id)
        return entry.outputs if entry else {}

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
