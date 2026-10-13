"""A number param types like a text box: no padding of trailing zeros, and
one commit for the whole number rather than one per keystroke."""
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QUndoStack

from flograph.core import Graph
from flograph.ui.number_box import NumberBox
from tests.conftest import make_node

SOURCE = """
NODE = {
    "label": "Num", "category": "Test",
    "inputs": [], "outputs": [("out", "any")],
}
PARAMS = [
    {"name": "ratio", "type": "float", "default": 0.0},
]
def run(ctx):
    return None
"""


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "flograph.ini")
    monkeypatch.setattr(
        "flograph.ui.properties.params_panel.QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


@pytest.mark.parametrize("value, shown", [
    (0.0, "0"), (0.5, "0.5"), (3.0, "3"), (-2.25, "-2.25"),
    (0.00001, "0.00001"), (1234567.0, "1234567"),
])
def test_shows_the_shortest_text(qtbot, value, shown):
    box = NumberBox()
    qtbot.addWidget(box)
    box.setDecimals(6)
    box.setRange(-1e18, 1e18)
    box.setValue(value)
    assert box.text() == shown


def test_typing_commits_once_without_padding(qtbot):
    from flograph.ui.properties.params_panel import ParamsPanel
    graph = Graph()
    node = make_node(SOURCE, "test.num")
    graph.add_node(node)
    undo = QUndoStack()
    panel = ParamsPanel(graph, undo)
    qtbot.addWidget(panel)
    panel.set_node(node.id)
    box = panel.findChild(NumberBox)
    assert box.text() == "0"

    box.lineEdit().selectAll()
    qtbot.keyClicks(box.lineEdit(), "0.5")
    # nothing committed or reformatted mid-number
    assert box.lineEdit().text() == "0.5"
    assert node.params["ratio"] == 0.0
    qtbot.keyClick(box.lineEdit(), Qt.Key_Return)
    assert node.params["ratio"] == 0.5
    assert box.text() == "0.5"
    assert undo.count() == 1
