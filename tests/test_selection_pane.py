"""The Selection pane: lists shapes and frames in drawing order, toggles
their visibility, and restacks them by drag."""
import pytest
from PySide6.QtCore import Qt, QPointF, QSettings

from flograph.core import Frame, NodeRegistry
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


def _rows(panel):
    return [panel._tree.topLevelItem(i).text(0)
            for i in range(panel._tree.topLevelItemCount())]


def test_lists_shapes_front_first_around_the_node_divider(window):
    window._add_shape_at(QPointF(0, 0), "rect")      # added first -> lower
    window._add_shape_at(QPointF(0, 0), "ellipse")   # added last  -> on top
    window.graph.add_frame(Frame(id="f1", title="Stage"))
    panel = window.selection_panel
    panel._rebuild()
    rows = _rows(panel)
    assert rows == ["Ellipse", "Rectangle", "Nodes & wires", "Frames", "Stage"]


def test_eye_toggle_hides_and_shows_the_shape(window):
    window._add_shape_at(QPointF(0, 0), "rect")
    sid = next(iter(window.graph.shapes))
    panel = window.selection_panel
    panel._rebuild()
    row = panel._tree.topLevelItem(0)
    row.setCheckState(1, Qt.Unchecked)
    assert window.graph.shapes[sid].hidden is True
    assert window.scene.shape_items[sid].isVisible() is False
    panel._rebuild()
    panel._tree.topLevelItem(0).setCheckState(1, Qt.Checked)
    assert window.graph.shapes[sid].hidden is False


def test_click_navigates_and_selects(window):
    window._add_shape_at(QPointF(500, 500), "rect")
    sid = next(iter(window.graph.shapes))
    window.scene.clearSelection()
    panel = window.selection_panel
    panel._rebuild()
    panel._on_clicked(panel._tree.topLevelItem(0), 0)
    assert window.scene.shape_items[sid].isSelected()


def test_dragging_a_shape_below_the_divider_sends_it_behind(window):
    window._add_shape_at(QPointF(0, 0), "rect")
    sid = next(iter(window.graph.shapes))
    panel = window.selection_panel
    panel._rebuild()
    tree = panel._tree
    row = tree.takeTopLevelItem(0)             # the shape, above the divider
    tree.insertTopLevelItem(tree.topLevelItemCount(), row)  # now last of all
    panel._commit_reorder()
    assert window.graph.shapes[sid].behind is True


def test_reordering_two_shapes_restacks_them(window):
    window._add_shape_at(QPointF(0, 0), "rect")
    window._add_shape_at(QPointF(0, 0), "ellipse")
    panel = window.selection_panel
    panel._rebuild()
    before = window.graph.stacking_order("shape")
    tree = panel._tree
    top = tree.takeTopLevelItem(0)             # frontmost shape
    tree.insertTopLevelItem(1, top)            # drop it below its neighbour
    panel._commit_reorder()
    assert window.graph.stacking_order("shape") == list(reversed(before))
