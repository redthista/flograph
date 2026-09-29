"""A mouse wheel over a closed drop-down or a number box in Properties
scrolls the panel instead of changing the setting, unless Settings > General turns it back on."""
import pytest
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QUndoStack, QWheelEvent
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox,
                               QSpinBox)

from flograph.core import Graph
from tests.conftest import make_node

SOURCE = """
NODE = {
    "label": "Pick", "category": "Test",
    "inputs": [], "outputs": [("out", "any")],
}
PARAMS = [
    {"name": "mode", "type": "choice", "options": ["a", "b", "c"],
     "default": "b"},
    {"name": "count", "type": "int", "default": 5},
    {"name": "ratio", "type": "float", "default": 0.5},
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


@pytest.fixture
def panel(qtbot):
    from flograph.ui.properties.params_panel import ParamsPanel
    graph = Graph()
    node = make_node(SOURCE, "test.pick")
    graph.add_node(node)
    panel = ParamsPanel(graph, QUndoStack())
    qtbot.addWidget(panel)
    panel.set_node(node.id)
    return panel, graph, node


def _wheel_down(widget) -> None:
    centre = QPointF(widget.rect().center())
    event = QWheelEvent(centre, QPointF(widget.mapToGlobal(QPoint(0, 0))),
                        QPoint(0, 0), QPoint(0, -120), Qt.NoButton,
                        Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)


def _combo(panel) -> QComboBox:
    return next(c for c in panel.findChildren(QComboBox)
                if c.findData("b") >= 0)


def test_off_by_default():
    from flograph.ui.properties.params_panel import wheel_changes_choices
    assert wheel_changes_choices() is False


def test_wheel_leaves_the_choice_alone_by_default(panel):
    panel, graph, node = panel
    combo = _combo(panel)
    _wheel_down(combo)
    assert combo.currentData() == "b"
    assert graph.nodes[node.id].params.get("mode", "b") == "b"


def test_setting_lets_the_wheel_change_it(panel):
    from flograph.ui.properties.params_panel import set_wheel_changes_choices
    panel, graph, node = panel
    set_wheel_changes_choices(True)
    combo = _combo(panel)
    _wheel_down(combo)
    assert combo.currentData() == "c"
    assert graph.nodes[node.id].params["mode"] == "c"


def test_wheel_leaves_number_boxes_alone_by_default(panel):
    panel, graph, node = panel
    spin = panel.findChild(QSpinBox)
    double = panel.findChild(QDoubleSpinBox)
    _wheel_down(spin)
    _wheel_down(double)
    assert spin.value() == 5
    assert double.value() == 0.5
    assert "count" not in graph.nodes[node.id].params or \
        graph.nodes[node.id].params["count"] == 5


def test_setting_lets_the_wheel_step_a_number(panel):
    from flograph.ui.properties.params_panel import set_wheel_changes_choices
    panel, graph, node = panel
    set_wheel_changes_choices(True)
    spin = panel.findChild(QSpinBox)
    _wheel_down(spin)
    assert spin.value() == 4
    assert graph.nodes[node.id].params["count"] == 4
