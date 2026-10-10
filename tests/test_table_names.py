"""Named ranges: =SUM(Sales) instead of =SUM(B2:B40) — Excel's defined
names, the Name Box, the Name Manager, completion and Go To."""
import json

import pytest
from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt

from flograph.core.sheet import (FUNCTION_NAMES, ColumnSpec, Sheet,
                                 evaluate_sheet, parse_sheet, sheet_to_dict)
from flograph.core.sheet import names as nm
from flograph.ui.spreadsheet import SheetModel, SheetWorkbench, SpreadsheetView


class TestCore:
    @pytest.mark.parametrize("name,ok", [
        ("Sales", True), ("tax_rate", True), ("Week52", True), ("_x", True),
        ("B2", False), ("Tax2026", False), ("SUM", False), ("true", False),
        ("two words", False), ("Q1Sales", False), ("", False),
        ("a.b", False)])
    def test_check_name(self, name, ok):
        assert (nm.check_name(name, (), FUNCTION_NAMES) is None) == ok

    def test_taken_is_case_blind(self):
        assert "already" in nm.check_name("SALES", ["Sales"])

    def test_parse_target(self):
        assert nm.parse_target("b2:B40") == "$B$2:$B$40"
        assert nm.parse_target("=$F$1") == "$F$1"
        assert nm.parse_target("D4:B2") == "$B$2:$D$4"
        assert nm.parse_target("Sales").startswith("!")
        assert nm.plain("$B$2:$B$40") == "B2:B40"

    def test_expand_leaves_strings_columns_and_calls(self):
        names = {"Sales": "$B$2:$B$3", "Rate": "$C$1"}
        src = '=SUM(Sales)*Rate & "Sales" & [Sales] + RATE( 1 )'
        assert nm.expand_names(src, names) == (
            '=SUM($B$2:$B$3)*$C$1 & "Sales" & [Sales] + RATE( 1 )')

    def test_rename_keeps_spacing(self):
        assert nm.rename_in_formula("=SUM( Sales ) * 2", "sales", "Rev") \
            == "=SUM( Rev ) * 2"

    def _sheet(self):
        sheet = Sheet(columns=[ColumnSpec("A"), ColumnSpec("B", "number"),
                               ColumnSpec("C")],
                      rows=[["x", "10", "=SUM(Sales)*Rate"],
                            ["y", "20", "=Sales"], ["z", "30", ""]])
        sheet.names = {"Sales": "$B$1:$B$3", "Rate": "$B$2"}
        return sheet

    def test_formulas_use_names(self):
        result = evaluate_sheet(self._sheet())
        assert result.values[0][2] == 1200          # (10+20+30) * 20
        # a whole range in one cell reads as a typed range does
        assert "needs a function like SUM" in result.errors[(1, 2)]

    def test_unknown_name_says_so(self):
        sheet = self._sheet()
        sheet.rows[2][2] = "=Nope*2"
        result = evaluate_sheet(sheet)
        assert "isn't a defined name" in result.errors[(2, 2)]

    def test_names_move_with_rows_and_save(self):
        sheet = self._sheet()
        sheet.insert_rows(0, 1)
        assert sheet.names == {"Sales": "$B$2:$B$4", "Rate": "$B$3"}
        sheet.remove_rows([2])                       # the Rate row
        assert sheet.names["Rate"] == "#REF!"
        data = sheet_to_dict(sheet)
        assert data["names"]["Sales"] == "$B$2:$B$3"
        back = parse_sheet(json.dumps(data))
        assert back.names == sheet.names
        assert sheet.copy().names == sheet.names

    def test_bad_saved_names_dropped(self):
        data = {"columns": ["A"], "rows": [["1"]],
                "names": {"Good": "A1", "B2": "A1", "Odd": "nonsense",
                          "Gone": "#REF!", 3: "A1"}}
        assert parse_sheet(data).names == {"Good": "$A$1", "Gone": "#REF!"}

    def test_incremental_recalc_follows_a_named_cell(self):
        from flograph.core.sheet import SheetEvaluator
        sheet = self._sheet()
        evaluator = SheetEvaluator(sheet)
        sheet.rows[1][1] = "5"                       # Rate, and in Sales
        result = evaluator.update(sheet, [(1, 1)])
        assert result.values[0][2] == (10 + 5 + 30) * 5


DATA = {"version": 2,
        "columns": [{"name": "Item"}, {"name": "Price", "type": "number"},
                    {"name": "Total"}],
        "rows": [["Pen", "2", "=SUM(Prices)"], ["Pad", "5", ""],
                 ["Ink", "4", ""]],
        "names": {"Prices": "$B$1:$B$3"}}


@pytest.fixture
def view(qtbot):
    model = SheetModel(json.dumps(DATA))
    view = SpreadsheetView()
    model.setParent(view)
    view.setModel(model)
    qtbot.addWidget(view)
    return view


def _select(view, r0, c0, r1, c1):
    model = view.model()
    view.setCurrentIndex(model.index(r0, c0))
    view.selectionModel().select(
        QItemSelection(model.index(r0, c0), model.index(r1, c1)),
        QItemSelectionModel.ClearAndSelect)


