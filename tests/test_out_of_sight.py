"""AE2: what nobody can see costs nothing.

A busy flow froze the window because every card re-rendered after every
run — the report card below the fold, the tables on a dashboard page
behind the canvas. Out of sight, a refresh now waits until the card comes
into view. And the watch that measures such freezes (`core.perf`,
`ui.perf`) is tested here too, since the benchmark depends on it."""
import json
import time

import pytest
from PySide6.QtCore import QObject, QPointF, QSettings, QTimer, Signal

from flograph.core import NodeRegistry, Page, Tile, perf
from flograph.ui import mainwindow as mod
from flograph.ui.commands import AddPageCommand, AddTileCommand
from flograph.ui.mainwindow import MainWindow


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


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
    return win


def _table(win, pos=(-300, 0)):
    node = win.registry.instantiate("flograph.io.table", pos=pos)
    win.graph.add_node(node)
    win.graph.set_param(node.id, "data", json.dumps({
        "columns": ["x"], "rows": [["1"], ["2"], ["3"]]}))
    return node


def _show_table(win, source, pos):
    node = win.registry.instantiate("flograph.viz.show_table", pos=pos)
    win.graph.add_node(node)
    win.graph.connect(source.id, "table", node.id, "table")
    return node


def _run(win, qtbot):
    with qtbot.waitSignal(win.engine.run_finished, timeout=20000) as blocker:
        win.engine.run_all()
    assert blocker.args[0], "run finished with a node failure"


# ------------------------------------------------------------ core.perf

class TestTimed:
    def test_totals_by_label(self):
        perf.reset()
        with perf.timed("t: block"):
            pass
        with perf.timed("t: block"):
            pass
        assert perf.tallies()["t: block"].count == 2

    def test_a_decorated_slot_takes_what_it_asks_for(self, qapp):
        """PySide drops the arguments a plain slot doesn't take. A wrapper
        taking *args would be handed all of them — and raise."""
        class Sender(QObject):
            fired = Signal(bool, str)

        calls = []

        class Receiver(QObject):
            @perf.timed("t: slot")
            def refresh(self):
                calls.append(True)

        sender, receiver = Sender(), Receiver()
        sender.fired.connect(receiver.refresh)
        sender.fired.emit(True, "x")
        assert calls == [True]

    def test_the_watchdog_names_the_block_it_waited_on(self, qtbot):
        from flograph.ui.perf import StallWatchdog

        dog = StallWatchdog()
        dog.start()

        def hog():
            with perf.timed("t: hog"):
                time.sleep(0.4)

        QTimer.singleShot(150, hog)
        qtbot.waitUntil(lambda: dog.count >= 1, timeout=3000)
        dog.stop()
        assert dog.longest >= 0.25
        assert dog.longest_label == "t: hog"


# ------------------------------------------------------ canvas cards

class TestCanvasCards:
    def test_a_card_out_of_view_waits_until_it_is_scrolled_to(
            self, window, qtbot):
        win = window
        source = _table(win)
        far = _show_table(win, source, pos=(40000, 40000))
        win.resize(1200, 800)
        win.show()
        qtbot.waitExposed(win)
        win.view.center_on_scene(QPointF(0, 0))
        item = win.scene.node_items[far.id]

        _run(win, qtbot)
        assert "output" in item.deferred_refreshes
        assert item._table_viewer_view.model() is None

        win.view.center_on_scene(item.sceneBoundingRect().center())
        qtbot.waitUntil(lambda: not item.deferred_refreshes, timeout=3000)
        assert item._table_viewer_view.model().rowCount() == 3

    def test_a_card_in_view_refreshes_at_once(self, window, qtbot):
        win = window
        source = _table(win)
        near = _show_table(win, source, pos=(300, 0))
        win.resize(1200, 800)
        win.show()
        qtbot.waitExposed(win)
        item = win.scene.node_items[near.id]
        win.view.center_on_scene(item.sceneBoundingRect().center())

        _run(win, qtbot)
        assert not item.deferred_refreshes
        assert item._table_viewer_view.model().rowCount() == 3

    def test_a_window_not_showing_refreshes_everything(self, window, qtbot):
        """Tests and a window still being built see every card, so nothing
        that worked eagerly before starts waiting."""
        win = window
        source = _table(win)
        far = _show_table(win, source, pos=(40000, 40000))
        _run(win, qtbot)
        item = win.scene.node_items[far.id]
        assert item._table_viewer_view.model().rowCount() == 3


