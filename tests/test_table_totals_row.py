"""Excel's Total Row on the Table grid: per-column totals under the grid,
over the rows a filter leaves showing, never in what the node sends on."""
import json

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent

from flograph.core.sheet import merge_linked_sheet, parse_sheet, sheet_to_dict
from flograph.ui.spreadsheet import SheetModel, SheetWorkbench, SpreadsheetView

DATA = {"version": 2,
        "columns": [{"name": "Region"},
                    {"name": "Units"},
                    {"name": "Price", "type": "number",
                     "format": {"kind": "currency", "symbol": "£",
                                "decimals": 2}}],
        "rows": [["North", "10", "2.5"], ["South", "40", "1"],
                 ["North", "", "4"], ["West", "25", "10"]]}


def _view(qtbot):
    model = SheetModel(json.dumps(DATA))
    view = SpreadsheetView()
    model.setParent(view)
    view.setModel(model)
    qtbot.addWidget(view)
    return view, model


class TestModel:
    def test_turning_on_sums_the_last_number_column(self, qtbot):
        _view_, model = _view(qtbot)
        model.set_show_totals(True)
        assert model.show_totals
        assert model.column_total(2) == "sum"
        assert model.total_text(2) == "£17.50"     # in the column's format

    @pytest.mark.parametrize("how,want", [
        ("sum", "75"), ("average", "25"), ("count", "3"), ("rows", "4"),
        ("min", "10"), ("max", "40"), ("distinct", "3"),
    ])
    def test_aggregations(self, qtbot, how, want):
        _view_, model = _view(qtbot)
        model.set_column_total([1], how)
        assert model.show_totals                   # a total turns it on
        assert model.total_text(1) == want

    def test_a_count_is_not_money(self, qtbot):
        _view_, model = _view(qtbot)
        model.set_column_total([2], "count")
        assert model.total_text(2) == "4"

    def test_only_the_rows_a_filter_shows(self, qtbot):
        view, model = _view(qtbot)
        model.set_column_total([1], "sum")
        view.set_column_filter(0, {"North"})
        bar = view.totals_bar()
        qtbot.addWidget(bar)
        assert model.total_text(1, bar._visible_rows()) == "10"

    def test_saved_with_the_sheet_and_kept_by_a_linked_refresh(self, qtbot):
        _view_, model = _view(qtbot)
        model.set_column_total([1], "average")
        data = model.sheet_dict()
        assert data["totals"] is True
        assert data["columns"][1]["total"] == "average"
        again = parse_sheet(data)
        assert again.show_totals and again.columns[1].total == "average"
        merged = merge_linked_sheet(parse_sheet(DATA), again)
        assert merged.show_totals and merged.columns[1].total == "average"

    def test_not_in_what_the_node_sends_on(self):
        from flograph.core import NodeRegistry, compile_run
        from tests.conftest import FakeContext
        reg = NodeRegistry()
        reg.load_builtins()
        spec = reg.get("flograph.io.table")
        run = compile_run(spec.source, "t")
        params = spec.default_params()
        data = dict(DATA, totals=True)
        data["columns"] = [dict(c, total="sum") for c in DATA["columns"]]
        params["data"] = json.dumps(data)
        out = run(FakeContext(params=params))
        assert len(out) == 4


class TestBar:
    def test_the_bar_follows_the_total_row(self, qtbot):
        model = SheetModel(json.dumps(DATA))
        bench = SheetWorkbench(model)
        qtbot.addWidget(bench)
        bench.show()
        assert bench.totals.isHidden()
        bench.view.actions["totals_row"].setChecked(True)
        assert not bench.totals.isHidden()
        assert model.show_totals
        cols = [c for c, _rect in bench.totals.column_rects()]
        assert cols[:3] == [0, 1, 2]

    def test_ctrl_shift_t_toggles_it(self, qtbot):
        view, model = _view(qtbot)
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_T,
                          Qt.ControlModifier | Qt.ShiftModifier)
        view.keyPressEvent(event)
        assert model.show_totals

    def test_clicking_a_total_offers_the_list(self, qtbot, monkeypatch):
        from flograph.ui.spreadsheet import totals
        shown = []
        monkeypatch.setattr("flograph.ui.spreadsheet.menus.exec_menu",
                            lambda menu, w, p: shown.append(menu))
        model = SheetModel(json.dumps(DATA))
        bench = SheetWorkbench(model)
        qtbot.addWidget(bench)
        bench.resize(600, 300)
        bench.show()
        model.set_show_totals(True)
        col, rect = next((c, r) for c, r in bench.totals.column_rects()
                         if c == 1)
        bench.totals.open_menu(col, rect.center())
        texts = [a.text() for a in shown[0].actions()]
        assert "Sum" in texts and "Average" in texts and "None" in texts
        next(a for a in shown[0].actions() if a.text() == "Max").trigger()
        assert model.column_total(1) == "max"
        assert totals.TotalsBar is type(bench.totals)
