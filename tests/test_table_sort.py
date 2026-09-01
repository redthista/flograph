"""Click-a-header-to-sort for the data tables and the Table-node grid.

Two things under test: the dtype sniffing that lets an object column of
date-text or number-text sort as dates or numbers rather than as strings,
and the asc -> desc -> clear click cycle (kept apart from a rename
double-click by a short timer).
"""
import pandas as pd
import pytest
from PySide6.QtCore import Qt

from flograph.ui.data_table import DataTableView
from flograph.ui.inspector.pandas_model import PandasModel
from flograph.ui.table_sort import HeaderSortCycler, pandas_sort_key


def _column(model, col):
    return [model.data(model.index(r, col), Qt.DisplayRole)
            for r in range(model.rowCount())]


class TestPandasSortKey:
    def test_native_numeric_column_passes_through(self):
        s = pd.Series([3, 1, 2])
        assert pandas_sort_key(s) is s

    def test_object_column_of_number_text_sorts_numerically(self):
        df = pd.DataFrame({"v": ["10", "9", "100", "2"]})
        model = PandasModel(df)
        model.sort(0, Qt.AscendingOrder)
        assert _column(model, 0) == ["2", "9", "10", "100"]

    def test_object_column_of_date_text_sorts_chronologically(self):
        df = pd.DataFrame({"d": ["5 Jan 2024", "12 Mar 2023", "1 Feb 2024"]})
        model = PandasModel(df)
        model.sort(0, Qt.AscendingOrder)
        assert _column(model, 0) == ["12 Mar 2023", "5 Jan 2024", "1 Feb 2024"]

    def test_real_datetime_column_sorts_chronologically(self):
        df = pd.DataFrame({"d": pd.to_datetime(
            ["2024-05-01", "2023-01-01", "2024-01-15"])})
        model = PandasModel(df)
        model.sort(0, Qt.DescendingOrder)
        assert _column(model, 0)[0].startswith("2024-05-01")

    def test_plain_text_sorts_case_insensitively(self):
        df = pd.DataFrame({"t": ["banana", "Apple", "cherry"]})
        model = PandasModel(df)
        model.sort(0, Qt.AscendingOrder)
        assert _column(model, 0) == ["Apple", "banana", "cherry"]

    def test_mixed_object_column_below_threshold_stays_textual(self):
        # only half parse as numbers -> sort as text, "10" < "9" lexically
        df = pd.DataFrame({"v": ["10", "9", "abc", "def"]})
        model = PandasModel(df)
        model.sort(0, Qt.AscendingOrder)
        assert _column(model, 0) == ["10", "9", "abc", "def"]


class TestPandasModelSort:
    def test_clear_restores_original_order(self):
        df = pd.DataFrame({"n": [3, 1, 2], "label": ["c", "a", "b"]})
        model = PandasModel(df)
        model.sort(0, Qt.AscendingOrder)
        assert _column(model, 1) == ["a", "b", "c"]
        model.sort(0, None)
        assert _column(model, 1) == ["c", "a", "b"]

    def test_source_frame_is_not_mutated(self):
        df = pd.DataFrame({"n": [3, 1, 2]})
        model = PandasModel(df)
        model.sort(0, Qt.AscendingOrder)
        assert list(df["n"]) == [3, 1, 2]

    def test_dataframe_accessor_reflects_the_sorted_view(self):
        df = pd.DataFrame({"n": [3, 1, 2]})
        model = PandasModel(df)
        model.sort(0, Qt.AscendingOrder)
        assert list(model.dataframe()["n"]) == [1, 2, 3]

    def test_nan_sorts_last_either_direction(self):
        df = pd.DataFrame({"n": [2.0, float("nan"), 1.0]})
        model = PandasModel(df)
        model.sort(0, Qt.AscendingOrder)
        assert _column(model, 0)[-1] == "NaN"
        model.sort(0, Qt.DescendingOrder)
        assert _column(model, 0)[-1] == "NaN"


class TestHeaderSortCycler:
    def _make(self, qtbot):
        view = DataTableView()
        qtbot.addWidget(view)
        view.setModel(PandasModel(
            pd.DataFrame({"n": [3, 1, 2]}), parent=view))
        return view

    def test_three_clicks_cycle_asc_desc_clear(self, qtbot):
        view = self._make(qtbot)
        modes = []
        view._sort_cycler.sortRequested.connect(
            lambda _c, m: modes.append(m))
        header = view.horizontalHeader()
        for _ in range(3):
            with qtbot.waitSignal(view._sort_cycler.sortRequested,
                                  timeout=2000):
                header.sectionClicked.emit(0)
        assert modes == ["asc", "desc", "clear"]
        assert _column(view.model(), 0) == ["3", "1", "2"]  # back to source

    def test_double_click_suppresses_the_sort(self, qtbot):
        view = self._make(qtbot)
        fired = []
        view._sort_cycler.sortRequested.connect(lambda *_: fired.append(1))
        header = view.horizontalHeader()
        header.sectionClicked.emit(0)
        header.sectionDoubleClicked.emit(0)   # arrives before the timer
        qtbot.wait(400)
        assert fired == []

    def test_switching_column_restarts_at_ascending(self, qtbot):
        view = DataTableView()
        qtbot.addWidget(view)
        view.setModel(PandasModel(
            pd.DataFrame({"a": [2, 1], "b": [1, 2]}), parent=view))
        modes = []
        view._sort_cycler.sortRequested.connect(
            lambda _c, m: modes.append(m))
        header = view.horizontalHeader()
        with qtbot.waitSignal(view._sort_cycler.sortRequested):
            header.sectionClicked.emit(0)
        with qtbot.waitSignal(view._sort_cycler.sortRequested):
            header.sectionClicked.emit(1)
        assert modes == ["asc", "asc"]