# ------------------------------------------------------ catching up

class TestCatchingUp:
    """Put off is not skipped: once nobody is moving, the waiting cards are
    rebuilt a card at a time, nearest first, so a later pan finds them
    ready instead of rebuilding them under the pointer (ui.catch_up)."""

    def _shown(self, win, qtbot):
        win.resize(1200, 800)
        win.show()
        qtbot.waitExposed(win)
        win.view.center_on_scene(QPointF(0, 0))

    def test_a_far_card_fills_while_nobody_moves(self, window, qtbot):
        win = window
        source = _table(win)
        far = _show_table(win, source, pos=(40000, 40000))
        self._shown(win, qtbot)
        item = win.scene.node_items[far.id]

        _run(win, qtbot)
        assert "output" in item.deferred_refreshes
        qtbot.waitUntil(lambda: not item.deferred_refreshes, timeout=5000)
        assert item._table_viewer_view.model().rowCount() == 3

    def test_the_nearest_goes_first(self, window, qtbot, monkeypatch):
        win = window
        source = _table(win)
        self._shown(win, qtbot)
        area = win.view.mapToScene(win.view.viewport().rect()).boundingRect()
        far = _show_table(win, source, pos=(area.right() + 40000, 0))
        near = _show_table(win, source, pos=(area.right() + 200, 0))
        order = []
        for node in (far, near):
            item = win.scene.node_items[node.id]
            original = item.flush_deferred
            monkeypatch.setattr(
                item, "flush_deferred",
                lambda n=node, f=original: (order.append(n.id), f()))

        _run(win, qtbot)
        qtbot.waitUntil(lambda: len(order) == 2, timeout=5000)
        assert order == [near.id, far.id]

    def test_nothing_is_rebuilt_while_a_button_is_held(
            self, window, qtbot, monkeypatch):
        from PySide6.QtCore import Qt

        from flograph.ui import catch_up

        win = window
        source = _table(win)
        far = _show_table(win, source, pos=(40000, 40000))
        self._shown(win, qtbot)
        item = win.scene.node_items[far.id]
        held = [True]
        monkeypatch.setattr(
            catch_up.QApplication, "mouseButtons",
            lambda: Qt.LeftButton if held[0] else Qt.NoButton)

        _run(win, qtbot)
        qtbot.wait(catch_up.IDLE_S * 1000 + 400)
        assert "output" in item.deferred_refreshes

        held[0] = False
        qtbot.waitUntil(lambda: not item.deferred_refreshes, timeout=5000)

    def test_a_far_web_card_waits_for_a_pan_to_come_near(
            self, window, qtbot):
        """Each web card wakes a Chromium renderer and holds its memory,
        so one far away is not loaded just in case."""
        from flograph.ui import catch_up

        win = window
        source = _table(win)
        chart = win.registry.instantiate("flograph.viz.show_plotly",
                                         pos=(40000, 40000))
        win.graph.add_node(chart)
        win.graph.connect(source.id, "table", chart.id, "table")
        self._shown(win, qtbot)
        item = win.scene.node_items[chart.id]

        _run(win, qtbot)
        qtbot.wait(catch_up.IDLE_S * 1000 + 400)
        assert "output" in item.deferred_refreshes

        area = win.view.mapToScene(win.view.viewport().rect()).boundingRect()
        rect = item.sceneBoundingRect()
        # half a screen short of it: near, not yet in sight
        win.view.center_on_scene(QPointF(
            rect.left() - area.width(), rect.center().y()))
        assert not win.scene.can_see(item)
        qtbot.waitUntil(lambda: not item.deferred_refreshes, timeout=5000)

    def test_a_hidden_page_fills_while_nobody_moves(self, window, qtbot):
        win = window
        source = _table(win)
        show = _show_table(win, source, pos=(300, 0))
        win.undo_stack.push(AddPageCommand(win.graph, Page(id="p1",
                                                           title="Board")))
        win.undo_stack.push(AddTileCommand(win.graph, "p1", Tile(
            id="t1", node_id=show.id, port="table")))
        page = win._dashboard_pages["p1"]
        tile = page.scene.tile_items["t1"]
        win.show()
        qtbot.waitExposed(win)
        win.page_bar.select_page(None)
        qtbot.waitUntil(lambda: not page.isVisible(), timeout=2000)

        _run(win, qtbot)
        assert "t1" in page.scene._stale_tiles
        qtbot.waitUntil(lambda: not page.scene._stale_tiles, timeout=5000)
        assert not page.isVisible()
        assert tile._table_view.model().rowCount() == 3


