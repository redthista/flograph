"""The Input Panel's setup wizard (ui/panel_wizard.py) and the Qt-free
halves it stands on: writing fields back as lines (dump_fields) and
proposing a field per column (suggest_fields)."""
import pandas as pd
import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QDialog

from flograph.core import Graph, NodeRegistry
from flograph.core import control_apply as ca
from flograph.core.input_panel import (dump_fields, parse_fields,
                                       suggest_field, suggest_fields)
from flograph.ui import panel_wizard as pw

SALES = pd.DataFrame({
    "region": ["North", "North", "South", "South", "East"],
    "city": ["Leeds", "York", "Bath", "Truro", "Ely"],
    "price": [10.0, 40.0, 25.0, 70.0, 55.0],
    "when": ["2026-01-05", "2026-02-10", "2026-02-20", "2026-03-01",
             "2026-03-15"],
    "in stock": [True, False, True, True, False],
    "order_id": [1, 2, 3, 4, 5],
})


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def _strip(fields):
    return [(f["label"], f["shape"], f["column"], f["op"], f["opts"])
            for f in fields]


class TestLines:
    def test_written_lines_read_back_as_the_same_fields(self):
        text = ("Region = slicer region\n"
                "Price = between price step=5\n"
                "Big = slider \"unit price\" <= help=\"the cap\"\n"
                "Ordered = date range when\n"
                "Search = text city startswith\n"
                "Top N = number min=1 max=50\n")
        fields, problems = parse_fields(text)
        assert problems == []
        again, problems = parse_fields(dump_fields(fields))
        assert problems == [] and _strip(again) == _strip(fields)

    def test_a_default_comparison_is_left_out(self):
        fields, _ = parse_fields("Price = slider price >=\n")
        assert dump_fields(fields) == "Price = slider price"


class TestSuggestions:
    def test_each_kind_of_column(self):
        by = {f["column"]: f for f in suggest_fields(SALES)}
        assert by["region"]["shape"] == "choice"            # 3 values
        assert by["region"]["opts"] == {"style": "buttons"}
        assert by["price"]["shape"] == "range"
        assert by["price"]["opts"]["step"] == "5"
        assert by["when"]["shape"] == "date_range"
        assert by["in stock"]["shape"] == "toggle"
        assert "order_id" not in by                          # an id
        assert by["in stock"]["label"] == "In stock"

    def test_a_few_dozen_values_is_a_slicer_and_unique_text_a_search(self):
        many = pd.Series([f"store {i % 30}" for i in range(300)])
        assert suggest_field("store", many)["shape"] == "list"
        names = pd.Series([f"customer {i}" for i in range(300)])
        assert suggest_field("customer", names)["shape"] == "text"

    def test_slicers_come_first(self):
        shapes = [f["shape"] for f in suggest_fields(SALES)]
        assert shapes.index("choice") < shapes.index("date_range") \
            < shapes.index("range") < shapes.index("toggle")


