"""Pop-out spreadsheet editor for the Table node.

Edits a copy of the sheet with its own local undo stack (Ctrl+Z inside
the dialog reverts one edit at a time); OK/Apply hands the result back to
the caller, which commits it to the graph as a single undo step on the
canvas. The dialog knows nothing about graphs or commands, so it stays
testable headless.
"""
from __future__ import annotations

from typing import Callable, Optional

import html

from PySide6.QtCore import QByteArray, QSettings, Qt, QTimer
from PySide6.QtGui import QKeySequence, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QLineEdit, QTextBrowser, QToolBar,
                               QToolButton, QVBoxLayout)

from flograph.core.sheet import FUNCTION_HELP, cell_name

from .. import theme
from .model import SheetModel
from .view import SpreadsheetView

_ORG = "flograph"
_APP = "flograph"
_GEOMETRY_KEY = "sheet_editor/geometry"


def _reference_html() -> str:
    """The fx button's help page: references, operators, and the function
    table generated from core's FUNCTION_HELP."""
    rows = "".join(
        f"<tr><td><b>{html.escape(signature)}</b></td>"
        f"<td>{html.escape(description)}</td>"
        f"<td><code>{html.escape(example)}</code></td></tr>"
        for _name, signature, description, example in FUNCTION_HELP)
    return f"""
<h3>Formulas</h3>
<p>Start a cell with <code>=</code> to enter a formula. Reference cells
by column letter and row number (<code>A1</code>, <code>B3</code>); row 1
is the first data row. Pin a reference with <code>$</code>
(<code>$A$1</code>) so paste and fill-down don't shift it, and use
<code>A1:B5</code> ranges inside functions.</p>
<p><b>Reference columns by name</b> with <code>[@Price]</code> — this
row's value in the "Price" column — or <code>[Price]</code> for the whole
column inside aggregates: <code>=[@Price]*[@Qty]</code>,
<code>=SUM([Total])</code>. Names may contain spaces
(<code>[@value x]</code>) and match case-insensitively. Named references
don't shift on paste or fill-down, follow the column when you rename it,
and keep working when columns move — prefer them over letters whenever a
column has a meaningful name.</p>
<p><b>Operators:</b> <code>+ &nbsp;- &nbsp;* &nbsp;/ &nbsp;^</code> (power),
<code>&amp;</code> (join text), <code>%</code> (percent, <code>50%</code> is 0.5),
and comparisons <code>= &nbsp;&lt;&gt; &nbsp;&lt; &nbsp;&lt;= &nbsp;&gt; &nbsp;&gt;=</code>.</p>
<p>Errors show in the cell (<code>#DIV/0!</code>, <code>#REF!</code>,
<code>#CYCLE!</code>, …) — hover for the reason.</p>
<h3>Functions</h3>
<table cellspacing="0" cellpadding="4" border="0">
<tr><th align="left">Function</th><th align="left">What it does</th>
<th align="left">Example</th></tr>
{rows}
</table>
"""


class _SheetEditCommand(QUndoCommand):
    """Snapshot undo: sheets are small, so before/after dicts are the
    simplest correct representation of any edit (cell or structural)."""

    def __init__(self, model: SheetModel, before: dict, after: dict) -> None:
        super().__init__("edit table")
        self._model = model
        self._before = before
        self._after = after
        self._first_redo = True   # the edit itself already happened

    def redo(self) -> None:
        if self._first_redo:
            self._first_redo = False
            return
        self._model.set_sheet(self._after)

    def undo(self) -> None:
        self._model.set_sheet(self._before)


