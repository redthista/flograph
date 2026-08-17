"""`visible_when`: a param row that only appears while a sibling param holds
one of the listed values (params.py) plus the properties-panel rebuild that
makes it happen (params_panel.py).

The Read File node is the reason it exists — five file formats' options in
one node is an unreadable panel if they all show at once.
"""
import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QComboBox

from flograph.core import Graph, ParamSpec
from flograph.core.params import controllers
from tests.conftest import make_node

SOURCE = """
NODE = {
    "label": "Reader", "category": "Test",
    "inputs": [], "outputs": [("out", "any")],
}
PARAMS = [
    {"name": "format", "type": "choice", "label": "Format",
     "options": ["auto", "csv", "excel"], "default": "auto"},
    {"name": "separator", "type": "string", "label": "Separator",
     "default": ",", "visible_when": {"format": ["auto", "csv"]}},
    {"name": "sheet", "type": "string", "label": "Sheet",
     "default": "0", "visible_when": {"format": ["auto", "excel"]}},
    {"name": "nrows", "type": "int", "label": "Max rows", "default": 0},
]
def run(ctx):
    return None
"""


class TestVisibleWhenSpec:
    def test_absent_by_default(self):
        spec = ParamSpec.from_dict({"name": "a", "type": "string"})
        assert spec.visible_when == {}
        assert spec.visible_for({"anything": "goes"})

    def test_a_bare_string_is_taken_as_one_value(self):
        spec = ParamSpec.from_dict(
            {"name": "sheet", "type": "string", "visible_when": {"format": "excel"}})
        assert spec.visible_when == {"format": ["excel"]}

    def test_shown_only_for_the_listed_values(self):
        spec = ParamSpec.from_dict(
            {"name": "sep", "type": "string",
             "visible_when": {"format": ["auto", "csv"]}})
        assert spec.visible_for({"format": "csv"})
        assert spec.visible_for({"format": "auto"})
        assert not spec.visible_for({"format": "excel"})

    def test_several_controllers_are_anded(self):
        spec = ParamSpec.from_dict(
            {"name": "x", "type": "string",
             "visible_when": {"format": ["csv"], "mode": ["advanced"]}})
        assert spec.visible_for({"format": "csv", "mode": "advanced"})
        assert not spec.visible_for({"format": "csv", "mode": "basic"})

    def test_an_unknown_controller_leaves_the_row_visible(self):
        """A typo should not make an option unreachable with no way back."""
        spec = ParamSpec.from_dict(
            {"name": "x", "type": "string", "visible_when": {"typo": ["csv"]}})
        assert spec.visible_for({"format": "csv"})

    def test_hidden_still_wins(self):
        spec = ParamSpec.from_dict(
            {"name": "x", "type": "string", "hidden": True,
             "visible_when": {"format": ["csv"]}})
        assert not spec.visible_for({"format": "csv"})

    def test_non_dict_is_rejected(self):
        with pytest.raises(ValueError, match="not a dict"):
            ParamSpec.from_dict(
                {"name": "x", "type": "string", "visible_when": ["csv"]})

    def test_self_reference_is_rejected(self):
        with pytest.raises(ValueError, match="its own value"):
            ParamSpec.from_dict(
                {"name": "x", "type": "string", "visible_when": {"x": ["a"]}})

    def test_empty_value_list_is_rejected(self):
        with pytest.raises(ValueError, match="could never be shown"):
            ParamSpec.from_dict(
                {"name": "x", "type": "string", "visible_when": {"format": []}})

    def test_controllers_collects_the_deciding_names(self):
        specs = [
            ParamSpec.from_dict({"name": "format", "type": "string"}),
            ParamSpec.from_dict({"name": "sep", "type": "string",
                                 "visible_when": {"format": ["csv"]}}),
            ParamSpec.from_dict({"name": "n", "type": "int"}),
        ]
        assert controllers(specs) == {"format"}


class TestVisibleWhenPanel:
    @pytest.fixture
    def panel(self, qtbot):
        from flograph.ui.properties.params_panel import ParamsPanel
        graph = Graph()
        node = make_node(SOURCE, "test.reader")
        graph.add_node(node)
        panel = ParamsPanel(graph, QUndoStack())
        qtbot.addWidget(panel)
        panel.set_node(node.id)
        return panel, graph, node

    def _labels(self, panel):
        tree = panel.tree
        return [tree.topLevelItem(i).text(0)
                for i in range(tree.topLevelItemCount())]

    def _format_combo(self, panel):
        tree = panel.tree
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            if item.text(0) == "Format":
                widget = tree.itemWidget(item, 1)
                assert isinstance(widget, QComboBox)
                return widget
        raise AssertionError("no Format row")

    def test_auto_shows_every_format_s_options(self, panel):
        panel, _graph, _node = panel
        labels = self._labels(panel)
        assert "Separator" in labels
        assert "Sheet" in labels

    def test_choosing_a_format_hides_the_others(self, panel, qtbot):
        panel, graph, node = panel
        self._format_combo(panel).setCurrentText("csv")
        qtbot.waitUntil(lambda: "Sheet" not in self._labels(panel))
        labels = self._labels(panel)
        assert "Separator" in labels
        assert "Max rows" in labels      # no visible_when, always shown
        assert graph.node(node.id).params["format"] == "csv"

    def test_switching_back_brings_the_row_back(self, panel, qtbot):
        panel, _graph, _node = panel
        combo = self._format_combo(panel)
        combo.setCurrentText("csv")
        qtbot.waitUntil(lambda: "Sheet" not in self._labels(panel))
        self._format_combo(panel).setCurrentText("excel")
        qtbot.waitUntil(lambda: "Sheet" in self._labels(panel))
        assert "Separator" not in self._labels(panel)

    def test_a_hidden_param_keeps_its_value(self, panel, qtbot):
        """Hiding a row must not clear it — run() still receives the value."""
        panel, graph, node = panel
        self._format_combo(panel).setCurrentText("excel")
        qtbot.waitUntil(lambda: "Separator" not in self._labels(panel))
        assert graph.node(node.id).params["separator"] == ","

    def test_the_panel_survives_switching_format_repeatedly(self, panel, qtbot):
        """The rebuild deletes the very combo that triggered it; deferring it
        to the next event-loop turn is what keeps that from crashing."""
        panel, _graph, _node = panel
        for value in ("csv", "excel", "auto", "csv", "excel"):
            self._format_combo(panel).setCurrentText(value)
            qtbot.wait(1)
        assert "Sheet" in self._labels(panel)
