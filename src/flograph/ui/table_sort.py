"""Click-a-header-to-sort, shared by the read-only data tables and the
editable Table-node grid.

:class:`HeaderSortCycler` is the interaction, and the only thing still
defined here. Qt's own ``setSortingEnabled(True)`` only ever toggles
ascending/descending and fires on the first press, before a double-click
(which the grid uses to rename a column) can arrive. This drives the
header itself: a click cycles a column through ascending -> descending ->
cleared, a single-shot timer holds the action back long enough to tell a
rename double-click apart, and the sort indicator is kept in step.

:func:`pandas_sort_key` — the "which way is up" for a DataFrame column —
moved to :mod:`flograph.core.table_sort` when a table gained a *default*
sort, because a sort set as a rule has to reach the printed report too and
the report renderer may not import Qt. It is re-exported here, where every
caller already looks.

The grid's equivalent key lives in ``core/sheet/schema.py`` instead —
that module must not import pandas.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QHeaderView

# The "which way is up" half of this module now lives in
# `core.table_sort`, so that the report renderer — which is core and
# Qt-free — orders a printed table exactly as the card orders it. Kept
# importable from here, which is where every caller already looks.
from flograph.core.table_sort import (  # noqa: F401  (re-export)
    pandas_sort_key, sort_positions, sorted_frame)


class HeaderSortCycler(QObject):
    """Attach to a horizontal ``QHeaderView`` to make its sections sort on
    click, cycling asc -> desc -> clear.

    Emits :attr:`sortRequested` with ``mode`` one of ``"asc"``,
    ``"desc"`` or ``"clear"``. The owner does the actual reordering and,
    for ``"clear"``, the restore.
    """

    sortRequested = Signal(int, str)

    _NEXT = {None: "asc", "asc": "desc", "desc": "clear", "clear": "asc"}

    def __init__(self, header: QHeaderView, can_sort=None) -> None:
        super().__init__(header)
        self._header = header
        self._can_sort = can_sort   # optional () -> bool, checked per click
        self._column: int | None = None
        self._mode: str | None = None
        self._enabled = True

        self._pending: int | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fire)

        header.setSortIndicatorShown(False)
        header.sectionClicked.connect(self._on_clicked)
        header.sectionDoubleClicked.connect(self._cancel)

    def set_enabled(self, flag: bool) -> None:
        """Turn click-to-sort off (e.g. a linked, read-only grid)."""
        self._enabled = bool(flag)
        if not self._enabled:
            self._cancel()
            self.reset()

    def reset(self) -> None:
        """Forget the current sort — call when the model is replaced."""
        self._timer.stop()
        self._pending = None
        self._column = None
        self._mode = None
        self._header.setSortIndicatorShown(False)

    # ---------------------------------------------------------- internals

    def _on_clicked(self, column: int) -> None:
        if not self._enabled or (self._can_sort is not None
                                 and not self._can_sort()):
            return
        self._pending = column
        self._timer.start(max(150, QApplication.doubleClickInterval()))

    def _cancel(self, *_) -> None:
        self._timer.stop()
        self._pending = None

    def _fire(self) -> None:
        column = self._pending
        self._pending = None
        if column is None:
            return

        if column != self._column:
            self._column, self._mode = column, "asc"
        else:
            self._mode = self._NEXT[self._mode]

        if self._mode == "clear":
            self._column = None
            self._mode = None
            self._header.setSortIndicatorShown(False)
            self.sortRequested.emit(column, "clear")
            return

        order = (Qt.AscendingOrder if self._mode == "asc"
                 else Qt.DescendingOrder)
        self._header.setSortIndicatorShown(True)
        self._header.setSortIndicator(column, order)
        self.sortRequested.emit(column, self._mode)
