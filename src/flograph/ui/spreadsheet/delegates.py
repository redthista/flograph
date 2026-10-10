"""Cell editors for the spreadsheet: a line edit that round-trips raw
sources (so formulas edit as "=A1*2", not their computed value), plus a
calendar-popup date editor for date columns whose cells hold dates.

The delegate also paints two things a cell's value does not: a ▾ on the
current cell of a column with a dropdown list (click it, or Alt+Down, for
the list — see dropdown.py), and, with Show Formulas on, a cell's formula
in place of its result."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, QEvent, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPolygon
from PySide6.QtWidgets import (QAbstractItemDelegate, QDateEdit, QFrame,
                               QLineEdit, QPlainTextEdit)

from ..table_delegate import NOTE_ROLE, ConditionalFormatDelegate

CARET_W = 14

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y")


def _parse_date(text: str):
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def caret_rect(cell: QRect) -> QRect:
    """Where a dropdown cell's ▾ sits inside the cell."""
    return QRect(cell.right() - CARET_W + 1, cell.top(), CARET_W,
                 cell.height())


class CellEdit(QPlainTextEdit):
    """The cell editor: several lines when asked (Alt+Enter), else one.

    A QPlainTextEdit, so a cell can hold a line break, wearing the slice of
    QLineEdit's API the grid's formula completer, Insert Function and the
    retry after a refused value use — text(), setText(), cursorPosition(),
    setCursorPosition(), insert() and a textEdited signal that only fires
    for typing. It grows downwards over the cells below as lines are added,
    the way Excel's editor does."""

    textEdited = Signal(str)

    def __init__(self, parent=None, wrap: bool = False) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth if wrap
                             else QPlainTextEdit.NoWrap)
        self.setTabChangesFocus(True)
        self.document().setDocumentMargin(2)
        self.min_height = 0
        self._quiet = False
        # set by the delegate: the grid and row this editor is in, so a line
        # added with Alt+Enter grows the row itself — outline and all —
        # rather than the editor spilling over the cells below
        self.grid = None
        self.row = -1
        self.textChanged.connect(self._changed)

    def _changed(self) -> None:
        if not self._quiet:
            self.textEdited.emit(self.toPlainText())
        self.grow()

    def needed_height(self) -> int:
        lines = max(1, int(self.document().size().height()))
        return (lines * QFontMetrics(self.font()).lineSpacing()
                + 2 * int(self.document().documentMargin()) + 2)

    def grow(self) -> None:
        """As tall as its lines: the row grows to hold them (the grid
        then gives the editor the taller cell), or, outside a grid, the
        editor grows by itself."""
        need = self.needed_height()
        grid = self.grid
        if grid is not None and self.row >= 0 and hasattr(
                grid, "editing_row_needs"):
            grid.editing_row_needs(self.row, need)
        height = max(self.min_height, need)
        if height != self.height():
            self.resize(self.width(), height)

    # -- the QLineEdit slice
    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str) -> None:
        self._quiet = True
        try:
            self.setPlainText(text)
        finally:
            self._quiet = False
        self.moveCursor(self.textCursor().MoveOperation.End)

    def cursorPosition(self) -> int:
        return self.textCursor().position()

    def setCursorPosition(self, pos: int) -> None:
        cursor = self.textCursor()
        cursor.setPosition(max(0, min(pos, len(self.toPlainText()))))
        self.setTextCursor(cursor)

    def insert(self, text: str) -> None:
        self.insertPlainText(text)

    def setFrame(self, _on: bool) -> None:
        pass


