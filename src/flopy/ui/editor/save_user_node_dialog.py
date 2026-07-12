"""Dialog for saving a node's current code as a reusable user library node."""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
    QVBoxLayout,
)

from flopy.core.user_nodes import slugify, type_id_for

_NO_GROUP = "(no group)"


class SaveUserNodeDialog(QDialog):
    """Collect a Name and Group for a new user node. `result()` returns
    (name, group) via `values()` when accepted; group is None when ungrouped."""

    def __init__(self, default_name: str, groups: list[str],
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save as user node")

        self._name = QLineEdit(default_name)
        self._group = QComboBox()
        self._group.setEditable(True)
        self._group.addItem(_NO_GROUP)
        for g in groups:
            self._group.addItem(g)
        self._group.setCurrentIndex(0)
        self._preview = QLabel()
        self._preview.setStyleSheet("color: #9ca3af;")

        form = QFormLayout()
        form.addRow("Name", self._name)
        form.addRow("Group", self._group)
        form.addRow("Type id", self._preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._ok = buttons.button(QDialogButtonBox.Ok)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._name.textChanged.connect(self._refresh)
        self._group.editTextChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        name, group = self.values()
        stem = slugify(name) if name.strip() else ""
        self._preview.setText(type_id_for(group, stem) if stem else "—")
        self._ok.setEnabled(bool(stem))

    def values(self) -> tuple[str, Optional[str]]:
        name = self._name.text().strip()
        raw = self._group.currentText().strip()
        group = None if raw in ("", _NO_GROUP) else slugify(raw)
        return name, group
