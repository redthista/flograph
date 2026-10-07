"""Pop-out spreadsheet editor for the Table node.

Edits a copy of the sheet with its own local undo stack (Ctrl+Z inside
the dialog reverts one edit at a time); OK/Apply hands the result back to
the caller, which commits it to the graph as a single undo step on the
canvas. The dialog knows nothing about graphs or commands, so it stays
testable headless.

The ribbon and formula bar themselves live in ``ribbon.py`` and
``tools.py``, shared with the dashboard tile — a formula has to behave the
same wherever it is typed.

Given the node's SheetHost, the ribbon's Submit cluster works here too:
Submit applies what is in the window and then submits it, so a table held
until Submit can be finished and sent on without closing the editor.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QByteArray, QSettings, Qt, QTimer
from PySide6.QtGui import QKeySequence, QUndoCommand, QUndoStack
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout

from .. import theme
from .model import SheetModel
from .binding import SheetHost
from .tools import FormulaBar
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


class _DialogHost(SheetHost):
    """The node's host, seen through the dialog: Undo is the window's own
    stack, and Submit / auto-apply first hand over what is in the window."""

    def __init__(self, dialog, inner: SheetHost) -> None:
        self._dialog, self._inner = dialog, inner

    def can_hold(self) -> bool:
        return self._inner.can_hold()

    def mode(self) -> str:
        return self._inner.mode()

    def pending_text(self) -> str:
        if self._inner.mode() != "submit":
            return ""
        if self._dialog.has_unapplied():
            return "Changes in this window not submitted"
        return self._inner.pending_text()

    def submit(self) -> None:
        self._dialog.apply_now()
        self._inner.submit()
        self._dialog.refresh_host()

    def discard(self) -> None:
        self._inner.discard()
        self._dialog.reload()

    def set_mode(self, mode: str) -> None:
        self._dialog.apply_now()
        self._inner.set_mode(mode)
        self._dialog.refresh_host()

    def undo_stack(self):
        return self._dialog.undo_stack

    def rules(self) -> str:
        return self._inner.rules()

    def can_format(self) -> bool:
        return self._inner.can_format()

    def set_rules(self, text: str) -> None:
        # rules are the node's, not the window's draft: they go straight
        # to the node (one undo step there) and repaint this grid too
        self._inner.set_rules(text)
        self._dialog.model.set_rules(self._inner.rules())


class SheetEditorDialog(QDialog):
    def __init__(self, sheet, title: str = "Edit Table", parent=None,
                 host: SheetHost = None, reload=None) -> None:
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
            f" border: 1px solid #3a3e47; padding: 2px 6px; }}"
            f"QTableCornerButton::section {{"
            f" background: {theme.NODE_HEADER.name()};"
            f" border: 1px solid #3a3e47; }}"
            f"QHeaderView {{ background: {theme.NODE_BODY.name()}; }}")
        self.undo_stack = QUndoStack(self)
        self._last_dict = self.model.sheet_dict()
        self._applied_dict = self._last_dict
        self._applying = False
        self._reload = reload
        self.on_apply: Optional[Callable[[dict], None]] = None
        self.view.set_host(_DialogHost(self, host or SheetHost()))
        self.model.set_rules(self.view.host.rules())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(0)
        # the same ribbon and formula bar a dashboard tile gets — see
        # spreadsheet/tools.py for why there is only one of each
        from .ribbon import SheetRibbon
        self._toolbar = self.ribbon = SheetRibbon(self.view, "auto", self)
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
        button_row = QVBoxLayout()
        button_row.setContentsMargins(8, 6, 8, 0)
        button_row.addWidget(buttons)
        layout.addLayout(button_row)

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
        self.view.actions.refresh()

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
        self.refresh_host()

    def _on_stack_moved(self, _index: int) -> None:
        self._last_dict = self.model.sheet_dict()
        self._sync_formula_bar(self.view.currentIndex())
        self.refresh_host()

    def _apply(self) -> None:
        self.apply_now()

    def apply_now(self) -> None:
        """Hand what is in the window to the caller (Apply, and the first
        half of Submit)."""
        self.view.commit_open_editor()
        if self.on_apply is not None:
            self.on_apply(self.sheet_dict())
        self._applied_dict = self.sheet_dict()
        self.refresh_host()

    def has_unapplied(self) -> bool:
        return self.sheet_dict() != self._applied_dict

    def reload(self) -> None:
        """After Discard: show the table the flow is using again."""
        if self._reload is not None:
            self.model.set_sheet(self._reload())
            self._last_dict = self._applied_dict = self.sheet_dict()
            self.undo_stack.clear()
        self.refresh_host()

    def refresh_host(self) -> None:
        self.view.actions.refresh()

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
