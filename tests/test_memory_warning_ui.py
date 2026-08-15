"""Saying that memory is short, where it can actually be seen.

The warning existed before this and was thrown away during a run — the one
time the flow is what is filling the machine up. And the status bar alone
answers "memory is tight" without answering "because of what", which is the
only half a person can act on.

Settings are kept off the real store, as in test_settings_reset.py.
"""
import pytest
from PySide6.QtCore import QSettings

from flograph.core import NodeRegistry
from flograph.ui import mainwindow as mod

MB = 1024 ** 2


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))
    monkeypatch.setattr(
        "flograph.ui.spreadsheet.view.QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def window(qtbot, registry):
    win = mod.MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


def heavy_node(window, registry, size_mb):
    node = registry.instantiate("flograph.util.constant", pos=(0, 0))
    window.graph.add_node(node)
    window.engine.cache.set(node.id, {"value": "x"}, wall_time=0.1)
    window.engine.cache.get(node.id).memory_bytes = size_mb * MB
    return node


class TestTheHeavyNodeMark:
    def test_it_appears_and_clears_with_the_pressure(self, window, registry):
        node = heavy_node(window, registry, 900)
        item = window.scene.node_items[node.id]
        assert not item._heavy_badge.isVisible()

        window._on_memory_pressure("Memory is running low")
        assert item._heavy_badge.isVisible()

        window._on_memory_pressure("")
        assert not item._heavy_badge.isVisible(), \
            "a mark left on a node that is no longer heavy is worse than none"

    def test_only_the_worst_offenders_are_marked(self, window, registry):
        """Marking everything says nothing. The point is to name the step
        worth putting a Max rows on."""
        big = [heavy_node(window, registry, 900 - i) for i in range(3)]
        small = heavy_node(window, registry, 1)

        window._on_memory_pressure("Memory is running low")
        assert all(window.scene.node_items[n.id]._heavy_badge.isVisible()
                   for n in big)
        assert not window.scene.node_items[small.id]._heavy_badge.isVisible()

    def test_a_node_holding_nothing_is_never_marked(self, window, registry):
        node = registry.instantiate("flograph.util.constant", pos=(0, 0))
        window.graph.add_node(node)
        window._on_memory_pressure("Memory is running low")
        assert not window.scene.node_items[node.id]._heavy_badge.isVisible()


class TestTheWarningReachesTheUser:
    def test_it_is_shown_when_nothing_is_running(self, window):
        window._on_memory_pressure("Memory is running low — 900 MB")
        assert "Memory is running low" in window.statusBar().currentMessage()

    def test_it_is_carried_by_the_run_line_instead_of_dropped(self, window):
        """The regression: during a run this used to return early and the
        message was lost."""
        window._run_node_label = "Group By"
        window._on_memory_pressure("memory is tight")
        assert window.engine.active is False   # the guard is on the note, not the run

        window._update_run_status()
        line = window.statusBar().currentMessage()
        assert "Running Group By" in line
        assert "memory is tight" in line

    def test_relief_takes_it_off_the_run_line(self, window):
        window._run_node_label = "Group By"
        window._on_memory_pressure("memory is tight")
        window._on_memory_pressure("")
        window._update_run_status()
        assert "memory is tight" not in window.statusBar().currentMessage()

    def test_the_note_can_stand_on_its_own(self, window):
        """Pressure can arrive before any node has claimed the floor. The
        line must not read 'Running' and then name nobody."""
        window._run_node_label = ""
        window._on_memory_pressure("memory is tight")
        window._update_run_status()
        line = window.statusBar().currentMessage()
        assert "memory is tight" in line
        assert "Running " not in line
