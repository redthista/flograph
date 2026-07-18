"""Shared checkbox/radio list for Slicer nodes — hosted by the canvas card
and by dashboard tiles. The widget only reflects and reports ticks; the
host commits the emitted param value and triggers the downstream re-run."""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QToolButton,
    QWidget,
)

from . import theme

MAX_OPTIONS = 500  # checkbox rows shown before truncating
MODES = ("multi", "single")


def selected_param_values(raw) -> list[str]:
    """The ticked values of a Slicer's "selected" param as strings: a JSON
    array normally (this widget writes that), falling back to a
    comma-separated list for hand edits."""
    raw = str(raw or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return [str(v) for v in parsed] if isinstance(parsed, list) \
            else [str(parsed)]
    except ValueError:
        return [part.strip() for part in raw.split(",") if part.strip()]


class SlicerListWidget(QListWidget):
    # the new "selected" param value: a JSON array, or "" for nothing ticked
    selection_committed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"QListWidget {{ background: {theme.NODE_BODY.name()};"
            f" color: {theme.NODE_TEXT.name()}; border: none;"
            f" font-size: 9pt; }}"
            f"QListWidget::item {{ padding: 1px 2px; }}")
        self._syncing = False
        self._mode = "multi"
        self._filter_text = ""
        self.itemChanged.connect(self._on_item_changed)

    def set_options(self, values: list[str], selected: set[str]) -> None:
        """Rebuild the checkbox rows from a column's unique values, ticking
        those in `selected`. Every tick re-runs the slicer and lands back
        here (the options come from the freshly-cached upstream table), so
        an active search filter is re-applied — otherwise the list would
        silently reset to "everything visible" mid-search on the first
        tick."""
        self._syncing = True
        try:
            self.clear()
            for value in values[:MAX_OPTIONS]:
                item = QListWidgetItem(value)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.Checked if value in selected else Qt.Unchecked)
                self.addItem(item)
            if len(values) > MAX_OPTIONS:
                extra = QListWidgetItem(
                    f"… {len(values) - MAX_OPTIONS:,} more values")
                extra.setFlags(Qt.NoItemFlags)
                self.addItem(extra)
        finally:
            self._syncing = False
        if self._filter_text:
            self._apply_filter(self._filter_text)

    def set_mode(self, mode: str) -> None:
        """"multi" (any number of ticks) or "single" (radio-style: ticking
        one clears the rest, and clicking the ticked value again clears it).
        Flipping from multi to single with more than one value already
        ticked trims down to the first, so the card and the "selected" param
        it commits never disagree about how many values are active."""
        mode = mode if mode in MODES else "multi"
        entering_single = mode == "single" and self._mode != "single"
        self._mode = mode
        if entering_single:
            self._trim_to_single_selection()

    def _trim_to_single_selection(self) -> None:
        checked = [i for i in range(self.count())
                  if self.item(i).flags() & Qt.ItemIsUserCheckable
                  and self.item(i).checkState() == Qt.Checked]
        if len(checked) <= 1:
            return
        self._syncing = True
        try:
            for i in checked[1:]:
                self.item(i).setCheckState(Qt.Unchecked)
        finally:
            self._syncing = False
        self._commit()

    def sync_checks(self, selected: set[str]) -> None:
        """Re-apply check states without re-emitting — for when the param
        changes elsewhere (properties panel, undo)."""
        self._syncing = True
        try:
            for i in range(self.count()):
                item = self.item(i)
                if item.flags() & Qt.ItemIsUserCheckable:
                    item.setCheckState(Qt.Checked if item.text() in selected
                                       else Qt.Unchecked)
        finally:
            self._syncing = False

    def set_filter(self, text: str) -> None:
        """Hide rows that don't match `text` (case-insensitive substring).
        Rows are hidden, never removed, so ticks on values outside the
        current search are never lost. Remembered and re-applied by
        `set_options`, so a tick mid-search doesn't reset the list."""
        self._filter_text = text.strip()
        self._apply_filter(self._filter_text)

    def _apply_filter(self, needle: str) -> None:
        needle = needle.lower()
        for i in range(self.count()):
            item = self.item(i)
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setHidden(bool(needle) and needle not in item.text().lower())
            else:
                item.setHidden(bool(needle))  # the "N more values" note

    def select_all(self) -> None:
        """Tick every visible (unfiltered) row — a no-op in single mode."""
        if self._mode == "single":
            return
        self._set_visible_checks(Qt.Checked)

    def clear_all(self) -> None:
        """Untick every visible (unfiltered) row."""
        self._set_visible_checks(Qt.Unchecked)

    def _set_visible_checks(self, state) -> None:
        self._syncing = True
        try:
            for i in range(self.count()):
                item = self.item(i)
                if item.flags() & Qt.ItemIsUserCheckable and not item.isHidden():
                    item.setCheckState(state)
        finally:
            self._syncing = False
        self._commit()

    def selected_values(self) -> list[str]:
        return [self.item(i).text() for i in range(self.count())
                if self.item(i).checkState() == Qt.Checked]

    def selection_summary(self) -> str:
        """"N/M" ticked-of-total for a compact status label; "" when there
        are no rows yet."""
        total = sum(1 for i in range(self.count())
                    if self.item(i).flags() & Qt.ItemIsUserCheckable)
        if not total:
            return ""
        return f"{len(self.selected_values())}/{total}"

    def _on_item_changed(self, item) -> None:
        if self._syncing:
            return
        if self._mode == "single" and item.checkState() == Qt.Checked:
            self._syncing = True
            try:
                for i in range(self.count()):
                    other = self.item(i)
                    if other is not item and other.flags() & Qt.ItemIsUserCheckable:
                        other.setCheckState(Qt.Unchecked)
            finally:
                self._syncing = False
        self._commit()

    def _commit(self) -> None:
        selected = self.selected_values()
        self.selection_committed.emit(json.dumps(selected) if selected else "")


