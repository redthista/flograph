"""'password' param type: masked QLineEdit with a Show/Hide reveal toggle
(ideas.md #6). Registration (params.py) and the properties-panel widget
(params_panel.py) both need covering."""
import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QLineEdit, QToolButton

from flograph.core import Graph, ParamSpec
from tests.conftest import make_node

SOURCE = """
NODE = {
    "label": "Creds", "category": "Test",
    "inputs": [], "outputs": [("out", "any")],
}
PARAMS = [
    {"name": "api_key", "type": "password", "default": "",
     "placeholder": "secret"},
]
def run(ctx):
    return None
"""


class TestPasswordParamSpec:
    def test_from_dict_defaults_to_empty_string(self):
        spec = ParamSpec.from_dict({"name": "secret", "type": "password"})
        assert spec.type == "password"
        assert spec.default == ""

    def test_from_dict_honors_explicit_default(self):
        spec = ParamSpec.from_dict(
            {"name": "secret", "type": "password", "default": "hunter2"})
        assert spec.default == "hunter2"


class TestPasswordParamWidget:
    @pytest.fixture
    def panel(self, qtbot):
        from flograph.ui.properties.params_panel import ParamsPanel
        graph = Graph()
        node = make_node(SOURCE, "test.creds")
        graph.add_node(node)
        panel = ParamsPanel(graph, QUndoStack())
        qtbot.addWidget(panel)
        panel.set_node(node.id)
        return panel, graph, node

    def _widgets(self, panel):
        edit = panel.findChild(QLineEdit, "param_api_key")
        reveal = panel.findChild(QToolButton, "param_api_key_reveal")
        return edit, reveal

    def test_starts_masked_with_placeholder(self, panel):
        panel, _graph, _node = panel
        edit, reveal = self._widgets(panel)
        assert edit.echoMode() == QLineEdit.Password
        assert edit.placeholderText() == "secret"
        assert reveal.text() == "Show"

    def test_reveal_toggle_unmasks_and_relabels(self, panel):
        panel, _graph, _node = panel
        edit, reveal = self._widgets(panel)
        reveal.setChecked(True)
        assert edit.echoMode() == QLineEdit.Normal
        assert reveal.text() == "Hide"
        reveal.setChecked(False)
        assert edit.echoMode() == QLineEdit.Password
        assert reveal.text() == "Show"

    def test_typing_commits_the_param(self, panel, qtbot):
        panel, graph, node = panel
        edit, _reveal = self._widgets(panel)
        qtbot.keyClicks(edit, "hunter2")
        assert graph.node(node.id).params["api_key"] == "hunter2"

    def test_undo_redo_syncs_widget_text(self, panel, qtbot):
        panel, graph, node = panel
        edit, _reveal = self._widgets(panel)
        qtbot.keyClicks(edit, "hunter2")
        panel._undo_stack.undo()
        assert edit.text() == ""
        panel._undo_stack.redo()
        assert edit.text() == "hunter2"
