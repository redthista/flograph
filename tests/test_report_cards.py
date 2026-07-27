"""Report cards, and lists of figures (#18).

Two connected things:

* A node output that is a **list** renders as a *stack* wherever a single
  one would — the canvas card, a dashboard tile, a report embed. That is
  all "one chart per value of a column" needs: the loop lives in the node's
  own code (see the Chart per Value node), not in a faceting UI.
* A **Report card** is a markdown block inside the flow. Unlike a report
  page, its embeds name its own *wired inputs* — a node must not depend on
  something the scheduler can't see.
"""
import pandas as pd
import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry, Page, Tile, compile_run
from flograph.engine.cache import OutputCache
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.inspector.plotly_view import to_html
from flograph.ui.report.render import render_card, render_report

from tests.conftest import FakeContext


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def figures(count=3):
    from matplotlib.figure import Figure
    made = []
    for i in range(count):
        figure = Figure(figsize=(4, 2))
        figure.add_subplot().plot([1, 2 + i, 3])
        made.append(figure)
    return made


class TestListsRenderAsStacks:

    def test_a_report_embed_stacks_every_figure(self, registry):
        graph, cache = Graph(), OutputCache()
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_label(node.id, "Per Region")
        cache.set(node.id, {"value": figures(3)}, 0.0)

        rendered = render_report("![[Per Region]]", graph, cache)
        html = rendered.document.toHtml()
        assert all(f'src="embed:{i}"' in html for i in range(3))
        assert rendered.problems == []

    def test_a_list_of_tables_stacks_too(self, registry):
        """Nothing about this is figure-specific — a list is a list."""
        graph, cache = Graph(), OutputCache()
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_label(node.id, "Splits")
        cache.set(node.id, {"value": [pd.DataFrame({"a": [1]}),
                                      pd.DataFrame({"b": [2]})]}, 0.0)
        html = render_report("![[Splits]]", graph, cache).document.toHtml()
        assert html.count("<table") == 2

    def test_an_empty_list_says_so_rather_than_vanishing(self, registry):
        graph, cache = Graph(), OutputCache()
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_label(node.id, "Nothing")
        cache.set(node.id, {"value": []}, 0.0)
        rendered = render_report("![[Nothing]]", graph, cache)
        assert rendered.problems == ["“Nothing” produced an empty list"]

    def test_the_figure_view_stacks_a_list_scrollably(self, qtbot):
        from PySide6.QtWidgets import QScrollArea
        from flograph.ui.inspector.figure_view import FigureView
        view = FigureView()
        qtbot.addWidget(view)
        view.set_figure(figures(4))
        assert isinstance(view._stack, QScrollArea)

    def test_it_goes_back_to_a_single_figure_cleanly(self, qtbot):
        from flograph.ui.inspector.figure_view import FigureView
        view = FigureView()
        qtbot.addWidget(view)
        view.set_figure(figures(3))
        view.set_figure(figures(1)[0])
        assert view._stack is None and view._canvas is not None

    def test_plotly_lists_become_one_scrolling_page(self):
        class Fake:
            def __init__(self, n):
                self.n = n

            def to_html(self, **kw):
                head = "<script>PLOTLYJS</script>" if kw.get(
                    "include_plotlyjs") else ""
                return f"{head}<div class='c'>{self.n}</div>"

        html = to_html([Fake(1), Fake(2), Fake(3)])
        assert html.count("class='c'") == 3
        # 3 MB of plotly.js per chart would be a page that never opens
        assert html.count("PLOTLYJS") == 1
        assert html.count("flograph-stack-item") >= 3

    def test_an_empty_plotly_list_renders_nothing(self):
        assert to_html([]) is None

    def test_a_single_figure_is_unaffected(self):
        class Fake:
            def to_html(self, **kw):
                return "<div>solo</div>"
        assert "flograph-stack-item" not in (to_html(Fake()) or "")


