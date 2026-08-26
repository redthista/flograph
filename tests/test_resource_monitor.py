"""Status bar resource monitor: the layered memory bar, the last run's cost,
and the selected node's — plus the drive watch that says when the project's
disk is running out."""
from types import SimpleNamespace

import pandas as pd
import pytest

from flograph.core import Graph, NodeRegistry
from flograph.engine import ExecutionEngine
from flograph.engine.cache import estimate_size
from flograph.engine.pressure import DISK_RELIEF, LOW_DISK_FREE, disk_is_low
from flograph.ui.resource_monitor import (MemoryBar, ResourceMonitorWidget,
                                          format_bytes, format_seconds)


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


class TestFormatBytes:
    def test_small_values_stay_in_bytes(self):
        assert format_bytes(512) == "512 B"

    def test_scales_to_kb_mb_gb(self):
        assert format_bytes(2048) == "2.0 KB"
        assert format_bytes(5 * 1024 * 1024) == "5.0 MB"
        assert format_bytes(3 * 1024 ** 3) == "3.0 GB"


class TestEstimateSize:
    def test_dataframe_uses_deep_memory_usage(self):
        df = pd.DataFrame({"a": range(1000), "b": ["x"] * 1000})
        expected = int(df.memory_usage(deep=True).sum())
        assert estimate_size(df) == expected

    def test_dict_sums_nested_values(self):
        assert estimate_size({"a": 1, "b": 2}) > 0

    def test_none_is_cheap(self):
        assert estimate_size(None) >= 0

    def test_a_series_is_measured_rather_than_raising(self):
        """Series.memory_usage answers with a plain int where DataFrame
        answers with a Series, so the shared `.sum()` used to raise — inside
        the engine's completion slot, which left the run unfinished and the
        Run button disabled for anything containing a groupby."""
        s = pd.Series(range(500))
        assert estimate_size(s) == int(s.memory_usage(deep=True))

    def test_a_grouped_result_is_measured(self):
        df = pd.DataFrame({"k": ["a", "b"] * 50, "v": range(100)})
        assert estimate_size(df.groupby("k").size()) > 0

    def test_an_index_is_measured(self):
        assert estimate_size(pd.DataFrame({"a": range(10)}).index) > 0

    def test_an_unmeasurable_value_is_worth_zero_not_an_exception(self):
        class Hostile:
            def __sizeof__(self):
                raise RuntimeError("no")

        assert estimate_size(Hostile()) == 0


class TestResourceMonitorWidget:
    def _run(self, qtbot, engine):
        with qtbot.waitSignal(engine.run_finished, timeout=5000):
            engine.run_all()

    def test_shows_placeholder_with_no_node_selected(self, qtbot, registry):
        graph = Graph()
        engine = ExecutionEngine(graph)
        widget = ResourceMonitorWidget(engine)
        qtbot.addWidget(widget)
        assert widget._node_label.text() == "Node: —"
        assert widget._run_label.text() == "Run: —"
        assert "/" in widget._mem_label.text()      # used / total
        assert widget.bar.cache_bytes == 0

    def test_file_total_sums_all_cached_nodes(self, qtbot, registry, tmp_path):
        csv = tmp_path / "d.csv"
        csv.write_text("a,b\n1,2\n3,4\n")
        graph = Graph()
        engine = ExecutionEngine(graph)
        r1 = graph.add_node(registry.instantiate("flograph.io.read_csv"))
        r2 = graph.add_node(registry.instantiate("flograph.io.read_csv"))
        graph.set_param(r1.id, "path", str(csv))
        graph.set_param(r2.id, "path", str(csv))

        widget = ResourceMonitorWidget(engine)
        qtbot.addWidget(widget)
        self._run(qtbot, engine)
        widget._refresh()

        expected = engine.cache.get(r1.id).memory_bytes + engine.cache.get(r2.id).memory_bytes
        assert engine.cache.total_bytes() == expected
        # the total moved from a label into the bar and the tooltip
        assert widget.bar.cache_bytes == expected
        assert format_bytes(expected) in widget.toolTip()

    def test_shows_cache_size_for_selected_node(self, qtbot, registry, tmp_path):
        csv = tmp_path / "d.csv"
        csv.write_text("a,b\n1,2\n3,4\n")
        graph = Graph()
        engine = ExecutionEngine(graph)
        reader = graph.add_node(registry.instantiate("flograph.io.read_csv"))
        graph.set_param(reader.id, "path", str(csv))

        widget = ResourceMonitorWidget(engine)
        qtbot.addWidget(widget)
        widget.set_node(reader.id)
        assert widget._node_label.text() == "Node: —"

        self._run(qtbot, engine)
        widget.set_node(reader.id)
        entry = engine.cache.get(reader.id)
        assert entry is not None
        assert entry.memory_bytes > 0
        assert format_bytes(entry.memory_bytes) in widget._node_label.text()

    def test_clearing_selection_reverts_to_placeholder(self, qtbot, registry, tmp_path):
        csv = tmp_path / "d.csv"
        csv.write_text("a,b\n1,2\n")
        graph = Graph()
        engine = ExecutionEngine(graph)
        reader = graph.add_node(registry.instantiate("flograph.io.read_csv"))
        graph.set_param(reader.id, "path", str(csv))

        widget = ResourceMonitorWidget(engine)
        qtbot.addWidget(widget)
        self._run(qtbot, engine)
        widget.set_node(reader.id)
        assert "Node: —" not in widget._node_label.text()

        widget.set_node(None)
        assert widget._node_label.text() == "Node: —"


