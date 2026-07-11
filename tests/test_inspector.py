"""M5 tests: pandas paging model, inspector binding, log console."""
import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QUndoStack

from flopy.core import Graph, NodeRegistry
from flopy.engine import ExecutionEngine
from flopy.ui.inspector.pandas_model import PAGE_SIZE, PandasModel
from flopy.ui.inspector.inspector_dock import InspectorPanel
from flopy.ui.console.log_dock import LogConsole


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


class TestPandasModel:
    def test_paging_large_frame(self, qtbot):
        df = pd.DataFrame({"a": np.arange(1_000_000)})
        model = PandasModel(df)
        assert model.rowCount() == PAGE_SIZE
        assert model.canFetchMore()
        model.fetchMore()
        assert model.rowCount() == 2 * PAGE_SIZE

    def test_small_frame_no_fetch(self, qtbot):
        model = PandasModel(pd.DataFrame({"a": [1, 2]}))
        assert model.rowCount() == 2
        assert not model.canFetchMore()

    def test_formatting(self, qtbot):
        df = pd.DataFrame({"x": [1.23456789, np.nan], "s": ["hi", "yo"]})
        model = PandasModel(df)
        idx = model.index(0, 0)
        assert model.data(idx, Qt.DisplayRole) == "1.23457"
        nan_idx = model.index(1, 0)
        assert model.data(nan_idx, Qt.DisplayRole) == "NaN"
        assert model.data(nan_idx, Qt.ForegroundRole) is not None
        assert model.headerData(0, Qt.Horizontal, Qt.DisplayRole) == "x"
        assert "int" in model.headerData(0, Qt.Horizontal, Qt.ToolTipRole) \
            or "float" in model.headerData(0, Qt.Horizontal, Qt.ToolTipRole)


class TestInspector:
    def _run(self, qtbot, engine):
        with qtbot.waitSignal(engine.run_finished, timeout=5000):
            engine.run_all()

    def test_node_outputs_shown_after_run(self, qtbot, registry, tmp_path):
        csv = tmp_path / "d.csv"
        csv.write_text("a,b\n1,2\n3,4\n-1,6\n")
        graph = Graph()
        engine = ExecutionEngine(graph)
        reader = graph.add_node(registry.instantiate("flopy.io.read_csv"))
        filt = graph.add_node(registry.instantiate("flopy.transform.filter_rows"))
        graph.set_param(reader.id, "path", str(csv))
        graph.set_param(filt.id, "query", "a > 0")
        graph.connect(reader.id, "table", filt.id, "table")

        panel = InspectorPanel(graph, engine)
        qtbot.addWidget(panel)
        panel.show_node(filt.id)
        assert "not computed" in panel._header.text()

        self._run(qtbot, engine)
        assert "computed in" in panel._header.text()
        assert panel._tabs.count() == 2  # filtered + rejected
        assert panel._tabs.tabText(0) == "filtered"
        assert not panel._stale.isVisibleTo(panel)

        # dirtying the node shows the stale watermark... after cache eviction
        # the cache is gone, so watermark hides again; check the wire view too
        conn = next(iter(graph.connections.values()))
        panel.show_wire(conn)
        assert panel._tabs.count() == 1
        assert panel._tabs.tabText(0) == "table"

    def test_figure_output_view(self, qtbot, registry, tmp_path):
        csv = tmp_path / "d.csv"
        csv.write_text("x,y\n1,2\n2,4\n3,9\n")
        graph = Graph()
        engine = ExecutionEngine(graph)
        reader = graph.add_node(registry.instantiate("flopy.io.read_csv"))
        plot = graph.add_node(registry.instantiate("flopy.viz.show_plot"))
        graph.set_param(reader.id, "path", str(csv))
        graph.connect(reader.id, "table", plot.id, "table")

        panel = InspectorPanel(graph, engine)
        qtbot.addWidget(panel)
        panel.show_node(plot.id)
        self._run(qtbot, engine)
        assert plot.status.value == "done"
        from flopy.ui.inspector.figure_view import FigureView
        assert panel._tabs.count() == 1
        host = panel._tabs.widget(0)
        assert host.findChildren(FigureView), "figure view not created"


class TestLogConsole:
    def test_log_lines_appear(self, qtbot, registry):
        graph = Graph()
        engine = ExecutionEngine(graph)
        node = graph.add_node(registry.instantiate("flopy.scripting.python_script"))
        console = LogConsole(graph, engine)
        qtbot.addWidget(console)
        with qtbot.waitSignal(engine.run_finished, timeout=5000):
            engine.run_all()
        text = console._text.toPlainText()
        assert "received:" in text            # ctx.log from python_script
        assert "run finished" in text
        assert "Python Script" in text        # node label tag


class TestSpecView:
    def test_spec_frame_describes_each_column(self):
        from flopy.ui.inspector.spec_view import spec_frame
        df = pd.DataFrame({
            "n": [1.0, 2.0, np.nan],
            "s": ["a", "b", "b"],
        })
        spec = spec_frame(df)
        assert list(spec["column"]) == ["n", "s"]
        assert spec["type"][0] == "float64"
        assert spec["non-null"][0] == "2 / 3"
        assert spec["unique"][1] == "2"
        assert spec["min"][0] == "1.0" and spec["max"][0] == "2.0"

    def test_spec_frame_survives_awkward_cells(self):
        from flopy.ui.inspector.spec_view import spec_frame
        # dicts are unhashable (no nunique) and unorderable (no min/max)
        spec = spec_frame(pd.DataFrame({"o": [{"a": 1}, {"b": 2}]}))
        assert spec["non-null"][0] == "2 / 2"
        assert spec["unique"][0] == ""
        assert spec["min"][0] == ""

    def test_spec_view_only_for_tables(self, qtbot):
        from flopy.ui.inspector.spec_view import spec_view_for
        assert spec_view_for(42) is None
        view = spec_view_for(pd.Series([1, 2], name="v"))
        assert view is not None
        assert view.model()._df["column"][0] == "v"

    def test_inspector_table_port_gets_a_spec_tab(self, qtbot, registry,
                                                  tmp_path):
        from PySide6.QtWidgets import QTabWidget
        csv = tmp_path / "d.csv"
        csv.write_text("a,b\n1,x\n3,y\n")
        graph = Graph()
        engine = ExecutionEngine(graph)
        reader = graph.add_node(registry.instantiate("flopy.io.read_csv"))
        graph.set_param(reader.id, "path", str(csv))

        panel = InspectorPanel(graph, engine)
        qtbot.addWidget(panel)
        panel.show_node(reader.id)
        with qtbot.waitSignal(engine.run_finished, timeout=5000):
            engine.run_all()

        host = panel._tabs.widget(0)
        sub = host.findChild(QTabWidget)
        assert sub is not None
        assert [sub.tabText(i) for i in range(sub.count())] == ["Data", "Spec"]
        spec_model = sub.widget(1).model()
        assert list(spec_model._df["column"]) == ["a", "b"]
        assert "int" in spec_model._df["type"][0]
