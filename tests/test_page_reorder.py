"""Reordering dashboard pages: the core model writer, the undo command, the
tab bar's drag gesture (Model pinned first, "+" pinned last), and the round
trip through MainWindow."""
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QUndoStack
from PySide6.QtTest import QTest

from flograph.core import Graph, GraphError, NodeRegistry, Page
from flograph.core.serialization import graph_from_dict, graph_to_dict
from flograph.ui import mainwindow as mod
from flograph.ui.commands import (
    AddPageCommand, RemovePageCommand, ReorderPagesCommand,
)
from flograph.ui.dashboard.page_bar import PageTabBar
from flograph.ui.mainwindow import MainWindow


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


@pytest.fixture
def graph():
    g = Graph()
    for page_id in ("p1", "p2", "p3"):
        g.add_page(Page(id=page_id, title=page_id.upper()))
    return g


class TestCoreReorder:
    def test_reorders_and_emits(self, graph):
        seen = []
        graph.events.pages_reordered.connect(seen.append)
        graph.reorder_pages(["p3", "p1", "p2"])
        assert list(graph.pages) == ["p3", "p1", "p2"]
        assert seen == [["p3", "p1", "p2"]]

    def test_pages_survive_intact(self, graph):
        graph.reorder_pages(["p2", "p3", "p1"])
        assert graph.pages["p2"].title == "P2"

    @pytest.mark.parametrize("order", [
        ["p1", "p2"],              # missing one
        ["p1", "p2", "p3", "p4"],  # unknown id
        ["p1", "p2", "p2"],        # duplicate
    ])
    def test_bad_order_rejected(self, graph, order):
        with pytest.raises(GraphError):
            graph.reorder_pages(order)
        assert list(graph.pages) == ["p1", "p2", "p3"]

    def test_order_round_trips_through_serialization(self, graph):
        graph.reorder_pages(["p3", "p2", "p1"])
        assert list(graph_from_dict(graph_to_dict(graph),
                                    NodeRegistry()).pages) == ["p3", "p2", "p1"]


class TestReorderCommand:
    def test_undo_redo_restores_order(self, qtbot, graph):
        stack = QUndoStack()
        before = graph_to_dict(graph)
        stack.push(ReorderPagesCommand(graph, ["p2", "p3", "p1"]))
        after = graph_to_dict(graph)
        assert list(graph.pages) == ["p2", "p3", "p1"]
        for _ in range(2):
            stack.undo()
            assert list(graph.pages) == ["p1", "p2", "p3"]
            assert graph_to_dict(graph) == before
            stack.redo()
            assert graph_to_dict(graph) == after
        stack.clear()   # free commands while the graph is alive (see notes)

    def test_delete_undo_restores_position(self, qtbot, graph):
        stack = QUndoStack()
        stack.push(RemovePageCommand(graph, "p2"))
        assert list(graph.pages) == ["p1", "p3"]
        stack.undo()
        assert list(graph.pages) == ["p1", "p2", "p3"]
        stack.clear()


@pytest.fixture
def bar(qtbot):
    widget = PageTabBar()
    qtbot.addWidget(widget)
    for page_id in ("p1", "p2", "p3"):
        widget.add_page_tab(Page(id=page_id, title=page_id.upper()))
    widget.resize(400, 30)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def drag_tab(qtbot, bar, source: int, target: int) -> None:
    """Drag the tab at `source` onto the tab at `target` with real mouse
    events, so Qt's own move machinery (and our pinning) is what runs."""
    start = bar.tabRect(source).center()
    end = bar.tabRect(target).center()
    QTest.mousePress(bar, Qt.LeftButton, Qt.NoModifier, start)
    step = 1 if end.x() > start.x() else -1
    for x in range(start.x(), end.x() + step, step * 4):
        QTest.mouseMove(bar, QPoint(x, start.y()))
    QTest.mouseMove(bar, end)
    QTest.mouseRelease(bar, Qt.LeftButton, Qt.NoModifier, end)


