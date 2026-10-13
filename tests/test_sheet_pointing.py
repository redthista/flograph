"""Point mode: click a cell while typing a formula to type its reference
(core/sheet/pointref.py, ui/spreadsheet/pointing.py). The UI tests click
with real mouse events, since what this has to survive is Qt moving focus
to the grid before anything else sees the click."""
import json

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from flograph.core.sheet.pointref import point_span, put, range_text
from flograph.ui.spreadsheet import SheetModel, SheetWorkbench

DATA = {"columns": [{"name": n} for n in ("Item", "Price", "Qty")],
        "rows": [["a", "1", "2"], ["b", "3", "4"], ["c", "5", "6"],
                 ["", "", ""], ["", "", ""]]}


class TestRule:
    @pytest.mark.parametrize("text", ["=", "=SUM(", "=A1+", "=IF(A1,",
                                      "=A1 * ", "=A1<>", "=SUM(A1:"])
    def test_points_after_an_opener(self, text):
        assert point_span(text, len(text)) == (len(text), len(text))

    @pytest.mark.parametrize("text", ["", "abc", "=A1", "=2", "=SUM(A1)",
                                      '="a', "=[Pri"])
    def test_not_elsewhere(self, text):
        assert point_span(text, len(text)) is None

    def test_a_selection_is_replaced(self):
        assert point_span("=SUM(C1:C3)", 5, 10) == (5, 10)

    def test_inside_quotes_is_not_a_place(self):
        assert point_span('=IF(A1="(", ', 9) is None

    def test_range_text(self):
        assert range_text((2, 1), (2, 1)) == "B3"
        assert range_text((3, 2), (0, 0)) == "A1:C4"

    def test_put(self):
        assert put("=SUM()", (5, 5), "B2:B4") == ("=SUM(B2:B4)", (5, 10))


@pytest.fixture
def bench(qtbot):
    bench = SheetWorkbench(SheetModel(json.dumps(DATA)))
    qtbot.addWidget(bench)
    bench.resize(900, 400)
    bench.show()
    qtbot.waitExposed(bench)
    return bench


def _start(view, row, col, text):
    index = view.model().index(row, col)
    view.setCurrentIndex(index)
    view.start_formula(text)
    from flograph.ui.spreadsheet.delegates import SheetDelegate
    return SheetDelegate.last_editor


def _at(table, row, col):
    return table.visualRect(table.model().index(row, col)).center()


def _click(table, row, col, mods=Qt.NoModifier):
    QTest.mouseClick(table.viewport(), Qt.LeftButton, mods,
                     _at(table, row, col))
    QTest.qWait(10)


def _open(editor) -> bool:
    import shiboken6
    return shiboken6.isValid(editor) and editor.isVisible()


class TestClicking:
    def test_equals_then_click(self, bench):
        view = bench.view
        editor = _start(view, 3, 0, "=")
        _click(view, 0, 1)
        assert _open(editor) and editor.text() == "=B1"
        assert QApplication.focusWidget() is editor
        assert view.ref_pointer.pointed == (0, 1, 0, 1)

    def test_a_second_click_replaces(self, bench):
        view = bench.view
        editor = _start(view, 3, 0, "=SUM(")
        _click(view, 0, 1)
        _click(view, 1, 2)
        assert editor.text() == "=SUM(C2"

    def test_shift_click_makes_a_range(self, bench):
        view = bench.view
        editor = _start(view, 3, 0, "=")
        _click(view, 0, 1)
        _click(view, 2, 2, Qt.ShiftModifier)
        assert editor.text() == "=B1:C3"

    def test_drag_makes_a_range(self, bench):
        view = bench.view
        editor = _start(view, 3, 0, "=SUM(")
        vp = view.viewport()
        QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, _at(view, 0, 1))
        QTest.mouseMove(vp, _at(view, 1, 1))
        QTest.mouseMove(vp, _at(view, 2, 1))
        QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, _at(view, 2, 1))
        assert editor.text() == "=SUM(B1:B3"
        assert view.ref_pointer.pointed == (0, 1, 2, 1)

    def test_after_an_operator_it_adds(self, bench):
        view = bench.view
        editor = _start(view, 3, 0, "=")
        _click(view, 0, 1)
        QTest.keyClicks(editor, "*")
        assert view.ref_pointer.pointed is None
        _click(view, 0, 2)
        assert editor.text() == "=B1*C1"
        QTest.keyClick(editor, Qt.Key_Return)
        assert view.model().computed_value(3, 0) == 2

    def test_a_double_click_still_points(self, bench):
        view = bench.view
        editor = _start(view, 3, 0, "=")
        QTest.mouseDClick(view.viewport(), Qt.LeftButton, Qt.NoModifier,
                          _at(view, 1, 1))
        QTest.qWait(10)
        assert _open(editor) and editor.text() == "=B2"


class TestNotPointing:
    def test_a_finished_reference_ends_the_edit(self, bench):
        view = bench.view
        model = view.model()
        editor = _start(view, 3, 0, "=B1*2")
        _click(view, 0, 2)
        QTest.qWait(20)
        assert not _open(editor)
        assert model.cell_source(3, 0) == "=B1*2"
        current = view.currentIndex()
        assert (current.row(), current.column()) == (0, 2)

    def test_plain_text_is_untouched(self, bench):
        view = bench.view
        editor = _start(view, 3, 0, "hello")
        _click(view, 0, 2)
        QTest.qWait(20)
        assert not _open(editor)
        assert view.model().cell_source(3, 0) == "hello"

    def test_a_header_click_ends_the_edit(self, bench):
        view = bench.view
        editor = _start(view, 3, 0, "=1+")
        header = view.horizontalHeader()
        QTest.mouseClick(header.viewport(), Qt.LeftButton, Qt.NoModifier,
                         _header_point(header, 2))
        QTest.qWait(30)
        assert not _open(editor)
        assert view.model().cell_source(3, 0) == "=1+"

    def test_empty_space_ends_the_edit(self, bench):
        view = bench.view
        editor = _start(view, 3, 0, "=")
        last = view.visualRect(view.model().index(4, 2))
        QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier,
                         QPoint(last.right() + 20, last.bottom() + 20))
        QTest.qWait(30)
        assert not _open(editor)


def _header_point(header, section):
    x = header.sectionViewportPosition(section) + header.sectionSize(
        section) // 3
    return QPoint(x, header.height() // 2)


class TestFrozen:
    def test_point_at_a_frozen_cell(self, bench):
        view = bench.view
        view.freeze_top_row()
        QTest.qWait(10)
        pane = view.frozen_panes.panes()["rows"]
        editor = _start(view, 3, 0, "=")
        _click(pane, 0, 2)
        assert _open(editor) and editor.text() == "=C1"
