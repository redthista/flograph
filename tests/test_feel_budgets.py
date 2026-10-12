"""The app's feel, held as work budgets rather than timings.

flograph runs on machines of every calibre, so a millisecond threshold on
whatever box runs the suite proves nothing about a slow laptop. What does
carry over is how much work a gesture costs and how that grows with the
flow: anything that does O(nodes) or O(cards) work on every pan frame or
every keystroke is a bug on any machine. These tests count that work.

Each one is a regression that shipped (0.1.25 / 0.1.26):
- every Table card re-read its whole command set on every undo push in the
  app — so on each keystroke typed into a report;
- the minimap walked every node on every frame of a pan or drag;
- embedded card widgets (ribbons, grids, controls) repainted every frame;
- Qt's 10 MB picture cache thrashed, so cached items repainted anyway;
- each keystroke in a report re-derived every derived edge in the graph.
"""
import json

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPixmapCache, QUndoCommand, QUndoStack
from PySide6.QtWidgets import QGraphicsItem

from flograph.core import Graph, NodeRegistry
from flograph.core.graph import Page
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.canvas.view import NodeGraphView
from flograph.ui.spreadsheet.actions import SheetActions

TABLE = "flograph.io.table"
FILTER = "flograph.transform.filter_rows"
SAVE = "flograph.io.save_report"


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def env(qtbot, registry):
    graph = Graph()
    stack = QUndoStack()
    scene = NodeGraphScene(graph, stack, registry=registry)
    yield graph, stack, scene
    stack.clear()


def _table_data():
    return {"version": 2,
            "columns": [{"name": n, "type": "auto"} for n in "abc"],
            "rows": [["1", "x", ""], ["2", "y", ""]]}


class _Nothing(QUndoCommand):
    """An edit somewhere else in the app — a report keystroke, a node
    moved: it goes on the same stack the Table cards read."""

    def redo(self):
        pass

    def undo(self):
        pass


def _count(monkeypatch, cls, name):
    calls = []
    original = getattr(cls, name)

    def counted(self, *args, **kwargs):
        calls.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(cls, name, counted)
    return calls


class TestTableCardsIgnoreOtherEdits:

    def test_an_edit_elsewhere_refreshes_no_table(self, env, registry,
                                                   monkeypatch):
        graph, stack, scene = env
        for i in range(6):
            node = graph.add_node(registry.instantiate(TABLE))
            graph.set_param(node.id, "data", json.dumps(_table_data()))
        refreshes = _count(monkeypatch, SheetActions, "refresh")
        for _ in range(10):
            stack.push(_Nothing())
        assert refreshes == []

    def test_undo_and_redo_still_follow_the_stack(self, env, registry):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate(TABLE))
        graph.set_param(node.id, "data", json.dumps(_table_data()))
        actions = scene.node_items[node.id]._table_widget.actions
        stack.clear()
        assert not actions["undo"].isEnabled()
        stack.push(_Nothing())
        assert actions["undo"].isEnabled()
        assert not actions["redo"].isEnabled()
        stack.undo()
        assert actions["redo"].isEnabled()


