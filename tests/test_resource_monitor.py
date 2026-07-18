"""Status bar resource monitor: system memory readout, whole-file cache size,
and selected-node cache size."""
import pandas as pd
import pytest

from flograph.core import Graph, NodeRegistry
from flograph.engine import ExecutionEngine
from flograph.engine.cache import estimate_size
from flograph.ui.resource_monitor import ResourceMonitorWidget, format_bytes


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


class TestResourceMonitorWidget:
    def _run(self, qtbot, engine):
        with qtbot.waitSignal(engine.run_finished, timeout=5000):
            engine.run_all()

    def test_shows_placeholder_with_no_node_selected(self, qtbot, registry):
        graph = Graph()
        engine = ExecutionEngine(graph)
        widget = ResourceMonitorWidget(engine)
        qtbot.addWidget(widget)
        assert widget._node_label.text() == "Node mem: —"
        assert "Sys mem:" in widget._system_label.text()
        assert widget._file_label.text() == "File mem: 0 B"

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
        assert format_bytes(expected) in widget._file_label.text()

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
        assert widget._node_label.text() == "Node mem: —"

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
        assert "Node mem: —" not in widget._node_label.text()

        widget.set_node(None)
        assert widget._node_label.text() == "Node mem: —"
