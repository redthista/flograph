"""Find & Select: Go To, Go To Special and Excel's quick picks (formulas,
constants, blanks, errors, problem cells), plus Ctrl+Enter filling every
selected cell — select the blanks, type once, fill them all."""
import json

import pytest
from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt
from PySide6.QtWidgets import QDialogButtonBox, QLineEdit

from flograph.core.sheet import select as pick
from flograph.core.sheet.values import FormulaError
from flograph.ui.spreadsheet import SheetModel, SpreadsheetView
from flograph.ui.spreadsheet.goto_dialog import GoToDialog, GoToSpecialDialog

GRID = [["1", "=A1*2", "", "x"],
        ["", "=1/0", "TRUE", ""],
        ["hi", '=""', "", "=A1>0"]]
VALUES = [[1.0, 2.0, None, "x"],
          [None, FormulaError("#DIV/0!"), True, None],
          ["hi", "", None, True]]


def _special(kind, types=pick.TYPES, within=None):
    return pick.special_cells(3, 4, lambda r, c: GRID[r][c],
                              lambda r, c: VALUES[r][c], kind, types,
                              within=within)


class TestCore:
    def test_formulas_and_their_types(self):
        assert _special("formulas") == [(0, 1), (1, 1), (2, 1), (2, 3)]
        assert _special("formulas", ["numbers"]) == [(0, 1)]
        assert _special("formulas", ["errors"]) == [(1, 1)]
        assert _special("formulas", ["logicals"]) == [(2, 3)]
        assert _special("formulas", ["text"]) == [(2, 1)]   # "" is text

    def test_constants(self):
        assert _special("constants") == [(0, 0), (0, 3), (1, 2), (2, 0)]
        assert _special("constants", ["text"]) == [(0, 3), (2, 0)]
        assert _special("constants", ["logicals"]) == [(1, 2)]

    def test_blanks_and_errors(self):
        assert _special("blanks") == [(0, 2), (1, 0), (1, 3), (2, 2)]
        assert _special("errors") == [(1, 1)]

    def test_within_a_selection(self):
        assert _special("blanks", within=[(0, 2), (0, 3), (1, 3)]) == [
            (0, 2), (1, 3)]

    def test_hidden_rows_are_passed_over(self):
        found = pick.special_cells(3, 4, lambda r, c: GRID[r][c],
                                   lambda r, c: VALUES[r][c], "blanks",
                                   skip_row=lambda r: r == 1)
        assert found == [(0, 2), (2, 2)]

    def test_current_region_stops_at_empty_rows_and_columns(self):
        grid = ["ab...",
                "a....",
                ".....",
                "...cc",
                "....c"]

        def filled(r, c):
            return grid[r][c] != "."
        assert pick.current_region(5, 5, filled, 0, 0) == (0, 0, 1, 1)
        assert pick.current_region(5, 5, filled, 4, 4) == (3, 3, 4, 4)
        # diagonal neighbours join a region, as in Excel
        diag = ["a..", ".b.", "..c"]
        assert pick.current_region(3, 3, lambda r, c: diag[r][c] != ".",
                                   0, 0) == (0, 0, 2, 2)

    def test_last_cell(self):
        grid = ["a..", "..b", "c.."]
        assert pick.last_cell(3, 3, lambda r, c: grid[r][c] != ".") == (2, 2)
        assert pick.last_cell(2, 2, lambda r, c: False) is None

    @pytest.mark.parametrize("text,want", [
        ("B2", (1, 1, 1, 1)), ("b2", (1, 1, 1, 1)), ("$B$2", (1, 1, 1, 1)),
        ("A1:C2", (0, 0, 1, 2)), ("C2:A1", (0, 0, 1, 2)),
        ("B:C", (0, 1, 4, 2)), ("2:3", (1, 0, 2, 3)), ("4", (3, 0, 3, 3)),
        ("price", (0, 1, 4, 1)), ("Q1", (0, 3, 4, 3)),
    ])
    def test_parse_reference(self, text, want):
        names = ["Item", "Price", "Qty", "Q1"]
        assert pick.parse_reference(text, names, 5, 4) == want

    @pytest.mark.parametrize("text", ["", "Z9", "A99", "9", "1:9", "A:Z",
                                      "what?"])
    def test_parse_reference_explains(self, text):
        found = pick.parse_reference(text, ["Item"], 5, 4)
        assert isinstance(found, str) and found.endswith((".", "name."))

    def test_found_text(self):
        assert pick.found_text("blanks", 0) == "No blank cells found."
        assert pick.found_text("errors", 1) == "1 error selected."
        assert "Ctrl+Enter" in pick.found_text("blanks", 3)


