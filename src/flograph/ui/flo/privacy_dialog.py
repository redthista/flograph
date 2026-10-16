"""Columns… — one rule per column: what Flo may know of it.

Every column the flow has in hand is listed (from cached outputs, or the
cache's record of a result still on disk — a node that has not run has no
columns to show yet), plus any column that already has a rule:

- **Hidden** — Flo never learns the column exists.
- **Name only** — the default: its name and type.
- **Name and values** — also its distinct values, so Flo can filter on a
  category by its exact spelling.

The flow's level ("Flo can see") is set on the panel, not here; this only
edits the columns and keeps the level as it is.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHeaderView, QLabel, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from ...core import ai_disclosure as disc

_TIPS = {
    disc.HIDDEN: "Flo never learns this column exists",
    disc.NAME: "Flo sees the column's name and type",
    disc.VALUES: "Flo also sees the column's distinct values (the 100 most "
                 "common), so it can filter on them",
}


def known_columns(graph, cache) -> dict[str, list[str]]:
    """Column name -> labels of the nodes whose output has it."""
    found: dict[str, list[str]] = {}
    if cache is None:
        return found
    for node in graph.nodes.values():
        names: list[str] = []
        try:
            for value in dict(cache.peek(node.id) or {}).values():
                names.extend(disc.column_names(value))
        except Exception:
            pass
        entry = getattr(cache, "get", lambda _id: None)(node.id)
        for recorded in (getattr(entry, "column_names", None) or {}).values():
            names.extend(str(n) for n in recorded)
        for name in names:
            where = found.setdefault(name, [])
            if node.label not in where:
                where.append(node.label)
    return found


class ColumnsDialog(QDialog):
    COLUMNS = ("Column", "Found in", "Flo sees")

    def __init__(self, graph, cache, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Columns — What Flo Knows of Each")
        self.resize(620, 520)
        self._privacy = disc.Privacy.from_dict(graph.ai_privacy)
        layout = QVBoxLayout(self)
        note = QLabel("Saved in this flow, so whoever you send it to gets the "
                      "same rules. Rows are never sent.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(note)

        columns = known_columns(graph, cache)
        for name in self._privacy.columns:
            columns.setdefault(name, [])
        self.table = QTableWidget(len(columns), len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        self._names: list[str] = []
        self.modes: list[QComboBox] = []
        for row, (name, where) in enumerate(sorted(
                columns.items(), key=lambda kv: kv[0].lower())):
            self._names.append(name)
            for col, text in ((0, name), (1, ", ".join(where) or "(not run now)")):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, col, item)
            combo = QComboBox()
            for mode in disc.MODES:
                combo.addItem(disc.MODE_NAMES[mode], mode)
                combo.setItemData(combo.count() - 1, _TIPS[mode], Qt.ToolTipRole)
            combo.setCurrentIndex(combo.findData(self._privacy.mode(name)))
            self.table.setCellWidget(row, 2, combo)
            self.modes.append(combo)
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table, 1)
        if not columns:
            empty = QLabel("No columns are known yet. Run the flow, so its "
                           "tables are in hand, then come back here.")
            empty.setWordWrap(True)
            layout.addWidget(empty)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def set_mode(self, column: str, mode: str) -> None:
        combo = self.modes[self._names.index(column)]
        combo.setCurrentIndex(combo.findData(mode))

    def privacy(self) -> dict:
        """The flow's settings with the columns as the dialog says now."""
        columns = {name: disc.ColumnRule(self.modes[row].currentData())
                   for row, name in enumerate(self._names)}
        return disc.Privacy(self._privacy.level, columns).to_dict()