# ------------------------------------------------------ dashboard pages

class TestHiddenPages:
    def test_a_hidden_page_fills_its_tiles_when_shown(self, window, qtbot):
        win = window
        source = _table(win)
        show = _show_table(win, source, pos=(300, 0))
        win.undo_stack.push(AddPageCommand(win.graph, Page(id="p1",
                                                           title="Board")))
        win.undo_stack.push(AddTileCommand(win.graph, "p1", Tile(
            id="t1", node_id=show.id, port="table")))
        page = win._dashboard_pages["p1"]
        tile = page.scene.tile_items["t1"]
        win.show()
        qtbot.waitExposed(win)
        win.page_bar.select_page(None)              # the canvas, not p1
        qtbot.waitUntil(lambda: not page.isVisible(), timeout=2000)

        _run(win, qtbot)
        assert "t1" in page.scene._stale_tiles

        win.page_bar.select_page("p1")
        qtbot.waitUntil(lambda: not page.scene._stale_tiles, timeout=3000)
        assert tile._table_view.model().rowCount() == 3


# ------------------------------------------------------ report cards

class TestReportCards:
    def _card(self, win, text, pos=(600, 0)):
        node = win.registry.instantiate("flograph.viz.report_card", pos=pos)
        win.graph.add_node(node)
        win.graph.set_param(node.id, "text", text)
        return node

    def _count_renders(self, win, node, monkeypatch):
        item = win.scene.node_items[node.id]
        calls = []
        original = item.refresh_report
        monkeypatch.setattr(item, "refresh_report",
                            lambda: (calls.append(1), original()))
        return calls

    def test_a_run_that_touches_nothing_it_shows_leaves_it_alone(
            self, window, qtbot, monkeypatch):
        win = window
        wired = _table(win)
        card = self._card(win, "# Report\n\n![[a]]\n")
        win.graph.connect(wired.id, "table", card.id, "a")
        _run(win, qtbot)
        qtbot.wait(200)                     # let the param coalescer drain

        unrelated = _table(win, pos=(-300, 400))
        calls = self._count_renders(win, card, monkeypatch)
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_targets([unrelated.id])
        assert calls == []

    def test_a_node_it_names_by_label_re_renders_it(
            self, window, qtbot, monkeypatch):
        win = window
        named = _table(win)
        win.graph.set_label(named.id, "Sales")
        card = self._card(win, "# Report\n\n![[Sales|rows=5]]\n")
        _run(win, qtbot)
        qtbot.wait(200)

        calls = self._count_renders(win, card, monkeypatch)
        win.graph.set_param(named.id, "data", json.dumps({
            "columns": ["x"], "rows": [["9"]]}))
        with qtbot.waitSignal(win.engine.run_finished, timeout=20000):
            win.engine.run_targets([named.id])
        assert calls


# ------------------------------------------------------ saying it is busy

class TestSayingItIsBusy:
    def test_busy_puts_the_cursor_back_even_on_an_error(self, window):
        from PySide6.QtGui import QGuiApplication

        from flograph.ui.busy import busy

        with pytest.raises(ValueError):
            with busy(window, "Opening a.flograph…"):
                assert QGuiApplication.overrideCursor() is not None
                assert window._status_label.text() == "Opening a.flograph…"
                raise ValueError("boom")
        assert QGuiApplication.overrideCursor() is None

    def test_a_long_freeze_is_named_afterwards(self, window):
        window._on_stall(1.8, "report card render")
        assert window._status_label.text() == (
            "The window was busy for 1.8 s (report card render)")

    def test_a_short_hitch_is_not_worth_a_word(self, window):
        window.show_status("")
        window._on_stall(0.4, "tile")
        assert window._status_label.text() == ""
