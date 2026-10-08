"""Custom Sort…: Excel's Sort dialog for the Table — several levels, each
breaking the ties of the one above, and a dropdown list's own order."""
import json

from flograph.core.sheet import ColumnSpec, Sheet
from flograph.ui.spreadsheet import SheetModel, SpreadsheetView
from flograph.ui.spreadsheet.sort_dialog import SortDialog, order_choices

DATA = {"version": 2,
        "columns": [{"name": "Region", "choices": ["North", "South", "East",
                                                   "West"]},
                    {"name": "Total", "type": "number"},
                    {"name": "When", "type": "date"}],
        "rows": [["South", "5", "2026-01-02"], ["North", "2", "2026-01-01"],
                 ["East", "9", "2026-01-03"], ["North", "7", ""],
                 ["", "1", "2026-01-05"], ["Mars", "3", "2026-01-04"],
                 ["South", "5", "2025-12-31"]]}


def _sheet(rows, choices=()):
    return Sheet(columns=[ColumnSpec("A", "text", choices=list(choices)),
                          ColumnSpec("B", "number")],
                 rows=[list(r) for r in rows])


def _view(qtbot):
    model = SheetModel(json.dumps(DATA))
    view = SpreadsheetView()
    model.setParent(view)
    view.setModel(model)
    qtbot.addWidget(view)
    return view, model


class TestCore:
    def test_second_level_breaks_ties(self):
        sheet = _sheet([["b", "1"], ["a", "2"], ["b", "3"], ["a", "1"]])
        sheet.sort_levels([(0, True, False), (1, False, False)])
        assert sheet.rows == [["a", "2"], ["a", "1"], ["b", "3"], ["b", "1"]]

    def test_ties_keep_their_order_past_the_last_level(self):
        sheet = _sheet([["a", "x1"], ["b", "x2"], ["a", "x3"]])
        sheet.sort_levels([(0, False, False)])
        assert sheet.rows == [["b", "x2"], ["a", "x1"], ["a", "x3"]]

    def test_dropdown_list_order(self):
        sheet = _sheet([["East"], ["Mars"], [""], ["North"], ["west"]],
                       choices=["North", "South", "East", "West"])
        for row in sheet.rows:
            row.append("")
        sheet.sort_levels([(0, True, True)])
        assert [r[0] for r in sheet.rows] == ["North", "East", "west",
                                              "Mars", ""]
        sheet.sort_levels([(0, False, True)])
        # reversed list, but off-list values and blanks still last
        assert [r[0] for r in sheet.rows] == ["west", "East", "North",
                                              "Mars", ""]

    def test_list_order_without_a_list_is_a_plain_sort(self):
        sheet = _sheet([["b", ""], ["a", ""]])
        sheet.sort_levels([(0, True, True)])
        assert [r[0] for r in sheet.rows] == ["a", "b"]

    def test_bad_columns_are_ignored(self):
        sheet = _sheet([["b", "1"], ["a", "2"]])
        sheet.sort_levels([(9, True, False), (0, True, False)])
        assert [r[0] for r in sheet.rows] == ["a", "b"]


class TestView:
    def test_one_undo_step_and_undo_sort(self, qtbot):
        view, model = _view(qtbot)
        before = [list(r) for r in model.sheet.rows]
        view.sort_with_levels([(0, True, True), (1, False, False),
                               (2, True, False)])
        assert [(r[0], r[1]) for r in model.sheet.rows] == [
            ("North", "7"), ("North", "2"), ("South", "5"), ("South", "5"),
            ("East", "9"), ("Mars", "3"), ("", "1")]
        # the South tie is settled by date, oldest first
        assert [r[2] for r in model.sheet.rows[2:4]] == ["2025-12-31",
                                                          "2026-01-02"]
        assert view.has_active_sort
        view.clear_sort()
        assert model.sheet.rows == before


class TestDialog:
    def test_order_words_follow_the_column_type(self):
        number = order_choices(ColumnSpec("N", "number"))
        assert [e[0] for e in number] == ["Smallest to Largest",
                                          "Largest to Smallest"]
        date = order_choices(ColumnSpec("D", "date"))
        assert date[0][0] == "Oldest to Newest"
        listed = order_choices(ColumnSpec("R", "text",
                                          choices=["N", "S"]))
        assert listed[2] == ("Dropdown list order (N, S)", True, True)

    def test_levels_round_trip_and_editing(self, qtbot):
        _v, model = _view(qtbot)
        dialog = SortDialog(model.sheet.columns, [(0, True, True),
                                                  (1, False, False)])
        qtbot.addWidget(dialog)
        assert dialog.levels() == [(0, True, True), (1, False, False)]
        # Add goes under the selected level, onto a column not yet used
        dialog.select(dialog._levels[0])
        dialog.add_level()
        assert dialog.levels() == [(0, True, True), (2, True, False),
                                   (1, False, False)]
        dialog.move_level(1)
        assert [lvl[0] for lvl in dialog.levels()] == [0, 1, 2]
        dialog.delete_level()
        assert [lvl[0] for lvl in dialog.levels()] == [0, 1]
        assert dialog._levels[0].caption.text() == "Sort by"
        assert dialog._levels[1].caption.text() == "Then by"

    def test_a_column_sorted_twice_is_flagged(self, qtbot):
        _v, model = _view(qtbot)
        dialog = SortDialog(model.sheet.columns, [(1, True, False)])
        qtbot.addWidget(dialog)
        assert dialog.warning.text() == ""
        dialog.copy_level()
        assert "Total is sorted on more than once" in dialog.warning.text()

    def test_cannot_delete_the_last_level(self, qtbot):
        _v, model = _view(qtbot)
        dialog = SortDialog(model.sheet.columns, [(1, True, False)])
        qtbot.addWidget(dialog)
        assert not dialog.delete_button.isEnabled()
        dialog.delete_level()
        assert len(dialog.levels()) == 1

    def test_changing_column_keeps_the_direction(self, qtbot):
        _v, model = _view(qtbot)
        dialog = SortDialog(model.sheet.columns, [(1, False, False)])
        qtbot.addWidget(dialog)
        line = dialog._levels[0]
        line.column.setCurrentIndex(2)
        assert line.level() == (2, False, False)
        assert line.order.currentText() == "Newest to Oldest"

    def test_custom_sort_remembers_levels(self, qtbot, monkeypatch):
        view, model = _view(qtbot)
        seen = []

        def fake_exec(dialog):
            seen.append(dialog.levels())
            dialog._levels[0].set_level(1, False, False)
            return True

        monkeypatch.setattr(SortDialog, "exec", fake_exec)
        view.custom_sort()
        assert [r[1] for r in model.sheet.rows][:2] == ["9", "7"]
        assert view.sort_levels_used == [("Total", False, False)]
        view.custom_sort()
        assert seen[1] == [(1, False, False)]

    def test_the_command_is_on_ribbon_and_menus(self, qtbot):
        view, _model = _view(qtbot)
        action = view.actions["sort_custom"]
        assert action.isEnabled()
        assert "several columns" in action.toolTip()
