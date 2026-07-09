"""Qt-free observer primitives.

The core model must not depend on Qt, but the UI and engine need change
notification. `Event` is a minimal callback list; `GraphEvents` bundles one
Event per kind of graph mutation.
"""
from __future__ import annotations

import contextlib
from typing import Any, Callable


class Event:
    __slots__ = ("_subscribers",)

    def __init__(self) -> None:
        self._subscribers: list[Callable[..., Any]] = []

    def connect(self, callback: Callable[..., Any]) -> None:
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def disconnect(self, callback: Callable[..., Any]) -> None:
        with contextlib.suppress(ValueError):
            self._subscribers.remove(callback)

    def emit(self, *args: Any, **kwargs: Any) -> None:
        for callback in list(self._subscribers):
            callback(*args, **kwargs)


class GraphEvents:
    """One Event per graph mutation. Payloads documented per attribute."""

    def __init__(self) -> None:
        self.node_added = Event()      # (node: NodeInstance)
        self.node_removed = Event()    # (node_id: str)
        self.connected = Event()       # (conn: Connection)
        self.disconnected = Event()    # (conn: Connection)
        self.node_moved = Event()      # (node_id: str, pos: tuple[float, float])
        self.param_changed = Event()   # (node_id: str, name: str, value: Any)
        self.code_changed = Event()    # (node_id: str)
        self.label_changed = Event()   # (node_id: str)
        self.dirty_changed = Event()   # (node_id: str, dirty: bool)
        self.status_changed = Event()  # (node_id: str, status: NodeStatus, message: str)
        self.frame_added = Event()     # (frame: Frame)
        self.frame_removed = Event()   # (frame_id: str)
        self.frame_changed = Event()   # (frame: Frame)
