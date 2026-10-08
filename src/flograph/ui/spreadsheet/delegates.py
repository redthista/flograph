"""Cell editors for the spreadsheet: a line edit that round-trips raw
sources (so formulas edit as "=A1*2", not their computed value), plus a
calendar-popup date editor for date columns whose cells hold dates.

The delegate also paints two things a cell's value does not: a ▾ on the
current cell of a column with a dropdown list (click it, or Alt+Down, for
the list — see dropdown.py), and, with Show Formulas on, a cell's formula
in place of its result."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPolygon
from PySide6.QtWidgets import QDateEdit, QLineEdit

from ..table_delegate import ConditionalFormatDelegate

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
            self.ctrl_enter = bool(event.modifiers() & Qt.ControlModifier)
        return super().eventFilter(editor, event)

    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        if self.show_formulas:
            source = str(index.data(Qt.EditRole) or "")
            if source.startswith("=") and source != "=":
                option.text = source
                option.displayAlignment = Qt.AlignLeft | Qt.AlignVCenter

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
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
        editor = QLineEdit(parent)
        editor.setFrame(False)
        if hasattr(model, "sheet"):
            from .completion import FormulaCompleter
            FormulaCompleter(editor, lambda m=model: m.sheet.column_names())
        SheetDelegate.last_editor = editor
        return editor

    def setEditorData(self, editor, index):
        if isinstance(editor, QDateEdit):
            source = str(index.data(Qt.EditRole) or "").strip()
            parsed = _parse_date(source) if source else None
            editor.setDate(QDate(parsed.year, parsed.month, parsed.day)
                           if parsed else QDate.currentDate())
            return
        super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QDateEdit):
            model.setData(index, editor.date().toString("yyyy-MM-dd"),
                          Qt.EditRole)
            return
        super().setModelData(editor, model, index)