class SheetDelegate(ConditionalFormatDelegate):
    """Line edit everywhere; date columns get a QDateEdit when the cell is
    empty or already holds a date (formulas keep the line edit).

    Built on Show Table's ConditionalFormatDelegate, so the data bars,
    icons and pills a conditional-formatting rule asks for are painted the
    same way in both — and a cell without any is a plain cell."""

    show_formulas = False
    last_editor = None   # the editor most recently opened, for start_formula
    ctrl_enter = False   # the editor was closed with Ctrl+Enter (fill all)

    def eventFilter(self, editor, event):
        if event.type() == QEvent.KeyPress and event.key() in (
                Qt.Key_Return, Qt.Key_Enter):
            if isinstance(editor, CellEdit):
                if event.modifiers() & Qt.AltModifier:
                    editor.insertPlainText("\n")   # Alt+Enter: a new line
                    return True
                # Enter commits, as in a one-line editor (Qt leaves Enter
                # to a QPlainTextEdit, which would start a new line)
                self.ctrl_enter = bool(event.modifiers() & Qt.ControlModifier)
                self.commitData.emit(editor)
                self.closeEditor.emit(editor,
                                      QAbstractItemDelegate.SubmitModelCache)
                return True
            self.ctrl_enter = bool(event.modifiers() & Qt.ControlModifier)
        return super().eventFilter(editor, event)

    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        wraps = getattr(index.model(), "wraps", None)
        if wraps is not None and wraps(index.row(), index.column()):
            # Wrap Text: long text runs onto more lines, from the top
            from PySide6.QtWidgets import QStyleOptionViewItem
            option.features |= QStyleOptionViewItem.WrapText
            option.displayAlignment = (
                option.displayAlignment & Qt.AlignHorizontal_Mask) \
                | Qt.AlignTop
        if self.show_formulas:
            source = str(index.data(Qt.EditRole) or "")
            if source.startswith("=") and source != "=":
                option.text = source
                option.displayAlignment = Qt.AlignLeft | Qt.AlignVCenter

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        if index.data(NOTE_ROLE):
            # Excel's note mark: a small red corner, top right
            r = option.rect
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#ef4444"))
            painter.drawPolygon(QPolygon([
                QPoint(r.right() - 6, r.top()), QPoint(r.right() + 1, r.top()),
                QPoint(r.right() + 1, r.top() + 7)]))
            painter.restore()
        model = index.model()
        choices = getattr(model, "column_choices", None)
        view = self.parent()
        if choices is None or not choices(index.column())[0]:
            return
        if view is None or view.currentIndex() != index:
            return
        rect = caret_rect(option.rect)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(75, 79, 92, 200))
        painter.drawRoundedRect(rect.adjusted(1, 2, -1, -2), 2, 2)
        painter.setBrush(QColor("#d6d8de"))
        cx, cy = rect.center().x(), rect.center().y()
        painter.drawPolygon(QPolygon([QPoint(cx - 3, cy - 1),
                                      QPoint(cx + 3, cy - 1),
                                      QPoint(cx, cy + 2)]))
        painter.restore()

    def createEditor(self, parent, option, index):
        model = index.model()
        col_type = getattr(model, "column_type", lambda _c: "auto")(
            index.column())
        source = str(index.data(Qt.EditRole) or "")
        if col_type == "date" and not source.startswith("="):
            parsed = _parse_date(source.strip()) if source.strip() else None
            if parsed is not None or not source.strip():
                editor = QDateEdit(parent)
                editor.setCalendarPopup(True)
                editor.setDisplayFormat("yyyy-MM-dd")
                return editor
        wraps = getattr(model, "wraps", None)
        editor = CellEdit(parent, wrap=bool(
            wraps and wraps(index.row(), index.column())))
        view = self.parent()
        editor.grid = getattr(view, "_main", view)    # a pane edits for it
        editor.row = index.row()
        if hasattr(model, "sheet"):
            from .completion import FormulaCompleter
            FormulaCompleter(editor, lambda m=model: m.sheet.column_names())
        SheetDelegate.last_editor = editor
        return editor

    def updateEditorGeometry(self, editor, option, index) -> None:
        super().updateEditorGeometry(editor, option, index)
        if isinstance(editor, CellEdit):
            editor.min_height = option.rect.height()
            editor.grow()

    def setEditorData(self, editor, index):
        if isinstance(editor, CellEdit):
            editor.setText(str(index.data(Qt.EditRole) or ""))
            # as Qt does for a line edit: a key typed to start editing
            # replaces the value, F2 then an arrow key moves within it
            editor.selectAll()
            return
        if isinstance(editor, QDateEdit):
            source = str(index.data(Qt.EditRole) or "").strip()
            parsed = _parse_date(source) if source else None
            editor.setDate(QDate(parsed.year, parsed.month, parsed.day)
                           if parsed else QDate.currentDate())
            return
        super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, CellEdit):
            model.setData(index, editor.text(), Qt.EditRole)
            return
        if isinstance(editor, QDateEdit):
            model.setData(index, editor.date().toString("yyyy-MM-dd"),
                          Qt.EditRole)
            return
        super().setModelData(editor, model, index)
