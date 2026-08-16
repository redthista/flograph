"""Secrets manager (Tools > Secrets…) — the .env file behind `${env:NAME}`.

The point of the whole mechanism is that a password never enters the
.flograph file, which `serialization.graph_to_dict` writes verbatim and
which gets emailed around. So this dialog edits a *separate* file and the
project stores only its path — relative to the project where it can be, so a
team can each hold their own copy at the same spot.

Values are masked in the table by default. Not theatre: this is a dialog
somebody opens while screen-sharing to check which keys exist, which is
exactly when the values should not be on the glass.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from flograph.core import dotenv
from flograph.core.varlinks import env_references

MASK = "••••••••"


def usage_counts(graph) -> dict[str, int]:
    """How many nodes reference each secret. Shown beside the key so it is
    obvious which entries are load-bearing and which are leftovers."""
    counts: dict[str, int] = {}
    for node in graph.nodes.values():
        for name in env_references(node):
            counts[name] = counts.get(name, 0) + 1
    return counts


class EnvDialog(QDialog):
    """Edit the project's secrets file. `accept()` writes it and tells the
    graph, which re-runs whatever reads one."""

    def __init__(self, graph, project_path: Optional[str] = None,
                 undo_stack=None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Secrets")
        self.resize(560, 380)
        self._graph = graph
        self._project_path = project_path
        self._undo_stack = undo_stack
        self._path = dotenv.resolve_path(graph.env_path, project_path)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Values here are referenced as <code>${env:NAME}</code> in any "
            "text box. They are stored in the file below, never in the "
            "project."))

        self._path_edit = QLineEdit(str(self._path))
        self._path_edit.setReadOnly(True)
        browse = QPushButton("Choose…")
        browse.setToolTip("Use an existing .env file, or create one here")
        browse.clicked.connect(self._choose)
        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("File"))
        path_row.addWidget(self._path_edit, 1)
        path_row.addWidget(browse)
        layout.addLayout(path_row)

        self._table = QTableWidget(0, 3, self)
        self._table.setHorizontalHeaderLabels(["Name", "Value", "Used by"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        layout.addWidget(self._table, 1)

        self._reveal = QCheckBox("Show values")
        self._reveal.toggled.connect(self._apply_mask)
        add = QPushButton("Add")
        add.clicked.connect(self._add_row)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove_row)
        tools = QHBoxLayout()
        tools.addWidget(self._reveal)
        tools.addStretch(1)
        tools.addWidget(add)
        tools.addWidget(remove)
        layout.addLayout(tools)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load()

    # ------------------------------------------------------------- table

    def _load(self) -> None:
        values = dotenv.load(self._path)
        counts = usage_counts(self._graph)
        # Referenced-but-missing keys are listed with an empty value rather
        # than left out: "the node wants DB_PASS and this file hasn't got
        # one" is the question this dialog exists to answer.
        for name in counts:
            values.setdefault(name, "")
        self._table.setRowCount(0)
        for name in sorted(values):
            self._append(name, values[name], counts.get(name, 0))
        self._apply_mask()

    def _append(self, name: str, value: str, used: int) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(name))
        item = QTableWidgetItem(value)
        # The real value rides along on the item, so masking is a display
        # change and cannot lose what the user typed.
        item.setData(Qt.UserRole, value)
        self._table.setItem(row, 1, item)
        used_item = QTableWidgetItem(str(used) if used else "—")
        used_item.setFlags(Qt.ItemIsEnabled)
        used_item.setTextAlignment(Qt.AlignCenter)
        self._table.setItem(row, 2, used_item)

    def _apply_mask(self) -> None:
        show = self._reveal.isChecked()
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 1)
            if item is None:
                continue
            if show:
                item.setText(str(item.data(Qt.UserRole) or ""))
            else:
                # Committing the edit first, so toggling the mask off never
                # discards something typed while it was on.
                item.setData(Qt.UserRole, self._value_of(item))
                item.setText(MASK if item.data(Qt.UserRole) else "")

    @staticmethod
    def _value_of(item: QTableWidgetItem) -> str:
        """What this row actually holds — the edited text when it is
        visible, the stashed value when it is masked."""
        text = item.text()
        if text == MASK:
            return str(item.data(Qt.UserRole) or "")
        return text

    def _add_row(self) -> None:
        was_masked = not self._reveal.isChecked()
        if was_masked:
            self._reveal.setChecked(True)   # you cannot type into a mask
        self._append("", "", 0)
        self._table.editItem(self._table.item(self._table.rowCount() - 1, 0))

    def _remove_row(self) -> None:
        rows = sorted({index.row() for index in
                       self._table.selectedIndexes()}, reverse=True)
        for row in rows:
            self._table.removeRow(row)

    # -------------------------------------------------------------- save

    def _choose(self) -> None:
        start = str(self._path.parent if self._path.parent.exists()
                    else Path.home())
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Secrets file", str(Path(start) / dotenv.FILENAME),
            "Environment files (*.env);;All files (*)")
        if not chosen:
            return
        self._path = Path(chosen)
        self._path_edit.setText(chosen)
        self._load()

    def values(self) -> dict[str, str]:
        """What the table currently holds, blank names dropped."""
        values: dict[str, str] = {}
        for row in range(self._table.rowCount()):
            name_item = self._table.item(row, 0)
            value_item = self._table.item(row, 1)
            if name_item is None or value_item is None:
                continue
            name = name_item.text().strip()
            if name:
                values[name] = self._value_of(value_item)
        return values

    def _save(self) -> None:
        values = self.values()
        bad = sorted(n for n in values if not dotenv.is_valid_key(n))
        if bad:
            QMessageBox.warning(
                self, "Secrets",
                "These names can't be referenced as ${env:NAME}: "
                + ", ".join(bad))
            return
        try:
            dotenv.save(self._path, values)
        except OSError as exc:
            QMessageBox.warning(self, "Secrets", f"Could not write the file:\n{exc}")
            return
        self.apply_to_graph()
        self.accept()

    def apply_to_graph(self) -> None:
        """Point the graph at this file and reload it. Separate from _save so
        the file write and the graph update can be tested apart.

        The path goes through the undo stack, because it is project state
        the graph carries; the loaded values do not, because they mirror a
        file this cannot put back. See commands.SetEnvPathCommand.
        """
        stored = dotenv.store_path(str(self._path), self._project_path)
        if stored != self._graph.env_path:
            if self._undo_stack is not None:
                from .commands import SetEnvPathCommand
                self._undo_stack.push(SetEnvPathCommand(self._graph, stored))
            else:
                self._graph.set_env_path(stored)
        self._graph.set_env(dotenv.environment(self._path))