class TestFormatSeconds:
    def test_sub_second_reads_in_milliseconds(self):
        assert format_seconds(0.042) == "42 ms"

    def test_seconds_keep_one_decimal(self):
        assert format_seconds(4.24) == "4.2 s"

    def test_long_runs_break_into_minutes(self):
        assert format_seconds(125) == "2m 5s"


class TestMemoryBar:
    def test_clamps_cache_inside_the_process(self, qtbot):
        """estimate_size measures a value's footprint, which is not its
        contribution to resident memory — the inner segment must not be able
        to overflow the outer one."""
        bar = MemoryBar()
        qtbot.addWidget(bar)
        bar.set_values(cache=900, process=400, used=800, total=1000)
        # drawing is what does the clamping; the stored values stay honest
        assert bar.cache_bytes == 900 and bar.process_bytes == 400
        bar.grab()          # must not raise or draw past the track

    def test_a_zero_total_does_not_divide_by_zero(self, qtbot):
        bar = MemoryBar()
        qtbot.addWidget(bar)
        bar.set_values(0, 0, 0, 0)
        assert bar.total_bytes == 1
        bar.grab()

    def test_negatives_are_floored(self, qtbot):
        bar = MemoryBar()
        qtbot.addWidget(bar)
        bar.set_values(-5, -5, -5, 100)
        assert (bar.cache_bytes, bar.process_bytes, bar.used_bytes) == (0, 0, 0)


class TestRunReadout:
    def test_reports_the_last_run(self, qtbot, registry, tmp_path):
        csv = tmp_path / "d.csv"
        csv.write_text("a,b\n1,2\n")
        graph = Graph()
        engine = ExecutionEngine(graph)
        reader = graph.add_node(registry.instantiate("flograph.io.read_csv"))
        graph.set_param(reader.id, "path", str(csv))
        widget = ResourceMonitorWidget(engine)
        qtbot.addWidget(widget)

        with qtbot.waitSignal(engine.run_finished, timeout=5000):
            engine.run_all()
        widget._refresh()
        assert widget._run_label.text().startswith("Run: ")
        assert widget._run_label.text() != "Run: —"

    def test_says_so_when_a_run_had_errors(self, qtbot, registry):
        graph = Graph()
        engine = ExecutionEngine(graph)
        node = graph.add_node(
            registry.instantiate("flograph.scripting.python_script"))
        graph.set_code(node.id, (
            'NODE = {"label": "Boom", "category": "T", "inputs": [], '
            '"outputs": [("result", "any")]}\n'
            'def run(ctx):\n    raise ValueError("no")\n'))
        widget = ResourceMonitorWidget(engine)
        qtbot.addWidget(widget)

        with qtbot.waitSignal(engine.run_finished, timeout=5000):
            engine.run_all()
        widget._refresh()
        assert "errors" in widget._run_label.text()

    def test_a_shared_value_is_labelled(self, qtbot, registry):
        """A Goto re-serving its source is not a second copy, and the readout
        has to say so or the same frame looks like it is in memory twice."""
        graph = Graph()
        engine = ExecutionEngine(graph)
        const = graph.add_node(registry.instantiate("flograph.util.constant"))
        dot = graph.add_node(registry.instantiate("flograph.util.reroute"))
        graph.connect(const.id, "value", dot.id, "value")
        widget = ResourceMonitorWidget(engine)
        qtbot.addWidget(widget)

        with qtbot.waitSignal(engine.run_finished, timeout=5000):
            engine.run_all()
        widget.set_node(dot.id)
        assert "shared" in widget._node_label.text()


