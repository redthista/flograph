"""M5 tests: pandas paging model, inspector binding, log console."""
import numpy as np
import pandas as pd
import pytest
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry
from flograph.engine import ExecutionEngine
from flograph.ui.inspector.pandas_model import PAGE_SIZE, PandasModel
from flograph.ui.inspector.inspector_dock import InspectorPanel
from flograph.ui.console.log_dock import LogConsole


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

    def test_roles_answer_the_same_as_plain_ints(self, qtbot):
        """data() compares int(role) against ints and returns early for the
        roles it has no opinion on — which also keeps it from doing a pandas
        `iat` lookup per unhandled role. Neither may change the answers."""
        df = pd.DataFrame({"x": [1.5, np.nan], "s": ["hi", "yo"]})
        model = PandasModel(df)
        for row in (0, 1):
            for col in (0, 1):
                index = model.index(row, col)
                for role in (Qt.DisplayRole, Qt.EditRole, Qt.ForegroundRole,
                             Qt.FontRole, Qt.TextAlignmentRole,
                             Qt.BackgroundRole, Qt.ToolTipRole,
                             Qt.DecorationRole):
                    assert model.data(index, role) == \
                        model.data(index, int(role))
        # the early-out roles genuinely answer nothing
        assert model.data(model.index(0, 0), Qt.BackgroundRole) is None
        assert model.data(model.index(0, 0), Qt.DecorationRole) is None
        # ...and an invalid index is still safe
        assert model.data(QModelIndex(), Qt.DisplayRole) is None

    def test_missing_values_stay_italic_and_grey(self, qtbot):
        """The italic font is built once at import now rather than per
        call — it must still only apply to the missing cells."""
        df = pd.DataFrame({"x": [1.5, np.nan]})
        model = PandasModel(df)
        assert model.data(model.index(1, 0), Qt.FontRole).italic()
        assert model.data(model.index(0, 0), Qt.FontRole) is None
        assert model.data(model.index(1, 0), Qt.ForegroundRole) is not None
        assert model.data(model.index(0, 0), Qt.ForegroundRole) is None


class TestInspector:
    def _run(self, qtbot, engine):
        with qtbot.waitSignal(engine.run_finished, timeout=5000):
            engine.run_all()

    def test_node_outputs_shown_after_run(self, qtbot, registry, tmp_path):
        csv = tmp_path / "d.csv"
        csv.write_text("a,b\n1,2\n3,4\n-1,6\n")
        graph = Graph()
        engine = ExecutionEngine(graph)
        reader = graph.add_node(registry.instantiate("flograph.io.read_csv"))
        filt = graph.add_node(registry.instantiate("flograph.transform.filter_rows"))
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

    def test_figure_output_shows_pointer_not_a_squeezed_copy(
            self, qtbot, registry, tmp_path):
        """The node's canvas card (or dashboard tile) already renders its
        figure at a sensible size; the docked Inspector is narrow and used
        to cram in its own squashed FigureCanvas copy — just point at the
        card instead of duplicating it badly."""
        csv = tmp_path / "d.csv"
        csv.write_text("x,y\n1,2\n2,4\n3,9\n")
        graph = Graph()
        engine = ExecutionEngine(graph)
        reader = graph.add_node(registry.instantiate("flograph.io.read_csv"))
        plot = graph.add_node(registry.instantiate("flograph.viz.show_plot"))
        graph.set_param(reader.id, "path", str(csv))
        graph.connect(reader.id, "table", plot.id, "table")

        panel = InspectorPanel(graph, engine)
        qtbot.addWidget(panel)
        panel.show_node(plot.id)
        self._run(qtbot, engine)
        assert plot.status.value == "done"
        from flograph.ui.inspector.figure_view import FigureView
        assert panel._tabs.count() == 1
        host = panel._tabs.widget(0)
        assert not host.findChildren(FigureView), \
            "inspector should not embed a live figure canvas"

    def test_popup_view_still_embeds_the_figure(self, qtbot, registry, tmp_path):
        """Unlike the docked Inspector, a popup view is a deliberate,
        generously-sized window — it should still show the real figure."""
        csv = tmp_path / "d.csv"
        csv.write_text("x,y\n1,2\n2,4\n3,9\n")
        graph = Graph()
        engine = ExecutionEngine(graph)
        reader = graph.add_node(registry.instantiate("flograph.io.read_csv"))
        plot = graph.add_node(registry.instantiate("flograph.viz.show_plot"))
        graph.set_param(reader.id, "path", str(csv))
        graph.connect(reader.id, "table", plot.id, "table")
        self._run(qtbot, engine)

        from flograph.ui.inspector.figure_view import FigureView
        from flograph.ui.inspector.popup_view import PopupView
        popup = PopupView(graph, engine, plot.id, "figure")
        qtbot.addWidget(popup)
        assert isinstance(popup._current_widget, FigureView)

    def test_stale_event_after_close_does_not_crash(
            self, qtbot, registry, tmp_path):
        """Crash report: WA_DeleteOnClose destruction is deferred, and a
        dirty_changed/node_succeeded event already in flight when the popup
        is torn down (e.g. from a WebEngine chart pumping the event loop
        reentrantly) could reach _refresh() after the dialog's C++ side —
        and its QVBoxLayout — was already gone, raising 'Internal C++
        object already deleted' from inside QUndoCommand.redo()."""
        csv = tmp_path / "d.csv"
        csv.write_text("x,y\n1,2\n2,4\n3,9\n")
        graph = Graph()
        engine = ExecutionEngine(graph)
        reader = graph.add_node(registry.instantiate("flograph.io.read_csv"))
        plot = graph.add_node(registry.instantiate("flograph.viz.show_plot"))
        graph.set_param(reader.id, "path", str(csv))
        graph.connect(reader.id, "table", plot.id, "table")
        self._run(qtbot, engine)

        from flograph.ui.inspector.popup_view import PopupView
        popup = PopupView(graph, engine, plot.id, "figure")
        # Not qtbot.addWidget()'d: this test forces destruction itself below,
        # and qtbot's own teardown-time close() would hit the same deleted
        # C++ object.

        from PySide6.QtCore import QCoreApplication, QEvent
        popup.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

        # Simulates a callback still in flight after the C++ object is
        # already gone — must not raise.
        popup._on_dirty_changed(plot.id, True)
        popup._on_node_ran(plot.id)
        popup._on_node_removed(plot.id)


