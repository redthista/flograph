"""Column-picker ergonomics: the menu that stays open while you tick
(ideas.md H1) and the insert-a-column-name button on free-text params
(H2). The plumbing that feeds both is covered in
test_column_suggestions.py; this is about what the picking feels like.
"""
import pandas as pd
import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import (
    QFocusEvent, QKeyEvent, QMouseEvent, QTextCursor, QUndoStack,
)
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
    {"name": "renames", "type": "text", "default": "",
     "insert_columns": "mapping"},
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


def _click_into(text):
    """What clicking into the editor does — offscreen, setFocus() alone
    delivers no focus event, so hand it the one Qt would."""
    text.focusInEvent(QFocusEvent(QEvent.FocusIn))


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

    def test_each_tick_is_its_own_undo(self, panel):
        # the menu stays open, so six ticks in a row is now normal — one
        # Ctrl+Z taking all six back would be a surprise
        panel, graph, node = panel
        menu, _edit = self._built(panel, node, "columns")
        _columns(menu)[0].trigger()
        _columns(menu)[1].trigger()
        assert graph.node(node.id).params["columns"] == "region, units"
        panel._undo_stack.undo()
        assert graph.node(node.id).params["columns"] == "region"
        panel._undo_stack.clear()

    def test_select_all_is_its_own_undo(self, panel):
        panel, graph, node = panel
        menu, _edit = self._built(panel, node, "columns")
        _columns(menu)[0].trigger()
        menu.actions()[0].trigger()          # Select all
        assert graph.node(node.id).params["columns"] == "region, units, revenue"
        panel._undo_stack.undo()
        assert graph.node(node.id).params["columns"] == "region"
        panel._undo_stack.clear()

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

    def _pick(self, panel, name, column, mode="inline"):
        text = panel.findChild(QPlainTextEdit, f"param_{name}")
        menu = QMenu()
        panel._fill_insert_menu(menu, text, self._spec(panel, name), mode)
        next(a for a in menu.actions() if a.text() == column).trigger()
        return text

    @staticmethod
    def _spec(panel, name):
        return next(s for s in panel._graph.node(panel._node_id).spec.params
                    if s.name == name)

    def test_spec_normalises_the_flag_to_a_mode(self):
        def mode(raw):
            spec = {"name": "m", "type": "text"}
            if raw is not None:
                spec["insert_columns"] = raw
            return ParamSpec.from_dict(spec).insert_columns

        assert mode(None) == ""       # absent — no picker
        assert mode(False) == ""
        assert mode(True) == "inline"  # the original spelling still works
        assert mode("inline") == "inline"
        assert mode("mapping") == "mapping"

    def test_spec_rejects_an_unknown_mode(self):
        with pytest.raises(ValueError, match="insert_columns"):
            ParamSpec.from_dict(
                {"name": "m", "type": "text", "insert_columns": "newline"})

    def test_button_only_on_the_flagged_param(self, panel):
        panel, _graph, _node = panel
        assert panel.findChild(QToolButton, "param_mapping_columns") is not None
        assert panel.findChild(QToolButton, "param_renames_columns") is not None
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

    def test_inline_insert_into_an_untouched_box_appends(self, panel):
        # the bug this exists for: a freshly built editor has its caret at
        # position 0, so "insert at the cursor" put the name in front of
        # everything already written the moment the box had content
        panel, _graph, _node = panel
        text = panel.findChild(QPlainTextEdit, "param_mapping")
        text.setPlainText("margin = revenue - cost")
        assert not text.caret_placed  # nothing has clicked into it
        self._pick(panel, "mapping", "region")
        assert text.toPlainText() == "margin = revenue - cost\nregion"

    def test_inline_insert_into_an_untouched_empty_box(self, panel):
        panel, _graph, _node = panel
        text = self._pick(panel, "mapping", "region")
        assert text.toPlainText() == "region"

    def test_focusing_the_box_makes_the_caret_count(self, panel):
        panel, _graph, _node = panel
        text = panel.findChild(QPlainTextEdit, "param_mapping")
        assert not text.caret_placed
        _click_into(text)
        assert text.caret_placed

    def test_inline_insert_lands_at_the_cursor(self, panel):
        panel, _graph, _node = panel
        text = panel.findChild(QPlainTextEdit, "param_mapping")
        text.setPlainText(" = revenue_usd")
        _click_into(text)
        cursor = text.textCursor()
        cursor.setPosition(0)
        text.setTextCursor(cursor)
        assert text.caret_placed
        self._pick(panel, "mapping", "revenue")
        assert text.toPlainText() == "revenue = revenue_usd"

    def test_inline_builds_one_line_from_several_columns(self, panel):
        # `margin = revenue - cost` — the reason inline exists
        panel, _graph, _node = panel
        text = panel.findChild(QPlainTextEdit, "param_mapping")
        text.setPlainText("margin = ")
        _click_into(text)
        cursor = text.textCursor()
        cursor.movePosition(QTextCursor.End)
        text.setTextCursor(cursor)
        self._pick(panel, "mapping", "revenue")
        text.insertPlainText(" - ")
        self._pick(panel, "mapping", "region")
        assert text.toPlainText() == "margin = revenue - region"

    def test_insert_reaches_the_graph(self, panel):
        panel, graph, node = panel
        self._pick(panel, "mapping", "region")
        panel.flush_pending()
        assert graph.node(node.id).params["mapping"] == "region"

    def test_shipped_nodes_pick_the_mode_their_format_needs(self):
        import flograph.nodes.transform.expression as expression
        import flograph.nodes.transform.rename_columns as rename
        # one mapping per line vs several columns in one expression
        for module, name, mode in ((rename, "mapping", "mapping"),
                                   (expression, "expressions", "inline")):
            spec = next(ParamSpec.from_dict(p) for p in module.PARAMS
                        if p["name"] == name)
            assert spec.insert_columns == mode, module.__name__

    def test_wrapped_editor_stays_the_right_height(self, panel):
        panel, _graph, _node = panel
        text = panel.findChild(QPlainTextEdit, "param_mapping")
        host = text.parentWidget()
        # the row sizing in _add_row reads maximumHeight off the widget it is
        # given, so the wrapper has to carry the editor's cap rather than the
        # 16777215 a bare QWidget starts with
        assert host.maximumHeight() == text.maximumHeight()


