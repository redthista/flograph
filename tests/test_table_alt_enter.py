"""Alt+Enter: a line break inside a cell, as in Excel — in the cell editor
and the formula bar — and the cell wraps so both lines show."""
import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from flograph.ui.spreadsheet import SheetModel, SheetWorkbench, SpreadsheetView
from flograph.ui.spreadsheet.delegates import CellEdit

DATA = {"version": 2,
        "columns": [{"name": "Item", "width": 120}, {"name": "Note",
                                                     "width": 120}],
        "rows": [["Pen", ""], ["Pad", ""], ["Ink", ""]]}


@pytest.fixture
def view(qtbot):
    model = SheetModel(json.dumps(DATA))
    view = SpreadsheetView()
    model.setParent(view)
    view.setModel(model)
    qtbot.addWidget(view)
    view.resize(400, 300)
    view.show()
    qtbot.waitExposed(view)
    return view


def _open(view, qtbot, row, col):
    index = view.model().index(row, col)
    view.setCurrentIndex(index)
    view.edit(index)
    qtbot.wait(20)
    editor = view.indexWidget(index)
    assert isinstance(editor, CellEdit)
    return editor


class TestCellEditor:
    def test_alt_enter_breaks_the_line_enter_commits(self, view, qtbot):
        model = view.model()
        editor = _open(view, qtbot, 0, 1)
        QTest.keyClicks(editor, "first")
        QTest.keyClick(editor, Qt.Key_Return, Qt.AltModifier)
        QTest.keyClicks(editor, "second")
        assert editor.text() == "first\nsecond"
        QTest.keyClick(editor, Qt.Key_Return)
        qtbot.wait(20)
        assert model.cell_source(0, 1) == "first\nsecond"
        assert view.currentIndex().row() == 1          # moved down, as ever

    def test_the_cell_wraps_and_its_row_grows(self, view, qtbot):
        model = view.model()
        default = view.verticalHeader().defaultSectionSize()
        edits = []
        model.sheet_edited.connect(edits.append)
        editor = _open(view, qtbot, 0, 1)
        editor.setText("one\ntwo\nthree")
        QTest.keyClick(editor, Qt.Key_Return)
        qtbot.waitUntil(lambda: view.rowHeight(0) > default * 2)
        assert model.cell_format(0, 1) == {"wrap": True}
        assert len(edits) == 1                        # text and wrap together

    def test_the_editor_grows_with_its_lines(self, view, qtbot):
        editor = _open(view, qtbot, 0, 1)
        one = editor.height()
        editor.setText("a\nb\nc\nd")
        assert editor.height() > one * 2

    def test_typing_replaces_like_a_line_edit(self, view, qtbot):
        model = view.model()
        editor = _open(view, qtbot, 0, 0)               # holds "Pen"
        QTest.keyClicks(editor, "Cap")
        QTest.keyClick(editor, Qt.Key_Return)
        qtbot.wait(20)
        assert model.cell_source(0, 0) == "Cap"

    def test_formula_completion_still_works(self, view, qtbot):
        editor = _open(view, qtbot, 2, 1)
        QTest.keyClicks(editor, "=SU")
        from PySide6.QtWidgets import QCompleter
        popup = editor.findChild(QCompleter).popup()
        qtbot.waitUntil(popup.isVisible)
        QTest.keyClick(popup, Qt.Key_Return)          # takes SUM
        assert editor.text() == "=SUM("

    def test_ctrl_enter_still_fills_the_selection(self, view, qtbot):
        from PySide6.QtCore import QItemSelection, QItemSelectionModel
        model = view.model()
        view.setCurrentIndex(model.index(0, 1))
        view.selectionModel().select(
            QItemSelection(model.index(0, 1), model.index(1, 1)),
            QItemSelectionModel.ClearAndSelect)
        view.edit(model.index(0, 1))                  # keeps the selection
        qtbot.wait(20)
        editor = view.indexWidget(model.index(0, 1))
        editor.setText("x")
        QTest.keyClick(editor, Qt.Key_Return, Qt.ControlModifier)
        qtbot.wait(20)
        assert [model.cell_source(r, 1) for r in (0, 1)] == ["x", "x"]


class TestFormulaBar:
    def test_shows_and_takes_line_breaks(self, qtbot):
        model = SheetModel(json.dumps(DATA))
        bench = SheetWorkbench(model)
        qtbot.addWidget(bench)
        bench.show()
        model.setData(model.index(0, 1), "a\nb")
        bench.view.setCurrentIndex(model.index(0, 1))
        from flograph.ui.spreadsheet.tools import FormulaBar
        bar = bench.findChild(FormulaBar)
        assert bar.edit.text() == "a↵b"
        bar.edit.setFocus()
        bar.edit.end(False)
        QTest.keyClick(bar.edit, Qt.Key_Return, Qt.AltModifier)
        QTest.keyClicks(bar.edit, "c")
        bar.commit()
        assert model.cell_source(0, 1) == "a\nb\nc"


def test_paste_keeps_a_multi_line_cell_together(view):
    model = view.model()
    QApplication.clipboard().setText('"one\ntwo"\tx')
    view.setCurrentIndex(model.index(0, 0))
    view.paste_clipboard()
    assert model.cell_source(0, 0) == "one\ntwo"
    assert model.cell_format(0, 0) == {"wrap": True}
    view.copy_selection()
    assert QApplication.clipboard().text().startswith('"one\ntwo"')


class TestRowGrowsWhileTyping:
    def test_the_row_grows_live_and_settles(self, view, qtbot):
        model = view.model()
        default = view.verticalHeader().defaultSectionSize()
        editor = _open(view, qtbot, 0, 1)
        QTest.keyClicks(editor, "one")
        QTest.keyClick(editor, Qt.Key_Return, Qt.AltModifier)
        QTest.keyClicks(editor, "two")
        QTest.keyClick(editor, Qt.Key_Return, Qt.AltModifier)
        QTest.keyClicks(editor, "three")
        # the row itself — and so the outline — grows while typing, and the
        # editor sits inside it rather than over the row below
        assert view.rowHeight(0) > default * 2
        assert editor.height() <= view.rowHeight(0)
        assert model.row_heights == {}                # not saved: just live
        QTest.keyClick(editor, Qt.Key_Return)
        qtbot.waitUntil(lambda: model.cell_source(0, 1) == "one\ntwo\nthree")
        qtbot.wait(50)
        assert view.rowHeight(0) > default * 2        # fitted to the kept text

    def test_escape_puts_the_row_back(self, view, qtbot):
        default = view.verticalHeader().defaultSectionSize()
        editor = _open(view, qtbot, 1, 1)
        editor.setText("a\nb\nc")
        assert view.rowHeight(1) > default
        QTest.keyClick(editor, Qt.Key_Escape)
        qtbot.waitUntil(lambda: view.rowHeight(1) == default)