class TestChartPerValue:

    def run_node(self, registry, table, **params):
        spec = registry.get("flograph.viz.chart_per_value")
        settings = spec.default_params()
        settings.update(params)
        context = FakeContext(params=settings)
        return compile_run(spec.source, "t")(context, table), context

    @pytest.fixture
    def table(self):
        return pd.DataFrame({
            "region": ["N"] * 3 + ["S"] * 3 + ["E"] * 3,
            "month": [1, 2, 3] * 3,
            "revenue": [3, 5, 4, 4, 5, 5, 5, 6, 7]})

    def test_one_chart_per_value(self, registry, table):
        out, _ = self.run_node(registry, table, split_by="region",
                               x="month", y="revenue")
        assert len(out["figures"]) == 3
        assert [f.axes[0].get_title() for f in out["figures"]] == [
            "region: E", "region: N", "region: S"]

    def test_the_scale_is_shared_so_panels_compare(self, registry, table):
        out, _ = self.run_node(registry, table, split_by="region",
                               x="month", y="revenue")
        limits = {f.axes[0].get_ylim() for f in out["figures"]}
        assert len(limits) == 1

    def test_the_scale_can_be_left_alone(self, registry, table):
        out, _ = self.run_node(registry, table, split_by="region", x="month",
                               y="revenue", shared_scale=False)
        assert len({f.axes[0].get_ylim() for f in out["figures"]}) > 1

    def test_max_charts_guards_a_high_cardinality_column(self, registry, table):
        """Splitting on an id column by accident would build thousands of
        figures and hang the run."""
        out, context = self.run_node(registry, table, split_by="region",
                                     x="month", y="revenue", max_charts=2)
        assert len(out["figures"]) == 2
        assert any("Max charts" in line for line in context.logs)

    def test_it_refuses_without_a_split_column(self, registry, table):
        with pytest.raises(ValueError, match="Split by"):
            self.run_node(registry, table, y="revenue")

    def test_it_refuses_an_unknown_split_column(self, registry, table):
        with pytest.raises(ValueError, match="no column 'nope'"):
            self.run_node(registry, table, split_by="nope")

    def test_numeric_columns_are_picked_when_y_is_blank(self, registry, table):
        out, _ = self.run_node(registry, table, split_by="region")
        assert len(out["figures"]) == 3


class TestChartPerValuePlotly:
    """The same node against the other backend. It earns its own class
    because nothing is shared between the two but the idea: this one emits
    plotly Figures onto a webview card, so the stack is HTML rather than a
    column of canvases, and the assertions have to read the layout object
    instead of matplotlib axes."""

    def run_node(self, registry, table, **params):
        spec = registry.get("flograph.viz.chart_per_value_plotly")
        settings = spec.default_params()
        settings.update(params)
        context = FakeContext(params=settings)
        return compile_run(spec.source, "t")(context, table), context

    @pytest.fixture
    def table(self):
        return pd.DataFrame({
            "region": ["N"] * 3 + ["S"] * 3 + ["E"] * 3,
            "month": [1, 2, 3] * 3,
            "revenue": [3, 5, 4, 4, 5, 5, 5, 6, 7]})

    def test_it_is_a_webview_card_emitting_a_list(self, registry):
        """The card kind is the whole difference — a figure card would try
        to draw a plotly object with matplotlib and show nothing."""
        spec = registry.get("flograph.viz.chart_per_value_plotly")
        assert spec.card == "webview"
        assert [p.name for p in spec.outputs] == ["figures"]

    def test_one_chart_per_value(self, registry, table):
        out, _ = self.run_node(registry, table, split_by="region",
                               x="month", y="revenue")
        assert len(out["figures"]) == 3
        assert [f.layout.title.text for f in out["figures"]] == [
            "region: E", "region: N", "region: S"]

    def test_the_scale_is_shared_so_panels_compare(self, registry, table):
        out, _ = self.run_node(registry, table, split_by="region",
                               x="month", y="revenue")
        ranges = {tuple(f.layout.yaxis.range) for f in out["figures"]}
        assert len(ranges) == 1

    def test_the_scale_can_be_left_alone(self, registry, table):
        out, _ = self.run_node(registry, table, split_by="region", x="month",
                               y="revenue", shared_scale=False)
        assert {f.layout.yaxis.range for f in out["figures"]} == {None}

    @pytest.mark.parametrize("kind", ["histogram", "box", "violin"])
    def test_distribution_kinds_are_never_given_a_range(self, registry, table,
                                                        kind):
        """Their value axis is a count or a spread the figure derives
        itself; bounding it to the source column's range would crop it."""
        out, _ = self.run_node(registry, table, split_by="region",
                               y="revenue", kind=kind)
        assert {f.layout.yaxis.range for f in out["figures"]} == {None}

    @pytest.mark.parametrize("kind", ["line", "bar", "scatter", "area"])
    def test_every_offered_kind_actually_plots(self, registry, table, kind):
        out, _ = self.run_node(registry, table, split_by="region",
                               x="month", y="revenue", kind=kind)
        assert len(out["figures"]) == 3

    def test_the_stack_carries_plotly_js_once(self, registry, table):
        """Twenty charts each bundling the ~3MB library is the difference
        between a card that opens and one that doesn't."""
        out, _ = self.run_node(registry, table, split_by="region",
                               x="month", y="revenue")
        html = to_html(out["figures"])
        assert html.count('class="flograph-stack-item"') == 3
        assert html.count("plotly.js v") == 1

    def test_max_charts_guards_a_high_cardinality_column(self, registry,
                                                         table):
        out, context = self.run_node(registry, table, split_by="region",
                                     x="month", y="revenue", max_charts=2)
        assert len(out["figures"]) == 2
        assert any("Max charts" in line for line in context.logs)

    def test_it_refuses_without_a_split_column(self, registry, table):
        with pytest.raises(ValueError, match="Split by"):
            self.run_node(registry, table, y="revenue")

    def test_it_refuses_an_unknown_split_column(self, registry, table):
        with pytest.raises(ValueError, match="no column 'nope'"):
            self.run_node(registry, table, split_by="nope")

    def test_it_refuses_an_unknown_y_column(self, registry, table):
        with pytest.raises(ValueError, match="ghost"):
            self.run_node(registry, table, split_by="region", y="ghost")

    def test_numeric_columns_are_picked_when_y_is_blank(self, registry, table):
        out, _ = self.run_node(registry, table, split_by="region")
        assert len(out["figures"]) == 3

    def test_the_layout_params_are_cosmetic_like_the_other_one(self, registry):
        """Re-arranging a slow split must not re-run it."""
        spec = registry.get("flograph.viz.chart_per_value_plotly")
        for name in ("columns", "rows", "direction"):
            assert spec.param(name).cosmetic, name


