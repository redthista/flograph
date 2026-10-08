"""Data Validation for the Table: per-column limits, required cells, a hint,
a custom message, and Excel's Stop alert that turns a typed value away."""
import datetime as dt
import json

import pytest
from PySide6.QtCore import Qt

from flograph.core.sheet import merge_linked_sheet, parse_sheet, sheet_to_dict
from flograph.core.sheet import validation as rules
from flograph.ui.spreadsheet import SheetModel, SpreadsheetView
from flograph.ui.spreadsheet.validation_dialog import ValidationDialog

TODAY = dt.date(2026, 10, 8)
UNITS = {"kind": "whole", "op": "between", "a": "1", "b": "100"}


class TestCheck:
    @pytest.mark.parametrize("text,ok", [
        ("1", True), ("100", True), ("50", True), ("0", False),
        ("101", False), ("2.5", False), ("abc", False), ("", True),
        ("=A1*2", True),
    ])
    def test_whole_between(self, text, ok):
        assert (rules.check(text, UNITS) is None) == ok

    def test_decimal_greater_than(self):
        rule = {"kind": "number", "op": "gt", "a": "0"}
        assert rules.check("0.01", rule) is None
        assert "breaks the rule" in rules.check("-1", rule)

    def test_not_between(self):
        rule = {"kind": "number", "op": "not_between", "a": "1", "b": "5"}
        assert rules.check("3", rule) is not None
        assert rules.check("6", rule) is None

    def test_dates_and_today(self):
        rule = {"kind": "date", "op": "ge", "a": "today"}
        assert rules.check("2026-10-08", rule, today=TODAY) is None
        assert rules.check("7 Oct 2026", rule, today=TODAY) is not None
        rule = {"kind": "date", "op": "between", "a": "today-7",
                "b": "today+7"}
        assert rules.check("2026-10-15", rule, today=TODAY) is None
        assert rules.check("2026-10-16", rule, today=TODAY) is not None
        assert "not a date" in rules.check("soon", rule, today=TODAY)

    def test_text_length(self):
        rule = {"kind": "length", "op": "le", "a": "3"}
        assert rules.check("abc", rule) is None
        assert rules.check("abcd", rule) is not None

    def test_required_only_in_a_row_with_data(self):
        rule = {"kind": "any", "required": True}
        assert rules.check("", rule, row_has_data=True)
        assert rules.check("", rule, row_has_data=False) is None
        assert rules.check("x", rule) is None

    def test_custom_error(self):
        rule = dict(UNITS, error="Units are 1 to 100.")
        assert rules.check("500", rule) == "Units are 1 to 100."

    def test_half_made_rule_checks_nothing(self):
        assert rules.check("5", {"kind": "whole", "op": "gt", "a": ""}) is None

    def test_clean(self):
        assert rules.clean(None) is None
        assert rules.clean({"kind": "any"}) is None
        assert rules.clean({"kind": "bogus", "required": 1}) == {
            "kind": "any", "required": True}
        assert "b" not in rules.clean({"kind": "whole", "op": "gt",
                                       "a": "1", "b": "9"})

    def test_bound_problem(self):
        assert rules.bound_problem(UNITS) is None
        assert "larger" in rules.bound_problem(dict(UNITS, a="9", b="1"))
        assert "date" in rules.bound_problem({"kind": "date", "op": "gt",
                                              "a": "whenever"})

    @pytest.mark.parametrize("rule,words", [
        (UNITS, "Units must be a whole number between 1 and 100."),
        (dict(UNITS, required=True),
         "Units must be a whole number between 1 and 100, never blank."),
        ({"kind": "date", "op": "gt", "a": "today"},
         "Units must be a date after today."),
        ({"kind": "length", "op": "le", "a": "10"},
         "Units must be text at most 10 characters long."),
        ({"kind": "any", "required": True}, "Units can't be left blank."),
    ])
    def test_describe(self, rule, words):
        assert rules.describe(rule, "Units") == words


class TestPersistence:
    def test_round_trip_and_merge(self):
        data = {"version": 2, "columns": [
            {"name": "Units", "validation": dict(UNITS, stop=True)}],
            "rows": [["5"]]}
        sheet = parse_sheet(json.dumps(data))
        assert sheet.columns[0].validation == dict(UNITS, stop=True)
        assert sheet_to_dict(sheet)["columns"][0]["validation"]["stop"]
        assert sheet.copy().columns[0].validation == dict(UNITS, stop=True)
        base = parse_sheet({"version": 2, "columns": [{"name": "Units"}],
                            "rows": [["7"]]})
        merged = merge_linked_sheet(base, sheet)
        assert merged.columns[0].validation == dict(UNITS, stop=True)

    def test_junk_is_dropped(self):
        sheet = parse_sheet({"version": 2, "columns": [
            {"name": "A", "validation": "nonsense"}], "rows": [["1"]]})
        assert sheet.columns[0].validation is None


def _view(qtbot, rule=None):
    data = {"version": 2,
            "columns": [{"name": "Item"},
                        {"name": "Units", "type": "integer"}],
            "rows": [["a", "5"], ["b", "500"], ["c", ""], ["", ""]]}
    if rule:
        data["columns"][1]["validation"] = rule
    model = SheetModel(json.dumps(data))
    view = SpreadsheetView()
    model.setParent(view)
    view.setModel(model)
    qtbot.addWidget(view)
    return view, model


