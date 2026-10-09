"""Wrap Text and row heights: long text runs onto more lines and its row
grows to fit; a row border dragged (or Row Height…) sets a height saved
with the table; AutoFit / a double-click on the border puts it back."""
import json

import pytest
from PySide6.QtCore import QItemSelection, QItemSelectionModel

from flograph.core.sheet import ColumnSpec, Sheet, parse_sheet, sheet_to_dict
from flograph.ui.spreadsheet import SheetModel, SpreadsheetView

LONG = ("A note long enough to run well past the edge of a narrow column "
        "and onto several lines")


class TestCore:
    def test_saved_clamped_and_following(self):
        sheet = Sheet(columns=[ColumnSpec("A")],
                      rows=[[str(i)] for i in range(4)])
        sheet.row_heights = {1: 40}
        data = sheet_to_dict(sheet)
        assert data["row_heights"] == [[1, 40]]
        data["row_heights"] += [[2, 5000], [9, 30], ["x", 3]]
        assert parse_sheet(data).row_heights == {1: 40, 2: 600}
        sheet.insert_rows(0)
        assert sheet.row_heights == {2: 40}
        sheet.remove_rows([2])
        assert sheet.row_heights == {}

    def test_wrap_is_a_cell_format(self):
        from flograph.core.sheet.cellfmt import clean
        assert clean({"wrap": True}) == {"wrap": True}


DATA = {"version": 2,
        "columns": [{"name": "Item", "width": 80}, {"name": "Note",
                                                    "width": 80}],
        "rows": [["Pen", LONG], ["Pad", "short"], ["Ink", ""]]}


@pytest.fixture
def view(qtbot):
    model = SheetModel(json.dumps(DATA))
    view = SpreadsheetView()
    model.setParent(view)
    view.setModel(model)
    qtbot.addWidget(view)
    view.resize(400, 300)
    view.show()
    qtbot.waitExposed(view)
    return view


def _select(view, r0, c0, r1, c1):
    model = view.model()
    view.setCurrentIndex(model.index(r0, c0))
    view.selectionModel().select(
        QItemSelection(model.index(r0, c0), model.index(r1, c1)),
        QItemSelectionModel.ClearAndSelect)


class TestWrap:
    def test_wrap_in_a_stretched_column_brings_it_back(self, view, qtbot):
        view.setColumnWidth(1, 600)                  # an earlier fit
        view.model().format_cells([(0, 1)], wrap=True)
        view.autosize_columns([1], persist=False)
        assert view.columnWidth(1) <= 100             # its saved 80, or so

    def test_autofit_leaves_a_wrapped_column_alone(self, view):
        model = view.model()
        view.setColumnWidth(1, 80)
        model.format_cells([(0, 1)], wrap=True)
        view.autosize_columns([1], persist=False)
        assert view.columnWidth(1) < 200          # not stretched to the note

    def test_wrapping_grows_the_row(self, view, qtbot):
        # wrapping keeps the column's width (as Excel's does): narrow it
        # first, as someone would, so the note has somewhere to wrap
        view.setColumnWidth(1, 80)
        default = view.verticalHeader().defaultSectionSize()
        assert view.rowHeight(0) == default
        _select(view, 0, 1, 0, 1)
        view.actions["fmt_wrap"].trigger()
        qtbot.waitUntil(lambda: view.rowHeight(0) > default * 2)
        assert view.rowHeight(1) == default
        view.actions.refresh()
        assert view.actions["fmt_wrap"].isChecked()
        view.actions["fmt_wrap"].trigger()            # off again
        qtbot.waitUntil(lambda: view.rowHeight(0) == default)

    def test_wider_column_shorter_row(self, view, qtbot):
        view.setColumnWidth(1, 80)
        view.model().format_cells([(0, 1)], wrap=True)
        qtbot.waitUntil(lambda: view.rowHeight(0) > 40)
        tall = view.rowHeight(0)
        view.model().set_column_widths({1: 400})     # a drag, once saved
        view.setColumnWidth(1, 400)
        qtbot.waitUntil(lambda: view.rowHeight(0) < tall)


class TestHeights:
    def test_a_drag_is_saved_as_one_edit(self, view, qtbot):
        model = view.model()
        edits = []
        model.sheet_edited.connect(edits.append)
        view.verticalHeader().resizeSection(1, 50)    # what a drag does
        qtbot.waitUntil(lambda: bool(edits))
        assert edits[-1]["row_heights"] == [[1, 50]]
        assert model.row_heights == {1: 50}

    def test_heights_come_back_after_a_reset_and_follow_a_sort(self, view):
        model = view.model()
        model.set_row_heights({2: 60})               # the Ink row
        model.sort_by(0)                             # Ink, Pad, Pen
        assert model.row_heights == {0: 60}
        assert view.rowHeight(0) == 60

    def test_autofit_and_double_click(self, view, qtbot):
        model = view.model()
        default = view.verticalHeader().defaultSectionSize()
        model.set_row_heights({0: 70, 1: 70})
        view.select_rows([0])
        view.actions["row_autofit"].trigger()
        assert model.row_heights == {1: 70}
        assert view.rowHeight(0) == default
        view._row_handle_double_clicked(1)            # the border under row 2
        assert model.row_heights == {}

    def test_manual_height_beats_the_fit(self, view, qtbot):
        model = view.model()
        view.setColumnWidth(1, 80)
        model.format_cells([(0, 1)], wrap=True)
        model.set_row_heights({0: 30})
        qtbot.wait(100)
        assert view.rowHeight(0) == 30

    def test_frozen_panes_take_the_heights(self, view, qtbot):
        model = view.model()
        model.set_freeze(0, 1)
        model.set_row_heights({1: 45})
        pane = view.frozen_panes.panes()["cols"]
        assert pane.rowHeight(1) == 45
        model.set_freeze(1, 1)                       # a frozen row stays put
        assert view.frozen_panes.panes()["corner"].rowHeight(0) > 0

    def test_a_height_is_look_only(self, registry):
        from flograph.core import Graph
        graph = Graph()
        node = graph.add_node(registry.instantiate("flograph.io.table",
                                                   (0, 0)))
        sheet = parse_sheet(node.params["data"])
        graph.mark_clean(node.id)
        sheet.row_heights = {0: 44}
        sheet.set_cell_format(0, 0, {"wrap": True})
        graph.set_param(node.id, "data", json.dumps(sheet_to_dict(sheet)))
        assert not node.dirty

    def test_ribbon_fits(self, qtbot):
        from flograph.ui.spreadsheet import SheetWorkbench
        bench = SheetWorkbench(SheetModel(json.dumps(DATA)))
        qtbot.addWidget(bench)
        stack = bench.ribbon._stacks["full"]
        assert max(stack.widget(i).sizeHint().width()
                   for i in range(stack.count())) <= 1100