def _constant(graph):
    """A bare Constant node, for standing in as a same-named decoy."""
    from flograph.core import NodeRegistry
    reg = NodeRegistry()
    reg.load_builtins()
    return reg.instantiate("flograph.util.constant")


class TestTheReportCard:

    @pytest.fixture
    def env(self, qtbot, registry):
        graph = Graph()
        stack = QUndoStack()
        scene = NodeGraphScene(graph, stack, registry=registry)
        scene.output_cache = OutputCache()
        report = graph.add_node(registry.instantiate("flograph.viz.report_card"))
        chart = graph.add_node(registry.instantiate("flograph.util.constant"))
        total = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.connect(chart.id, "value", report.id, "a")
        graph.connect(total.id, "value", report.id, "b")
        scene.output_cache.set(chart.id, {"value": figures(2)}, 0.0)
        scene.output_cache.set(total.id, {"value": 48250}, 0.0)
        return graph, scene, report

    def html(self, env):
        _graph, scene, report = env
        return scene.node_items[report.id]._report_view.document().toHtml()

    def test_it_is_a_card_with_its_own_widget(self, env):
        _graph, scene, report = env
        item = scene.node_items[report.id]
        assert item.report_card and item._report_view is not None
        assert item._resizable()

    def test_embeds_name_its_wired_inputs(self, env):
        graph, _scene, report = env
        graph.set_param(report.id, "text", "Total ![[b]].")
        assert "48,250" in self.html(env)

    def test_a_wired_list_stacks_on_the_card(self, env):
        graph, _scene, report = env
        graph.set_param(report.id, "text", "![[a]]")
        html = self.html(env)
        assert all(f'src="embed:{i}"' in html for i in range(2))

    def test_an_indented_markdown_string_renders_as_markdown(self, env):
        """Where it turned up (2026-07-26): a Python Script building its
        markdown inside run() hands over Python's indentation on every line,
        and four spaces in markdown is a code block. The card resolves
        embeds through the same renderer as a page, so the dedent covers
        both — this pins that they don't drift apart."""
        graph, _scene, report = env
        total = next(c.src_node for c in graph.connections.values()
                     if c.dst_port == "b")
        _scene.output_cache.set(total, {"value": "\n    ## my markdown\n    "},
                                0.0)
        graph.set_param(report.id, "text", "![[b]]")
        html = self.html(env)
        assert "my markdown</" in html
        assert "## my markdown" not in html   # not left as literal text

    def test_an_unwired_input_says_to_wire_it(self, env):
        graph, _scene, report = env
        graph.set_param(report.id, "text", "![[c]]")
        assert "Nothing wired into" in self.html(env)

    def test_a_name_that_is_neither_an_input_nor_a_node_says_so(self, env):
        graph, _scene, report = env
        graph.set_param(report.id, "text", "![[zzz]]")
        assert "no node called" in self.html(env).casefold()

    def test_it_can_also_name_any_node_by_label(self, env):
        """Reported 2026-07-26: "i do like the idea of being able to call any
        node into the report canvas node aswell, can we enable this?"

        The trade-off is real and deliberate — a label is a dependency the
        scheduler cannot see, so it neither orders the card after that node
        nor shows on the canvas as a wire. Wires stay the honest option;
        this is the convenient one."""
        graph, _scene, report = env
        chart_id = next(n for n in graph.nodes if n != report.id)
        graph.set_label(chart_id, "Chart Node")
        graph.set_param(report.id, "text", "![[Chart Node]]")
        assert 'src="embed:0"' in self.html(env)

    def test_a_wired_input_wins_over_a_node_of_the_same_name(self, env):
        """The priority rule: "if a input abel and a node name match
        then we should pick the input node as priority"."""
        graph, _scene, report = env
        # a *different* node now also answers to "b", the wired input's name
        decoy = graph.add_node(_constant(graph))
        graph.set_label(decoy.id, "b")
        graph.set_param(report.id, "text", "![[b]]")
        assert "48,250" in self.html(env)      # the wired input, not the decoy

    def test_an_unwired_input_reports_itself_rather_than_finding_a_node(
            self, env):
        """Unplugging a wire must not silently swap the source of a
        paragraph to whatever node happens to share the port's name."""
        graph, _scene, report = env
        decoy = graph.add_node(_constant(graph))
        graph.set_label(decoy.id, "c")
        graph.set_param(report.id, "text", "![[c]]")
        assert "Nothing wired into" in self.html(env)

    def test_widening_the_card_widens_its_charts(self, env):
        """Qt rich text has no percentage image sizing, so a chart drawn at
        one width simply hangs off a card of another."""
        graph, scene, report = env
        graph.set_param(report.id, "text", "![[a]]")
        item = scene.node_items[report.id]
        for width in (300, 900):
            graph.set_param(report.id, "width", width)
            document = item._report_view.document()
            document.setTextWidth(width - 44)
            assert round(document.idealWidth()) <= width - 44

    def test_the_card_survives_having_no_cache(self, registry, qtbot):
        """A scene with no engine behind it must still draw the text."""
        graph = Graph()
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        node = graph.add_node(registry.instantiate("flograph.viz.report_card"))
        graph.set_param(node.id, "text", "# Hello")
        assert "Hello" in scene.node_items[node.id]._report_view.toPlainText()


