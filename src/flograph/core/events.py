"""Qt-free observer primitives.

The core model must not depend on Qt, but the UI and engine need change
notification. `Event` is a minimal callback list; `GraphEvents` bundles one
Event per kind of graph mutation.
"""
from __future__ import annotations

import contextlib
import sys
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
        """Tell every subscriber, whatever any one of them does about it.

        A subscriber is a view of the change, not part of it, so one that
        raises is reported and the rest are still told — the rule Qt's own
        signals keep. Letting it propagate instead unwound whoever made the
        change, half-way through: a card that fell over as a node went DONE
        took the scheduler's next step with it, leaving the node green, the
        one after it orange forever and the run never ending.

        Reported through sys.excepthook rather than swallowed, so the
        traceback still reaches the console — and pytest-qt, which hooks it,
        still fails the test.
        """
        for callback in list(self._subscribers):
            try:
                callback(*args, **kwargs)
            except Exception:
                sys.excepthook(*sys.exc_info())


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
        self.description_changed = Event()  # (node_id: str)
        self.active_changed = Event()  # (node_id: str, active: bool)
        self.locked_changed = Event()  # (node_id: str, locked: bool)
        self.frozen_changed = Event()  # (node_id: str, frozen: bool)
        self.manual_changed = Event()  # (node_id: str, manual: bool)
        self.bypassed_changed = Event()  # (node_id: str, bypassed: bool)
        self.drop_output_changed = Event()  # (node_id: str, drop: bool)
        self.released_changed = Event()  # (node_id: str, released: bool)
        self.preview_enabled_changed = Event()  # (node_id: str, enabled: bool)
        self.port_labels_changed = Event()  # (node_id: str)
        self.flow_pins_changed = Event()    # (node_id: str)
        self.ports_collapsed_changed = Event()  # (node_id: str)
        self.color_changed = Event()   # (node_id: str)
        self.mark_changed = Event()    # (node_id: str)
        self.compact_view_changed = Event()  # (node_id: str)
        self.links_changed = Event()   # () — the derived Goto/From link set moved
        self.dirty_changed = Event()   # (node_id: str, dirty: bool)
        self.status_changed = Event()  # (node_id: str, status: NodeStatus, message: str)
        self.progress_changed = Event()  # (node_id: str, fraction: float)
        self.temp_edit_changed = Event()  # (node_id: str, has_temp_edit: bool)
        # (kind: "node"|"frame"|"shape", item_id: str) — it moved to another
        # canvas (G12/G13), so which tab draws it changed. Position and
        # wires are untouched, which is why this is not node_moved.
        self.item_canvas_changed = Event()
        self.frame_added = Event()     # (frame: Frame)
        self.frame_removed = Event()   # (frame_id: str)
        self.frame_changed = Event()   # (frame: Frame)
        self.shape_added = Event()     # (shape: Shape)
        self.shape_removed = Event()   # (shape_id: str)
        self.shape_changed = Event()   # (shape: Shape)
        self.page_added = Event()      # (page: Page)
        self.page_removed = Event()    # (page_id: str)
        self.page_changed = Event()    # (page: Page)
        self.page_body_changed = Event()  # (page: Page) — report markdown
        self.pages_reordered = Event()  # (order: list[str]) — page ids, new order
        self.page_groups_changed = Event()  # () — a tab-bar group's colour
        self.tile_added = Event()      # (page_id: str, tile: Tile)
        self.tile_removed = Event()    # (page_id: str, tile_id: str)
        self.tile_changed = Event()    # (page_id: str, tile: Tile)
        # (kind: "node"|"frame"|"shape"|"tile", page_id: str|None) — the stacking
        # order of that whole kind changed; hosts re-read z for every item
        # they own rather than being told which ones moved
        self.restacked = Event()