class TestDialog:
    def test_existing_fields_load_and_round_trip(self, qtbot):
        params = {"fields": "Region = slicer region\nPrice = between price"}
        dlg = pw.PanelWizard(params, SALES)
        qtbot.addWidget(dlg)
        assert dlg.table.rowCount() == 2
        assert dlg.fields_text() == "Region = slicer region\n" \
                                    "Price = between price"

    def test_an_empty_panel_starts_from_ticked_suggestions(self, qtbot):
        dlg = pw.PanelWizard({"fields": ""}, SALES)
        qtbot.addWidget(dlg)
        assert dlg.table.rowCount() == len(suggest_fields(SALES))
        # OK on an untouched dialog takes the proposal as it stands
        assert dlg.fields_text() == dump_fields(suggest_fields(SALES))
        tick = dlg.table.cellWidget(0, pw._USE).findChild(
            __import__("PySide6.QtWidgets", fromlist=["QCheckBox"]).QCheckBox)
        tick.setChecked(False)
        assert len(dlg.fields()) == len(suggest_fields(SALES)) - 1

    def test_editing_a_row(self, qtbot):
        dlg = pw.PanelWizard({"fields": "Region = slicer region"}, SALES)
        qtbot.addWidget(dlg)
        shape = dlg.table.cellWidget(0, pw._SHAPE)
        shape.setCurrentIndex(shape.findData("choice"))
        dlg.table.cellWidget(0, pw._OPTS).setText("style=buttons")
        assert dlg.fields_text() == "Region = choice region style=buttons"
        assert "Region = choice region style=buttons" in \
            dlg.preview.toPlainText()

    def test_the_comparison_follows_the_shape(self, qtbot):
        dlg = pw.PanelWizard({"fields": "Price = slider price"}, SALES)
        qtbot.addWidget(dlg)
        op = dlg.table.cellWidget(0, pw._OP)
        assert op.isEnabled() and op.currentData() == ">="
        op.setCurrentIndex(op.findData("<="))
        assert dlg.fields_text() == "Price = slider price <="
        shape = dlg.table.cellWidget(0, pw._SHAPE)
        shape.setCurrentIndex(shape.findData("list"))
        assert not dlg.table.cellWidget(0, pw._OP).isEnabled()

    def test_add_suggest_reorder_remove(self, qtbot):
        dlg = pw.PanelWizard({"fields": "Region = slicer region"}, SALES)
        qtbot.addWidget(dlg)
        dlg.suggest()
        columns = [f["column"] for f in dlg.fields()]
        assert columns.count("region") == 1 and "price" in columns
        dlg.table.selectRow(1)
        dlg._move(-1)
        assert dlg.fields()[0]["column"] != "region"
        dlg.table.selectRow(0)
        dlg._remove_row()
        assert dlg.fields()[0]["column"] == "region"

    def test_a_column_name_can_be_typed(self, qtbot):
        dlg = pw.PanelWizard({"fields": ""}, None)
        qtbot.addWidget(dlg)
        dlg.add_field(None)
        dlg.table.cellWidget(0, pw._COLUMN).setEditText("unit price")
        dlg.table.cellWidget(0, pw._LABEL).setText("Unit price")
        assert dlg.fields_text() == "Unit price = slicer 'unit price'"
        assert not dlg._suggest.isEnabled()

    def test_panel_settings(self, qtbot):
        dlg = pw.PanelWizard({"fields": "", "apply": ca.BUTTON,
                              "cascade": "off"}, SALES)
        qtbot.addWidget(dlg)
        params = dlg.result_params()
        assert params["apply"] == ca.BUTTON and params["cascade"] == "off"


class TestOpening:
    def test_ok_writes_every_setting_as_one_undo_step(self, qtbot, registry,
                                                      monkeypatch):
        graph = Graph()
        node = graph.add_node(registry.instantiate("flograph.input.input_panel"))
        stack = QUndoStack()

        def accept(self):
            # as if a run had put SALES on the panel's data input
            self._data = SALES
            self._columns = list(SALES.columns)
            self.suggest()
            self._apply.setCurrentIndex(self._apply.findData(ca.BUTTON))
            return QDialog.Accepted
        monkeypatch.setattr(pw.PanelWizard, "exec", accept)
        before = stack.index()
        assert pw.open_panel_wizard(None, graph, stack, None, node.id)
        assert stack.index() == before + 1
        assert "Region = choice region" in node.params["fields"]
        assert node.params["apply"] == ca.BUTTON
        stack.undo()
        assert node.params["fields"] == "" and node.params["apply"] == ca.LIVE

    def test_cancel_changes_nothing(self, qtbot, registry, monkeypatch):
        graph = Graph()
        node = graph.add_node(registry.instantiate("flograph.input.input_panel"))
        stack = QUndoStack()
        monkeypatch.setattr(pw.PanelWizard, "exec",
                            lambda self: QDialog.Rejected)
        assert not pw.open_panel_wizard(None, graph, stack, None, node.id)
        assert stack.count() == 0

    def test_the_empty_card_offers_set_up(self, qtbot, registry):
        from flograph.ui.canvas import NodeGraphScene
        graph = Graph()
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        node = graph.add_node(registry.instantiate("flograph.input.input_panel"))
        widget = scene.node_items[node.id]._control_widget
        assert not widget._hint.isHidden()
        asked = []
        scene.panel_setup_requested.connect(asked.append)
        widget._setup.click()
        assert asked == [node.id]