@pytest.fixture
def busy_view(qtbot, env, registry):
    graph, stack, scene = env
    for n in range(120):
        graph.add_node(registry.instantiate(
            FILTER, pos=((n % 12) * 300, (n // 12) * 250)))
    view = NodeGraphView(scene)
    view.resize(900, 600)
    qtbot.addWidget(view)
    view.show()
    qtbot.waitExposed(view)
    view.minimap.mark_stale()
    qtbot.wait(view.minimap.SETTLE_MS + 100)
    return graph, view


class TestMinimapDrawsFromASnapshot:

    def test_a_pan_retakes_nothing(self, qtbot, busy_view, monkeypatch):
        graph, view = busy_view
        minimap = view.minimap
        view.viewport().repaint()
        minimap.repaint()
        before = minimap.snapshots
        walks = _count(monkeypatch, type(minimap), "_snapshot")
        for _ in range(20):
            view.scroll_by(-25, 0)
            view.viewport().repaint()
            minimap.repaint()
        assert walks == []
        assert minimap.snapshots == before

    def test_a_move_is_retaken_once_it_settles(self, qtbot, busy_view):
        graph, view = busy_view
        minimap = view.minimap
        before = minimap.snapshots
        node = next(iter(graph.nodes.values()))
        for step in range(5):
            graph.move_node(node.id, (step * 10.0, 0.0))
        assert minimap.snapshots == before      # not one per change
        qtbot.waitUntil(lambda: minimap.snapshots == before + 1,
                        timeout=minimap.SETTLE_MS + 1000)
        qtbot.wait(minimap.SETTLE_MS + 100)
        assert minimap.snapshots == before + 1

    def test_the_map_shows_where_the_node_went(self, qtbot, busy_view):
        graph, view = busy_view
        minimap = view.minimap
        node = next(iter(graph.nodes.values()))
        graph.move_node(node.id, (-5000.0, -5000.0))
        qtbot.wait(minimap.SETTLE_MS + 100)
        minimap.repaint()
        assert minimap._items_rect.contains(QPointF(-4990.0, -4990.0))


class TestCardWidgetsPaintFromACache:

    def test_a_table_card_is_cached(self, env, registry):
        graph, stack, scene = env
        node = graph.add_node(registry.instantiate(TABLE))
        proxy = scene.node_items[node.id]._table_proxy
        assert proxy.cacheMode() == QGraphicsItem.DeviceCoordinateCache

    def test_the_shared_picture_cache_has_room(self, qtbot, env):
        from flograph.ui.proxy_cache import (PIXMAP_CACHE_MIN_KB,
                                             size_pixmap_cache)
        assert size_pixmap_cache() >= PIXMAP_CACHE_MIN_KB
        assert QPixmapCache.cacheLimit() >= PIXMAP_CACHE_MIN_KB


class TestReportTypingStaysLocal:

    @pytest.fixture
    def flow(self, registry):
        graph = Graph()
        graph.add_page(Page(id="r1", title="Weekly", kind="report",
                            body="# Weekly\n"))
        saver = graph.add_node(registry.instantiate(SAVE))
        graph.set_param(saver.id, "page", "r1")
        for n in range(50):
            graph.add_node(registry.instantiate(FILTER))
        return graph, saver

    def test_typing_prose_rederives_no_edges(self, flow, monkeypatch):
        graph, saver = flow
        graph.set_page_body("r1", "# Weekly\n\nS")
        rescans = _count(monkeypatch, Graph, "_refresh_links")
        text = "# Weekly\n\nS"
        for ch in "ales are up this week":
            text += ch
            graph.set_page_body("r1", text)
        assert rescans == []
        assert graph.nodes[saver.id].dirty

    def test_typing_an_embed_does(self, flow, monkeypatch):
        graph, saver = flow
        graph.set_page_body("r1", "# Weekly\n")
        rescans = _count(monkeypatch, Graph, "_refresh_links")
        graph.set_page_body("r1", "# Weekly\n\n![[Filter Rows]]\n")
        assert len(rescans) == 1


class TestSelectingIsOnePass:
    """Qt says selectionChanged once per item, and every listener reads the
    whole selection: selecting n items one by one cost n x n. Ctrl+A on 400
    nodes was a million calls."""

    @pytest.fixture
    def nodes(self, env, registry):
        graph, stack, scene = env
        return [graph.add_node(registry.instantiate(
            FILTER, pos=((n % 10) * 300, (n // 10) * 250))) for n in range(60)]

    def test_a_batch_is_announced_once(self, env, nodes):
        graph, stack, scene = env
        heard = []
        scene.selectionChanged.connect(lambda: heard.append(1))
        scene.select_items(scene.node_items.values())
        assert len(heard) == 1
        assert len(scene.selected_node_items()) == len(nodes)

    def test_nothing_new_is_not_announced(self, env, nodes):
        graph, stack, scene = env
        scene.select_items(scene.node_items.values())
        heard = []
        scene.selectionChanged.connect(lambda: heard.append(1))
        scene.select_items(scene.node_items.values())
        assert heard == []

    def test_unlinked_cards_are_not_touched(self, env, nodes, monkeypatch):
        graph, stack, scene = env
        from flograph.ui.canvas.node_item import NodeItem
        glows = _count(monkeypatch, NodeItem, "set_link_highlight")
        scene.select_items(scene.node_items.values())
        scene.clearSelection()
        assert glows == []


class TestTheScrollSpanAsksNoNode:
    """With the scroll bars on, the span is refitted after edits and while
    anything repaints. Measuring it through itemsBoundingRect asked every
    pin, label and wire for its bounds in Python — ~34k calls at 400 nodes,
    every 250 ms of a run."""

    @pytest.fixture
    def fitted(self, env, registry, monkeypatch):
        graph, stack, scene = env
        from flograph.ui.canvas.node_item import NodeItem
        # counted before the items exist: PySide resolves the override
        # when an item is made
        asked = _count(monkeypatch, NodeItem, "boundingRect")
        for n in range(40):
            graph.add_node(registry.instantiate(
                FILTER, pos=((n % 8) * 300, (n // 8) * 250)))
        scene.set_rect_fitted(True)
        return scene, asked

    def test_a_refit_asks_no_node(self, fitted):
        scene, asked = fitted
        asked.clear()
        scene.flush_rect_fit()
        assert asked == []

    def test_the_span_still_holds_every_node(self, fitted):
        scene, _asked = fitted
        scene.flush_rect_fit()
        span = scene.sceneRect()
        for item in scene.node_items.values():
            assert span.contains(item.sceneBoundingRect())

    def test_a_change_inside_the_flow_queues_nothing(self, fitted):
        scene, _asked = fitted
        scene.flush_rect_fit()
        middle = list(scene.node_items.values())[8 * 2 + 3]
        scene._queue_rect_fit([middle.sceneBoundingRect()])
        assert not scene._rect_timer.isActive()
        scene._queue_rect_fit([])     # Qt's "something repainted"
        assert scene._rect_timer.isActive()


class TestAFailureCostsWhatItReaches:
    """Each failure in a run looked at every node still pending, and
    gathered every edge in the graph: a run where many nodes fail cost the
    flow squared, on the window's thread."""

    def test_no_pending_node_is_asked_about_saving(self, qtbot, registry,
                                                   monkeypatch):
        from flograph.engine import ExecutionEngine
        from flograph.engine import scheduler
        graph = Graph()
        for n in range(60):       # unwired: each fails on its own
            graph.add_node(registry.instantiate(FILTER))
        asked = []
        original = scheduler.saves_anyway
        monkeypatch.setattr(scheduler, "saves_anyway",
                            lambda node: asked.append(node) or original(node))
        engine = ExecutionEngine(graph)
        with qtbot.waitSignal(engine.run_finished, timeout=15000) as blocker:
            engine.run_all()
        assert blocker.args[0] is False
        assert asked == []
