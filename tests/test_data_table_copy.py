"""Copying out of the read-only data tables.

The node cards, dashboard tiles and inspector all showed data in plain
QTableViews, which Qt gives no copy handling at all — Ctrl+C did nothing and
the column names could not be got out. These cover the shared view that
fixes that, and in particular the two things easy to get wrong: that the
clipboard carries the real values rather than the rounded display, and that
"the whole table" means the whole frame and not just the rows paged in.
"""
import pandas as pd
import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtGui import QGuiApplication

from flograph.ui.data_table import (CONFIRM_ROWS, MAX_COL_WIDTH, MIN_COL_WIDTH,
                                    DataTableView, cell_text, full_row_count,
                                    put_on_clipboard, selection_block,
                                    whole_block)
from flograph.ui.inspector.pandas_model import PAGE_SIZE, PandasModel

FRAME = {"region": ["North", "South", "East"],
         "sales": [1234.5678901234, 99.5, float("nan")],
         "n": [10, 20, 30]}


@pytest.fixture
def view(qtbot):
    table = DataTableView()
    qtbot.addWidget(table)
    table.setModel(PandasModel(pd.DataFrame(FRAME), parent=table))
    return table


def select(view, cells):
    model = view.selectionModel()
    model.clearSelection()
    for row, col in cells:
        model.select(view.model().index(row, col), QItemSelectionModel.Select)


class TestCellText:
    def test_takes_the_real_value_not_the_rounded_display(self, view):
        """The display rounds to six significant figures so a column reads
        cleanly; pasting that into a spreadsheet would lose precision from
        every float in the table."""
        index = view.model().index(0, 1)
        assert index.data(Qt.DisplayRole) == "1234.57"
        assert cell_text(index) == "1234.5678901234"

    def test_missing_goes_out_empty_not_as_nan(self, view):
        index = view.model().index(2, 1)
        assert index.data(Qt.DisplayRole) == "NaN"
        assert cell_text(index) == ""

    def test_a_numpy_float_is_not_copied_as_its_repr(self, view):
        """numpy scalars are float subclasses whose own repr is
        "np.float64(99.5)" — not a number any spreadsheet will take."""
        assert cell_text(view.model().index(1, 1)) == "99.5"

    def test_falls_back_to_the_display_role(self, qtbot):
        from PySide6.QtGui import QStandardItem, QStandardItemModel
        table = DataTableView()
        qtbot.addWidget(table)
        model = QStandardItemModel(1, 1)
        model.setItem(0, 0, QStandardItem("plain"))
        table.setModel(model)
        assert cell_text(model.index(0, 0)) == "plain"


class TestSelectionBlock:
    def test_copies_the_selected_rectangle(self, view):
        select(view, [(1, 0), (1, 1)])
        assert selection_block(view, False) == [["South", "99.5"]]

    def test_headers_are_the_columns_selected(self, view):
        select(view, [(1, 1), (1, 2)])
        assert selection_block(view, True) == [["sales", "n"], ["99.5", "20"]]

    def test_a_gappy_selection_compacts_to_what_was_picked(self, view):
        """Rows 0 and 2 come out adjacent rather than dragging row 1 along
        with them — which is what a spreadsheet does. Cells inside the
        resulting grid that were not selected come out blank."""
        select(view, [(0, 0), (2, 2)])
        assert selection_block(view, False) == [["North", ""], ["", "30"]]

    def test_a_gappy_selection_keeps_the_columns_it_picked(self, view):
        select(view, [(0, 0), (2, 2)])
        assert selection_block(view, True)[0] == ["region", "n"]

    def test_nothing_selected_is_an_empty_block(self, view):
        view.selectionModel().clearSelection()
        assert selection_block(view, True) == []


class TestWholeBlock:
    def test_leads_with_the_column_names(self, view):
        assert whole_block(view, True)[0] == ["region", "sales", "n"]

    def test_carries_every_row(self, view):
        assert len(whole_block(view, True)) == 4

    def test_reaches_past_the_rows_paged_in(self, qtbot):
        """The model loads 500 rows at a time. Copying "the whole table" off
        the view alone would hand back the first page and say nothing."""
        table = DataTableView()
        qtbot.addWidget(table)
        table.setModel(PandasModel(pd.DataFrame({"a": range(1200)}),
                                   parent=table))
        assert table.model().rowCount() == PAGE_SIZE
        assert len(whole_block(table, True)) == 1201
        assert full_row_count(table) == 1200

    def test_a_model_without_a_frame_still_copies(self, qtbot):
        from PySide6.QtGui import QStandardItem, QStandardItemModel
        table = DataTableView()
        qtbot.addWidget(table)
        model = QStandardItemModel(2, 1)
        model.setHorizontalHeaderLabels(["thing"])
        for row in range(2):
            model.setItem(row, 0, QStandardItem(f"v{row}"))
        table.setModel(model)
        assert whole_block(table, True) == [["thing"], ["v0"], ["v1"]]

    def test_no_model_is_no_block(self, qtbot):
        table = DataTableView()
        qtbot.addWidget(table)
        assert whole_block(table, True) == []


