"""Show Table click-to-filter: pick a cell, a row or a column on the card and
the `filtered` output is the table narrowed to it — Show Plotly's On click,
for a table.

Three layers: the pick itself (core/table_picks.py, Qt-free), the node's
run, and the gestures on a DataTableView — driven as clicks, not as method
calls, because what matters is what Qt does with a click on a header.
"""
import json

import pandas as pd
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from flograph.core import NodeRegistry, compile_run
from flograph.core.table_picks import (
    Picks, describe, filter_frame, parse_picks, pick_mode)
from tests.conftest import FakeContext


def _frame():
    return pd.DataFrame({
        "region": ["north", "south", "north", "east", "south"],
        "product": ["widget", "widget", "gadget", "widget", "gadget"],
        "units": [10, 20, 30, 40, 50],
    })


# ----------------------------------------------------------------- the pick

class TestPicks:
    def test_blank_and_junk_are_no_pick(self):
        assert not parse_picks("")
        assert not parse_picks("   ")
        assert not parse_picks("{not json")
        assert not parse_picks("42")

    def test_round_trip_keeps_only_what_is_used(self):
        picks = Picks(cells={"region": ["north"]}, rows=["3"])
        text = picks.to_json()
        assert json.loads(text) == {"cells": {"region": ["north"]},
                                    "rows": ["3"]}
        assert parse_picks(text) == picks
        assert Picks().to_json() == ""

    def test_a_bare_list_is_row_labels(self):
        assert parse_picks('[0, 2]') == Picks(rows=["0", "2"])

    def test_values_are_text_and_deduplicated(self):
        picks = parse_picks('{"cells": {"units": [10, "10", 20]}}')
        assert picks.cells == {"units": ["10", "20"]}

    def test_pick_mode_is_nothing_without_the_param(self):
        assert pick_mode({}) == "nothing"
        assert pick_mode({"on_click": "select many"}) == "select many"
        assert pick_mode({"on_click": "bogus"}) == "nothing"


class TestFilter:
    def test_no_pick_is_the_same_table(self):
        df = _frame()
        out, notes = filter_frame(df, "")
        assert out is df and notes == []

    def test_values_in_one_column_add_up(self):
        out, _ = filter_frame(_frame(), {"cells": {"region": ["north",
                                                              "east"]}})
        assert list(out["units"]) == [10, 30, 40]

    def test_columns_narrow_each_other(self):
        out, _ = filter_frame(_frame(), {"cells": {"region": ["north"],
                                                   "product": ["widget"]}})
        assert list(out["units"]) == [10]

    def test_rows_add_to_what_the_cells_match(self):
        out, _ = filter_frame(_frame(), {"cells": {"region": ["north"]},
                                         "rows": ["4"]})
        assert list(out["units"]) == [10, 30, 50]

    def test_rows_alone_keep_by_index_label(self):
        df = _frame().set_index(pd.Index(["a", "b", "c", "d", "e"]))
        out, _ = filter_frame(df, {"rows": ["b", "d"]})
        assert list(out["units"]) == [20, 40]

    def test_columns_keep_columns_and_not_rows(self):
        out, _ = filter_frame(_frame(), {"columns": ["units", "region"]})
        assert list(out.columns) == ["region", "units"]   # table order
        assert len(out) == 5

    def test_numbers_match_as_they_print(self):
        out, _ = filter_frame(_frame(), {"cells": {"units": ["20"]}})
        assert list(out["region"]) == ["south"]

    def test_dates_match_the_whole_column_format(self):
        df = pd.DataFrame({"when": pd.to_datetime(
            ["2024-01-01", "2024-01-02 13:30"], format="mixed")})
        text = df["when"].astype(str).iloc[0]
        out, _ = filter_frame(df, {"cells": {"when": [text]}})
        assert len(out) == 1

    def test_a_missing_column_is_reported_not_raised(self):
        out, notes = filter_frame(_frame(), {"cells": {"nope": ["x"]},
                                             "columns": ["gone"]})
        assert len(out) == 5
        assert any("nope" in n for n in notes)
        assert any("gone" in n for n in notes)

    def test_describe(self):
        text = describe({"cells": {"region": ["north"]}, "rows": ["1", "2"],
                         "columns": ["units"]})
        assert "region = north" in text and "2 rows" in text \
            and "units" in text


# ----------------------------------------------------------------- the node

@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def _run(registry, **params):
    spec = registry.get("flograph.viz.show_table")
    values = spec.default_params()
    values.update(params)
    return compile_run(spec.source, "show-table-picks")(
        FakeContext(params=values), table=_frame())


def test_node_has_on_click_selected_and_a_filtered_output(registry):
    spec = registry.get("flograph.viz.show_table")
    assert [p.name for p in spec.outputs] == ["table", "style", "filtered"]
    assert spec.param("on_click").default == "nothing"
    assert spec.param("selected").type == "string"


