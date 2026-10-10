"""The small Excel staples: the selection summary (Average / Count / Sum
beside the formula bar), AutoSum (Alt+=) and F4 pinning a reference."""
import json

import pytest
from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt
from PySide6.QtTest import QTest

from flograph.core.sheet.absref import cycle
from flograph.core.sheet.autosum import Totals, propose, totals
from flograph.core.sheet.summary import summarise, summary_text
from flograph.ui.spreadsheet import SheetModel, SheetWorkbench


class TestSummary:
    def test_counts_like_excel(self):
        s = summarise([1, 2, "x", True, None, "", 3.5])
        assert (s.count, s.numbers, s.sum, s.min, s.max) == (5, 3, 6.5, 1, 3.5)
        assert summary_text(s) == "Average: 2.166666667   Count: 5   Sum: 6.5"

    def test_text_only_shows_count(self):
        assert summary_text(summarise(["a", "b"])) == "Count: 2"
        assert summary_text(summarise([])) == ""

    def test_chosen_figures_and_format(self):
        s = summarise([1000, 2000])
        assert summary_text(s, ["min", "max", "numbers"]) == (
            "Numerical Count: 2   Min: 1,000   Max: 2,000")
        assert summary_text(s, ["sum"], lambda v: f"£{v:.2f}") == (
            "Sum: £3000.00")


class TestAutoSumRule:
    NUMS = {(0, 1), (1, 1), (2, 1), (4, 0), (4, 1)}

    def _num(self, r, c):
        return (r, c) in self.NUMS

    def test_proposes_the_numbers_above(self):
        p = propose("SUM", 3, 1, self._num)
        assert p.text == "=SUM(B1:B3)"
        assert p.text[p.span[0]:p.span[1]] == "B1:B3"

    def test_else_the_numbers_left(self):
        assert propose("AVERAGE", 4, 2, self._num).text == "=AVERAGE(A5:B5)"

    def test_else_an_empty_call(self):
        p = propose("MAX", 0, 0, self._num)
        assert p.text == "=MAX()" and p.span == (5, 5)

    def test_range_totals_go_below(self):
        nums = {(r, c) for r in range(3) for c in (1, 2)}
        filled = nums | {(r, 0) for r in range(3)}
        result = totals("SUM", (0, 0, 2, 2), 3, 3, lambda r, c: (r, c) in nums,
                        lambda r, c: (r, c) not in filled)
        assert result == Totals({(3, 1): "=SUM(B1:B3)",
                                 (3, 2): "=SUM(C1:C3)"}, grows=True)

    def test_an_empty_last_row_takes_them(self):
        nums = {(0, 0), (1, 0)}
        result = totals("SUM", (0, 0, 2, 0), 5, 1,
                        lambda r, c: (r, c) in nums,
                        lambda r, c: (r, c) not in nums)
        assert result.cells == {(2, 0): "=SUM(A1:A2)"} and not result.grows

    def test_one_row_totals_to_the_right(self):
        nums = {(0, 0), (0, 1)}
        result = totals("SUM", (0, 0, 0, 1), 1, 4,
                        lambda r, c: (r, c) in nums,
                        lambda r, c: (r, c) not in nums)
        assert result.cells == {(0, 2): "=SUM(A1:B1)"}

    def test_nothing_to_total(self):
        assert "no numbers" in totals("SUM", (0, 0, 2, 0), 3, 1,
                                      lambda r, c: False, lambda r, c: True)


class TestF4:
    @pytest.mark.parametrize("before,after", [
        ("=A1", "=$A$1"), ("=$A$1", "=A$1"), ("=A$1", "=$A1"),
        ("=$A1", "=A1")])
    def test_the_cycle(self, before, after):
        assert cycle(before, len(before))[0] == after

    def test_a_range_moves_as_one(self):
        text, start, end = cycle("=SUM(B2:B9)*C1", 6)
        assert text == "=SUM($B$2:$B$9)*C1" and start == end == 14

    def test_selection_moves_every_reference(self):
        assert cycle("=A1+B2+C3", 0, 9) == ("=$A$1+$B$2+$C$3", 1, 15)

    def test_leaves_text_columns_names_and_calls(self):
        assert cycle('="B2"', 4) is None
        assert cycle("=[B2]+1", 3) is None
        assert cycle("=Week52", 7) is None
        assert cycle("plain B2", 8) is None
        assert cycle("=LOG10(2)", 6) is None