class TestClipboard:
    def test_puts_both_flavours_on_at_once(self, view):
        assert put_on_clipboard([["a", "b"], ["1", "2"]])
        data = QGuiApplication.clipboard().mimeData()
        assert data.text() == "a\tb\n1\t2"
        assert "<table>" in data.html() and "<td>1</td>" in data.html()

    def test_an_empty_block_is_not_copied(self, view):
        assert put_on_clipboard([]) is False


class TestCopyActions:
    def test_ctrl_c_on_whole_columns_brings_the_names(self, view):
        """The case the whole thing is for: select the table, paste into
        Excel, get the column names with it."""
        view.selectAll()
        assert view.copy_selection()
        assert QGuiApplication.clipboard().text().startswith("region\tsales\tn\n")

    def test_ctrl_c_on_a_few_cells_does_not(self, view):
        select(view, [(1, 0), (1, 1)])
        assert view.copy_selection()
        assert QGuiApplication.clipboard().text() == "South\t99.5"

    def test_ctrl_c_with_nothing_selected_copies_everything(self, view):
        view.selectionModel().clearSelection()
        assert view.copy_selection()
        text = QGuiApplication.clipboard().text()
        assert text.startswith("region\tsales\tn\n")
        assert len(text.splitlines()) == 4

    def test_copy_with_headers_forces_them_onto_a_partial_selection(self, view):
        select(view, [(1, 1)])
        assert view.copy_selection_with_headers()
        assert QGuiApplication.clipboard().text() == "sales\n99.5"

    def test_copy_all_ignores_the_selection(self, view):
        select(view, [(0, 0)])
        assert view.copy_all()
        assert len(QGuiApplication.clipboard().text().splitlines()) == 4

    def test_a_huge_table_asks_first(self, qtbot, monkeypatch):
        table = DataTableView()
        qtbot.addWidget(table)
        table.setModel(PandasModel(
            pd.DataFrame({"a": range(CONFIRM_ROWS + 1)}), parent=table))
        asked = []
        monkeypatch.setattr(table, "_confirm_large",
                            lambda rows: asked.append(rows) or False)
        assert table.copy_all() is False
        assert asked == [CONFIRM_ROWS + 1]

    def test_an_ordinary_table_does_not_ask(self, view, monkeypatch):
        monkeypatch.setattr(
            view, "_confirm_large",
            lambda rows: pytest.fail("should not have asked"))
        assert view.copy_all()


class TestKeyboard:
    """Ctrl+C is handled in keyPressEvent, not by a QShortcut.

    A QShortcut is the obvious way to do this and silently does not work on
    the table people reach for first: the one on a node card lives inside a
    QGraphicsProxyWidget, and an embedded widget is not in the window focus
    chain Qt matches shortcuts against.
    """

    def test_ctrl_c_copies(self, qtbot, view):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        view.selectAll()
        QGuiApplication.clipboard().clear()
        view.keyPressEvent(
            QKeyEvent(QEvent.KeyPress, Qt.Key_C, Qt.ControlModifier))
        assert QGuiApplication.clipboard().text().startswith("region\tsales\tn")

    def test_ctrl_a_selects_everything(self, qtbot, view):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        view.selectionModel().clearSelection()
        view.keyPressEvent(
            QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.ControlModifier))
        assert view.selectionModel().hasSelection()

    def test_other_keys_are_left_alone(self, qtbot, view):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        QGuiApplication.clipboard().clear()
        view.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Down,
                                     Qt.NoModifier))
        assert QGuiApplication.clipboard().text() == ""

    def test_ctrl_c_works_inside_a_graphics_proxy(self, qtbot):
        """The node-card case, end to end: a table embedded in a scene, sent
        the key the way the canvas sends it."""
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import (QGraphicsProxyWidget, QGraphicsScene,
                                       QGraphicsView, QVBoxLayout, QWidget)

        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        table = DataTableView()
        table.setModel(PandasModel(pd.DataFrame(FRAME), parent=table))
        layout.addWidget(table)

        scene = QGraphicsScene()
        graphics_view = QGraphicsView(scene)
        qtbot.addWidget(graphics_view)
        proxy = QGraphicsProxyWidget()
        proxy.setWidget(host)
        scene.addItem(proxy)
        graphics_view.resize(400, 300)
        graphics_view.show()

        table.selectAll()
        table.setFocus()
        QGuiApplication.clipboard().clear()
        scene.sendEvent(proxy, QKeyEvent(QEvent.KeyPress, Qt.Key_C,
                                         Qt.ControlModifier))
        assert QGuiApplication.clipboard().text().startswith("region\tsales\tn")