class TestTheReportTile:

    @pytest.fixture
    def env(self, qtbot, registry):
        from flograph.engine import ExecutionEngine
        from flograph.ui.dashboard.dashboard_scene import DashboardScene
        graph = Graph()
        engine = ExecutionEngine(graph)
        report = graph.add_node(registry.instantiate("flograph.viz.report_card"))
        total = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.connect(total.id, "value", report.id, "a")
        engine.cache.set(total.id, {"value": 999}, 0.0)
        graph.set_param(report.id, "text", "Total ![[a]].")
        graph.add_page(Page(id="p1"))
        graph.add_tile("p1", Tile(id="t1", node_id=report.id, port="text"))
        scene = DashboardScene(graph, engine, QUndoStack(), "p1")
        yield graph, scene, report
        scene.dispose()

    def test_a_report_node_can_be_tiled(self, registry):
        from flograph.ui.dashboard.tile_item import is_tile_able
        graph = Graph()
        node = graph.add_node(registry.instantiate("flograph.viz.report_card"))
        assert is_tile_able(node)

    def test_the_tile_renders_the_same_thing(self, env):
        _graph, scene, _report = env
        tile = scene.tile_items["t1"]
        assert tile._kind() == "report"
        assert "999" in tile._report_view.document().toHtml()

    def test_editing_the_text_updates_the_tile(self, env):
        graph, scene, report = env
        graph.set_param(report.id, "text", "# Changed")
        assert "Changed" in scene.tile_items["t1"]._report_view.toPlainText()

    def test_it_does_mark_itself_stale(self, env):
        """Unlike a Table or a control tile, a report is *not* pure input —
        its embeds show upstream data. When the node is dirty an embedded
        chart may be out of date, and a report is something you hand to
        other people, so saying so beats hiding it. The cost is a STALE
        badge after a text-only edit, which is the safe way round."""
        graph, scene, report = env
        graph.mark_dirty(report.id)
        assert scene.tile_items["t1"]._is_stale() is True


