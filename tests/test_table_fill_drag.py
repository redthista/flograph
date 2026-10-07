"""The fill handle (Excel's AutoFill) and dragging rows/columns by their
headers. The gestures are driven with real mouse events at the widgets Qt
delivers them to — calling the handlers would prove nothing about whether
Qt calls them."""
import json

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from flograph.core.sheet.fill import fill_values
from flograph.ui.spreadsheet import SheetModel, SpreadsheetView


class TestFillValues:
    @pytest.mark.parametrize("seed,count,want", [
        (["1", "3"], 3, ["5", "7", "9"]),
        (["5"], 2, ["5", "5"]),                       # a lone number copies
        (["0.5", "1"], 2, ["1.5", "2"]),
        (["2026-10-30"], 3, ["2026-10-31", "2026-11-01", "2026-11-02"]),
        (["2026-01-01", "2026-01-08"], 1, ["2026-01-15"]),
        (["Item 1"], 2, ["Item 2", "Item 3"]),
        (["Q08"], 3, ["Q09", "Q10", "Q11"]),
        (["Mon"], 3, ["Tue", "Wed", "Thu"]),
        (["Friday"], 3, ["Saturday", "Sunday", "Monday"]),
        (["NOV"], 3, ["DEC", "JAN", "FEB"]),
        (["Jan", "Mar"], 2, ["May", "Jul"]),
        (["a", "b"], 3, ["a", "b", "a"]),
        (["", ""], 1, [""]),
    ])
    def test_series(self, seed, count, want):
        assert fill_values(seed, count) == want

    def test_ctrl_makes_a_lone_number_count(self):
        assert fill_values(["7"], 3, series=True) == ["8", "9", "10"]

    def test_formulas_shift_by_distance(self):
        assert fill_values(["=A1*2"], 2) == ["=A2*2", "=A3*2"]
        assert fill_values(["=A1", "=$B$1"], 2) == ["=A3", "=$B$1"]
        assert fill_values(["=A1"], 2, along="col") == ["=B1", "=C1"]

    def test_backwards(self):
        # 3, 4 dragged up: the seed comes reversed (4, 3) and carries on down
        assert fill_values(["4", "3"], 2, backwards=True) == ["2", "1"]
        assert fill_values(["=A5"], 1, backwards=True) == ["=A4"]


def _model(rows, n_cols=2):
    return SheetModel({"version": 2,
                       "columns": [{"name": c} for c in "ABCD"[:n_cols]],
                       "rows": rows})


class TestFillRange:
    def test_down_fills_each_column_from_its_own_seed(self):
        model = _model([["1", "Mon"], ["2", "Tue"], ["", ""], ["", ""]])
        edits = []
        model.sheet_edited.connect(edits.append)
        model.fill_range((0, 0, 1, 1), (0, 0, 3, 1))
        assert model.sheet.rows[2:] == [["3", "Wed"], ["4", "Thu"]]
        assert len(edits) == 1                       # one undo step

    def test_past_the_end_grows_the_grid(self):
        model = _model([["=B1", "1"]])
        model.fill_range((0, 0, 0, 1), (0, 0, 3, 1))
        assert model.rowCount() == 4
        assert [r[0] for r in model.sheet.rows] == ["=B1", "=B2", "=B3",
                                                     "=B4"]

    def test_up_and_left(self):
        model = _model([["", ""], ["", ""], ["3", "x"], ["4", "x"]])
        model.fill_range((2, 0, 3, 0), (0, 0, 3, 0))
        assert [r[0] for r in model.sheet.rows] == ["1", "2", "3", "4"]
        model = _model([["", "5"]])
        model.fill_range((0, 1, 0, 1), (0, 0, 0, 1))
        assert model.sheet.rows[0] == ["5", "5"]


def _view(qtbot, rows, n_cols=2):
    model = _model(rows, n_cols)
    view = SpreadsheetView()
    model.setParent(view)
    view.setModel(model)
    view.resize(500, 400)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    return view, model


def _mouse(widget, kind, pos, buttons=Qt.LeftButton,
           modifiers=Qt.NoModifier):
    button = Qt.LeftButton if kind != QEvent.MouseMove else Qt.NoButton
    event = QMouseEvent(kind, QPointF(pos), QPointF(widget.mapToGlobal(pos)),
                        button, buttons, modifiers)
    QApplication.sendEvent(widget, event)


