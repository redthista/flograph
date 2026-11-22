"""Dropdown lists — Excel's data validation "List", for a Table column.

A column can carry a list of values (`ColumnSpec.choices`), typed in or
read from a column of a helper table wired into the node
(`ColumnSpec.choices_from`, core/sheet/choice_sources.py). Its current
cell then shows a ▾; click it (or press Alt+Down) and the list opens to
pick from. Typing still works as in any cell. A *strict* list turns
anything not on it red, like any other value that doesn't fit its column;
a loose one is only a suggestion.

The list opens as a menu window, not as a combo box inside the cell: on a
canvas card a combo's popup would be embedded in the scene (see
canvas/popup_lift.py), and an editor that closes as its own popup takes
focus loses the pick.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox,
                               QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QVBoxLayout)

from .menus import exec_menu, heading, new_menu, real_window
from flograph.ui import theme as _theme  # noqa: E402


def open_choice_list(view, index) -> None:
    model = view.sheet_model()
    if model is None or not index.isValid():
        return
    choices, strict = model.column_choices(index.column())
    if not choices:
        return
    current = model.cell_source(index.row(), index.column()).strip()
    menu = new_menu(view.viewport())
    heading(menu, model.sheet.columns[index.column()].name)
    for value in choices:
        action = menu.addAction(value)
        action.setCheckable(True)
        action.setChecked(value.casefold() == current.casefold())
        action.triggered.connect(
            lambda _=False, v=value: model.setData(index, v, Qt.EditRole))
    menu.addSeparator()
    clear = menu.addAction("(blank)")
    clear.setToolTip("Empty the cell.")
    clear.triggered.connect(
        lambda: model.setData(index, "", Qt.EditRole))
    rect = view.visualRect(index)
    exec_menu(menu, view.viewport(), QPoint(rect.left(), rect.bottom() + 1))


class DropdownListDialog(QDialog):
    """Edit one column's list: one value per line, or read from a column
    of a helper table wired into the node (core/sheet/choice_sources.py).
    """

    def __init__(self, view, col: int, parent=None) -> None:
        super().__init__(parent)
        model = view.sheet_model()
        name = model.sheet.columns[col].name
        choices, strict = model.column_choices(col)
        source = model.column_choice_source(col)
        # the host's answer is the live one; the grid's copy can be stale
        # (the full editor took it when it opened)
        self._host = view.host
        self._frames, helpers = self._host.helper_state()
        self._helpers = helpers or model.helper_tables()
        self.setWindowTitle(f"Dropdown List — {name}")
        self._view, self._col = view, col
        self._typed = "\n".join(choices) if source is None else ""
        self._source_choices = (choices, source)

        layout = QVBoxLayout(self)
        intro = QLabel(
            f"The values a cell in <b>{name}</b> can be picked from. The "
            "current cell of the column shows a ▾ to open the list "
            "(Alt+Down from the keyboard); typing still works as usual.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # where the list comes from: typed here, or a helper table's column
        self.from_box = QComboBox()
        self.from_box.addItem("Typed below", None)
        for helper in self._helpers:
            self.from_box.addItem(
                f"{helper['label']} ({helper['input']})", helper["input"])
        self.from_box.setToolTip(
            "A helper table is any table wired into the empty \"helper\" "
            "port at the bottom of the Table node. Its column's values "
            "become the list and follow it as it changes.")
        self.column_box = QComboBox()
        self.column_box.setToolTip("The helper's column to list.")
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Values from"))
        source_row.addWidget(self.from_box, 1)
        source_row.addWidget(self.column_box, 1)
        layout.addLayout(source_row)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        _theme.set_qss(self.hint, "color: #9aa0ab;")
        self.run_button = QPushButton("Run Helpers")
        self.run_button.setToolTip(
            "Run the helper tables wired into this Table — only those, not "
            "the table itself — and read their columns again.")
        self.run_button.clicked.connect(self._run_helpers)
        hint_row = QHBoxLayout()
        hint_row.addWidget(self.hint, 1)
        hint_row.addWidget(self.run_button, 0, Qt.AlignTop)
        layout.addLayout(hint_row)
        self._poll = QTimer(self)
        self._poll.setInterval(200)
        self._poll.timeout.connect(self._check_run)

        self.edit = QPlainTextEdit("\n".join(choices))
        self.edit.setPlaceholderText("Open\nIn progress\nDone")
        layout.addWidget(self.edit, 1)

        self.fill = QPushButton("Fill From Column")
        self.fill.setToolTip("Put every distinct value already in this "
                             "column into the list, in the order they first "
                             "appear.")
        self.fill.clicked.connect(self._fill_from_column)
        row = QHBoxLayout()
        row.addWidget(self.fill)
        row.addStretch(1)
        layout.addLayout(row)

        self.strict = QCheckBox("Only allow values on the list")
        self.strict.setToolTip(
            "Anything else turns red and its tooltip says why — as a number "
            "in a number column would. Off, the list is a suggestion.")
        self.strict.setChecked(strict)
        layout.addWidget(self.strict)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        remove = buttons.addButton("Remove List",
                                   QDialogButtonBox.DestructiveRole)
        remove.setToolTip("Take the list off this column. Its values stay.")
        remove.clicked.connect(self._remove)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(420, 400)

        if source is not None:
            at = self.from_box.findData(source.get("input"))
            if at < 0:
                # the port it named is gone: list it anyway, so OK keeps
                # the source rather than silently dropping it
                self.from_box.addItem(
                    f"{source.get('input') or '?'} (not wired)",
                    source.get("input"))
                at = self.from_box.count() - 1
            self.from_box.setCurrentIndex(at)
        # read-only means "showing a helper's values": _show_mode keeps the
        # typed text only when leaving an editable box
        self.edit.setReadOnly(source is not None)
        self._fill_columns(source.get("column") if source else None)
        self.from_box.currentIndexChanged.connect(
            lambda _i: self._fill_columns(None))
        self.column_box.currentIndexChanged.connect(
            lambda _i: self._show_mode())

    # ------------------------------------------------------------- source

    def _helper(self, port) -> dict:
        return next((h for h in self._helpers if h["input"] == port), {})

    def _fill_columns(self, keep) -> None:
        port = self.from_box.currentData()
        self.column_box.blockSignals(True)
        self.column_box.clear()
        if port is not None:
            columns = list(self._helper(port).get("columns") or [])
            if keep and keep not in columns:
                columns.append(keep)
            self.column_box.addItems(columns)
            if keep:
                self.column_box.setCurrentText(keep)
        self.column_box.blockSignals(False)
        self._show_mode()

    def source(self):
        """The chosen helper source, or None for a typed list."""
        port = self.from_box.currentData()
        column = self.column_box.currentText().strip()
        if port is None or not column:
            return None
        return {"input": port, "column": column}

    def _show_mode(self) -> None:
        source = self.source()
        typed = self.from_box.currentData() is None
        if not typed and self.edit.isReadOnly() is False:
            self._typed = self.edit.toPlainText()
        self.column_box.setVisible(not typed)
        self.edit.setReadOnly(not typed)
        self.fill.setEnabled(typed)
        self.run_button.setVisible(not typed and self._host.can_run_helpers())
        if typed:
            self.edit.setPlainText(self._typed)
            self.hint.setText(
                "One value per line." if self._helpers else
                "One value per line. To read the list from another table, "
                "wire that table into the empty \"helper\" port at the "
                "bottom of this Table node.")
            return
        if self._poll.isActive():
            return
        from flograph.core.sheet.choice_sources import (distinct_values,
                                                        find_column)
        found = (find_column(self._frames, source)
                 if source is not None else None)
        if found is not None:
            self.edit.setPlainText("\n".join(distinct_values(*found)))
            self.hint.setText("Read from the helper table — it follows the "
                              "helper as it changes.")
            return
        shown, was = self._source_choices
        if source is not None and source == was:
            self.edit.setPlainText("\n".join(shown))
            self.hint.setText("The values this list last read. Run the "
                              "helpers to read them again.")
        elif not self._helper(self.from_box.currentData()).get("columns"):
            self.edit.setPlainText("")
            self.hint.setText("This helper hasn't run yet, so its columns "
                              "aren't known. Run it to pick one.")
        else:
            self.edit.setPlainText("")
            self.hint.setText("The list fills once the helper has run.")

    # --------------------------------------------------------- run helpers

    def _run_helpers(self) -> None:
        if not self._host.run_helpers():
            return
        self.run_button.setEnabled(False)
        self.hint.setText("Running the helper tables…")
        self._poll.start()

    def _check_run(self) -> None:
        """Poll until the helper nodes have left the queue, then read their
        tables again. Polled rather than signalled: the grid's host has no
        handle on the engine, only on the graph's node statuses."""
        if self._host.helpers_busy():
            return
        self._poll.stop()
        self.run_button.setEnabled(True)
        keep = self.column_box.currentText().strip() or None
        port = self.from_box.currentData()
        self._frames, helpers = self._host.helper_state()
        if helpers:
            self._helpers = helpers
        self._fill_columns(keep)
        if port is not None and port not in self._frames:
            self.hint.setText("The helper didn't produce a table — see the "
                              "Log for what went wrong.")

    def values(self) -> list[str]:
        seen, out = set(), []
        for line in self.edit.toPlainText().splitlines():
            value = line.strip()
            if value and value.casefold() not in seen:
                seen.add(value.casefold())
                out.append(value)
        return out

    def _fill_from_column(self) -> None:
        model = self._view.sheet_model()
        existing = self.values()
        seen = {v.casefold() for v in existing}
        for row in range(model.rowCount()):
            value = model.value_text(row, self._col).strip()
            if value and value.casefold() not in seen:
                seen.add(value.casefold())
                existing.append(value)
        self.edit.setPlainText("\n".join(existing))

    def _remove(self) -> None:
        self.from_box.setCurrentIndex(0)
        self._typed = ""
        self.edit.setPlainText("")
        self.strict.setChecked(False)
        self.accept()


def edit_dropdown_list(view, col: int) -> None:
    model = view.sheet_model()
    if model is None or model.read_only or not 0 <= col < model.columnCount():
        return
    dialog = DropdownListDialog(view, col, real_window(view))
    if dialog.exec():
        model.set_column_choices(col, dialog.values(),
                                 dialog.strict.isChecked(), dialog.source())
