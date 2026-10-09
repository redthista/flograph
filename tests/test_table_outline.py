"""Grouped rows — Excel's outline: group rows, fold them away under a −/+
in the margin, nest groups, and have commands leave folded rows alone, as
they do rows a filter hides. Folding is view state: never an edit."""
import json

import pytest
from PySide6.QtCore import QItemSelection, QItemSelectionModel, QPoint, Qt
from PySide6.QtGui import QKeyEvent

from flograph.core.sheet import ColumnSpec, Sheet, parse_sheet, sheet_to_dict
from flograph.core.sheet import outline as o
from flograph.core.sheet.engine import merge_linked_sheet
from flograph.ui.spreadsheet import SheetModel, SpreadsheetView


class TestCore:
    def test_nest_and_reject_overlap(self):
        groups = o.add_group([], 1, 4, 10)
        groups = o.add_group(groups, 2, 3, 10)
        assert [(g.start, g.end) for g in groups] == [(1, 4), (2, 3)]
        assert [o.level_of(groups, g) for g in groups] == [1, 2]
        assert o.depth(groups) == 2
        why = o.add_group(groups, 3, 6, 10)
        assert isinstance(why, str) and "partly overlap" in why
        assert isinstance(o.add_group([], 0, 9, 10), str)   # every row

    def test_same_rows_twice_nests(self):
        groups = o.add_group(o.add_group([], 2, 4, 10), 2, 4, 10)
        assert sorted(o.level_of(groups, g) for g in groups) == [1, 2]

    def test_max_depth(self):
        groups = []
        for i in range(o.MAX_LEVELS):
            groups = o.add_group(groups, 1 + i, 20 - i, 30)
        assert isinstance(o.add_group(groups, 9, 10, 30), str)

    def test_ungroup_takes_one_level(self):
        groups = o.add_group(o.add_group([], 1, 6, 10), 2, 3, 10)
        once = o.remove_group(groups, 2, 2)
        assert [(g.start, g.end) for g in once] == [(1, 6)]
        assert o.remove_group(once, 2, 2) == []

    def test_button_row_and_hidden(self):
        groups = o.add_group([], 2, 4, 10)
        assert o.button_row(groups[0], 10) == 5
        assert o.button_row(o.Group(7, 9), 10) == 6     # runs to the end
        groups[0].collapsed = True
        assert o.hidden_rows(groups) == {2, 3, 4}

    def test_follow_inserts_and_deletes(self):
        groups = [o.Group(2, 4)]
        assert o.after_insert(groups, 3, 2)[0] == o.Group(2, 6)    # inside
        assert o.after_insert(groups, 0, 1)[0] == o.Group(3, 5)    # above
        assert o.after_insert(groups, 5, 1)[0] == o.Group(2, 4)    # below
        assert o.after_remove(groups, 3)[0] == o.Group(2, 3)
        assert o.after_remove([o.Group(2, 2)], 2) == []

    def test_saved_without_folds(self):
        sheet = Sheet(columns=[ColumnSpec("A")],
                      rows=[[str(i)] for i in range(6)])
        sheet.groups = o.add_group([], 1, 3, 6)
        sheet.groups[0].collapsed = True
        data = sheet_to_dict(sheet)
        assert data["groups"] == [[1, 3]]
        back = parse_sheet(json.dumps(data))
        assert back.groups == [o.Group(1, 3)]            # unfolded
        sheet.insert_rows(2)
        assert sheet.groups[0] == o.Group(1, 4, True)
        sheet.remove_rows([0])
        assert (sheet.groups[0].start, sheet.groups[0].end) == (0, 3)

    def test_bad_groups_dropped(self):
        data = {"columns": ["A"], "rows": [["x"]] * 5,
                "groups": [[1, 2], [2, 3], [9, 9], ["a", 1], [0, 4]]}
        assert parse_sheet(data).groups == [o.Group(1, 2)]

    def test_linked_refresh_keeps_groups(self):
        stored = Sheet(columns=[ColumnSpec("A")],
                       rows=[[str(i)] for i in range(6)])
        stored.groups = [o.Group(1, 4)]
        base = Sheet(columns=[ColumnSpec("A")],
                     rows=[[str(i)] for i in range(3)])
        assert merge_linked_sheet(base, stored).groups == [o.Group(1, 2)]


DATA = {"version": 2,
        "columns": [{"name": "Item"}, {"name": "Price", "type": "number"}],
        "rows": [["North", ""], ["Pen", "2"], ["Pad", ""], ["Ink", "4"],
                 ["South", ""], ["Cap", "1"], ["Tape", "3"]]}


@pytest.fixture
def view(qtbot):
    model = SheetModel(json.dumps(DATA))
    view = SpreadsheetView()
    model.setParent(view)
    view.setModel(model)
    qtbot.addWidget(view)
    view.resize(400, 400)
    view.show()
    qtbot.waitExposed(view)
    return view


def _pick_rows(view, r0, r1):
    view.select_rows(list(range(r0, r1 + 1)))


def _hidden(view):
    return [r for r in range(view.model().rowCount()) if view.isRowHidden(r)]