class TestDiskIsLow:
    def test_under_the_line_warns_and_over_it_does_not(self):
        assert disk_is_low(LOW_DISK_FREE - 1)
        assert not disk_is_low(LOW_DISK_FREE + 1024 ** 3)

    def test_hysteresis_keeps_the_warning_until_space_returns(self):
        # just above the line: quiet unless already warning, then still loud
        assert not disk_is_low(LOW_DISK_FREE + 1024, already_warning=False)
        assert disk_is_low(LOW_DISK_FREE + 1024, already_warning=True)
        # past the relief band the warning clears
        assert not disk_is_low(LOW_DISK_FREE + DISK_RELIEF + 1,
                               already_warning=True)

    def test_an_unreadable_drive_warns_about_nothing(self):
        assert not disk_is_low(-1)


class TestDiskWatch:
    """The widget's drive watch: announce once on entering low space, clear
    on leaving it, stay silent when nothing is watched."""

    def _widget(self, qtbot):
        engine = ExecutionEngine(Graph())
        widget = ResourceMonitorWidget(engine)
        qtbot.addWidget(widget)
        return widget

    def _watch(self, monkeypatch, usage_box):
        import flograph.ui.resource_monitor as rm
        monkeypatch.setattr(
            rm.shutil, "disk_usage",
            lambda drive: SimpleNamespace(free=usage_box["free"], total=10 ** 9))

    def test_low_disk_is_announced_once_and_cleared_once(
            self, qtbot, monkeypatch):
        usage_box = {"free": LOW_DISK_FREE - 500 * 1024 ** 2}
        self._watch(monkeypatch, usage_box)
        widget = self._widget(qtbot)
        seen = []
        widget.disk_changed.connect(seen.append)

        # watching a drive that is already low announces immediately
        with qtbot.waitSignal(widget.disk_changed) as got:
            widget.set_disk_watch_path("/somewhere/proj.flograph")
        assert "running out of space" in got.args[0]
        assert "Reset Caches" in got.args[0]

        # still low: no repeat — nagging gets ignored
        before = len(seen)
        widget._refresh()
        assert len(seen) == before

        with qtbot.waitSignal(widget.disk_changed) as gone:
            usage_box["free"] = LOW_DISK_FREE * 4
            widget._refresh()
        assert gone.args[0] == ""

    def test_nothing_is_watched_without_a_project(self, qtbot, monkeypatch):
        usage_box = {"free": 100}
        self._watch(monkeypatch, usage_box)
        widget = self._widget(qtbot)
        seen = []
        widget.disk_changed.connect(seen.append)

        widget.set_disk_watch_path(None)
        widget._refresh()
        assert seen == []

    def test_the_tooltip_reports_free_space_when_watching(
            self, qtbot, monkeypatch):
        usage_box = {"free": LOW_DISK_FREE * 3}
        self._watch(monkeypatch, usage_box)
        widget = self._widget(qtbot)
        widget.set_disk_watch_path("/somewhere/proj.flograph")
        assert "free" in widget.toolTip()

        widget.set_disk_watch_path(None)
        widget._refresh()
        assert "free" not in widget.toolTip()

    def test_the_tooltip_compares_stored_against_uncompressed(
            self, qtbot, monkeypatch, registry, tmp_path):
        """A real side-car on disk: the hover says what it costs stored and
        what the same values would have cost raw, and by how much."""
        import pandas as pd

        from flograph.engine.cache import OutputCache
        from flograph.engine.cache_persistence import save_cache

        graph = Graph()
        const = graph.add_node(registry.instantiate("flograph.util.constant"))
        df = pd.DataFrame({"name": [f"row-{i:05d}" for i in range(2000)]})
        cache = OutputCache()
        cache.set(const.id, {"value": df}, wall_time=0.01)
        project = tmp_path / "proj.flograph"
        save_cache(graph, cache, project)

        usage_box = {"free": LOW_DISK_FREE * 4}
        self._watch(monkeypatch, usage_box)
        widget = self._widget(qtbot)
        widget.set_disk_watch_path(str(project))

        tip = widget.toolTip()
        assert "Cache on disk" in tip
        assert "uncompressed" in tip
        assert "%" in tip
