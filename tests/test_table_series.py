"""Fill Series…: Excel's Series dialog — linear, growth, dates by day,
weekday, month or year, and AutoFill — with a step and a stop value."""
import json

import pytest
from PySide6.QtCore import QItemSelection, QItemSelectionModel
from PySide6.QtWidgets import QDialogButtonBox

from flograph.core.sheet.series import check, series_values
from flograph.ui.spreadsheet import SheetModel, SpreadsheetView
from flograph.ui.spreadsheet.series_dialog import SeriesDialog


class TestCore:
    def test_linear(self):
        assert series_values("1", 4, "linear", "2") == ["3", "5", "7", "9"]
        assert series_values("1", None, "linear", "2", "8") == ["3", "5",
                                                               "7"]
        assert series_values("10", 3, "linear", "-2.5") == ["7.5", "5",
                                                            "2.5"]
        assert series_values("0.1", 2, "linear", "0.2") == ["0.3", "0.5"]

    def test_growth(self):
        assert series_values("2", None, "growth", "2", "40") == [
            "4", "8", "16", "32"]
        assert series_values("100", 2, "growth", "0.5") == ["50", "25"]

    def test_dates(self):
        assert series_values("2026-01-30", 3, "date", "1", unit="day") == [
            "2026-01-31", "2026-02-01", "2026-02-02"]
        # month-end clamps and doesn't drift: Jan 31 → Feb 28 → Mar 31
        assert series_values("2026-01-31", 2, "date", "1", unit="month") == [
            "2026-02-28", "2026-03-31"]
        assert series_values("2024-02-29", 1, "date", "1", unit="year") == [
            "2025-02-28"]
        # Friday → Monday, Tuesday
        assert series_values("2026-10-09", 2, "date", "1",
                             unit="weekday") == ["2026-10-12", "2026-10-13"]
        assert series_values("2026-01-01", None, "date", "7",
                             "2026-01-31") == ["2026-01-08", "2026-01-15",
                                               "2026-01-22", "2026-01-29"]

    def test_autofill(self):
        assert series_values("Mon", 2, "autofill") == ["Tue", "Wed"]
        assert series_values("Item 9", 1, "autofill") == ["Item 10"]

    @pytest.mark.parametrize("args,bit", [
        (("abc", None, "linear", "1", "5"), "needs a number"),
        (("1", None, "linear", "x", "5"), "step needs"),
        (("1", None, "linear", "1", ""), "give a stop value"),
        (("1", None, "linear", "0", "5"), "never moves"),
        (("1", None, "growth", "1", "5"), "never moves"),
        (("5", 2, "date", "1"), "needs a date"),
        (("2026-01-01", 2, "date", "1.5"), "whole number"),
        (("Mon", None, "autofill"), "selected"),
    ])
    def test_reasons(self, args, bit):
        result = series_values(*args)
        assert isinstance(result, str) and bit in result

    def test_check_ok(self):
        assert check("1", "linear", "1", "") is None


DATA = {"version": 2,
        "columns": [{"name": "N"}, {"name": "When"}, {"name": "Day"}],
        "rows": [["1", "2026-01-31", "Mon"], ["", "", ""], ["", "", ""],
                 ["x", "", ""]]}


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
    view.selectionModel().select(
        QItemSelection(model.index(r0, c0), model.index(r1, c1)),
        QItemSelectionModel.ClearAndSelect)


class TestDialog:
    def test_guesses_the_type_and_previews(self, view, qtbot):
        _select(view, 0, 1, 2, 1)
        dialog = SeriesDialog(view, view._selection_rect())
        qtbot.addWidget(dialog)
        assert dialog.chosen()["kind"] == "date"
        assert dialog.columns.isChecked()
        dialog._unit_buttons["month"].setChecked(True)
        assert "2026-02-28, 2026-03-31" in dialog.preview.text()

    def test_fill_a_range_one_edit(self, view, qtbot):
        model = view.model()
        _select(view, 0, 0, 3, 0)
        dialog = SeriesDialog(view, view._selection_rect())
        qtbot.addWidget(dialog)
        assert dialog.chosen()["kind"] == "linear"
        dialog.step.setText("10")
        edits = []
        model.sheet_edited.connect(edits.append)
        view.write_series(dialog.plan(), True)
        assert len(edits) == 1
        assert [model.cell_source(r, 0) for r in range(4)] == [
            "1", "11", "21", "31"]

    def test_one_cell_grows_to_the_stop(self, view, qtbot):
        model = view.model()
        _select(view, 0, 0, 0, 0)
        dialog = SeriesDialog(view, view._selection_rect())
        qtbot.addWidget(dialog)
        assert not dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()
        assert "stop value" in dialog.preview.text()
        dialog.stop.setText("6")
        view.write_series(dialog.plan(), True)
        assert model.rowCount() == 6
        assert [model.cell_source(r, 0) for r in range(6)] == [
            "1", "2", "3", "4", "5", "6"]

    def test_stop_leaves_the_rest(self, view, qtbot):
        model = view.model()
        _select(view, 0, 0, 3, 0)
        dialog = SeriesDialog(view, view._selection_rect())
        qtbot.addWidget(dialog)
        dialog.stop.setText("2")
        view.write_series(dialog.plan(), True)
        assert [model.cell_source(r, 0) for r in range(4)] == [
            "1", "2", "", "x"]

    def test_autofill_down(self, view, qtbot):
        model = view.model()
        _select(view, 0, 2, 2, 2)
        dialog = SeriesDialog(view, view._selection_rect())
        qtbot.addWidget(dialog)
        assert dialog.chosen()["kind"] == "autofill"
        view.write_series(dialog.plan(), True)
        assert [model.cell_source(r, 2) for r in range(3)] == [
            "Mon", "Tue", "Wed"]

    def test_action_and_ribbon(self, view, qtbot):
        view.setCurrentIndex(view.model().index(0, 0))
        view.actions.refresh()
        assert view.actions["fill_series"].isEnabled()
        from flograph.ui.spreadsheet import SheetWorkbench
        bench = SheetWorkbench(SheetModel(json.dumps(DATA)))
        qtbot.addWidget(bench)
        stack = bench.ribbon._stacks["full"]
        assert max(stack.widget(i).sizeHint().width()
                   for i in range(stack.count())) <= 1100
