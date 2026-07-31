"""Pop-out spreadsheet editor for the Table node.

Edits a copy of the sheet with its own local undo stack (Ctrl+Z inside
the dialog reverts one edit at a time); OK/Apply hands the result back to
the caller, which commits it to the graph as a single undo step on the
canvas. The dialog knows nothing about graphs or commands, so it stays
testable headless.

The toolbar and formula bar themselves live in ``tools.py``, shared with
the dashboard tile — a formula has to behave the same wherever it is typed.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QByteArray, QSettings, Qt, QTimer
from PySide6.QtGui import QKeySequence, QUndoCommand, QUndoStack
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout

from .. import theme
from .model import SheetModel
from .tools import FormulaBar, SheetToolbar
from .view import SpreadsheetView

_ORG = "flograph"
_APP = "flograph"
_GEOMETRY_KEY = "sheet_editor/geometry"


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
        # lighter gridlines and brighter header text than a card: this is a
        # window of its own, not a thumbnail on a canvas
        theme.style_scroll_area(
            self.view,
            f"QTableView {{ background: {theme.NODE_BODY.name()};"
            f" color: {theme.NODE_TEXT.name()}; border: none;"
            f" gridline-color: #3a3e47; }}"
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
        # the same toolbar and formula bar a dashboard tile gets — see
        # spreadsheet/tools.py for why there is only one of each
        self._toolbar = SheetToolbar(self.view, self)
        self._formula_bar = FormulaBar(self.view, self)
        layout.addWidget(self._toolbar)
        layout.addWidget(self._formula_bar)
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

    def _sync_formula_bar(self, current=None, _previous=None) -> None:
        self._formula_bar.sync(current)

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