class TestFigureCardPorts:
    """The canvas figure card used to read a hardcoded "figure" port, so a
    node emitting a list under any other name (Chart per Value emits
    "figures") sat on its run-me placeholder forever — while a report embed
    of the same node worked, because that reads the declared port."""

    @pytest.fixture
    def window(self, qtbot, registry, tmp_path, monkeypatch):
        from PySide6.QtCore import QSettings
        from flograph.ui import mainwindow as mod
        monkeypatch.setattr(
            mod, "QSettings",
            lambda *a, **k: QSettings(str(tmp_path / "s.ini"),
                                      QSettings.IniFormat))
        win = mod.MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def test_a_figure_card_reads_its_own_output_port(self, window):
        node = window.graph.add_node(
            window.registry.instantiate("flograph.viz.chart_per_value"))
        assert node.spec.outputs[0].name == "figures"   # not "figure"
        window.engine.cache.set(node.id, {"figures": figures(3)}, 0.0)
        window.engine.node_succeeded.emit(node.id)

        view = window.scene.node_items[node.id]._figure_view
        assert view._stack is not None

    def test_the_ordinary_figure_port_still_works(self, window):
        node = window.graph.add_node(
            window.registry.instantiate("flograph.viz.show_plot"))
        window.engine.cache.set(node.id, {"figure": figures(1)[0]}, 0.0)
        window.engine.node_succeeded.emit(node.id)

        view = window.scene.node_items[node.id]._figure_view
        assert view._canvas is not None and view._stack is None


class TestScrollingAStack:
    """A stack you cannot scroll is a stack that shows one chart. matplotlib
    canvases consume wheel ticks for their own zoom, so with the cursor over
    a chart — which is nearly always — the scroll area never saw them and
    only dragging the scrollbar worked."""

    def wheel(self):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        return QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0),
                           QPoint(0, -360), Qt.NoButton, Qt.NoModifier,
                           Qt.NoScrollPhase, False)

    def canvases(self, view):
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        return view._stack.widget().findChildren(FigureCanvasQTAgg)

    def test_a_stacked_canvas_declines_the_wheel(self, qtbot):
        """Declining is what hands the tick to the scroll area behind it;
        accepting is what made only the scrollbar itself work."""
        from flograph.ui.inspector.figure_view import FigureView
        view = FigureView()
        qtbot.addWidget(view)
        view.set_figure(figures(4))

        charts = self.canvases(view)
        assert len(charts) == 4
        for chart in charts:
            event = self.wheel()
            event.accept()          # Qt hands events in pre-accepted
            chart.wheelEvent(event)
            assert not event.isAccepted()

    def test_the_stack_has_something_to_scroll(self, qtbot):
        """Guards the test above from passing vacuously on a stack that
        happens to fit."""
        from flograph.ui.inspector.figure_view import FigureView
        view = FigureView()
        qtbot.addWidget(view)
        view.resize(400, 300)
        view.set_figure(figures(4))
        view.show()
        qtbot.waitExposed(view)
        assert view._stack.verticalScrollBar().maximum() > 0

    def test_a_single_figure_keeps_its_toolbar(self, qtbot):
        """Only stacked canvases give the wheel up — a lone chart still has
        a toolbar and real pan/zoom to use it for."""
        from flograph.ui.inspector.figure_view import FigureView
        view = FigureView()
        qtbot.addWidget(view)
        view.set_figure(figures(1)[0])
        assert view._toolbar is not None and view._stack is None


