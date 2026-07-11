"""Shared checkbox list for Slicer nodes — hosted by the canvas card and by
dashboard tiles. The widget only reflects and reports ticks; the host
commits the emitted param value and triggers the downstream re-run."""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from . import theme

MAX_OPTIONS = 500  # checkbox rows shown before truncating


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
        self.itemChanged.connect(self._on_item_changed)

    def set_options(self, values: list[str], selected: set[str]) -> None:
        """Rebuild the checkbox rows from a column's unique values, ticking
        those in `selected`."""
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

    def selected_values(self) -> list[str]:
        return [self.item(i).text() for i in range(self.count())
                if self.item(i).checkState() == Qt.Checked]

    def _on_item_changed(self, _item) -> None:
        if self._syncing:
            return
        selected = self.selected_values()
        self.selection_committed.emit(json.dumps(selected) if selected else "")
