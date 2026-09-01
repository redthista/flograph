"""Click-a-header-to-sort, shared by the read-only data tables and the
editable Table-node grid.

Two things live here:

- :class:`HeaderSortCycler` — the interaction. Qt's own
  ``setSortingEnabled(True)`` only ever toggles ascending/descending and
  fires on the first press, before a double-click (which the grid uses to
  rename a column) can arrive. This drives the header itself: a click
  cycles a column through ascending -> descending -> cleared, a
  single-shot timer holds the action back long enough to tell a rename
  double-click apart, and the sort indicator is kept in step.

- :func:`pandas_sort_key` — the "which way is up" for a DataFrame column.
  Real dtypes (numbers, ``datetime64``, bool, category) already sort
  correctly, so they pass straight through. An ``object`` column is
  sniffed: numbers stored as text sort numerically, dates stored as text
  sort chronologically, and anything else sorts case-insensitively.

The grid's equivalent key lives in ``core/sheet/schema.py`` instead —
that module must not import pandas.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QHeaderView

# Fraction of a sampled object column that must parse as one type before we
# sort the whole column as that type. High enough that a stray numeric code
# in a text column doesn't flip it, low enough to tolerate a few bad cells.
_DETECT_THRESHOLD = 0.9
_DETECT_SAMPLE = 1000


def pandas_sort_key(series):
    """The series pandas should actually order when sorting ``series``.

    Passed as ``key=`` to :meth:`DataFrame.sort_values`. Same shape out as
    in; NaT/NaN survive so ``na_position`` still applies.
    """
    import pandas as pd
    from pandas.api import types as pdt

    # Numbers, datetimes, timedeltas, bools and categoricals already order
    # correctly; only string / object / mixed columns need sniffing.
    if (pdt.is_numeric_dtype(series)
            or pdt.is_datetime64_any_dtype(series)
            or pdt.is_timedelta64_dtype(series)
            or isinstance(series.dtype, pd.CategoricalDtype)):
        return series

    sample = series.dropna().astype(str).head(_DETECT_SAMPLE)
    if sample.empty:
        return series

    as_num = pd.to_numeric(sample, errors="coerce")
    if as_num.notna().mean() >= _DETECT_THRESHOLD:
        return pd.to_numeric(series, errors="coerce")

    as_dt = pd.to_datetime(sample, errors="coerce", format="mixed")
    if as_dt.notna().mean() >= _DETECT_THRESHOLD:
        return pd.to_datetime(series, errors="coerce", format="mixed")

    return series.astype("string").str.casefold()


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
