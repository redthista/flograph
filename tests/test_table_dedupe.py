"""Remove Duplicates…: rows that repeat an earlier one on the ticked
columns go, the first of each set stays — compared by what the cells show,
ignoring case and spaces; rows a filter hides are left alone."""
import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox

from flograph.core.sheet.dedupe import duplicate_rows, summary
from flograph.ui.spreadsheet import SheetModel, SpreadsheetView
from flograph.ui.spreadsheet.dedupe_dialog import DedupeDialog

GRID = [["North", "Pen", "2"], ["north ", "Pen", "2"], ["South", "Pen", "2"],
        ["North", "Pad", "2"], ["NORTH", "pen", "2"]]


def _shown(r, c):
    return GRID[r][c]


class TestCore:
    def test_all_columns(self):
        assert duplicate_rows(5, [0, 1, 2], _shown) == [1, 4]

    def test_some_columns(self):
        assert duplicate_rows(5, [0], _shown) == [1, 3, 4]
        assert duplicate_rows(5, [2], _shown) == [1, 2, 3, 4]
        assert duplicate_rows(5, [], _shown) == []

    def test_only_given_rows(self):
        assert duplicate_rows(5, [0], _shown, rows=[2, 3, 4]) == [4]

    def test_summary(self):
        assert summary(0, 4) == "No duplicates — all 4 rows are different."
        assert summary(1, 3) == "1 duplicate row removed; 3 unique rows remain."


DATA = {"version": 2,
        "columns": [{"name": "Region"}, {"name": "Item"},
                    {"name": "Price", "type": "number"}, {"name": "Twice"}],
        "rows": [["North", "Pen", "2", "=C1*2"], ["South", "Pad", "4", "=C2*2"],
                 ["north", "Pen", "2.0", "=C3*2"], ["West", "Ink", "1", "=4/2"],
                 ["South", "Pad", "4", "=C5*2"]],
        "notes": [[3, 0, "keep me"]]}


@pytest.fixture
def view(qtbot):
    model = SheetModel(json.dumps(DATA))
    view = SpreadsheetView()
    model.setParent(view)
    view.setModel(model)
    qtbot.addWidget(view)
    return view


class TestView:
    def test_values_shown_are_compared(self, view):
        # "2" and "2.0" both show 2; =C1*2 and =C3*2 both show 4
        assert view.duplicate_rows([0, 1, 2, 3]) == [2, 4]
        # "Twice" alone: row 4's =4/2 shows 2, not 4 — different
        assert view.duplicate_rows([3]) == [2, 4]

    def test_drop_is_one_edit_and_keeps_the_first(self, view):
        model = view.model()
        edits = []
        model.sheet_edited.connect(edits.append)
        assert view.drop_duplicates([0, 1]) == 2
        assert len(edits) == 1
        assert [r[0] for r in model.sheet.rows] == ["North", "South", "West"]
        assert model.note(2, 0) == "keep me"          # notes follow
        # the kept rows' formulas still point at their own row
        assert model.cell_source(1, 3) == "=C2*2"

    def test_hidden_rows_are_left_alone(self, view):
        view.set_column_filter(0, {"South", "West"})
        assert view.duplicate_rows([0, 1]) == [4]
        view.drop_duplicates([0, 1])
        assert view.model().rowCount() == 4           # "north" survived

    def test_select_them(self, view):
        assert view.select_duplicates([0, 1]) == 2
        rows = {i.row() for i in view.selectionModel().selectedIndexes()}
        assert rows == {2, 4}
        assert view.model().rowCount() == 5           # nothing removed

    def test_action(self, view):
        view.actions.refresh()
        assert view.actions["dedupe"].isEnabled()


class TestDialog:
    def test_all_ticked_by_default_and_live_count(self, view, qtbot):
        view.setCurrentIndex(view.model().index(0, 0))
        dialog = DedupeDialog(view, view.target_columns())
        qtbot.addWidget(dialog)
        assert dialog.chosen_columns() == [0, 1, 2, 3]
        assert "2 duplicate rows (row 3, 5)" in dialog.status.text()
        assert "3 will remain" in dialog.status.text()
        dialog.columns.item(1).setCheckState(Qt.Unchecked)
        dialog.columns.item(2).setCheckState(Qt.Unchecked)
        dialog.columns.item(3).setCheckState(Qt.Unchecked)
        assert dialog.chosen_columns() == [0]
        assert "row 3, 5" in dialog.status.text()
        dialog._tick_all(False)
        assert not dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()
        assert "at least one" in dialog.status.text()

    def test_several_selected_columns_start_ticked(self, view, qtbot):
        dialog = DedupeDialog(view, [0, 1])
        qtbot.addWidget(dialog)
        assert dialog.chosen_columns() == [0, 1]
        dialog.select_btn.click()
        assert dialog.choice == "select"

    def test_filter_warning(self, view, qtbot):
        view.set_column_filter(0, {"South"})
        dialog = DedupeDialog(view, [0])
        qtbot.addWidget(dialog)
        texts = [w.text() for w in dialog.findChildren(type(dialog.status))]
        assert any("hidden rows stay" in t for t in texts)

    def test_ribbon_still_fits(self, qtbot):
        from flograph.ui.spreadsheet import SheetWorkbench
        from flograph.ui.spreadsheet.ribbon import RibbonButton
        bench = SheetWorkbench(SheetModel(json.dumps(DATA)))
        qtbot.addWidget(bench)
        labels = {b.text() for b in bench.ribbon.findChildren(RibbonButton)}
        assert "Remove Duplicates" in labels
        stack = bench.ribbon._stacks["full"]
        widths = [stack.widget(i).sizeHint().width()
                  for i in range(stack.count())]
        assert max(widths) <= 1100, widths
