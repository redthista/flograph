"""Align and Distribute on the canvas right-click menu, for a selection —
the Edit menu's four, where the selection already is."""
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMenu

from flograph.core import Frame
from flograph.ui import mainwindow as mw
from flograph.ui.mainwindow import MainWindow

CONST = "flograph.util.constant"


def _find(menu, text):
    for action in menu.actions():
        if action.text() == text:
            return action
        if action.menu() is not None:
            found = _find(action.menu(), text)
            if found is not None:
                return found
    return None


def _pick(monkeypatch, text):
    """Only the top menu's exec runs; it hands back the chosen entry the
    way Qt would, submenus included, without triggering it."""
    class _Picker(QMenu):
        def exec(self, *args):
            return _find(self, text)
    monkeypatch.setattr(mw, "QMenu", _Picker)


def _titles(monkeypatch):
    seen: list = []

    class _Recorder(QMenu):
        def exec(self, *args):
            seen.extend(a.text() for a in self.actions())
            return None
    monkeypatch.setattr(mw, "QMenu", _Recorder)
    return seen


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


def _nodes(window, *positions, select=True):
    nodes = [window.graph.add_node(window.registry.instantiate(CONST, pos=p))
             for p in positions]
    for node in nodes:
        window.scene.node_items[node.id].setSelected(select)
    return nodes


class TestAlignOnTheNodeMenu:
    def test_offered_for_a_selection(self, window, monkeypatch):
        nodes = _nodes(window, (0, 0), (50, 100))
        seen = _titles(monkeypatch)
        window._show_node_menu(nodes[0].id, QPoint(0, 0))
        assert "Align" in seen

    def test_not_offered_for_one_node(self, window, monkeypatch):
        nodes = _nodes(window, (0, 0), (50, 100), select=False)
        seen = _titles(monkeypatch)
        window._show_node_menu(nodes[0].id, QPoint(0, 0))
        assert seen and "Align" not in seen

    def test_align_left_lines_the_selection_up(self, window, monkeypatch):
        nodes = _nodes(window, (0, 0), (50, 100), (120, 260))
        _pick(monkeypatch, "Align Left")
        window._show_node_menu(nodes[1].id, QPoint(0, 0))
        assert all(n.pos[0] == 0 for n in nodes)
        # one step, not two: the entry runs once
        window.undo_stack.undo()
        assert nodes[1].pos == (50.0, 100.0)

    def test_distribute_vertically(self, window, monkeypatch):
        nodes = _nodes(window, (0, 0), (0, 40), (0, 300))
        _pick(monkeypatch, "Distribute Vertically")
        window._show_node_menu(nodes[0].id, QPoint(0, 0))
        ys = sorted(n.pos[1] for n in nodes)
        assert ys[1] - ys[0] == pytest.approx(ys[2] - ys[1])


class TestAlignOnTheFrameMenu:
    def test_a_frame_and_a_node_line_up(self, window, monkeypatch):
        window.graph.add_frame(Frame(id="f1", title="T",
                                     rect=(300, 400, 200, 120)))
        window.scene.frame_items["f1"].setSelected(True)
        (node,) = _nodes(window, (40, 0))
        _pick(monkeypatch, "Align Top")
        window._show_frame_menu("f1", QPoint(0, 0))
        assert node.pos[1] == pytest.approx(
            window.graph.frames["f1"].rect[1])

    def test_not_offered_for_a_lone_frame(self, window, monkeypatch):
        window.graph.add_frame(Frame(id="f1", title="T",
                                     rect=(300, 400, 200, 120)))
        seen = _titles(monkeypatch)
        window._show_frame_menu("f1", QPoint(0, 0))
        assert seen and "Align" not in seen