class TestFillGesture:
    def test_dragging_the_handle_fills(self, qtbot):
        view, model = _view(qtbot, [["1", ""], ["2", ""]] + [["", ""]] * 4)
        view._select_block(0, 0, 1, 0)
        handle = view.fill_handle_rect().center()
        target = view.visualRect(model.index(4, 0)).center()
        viewport = view.viewport()
        _mouse(viewport, QEvent.MouseButtonPress, handle)
        assert view._fill.dragging
        _mouse(viewport, QEvent.MouseMove, target, buttons=Qt.LeftButton)
        assert view._fill.overlay.fill_target == (0, 0, 4, 0)
        _mouse(viewport, QEvent.MouseButtonRelease, target,
               buttons=Qt.NoButton)
        assert [r[0] for r in model.sheet.rows[:5]] == ["1", "2", "3", "4",
                                                         "5"]
        assert not view._fill.dragging
        assert view._selection_rect() == (0, 0, 4, 0)

    def test_escape_cancels_a_fill(self, qtbot):
        from PySide6.QtGui import QKeyEvent
        view, model = _view(qtbot, [["1", ""], ["", ""], ["", ""]])
        view._select_block(0, 0, 0, 0)
        viewport = view.viewport()
        _mouse(viewport, QEvent.MouseButtonPress,
               view.fill_handle_rect().center())
        _mouse(viewport, QEvent.MouseMove,
               view.visualRect(model.index(2, 0)).center(),
               buttons=Qt.LeftButton)
        view.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape,
                                     Qt.NoModifier))
        assert not view._fill.dragging
        assert model.cell_source(2, 0) == ""

    def test_a_press_off_the_handle_is_an_ordinary_click(self, qtbot):
        view, model = _view(qtbot, [["1", ""], ["2", ""]])
        view._select_block(0, 0, 0, 0)
        cell = view.visualRect(model.index(1, 1)).center()
        _mouse(view.viewport(), QEvent.MouseButtonPress, cell)
        assert not view._fill.dragging
        assert view.currentIndex().row() == 1


class TestHeaderMove:
    def test_dragging_a_selected_row_moves_it(self, qtbot):
        view, model = _view(qtbot, [["a", ""], ["b", ""], ["c", ""],
                                    ["d", ""]])
        view.select_rows([0])
        header = view.verticalHeader().viewport()
        x = 5
        start = QPoint(x, view.rowViewportPosition(0) + 5)
        end = QPoint(x, view.rowViewportPosition(3) + view.rowHeight(3) - 3)
        _mouse(header, QEvent.MouseButtonPress, start)
        _mouse(header, QEvent.MouseMove, end, buttons=Qt.LeftButton)
        assert view._fill.overlay.drop_line is not None
        _mouse(header, QEvent.MouseButtonRelease, end, buttons=Qt.NoButton)
        assert [r[0] for r in model.sheet.rows] == ["b", "c", "d", "a"]
        assert view.selected_rows() == [3]
        assert view._fill.overlay.drop_line is None

    def test_dragging_selected_columns_moves_them(self, qtbot):
        view, model = _view(qtbot, [["1", "2", "3"]], n_cols=3)
        view.select_columns([0, 1])
        header = view.horizontalHeader().viewport()
        y = 5
        start = QPoint(view.columnViewportPosition(0) + 5, y)
        end = QPoint(view.columnViewportPosition(2)
                     + view.columnWidth(2) - 3, y)
        _mouse(header, QEvent.MouseButtonPress, start)
        _mouse(header, QEvent.MouseMove, end, buttons=Qt.LeftButton)
        _mouse(header, QEvent.MouseButtonRelease, end, buttons=Qt.NoButton)
        assert model.sheet.column_names() == ["C", "A", "B"]
        assert view.selected_columns() == [1, 2]

    def test_click_on_a_selected_header_without_moving_selects_just_it(
            self, qtbot):
        view, model = _view(qtbot, [["a", ""], ["b", ""], ["c", ""]])
        view.select_rows([0, 1])
        header = view.verticalHeader().viewport()
        pos = QPoint(5, view.rowViewportPosition(1) + 5)
        _mouse(header, QEvent.MouseButtonPress, pos)
        _mouse(header, QEvent.MouseButtonRelease, pos, buttons=Qt.NoButton)
        assert [r[0] for r in model.sheet.rows] == ["a", "b", "c"]
        assert view.selected_rows() == [1]

    def test_dragging_an_unselected_header_still_selects(self, qtbot):
        view, model = _view(qtbot, [["a", ""], ["b", ""], ["c", ""]])
        view.select_rows([0])
        header = view.verticalHeader().viewport()
        _mouse(header, QEvent.MouseButtonPress,
               QPoint(5, view.rowViewportPosition(2) + 5))
        assert [r[0] for r in model.sheet.rows] == ["a", "b", "c"]
        assert view._row_move._press is None