class TestGrid:
    def test_broken_cells_are_flagged(self, qtbot):
        _v, model = _view(qtbot, dict(UNITS, required=True))
        assert model.cell_problem(0, 1) is None
        assert "breaks the rule" in model.cell_problem(1, 1)
        assert "blank" in model.cell_problem(2, 1)
        assert model.cell_problem(3, 1) is None    # an empty row
        tip = model.data(model.index(1, 1), Qt.ToolTipRole)
        assert "between 1 and 100" in tip
        assert model.data(model.index(1, 1), Qt.BackgroundRole) is not None
        assert model.problem_cells() == [(1, 1), (2, 1)]

    def test_set_rule_is_one_undo_step_and_values_stay(self, qtbot):
        _v, model = _view(qtbot)
        edits = []
        model.sheet_edited.connect(edits.append)
        model.set_column_validation([1], UNITS)
        assert len(edits) == 1
        assert edits[0]["columns"][1]["validation"] == UNITS
        assert model.cell_source(1, 1) == "500"
        model.set_column_validation([1], None)
        assert model.problem_cells() == []

    def test_flag_mode_keeps_the_value(self, qtbot):
        _v, model = _view(qtbot, UNITS)
        assert model.setData(model.index(0, 1), "999", Qt.EditRole)
        assert model.cell_source(0, 1) == "999"

    def test_stop_mode_turns_a_typed_value_away(self, qtbot):
        _v, model = _view(qtbot, dict(UNITS, stop=True))
        refused = []
        model.edit_refused.connect(lambda *a: refused.append(a))
        assert not model.setData(model.index(0, 1), "999", Qt.EditRole)
        assert model.cell_source(0, 1) == "5"
        assert refused and refused[0][:3] == (0, 1, "999")
        assert model.setData(model.index(0, 1), "42", Qt.EditRole)
        # paste is never turned away, as in Excel — it is flagged instead
        model.set_cells((0, 1), [["999"]])
        assert model.cell_source(0, 1) == "999"
        assert model.cell_problem(0, 1)

    def test_next_problem_walks_and_wraps(self, qtbot):
        view, model = _view(qtbot, dict(UNITS, required=True))
        view.setCurrentIndex(model.index(0, 0))
        view.next_problem()
        assert (view.currentIndex().row(), view.currentIndex().column()) \
            == (1, 1)
        view.next_problem()
        assert view.currentIndex().row() == 2
        view.next_problem()
        assert view.currentIndex().row() == 1     # wrapped round

    def test_refusal_reopens_the_editor(self, qtbot):
        view, model = _view(qtbot, dict(UNITS, stop=True))
        view.show()
        qtbot.waitExposed(view)
        index = model.index(0, 1)
        view.setCurrentIndex(index)
        model.setData(index, "999", Qt.EditRole)
        qtbot.wait(20)
        assert view.state() == view.State.EditingState
        assert view.currentIndex() == index

    def test_commands_exist(self, qtbot):
        view, _model = _view(qtbot)
        view.setCurrentIndex(view.model().index(0, 1))
        view.actions.refresh()
        assert view.actions["validation"].isEnabled()
        assert view.actions["next_problem"].isEnabled()


class TestDialog:
    def test_loads_and_returns_the_rule(self, qtbot):
        view, model = _view(qtbot, dict(UNITS, hint="1 to 100"))
        dialog = ValidationDialog(view, [1])
        qtbot.addWidget(dialog)
        assert dialog.chosen() == dict(UNITS, hint="1 to 100")
        assert dialog.summary.text() == ("Units must be a whole number "
                                         "between 1 and 100.")
        assert "1 cell already breaks it" in dialog.status.text()

    def test_bad_bounds_disable_ok(self, qtbot):
        view, _model = _view(qtbot)
        dialog = ValidationDialog(view, [1])
        qtbot.addWidget(dialog)
        dialog.kind.setCurrentIndex(dialog.kind.findData("whole"))
        dialog.a.setText("10")
        dialog.b.setText("1")
        ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
        assert not ok.isEnabled()
        dialog.b.setText("20")
        assert ok.isEnabled()

    def test_one_bound_ops_hide_the_second_box(self, qtbot):
        view, _model = _view(qtbot)
        dialog = ValidationDialog(view, [1])
        qtbot.addWidget(dialog)
        dialog.show()
        dialog.kind.setCurrentIndex(dialog.kind.findData("date"))
        dialog.op.setCurrentIndex(dialog.op.findData("gt"))
        assert not dialog.b.isVisible()
        assert dialog.a_label.text() == "Date"

    def test_clear_rule(self, qtbot, monkeypatch):
        view, model = _view(qtbot, UNITS)
        dialog = ValidationDialog(view, [1])
        qtbot.addWidget(dialog)
        dialog._clear()
        assert dialog.chosen() is None

    def test_the_help_text_is_never_cut_off(self, qtbot):
        view, _model = _view(qtbot)
        dialog = ValidationDialog(view, [0])
        qtbot.addWidget(dialog)
        dialog.show()
        qtbot.waitExposed(dialog)
        for kind in ("any", "date", "length", "any"):
            dialog.kind.setCurrentIndex(dialog.kind.findData(kind))
            qtbot.wait(10)
            label = dialog.kind_help
            assert label.height() >= label.heightForWidth(label.width())
        assert not dialog.op.isVisible()     # no Data row for Any value
