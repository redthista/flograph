"""Number formats: how a Table column's values read — never what they are."""
import json

import pytest
from PySide6.QtCore import Qt

from flograph.core.sheet import parse_sheet, sheet_to_dict
from flograph.core.sheet.numfmt import (clean, describe, format_value_as,
                                        parse_typed, step_decimals)
from flograph.ui.spreadsheet import SheetModel, SpreadsheetView

NUM = {"kind": "number", "decimals": 2, "thousands": True,
       "negative": "minus"}
GBP = {"kind": "currency", "symbol": "£", "decimals": 2, "negative": "minus"}


class TestFormatValue:
    @pytest.mark.parametrize("value,fmt,want", [
        (1234.5678, NUM, ("1,234.57", False)),
        (1234.5, {"kind": "number", "decimals": 0}, ("1235", False)),
        (-1234.5, {**NUM, "negative": "parens"}, ("(1,234.50)", False)),
        (-1234.5, {**NUM, "negative": "red"}, ("-1,234.50", True)),
        (-5, {**NUM, "negative": "red_parens"}, ("(5.00)", True)),
        (1200, GBP, ("£1,200.00", False)),
        (-3.5, GBP, ("-£3.50", False)),
        (0.256, {"kind": "percent", "decimals": 1}, ("25.6%", False)),
        (1234567, {"kind": "scientific", "decimals": 2}, ("1.23E+6", False)),
        ("2026-10-07", {"kind": "date", "pattern": "%-d %b %Y"},
         ("7 Oct 2026", False)),
        ("7/10/2026", {"kind": "date", "pattern": "%Y-%m-%d"},
         ("2026-10-07", False)),
    ])
    def test_reads(self, value, fmt, want):
        assert format_value_as(value, fmt) == want

    def test_a_format_leaves_what_it_cannot_read_alone(self):
        assert format_value_as("abc", NUM) is None
        assert format_value_as(True, NUM) is None
        assert format_value_as(5, None) is None
        assert format_value_as("not a date", {"kind": "date"}) is None

    def test_rounding_to_zero_drops_the_minus(self):
        assert format_value_as(-0.001, NUM) == ("0.00", False)

    def test_clean_rejects_junk(self):
        assert clean({"kind": "bogus"}) is None
        assert clean("x") is None
        assert clean({"kind": "number", "decimals": 99})["decimals"] == 10

    def test_describe(self):
        assert describe(None) == "General"
        assert describe(GBP) == "Currency (-£1,234.57)"


class TestTyping:
    @pytest.mark.parametrize("text,fmt,want", [
        ("£1,200", GBP, "1200"),
        ("-£3.50", GBP, "-3.5"),
        ("(40)", NUM, "-40"),
        ("1,234.5", NUM, "1234.5"),
        ("25%", {"kind": "percent"}, "0.25"),
        ("0.3", {"kind": "percent"}, "0.3"),
        ("hello", NUM, "hello"),
        ("=A1", NUM, "=A1"),
        ("£5", None, "£5"),
    ])
    def test_parse_typed(self, text, fmt, want):
        assert parse_typed(text, fmt) == want


def test_step_decimals_starts_from_what_shows():
    assert step_decimals(None, 1, "3.14")["decimals"] == 3
    assert step_decimals(NUM, -1)["decimals"] == 1
    assert step_decimals({**NUM, "decimals": 0}, -1)["decimals"] == 0


def test_round_trips_with_the_sheet():
    sheet = parse_sheet({"columns": [{"name": "p", "format": GBP},
                                     {"name": "q"}],
                         "rows": [["1", "2"]]})
    assert sheet.columns[0].format["symbol"] == "£"
    data = sheet_to_dict(sheet)
    assert "format" not in data["columns"][1]      # General is not written
    assert sheet_to_dict(parse_sheet(data)) == data


def _model(fmt=None, rows=None, col_type="auto"):
    column = {"name": "v", "type": col_type}
    if fmt:
        column["format"] = fmt
    return SheetModel({"version": 2, "columns": [column],
                       "rows": rows or [["1234.5"], ["-3"], ["=A1*2"]]})