DATA = {"version": 2,
        "columns": [{"name": "Item"}, {"name": "Price", "type": "number",
                                       "format": {"kind": "currency",
                                                  "symbol": "£",
                                                  "decimals": 2}},
                    {"name": "Qty", "type": "number"}],
        "rows": [["Pen", "2", "10"], ["Pad", "5", "1"], ["Ink", "4", "3"],
                 ["", "", ""]]}


@pytest.fixture
def bench(qtbot):
    bench = SheetWorkbench(SheetModel(json.dumps(DATA)))
    qtbot.addWidget(bench)
    bench.resize(900, 400)
    bench.show()
    qtbot.waitExposed(bench)
    return bench


def _select(view, r0, c0, r1, c1):
    model = view.model()
    view.setCurrentIndex(model.index(r0, c0))
    view.selectionModel().select(
        QItemSelection(model.index(r0, c0), model.index(r1, c1)),
        QItemSelectionModel.ClearAndSelect)


def _bar(bench):
    from flograph.ui.spreadsheet.tools import FormulaBar
    return bench.findChild(FormulaBar)


class TestOnTheGrid:
    def test_summary_follows_the_selection(self, bench, qtbot, monkeypatch):
        from flograph.ui.spreadsheet import tools
        monkeypatch.setattr(tools, "summary_figures",
                            lambda: ["average", "count", "sum"])
        bar = _bar(bench)
        _select(bench.view, 0, 1, 2, 1)
        qtbot.waitUntil(bar.summary.isVisible)
        assert bar.summary.text() == (
            "Average: £3.67   Count: 3   Sum: £11.00")
        _select(bench.view, 0, 0, 0, 0)          # one cell: nothing
        qtbot.waitUntil(lambda: not bar.summary.isVisible())
        bench.view.setRowHidden(0, True)         # out of sight: left out
        _select(bench.view, 0, 2, 2, 2)
        qtbot.waitUntil(lambda: "Sum: 4" in bar.summary.text())

    def test_autosum_a_range_writes_the_totals(self, bench):
        view, model = bench.view, bench.view.model()
        _select(view, 0, 1, 2, 2)
        view.actions["autosum"].trigger()
        assert model.cell_source(3, 1) == "=SUM(B1:B3)"
        assert model.cell_source(3, 2) == "=SUM(C1:C3)"
        assert model.computed_value(3, 2) == 14
        assert model.rowCount() == 4             # the blank row took them

    def test_autosum_grows_a_row_when_full(self, bench):
        view, model = bench.view, bench.view.model()
        model.set_cells((3, 0), [["x", "1", "1"]])
        _select(view, 0, 2, 3, 2)
        view.actions["autosum_max"].trigger()
        assert model.rowCount() == 5
        assert model.cell_source(4, 2) == "=MAX(C1:C4)"

    def test_autosum_one_cell_proposes(self, bench, qtbot):
        view = bench.view
        _select(view, 3, 2, 3, 2)
        view.actions["autosum"].trigger()
        editor = view.indexWidget(view.model().index(3, 2))
        assert editor.text() == "=SUM(C1:C3)"
        assert editor.textCursor().selectedText() == "C1:C3"
        QTest.keyClick(editor, Qt.Key_Return)
        assert view.model().computed_value(3, 2) == 14

    def test_alt_equals_is_autosum(self, bench):
        action = bench.view.actions.for_key(
            _key(Qt.Key_Equal, Qt.AltModifier))
        assert action is bench.view.actions["autosum"]

    def test_f4_in_the_cell_editor(self, bench, qtbot):
        view = bench.view
        index = view.model().index(3, 0)
        view.setCurrentIndex(index)
        view.start_formula("=B1*C1")
        editor = view.indexWidget(index)
        editor.setCursorPosition(3)
        QTest.keyClick(editor, Qt.Key_F4)
        assert editor.text() == "=$B$1*C1"
        QTest.keyClick(editor, Qt.Key_F4)
        assert editor.text() == "=B$1*C1"

    def test_f4_in_the_formula_bar(self, bench):
        edit = _bar(bench).edit
        edit.setText("=SUM(A1:A3)")
        edit.setCursorPosition(7)
        QTest.keyClick(edit, Qt.Key_F4)
        assert edit.text() == "=SUM($A$1:$A$3)"

    def test_ribbon_has_autosum(self, bench):
        from flograph.ui.spreadsheet.ribbon import RibbonButton
        labels = [b.text() for b in bench.ribbon.findChildren(RibbonButton)]
        assert "AutoSum" in labels               # Home and Formulas


def _key(key, mods):
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    return QKeyEvent(QEvent.KeyPress, key, mods)
