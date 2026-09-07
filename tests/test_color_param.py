"""'color' param type: a swatch button that opens the colour picker, with a
clear button that puts it back to "no colour chosen".

Blank is a real value here rather than an empty field — it means "use the
theme's own colour", which is what a node does until someone deliberately
overrides it. Registration (params.py) and the properties-panel widget
(params_panel.py) both need covering.
"""
import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QPushButton

from flograph.core import Graph, ParamSpec
from flograph.ui.properties.colour_row import ColourRow
from tests.conftest import make_node

SOURCE = """
NODE = {
    "label": "Painted", "category": "Test",
    "inputs": [], "outputs": [("out", "any")],
}
PARAMS = [
    {"name": "accent", "type": "color", "label": "Accent colour",
     "default": "", "placeholder": "Theme", "cosmetic": True},
]
def run(ctx):
    return None
"""


class TestColorParamSpec:
    def test_it_is_a_registered_type(self):
        spec = ParamSpec.from_dict({"name": "accent", "type": "color"})
        assert spec.type == "color"

    def test_it_defaults_to_no_colour(self):
        """Not "#000000" — a node with no accent chosen follows the theme,
        and black is a colour somebody could have meant."""
        assert ParamSpec.from_dict({"name": "accent", "type": "color"}).default == ""

    def test_it_honours_an_explicit_default(self):
        spec = ParamSpec.from_dict(
            {"name": "accent", "type": "color", "default": "#e11d48"})
        assert spec.default == "#e11d48"

    def test_it_can_be_cosmetic(self):
        """Recolouring a card must not re-run the flow."""
        spec = ParamSpec.from_dict(
            {"name": "accent", "type": "color", "cosmetic": True})
        assert spec.cosmetic


class TestColourRowWidget:
    def test_no_colour_shows_the_none_label(self, qtbot):
        row = ColourRow(lambda c: None, lambda: None)
        qtbot.addWidget(row)
        row.set_colour("", none_label="Theme")
        assert row._swatch.text() == "Theme"
        assert row.value() == ""

    def test_a_colour_paints_the_swatch_and_drops_the_label(self, qtbot):
        row = ColourRow(lambda c: None, lambda: None)
        qtbot.addWidget(row)
        row.set_colour("#e11d48", none_label="Theme")
        assert row._swatch.text() == ""
        assert "#e11d48" in row._swatch.styleSheet()
        assert row.value() == "#e11d48"

    def test_clear_is_dead_until_there_is_something_to_clear(self, qtbot):
        row = ColourRow(lambda c: None, lambda: None)
        qtbot.addWidget(row)
        row.set_colour("", none_label="Theme")
        assert not row._clear.isEnabled()
        row.set_colour("#e11d48", none_label="Theme")
        assert row._clear.isEnabled()

    def test_clearing_reports_the_empty_value(self, qtbot):
        seen = []
        row = ColourRow(lambda c: seen.append(c), lambda: seen.append(""))
        qtbot.addWidget(row)
        row.set_colour("#e11d48", none_label="Theme")
        row._clear.click()
        assert seen == [""]


class TestColorParamInThePanel:
    @pytest.fixture
    def panel(self, qtbot):
        from flograph.ui.properties.params_panel import ParamsPanel
        graph = Graph()
        node = make_node(SOURCE, "test.painted")
        graph.add_node(node)
        panel = ParamsPanel(graph, QUndoStack())
        qtbot.addWidget(panel)
        panel.set_node(node.id)
        return panel, graph, node

    def _row(self, panel):
        return panel.findChild(ColourRow)

    def test_the_panel_builds_a_swatch(self, panel):
        panel, _graph, _node = panel
        assert self._row(panel) is not None

    def test_the_placeholder_names_what_blank_means(self, panel):
        """"Theme" rather than an empty button: the swatch has to say what
        no colour *does*, not just look unset."""
        panel, _graph, _node = panel
        assert self._row(panel)._swatch.text() == "Theme"

    def test_a_stored_colour_arrives_on_the_swatch(self, panel):
        panel, graph, node = panel
        graph.set_param(node.id, "accent", "#16a34a")
        panel.set_node(node.id)
        assert self._row(panel).value() == "#16a34a"

    def test_clearing_writes_the_empty_value_back(self, panel):
        panel, graph, node = panel
        graph.set_param(node.id, "accent", "#16a34a")
        panel.set_node(node.id)
        clear = self._row(panel).findChildren(QPushButton)[-1]
        clear.click()
        assert graph.nodes[node.id].params["accent"] == ""

    def test_a_graph_edit_flows_back_into_the_swatch(self, panel):
        """Undo/redo and edits from elsewhere have to reach the widget."""
        panel, graph, node = panel
        graph.set_param(node.id, "accent", "#0ea5e9")
        assert self._row(panel).value() == "#0ea5e9"