DATA = {"version": 2,
        "columns": [{"name": "Item"}, {"name": "Price", "type": "number"},
                    {"name": "Total"}],
        "rows": [["Pen", "2", "=B1*2"], ["", "abc", "=1/0"],
                 ["Ink", "", "=B3*2"], ["", "4", ""]]}


@pytest.fixture
def view(qtbot):
    model = SheetModel(json.dumps(DATA))
    view = SpreadsheetView()
    model.setParent(view)
    view.setModel(model)
    qtbot.addWidget(view)
    view.resize(500, 300)
    view.show()
    return view


def _selected(view):
    return sorted((i.row(), i.column())
                  for i in view.selectionModel().selectedIndexes())


def _select(view, r0, c0, r1, c1):
    model = view.model()
    view.setCurrentIndex(model.index(r0, c0))
    view.selectionModel().select(
        QItemSelection(model.index(r0, c0), model.index(r1, c1)),
        QItemSelectionModel.ClearAndSelect)


def _open_editor(view, qtbot):
    qtbot.waitExposed(view)
    index = view.currentIndex()
    view.edit(index)
    qtbot.wait(20)
    editor = view.indexWidget(index)
    assert isinstance(editor, QLineEdit)
    return editor


class TestView:
    def test_select_blanks_in_the_whole_table(self, view):
        view.setCurrentIndex(view.model().index(0, 0))
        assert view.select_special("blanks") == 4
        assert _selected(view) == [(1, 0), (2, 1), (3, 0), (3, 2)]
        assert view.currentIndex().row() == 1

    def test_select_inside_the_selection(self, view):
        _select(view, 0, 0, 1, 2)
        assert view.select_special("formulas") == 2
        assert _selected(view) == [(0, 2), (1, 2)]

    def test_errors_and_problems(self, view):
        view.select_special("errors")
        assert _selected(view) == [(1, 2)]
        # one cell selected again (not a bare setCurrentIndex, whose effect
        # on the selection depends on the app's modifier-key state)
        _select(view, 0, 0, 0, 0)
        view.select_special("problems")
        assert (1, 1) in _selected(view)          # "abc" in a number column

    def test_nothing_found_keeps_the_selection(self, view):
        _select(view, 0, 0, 0, 1)
        assert view.select_special("errors") == 0
        assert _selected(view) == [(0, 0), (0, 1)]

    def test_filtered_rows_are_not_picked(self, view):
        view.set_column_filter(0, {"Pen", "Ink"})
        view.setCurrentIndex(view.model().index(0, 0))
        view.select_special("blanks")
        assert _selected(view) == [(2, 1)]

    def test_region_and_last_cell(self, view):
        view.setCurrentIndex(view.model().index(0, 0))
        view.select_special("region")
        assert _selected(view)[0] == (0, 0) and _selected(view)[-1] == (3, 2)
        view.select_special("last")              # last used row × column
        assert _selected(view) == [(3, 2)]

    def test_quick_pick_actions(self, view):
        view.setCurrentIndex(view.model().index(0, 0))
        view.actions["select_formulas"].trigger()
        assert _selected(view) == [(0, 2), (1, 2), (2, 2)]
        assert view.actions["goto"].shortcut().toString() == "Ctrl+G"

    def test_ctrl_enter_fills_every_selected_cell(self, view, qtbot):
        model = view.model()
        view.setCurrentIndex(model.index(0, 0))
        view.select_special("blanks")
        edits = []
        model.sheet_edited.connect(edits.append)
        editor = _open_editor(view, qtbot)
        editor.setText("n/a")
        qtbot.keyClick(editor, Qt.Key_Return, Qt.ControlModifier)
        qtbot.wait(50)                             # Qt commits queued
        assert [model.cell_source(*cell) for cell in
                [(1, 0), (2, 1), (3, 0), (3, 2)]] == ["n/a"] * 4
        assert len(edits) == 1                     # one undo step
        assert view.currentIndex().row() == 1      # stays put, as Excel
        assert len(_selected(view)) == 4

    def test_ctrl_enter_shifts_a_formula_per_cell(self, view, qtbot):
        model = view.model()
        _select(view, 0, 2, 3, 2)
        editor = _open_editor(view, qtbot)
        editor.setText("=B1*3")
        qtbot.keyClick(editor, Qt.Key_Enter, Qt.ControlModifier)
        qtbot.wait(50)                             # Qt commits queued
        assert [model.cell_source(r, 2) for r in range(4)] == [
            "=B1*3", "=B2*3", "=B3*3", "=B4*3"]

    def test_plain_enter_still_moves_down(self, view, qtbot):
        model = view.model()
        _select(view, 0, 0, 1, 0)
        editor = _open_editor(view, qtbot)
        editor.setText("Cap")
        qtbot.keyClick(editor, Qt.Key_Return)
        qtbot.wait(50)                             # Qt commits queued
        assert model.cell_source(0, 0) == "Cap"
        assert model.cell_source(1, 0) == ""
        assert view.currentIndex().row() == 1