class TestView:
    def test_group_is_an_edit_folding_is_not(self, view):
        model = view.model()
        edits = []
        model.sheet_edited.connect(edits.append)
        _pick_rows(view, 1, 3)
        view.actions["group"].trigger()
        assert len(edits) == 1 and edits[0]["groups"] == [[1, 3]]
        view.setCurrentIndex(model.index(2, 0))
        view.actions.refresh()
        view.actions["hide_detail"].trigger()
        assert _hidden(view) == [1, 2, 3]
        assert len(edits) == 1                       # folding: not an edit
        assert view.currentIndex().row() == 4        # onto the button row
        view.actions["show_detail"].trigger()
        assert _hidden(view) == []

    def test_folded_rows_count_as_hidden(self, view):
        model = view.model()
        model.group_rows(1, 3)
        view.fold_all(True)
        view.setCurrentIndex(model.index(0, 0))
        assert view.row_filtered(2)
        # blank prices: rows 0, 2 and 4 — row 2 is folded away
        assert view.select_special("blanks") == 2
        assert (2, 1) not in [(i.row(), i.column()) for i in
                              view.selectionModel().selectedIndexes()]
        assert view.visible_row_count() == 4

    def test_folds_survive_an_edit_elsewhere(self, view):
        model = view.model()
        model.group_rows(1, 3)
        view.fold_all(True)
        model.setData(model.index(5, 1), "9")
        model.set_sheet(model.sheet_dict())          # the param round trip
        assert _hidden(view) == [1, 2, 3]
        model.insert_rows_at(0, 1)                   # a reset: shifts down
        assert _hidden(view) == [2, 3, 4]

    def test_with_a_filter(self, view):
        model = view.model()
        model.group_rows(4, 5)
        view.set_column_filter(0, {"North", "Pen", "South", "Cap", "Tape"})
        view.fold_all(True)
        assert _hidden(view) == [2, 3, 4, 5]
        view.fold_all(False)
        assert _hidden(view) == [2, 3]
        view.clear_filters()
        assert _hidden(view) == []

    def test_gutter_clicks(self, view, qtbot):
        model = view.model()
        model.group_rows(1, 3)
        header = view.verticalHeader()
        assert header.gutter_width() > 0
        x = header._column_x(1)

        def button_y():           # row 4 moves up once the group folds
            return (header.sectionViewportPosition(4)
                    + header.sectionSize(4) // 2)
        qtbot.mouseClick(header.viewport(), Qt.LeftButton,
                         pos=QPoint(x, button_y()))
        assert _hidden(view) == [1, 2, 3]
        qtbot.mouseClick(header.viewport(), Qt.LeftButton,
                         pos=QPoint(x, button_y()))
        assert _hidden(view) == []
        # a click on the bracket folds too, and never selects rows
        y = header.sectionViewportPosition(2) + 5
        qtbot.mouseClick(header.viewport(), Qt.LeftButton, pos=QPoint(x, y))
        assert _hidden(view) == [1, 2, 3]
        assert not view.selectionModel().isRowSelected(2)

    def test_saved_groups_show_on_open(self, qtbot):
        data = dict(DATA, groups=[[1, 3]])
        model = SheetModel(json.dumps(data))
        view = SpreadsheetView()
        model.setParent(view)
        view.setModel(model)
        qtbot.addWidget(view)
        assert view.verticalHeader().gutter_width() > 0

    def test_gutter_grows_with_levels_and_goes(self, view):
        model = view.model()
        header = view.verticalHeader()
        assert header.gutter_width() == 0
        model.group_rows(1, 5)
        one = header.gutter_width()
        model.group_rows(2, 3)
        assert header.gutter_width() > one
        model.clear_outline()
        assert header.gutter_width() == 0

    def test_ungroup_and_errors(self, view):
        model = view.model()
        _pick_rows(view, 1, 3)
        view.group_selected_rows()
        _pick_rows(view, 2, 5)
        view.group_selected_rows()                   # crosses: refused
        assert [(g.start, g.end) for g in model.groups] == [(1, 3)]
        _pick_rows(view, 2, 2)
        view.ungroup_selected_rows()
        assert model.groups == []

    def test_fold_level(self, view):
        model = view.model()
        model.group_rows(1, 5)
        model.group_rows(2, 3)
        view.fold_level(2)
        assert _hidden(view) == [2, 3]
        view.fold_level(1)
        assert _hidden(view) == [1, 2, 3, 4, 5]

    def test_alt_shift_arrows_still_move_columns(self, view):
        # Excel groups on Alt+Shift+arrows; here those keys already move
        # rows and columns, so Group/Ungroup live on the ribbon and menus
        event = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Right,
                          Qt.ShiftModifier | Qt.AltModifier)
        assert view.actions.for_key(event) is view.actions["col_move_right"]

    def test_ribbon_fits(self, qtbot):
        from flograph.ui.spreadsheet import SheetWorkbench
        bench = SheetWorkbench(SheetModel(json.dumps(DATA)))
        qtbot.addWidget(bench)
        stack = bench.ribbon._stacks["full"]
        assert max(stack.widget(i).sizeHint().width()
                   for i in range(stack.count())) <= 1100