def test_filtered_is_the_table_until_on_click_is_on(registry):
    out = _run(registry, selected='{"cells": {"region": ["north"]}}')
    assert out["filtered"] is out["table"]


def test_filtered_follows_the_pick(registry):
    out = _run(registry, on_click="select many",
               selected='{"cells": {"region": ["north"]}}')
    assert list(out["filtered"]["units"]) == [10, 30]
    assert len(out["table"]) == 5            # the card keeps every row


def test_matrix_mode_filters_the_matrix(registry):
    out = _run(registry, on_click="select one", mode="matrix",
               matrix_rows="region", matrix_columns="product",
               matrix_values="units",
               selected='{"cells": {"region": ["north"]}}')
    assert list(out["filtered"]["region"]) == ["north"]


# ------------------------------------------------------------ the gestures

@pytest.fixture
def view(qtbot):
    from flograph.ui.data_table import DataTableView
    from flograph.ui.inspector.pandas_model import styled_model

    widget = DataTableView()
    widget.setModel(styled_model(_frame(), None, parent=widget))
    widget.resize(500, 300)
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    widget.set_pick_mode("select many")
    return widget


def _cell(view, row, col):
    return view.visualRect(view.model().index(row, col)).center()


def _click_cell(qtbot, view, row, col, modifier=Qt.NoModifier):
    QTest.mouseClick(view.viewport(), Qt.LeftButton, modifier,
                     _cell(view, row, col))


def _committed(qtbot, view, gesture):
    with qtbot.waitSignal(view.picks_committed, timeout=2000) as blocker:
        gesture()
    return parse_picks(blocker.args[0])


def _selected_cells(view):
    return sorted((i.row(), i.column())
                  for i in view.selectionModel().selectedIndexes())


