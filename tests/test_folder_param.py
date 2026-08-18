"""'folder_open' param type: a line edit whose browse button opens a
directory chooser rather than a file chooser. The `Read … (Folder)` nodes
take a directory, so a file dialog there could only ever offer wrong
answers. Registration (params.py) and the properties-panel widget
(params_panel.py) both need covering."""
import pytest
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QLineEdit, QToolButton

from flograph.core import Graph, ParamSpec
from flograph.core.varlinks import SUBSTITUTABLE
from tests.conftest import make_node

SOURCE = """
NODE = {
    "label": "Reader", "category": "Test",
    "inputs": [], "outputs": [("out", "any")],
}
PARAMS = [
    {"name": "path", "type": "folder_open", "label": "Folder", "default": "",
     "placeholder": "folder holding the files"},
]
def run(ctx):
    return None
"""

FOLDER_READERS = [
    "flograph.io.read_csv_folder",
    "flograph.io.read_excel_folder",
    "flograph.io.read_parquet_folder",
]


class TestFolderParamSpec:
    def test_from_dict_defaults_to_empty_string(self):
        spec = ParamSpec.from_dict({"name": "path", "type": "folder_open"})
        assert spec.type == "folder_open"
        assert spec.default == ""

    def test_accepts_a_flow_variable(self):
        # a folder is a path like any other — `${data_dir}` must work there
        assert "folder_open" in SUBSTITUTABLE

    @pytest.mark.parametrize("type_id", FOLDER_READERS)
    def test_folder_readers_ask_for_a_folder(self, registry, type_id):
        spec = registry.get(type_id)
        path = next(p for p in spec.params if p.name == "path")
        assert path.type == "folder_open"


class TestFolderParamWidget:
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

    def _widgets(self, panel):
        return (panel.findChild(QLineEdit, "param_path"),
                panel.findChild(QToolButton, "param_path_browse"))

    def test_shows_an_editable_path_with_a_browse_button(self, panel):
        panel, _graph, _node = panel
        edit, browse = self._widgets(panel)
        assert edit is not None and browse is not None
        assert edit.placeholderText() == "folder holding the files"

    def test_browse_opens_a_directory_chooser(self, panel, monkeypatch, tmp_path):
        panel, _graph, node = panel
        from flograph.ui.properties import params_panel as mod
        calls = []

        def fake_dir(parent, caption="", directory="", *args, **kwargs):
            calls.append((caption, directory))
            return str(tmp_path)

        def refuse(*args, **kwargs):  # a file dialog here would be the bug
            raise AssertionError("opened a file chooser for a folder param")

        monkeypatch.setattr(mod.QFileDialog, "getExistingDirectory", fake_dir)
        monkeypatch.setattr(mod.QFileDialog, "getOpenFileName", refuse)
        monkeypatch.setattr(mod.QFileDialog, "getSaveFileName", refuse)

        edit, browse = self._widgets(panel)
        browse.click()

        assert calls and calls[0][0] == "Folder"
        assert edit.text() == str(tmp_path)
        assert node.params["path"] == str(tmp_path)

    def test_browse_starts_from_the_current_folder(self, panel, monkeypatch,
                                                   tmp_path):
        panel, _graph, _node = panel
        from flograph.ui.properties import params_panel as mod
        seen = []
        monkeypatch.setattr(
            mod.QFileDialog, "getExistingDirectory",
            lambda parent, caption="", directory="", *a, **k:
                (seen.append(directory), "")[1])

        edit, browse = self._widgets(panel)
        edit.setText(str(tmp_path))
        browse.click()

        assert seen == [str(tmp_path)]

    def test_cancelling_leaves_the_value_alone(self, panel, monkeypatch):
        panel, _graph, node = panel
        from flograph.ui.properties import params_panel as mod
        monkeypatch.setattr(
            mod.QFileDialog, "getExistingDirectory",
            lambda *a, **k: "")  # user pressed Cancel

        edit, browse = self._widgets(panel)
        edit.setText("/data/sales")
        edit.editingFinished.emit()
        browse.click()

        assert edit.text() == "/data/sales"
        assert node.params["path"] == "/data/sales"
