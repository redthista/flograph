"""Go To… and Go To Special… — Excel's two Find & Select dialogs.

Go To takes a reference — B4, B2:D10, B:D, 3:5, 12 or a column's name —
or a column picked from the list, and selects it. Go To Special selects
every cell of one kind (formulas, typed values, blanks, errors, problem
cells, the current region, the last cell), formulas and values narrowed
by what they hold. Both say what they will do before they do it.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog,
                               QDialogButtonBox, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget,
                               QRadioButton, QVBoxLayout, QWidget)

from flograph.core.sheet import select as pick
from flograph.core.sheet.formula import cell_name

from .menus import real_window

_KIND_HELP = {
    "formulas": "Cells worked out by a formula.",
    "constants": "Cells with a value typed in, not a formula.",
    "blanks": "Empty cells. Type a value and press Ctrl+Enter to fill "
              "them all at once.",
    "errors": "Cells showing an error such as #DIV/0!, #REF! or #N/A.",
    "problems": "Cells shown red: a value the column's type, dropdown list "
                "or validation rule doesn't allow.",
    "region": "The block of data around the current cell, up to the "
              "first empty row and column on each side.",
    "last": "The last row and column that hold anything.",
}
_TYPE_LABELS = (("numbers", "Numbers"), ("text", "Text"),
                ("logicals", "TRUE / FALSE"), ("errors", "Errors"))


class GoToDialog(QDialog):
    def __init__(self, view, parent=None) -> None:
        super().__init__(parent)
        self._view = view
        model = self._model = view.sheet_model()
        self.setWindowTitle("Go To")
        layout = QVBoxLayout(self)
        intro = QLabel("Pick a column, or type where to go.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.columns = QListWidget()
        self.columns.addItems(model.sheet.column_names())
        self.columns.setMaximumHeight(160)
        layout.addWidget(self.columns)
        row = QHBoxLayout()
        row.addWidget(QLabel("Reference"))
        self.ref = QLineEdit()
        self.ref.setPlaceholderText("B4, B2:D10, B:D, 3:5, 12 or a column")
        current = view.currentIndex()
        if current.isValid():
            self.ref.setText(cell_name(current.row(), current.column()))
            self.ref.selectAll()
        row.addWidget(self.ref, 1)
        layout.addLayout(row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                        | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Go")
        special = self.buttons.addButton("Special…",
                                         QDialogButtonBox.ActionRole)
        special.setToolTip("Select every formula, blank, error … instead.")
        special.clicked.connect(self._special)
        self.buttons.accepted.connect(self._go)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.columns.currentTextChanged.connect(self.ref.setText)
        self.columns.itemDoubleClicked.connect(lambda _i: self._go())
        self.ref.textChanged.connect(self._refresh)
        self.ref.setFocus()
        self._wants_special = False
        self._refresh()
        self.resize(360, 0)

    def target(self):
        model = self._model
        return pick.parse_reference(self.ref.text(),
                                    model.sheet.column_names(),
                                    model.rowCount(), model.columnCount())

    def _refresh(self, *_args) -> None:
        found = self.target()
        ok = self.buttons.button(QDialogButtonBox.Ok)
        if isinstance(found, str):
            ok.setEnabled(False)
            self.status.setStyleSheet("color: #f87171;" if self.ref.text()
                                      .strip() else "color: #9ca3af;")
            self.status.setText(found)
            return
        ok.setEnabled(True)
        self.status.setStyleSheet("color: #9ca3af;")
        r0, c0, r1, c1 = found
        if (r0, c0) == (r1, c1):
            name = self._model.sheet.columns[c0].name
            self.status.setText(f"Goes to {name}, row {r0 + 1}.")
        else:
            self.status.setText(
                f"Selects {cell_name(r0, c0)}:{cell_name(r1, c1)} — "
                f"{r1 - r0 + 1} × {c1 - c0 + 1} cells.")

    def _go(self) -> None:
        if not isinstance(self.target(), str):
            self.accept()

    def _special(self) -> None:
        self._wants_special = True
        self.reject()


class GoToSpecialDialog(QDialog):
    def __init__(self, view, parent=None) -> None:
        super().__init__(parent)
        self._view = view
        self.setWindowTitle("Go To Special")
        layout = QVBoxLayout(self)
        scope = view._special_scope()
        self.scope = QLabel(
            f"Looks inside the {len(scope)} selected cells."
            if scope else "Looks at the whole table (select some cells "
            "first to look only there).")
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)

        grid = QGridLayout()
        self.kinds = QButtonGroup(self)
        self._kind_buttons = {}
        for i, (key, label) in enumerate(pick.KINDS):
            button = QRadioButton(label)
            button.setToolTip(_KIND_HELP[key])
            self.kinds.addButton(button, i)
            self._kind_buttons[key] = button
            grid.addWidget(button, i % 4, i // 4)
        layout.addLayout(grid)

        self.types_box = QWidget()
        types = QHBoxLayout(self.types_box)
        types.setContentsMargins(24, 0, 0, 0)
        self._type_boxes = {}
        for key, label in _TYPE_LABELS:
            box = QCheckBox(label)
            box.setChecked(True)
            self._type_boxes[key] = box
            types.addWidget(box)
            box.toggled.connect(self._refresh)
        types.addStretch(1)
        layout.addWidget(self.types_box)

        self.help = QLabel()
        self.help.setWordWrap(True)
        self.help.setStyleSheet("color: #9ca3af;")
        self.help.setMinimumHeight(self.help.fontMetrics().height() * 2 + 4)
        layout.addWidget(self.help)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                        | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Select")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._kind_buttons["blanks"].setChecked(True)
        self.kinds.idToggled.connect(self._refresh)
        self._refresh()
        self.resize(440, 0)

    def chosen(self) -> tuple[str, tuple[str, ...]]:
        kind = next(key for key, button in self._kind_buttons.items()
                    if button.isChecked())
        types = tuple(key for key, box in self._type_boxes.items()
                      if box.isChecked())
        return kind, types

    def _refresh(self, *_args) -> None:
        kind, types = self.chosen()
        narrowed = kind in ("formulas", "constants")
        self.types_box.setEnabled(narrowed)
        self.help.setText(_KIND_HELP[kind]
                          + (" Tick what they may hold." if narrowed else ""))
        ok = self.buttons.button(QDialogButtonBox.Ok)
        ok.setEnabled(not narrowed or bool(types))


def go_to(view) -> None:
    model = view.sheet_model()
    if model is None or model.columnCount() == 0:
        return
    dialog = GoToDialog(view, real_window(view))
    if dialog.exec():
        found = dialog.target()
        if not isinstance(found, str):
            view.select_rect(found)
    elif dialog._wants_special:
        go_to_special(view)


def go_to_special(view) -> None:
    model = view.sheet_model()
    if model is None or model.columnCount() == 0:
        return
    dialog = GoToSpecialDialog(view, real_window(view))
    if dialog.exec():
        kind, types = dialog.chosen()
        view.select_special(kind, types)