class SheetEditorDialog(QDialog):
    def __init__(self, sheet, title: str = "Edit Table", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)

        self.model = SheetModel(sheet, self)
        self.view = SpreadsheetView(self)
        self.view.setModel(self.model)
        # Qt's default gridlines all but vanish on the dark palette
        self.view.setShowGrid(True)
        self.view.setStyleSheet(
            "QTableView { gridline-color: #3a3e47; }"
            f"QHeaderView::section {{ background: {theme.NODE_HEADER.name()};"
            f" color: {theme.NODE_TEXT.name()};"
            f" border: 1px solid #3a3e47; padding: 2px 6px; }}")
        self.undo_stack = QUndoStack(self)
        self._last_dict = self.model.sheet_dict()
        self._applying = False
        self.on_apply: Optional[Callable[[dict], None]] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(self._build_toolbar())
        layout.addLayout(self._build_formula_bar())
        layout.addWidget(self.view, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel
                                   | QDialogButtonBox.Apply)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._apply)
        # no default button: Enter belongs to the grid (commit + move down)
        # and the formula bar — Qt's delegate lets Return propagate after a
        # cell commit, which would otherwise "click" OK and close the dialog
        self._buttons = buttons
        self._strip_default_buttons()
        layout.addWidget(buttons)

        self.model.sheet_edited.connect(self._record_edit)
        # undo/redo replace the sheet without emitting sheet_edited — keep
        # the before-snapshot and the formula bar in step with the stack
        self.undo_stack.indexChanged.connect(self._on_stack_moved)
        selection = self.view.selectionModel()
        if selection is not None:
            selection.currentChanged.connect(self._sync_formula_bar)

        undo_action = self.undo_stack.createUndoAction(self)
        undo_action.setShortcut(QKeySequence.Undo)
        redo_action = self.undo_stack.createRedoAction(self)
        redo_action.setShortcut(QKeySequence.Redo)
        self.addAction(undo_action)
        self.addAction(redo_action)
        self._toolbar.insertAction(self._toolbar.actions()[0], redo_action)
        self._toolbar.insertAction(redo_action, undo_action)

        self.resize(900, 600)
        stored = QSettings(_ORG, _APP).value(_GEOMETRY_KEY)
        if isinstance(stored, QByteArray):
            self.restoreGeometry(stored)
        self._sync_formula_bar(self.view.currentIndex())

    # ------------------------------------------------------------- layout

    def _build_toolbar(self) -> QToolBar:
        toolbar = QToolBar(self)
        toolbar.setMovable(False)
        view, model = self.view, self.model

        def current_row() -> int:
            index = view.currentIndex()
            return index.row() if index.isValid() else 0

        def current_col() -> int:
            index = view.currentIndex()
            return index.column() if index.isValid() else 0

        toolbar.addSeparator()
        toolbar.addAction("+ Row above",
                          lambda: model.insert_rows_at(current_row()))
        toolbar.addAction("+ Row below",
                          lambda: model.insert_rows_at(current_row() + 1))
        toolbar.addAction("+ Column",
                          lambda: model.insert_columns_at(current_col() + 1))
        toolbar.addSeparator()
        toolbar.addAction("Fill down", view.fill_down_selection)
        toolbar.addAction("Fit columns", lambda: view.autosize_columns())
        toolbar.addAction("Sort ↑", lambda: model.sort_by(current_col(), True))
        toolbar.addAction("Sort ↓", lambda: model.sort_by(current_col(), False))
        self._toolbar = toolbar
        return toolbar

    def _build_formula_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        self._cell_label = QLabel("A1")
        self._cell_label.setMinimumWidth(40)
        self._cell_label.setAlignment(Qt.AlignCenter)
        self._formula_edit = QLineEdit()
        self._formula_edit.setPlaceholderText(
            "value or =formula — click fx for the function list")
        self._formula_edit.editingFinished.connect(self._commit_formula_bar)
        from .completion import FormulaCompleter
        FormulaCompleter(self._formula_edit,
                         lambda: self.model.sheet.column_names())
        fx_button = QToolButton(text="fx")
        fx_button.setAutoRaise(True)
        fx_button.setToolTip("Show available formulas and examples")
        fx_button.clicked.connect(self._show_formula_reference)
        self._reference_dialog: Optional[QDialog] = None
        row.addWidget(fx_button)
        row.addWidget(self._cell_label)
        row.addWidget(self._formula_edit, 1)
        return row

    def _show_formula_reference(self) -> None:
        if self._reference_dialog is None:
            dialog = QDialog(self)
            dialog.setWindowTitle("Formula reference")
            dialog.setModal(False)   # keep it open beside the editor
            dialog.resize(560, 520)
            layout = QVBoxLayout(dialog)
            browser = QTextBrowser()
            browser.setOpenExternalLinks(False)
            browser.setHtml(_reference_html())
            layout.addWidget(browser)
            self._reference_dialog = dialog
        self._reference_dialog.show()
        self._reference_dialog.raise_()
        self._reference_dialog.activateWindow()

    # ------------------------------------------------------- formula bar

    def _sync_formula_bar(self, current, _previous=None) -> None:
        if current is None or not current.isValid():
            self._cell_label.setText("")
            self._formula_edit.clear()
            return
        self._cell_label.setText(cell_name(current.row(), current.column()))
        self._formula_edit.setText(
            self.model.cell_source(current.row(), current.column()))

    def _commit_formula_bar(self) -> None:
        current = self.view.currentIndex()
        if not current.isValid():
            return
        text = self._formula_edit.text()
        if text != self.model.cell_source(current.row(), current.column()):
            self.model.setData(current, text, Qt.EditRole)
        self.view.setFocus()

    # ----------------------------------------------------------- undo/OK

    def _record_edit(self, after: dict) -> None:
        before, self._last_dict = self._last_dict, after
        self.undo_stack.push(_SheetEditCommand(self.model, before, after))

    def _on_stack_moved(self, _index: int) -> None:
        self._last_dict = self.model.sheet_dict()
        self._sync_formula_bar(self.view.currentIndex())

    def _apply(self) -> None:
        if self.on_apply is not None:
            self.on_apply(self.sheet_dict())

    def sheet_dict(self) -> dict:
        return self.model.sheet_dict()

    def _strip_default_buttons(self) -> None:
        for button in self._buttons.buttons():
            button.setAutoDefault(False)
            button.setDefault(False)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # QDialogButtonBox re-promotes OK to default on its own Show event,
        # undoing the constructor's strip — clear again once shown
        QTimer.singleShot(0, self._strip_default_buttons)

    def keyPressEvent(self, event) -> None:
        # a stray Enter that nothing consumed must never close the dialog
        # (QDialog would click the default button); OK/Cancel are click-only,
        # Escape still cancels via QDialog's separate reject path
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    def done(self, result: int) -> None:
        QSettings(_ORG, _APP).setValue(_GEOMETRY_KEY, self.saveGeometry())
        super().done(result)