class TestEditingACardInPlace:
    """Double-click the body to type, click away to go back to reading —
    the same in-place editor the Note card has, since both are markdown in
    a "text" param and both are quicker to edit where you are looking."""

    @pytest.fixture
    def env(self, qtbot, registry):
        graph = Graph()
        stack = QUndoStack()
        scene = NodeGraphScene(graph, stack, registry=registry)
        scene.output_cache = OutputCache()
        report = graph.add_node(registry.instantiate("flograph.viz.report_card"))
        graph.set_param(report.id, "text", "## Before")
        return graph, stack, scene.node_items[report.id], report.id

    def test_it_opens_showing_the_current_text(self, env):
        _graph, _stack, item, _node_id = env
        item.start_note_edit()
        assert item._note_editor is not None
        assert item._note_editor_widget.toPlainText() == "## Before"

    def test_the_rendered_view_steps_aside_while_typing(self, env):
        _graph, _stack, item, _node_id = env
        item.start_note_edit()
        assert not item._report_proxy.isVisible()

    def test_committing_writes_it_and_re_renders(self, env):
        graph, _stack, item, node_id = env
        item.start_note_edit()
        item._note_editor_widget.setPlainText("## After")
        item._finish_note_edit(commit=True)

        assert graph.node(node_id).params["text"] == "## After"
        assert item._report_proxy.isVisible()
        assert "After" in item._report_view.toPlainText()

    def test_it_is_one_undo_step(self, env):
        graph, stack, item, node_id = env
        item.start_note_edit()
        item._note_editor_widget.setPlainText("## After")
        item._finish_note_edit(commit=True)
        stack.undo()
        assert graph.node(node_id).params["text"] == "## Before"

    def test_cancelling_changes_nothing_and_restores_the_view(self, env):
        graph, _stack, item, node_id = env
        item.start_note_edit()
        item._note_editor_widget.setPlainText("## Throwaway")
        item._finish_note_edit(commit=False)

        assert graph.node(node_id).params["text"] == "## Before"
        assert item._report_proxy.isVisible()
        assert "Before" in item._report_view.toPlainText()

    def test_the_header_still_renames(self, env):
        """Double-clicking the title bar is rename, as on every other card
        — only the body opens the editor."""
        from PySide6.QtCore import QPointF
        _graph, _stack, item, node_id = env
        renamed = []
        item.scene().node_rename_requested.connect(renamed.append)

        class Event:
            def __init__(self, y):
                self._pos = QPointF(40, y)

            def pos(self):
                return self._pos

            def accept(self):
                pass

        item.mouseDoubleClickEvent(Event(4))       # header
        assert renamed == [node_id] and item._note_editor is None

        item.mouseDoubleClickEvent(Event(120))     # body
        assert item._note_editor is not None

    def test_a_plain_node_is_unaffected(self, env, registry):
        graph, stack, _item, _node_id = env
        scene = NodeGraphScene(graph, stack, registry=registry)
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        item = scene.node_items[node.id]
        item.start_note_edit()
        assert item._note_editor is None