def _column_header(view, col):
    header = view.horizontalHeader()
    return QPoint(header.sectionViewportPosition(col)
                  + header.sectionSize(col) // 2, header.height() // 2)


def _row_header(view, row):
    header = view.verticalHeader()
    return QPoint(header.width() // 2, header.sectionViewportPosition(row)
                  + header.sectionSize(row) // 2)


class TestGestures:
    def test_a_plain_table_never_picks(self, qtbot):
        from flograph.ui.data_table import DataTableView
        from flograph.ui.inspector.pandas_model import styled_model

        widget = DataTableView()
        widget.setModel(styled_model(_frame(), None, parent=widget))
        qtbot.addWidget(widget)
        widget.show()
        seen = []
        widget.picks_committed.connect(seen.append)
        _click_cell(qtbot, widget, 0, 0)
        qtbot.wait(400)
        assert seen == []

    def test_clicking_a_cell_picks_its_value_and_shows_every_match(
            self, qtbot, view):
        picks = _committed(qtbot, view, lambda: _click_cell(qtbot, view, 0, 0))
        assert picks == Picks(cells={"region": ["north"]})
        # both north cells light up: the card shows what the filter keeps
        assert _selected_cells(view) == [(0, 0), (2, 0)]

    def test_ctrl_click_adds_and_columns_narrow(self, qtbot, view):
        _committed(qtbot, view, lambda: _click_cell(qtbot, view, 0, 0))
        picks = _committed(qtbot, view, lambda: _click_cell(
            qtbot, view, 0, 1, Qt.ControlModifier))
        assert picks.cells == {"region": ["north"], "product": ["widget"]}

    def test_clicking_the_only_pick_again_clears_it(self, qtbot, view):
        _committed(qtbot, view, lambda: _click_cell(qtbot, view, 0, 0))
        picks = _committed(qtbot, view, lambda: _click_cell(qtbot, view, 2, 0))
        assert not picks
        assert _selected_cells(view) == []

    def test_ctrl_click_takes_one_value_out(self, qtbot, view):
        view.set_picks('{"cells": {"region": ["north", "south"]}}')
        picks = _committed(qtbot, view, lambda: _click_cell(
            qtbot, view, 1, 0, Qt.ControlModifier))
        assert picks.cells == {"region": ["north"]}

    def test_a_row_header_picks_the_row(self, qtbot, view):
        picks = _committed(qtbot, view, lambda: QTest.mouseClick(
            view.verticalHeader().viewport(), Qt.LeftButton, Qt.NoModifier,
            _row_header(view, 3)))
        assert picks == Picks(rows=["3"])
        # and a second click on it lets every row through
        picks = _committed(qtbot, view, lambda: QTest.mouseClick(
            view.verticalHeader().viewport(), Qt.LeftButton, Qt.NoModifier,
            _row_header(view, 3)))
        assert not picks

    def test_ctrl_click_on_a_header_picks_the_column_without_sorting(
            self, qtbot, view):
        before = list(view.model().dataframe()["units"])
        picks = _committed(qtbot, view, lambda: QTest.mouseClick(
            view.horizontalHeader().viewport(), Qt.LeftButton,
            Qt.ControlModifier, _column_header(view, 2)))
        assert picks == Picks(columns=["units"])
        qtbot.wait(700)                            # past the sort's timer
        assert list(view.model().dataframe()["units"]) == before

    def test_a_plain_header_click_sorts_and_keeps_the_pick(self, qtbot, view):
        _committed(qtbot, view, lambda: _click_cell(qtbot, view, 1, 0))
        seen = []
        view.picks_committed.connect(seen.append)
        # One click: two in a row from QTest land inside the double-click
        # interval, which the sort cycler rightly reads as "not a sort".
        QTest.mouseClick(view.horizontalHeader().viewport(), Qt.LeftButton,
                         Qt.NoModifier, _column_header(view, 0))
        qtbot.waitUntil(lambda: list(view.model().dataframe()["region"])
                        == ["east", "north", "north", "south", "south"],
                        timeout=2000)
        qtbot.wait(400)
        assert seen == []                        # sorting is not a pick
        # the south cells are highlighted where they now sit
        regions = list(view.model().dataframe()["region"])
        assert _selected_cells(view) == [
            (r, 0) for r, name in enumerate(regions) if name == "south"]

    def test_select_one_keeps_only_the_last_click(self, qtbot, view):
        view.set_pick_mode("select one")
        _committed(qtbot, view, lambda: _click_cell(qtbot, view, 0, 0))
        picks = _committed(qtbot, view, lambda: _click_cell(
            qtbot, view, 0, 1, Qt.ControlModifier))
        assert picks == Picks(cells={"product": ["widget"]})

    def test_select_all_filters_nothing(self, qtbot, view):
        _committed(qtbot, view, lambda: _click_cell(qtbot, view, 0, 0))
        picks = _committed(qtbot, view, view.selectAll)
        assert not picks

    def test_escape_clears(self, qtbot, view):
        _committed(qtbot, view, lambda: _click_cell(qtbot, view, 0, 0))
        picks = _committed(qtbot, view, lambda: QTest.keyClick(
            view, Qt.Key_Escape))
        assert not picks

    def test_a_pick_from_outside_is_shown_not_sent_back(self, qtbot, view):
        seen = []
        view.picks_committed.connect(seen.append)
        view.set_picks('{"rows": ["1"], "columns": ["units"]}')
        qtbot.wait(400)
        assert seen == []
        cells = _selected_cells(view)
        assert (1, 0) in cells and (1, 1) in cells
        assert all((r, 2) in cells for r in range(5))

    def test_the_menu_offers_clear_selection(self, qtbot, view):
        view.set_picks('{"rows": ["1"]}')
        menu = view.build_menu()
        clear = next(a for a in menu.actions()
                     if a.text() == "Clear Selection")
        assert clear.isEnabled()
        menu.deleteLater()


def test_keeps_table_accepts_an_equal_copy_and_rejects_a_change(qtbot):
    from flograph.ui.inspector.pandas_model import keeps_table, styled_model

    df = _frame()
    model = styled_model(df, None)
    assert keeps_table(model, df, None)
    assert keeps_table(model, df.copy(deep=False), None)
    changed = df.copy()
    changed.loc[0, "units"] = 99
    assert not keeps_table(model, changed, None)
    assert not keeps_table(model, df, {"rules": ["units bar blue"]})
    model.deleteLater()


# -------------------------------------------------------------- in the app

def test_a_pick_on_the_card_filters_downstream_and_keeps_the_model(
        qtbot, registry):
    from flograph.ui.mainwindow import MainWindow

    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    source = win.registry.instantiate("flograph.io.table", pos=(-300, 0))
    show = win.registry.instantiate("flograph.viz.show_table", pos=(300, 0))
    win.graph.add_node(source)
    win.graph.add_node(show)
    win.graph.set_param(source.id, "data", json.dumps({
        "columns": ["region", "units"],
        "rows": [["north", "1"], ["south", "2"], ["north", "3"]]}))
    win.graph.set_param(show.id, "on_click", "select many")
    win.graph.connect(source.id, "table", show.id, "table")
    with qtbot.waitSignal(win.engine.run_finished, timeout=20000) as blocker:
        win.engine.run_all()
    assert blocker.args[0]

    view = win.scene.node_items[show.id]._table_viewer_view
    model = view.model()
    assert view.pick_mode() == "select many"
    with qtbot.waitSignal(win.engine.run_finished, timeout=20000) as blocker:
        view._put_picks(Picks(cells={"region": ["north"]}))
    assert blocker.args[0]

    assert parse_picks(show.params["selected"]) == \
        Picks(cells={"region": ["north"]})
    outputs = win.engine.cache.outputs_for(show.id)
    assert list(outputs["filtered"]["region"]) == ["north", "north"]
    assert len(outputs["table"]) == 3
    assert view.model() is model      # same table: nothing was rebuilt
    assert _selected_cells(view) == [(0, 0), (2, 0)]

    # an undo puts the pick back to nothing, on the card too
    win.undo_stack.undo()
    assert show.params["selected"] == ""
    assert _selected_cells(view) == []
    win.undo_stack.clear()
