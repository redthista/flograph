"""Column-picker ergonomics: the menu that stays open while you tick
(ideas.md H1) and the insert-a-column-name button on free-text params
(H2). The plumbing that feeds both is covered in
test_column_suggestions.py; this is about what the picking feels like.
"""
import pandas as pd
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QUndoStack
from PySide6.QtWidgets import QLineEdit, QMenu, QPlainTextEdit, QToolButton

from flograph.core import Graph, ParamSpec
from flograph.engine import OutputCache
from flograph.ui.properties.params_panel import (
    _STAYS_OPEN, ParamsPanel, _ColumnsMenu,
)
from tests.conftest import make_node

SOURCE = """
NODE = {
    "label": "Src", "category": "Test",
    "inputs": [], "outputs": [("table", "dataframe")],
}
def run(ctx):
    return None
"""

CONSUMER = """
NODE = {
    "label": "Consumer", "category": "Test",
    "inputs": [("table", "dataframe")],
    "outputs": [("out", "dataframe")],
}
PARAMS = [
    {"name": "columns", "type": "columns", "default": ""},
    {"name": "x", "type": "columns", "default": "", "multi": False},
]
def run(ctx, table):
    return table
"""

INSERTER = """
NODE = {
    "label": "Renamer", "category": "Test",
    "inputs": [("table", "dataframe")],
    "outputs": [("out", "dataframe")],
}
PARAMS = [
    {"name": "mapping", "type": "text", "default": "",
     "insert_columns": True},
    {"name": "plain", "type": "text", "default": ""},
]
def run(ctx, table):
    return table
"""


@pytest.fixture
def table():
    return pd.DataFrame({"region": ["n"], "units": [1], "revenue": [2.0]})


def _panel_for(qtbot, consumer_source, table):
    graph = Graph()
    src = make_node(SOURCE, "test.src")
    node = make_node(consumer_source, "test.consumer")
    graph.add_node(src)
    graph.add_node(node)
    graph.connect(src.id, "table", node.id, "table")
    cache = OutputCache()
    cache.set(src.id, {"table": table}, 0.0)
    panel = ParamsPanel(graph, QUndoStack(), cache=cache)
    qtbot.addWidget(panel)
    panel.set_node(node.id)
    return panel, graph, node


def _columns(menu):
    """The column entries of a picker menu — skipping select all/none and
    the separator after them."""
    return [a for a in menu.actions()
            if not a.isSeparator() and a.data() is not None]