class TestFigureViewTeardown:
    """Regression for the locLabel segfault: matplotlib keeps event
    callbacks on the Figure (they survive canvas swaps), so a torn-down
    toolbar left connected keeps receiving mouse_move through any later
    canvas showing the same figure — set_message then hits its deleted
    QLabel ("Internal C++ object already deleted", eventually SIGSEGV)."""

    @staticmethod
    def _motion_cids(figure) -> set:
        return set(figure._canvas_callbacks.callbacks.get(
            "motion_notify_event", {}))

    @staticmethod
    def _make_view(qtbot):
        from matplotlib.figure import Figure
        from flograph.ui.inspector.figure_view import FigureView
        view = FigureView()
        qtbot.addWidget(view)
        view.set_figure(Figure())
        return view

    def test_set_figure_swap_unhooks_old_toolbar(self, qtbot):
        view = self._make_view(qtbot)
        fig = view._canvas.figure
        old_cid = view._toolbar._id_drag
        assert old_cid in self._motion_cids(fig)

        view.set_figure(fig)  # node re-ran: same figure, fresh canvas/toolbar
        assert old_cid not in self._motion_cids(fig)
        assert view._toolbar._id_drag in self._motion_cids(fig)

    def test_clear_unhooks_toolbar(self, qtbot):
        view = self._make_view(qtbot)
        fig = view._canvas.figure
        cid = view._toolbar._id_drag
        view.clear()
        assert cid not in self._motion_cids(fig)

    def test_widget_destruction_without_clear_unhooks_toolbar(self, qtbot):
        # scene removeItem / popup close delete the widget tree without ever
        # calling clear(); the toolbar's destroyed signal must unhook it
        from PySide6.QtCore import QCoreApplication, QEvent
        view = self._make_view(qtbot)
        fig = view._canvas.figure
        cid = view._toolbar._id_drag
        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert cid not in self._motion_cids(fig)


class TestLogConsole:
    def test_log_lines_appear(self, qtbot, registry):
        graph = Graph()
        engine = ExecutionEngine(graph)
        node = graph.add_node(registry.instantiate("flograph.scripting.python_script"))
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
        from flograph.ui.inspector.spec_view import spec_frame
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
        from flograph.ui.inspector.spec_view import spec_frame
        # dicts are unhashable (no nunique) and unorderable (no min/max)
        spec = spec_frame(pd.DataFrame({"o": [{"a": 1}, {"b": 2}]}))
        assert spec["non-null"][0] == "2 / 2"
        assert spec["unique"][0] == ""
        assert spec["min"][0] == ""

    def test_spec_view_only_for_tables(self, qtbot):
        from flograph.ui.inspector.spec_view import spec_view_for
        assert spec_view_for(42) is None
        view = spec_view_for(pd.Series([1, 2], name="v"))
        assert view is not None
        assert view.model()._df["column"][0] == "v"

    def test_inspector_table_port_gets_a_spec_tab(self, qtbot, registry,
                                                  tmp_path):
        from PySide6.QtWidgets import QTabWidget, QTableView
        csv = tmp_path / "d.csv"
        csv.write_text("a,b\n1,x\n3,y\n")
        graph = Graph()
        engine = ExecutionEngine(graph)
        reader = graph.add_node(registry.instantiate("flograph.io.read_csv"))
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

        # the Spec tab defers its column-stats scan until it's actually
        # opened, so before that its content isn't a table view yet
        assert sub.widget(1).findChild(QTableView) is None

        sub.setCurrentIndex(1)  # "opening" the tab builds it on demand
        spec_view = sub.widget(1).findChild(QTableView)
        assert spec_view is not None
        spec_model = spec_view.model()
        assert list(spec_model._df["column"]) == ["a", "b"]
        assert "int" in spec_model._df["type"][0]
