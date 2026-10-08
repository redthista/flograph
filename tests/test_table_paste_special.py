"""Paste Special…: values or formulas, add/subtract/multiply/divide into
what is there, skip blanks and transpose — Excel's rules, one undo step."""
import json

import pytest
from PySide6.QtCore import QItemSelection, QItemSelectionModel
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from flograph.core.sheet.paste import combine, describe, special_block
from flograph.ui.spreadsheet import SheetModel, SpreadsheetView
from flograph.ui.spreadsheet.paste_dialog import PasteSpecialDialog


def _target(cells):
    return lambda r, c: cells.get((r, c), ("", None))


class TestCombine:
    def test_numbers(self):
        assert combine("add", "10", 10.0, "5") == "15"
        assert combine("subtract", "10", 10.0, "2.5") == "7.5"
        assert combine("multiply", "20", 20.0, "1.1") == "22"
        assert combine("divide", "9", 9.0, "3") == "3"

    def test_blank_counts_as_zero(self):
        assert combine("add", "", None, "5") == "5"
        assert combine("multiply", "", None, "5") is None   # stays blank
        assert combine("divide", "", None, "5") is None
        assert combine("add", "4", 4.0, "") == "4"

    def test_text_on_either_side_leaves_the_cell(self):
        assert combine("add", "North", "North", "5") is None
        assert combine("add", "4", 4.0, "abc") is None
        assert combine("add", "TRUE", True, "1") is None

    def test_formula_stays_live(self):
        assert combine("add", "=A1*2", 6.0, "5") == "=(A1*2)+5"
        assert combine("divide", "=SUM(A1:A3)", 6.0, "2") == "=(SUM(A1:A3))/2"

    def test_dividing_by_zero_shows_the_error(self):
        assert combine("divide", "6", 6.0, "0") == "=6/0"

    def test_dates_move_by_days(self):
        assert combine("add", "2026-01-30", "2026-01-30", "3") == "2026-02-02"
        assert combine("subtract", "2026-03-01", "2026-03-01", "1") \
            == "2026-02-28"
        assert combine("multiply", "2026-03-01", "2026-03-01", "2") is None


class TestSpecialBlock:
    def test_values_only_drops_formulas(self):
        block = special_block(values=[["3", "7"]], sources=[["3", "=A1+4"]],
                              origin=(0, 0), at=(5, 0), target=_target({}),
                              what="values")
        assert block == [["3", "7"]]

    def test_all_shifts_references(self):
        block = special_block(values=[["7"]], sources=[["=A1+4"]],
                              origin=(0, 1), at=(2, 1), target=_target({}))
        assert block == [["=A3+4"]]

    def test_transpose_turns_rows_into_columns(self):
        block = special_block(values=[["a", "b", "c"], ["1", "2", "3"]],
                              at=(0, 0), target=_target({}), transpose=True)
        assert block == [["a", "1"], ["b", "2"], ["c", "3"]]

    def test_transpose_shifts_each_formula_by_its_own_move(self):
        # copied from A1:B1 = [x, =A1]; transposed to D1:D2, =A1 (from B1)
        # lands in D2 — one row down, two columns right
        block = special_block(values=[["x", "x"]], sources=[["x", "=A1"]],
                              origin=(0, 0), at=(0, 3), target=_target({}),
                              transpose=True)
        assert block == [["x"], ["=C2"]]

    def test_skip_blanks_leaves_cells(self):
        block = special_block(values=[["1", "", "3"]], at=(0, 0),
                              target=_target({}), skip_blanks=True)
        assert block == [["1", None, "3"]]

    def test_operation_reads_each_target(self):
        cells = {(0, 0): ("10", 10.0), (1, 0): ("x", "x"),
                 (2, 0): ("=B3", 4.0)}
        block = special_block(values=[["2"], ["2"], ["2"]], at=(0, 0),
                              target=_target(cells), op="multiply")
        assert block == [["20"], [None], ["=(B3)*2"]]

    def test_one_cell_fills_the_selection(self):
        cells = {(r, 0): (str(r + 1), float(r + 1)) for r in range(3)}
        block = special_block(values=[["10"]], at=(0, 0),
                              target=_target(cells), op="add",
                              fill_to=(3, 1))
        assert block == [["11"], ["12"], ["13"]]

    def test_describe(self):
        assert describe("all", "none", False, False, True).startswith(
            "Pastes the copied cells with their formulas")
        assert describe("all", "none", False, False, False).startswith(
            "Pastes what the copied cells show")
        text = describe("values", "multiply", True, True, True)
        assert "Multiplies" in text and "rows turned into columns" in text \
            and "copy was empty" in text