class TestDialogs:
    def test_go_to(self, view, qtbot):
        view.setCurrentIndex(view.model().index(1, 1))
        dialog = GoToDialog(view)
        qtbot.addWidget(dialog)
        assert dialog.ref.text() == "B2"
        dialog.ref.setText("A1:B3")
        assert "6 cells" in dialog.status.text().replace("3 × 2", "6")\
            or "3 × 2 cells" in dialog.status.text()
        dialog.ref.setText("nowhere")
        assert not dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()
        dialog.columns.setCurrentRow(2)
        assert dialog.ref.text() == "Total"
        assert dialog.target() == (0, 2, 3, 2)
        view.select_rect(dialog.target())
        assert _selected(view) == [(r, 2) for r in range(4)]

    def test_go_to_special(self, view, qtbot):
        view.setCurrentIndex(view.model().index(0, 0))
        dialog = GoToSpecialDialog(view)
        qtbot.addWidget(dialog)
        assert "whole table" in dialog.scope.text()
        assert dialog.chosen()[0] == "blanks"
        assert not dialog.types_box.isEnabled()
        dialog._kind_buttons["constants"].setChecked(True)
        assert dialog.types_box.isEnabled()
        for box in dialog._type_boxes.values():
            box.setChecked(False)
        assert not dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()
        dialog._type_boxes["text"].setChecked(True)
        kind, types = dialog.chosen()
        view.select_special(kind, types)
        assert _selected(view) == [(0, 0), (1, 1), (2, 0)]

    def test_ribbon_has_find_and_select(self, qtbot):
        from flograph.ui.spreadsheet import SheetWorkbench
        from flograph.ui.spreadsheet.ribbon import RibbonButton
        bench = SheetWorkbench(SheetModel(json.dumps(DATA)))
        qtbot.addWidget(bench)
        labels = {b.text() for b in bench.ribbon.findChildren(RibbonButton)}
        assert "Find && Select" in labels           # && shows one &
