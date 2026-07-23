"""Cell editors for the spreadsheet: a line edit that round-trips raw
sources (so formulas edit as "=A1*2", not their computed value), plus a
calendar-popup date editor for date columns whose cells hold dates."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QDateEdit, QLineEdit, QStyledItemDelegate

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y")


def _parse_date(text: str):
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


class SheetDelegate(QStyledItemDelegate):
    """Line edit everywhere; date columns get a QDateEdit when the cell is
    empty or already holds a date (formulas keep the line edit)."""

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