DATA = {"version": 2,
        "columns": [{"name": "Item"}, {"name": "Price", "type": "number"},
                    {"name": "Qty", "type": "number"}],
        "rows": [["Pen", "2", "10"], ["Pad", "5", ""], ["Ink", "", "3"]]}


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
    selection = view.selectionModel()
    selection.clearSelection()
    selection.select(QItemSelection(model.index(r0, c0), model.index(r1, c1)),
                     QItemSelectionModel.Select)


class TestView:
    def test_raise_prices_ten_percent(self, view):
        model = view.model()
        QApplication.clipboard().setText("1.1")
        _select(view, 0, 1, 2, 1)
        assert view.paste_special(op="multiply")
        assert [model.cell_source(r, 1) for r in range(3)] == ["2.2", "5.5",
                                                               ""]

    def test_one_undo_step(self, view):
        model = view.model()
        edits = []
        model.sheet_edited.connect(edits.append)
        QApplication.clipboard().setText("1\n1\n1")
        _select(view, 0, 2, 0, 2)
        view.paste_special(op="add")
        assert [model.cell_source(r, 2) for r in range(3)] == ["11", "1",
                                                               "4"]
        assert len(edits) == 1                     # one edit, one undo step

    def test_skip_blanks_keeps_what_is_under(self, view):
        model = view.model()
        QApplication.clipboard().setText("A\t\tB")
        _select(view, 0, 0, 0, 0)
        view.paste_special(what="values", skip_blanks=True)
        assert [model.cell_source(0, c) for c in range(3)] == ["A", "2", "B"]

    def test_transposed_paste_grows_the_grid(self, view):
        model = view.model()
        _select(view, 0, 0, 0, 2)
        view.copy_selection()
        _select(view, 0, 0, 0, 0)
        view.paste_transposed()
        assert [model.cell_source(r, 0) for r in range(3)] == ["Pen", "2",
                                                               "10"]

    def test_actions_ribbon_and_menu(self, view):
        actions = view.actions
        assert actions["paste_special"].shortcut().toString() == "Ctrl+Alt+V"
        assert {"paste_special", "paste_transpose"} <= set(actions.names())
        QApplication.clipboard().setText("x")
        actions.refresh()
        assert actions["paste_special"].isEnabled()

    def test_ribbon_button(self, qtbot):
        from flograph.ui.spreadsheet import SheetWorkbench
        from flograph.ui.spreadsheet.ribbon import RibbonButton
        bench = SheetWorkbench(SheetModel(json.dumps(DATA)))
        qtbot.addWidget(bench)
        labels = {b.text() for b in bench.ribbon.findChildren(RibbonButton)}
        assert "Paste Special" in labels

    def test_dialog_preview_and_paste(self, view, qtbot):
        model = view.model()
        QApplication.clipboard().setText("1.1")
        _select(view, 0, 1, 2, 1)
        dialog = PasteSpecialDialog(view)
        qtbot.addWidget(dialog)
        assert not dialog.all.isEnabled()          # copied from outside
        assert dialog.values.isChecked()
        dialog._op_buttons["multiply"].setChecked(True)
        assert "Multiplies" in dialog.summary.text()
        assert "3 rows × 1 column" in dialog.where.text()
        assert dialog.preview.rowCount() == 3
        assert dialog.preview.item(0, 0).text() == "2.2"
        assert dialog.preview.item(1, 0).toolTip() == "Was: 5"
        assert dialog.chosen()["op"] == "multiply"
        dialog.buttons.button(QDialogButtonBox.Ok).click()
        view.paste_special(**dialog.chosen())
        assert model.cell_source(0, 1) == "2.2"

    def test_dialog_from_inside_offers_formulas(self, view, qtbot):
        _select(view, 0, 0, 1, 2)
        view.copy_selection()
        _select(view, 2, 0, 2, 0)                 # the last row
        dialog = PasteSpecialDialog(view)
        qtbot.addWidget(dialog)
        assert dialog.all.isEnabled() and dialog.all.isChecked()
        assert "Item, row 3 — the table grows" in dialog.where.text()
        dialog.transpose.setChecked(True)
        assert "3 rows × 2 columns" in dialog.where.text()