class TestModel:
    def test_value_and_edits(self, view):
        model = view.model()
        assert model.value_text(0, 2) == "11"
        model.setData(model.index(1, 1), "15")
        assert model.value_text(0, 2) == "21"
        assert model.name_value_text("prices").startswith("{2, 15, 4}")

    def test_define_rename_delete_are_edits(self, view):
        model = view.model()
        edits = []
        model.sheet_edited.connect(edits.append)
        model.define_name("Cost", "$B$1:$B$3", replacing="Prices")
        assert model.cell_source(0, 2) == "=SUM(Cost)"   # formula followed
        assert model.value_text(0, 2) == "11"
        model.delete_name("Cost")
        assert "isn't a defined name" in model.cell_error(0, 2)
        assert len(edits) == 2


class TestNameBox:
    def test_go_to_a_name_and_name_a_selection(self, qtbot):
        model = SheetModel(json.dumps(DATA))
        bench = SheetWorkbench(model)
        qtbot.addWidget(bench)
        from flograph.ui.spreadsheet.tools import FormulaBar
        bar = bench.findChild(FormulaBar)
        box = bar.cell_label
        assert [box.itemText(i) for i in range(box.count())] == ["Prices"]
        bar._name_box_entered("prices")
        rows = sorted({i.row() for i in
                       bench.view.selectionModel().selectedIndexes()})
        assert rows == [0, 1, 2]
        _select(bench.view, 0, 0, 2, 0)
        bar._name_box_entered("Items")                # a new name
        assert model.names["Items"] == "$A$1:$A$3"
        assert "Items" in [box.itemText(i) for i in range(box.count())]
        bar._name_box_entered("B2")                   # an address: go
        assert bench.view.currentIndex().row() == 1
        bar._name_box_entered("B9")                   # nowhere: no name made
        assert "B9" not in model.names

    def test_the_box_names_a_named_selection(self, qtbot):
        model = SheetModel(json.dumps(dict(DATA, names={
            "Prices": "$B$1:$B$3", "First": "$A$1"})))
        bench = SheetWorkbench(model)
        qtbot.addWidget(bench)
        from flograph.ui.spreadsheet.tools import FormulaBar
        box = bench.findChild(FormulaBar).cell_label
        view = bench.view
        _select(view, 0, 1, 2, 1)                     # exactly Prices
        assert box.text() == "Prices"
        _select(view, 0, 1, 1, 1)                     # part of it
        assert box.text() == "B1"
        _select(view, 0, 0, 0, 0)                     # a named cell
        assert box.text() == "First"
        _select(view, 1, 0, 1, 0)
        assert box.text() == "A2"
        _select(view, 0, 2, 2, 2)
        bench.findChild(FormulaBar)._name_box_entered("Totals")
        assert box.text() == "Totals"                 # just named: shows

    def test_name_manager(self, view, qtbot):
        from flograph.ui.spreadsheet.names_dialog import NameManager
        model = view.model()
        _select(view, 0, 1, 1, 1)
        dialog = NameManager(view, new_from_selection=True)
        qtbot.addWidget(dialog)
        assert dialog.target.text() == "B1:B2"
        dialog.name.setText("SUM")
        assert not dialog.save_btn.isEnabled()
        dialog.name.setText("Firsts")
        assert "will stand for B1:B2" in dialog.status.text()
        dialog.save_btn.click()
        assert model.names["Firsts"] == "$B$1:$B$2"
        dialog.table.selectRow([dialog.table.item(i, 0).text()
                                for i in range(dialog.table.rowCount())]
                               .index("Firsts"))
        dialog.delete_btn.click()
        assert "Firsts" not in model.names

    def test_go_to_takes_names(self, view, qtbot):
        from flograph.ui.spreadsheet.goto_dialog import GoToDialog
        dialog = GoToDialog(view)
        qtbot.addWidget(dialog)
        dialog.ref.setText("Prices")
        assert dialog.target() == (0, 1, 2, 1)

    def test_completion_offers_names(self, view, qtbot):
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QCompleter
        view.resize(400, 300)
        view.show()
        qtbot.waitExposed(view)
        index = view.model().index(2, 2)
        view.setCurrentIndex(index)
        view.edit(index)
        qtbot.wait(20)
        editor = view.indexWidget(index)
        QTest.keyClicks(editor, "=SUM(Pri")
        popup = editor.findChild(QCompleter).popup()
        qtbot.waitUntil(popup.isVisible)
        QTest.keyClick(popup, Qt.Key_Return)
        assert editor.text() == "=SUM(Prices"           # bare: no "("

    def test_ribbon(self, qtbot):
        from flograph.ui.spreadsheet.ribbon import RibbonButton
        bench = SheetWorkbench(SheetModel(json.dumps(DATA)))
        qtbot.addWidget(bench)
        labels = {b.text() for b in bench.ribbon.findChildren(RibbonButton)}
        assert {"Define Name", "Name Manager"} <= labels