class TestMappingPicker:
    """H2, mapping mode: the box is one `column = value` per line, so the
    picker is a set of ticks — ticking writes the line, unticking takes it
    away again."""

    @pytest.fixture
    def panel(self, qtbot, table):
        return _panel_for(qtbot, INSERTER, table)

    def _spec(self, panel, name="renames"):
        return next(s for s in panel._graph.node(panel._node_id).spec.params
                    if s.name == name)

    def _menu(self, panel, name="renames"):
        text = panel.findChild(QPlainTextEdit, f"param_{name}")
        menu = _ColumnsMenu()
        panel._fill_insert_menu(menu, text, self._spec(panel, name), "mapping")
        return menu, text

    def _tick(self, panel, column, name="renames"):
        menu, text = self._menu(panel, name)
        next(a for a in menu.actions() if a.text() == column).trigger()
        return text

    def test_entries_are_tickable_and_stay_open(self, panel):
        panel, _graph, _node = panel
        menu, _text = self._menu(panel)
        assert all(a.isCheckable() for a in menu.actions())
        assert all(a.property(_STAYS_OPEN) for a in menu.actions())

    def test_ticking_writes_the_column_and_an_equals(self, panel):
        # "col = " rather than bare "col": the half you have to supply is
        # the new name, so the caret lands where you type it
        panel, _graph, _node = panel
        text = self._tick(panel, "region")
        assert text.toPlainText() == "region = "

    def test_the_caret_is_ready_for_the_new_name(self, panel):
        panel, _graph, _node = panel
        text = self._tick(panel, "region")
        text.insertPlainText("area")
        assert text.toPlainText() == "region = area"

    def test_ticks_stack_up_one_line_each(self, panel):
        panel, _graph, _node = panel
        for column in ("region", "units"):
            text = self._tick(panel, column)
        assert text.toPlainText() == "region = \nunits = "

    def test_unticking_deletes_the_whole_line(self, panel):
        panel, _graph, _node = panel
        text = panel.findChild(QPlainTextEdit, "param_renames")
        text.setPlainText("region = area\nunits = qty\nrevenue = revenue_usd")
        self._tick(panel, "units")
        assert text.toPlainText() == "region = area\nrevenue = revenue_usd"

    def test_unticking_the_only_line_empties_the_box(self, panel):
        panel, _graph, _node = panel
        text = panel.findChild(QPlainTextEdit, "param_renames")
        text.setPlainText("region = area")
        self._tick(panel, "region")
        assert text.toPlainText() == ""

    def test_a_round_trip_leaves_no_trace(self, panel):
        panel, _graph, _node = panel
        text = panel.findChild(QPlainTextEdit, "param_renames")
        text.setPlainText("units = qty")
        self._tick(panel, "region")
        self._tick(panel, "region")
        assert text.toPlainText() == "units = qty"

    def test_ticks_reflect_what_the_box_already_says(self, panel):
        panel, _graph, _node = panel
        text = panel.findChild(QPlainTextEdit, "param_renames")
        text.setPlainText("units = qty\nrevenue = ")
        menu, _text = self._menu(panel)
        checked = {a.text(): a.isChecked() for a in menu.actions()}
        # `revenue = ` counts: a line still being typed is still that
        # column's line, or the tick would flicker as you type the value
        assert checked == {"region": False, "units": True, "revenue": True}

    def test_a_hand_typed_bare_column_counts_as_ticked(self, panel):
        panel, _graph, _node = panel
        text = panel.findChild(QPlainTextEdit, "param_renames")
        text.setPlainText("units")
        menu, _text = self._menu(panel)
        assert next(a for a in menu.actions() if a.text() == "units").isChecked()

    def test_comments_and_blank_lines_survive(self, panel):
        panel, _graph, _node = panel
        text = panel.findChild(QPlainTextEdit, "param_renames")
        text.setPlainText("# the ones finance asked for\nunits = qty")
        self._tick(panel, "region")
        assert text.toPlainText() == (
            "# the ones finance asked for\nunits = qty\nregion = ")
        self._tick(panel, "units")
        assert text.toPlainText() == (
            "# the ones finance asked for\nregion = ")

    def test_a_trailing_blank_line_is_not_doubled(self, panel):
        panel, _graph, _node = panel
        text = panel.findChild(QPlainTextEdit, "param_renames")
        text.setPlainText("units = qty\n")
        self._tick(panel, "region")
        assert text.toPlainText() == "units = qty\nregion = "

    def test_a_tick_reaches_the_graph_in_one_step(self, panel):
        panel, graph, node = panel
        self._tick(panel, "region")
        assert graph.node(node.id).params["renames"] == "region = "
        self._tick(panel, "region")
        assert graph.node(node.id).params["renames"] == ""

    def test_a_tick_is_one_undo(self, panel, qtbot):
        panel, graph, node = panel
        self._tick(panel, "region")
        self._tick(panel, "units")
        assert graph.node(node.id).params["renames"] == "region = \nunits = "
        panel._undo_stack.undo()
        assert graph.node(node.id).params["renames"] == "region = "
        panel._undo_stack.undo()
        assert graph.node(node.id).params["renames"] == ""
        panel._undo_stack.clear()

    def test_inline_mode_is_not_tickable(self, panel):
        panel, _graph, _node = panel
        text = panel.findChild(QPlainTextEdit, "param_mapping")
        menu = QMenu()
        panel._fill_insert_menu(menu, text, self._spec(panel, "mapping"),
                                "inline")
        assert not any(a.isCheckable() for a in menu.actions())
