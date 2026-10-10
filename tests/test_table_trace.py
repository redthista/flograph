"""Formula auditing: Trace Precedents / Dependents arrows, Remove Arrows,
and Ctrl+[ / Ctrl+] selecting what a formula reads or what reads it."""
import json

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from flograph.core.sheet import ColumnSpec, Sheet
from flograph.core.sheet.engine import SheetEvaluator
from flograph.core.sheet.trace import Arrow, Trace
from flograph.ui.spreadsheet import SheetModel, SheetWorkbench


def _sheet():
    #    A    B     C
    # 1  1    2     =A1+B1
    # 2  3    4     =A2*2
    # 3              =SUM(C1:C2)
    return Sheet(columns=[ColumnSpec("A"), ColumnSpec("B"), ColumnSpec("C")],
                 rows=[["1", "2", "=A1+B1"], ["3", "4", "=A2*2"],
                       ["", "", "=SUM(C1:C2)"]])


class TestEngine:
    def test_what_a_formula_reads_and_what_reads_a_cell(self):
        e = SheetEvaluator(_sheet())
        assert e.precedents((0, 2)) == ([(0, 0), (0, 1)], [])
        assert e.precedents((2, 2)) == ([], [(0, 2, 1, 2)])
        assert e.precedents((0, 0)) == ([], [])
        assert e.dependents((0, 0)) == [(0, 2)]
        assert e.dependents((1, 2)) == [(2, 2)]      # through the range
        assert e.is_formula((2, 2)) and not e.is_formula((0, 0))


class TestTrace:
    def test_precedents_level_by_level(self):
        e, t = SheetEvaluator(_sheet()), Trace()
        assert t.precedents(e, (2, 2)) == 1
        assert t.boxes == {(0, 2, 1, 2)}
        assert Arrow((0, 2), (2, 2), (0, 2, 1, 2)) in t.arrows
        assert t.precedents(e, (2, 2)) == 3          # into C1 and C2
        assert Arrow((0, 0), (0, 2)) in t.arrows
        assert t.precedents(e, (2, 2)) == 0          # only values left

    def test_dependents_level_by_level(self):
        e, t = SheetEvaluator(_sheet()), Trace()
        assert t.dependents(e, (0, 0)) == 1
        assert t.dependents(e, (0, 0)) == 1          # C1 → C3
        assert Arrow((0, 2), (2, 2)) in t.arrows
        assert t.dependents(e, (0, 0)) == 0

    def test_clear(self):
        e, t = SheetEvaluator(_sheet()), Trace()
        t.precedents(e, (2, 2))
        assert t
        t.clear()
        assert not t and t.precedents(e, (2, 2)) == 1


DATA = {"version": 2,
        "columns": [{"name": "Price", "type": "number"},
                    {"name": "Qty", "type": "number"}, {"name": "Total"}],
        "rows": [["2", "10", "=[@Price]*[@Qty]"],
                 ["5", "1", "=[@Price]*[@Qty]"],
                 ["", "", "=SUM([Total])"]]}


@pytest.fixture
def bench(qtbot):
    bench = SheetWorkbench(SheetModel(json.dumps(DATA)))
    qtbot.addWidget(bench)
    bench.resize(800, 300)
    bench.show()
    qtbot.waitExposed(bench)
    return bench


class TestGrid:
    def test_trace_and_remove(self, bench):
        view = bench.view
        model = view.model()
        view.setCurrentIndex(model.index(0, 2))
        view.actions.refresh()
        view.actions["trace_precedents"].trigger()
        assert {(a.source, a.target) for a in view._trace.arrows} == {
            ((0, 0), (0, 2)), ((0, 1), (0, 2))}
        view.actions.refresh()
        assert view.actions["remove_arrows"].isEnabled()
        view.repaint()                               # paints without error
        view.actions["remove_arrows"].trigger()
        assert not view.has_arrows

    def test_an_edit_clears_the_arrows(self, bench):
        view = bench.view
        model = view.model()
        view.setCurrentIndex(model.index(1, 0))
        view.trace_dependents()
        assert view.has_arrows
        model.setData(model.index(1, 0), "6")
        assert not view.has_arrows

    def test_whole_column_reads_as_a_box(self, bench):
        view = bench.view
        view.setCurrentIndex(view.model().index(2, 2))
        view.trace_precedents()
        assert view._trace.boxes == {(0, 2, 2, 2)}
        from flograph.ui.spreadsheet.trace_paint import box_rect
        assert box_rect(view, (0, 2, 2, 2)) is not None
        view.setRowHidden(1, True)
        assert box_rect(view, (0, 2, 2, 2)) is not None
        view.repaint()

    def test_a_value_says_it_reads_nothing(self, bench, monkeypatch):
        view = bench.view
        said = []
        monkeypatch.setattr(view, "say", said.append)
        view.setCurrentIndex(view.model().index(0, 0))
        view.trace_precedents()
        assert "holds no formula" in said[-1]
        view.setCurrentIndex(view.model().index(2, 0))
        view.trace_dependents()
        assert said[-1] == "No formula reads A3."

    def test_ctrl_brackets_select(self, bench):
        view = bench.view
        model = view.model()
        view.setCurrentIndex(model.index(0, 2))
        key = QKeyEvent(QEvent.KeyPress, Qt.Key_BracketLeft,
                        Qt.ControlModifier)
        assert view.actions.for_key(key) is view.actions["select_precedents"]
        view.select_precedents()
        picked = {(i.row(), i.column())
                  for i in view.selectionModel().selectedIndexes()}
        assert picked == {(0, 0), (0, 1)}
        view.setCurrentIndex(model.index(0, 0))
        view.select_dependents()
        picked = {(i.row(), i.column())
                  for i in view.selectionModel().selectedIndexes()}
        assert picked == {(0, 2)}

    def test_ribbon_group(self, bench):
        from flograph.ui.spreadsheet.ribbon import RibbonButton
        labels = {b.text() for b in bench.ribbon.findChildren(RibbonButton)}
        assert {"Trace Precedents", "Trace Dependents",
                "Remove Arrows"} <= labels
