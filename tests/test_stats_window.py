"""The statistics window: run cost, project weight, canvas health.

Painted widgets are checked by counting inked pixels rather than by asserting
they are visible — a widget can report a perfectly good geometry and draw
nothing at all, which is exactly how an invisible glyph gets shipped.
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from flograph.core import Graph, NodeRegistry
from flograph.engine.runstats import NodeRun, RunRecord
from flograph.engine.scheduler import ExecutionEngine
from flograph.ui import theme
from flograph.ui.mainwindow import MainWindow
from flograph.ui.stats_window import (CanvasTab, FrameStrip, GraphTab, RunTab,
                                      RunTimeline, SortableItem, StatsWindow)

SCRIPT = "flograph.scripting.python_script"


def source(label, body, inputs="[]"):
    return (f'NODE = {{"label": "{label}", "category": "T", '
            f'"inputs": {inputs}, "outputs": [("result", "any")]}}\n{body}\n')


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


def ink(widget, background: QColor = theme.CANVAS_BG) -> int:
    """Pixels that are not the background — "did this actually draw"."""
    image = widget.grab().toImage()
    bg = background.rgb() & 0x00FFFFFF
    return sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if (image.pixel(x, y) & 0x00FFFFFF) != bg
    )


def sample_record() -> RunRecord:
    return RunRecord(
        wall_time=4.0, ok=False,
        skipped_clean=2, skipped_frozen=1, skipped_inactive=3,
        rss_start=1000, rss_peak=5000,
        nodes=[
            NodeRun("a", "Read CSV", "ok", started=0.0, wall_time=3.0,
                    output_bytes=2048, summary="900 rows × 3 cols",
                    rss_start=1000, rss_peak=4000),
            NodeRun("b", "Tidy", "ok", started=3.0, wall_time=0.5,
                    output_bytes=64, summary="int · 4"),
            NodeRun("c", "Export", "failed", started=3.5, wall_time=0.1),
        ])


class TestSortableItem:
    def test_sorts_on_the_key_not_the_text(self):
        """Every number in the tables is formatted, so sorting on the
        displayed string would put '9 ms' after '10 s'."""
        small = SortableItem("9 ms", 0.009)
        large = SortableItem("10 s", 10.0)
        assert small < large
        assert not (large < small)

    def test_cells_are_not_editable(self):
        assert not (SortableItem("x", 0).flags() & Qt.ItemIsEditable)


class TestRunTimeline:
    def test_says_so_when_there_is_nothing_to_show(self, qtbot):
        timeline = RunTimeline()
        qtbot.addWidget(timeline)
        timeline.resize(400, 60)
        timeline.set_record(None)
        assert ink(timeline) > 0          # the placeholder text

    def test_draws_a_bar_per_node(self, qtbot):
        timeline = RunTimeline()
        qtbot.addWidget(timeline)
        timeline.resize(400, 200)
        timeline.set_record(sample_record())
        assert ink(timeline) > 200

    def test_rows_share_a_tall_panel_without_becoming_absurd(self, qtbot):
        """Given the whole sub-tab, a three-node run should spread out — but
        only up to a point, not one bar per third of the window."""
        timeline = RunTimeline()
        qtbot.addWidget(timeline)
        timeline.resize(500, 600)
        timeline.set_record(sample_record())
        image = timeline.grab().toImage()
        rows_with_ink = sum(
            1 for y in range(image.height())
            if any((image.pixel(x, y) & 0x00FFFFFF)
                   != (theme.CANVAS_BG.rgb() & 0x00FFFFFF)
                   for x in range(0, image.width(), 7)))
        assert 0 < rows_with_ink < image.height() / 2

    def test_grows_to_fit_its_rows(self, qtbot):
        timeline = RunTimeline()
        qtbot.addWidget(timeline)
        before = timeline.minimumHeight()
        timeline.set_record(sample_record())
        assert timeline.minimumHeight() > before

    def test_a_failed_node_is_drawn_in_the_error_colour(self, qtbot):
        timeline = RunTimeline()
        qtbot.addWidget(timeline)
        timeline.resize(400, 200)
        timeline.set_record(sample_record())
        image = timeline.grab().toImage()
        target = theme.WIRE_INVALID.rgb() & 0x00FFFFFF
        found = any((image.pixel(x, y) & 0x00FFFFFF) == target
                    for y in range(image.height())
                    for x in range(image.width()))
        assert found


class TestFrameStrip:
    def test_prompts_when_nothing_has_been_drawn(self, qtbot):
        strip = FrameStrip()
        qtbot.addWidget(strip)
        strip.resize(300, 64)
        strip.set_frames([])
        assert ink(strip) > 0

    def test_draws_a_bar_per_frame(self, qtbot):
        strip = FrameStrip()
        qtbot.addWidget(strip)
        strip.resize(300, 64)
        strip.set_frames([0.004] * 30)
        assert ink(strip) > 100

    def test_an_over_budget_frame_is_red(self, qtbot):
        strip = FrameStrip()
        qtbot.addWidget(strip)
        strip.resize(300, 64)
        strip.set_frames([0.004, 0.004, 0.100])
        image = strip.grab().toImage()
        target = theme.WIRE_INVALID.rgb() & 0x00FFFFFF
        assert any((image.pixel(x, y) & 0x00FFFFFF) == target
                   for y in range(image.height())
                   for x in range(image.width()))

    def test_a_comfortable_canvas_stays_under_the_line(self, qtbot):
        """Scaling to the worst frame alone would stretch a fast canvas to
        fill the box and make it look like it was struggling."""
        strip = FrameStrip()
        qtbot.addWidget(strip)
        strip.resize(300, 64)
        strip.set_frames([0.001] * 20)
        image = strip.grab().toImage()
        target = theme.WIRE_INVALID.rgb() & 0x00FFFFFF
        assert not any((image.pixel(x, y) & 0x00FFFFFF) == target
                       for y in range(image.height())
                       for x in range(image.width()))


class TestRunTab:
    def _tab(self, qtbot, engine):
        tab = RunTab(engine)
        qtbot.addWidget(tab)
        return tab

    def test_says_nothing_has_run(self, qtbot):
        tab = self._tab(qtbot, ExecutionEngine(Graph()))
        tab.refresh()
        assert "Nothing has run" in tab.summary.text()
        assert tab.table.rowCount() == 0

    def test_fills_a_row_per_node(self, qtbot):
        engine = ExecutionEngine(Graph())
        engine.history.add(sample_record())
        tab = self._tab(qtbot, engine)
        tab.refresh()
        assert tab.table.rowCount() == 3

    def test_summary_breaks_the_run_down(self, qtbot):
        engine = ExecutionEngine(Graph())
        engine.history.add(sample_record())
        tab = self._tab(qtbot, engine)
        tab.refresh()
        text = tab.summary.text()
        assert "in nodes" in text and "scheduling" in text
        assert "6 skipped" in text          # 2 cached + 1 frozen + 3 off
        assert "1 failed: Export" in text

    def test_opens_sorted_by_time(self, qtbot):
        """The tab exists to answer 'what was slow', so the slow one has to
        be the first row without anybody clicking anything."""
        engine = ExecutionEngine(Graph())
        engine.history.add(sample_record())
        tab = self._tab(qtbot, engine)
        tab.refresh()
        assert tab.table.item(0, 0).text() == "Read CSV"

    def test_the_picker_lists_every_run_newest_first(self, qtbot):
        engine = ExecutionEngine(Graph())
        for _ in range(3):
            engine.history.add(sample_record())
        tab = self._tab(qtbot, engine)
        tab.refresh()
        assert tab.picker.count() == 3
        assert tab.picker.itemText(0).startswith("latest")
        assert "2 runs ago" in tab.picker.itemText(2)

    def test_choosing_an_older_run_shows_that_run(self, qtbot):
        engine = ExecutionEngine(Graph())
        engine.history.add(RunRecord(wall_time=1.0, nodes=[
            NodeRun("x", "Only", wall_time=1.0)]))
        engine.history.add(sample_record())
        tab = self._tab(qtbot, engine)
        tab.refresh()
        assert tab.table.rowCount() == 3
        tab.picker.setCurrentIndex(1)
        assert tab.table.rowCount() == 1
        assert tab.table.item(0, 0).text() == "Only"

    def test_timeline_and_table_are_sub_tabs(self, qtbot):
        tab = self._tab(qtbot, ExecutionEngine(Graph()))
        assert [tab.sub_tabs.tabText(i)
                for i in range(tab.sub_tabs.count())] == ["Timeline", "Table"]

    def test_the_picker_and_summary_sit_above_both(self, qtbot):
        """They describe the run rather than either view of it, so switching
        sub-tab must not change or hide them."""
        engine = ExecutionEngine(Graph())
        engine.history.add(sample_record())
        tab = self._tab(qtbot, engine)
        tab.refresh()
        before = (tab.picker.currentText(), tab.summary.text())
        tab.sub_tabs.setCurrentIndex(1)
        assert (tab.picker.currentText(), tab.summary.text()) == before

    def test_both_sub_tabs_follow_the_selected_run(self, qtbot):
        engine = ExecutionEngine(Graph())
        engine.history.add(RunRecord(wall_time=1.0, nodes=[
            NodeRun("x", "Only", wall_time=1.0)]))
        engine.history.add(sample_record())
        tab = self._tab(qtbot, engine)
        tab.refresh()
        tab.picker.setCurrentIndex(1)
        assert tab.table.rowCount() == 1
        assert tab.timeline._record.nodes[0].label == "Only"

    def test_a_cancelled_run_says_so(self, qtbot):
        record = sample_record()
        record.cancelled = True
        engine = ExecutionEngine(Graph())
        engine.history.add(record)
        tab = self._tab(qtbot, engine)
        tab.refresh()
        assert "Cancelled" in tab.summary.text()


class TestGraphTab:
    def test_counts_an_empty_project(self, qtbot):
        tab = GraphTab(ExecutionEngine(Graph()))
        qtbot.addWidget(tab)
        tab.refresh()
        assert "<b>0</b> nodes" in tab.counts.text()
        assert tab.table.rowCount() == 0

    def test_counts_node_states(self, qtbot, registry):
        graph = Graph()
        a = graph.add_node(registry.instantiate("flograph.util.constant"))
        b = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_frozen(a.id, True)
        graph.set_active(b.id, False)
        graph.set_locked(b.id, True)
        tab = GraphTab(ExecutionEngine(graph))
        qtbot.addWidget(tab)
        tab.refresh()
        text = tab.counts.text()
        assert "<b>2</b> nodes" in text
        assert "1 frozen" in text and "1 deactivated" in text and "1 locked" in text

    def test_lists_cached_nodes_heaviest_first(self, qtbot, registry):
        graph = Graph()
        engine = ExecutionEngine(graph)
        small = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(small.id, source("Small", "def run(ctx):\n    return 1"))
        big = graph.add_node(registry.instantiate(SCRIPT))
        graph.set_code(big.id, source("Big", (
            "import pandas as pd\ndef run(ctx):\n"
            "    return pd.DataFrame({'a': range(5000)})")))
        with qtbot.waitSignal(engine.run_finished, timeout=20000):
            engine.run_all()
        tab = GraphTab(engine)
        qtbot.addWidget(tab)
        tab.refresh()
        assert tab.table.rowCount() == 2
        assert tab.table.item(0, 0).text() == "Big"

    def test_a_shared_value_is_marked(self, qtbot, registry):
        graph = Graph()
        engine = ExecutionEngine(graph)
        const = graph.add_node(registry.instantiate("flograph.util.constant"))
        dot = graph.add_node(registry.instantiate("flograph.util.reroute"))
        graph.connect(const.id, "value", dot.id, "value")
        with qtbot.waitSignal(engine.run_finished, timeout=20000):
            engine.run_all()
        tab = GraphTab(engine)
        qtbot.addWidget(tab)
        tab.refresh()
        states = {tab.table.item(r, 0).text(): tab.table.item(r, 3).text()
                  for r in range(tab.table.rowCount())}
        assert "shared" in states["Reroute"]


class TestCanvasTab:
    def test_reports_paint_cost_and_item_counts(self, qtbot, window):
        tab = CanvasTab(window)
        qtbot.addWidget(tab)
        window.view.paint_stats.record(0.004)
        tab.refresh()
        assert "ms" in tab.paint.text()
        assert "items in view" in tab.items.text()

    def test_says_nothing_drawn_before_any_frame(self, qtbot, window):
        tab = CanvasTab(window)
        qtbot.addWidget(tab)
        window.view.paint_stats.reset()
        tab.refresh()
        assert "Nothing drawn yet" in tab.paint.text()

    def test_a_comfortable_canvas_is_reported_as_such(self, qtbot, window):
        tab = CanvasTab(window)
        qtbot.addWidget(tab)
        window.view.paint_stats.reset()
        window.view.paint_stats.record(0.002)
        tab.refresh()
        assert "comfortably" in tab.advice.text()

    def test_slow_painting_names_the_lever(self, qtbot, window):
        tab = CanvasTab(window)
        qtbot.addWidget(tab)
        window.view.paint_stats.reset()
        window.view.paint_stats.record(0.120)
        window.scene.lod_enabled = False
        tab.refresh()
        assert "Simplify nodes when zoomed out" in tab.advice.text()

    def test_reports_the_lod_state(self, qtbot, window):
        tab = CanvasTab(window)
        qtbot.addWidget(tab)
        window.scene.lod_enabled = True
        tab.refresh()
        assert "simplification on" in tab.items.text()


class TestStatsWindow:
    def test_has_the_three_tabs(self, qtbot, window):
        stats = StatsWindow(window)
        qtbot.addWidget(stats)
        assert [stats.tabs.tabText(i)
                for i in range(stats.tabs.count())] == ["Run", "Graph", "Canvas"]

    def test_refreshes_without_a_run(self, qtbot, window):
        stats = StatsWindow(window)
        qtbot.addWidget(stats)
        stats.refresh()
        assert "Nothing has run" in stats.run_tab.summary.text()

    def test_is_modeless(self, qtbot, window):
        """It is meant to be left open beside the canvas during a run."""
        stats = StatsWindow(window)
        qtbot.addWidget(stats)
        assert stats.isModal() is False

    def test_the_timer_only_runs_while_it_is_visible(self, qtbot, window):
        stats = StatsWindow(window)
        qtbot.addWidget(stats)
        assert not stats._timer.isActive()
        stats.show()
        assert stats._timer.isActive()
        stats.hide()
        assert not stats._timer.isActive()

    def test_the_window_holds_one_instance(self, qtbot, window):
        window._show_stats()
        first = window._stats_window
        window._show_stats()
        assert window._stats_window is first

    def test_clicking_the_status_bar_opens_it(self, qtbot, window):
        assert window._stats_window is None
        window.resource_monitor.clicked.emit()
        assert window._stats_window is not None

    def test_a_real_run_lands_in_the_window(self, qtbot, window, registry):
        node = window.graph.add_node(registry.instantiate(SCRIPT))
        window.graph.set_code(node.id, source(
            "Work", "import time\ndef run(ctx):\n    time.sleep(0.05)\n    return 7"))
        with qtbot.waitSignal(window.engine.run_finished, timeout=20000):
            window.engine.run_all()
        stats = StatsWindow(window)
        qtbot.addWidget(stats)
        stats.refresh()
        assert stats.run_tab.table.rowCount() == 1
        assert stats.run_tab.table.item(0, 0).text() == "Work"
