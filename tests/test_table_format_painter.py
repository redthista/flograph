"""Format Painter: pick up a look, click or drag over cells to paint it —
once, or (double-click) until Esc — with the source's pattern repeated
across a bigger target, as one undo step."""
import json

import pytest
from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt
from PySide6.QtTest import QTest

from flograph.ui.spreadsheet import SheetModel, SpreadsheetView

DATA = {"version": 2,
        "columns": [{"name": "A"}, {"name": "B"}, {"name": "C"}],
        "rows": [["1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"],
                 ["10", "11", "12"]],
        "styles": [[0, 0, {"b": True}], [1, 0, {"fill": "#fde68a"}]]}


@pytest.fixture
def view(qtbot):
    model = SheetModel(json.dumps(DATA))
    view = SpreadsheetView()
    model.setParent(view)
    view.setModel(model)
    qtbot.addWidget(view)
    view.resize(500, 300)
    view.show()
    qtbot.waitExposed(view)
    return view


def _select(view, r0, c0, r1, c1):
    model = view.model()
    view.setCurrentIndex(model.index(r0, c0))
    view.selectionModel().select(
        QItemSelection(model.index(r0, c0), model.index(r1, c1)),
        QItemSelectionModel.ClearAndSelect)


def _click(view, row, col):
    rect = view.visualRect(view.model().index(row, col))
    QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=rect.center())


def _drag(view, a, b):
    start = view.visualRect(view.model().index(*a)).center()
    end = view.visualRect(view.model().index(*b)).center()
    QTest.mousePress(view.viewport(), Qt.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), end)
    QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=end)


class TestPainter:
    def test_one_click_paints_once(self, view):
        model = view.model()
        _select(view, 0, 0, 0, 0)
        view.actions["format_painter"].trigger()
        assert view.painting
        _click(view, 2, 2)
        assert model.cell_format(2, 2) == {"b": True}
        assert not view.painting                     # one go, then off
        _click(view, 3, 2)
        assert model.cell_format(3, 2) == {}
        assert model.cell_source(2, 2) == "9"        # values untouched

    def test_pattern_repeats_over_a_drag_as_one_edit(self, view):
        model = view.model()
        _select(view, 0, 0, 1, 0)                     # bold, then yellow
        view.start_painter()
        edits = []
        model.sheet_edited.connect(edits.append)
        _drag(view, (0, 1), (3, 1))
        assert len(edits) == 1
        assert [model.cell_format(r, 1) for r in range(4)] == [
            {"b": True}, {"fill": "#fde68a"}, {"b": True},
            {"fill": "#fde68a"}]

    def test_plain_source_clears(self, view):
        model = view.model()
        _select(view, 2, 2, 2, 2)                     # no format
        view.start_painter()
        _click(view, 0, 0)
        assert model.cell_format(0, 0) == {}

    def test_sticky_until_escape(self, view):
        model = view.model()
        _select(view, 0, 0, 0, 0)
        view.start_painter(sticky=True)
        _click(view, 2, 1)
        _click(view, 3, 2)
        assert view.painting
        assert model.cell_format(2, 1) == model.cell_format(3, 2) == {
            "b": True}
        QTest.keyClick(view, Qt.Key_Escape)
        assert not view.painting
        assert view.viewport().cursor().shape() != Qt.BitmapCursor

    def test_button_off_stops(self, view):
        _select(view, 0, 0, 0, 0)
        action = view.actions["format_painter"]
        action.trigger()
        view.actions.refresh()
        assert action.isChecked()
        action.trigger()
        assert not view.painting

    def test_ribbon_double_click_keeps_painting(self, qtbot):
        from flograph.ui.spreadsheet import SheetWorkbench
        from flograph.ui.spreadsheet.ribbon import RibbonButton
        bench = SheetWorkbench(SheetModel(json.dumps(DATA)))
        qtbot.addWidget(bench)
        bench.show()
        qtbot.waitExposed(bench)
        view = bench.view
        _select(view, 0, 0, 0, 0)
        button = next(b for b in bench.ribbon.findChildren(RibbonButton)
                      if b._action is view.actions["format_painter"]
                      and b.isVisible())
        QTest.mouseDClick(button, Qt.LeftButton)
        assert view.painting and view._painter["sticky"]

    def test_ribbon_still_fits(self, qtbot):
        from flograph.ui.spreadsheet import SheetWorkbench
        bench = SheetWorkbench(SheetModel(json.dumps(DATA)))
        qtbot.addWidget(bench)
        stack = bench.ribbon._stacks["full"]
        assert max(stack.widget(i).sizeHint().width()
                   for i in range(stack.count())) <= 1100
