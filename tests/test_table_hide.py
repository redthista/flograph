"""Hide and Unhide rows and columns — out of sight, still in the table and
still sent on — and the rule underneath it: an edit to only how a Table
looks (a hidden column, a frozen pane, a note) re-runs nothing."""
import json

import pytest
from PySide6.QtCore import QItemSelection, QItemSelectionModel, QPoint, Qt
from PySide6.QtGui import QKeyEvent

from flograph.core.params import ParamSpec
from flograph.core.sheet import ColumnSpec, Sheet, parse_sheet, sheet_to_dict
from flograph.core.sheet.engine import merge_linked_sheet
from flograph.ui.spreadsheet import SheetModel, SpreadsheetView


class TestPresentationParam:
    SPEC = ParamSpec.from_dict({"name": "data", "type": "text",
                                "presentation": ["freeze",
                                                 "columns.*.width"]})

    def test_only_listed_paths_count(self):
        old = json.dumps({"rows": [["1"]], "columns": [{"name": "A"}]})
        moved = json.dumps({"rows": [["1"]], "freeze": {"rows": 1},
                            "columns": [{"name": "A", "width": 90}]})
        edited = json.dumps({"rows": [["2"]], "columns": [{"name": "A"}]})
        assert self.SPEC.only_presentation_changed(old, moved)
        assert not self.SPEC.only_presentation_changed(old, edited)
        assert not self.SPEC.only_presentation_changed(old, "not json")

    def test_a_table_stays_clean_for_a_look_only_edit(self, registry):
        from flograph.core import Graph
        graph = Graph()
        node = graph.add_node(registry.instantiate("flograph.io.table",
                                                   (0, 0)))
        sheet = parse_sheet(node.params["data"])
        graph.mark_clean(node.id)
        sheet.columns[0].hidden = True
        sheet.freeze_rows = 1
        sheet.set_note(0, 0, "hi")
        graph.set_param(node.id, "data", json.dumps(sheet_to_dict(sheet)))
        assert not node.dirty
        sheet.set_cell(0, 0, "changed")
        graph.set_param(node.id, "data", json.dumps(sheet_to_dict(sheet)))
        assert node.dirty


class TestCore:
    def _sheet(self):
        return Sheet(columns=[ColumnSpec("A"), ColumnSpec("B"),
                              ColumnSpec("C")],
                     rows=[[str(i), "", ""] for i in range(5)])

    def test_saved_and_read(self):
        sheet = self._sheet()
        sheet.columns[1].hidden = True
        sheet.hidden_rows = {2, 3}
        data = sheet_to_dict(sheet)
        assert data["hidden_rows"] == [2, 3]
        assert data["columns"][1]["hidden"] is True
        back = parse_sheet(json.dumps(data))
        assert back.hidden_rows == {2, 3} and back.columns[1].hidden
        assert sheet.copy().hidden_rows == {2, 3}

    def test_hidden_rows_follow(self):
        sheet = self._sheet()
        sheet.hidden_rows = {2}
        sheet.insert_rows(0, 2)
        assert sheet.hidden_rows == {4}
        sheet.remove_rows([0])
        assert sheet.hidden_rows == {3}
        sheet.sort_by(0, ascending=False)            # 2 moves to the top
        assert [sheet.rows[r][0] for r in sheet.hidden_rows] == ["2"]
        sheet.remove_columns([0])                    # a column change
        assert len(sheet.hidden_rows) == 1
        sheet.move_columns([0], 1)
        assert len(sheet.hidden_rows) == 1

    def test_hidden_column_moves_with_its_column(self):
        sheet = self._sheet()
        sheet.columns[0].hidden = True
        sheet.move_columns([0], 2)
        assert [c.hidden for c in sheet.columns] == [False, False, True]

    def test_never_every_row_on_read(self):
        data = {"columns": ["A"], "rows": [["1"], ["2"]],
                "hidden_rows": [0, 1]}
        assert parse_sheet(data).hidden_rows == set()

    def test_linked_refresh_keeps_them(self):
        stored = self._sheet()
        stored.columns[1].hidden = True
        stored.hidden_rows = {1, 4}
        base = Sheet(columns=[ColumnSpec("B"), ColumnSpec("A")],
                     rows=[["x", "y"], ["x", "y"], ["x", "y"]])
        merged = merge_linked_sheet(base, stored)
        assert merged.columns[0].hidden and not merged.columns[1].hidden
        assert merged.hidden_rows == {1}


