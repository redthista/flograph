"""Conditional formatting on the Table grid: Show Table's rules, evaluated
and painted by the same engine, written from the node's `rules` param or
the ribbon's presets."""
import json

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.spreadsheet import SheetModel, SpreadsheetView
from flograph.ui.spreadsheet import cond_format
from flograph.ui.table_delegate import (BAR_ROLE, DECOR_ROLE,
                                        ConditionalFormatDelegate)

DATA = {"version": 2,
        "columns": [{"name": "Region"}, {"name": "Units"},
                    {"name": "Total"}],
        "rows": [["North", "10", "=B1*2"], ["South", "40", "=B2*2"],
                 ["East", "", "=B3*2"], ["West", "25", "=B4*2"]]}


def _model(rules=""):
    model = SheetModel(json.dumps(DATA))
    model.set_rules(rules)
    return model


class TestRules:
    def test_colour_scale_shades_by_value(self, qtbot):
        model = _model("Units scale green")
        low = model.index(0, 1).data(Qt.BackgroundRole)
        high = model.index(1, 1).data(Qt.BackgroundRole)
        assert low is not None and high is not None
        assert low.color() != high.color()
        assert model.index(0, 0).data(Qt.BackgroundRole) is None

    def test_data_bar_and_icons(self, qtbot):
        model = _model("Units bar blue\nTotal icons traffic")
        bar = model.index(1, 1).data(BAR_ROLE)
        assert bar is not None and bar[0] == pytest.approx(1.0)
        assert model.index(0, 2).data(DECOR_ROLE) is not None

    def test_highlight_and_row(self, qtbot):
        model = _model("Units > 20 => bg red, bold\n"
                       "Region = East => row amber")
        assert model.index(1, 1).data(Qt.BackgroundRole) is not None
        assert model.index(1, 1).data(Qt.FontRole).bold()
        assert model.index(0, 1).data(Qt.BackgroundRole) is None
        # a whole-row rule colours every cell of the row it picks
        for col in range(3):
            assert model.index(2, col).data(Qt.BackgroundRole) is not None

    def test_rules_follow_edits_and_formulas(self, qtbot):
        model = _model("Total > 70 => bg green")
        assert model.index(1, 2).data(Qt.BackgroundRole) is not None
        model.setData(model.index(1, 1), "5")
        assert model.index(1, 2).data(Qt.BackgroundRole) is None

    def test_only_draws_the_format(self, qtbot):
        model = _model("Units bar blue only")
        assert model.index(1, 1).data(Qt.DisplayRole) == ""
        assert model.index(1, 1).data(Qt.EditRole) == "40"   # value kept

    def test_a_bad_line_does_not_stop_the_rest(self, qtbot):
        model = _model("this is not a rule\nUnits scale green")
        assert model.index(1, 1).data(Qt.BackgroundRole) is not None

    def test_no_rules_costs_nothing(self, qtbot):
        model = _model("")
        assert model.cell_style(0, 0) is None
        assert model._cf_frame is None

    def test_delegate_is_show_tables(self):
        from flograph.ui.spreadsheet.delegates import SheetDelegate
        assert issubclass(SheetDelegate, ConditionalFormatDelegate)


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def env(qtbot, registry):
    graph = Graph()
    stack = QUndoStack()
    scene = NodeGraphScene(graph, stack, registry=registry)
    yield graph, stack, scene
    stack.clear()


def _card(graph, registry, scene):
    node = graph.add_node(registry.instantiate("flograph.io.table"))
    graph.set_param(node.id, "data", json.dumps(DATA))
    return node, scene.node_items[node.id]


class TestOnTheCard:
    def test_the_rules_param_paints_the_card(self, env, registry):
        graph, stack, scene = env
        node, item = _card(graph, registry, scene)
        graph.set_param(node.id, "rules", "Units > 20 => bg red")
        assert item._table_model.index(1, 1).data(
            Qt.BackgroundRole) is not None

    def test_presets_write_rules_undoably_and_rerun_nothing(
            self, env, registry):
        graph, stack, scene = env
        node, item = _card(graph, registry, scene)
        graph.nodes[node.id].dirty = False
        grid = item._table_widget
        grid.select_columns([1])
        cond_format._apply(grid, lambda c: f"{c} scale green")
        assert node.params["rules"] == "Units scale green"
        assert not graph.nodes[node.id].dirty     # cosmetic: no re-run
        assert item._table_model.index(1, 1).data(
            Qt.BackgroundRole) is not None
        stack.undo()
        assert node.params["rules"] == ""

    def test_clear_rules_from_column_keeps_the_others(self, env, registry):
        graph, stack, scene = env
        node, item = _card(graph, registry, scene)
        graph.set_param(node.id, "rules",
                        "Units scale green\n# note\nTotal bar blue")
        grid = item._table_widget
        grid.select_columns([1])
        cond_format.clear_columns(grid)
        assert node.params["rules"] == "# note\nTotal bar blue"

    def test_quoted_column_names(self, env, registry):
        graph, stack, scene = env
        node, item = _card(graph, registry, scene)
        model = item._table_model
        model.rename_column(1, "Units Sold")
        grid = item._table_widget
        grid.select_columns([1])
        cond_format._apply(grid, lambda c: f"{c} bar green")
        assert node.params["rules"] == '"Units Sold" bar green'
        assert model.index(1, 1).data(BAR_ROLE) is not None

    def test_the_menus_offer_conditional_formatting(self, env, registry,
                                                    monkeypatch):
        from flograph.ui.spreadsheet import menus
        shown = []
        monkeypatch.setattr(menus, "exec_menu",
                            lambda menu, w, p: shown.append(menu))
        graph, stack, scene = env
        node, item = _card(graph, registry, scene)
        grid = item._table_widget
        grid.setCurrentIndex(grid.model().index(0, 1))
        menus.cell_menu(grid, grid.viewport(), QPoint(5, 5))
        titles = [a.text() for a in shown[0].actions()]
        assert "Conditional Formatting" in titles


def test_add_rule_and_without_columns():
    assert cond_format.add_rule("", "a scale green") == "a scale green"
    assert cond_format.add_rule("x bar blue\n", "a scale green") == \
        "x bar blue\na scale green"
    assert cond_format.without_columns("a scale green\nb bar blue",
                                       ["a"]) == "b bar blue"