class TestModel:
    def test_display_reads_formatted_value_stays(self, qtbot):
        model = _model({**NUM, "negative": "red"})
        assert model.index(0, 0).data(Qt.DisplayRole) == "1,234.50"
        assert model.index(2, 0).data(Qt.DisplayRole) == "2,469.00"
        assert model.index(0, 0).data(Qt.EditRole) == "1234.5"
        assert model.value_text(0, 0) == "1234.5"
        assert model.index(1, 0).data(Qt.ForegroundRole) is not None

    def test_typing_in_the_format_stores_the_number(self, qtbot):
        model = _model(GBP)
        model.setData(model.index(0, 0), "£2,500")
        assert model.cell_source(0, 0) == "2500"

    def test_set_column_format_is_one_edit(self, qtbot):
        model = SheetModel({"version": 2,
                            "columns": [{"name": "a"}, {"name": "b"}],
                            "rows": [["0.5", "0.25"]]})
        edits = []
        model.sheet_edited.connect(edits.append)
        model.set_column_format([0, 1], {"kind": "percent"})
        assert len(edits) == 1
        assert model.index(0, 1).data(Qt.DisplayRole) == "25%"
        model.set_column_format([0, 1], None)
        assert model.index(0, 1).data(Qt.DisplayRole) == "0.25"

    def test_table_output_is_untouched(self):
        from flograph.core import NodeRegistry, compile_run
        from tests.conftest import FakeContext
        reg = NodeRegistry()
        reg.load_builtins()
        spec = reg.get("flograph.io.table")
        run = compile_run(spec.source, "t")
        params = spec.default_params()
        params["data"] = json.dumps({
            "version": 2,
            "columns": [{"name": "v", "type": "number", "format": GBP}],
            "rows": [["1234.5"]]})
        out = run(FakeContext(params=params))
        assert out["v"].tolist() == [1234.5]


class TestCommands:
    def _view(self, qtbot):
        model = _model()
        view = SpreadsheetView()
        model.setParent(view)
        view.setModel(model)
        qtbot.addWidget(view)
        view.select_columns([0])
        return view, model

    def test_quick_buttons(self, qtbot):
        view, model = self._view(qtbot)
        view.actions["fmt_thousands"].trigger()
        assert model.index(0, 0).data() == "1,234.50"
        view.actions["dec_less"].trigger()
        assert model.index(0, 0).data() == "1,234.5"
        view.actions["fmt_percent"].trigger()
        assert model.column_format(0)["kind"] == "percent"
        view.actions["fmt_general"].trigger()
        assert model.column_format(0) is None

    def test_ctrl_1_reaches_format_cells(self, qtbot):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        view, _model_ = self._view(qtbot)
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_1, Qt.ControlModifier)
        assert view.actions.for_key(event) is view.actions["format_cells"]

    def test_number_format_menu_lists_presets(self, qtbot):
        from flograph.ui.spreadsheet.actions import fill_number_format_menu
        from flograph.ui.spreadsheet.menus import new_menu
        view, model = self._view(qtbot)
        menu = new_menu(view)
        fill_number_format_menu(menu, view)
        texts = [a.text() for a in menu.actions()]
        assert any(t.startswith("Currency") for t in texts)
        number = next(a for a in menu.actions()
                      if a.text().startswith("Number"))
        number.trigger()
        assert model.column_format(0)["kind"] == "number"

    def test_dialog_builds_the_format_shown(self, qtbot):
        from flograph.ui.spreadsheet.numfmt_dialog import FormatCellsDialog
        view, model = self._view(qtbot)
        dialog = FormatCellsDialog(view, [0])
        qtbot.addWidget(dialog)
        dialog.categories.setCurrentRow(2)            # Currency
        dialog.cur_symbol.setCurrentText("€")
        dialog.cur_decimals.setValue(0)
        assert dialog.chosen()["symbol"] == "€"
        assert dialog.sample.text() == "€1,235"