DATA = {"version": 2,
        "columns": [{"name": "A"}, {"name": "B"}, {"name": "C"},
                    {"name": "D"}],
        "rows": [[str(r * 4 + c) for c in range(4)] for r in range(5)]}


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


def _hidden_rows(view):
    return [r for r in range(view.model().rowCount()) if view.isRowHidden(r)]


def _hidden_cols(view):
    return [c for c in range(view.model().columnCount())
            if view.isColumnHidden(c)]


class TestView:
    def test_hide_and_unhide_rows(self, view):
        model = view.model()
        view.select_rows([1, 2])
        edits = []
        model.sheet_edited.connect(edits.append)
        view.actions["row_hide"].trigger()
        assert len(edits) == 1 and edits[0]["hidden_rows"] == [1, 2]
        assert _hidden_rows(view) == [1, 2]
        assert view.row_filtered(1)                  # out of sight
        view.select_rows([0, 3])                     # either side
        view.actions.refresh()
        view.actions["row_unhide"].trigger()
        assert _hidden_rows(view) == []

    def test_unhide_from_a_neighbour(self, view):
        model = view.model()
        model.hide_rows([3, 4])
        view.select_rows([2])
        view.unhide_selected_rows()
        assert model.hidden_rows == set()

    def test_hide_and_unhide_columns(self, view):
        model = view.model()
        view.select_columns([1])
        view.actions["col_hide"].trigger()
        assert _hidden_cols(view) == [1]
        assert model.cell_source(0, 1) == "1"        # still there
        view.select_columns([0, 2])
        view.actions.refresh()
        view.actions["col_unhide"].trigger()
        assert _hidden_cols(view) == []

    def test_not_everything(self, view):
        model = view.model()
        view.select_columns([0, 1, 2, 3])
        view.hide_selected_columns()
        assert _hidden_cols(view) == []
        assert not model.hide_rows(range(5))

    def test_double_click_the_edge_unhides(self, view, qtbot):
        model = view.model()
        model.hide_columns([1, 2])
        assert _hidden_cols(view) == [1, 2]
        view._autosize_from_handle(0)                # the edge after A
        assert _hidden_cols(view) == []
        model.hide_rows([2])
        view._row_handle_double_clicked(1)
        assert _hidden_rows(view) == []

    def test_unhide_all_and_undo_shape(self, view):
        model = view.model()
        model.hide_rows([0])
        model.hide_columns([3])
        before = model.sheet_dict()
        view.actions.refresh()
        view.actions["unhide_all"].trigger()
        assert _hidden_rows(view) == [] and _hidden_cols(view) == []
        model.set_sheet(before)                      # what undo does
        assert _hidden_rows(view) == [0] and _hidden_cols(view) == [3]

    def test_with_frozen_panes(self, view):
        model = view.model()
        model.set_freeze(0, 2)                       # A, B frozen
        model.hide_columns([1, 3])
        panes = view.frozen_panes.panes()
        cols_pane = panes["cols"]
        assert cols_pane.isColumnHidden(1) and not cols_pane.isColumnHidden(0)
        assert view.isColumnHidden(3) and not view.isColumnHidden(2)
        model.unhide_columns()
        assert not cols_pane.isColumnHidden(1)

    @pytest.mark.parametrize("key,mods,name", [
        (Qt.Key_9, Qt.ControlModifier, "row_hide"),
        (Qt.Key_0, Qt.ControlModifier, "col_hide"),
    ])
    def test_keys(self, view, key, mods, name):
        event = QKeyEvent(QKeyEvent.KeyPress, key, mods)
        assert view.actions.for_key(event) is view.actions[name]

    def test_ribbon_fits(self, qtbot):
        from flograph.ui.spreadsheet import SheetWorkbench
        bench = SheetWorkbench(SheetModel(json.dumps(DATA)))
        qtbot.addWidget(bench)
        stack = bench.ribbon._stacks["full"]
        assert max(stack.widget(i).sizeHint().width()
                   for i in range(stack.count())) <= 1100