class TestTabBarDrag:
    def test_layout(self, bar):
        assert bar.tabText(0) == "Model"
        assert bar.tabText(bar.count() - 1) == "+"
        assert bar.page_order() == ["p1", "p2", "p3"]

    def test_drag_page_emits_new_order(self, qtbot, bar):
        with qtbot.waitSignal(bar.reorder_pages_requested) as blocker:
            drag_tab(qtbot, bar, bar._index_of_page("p3"),
                     bar._index_of_page("p1"))
        assert blocker.args[0] == bar.page_order()
        assert bar.page_order()[0] == "p3"

    def test_one_request_per_drag(self, qtbot, bar):
        emitted = []
        bar.reorder_pages_requested.connect(emitted.append)
        drag_tab(qtbot, bar, bar._index_of_page("p1"),
                 bar._index_of_page("p3"))
        assert len(emitted) == 1

    def test_model_tab_cannot_be_dragged(self, qtbot, bar):
        emitted = []
        bar.reorder_pages_requested.connect(emitted.append)
        drag_tab(qtbot, bar, 0, bar._index_of_page("p3"))
        assert bar.tabText(0) == "Model"
        assert bar.page_order() == ["p1", "p2", "p3"]
        assert emitted == []

    def test_page_cannot_be_dragged_before_model(self, qtbot, bar):
        drag_tab(qtbot, bar, bar._index_of_page("p3"), 0)
        assert bar.tabText(0) == "Model"
        assert set(bar.page_order()) == {"p1", "p2", "p3"}

    def test_page_cannot_be_dragged_past_plus(self, qtbot, bar):
        drag_tab(qtbot, bar, bar._index_of_page("p1"), bar.count() - 1)
        assert bar.tabText(bar.count() - 1) == "+"
        assert set(bar.page_order()) == {"p1", "p2", "p3"}

    def test_dragged_page_follows_the_drag(self, qtbot, bar):
        # pressing a tab selects it (as any tab click does), and the moved
        # tab must still be the current one once it lands
        bar.select_page("p2")
        drag_tab(qtbot, bar, bar._index_of_page("p3"),
                 bar._index_of_page("p1"))
        assert bar.current_page_id() == "p3"
        assert bar.tabData(bar.currentIndex()) == "p3"

    def test_set_page_order_keeps_the_current_page(self, bar):
        bar.select_page("p2")
        bar.set_page_order(["p3", "p2", "p1"])
        assert bar.current_page_id() == "p2"

    def test_set_page_order_permutes_tabs(self, bar):
        bar.set_page_order(["p3", "p1", "p2"])
        assert bar.page_order() == ["p3", "p1", "p2"]
        assert bar.tabText(0) == "Model"
        assert bar.tabText(bar.count() - 1) == "+"

    def test_add_and_remove_still_work_after_reorder(self, bar):
        bar.set_page_order(["p3", "p2", "p1"])
        bar.add_page_tab(Page(id="p4", title="P4"))
        assert bar.page_order() == ["p3", "p2", "p1", "p4"]
        assert bar.tabText(bar.count() - 1) == "+"
        bar.remove_page_tab("p2")
        assert bar.page_order() == ["p3", "p1", "p4"]


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
    for page_id in ("p1", "p2", "p3"):
        win.undo_stack.push(
            AddPageCommand(win.graph, Page(id=page_id, title=page_id.upper())))
    return win


class TestWindowRoundTrip:
    def test_bar_request_reorders_graph_undoably(self, window):
        window.page_bar.reorder_pages_requested.emit(["p2", "p3", "p1"])
        assert list(window.graph.pages) == ["p2", "p3", "p1"]
        assert window.page_bar.page_order() == ["p2", "p3", "p1"]
        window.undo_stack.undo()
        assert list(window.graph.pages) == ["p1", "p2", "p3"]
        assert window.page_bar.page_order() == ["p1", "p2", "p3"]

    def test_no_command_when_order_unchanged(self, window):
        depth = window.undo_stack.count()
        window.page_bar.reorder_pages_requested.emit(["p1", "p2", "p3"])
        assert window.undo_stack.count() == depth

    def test_stale_request_resyncs_bar_from_graph(self, window):
        window.page_bar.reorder_pages_requested.emit(["p2", "p9"])
        assert list(window.graph.pages) == ["p1", "p2", "p3"]
        assert window.page_bar.page_order() == ["p1", "p2", "p3"]

    def test_delete_undo_puts_the_tab_back_in_place(self, window):
        window.undo_stack.push(RemovePageCommand(window.graph, "p2"))
        assert window.page_bar.page_order() == ["p1", "p3"]
        window.undo_stack.undo()
        assert window.page_bar.page_order() == ["p1", "p2", "p3"]
