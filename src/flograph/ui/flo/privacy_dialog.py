"""The flow's AI privacy: its level cap, and a rule per column.

Every column the flow has in hand is listed (from cached outputs — a node
that has not run has no columns to show yet), plus any column that already
has a rule. *Sensitive* sends the name and type only: no ranges, no
inferred kind. An *alias* replaces the name in everything sent and is
turned back into the real name in what the AI sends back, so a model can
build `x = "Customer"` without ever learning the column is called
`patient_name`. The meaning note goes with the alias, to stand in for what
the real name would have told it.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHeaderView,
    QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QHBoxLayout,
)

from ...core import ai_disclosure as disc
from ...llm.profiles import LEVELS

_NO_CAP = "No limit — the connection and the chat decide"


def known_columns(graph, cache) -> dict[str, list[str]]:
    """Column name -> labels of the nodes whose cached output has it."""
    found: dict[str, list[str]] = {}
    if cache is None:
        return found
    for node in graph.nodes.values():
        try:
            outputs = dict(cache.peek(node.id) or {})
        except Exception:
            continue
        for value in outputs.values():
            for name in disc.column_names(value):
                where = found.setdefault(name, [])
                if node.label not in where:
                    where.append(node.label)
    return found


class PrivacyDialog(QDialog):
    COLUMNS = ("Column", "Found in", "Sensitive", "Shown to the AI as",
               "Meaning (sent with the alias)")

    def __init__(self, graph, cache, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("What the Flo Assistant May See of This Flow")
        self.resize(760, 520)
        self._privacy = disc.Privacy.from_dict(graph.ai_privacy)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.level = QComboBox()
        self.level.addItem(_NO_CAP, None)
        for index in range(disc.BUILT_MAX + 1):
            self.level.addItem(LEVELS[index][1], index)
        if self._privacy.level is not None and self._privacy.level > disc.BUILT_MAX:
            self.level.addItem(LEVELS[self._privacy.level][1] + " (not built yet "
                               "— works as Profile)", self._privacy.level)
        self.level.setCurrentIndex(max(0, self.level.findData(self._privacy.level)))
        form.addRow("This flow allows at most:", self.level)
        layout.addLayout(form)
        note = QLabel(
            "Saved in the flow, so whoever you send it to gets the same "
            "limit — their connection can lower it, not raise it. It is a "
            "setting, not a lock: anyone who edits the flow can change it.")
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
        self._sensitive: list[QCheckBox] = []
        for row, (name, where) in enumerate(sorted(
                columns.items(), key=lambda kv: kv[0].lower())):
            rule = self._privacy.columns.get(name) or disc.ColumnRule()
            self._names.append(name)
            for col, text in ((0, name), (1, ", ".join(where) or "(not run now)")):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, col, item)
            box = QCheckBox()
            box.setChecked(rule.sensitive)
            box.setToolTip("Send this column's name and type only — no "
                           "ranges, counts of distinct values or guesses at "
                           "what it holds")
            holder = QWidget()
            centre = QHBoxLayout(holder)
            centre.setContentsMargins(0, 0, 0, 0)
            centre.setAlignment(Qt.AlignCenter)
            centre.addWidget(box)
            self.table.setCellWidget(row, 2, holder)
            self._sensitive.append(box)
            self.table.setItem(row, 3, QTableWidgetItem(rule.alias))
            self.table.setItem(row, 4, QTableWidgetItem(rule.hint))
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

    def alias_problem(self) -> str:
        """Why the aliases can't be used as typed, or "". Each must be
        unique and must not be another column's real name, or the AI's
        answer would be turned back into the wrong column."""
        seen: dict[str, str] = {}
        real = set(self._names)
        for row, name in enumerate(self._names):
            alias = (self.table.item(row, 3).text() or "").strip()
            if not alias or alias == name:
                continue
            if alias in real:
                return (f"'{name}' is shown as '{alias}', which is the real "
                        "name of another column.")
            if alias in seen:
                return (f"'{seen[alias]}' and '{name}' are both shown as "
                        f"'{alias}'.")
            seen[alias] = name
        return ""

    def accept(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        problem = self.alias_problem()
        if problem:
            QMessageBox.warning(self, "Aliases", problem
                                + " Give each column a name of its own.")
            return
        super().accept()

    def privacy(self) -> dict:
        """What the dialog says now, in the flow's saved shape."""
        columns = {}
        for row, name in enumerate(self._names):
            alias = (self.table.item(row, 3).text() or "").strip()
            hint = (self.table.item(row, 4).text() or "").strip()
            columns[name] = disc.ColumnRule(
                sensitive=self._sensitive[row].isChecked(), alias=alias, hint=hint)
        return disc.Privacy(self.level.currentData(), columns).to_dict()
