"""The optional shape tool rail: off by default, and when armed a drag on the
canvas draws one shape."""
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSettings, Qt
from PySide6.QtGui import QMouseEvent

from flograph.core import NodeRegistry
from flograph.ui import mainwindow as mod
from flograph.ui.mainwindow import MainWindow


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini = str(tmp_path / "s.ini")
    monkeypatch.setattr(mod, "QSettings",
                        lambda *a, **k: QSettings(ini, QSettings.IniFormat))


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    yield win


def _mouse(kind, pos, button=Qt.LeftButton):
    return QMouseEvent(kind, QPointF(pos), QPointF(pos), button, button,
                       Qt.NoModifier)


def test_rail_is_off_by_default(window):
    assert window.shape_rail_enabled is False
    assert window.view._shape_rail is None


def test_enabling_the_rail_creates_it(window):
    window.set_shape_rail_enabled(True)
    assert window.view._shape_rail is not None
    window.set_shape_rail_enabled(False)
    assert window.view._shape_rail.isVisible() is False


def test_armed_drag_draws_one_shape(window):
    window.set_shape_rail_enabled(True)
    window.view._arm_shape_draw("ellipse")
    window.view.mousePressEvent(_mouse(QEvent.MouseButtonPress, QPoint(40, 40)))
    window.view.mouseMoveEvent(
        _mouse(QEvent.MouseMove, QPoint(180, 140), Qt.NoButton))
    window.view.mouseReleaseEvent(
        _mouse(QEvent.MouseButtonRelease, QPoint(180, 140)))
    assert len(window.graph.shapes) == 1
    shape = next(iter(window.graph.shapes.values()))
    assert shape.kind == "ellipse"
    assert shape.rect[2] > 50 and shape.rect[3] > 50
    assert window.view._shape_draw_kind is None       # disarms after one


def test_escape_disarms_without_drawing(window):
    window.set_shape_rail_enabled(True)
    window.view._arm_shape_draw("rect")
    from PySide6.QtGui import QKeyEvent
    window.view.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape,
                                        Qt.NoModifier))
    assert window.view._shape_draw_kind is None
    assert not window.graph.shapes


def test_a_click_without_a_drag_still_makes_a_shape(window):
    window.set_shape_rail_enabled(True)
    window.view._arm_shape_draw("text")
    window.view.mousePressEvent(_mouse(QEvent.MouseButtonPress, QPoint(90, 90)))
    window.view.mouseReleaseEvent(
        _mouse(QEvent.MouseButtonRelease, QPoint(91, 91)))
    assert len(window.graph.shapes) == 1