class TestTheEditorContextMenu:
    """Reported 2026-07-26: "context menu on editmode of report node, for
    somthing like add -> list of addable items from canvas. and maybe a copy
    and paste option while we are there."

    A report page has a toolbar button for this; a card has no room for one,
    and the embed syntax is the one thing about a report card you cannot
    guess — so it lives where you are typing."""

    @pytest.fixture
    def editing(self, qtbot, registry):
        from PySide6.QtGui import QUndoStack
        from flograph.core import Graph
        from flograph.engine.cache import OutputCache
        from flograph.ui.canvas import NodeGraphScene
        graph = Graph()
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        scene.output_cache = OutputCache()
        card = graph.add_node(registry.instantiate("flograph.viz.report_card"))
        wired = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_label(wired.id, "Revenue")
        graph.connect(wired.id, "value", card.id, "a")
        scene.output_cache.set(wired.id, {"value": 42}, 0.0)
        item = scene.node_items[card.id]
        item.start_note_edit()
        return graph, scene, item

    def menu(self, item):
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        return menu, item.add_insert_menu(menu)

    def entries(self, menu):
        """(text, enabled) for everything in the Insert submenu."""
        submenu = next(a.menu() for a in menu.actions()
                       if a.menu() is not None and a.text() == "Insert")
        return [(a.text(), a.isEnabled()) for a in submenu.actions()
                if not a.isSeparator()]

    def test_the_editor_offers_the_standard_copy_and_paste(self, editing):
        """The "copy and paste option while we are there" — Qt's own menu
        already carries them, so the job is to build on it rather than
        replace it."""
        _graph, _scene, item = editing
        editor = item._note_editor_widget
        standard = [a.text() for a in editor.createStandardContextMenu().actions()]
        # "&" are keyboard mnemonics — Qt writes Cut as "cu&t"
        joined = " ".join(standard).casefold().replace("&", "")
        for wanted in ("copy", "paste", "cut", "undo"):
            assert wanted in joined

    def test_wired_inputs_come_first(self, editing):
        _graph, _scene, item = editing
        menu, _actions = self.menu(item)
        assert self.entries(menu)[0] == ("a", True)

    def test_an_unwired_input_is_listed_but_disabled(self, editing):
        """Seeing that `c` exists and has nothing in it is the useful part;
        omitting it would leave you wondering."""
        _graph, _scene, item = editing
        menu, _actions = self.menu(item)
        assert ("c  — nothing wired in", False) in self.entries(menu)

    def test_nodes_that_have_run_are_offered_by_label(self, editing):
        _graph, _scene, item = editing
        menu, _actions = self.menu(item)
        assert ("Revenue", True) in self.entries(menu)

    def test_it_does_not_offer_the_card_itself(self, editing):
        graph, scene, item = editing
        scene.output_cache.set(item.node.id, {"text": "hi"}, 0.0)
        menu, _actions = self.menu(item)
        assert all(text != item.node.label for text, _on in self.entries(menu))

    def test_a_duplicate_label_is_disabled(self, editing):
        graph, _scene, item = editing
        twin = graph.add_node(
            _constant(graph))
        graph.set_label(twin.id, "Revenue")
        menu, _actions = self.menu(item)
        labels = dict(self.entries(menu))
        assert labels.get("Revenue  — duplicate name, rename one first") is False

    def test_choosing_one_writes_the_embed_on_its_own_line(self, editing):
        _graph, _scene, item = editing
        editor = item._note_editor_widget
        editor.setPlainText("Some prose.")
        cursor = editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        editor.setTextCursor(cursor)
        editor.insert_embed("Revenue")
        assert editor.toPlainText() == "Some prose.\n\n![[Revenue]]\n"

    def test_opening_the_menu_does_not_end_edit_mode(self, editing):
        """Reported 2026-07-26: "when i edit the node, and right click it just
        ends edit mode". The editor commits on focus-out, and a popup takes
        focus while it is up — so the menu closed the editor out from under
        itself and never appeared."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QFocusEvent
        _graph, _scene, item = editing
        editor = item._note_editor_widget
        editor.setPlainText("half-written")

        for reason in (Qt.PopupFocusReason, Qt.ActiveWindowFocusReason):
            item.eventFilter(editor, QFocusEvent(QFocusEvent.Type.FocusOut,
                                                 reason))
            assert item._note_editor_widget is editor, reason  # still editing
            assert item.node.params.get("text") != "half-written"

    def test_clicking_away_still_commits(self, editing):
        """The popup exemption must not swallow the ordinary case."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QFocusEvent
        _graph, _scene, item = editing
        editor = item._note_editor_widget
        editor.setPlainText("done typing")

        item.eventFilter(editor, QFocusEvent(QFocusEvent.Type.FocusOut,
                                             Qt.MouseFocusReason))
        assert item._note_editor_widget is None
        assert item.node.params.get("text") == "done typing"

    def test_a_note_card_gets_no_insert_menu(self, qtbot, registry):
        """Notes are markdown too, but have no embeds to offer."""
        from PySide6.QtGui import QUndoStack
        from PySide6.QtWidgets import QMenu
        from flograph.core import Graph
        from flograph.ui.canvas import NodeGraphScene
        graph = Graph()
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        note = graph.add_node(registry.instantiate("flograph.util.note"))
        item = scene.node_items[note.id]
        item.start_note_edit()
        menu = QMenu()
        assert item.add_insert_menu(menu) == {}
        assert menu.actions() == []