class TestStayOpenMenu:
    """H1: ticking a column leaves the menu up, and select all/none save
    doing it one column at a time."""

    @pytest.fixture
    def panel(self, qtbot, table):
        return _panel_for(qtbot, CONSUMER, table)

    def _spec(self, node, name):
        return next(s for s in node.spec.params if s.name == name)

    def _built(self, panel, node, name, value=""):
        menu, edit = _ColumnsMenu(), QLineEdit(value)
        panel._fill_columns_menu(menu, edit, self._spec(node, name))
        return menu, edit

    def test_multi_menu_offers_select_all_and_none(self, panel):
        panel, _graph, node = panel
        menu, _edit = self._built(panel, node, "columns")
        assert [a.text() for a in menu.actions()[:2]] == [
            "Select all", "Select none"]
        assert menu.actions()[2].isSeparator()
        assert [a.text() for a in _columns(menu)] == [
            "region", "units", "revenue"]

    def test_single_menu_has_no_select_all(self, panel):
        panel, _graph, node = panel
        menu, _edit = self._built(panel, node, "x")
        assert [a.text() for a in menu.actions()] == [
            "region", "units", "revenue"]

    def test_select_all_then_none(self, panel):
        panel, graph, node = panel
        menu, edit = self._built(panel, node, "columns")
        menu.actions()[0].trigger()
        assert edit.text() == "region, units, revenue"
        assert graph.node(node.id).params["columns"] == "region, units, revenue"
        # the menu is still showing, so its ticks had to be updated in place
        assert all(a.isChecked() for a in _columns(menu))
        menu.actions()[1].trigger()
        assert edit.text() == ""
        assert graph.node(node.id).params["columns"] == ""
        assert not any(a.isChecked() for a in _columns(menu))

    def test_select_all_from_a_partial_value(self, panel):
        panel, _graph, node = panel
        menu, edit = self._built(panel, node, "columns", "units")
        menu.actions()[0].trigger()
        assert edit.text() == "region, units, revenue"

    def test_column_actions_are_marked_stay_open(self, panel):
        panel, _graph, node = panel
        multi, _edit = self._built(panel, node, "columns")
        assert all(a.property(_STAYS_OPEN) for a in _columns(multi))
        assert all(a.property(_STAYS_OPEN) for a in multi.actions()[:2])
        # a single-column param is one pick, so closing on it is right
        single, _edit = self._built(panel, node, "x")
        assert not any(a.property(_STAYS_OPEN) for a in single.actions())

    def test_placeholder_row_is_not_stay_open(self, panel):
        panel, _graph, node = panel
        panel._cache = OutputCache()  # nothing upstream has run
        menu, _edit = self._built(panel, node, "columns")
        assert len(menu.actions()) == 1
        assert not menu._stays_open(menu.actions()[0])

    def test_click_on_a_column_does_not_close_the_menu(self, panel, qtbot):
        panel, _graph, node = panel
        menu, edit = self._built(panel, node, "columns")
        qtbot.addWidget(menu)
        menu.popup(QPoint(0, 0))
        try:
            at = menu.actionGeometry(_columns(menu)[0]).center()
            menu.mouseReleaseEvent(QMouseEvent(
                QMouseEvent.MouseButtonRelease, at, menu.mapToGlobal(at),
                Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
            assert edit.text() == "region"
            assert menu.isVisible()
            # ...and a second tick lands without reopening anything
            at = menu.actionGeometry(_columns(menu)[2]).center()
            menu.mouseReleaseEvent(QMouseEvent(
                QMouseEvent.MouseButtonRelease, at, menu.mapToGlobal(at),
                Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
            assert edit.text() == "region, revenue"
            assert menu.isVisible()
        finally:
            menu.close()

    def test_space_ticks_without_closing(self, panel, qtbot):
        panel, _graph, node = panel
        menu, edit = self._built(panel, node, "columns")
        qtbot.addWidget(menu)
        menu.popup(QPoint(0, 0))
        try:
            menu.setActiveAction(_columns(menu)[1])
            menu.keyPressEvent(
                QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Space, Qt.NoModifier))
            assert edit.text() == "units"
            assert menu.isVisible()
        finally:
            menu.close()

    def test_single_select_click_still_closes(self, panel, qtbot):
        # a real press+release, not the synthetic release the tests above
        # use: QMenu only closes on a release it saw the press for, so
        # falling through to super() has to be exercised the whole way
        panel, _graph, node = panel
        menu, edit = self._built(panel, node, "x")
        qtbot.addWidget(menu)
        menu.popup(QPoint(0, 0))
        try:
            at = menu.actionGeometry(menu.actions()[0]).center()
            qtbot.mouseClick(menu, Qt.LeftButton, pos=at)
            assert edit.text() == "region"
            assert not menu.isVisible()
        finally:
            menu.close()

    def test_real_click_on_a_multi_column_keeps_it_open(self, panel, qtbot):
        panel, _graph, node = panel
        menu, edit = self._built(panel, node, "columns")
        qtbot.addWidget(menu)
        menu.popup(QPoint(0, 0))
        try:
            at = menu.actionGeometry(_columns(menu)[0]).center()
            qtbot.mouseClick(menu, Qt.LeftButton, pos=at)
            assert edit.text() == "region"
            assert menu.isVisible()
        finally:
            menu.close()


class TestColumnInserter:
    """H2: a free-text box whose content is *about* columns gets a picker
    that types a name in at the cursor."""

    @pytest.fixture
    def panel(self, qtbot, table):
        return _panel_for(qtbot, INSERTER, table)

    def test_spec_carries_the_flag(self):
        assert ParamSpec.from_dict(
            {"name": "m", "type": "text",
             "insert_columns": True}).insert_columns
        assert not ParamSpec.from_dict(
            {"name": "m", "type": "text"}).insert_columns

    def test_button_only_on_the_flagged_param(self, panel):
        panel, _graph, _node = panel
        assert panel.findChild(QToolButton, "param_mapping_columns") is not None
        assert panel.findChild(QToolButton, "param_plain_columns") is None

    def test_menu_lists_upstream_columns(self, panel):
        panel, _graph, _node = panel
        menu = QMenu()
        panel._fill_insert_menu(
            menu, panel.findChild(QPlainTextEdit, "param_mapping"))
        assert [a.text() for a in menu.actions()] == [
            "region", "units", "revenue"]

    def test_menu_placeholder_without_cache(self, panel):
        panel, _graph, _node = panel
        panel._cache = OutputCache()
        menu = QMenu()
        panel._fill_insert_menu(
            menu, panel.findChild(QPlainTextEdit, "param_mapping"))
        assert len(menu.actions()) == 1
        assert not menu.actions()[0].isEnabled()

    def test_insert_lands_at_the_cursor(self, panel):
        panel, _graph, _node = panel
        text = panel.findChild(QPlainTextEdit, "param_mapping")
        text.setPlainText(" = revenue_usd")
        cursor = text.textCursor()
        cursor.setPosition(0)
        text.setTextCursor(cursor)
        menu = QMenu()
        panel._fill_insert_menu(menu, text)
        next(a for a in menu.actions() if a.text() == "revenue").trigger()
        assert text.toPlainText() == "revenue = revenue_usd"

    def test_insert_reaches_the_graph(self, panel):
        panel, graph, node = panel
        text = panel.findChild(QPlainTextEdit, "param_mapping")
        menu = QMenu()
        panel._fill_insert_menu(menu, text)
        menu.actions()[0].trigger()
        panel.flush_pending()
        assert graph.node(node.id).params["mapping"] == "region"

    def test_wrapped_editor_stays_the_right_height(self, panel):
        panel, _graph, _node = panel
        text = panel.findChild(QPlainTextEdit, "param_mapping")
        host = text.parentWidget()
        # the row sizing in _add_row reads maximumHeight off the widget it is
        # given, so the wrapper has to carry the editor's cap rather than the
        # 16777215 a bare QWidget starts with
        assert host.maximumHeight() == text.maximumHeight()

    def test_shipped_nodes_have_it_on(self):
        import flograph.nodes.transform.expression as expression
        import flograph.nodes.transform.rename_columns as rename
        for module, name in ((rename, "mapping"),
                             (expression, "expressions")):
            spec = next(ParamSpec.from_dict(p) for p in module.PARAMS
                        if p["name"] == name)
            assert spec.insert_columns, module.__name__