class TestMenu:
    def test_offers_the_copy_actions(self, view):
        labels = [a.text() for a in view.build_menu().actions() if a.text()]
        assert labels == ["Copy", "Copy with Column Names",
                          "Copy Whole Table", "Select All"]

    def test_selection_actions_are_off_with_nothing_selected(self, view):
        view.selectionModel().clearSelection()
        actions = {a.text(): a for a in view.build_menu().actions() if a.text()}
        assert not actions["Copy"].isEnabled()
        assert not actions["Copy with Column Names"].isEnabled()
        assert actions["Copy Whole Table"].isEnabled()

    def test_selection_actions_come_on_with_a_selection(self, view):
        select(view, [(0, 0)])
        actions = {a.text(): a for a in view.build_menu().actions() if a.text()}
        assert actions["Copy"].isEnabled()
        assert actions["Copy with Column Names"].isEnabled()


class TestEveryTableIsCopyable:
    """The point of one shared subclass — miss a site and that table is
    silently back to having no copy at all."""

    def test_the_inspector_builds_one(self):
        from flograph.ui.inspector.view_for import view_for
        assert isinstance(view_for(pd.DataFrame(FRAME)), DataTableView)

    def test_a_series_gets_one_too(self):
        from flograph.ui.inspector.view_for import view_for
        assert isinstance(view_for(pd.Series([1, 2, 3])), DataTableView)

    def test_the_node_card_and_tile_use_it(self):
        import inspect

        from flograph.ui.canvas import node_item
        from flograph.ui.dashboard import tile_item
        for module in (node_item, tile_item):
            assert "DataTableView()" in inspect.getsource(module)


class TestColumnFit:
    """R1 — a read-only column is at least as wide as its own name. The
    plain QTableView did no sizing, so every column sat at Qt's 100px
    default and a longer header was clipped."""

    def test_a_long_header_widens_its_column(self, qtbot):
        table = DataTableView()
        qtbot.addWidget(table)
        df = pd.DataFrame({"a_decidedly_long_header_that_needs_room": [1, 2],
                           "x": [1, 2]})
        table.setModel(PandasModel(df, parent=table))
        assert table.columnWidth(0) > table.columnWidth(1)
        assert table.columnWidth(0) > 100   # wider than Qt's old default

    def test_a_narrow_column_still_shows_its_name(self, qtbot):
        table = DataTableView()
        qtbot.addWidget(table)
        table.setModel(PandasModel(pd.DataFrame({"n": [1, 2, 3]}), parent=table))
        assert table.columnWidth(0) >= MIN_COL_WIDTH

    def test_one_huge_value_cannot_run_the_column_off_the_view(self, qtbot):
        table = DataTableView()
        qtbot.addWidget(table)
        df = pd.DataFrame({"c": ["x" * 4000, "y"]})
        table.setModel(PandasModel(df, parent=table))
        assert table.columnWidth(0) == MAX_COL_WIDTH

    def test_an_empty_result_still_fits_its_headers(self, qtbot):
        table = DataTableView()
        qtbot.addWidget(table)
        df = pd.DataFrame({"a_decidedly_long_header_that_needs_room": []})
        table.setModel(PandasModel(df, parent=table))
        assert table.columnWidth(0) > 100

    def test_a_bar_only_column_is_wide_enough_to_read_the_bar(self, qtbot):
        """`units bar blue only` leaves no text to fit to, and a column
        sized to the header alone would make the bar — the entire content
        of the column — a few pixels long."""
        from flograph.core.table_format import parse_rules
        from flograph.ui.data_table import BAR_ONLY_WIDTH

        table = DataTableView()
        qtbot.addWidget(table)
        df = pd.DataFrame({"n": [1, 200]})
        table.setModel(PandasModel(df, parent=table,
                                   rules=parse_rules("n bar blue only")))
        assert table.columnWidth(0) >= BAR_ONLY_WIDTH
