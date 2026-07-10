"""Upstream-column introspection and the params-panel column picker."""
import pandas as pd
import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QLineEdit, QMenu

from flopy.core import Graph
from flopy.engine import OutputCache, upstream_columns
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

TWO_INPUTS = """
NODE = {
    "label": "Two", "category": "Test",
    "inputs": [("left", "dataframe"), ("right", "dataframe")],
    "outputs": [("out", "dataframe")],
}
def run(ctx, left, right):
    return left
"""


@pytest.fixture
def wired():
    graph = Graph()
    src = make_node(SOURCE, "test.src")
    consumer = make_node(CONSUMER, "test.consumer")
    graph.add_node(src)
    graph.add_node(consumer)
    graph.connect(src.id, "table", consumer.id, "table")
    cache = OutputCache()
    return graph, cache, src, consumer


@pytest.fixture
def table():
    return pd.DataFrame({"region": ["n"], "units": [1], "revenue": [2.0]})


class TestUpstreamColumns:
    def test_empty_before_any_run(self, wired):
        graph, cache, _src, consumer = wired
        assert upstream_columns(graph, cache, consumer.id) == []

    def test_columns_from_cached_upstream(self, wired, table):
        graph, cache, src, consumer = wired
        cache.set(src.id, {"table": table}, 0.0)
        assert upstream_columns(graph, cache, consumer.id) == [
            "region", "units", "revenue"]

    def test_union_over_two_inputs_dedupes(self, table):
        graph = Graph()
        a = make_node(SOURCE, "test.src")
        b = make_node(SOURCE, "test.src")
        two = make_node(TWO_INPUTS, "test.two")
        for node in (a, b, two):
            graph.add_node(node)
        graph.connect(a.id, "table", two.id, "left")
        graph.connect(b.id, "table", two.id, "right")
        cache = OutputCache()
        cache.set(a.id, {"table": table}, 0.0)
        cache.set(b.id, {"table": pd.DataFrame({"region": [], "price": []})},
                  0.0)
        assert upstream_columns(graph, cache, two.id) == [
            "region", "units", "revenue", "price"]

    def test_non_dataframe_output_ignored(self, wired):
        graph, cache, src, consumer = wired
        cache.set(src.id, {"table": 42}, 0.0)
        assert upstream_columns(graph, cache, consumer.id) == []

    def test_unknown_node(self, wired):
        graph, cache, _src, _consumer = wired
        assert upstream_columns(graph, cache, "nope") == []


class TestColumnPicker:
    @pytest.fixture
    def panel(self, qtbot, wired, table):
        from flopy.ui.properties.params_panel import ParamsPanel
        graph, cache, src, consumer = wired
        cache.set(src.id, {"table": table}, 0.0)
        panel = ParamsPanel(graph, QUndoStack(), cache=cache)
        qtbot.addWidget(panel)
        panel.set_node(consumer.id)
        return panel, graph, consumer

    def _spec(self, consumer, name):
        return next(s for s in consumer.spec.params if s.name == name)

    def test_menu_lists_upstream_columns(self, panel):
        panel, _graph, consumer = panel
        menu, edit = QMenu(), QLineEdit()
        panel._fill_columns_menu(menu, edit, self._spec(consumer, "columns"))
        assert [a.text() for a in menu.actions()] == [
            "region", "units", "revenue"]
        assert all(a.isCheckable() for a in menu.actions())

    def test_menu_placeholder_without_cache(self, panel, wired):
        panel, _graph, consumer = panel
        panel._cache = OutputCache()  # nothing upstream has run
        menu, edit = QMenu(), QLineEdit()
        panel._fill_columns_menu(menu, edit, self._spec(consumer, "columns"))
        assert len(menu.actions()) == 1
        assert not menu.actions()[0].isEnabled()

    def test_multi_pick_toggles_comma_list(self, panel):
        panel, graph, consumer = panel
        spec = self._spec(consumer, "columns")
        edit = QLineEdit()
        panel._pick_column(edit, spec, "region")
        panel._pick_column(edit, spec, "units")
        assert edit.text() == "region, units"
        assert graph.node(consumer.id).params["columns"] == "region, units"
        panel._pick_column(edit, spec, "region")
        assert edit.text() == "units"

    def test_single_pick_replaces(self, panel):
        panel, graph, consumer = panel
        spec = self._spec(consumer, "x")
        assert not spec.multi
        edit = QLineEdit("old")
        panel._pick_column(edit, spec, "region")
        panel._pick_column(edit, spec, "units")
        assert edit.text() == "units"
        assert graph.node(consumer.id).params["x"] == "units"

    def test_checked_state_follows_current_value(self, panel):
        panel, _graph, consumer = panel
        menu, edit = QMenu(), QLineEdit("units, revenue")
        panel._fill_columns_menu(menu, edit, self._spec(consumer, "columns"))
        checked = {a.text(): a.isChecked() for a in menu.actions()}
        assert checked == {"region": False, "units": True, "revenue": True}