class SlicerToolbar(QWidget):
    """Compact search box + Select All / None row that drives a
    SlicerListWidget — a separate widget so both hosts (canvas card,
    dashboard tile) can lay it out above their list without the list itself
    changing shape."""

    def __init__(self, target: SlicerListWidget, parent=None) -> None:
        super().__init__(parent)
        self._target = target
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 2)
        layout.setSpacing(2)

        search = QLineEdit()
        search.setPlaceholderText("Search…")
        search.setClearButtonEnabled(True)
        search.textChanged.connect(target.set_filter)
        layout.addWidget(search, 1)

        select_all = QToolButton()
        select_all.setText("All")
        select_all.setToolTip("Select every visible value")
        select_all.clicked.connect(target.select_all)
        layout.addWidget(select_all)
        self._select_all = select_all

        clear = QToolButton()
        clear.setText("None")
        clear.setToolTip("Clear the selection")
        clear.clicked.connect(target.clear_all)
        layout.addWidget(clear)

        count = QLabel("")
        count.setToolTip("Values ticked, of the total on this column")
        layout.addWidget(count)
        self._count = count

        self.setStyleSheet(
            f"QLineEdit {{ background: {theme.NODE_BODY.name()};"
            f" color: {theme.NODE_TEXT.name()};"
            f" border: 1px solid {theme.NODE_BORDER.name()};"
            f" border-radius: 3px; padding: 1px 3px; font-size: 8pt; }}"
            f"QToolButton {{ font-size: 8pt; padding: 1px 4px; }}"
            f"QLabel {{ color: {theme.NODE_SUBTEXT.name()}; font-size: 8pt; }}")

        target.selection_committed.connect(lambda _v: self.refresh_summary())

    def set_mode(self, mode: str) -> None:
        """Select All is meaningless once only one value can be picked."""
        self._select_all.setVisible(mode != "single")

    def refresh_summary(self) -> None:
        """Re-read the "N/M" count off the target list — hosts call this
        after repopulating it (set_options/sync_checks don't themselves
        emit selection_committed)."""
        self._count.setText(self._target.selection_summary())
