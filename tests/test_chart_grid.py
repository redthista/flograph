"""Arranging a list of charts in a grid.

Columns and rows, either of which may be 0 meaning "work it out", plus a
fill direction. One definition (core.chart_grid) shared by the canvas card,
the dashboard tile, the plotly page and the PDF, so a node's charts are
laid out the same way everywhere they are shown.
"""
import pytest

from flograph.core.chart_grid import (DEFAULT_DIRECTION, cells,
                                      grid_settings, grid_shape)


class TestTheShape:

    def test_nothing_configured_is_a_single_column(self):
        """The direction decides when there is nothing to derive from, and
        it defaults to "down" so an unconfigured stack looks the way stacks
        always have."""
        assert DEFAULT_DIRECTION == "down"
        assert grid_shape(5) == (1, 5)

    def test_across_with_nothing_else_set_is_a_single_row(self):
        assert grid_shape(5, direction="across") == (5, 1)

    def test_columns_derive_the_rows(self):
        assert grid_shape(6, columns=2) == (2, 3)
        assert grid_shape(7, columns=3) == (3, 3)      # rounded up, not down

    def test_rows_derive_the_columns(self):
        """Rows with columns left at 0 is the single scrolling row."""
        assert grid_shape(6, rows=1) == (6, 1)
        assert grid_shape(7, rows=2) == (4, 2)

    def test_both_given_are_taken_as_asked(self):
        assert grid_shape(6, columns=3, rows=2) == (3, 2)

    def test_a_grid_too_small_grows_rather_than_hiding_charts(self):
        """Comparing a *complete* set is the point — a layout setting that
        silently dropped the last three would defeat it."""
        columns, rows = grid_shape(10, columns=3, rows=2)
        assert columns * rows >= 10
        assert columns == 3          # respects the width that was asked for

    def test_no_charts(self):
        assert grid_shape(0) == (1, 0)


class TestAnExplicitGridKeepsItsShape:
    """Asking for 2 columns and 3 rows with 3 charts should get you a 2x3
    grid with an empty cell — not a grid quietly shrunk to the cells that
    happened to be filled, which would resize every chart behind your
    back."""

    def test_the_shape_is_what_was_asked_for(self):
        assert grid_shape(3, columns=2, rows=3) == (2, 3)

    def test_across_leaves_the_last_row_empty(self):
        placed = cells(3, columns=2, rows=3, direction="across")
        assert placed == [(0, 0), (0, 1), (1, 0)]
        assert 2 not in {row for row, _ in placed}      # bottom row is blank

    def test_down_leaves_the_last_column_empty(self):
        placed = cells(3, columns=2, rows=3, direction="down")
        assert placed == [(0, 0), (1, 0), (2, 0)]
        assert 1 not in {column for _, column in placed}

    def test_the_matplotlib_grid_reserves_the_empty_cells(self, qtbot):
        from matplotlib.figure import Figure
        from flograph.ui.inspector.figure_view import FigureView
        view = FigureView()
        qtbot.addWidget(view)
        view.set_grid(columns=2, rows=3, direction="across")
        figures = []
        for i in range(3):
            figure = Figure(figsize=(4, 2))
            figure.add_subplot().plot([1, 2 + i, 3])
            figures.append(figure)
        view.set_figure(figures)

        layout = view._stack.widget().layout()
        assert (layout.columnCount(), layout.rowCount()) == (2, 3)
        assert layout.rowMinimumHeight(2) > 0        # the blank row is real

    def test_the_plotly_grid_reserves_them_too(self):
        from flograph.ui.inspector.plotly_view import to_html

        class Fake:
            def to_html(self, **kw):
                return "<div class='plotly-graph-div'></div>"

        page = to_html([Fake() for _ in range(3)], columns=2, rows=3)
        assert "grid-template-rows:repeat(3," in page

    def test_the_pdf_grid_reserves_them_too(self, qtbot):
        # figures, not frames: a frame renders as its own nested table and
        # its rows would be counted alongside the grid's
        from matplotlib.figure import Figure
        from flograph.core import Graph, NodeRegistry
        from flograph.engine.cache import OutputCache
        from flograph.ui.report.render import render_report

        registry = NodeRegistry()
        registry.load_builtins()
        graph, cache = Graph(), OutputCache()
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_label(node.id, "Split")
        figures = []
        for i in range(3):
            figure = Figure(figsize=(4, 2))
            figure.add_subplot().plot([1, 2 + i, 3])
            figures.append(figure)
        cache.set(node.id, {"value": figures}, 0.0)
        node.params.update({"columns": 2, "rows": 3, "direction": "across"})

        html = render_report("![[Split]]", graph, cache).document.toHtml()
        assert html.count("<tr") == 3          # including the empty one
        assert html.count("<td") == 6          # 2 x 3, three of them blank
        assert html.count('src="embed:') == 3


class TestThePlacement:

    def test_the_direction_alone_lays_them_out(self):
        assert cells(3, direction="across") == [(0, 0), (0, 1), (0, 2)]
        assert cells(3, direction="down") == [(0, 0), (1, 0), (2, 0)]

    def test_across_fills_rows_left_to_right(self):
        assert cells(6, columns=2, direction="across") == [
            (0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)]

    def test_down_fills_columns_top_to_bottom(self):
        assert cells(6, columns=2, direction="down") == [
            (0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1)]

    def test_a_single_row_runs_sideways(self):
        assert cells(4, rows=1) == [(0, 0), (0, 1), (0, 2), (0, 3)]

    def test_the_default_is_a_column(self):
        assert cells(3) == [(0, 0), (1, 0), (2, 0)]

    def test_every_chart_gets_its_own_cell(self):
        for count in range(1, 20):
            for columns in range(0, 5):
                for direction in ("across", "down"):
                    placed = cells(count, columns=columns, direction=direction)
                    assert len(placed) == count
                    assert len(set(placed)) == count, "two charts overlap"

    def test_an_unknown_direction_is_refused(self):
        with pytest.raises(ValueError, match="unknown direction"):
            cells(3, direction="diagonally")


class TestReadingTheSettings:
    """Every one of these is optional — a list-producing node that declares
    none of them, which is every one written before this existed, must keep
    stacking the way it always did."""

    def test_no_params_at_all(self):
        assert grid_settings(None) == (0, 0, "down")
        assert grid_settings({}) == (0, 0, "down")

    def test_values_are_read(self):
        assert grid_settings(
            {"columns": 3, "rows": 2, "direction": "down"}) == (3, 2, "down")

    def test_strings_from_a_saved_file_are_accepted(self):
        assert grid_settings({"columns": "3", "rows": "0"}) == (3, 0, "down")

    def test_junk_falls_back_rather_than_raising(self):
        assert grid_settings(
            {"columns": "lots", "rows": None, "direction": "sideways"}) \
            == (0, 0, "down")

    def test_negatives_are_treated_as_unset(self):
        assert grid_settings({"columns": -4}) == (0, 0, "down")

    def test_direction_is_case_insensitive(self):
        assert grid_settings({"direction": "Down"})[2] == "down"


class TestTheHostsAgree:
    """The grid is only worth having if the card, the tile and the PDF all
    arrange a node's charts identically."""

    def figures(self, count):
        from matplotlib.figure import Figure
        made = []
        for i in range(count):
            figure = Figure(figsize=(4, 2))
            figure.add_subplot().plot([1, 2 + i, 3])
            made.append(figure)
        return made

    def test_the_matplotlib_stack_uses_it(self, qtbot):
        from flograph.ui.inspector.figure_view import FigureView
        view = FigureView()
        qtbot.addWidget(view)
        view.set_grid(columns=3)
        view.set_figure(self.figures(6))

        layout = view._stack.widget().layout()
        placed = [layout.getItemPosition(i)[:2]
                  for i in range(layout.count())
                  if layout.itemAt(i).widget() is not None]
        assert placed == cells(6, columns=3)

    def test_the_plotly_page_uses_it(self):
        from flograph.ui.inspector.plotly_view import to_html

        class Fake:
            def to_html(self, **kw):
                return "<div class='c'></div>"

        html = to_html([Fake() for _ in range(6)], columns=3)
        assert "repeat(3,minmax(0,1fr))" in html
        for row, column in cells(6, columns=3):
            assert f"grid-row:{row + 1};grid-column:{column + 1}" in html

    def test_the_plotly_page_honours_a_row(self):
        """Any node returning a list can declare these — the plotly stacker
        gets it for nothing."""
        from flograph.ui.inspector.plotly_view import to_html

        class Fake:
            def to_html(self, **kw):
                return "<div class='c'></div>"

        html = to_html([Fake() for _ in range(4)], direction="across")
        assert "repeat(4,minmax(0,1fr))" in html

    def test_a_single_column_plotly_page_is_unchanged(self):
        from flograph.ui.inspector.plotly_view import to_html

        class Fake:
            def to_html(self, **kw):
                return "<div class='c'></div>"

        assert "repeat(1,minmax(0,1fr))" in to_html([Fake(), Fake()])


class TestChangingTheLayoutIsImmediate:
    """Columns/Rows/Fill are layout, not data — but changing a param
    dirties the node and evicts its cache, so a view that waited for the
    next run would sit on the old arrangement with nothing to recompute
    it."""

    def figures(self, count=6):
        from matplotlib.figure import Figure
        made = []
        for i in range(count):
            figure = Figure(figsize=(4, 2))
            figure.add_subplot().plot([1, 2 + i, 3])
            made.append(figure)
        return made

    def shape(self, view):
        layout = view._stack.widget().layout()
        return (layout.columnCount(), layout.rowCount())

    def test_the_matplotlib_stack_re_arranges_on_the_spot(self, qtbot):
        from flograph.ui.inspector.figure_view import FigureView
        view = FigureView()
        qtbot.addWidget(view)
        view.set_figure(self.figures())
        assert self.shape(view) == (1, 6)

        view.set_grid(columns=3)
        assert self.shape(view) == (3, 2)
        view.set_grid(direction="across")
        assert self.shape(view) == (6, 1)

    def test_an_unchanged_grid_does_not_rebuild(self, qtbot):
        from flograph.ui.inspector.figure_view import FigureView
        view = FigureView()
        qtbot.addWidget(view)
        view.set_figure(self.figures(2))
        before = view._stack
        view.set_grid()          # same as the default
        assert view._stack is before

    def test_a_single_figure_forgets_the_list(self, qtbot):
        """...so a later set_grid can't resurrect a stack that is gone."""
        from flograph.ui.inspector.figure_view import FigureView
        view = FigureView()
        qtbot.addWidget(view)
        view.set_figure(self.figures(3))
        view.set_figure(self.figures(1)[0])
        view.set_grid(columns=2)
        assert view._stack is None and view._canvas is not None

    def test_the_plotly_page_re_renders_on_the_spot(self, qtbot):
        from flograph.ui.inspector.plotly_view import PlotlyView

        class Fake:
            def to_html(self, **kw):
                return "<div class='c'></div>"

        view = PlotlyView()
        qtbot.addWidget(view)
        view.set_content([Fake() for _ in range(4)])
        assert view._content is not None
        view.set_grid(direction="across")
        assert view._grid == (0, 0, "across")


class TestLayoutIsNotData:
    """Columns/Rows/Fill are declared `"cosmetic": True`, so changing one
    re-arranges the charts without invalidating the node. Re-running a slow
    split — and everything downstream of it — to produce exactly what it
    already produced would be absurd."""

    @pytest.fixture
    def env(self):
        from flograph.core import Graph, NodeRegistry
        registry = NodeRegistry()
        registry.load_builtins()
        graph = Graph()
        node = graph.add_node(
            registry.instantiate("flograph.viz.chart_per_value"))
        node.dirty = False
        return graph, node

    def test_the_layout_params_are_declared_cosmetic(self, env):
        _graph, node = env
        # "scale" too, unlike the single-chart nodes: zooming the card is
        # presentation, and this node's run can be slow
        for name in ("columns", "rows", "direction", "scale"):
            assert node.spec.param(name).cosmetic, name

    def test_changing_them_leaves_the_node_clean(self, env):
        graph, node = env
        graph.set_param(node.id, "columns", 3)
        graph.set_param(node.id, "direction", "across")
        graph.set_param(node.id, "scale", 50)
        assert not node.dirty

    def test_a_real_setting_still_dirties_it(self, env):
        graph, node = env
        graph.set_param(node.id, "split_by", "region")
        assert node.dirty

    def test_downstream_is_left_alone_too(self, env, ):
        from flograph.core import NodeRegistry
        registry = NodeRegistry()
        registry.load_builtins()
        graph, node = env
        after = graph.add_node(registry.instantiate("flograph.viz.show_table"))
        after.dirty = False
        graph.set_param(node.id, "columns", 2)
        assert not after.dirty

    def test_params_are_not_cosmetic_unless_they_say_so(self, env):
        _graph, node = env
        assert not node.spec.param("split_by").cosmetic
        assert not node.spec.param("width").cosmetic


class TestScaleZoomsTheStack:
    """Scale % on the stack nodes does what it does on the single-chart
    ones: zooms the card's contents, so a smaller setting fits more of the
    stack on the same card. Width and Height size the card; this doesn't."""

    @pytest.fixture
    def env(self, qtbot):
        from PySide6.QtGui import QUndoStack
        from flograph.core import Graph, NodeRegistry
        from flograph.ui.canvas import NodeGraphScene
        registry = NodeRegistry()
        registry.load_builtins()
        graph = Graph()
        stack = QUndoStack()
        scene = NodeGraphScene(graph, stack, registry=registry)
        yield graph, scene, registry
        stack.clear()

    def test_it_zooms_the_embedded_stack(self, env):
        graph, scene, registry = env
        node = graph.add_node(
            registry.instantiate("flograph.viz.chart_per_value"))
        proxy = scene.node_items[node.id]._figure_proxy
        assert proxy.scale() == 1.0

        graph.set_param(node.id, "scale", 50)
        rect = scene.node_items[node.id]._figure_proxy_rect()
        assert proxy.scale() == 0.5
        # half scale hands the stack twice the logical room, which is what
        # puts more charts on the card rather than shrinking the card
        assert proxy.size().width() == pytest.approx(rect.width() / 0.5)

        graph.set_param(node.id, "scale", 9999)   # clamped to 400%
        assert proxy.scale() == 4.0

    def test_the_plotly_twin_declares_it_too(self, env):
        _graph, _scene, registry = env
        spec = registry.get("flograph.viz.chart_per_value_plotly")
        assert spec.param("scale").cosmetic
        assert spec.default_params()["scale"] == 100


class TestPlotlyCannotSpillIntoItsNeighbour:
    """Plotly sizes its plot in pixels when it initialises. If the grid
    hasn't settled by then it picks its own default and the chart spills
    out of its cell, painting over the one next door — which is what a
    3-chart, 2-column stack did."""

    def html(self, count=3, **grid):
        from flograph.ui.inspector.plotly_view import to_html

        class Fake:
            def to_html(self, **kw):
                return "<div class='plotly-graph-div'></div>"

        return to_html([Fake() for _ in range(count)], **grid)

    def test_each_cell_clips_its_own_chart(self):
        assert "overflow:hidden" in self.html(columns=2)

    def test_plotly_is_told_to_re_measure_once_laid_out(self):
        """The belt to the clip's braces: after load, every chart is asked
        to resize, so there is nothing left to clip."""
        page = self.html(columns=2)
        assert "Plotly.Plots.resize" in page
        assert "addEventListener('load'" in page

    def test_the_rows_still_stretch_into_spare_height(self):
        """Fixing the spill must not undo the fill — a short stack should
        still grow into the card rather than leave it half empty."""
        page = self.html(columns=2)
        assert "grid-template-rows:repeat(" in page and ",1fr))" in page
        assert "min-height:100%" in page


class TestCosmeticChangesStillReachTheViews:
    """The catch in making layout params cosmetic: nothing runs, so
    node_succeeded never fires — and every report surface was refreshing
    off exactly that signal. A setting that changed the model but not the
    screen would be worse than the re-run it was avoiding."""

    def figures(self, count=3):
        from matplotlib.figure import Figure
        made = []
        for i in range(count):
            figure = Figure(figsize=(4, 2))
            figure.add_subplot().plot([1, 2 + i, 3])
            made.append(figure)
        return made

    @pytest.fixture
    def window(self, qtbot, tmp_path, monkeypatch):
        from PySide6.QtCore import QSettings
        from flograph.core import NodeRegistry
        from flograph.ui import mainwindow as mod
        monkeypatch.setattr(
            mod, "QSettings",
            lambda *a, **k: QSettings(str(tmp_path / "s.ini"),
                                      QSettings.IniFormat))
        registry = NodeRegistry()
        registry.load_builtins()
        win = mod.MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def test_a_report_page_re_renders(self, window, qtbot):
        from flograph.core import Page
        source = window.graph.add_node(
            window.registry.instantiate("flograph.viz.chart_per_value"))
        window.graph.set_label(source.id, "Split")
        window.engine.cache.set(source.id, {"figures": self.figures()}, 0.0)
        window.graph.add_page(Page(id="r", kind="report",
                                   body="![[Split]]"))
        page = window._dashboard_pages["r"]
        page.refresh_preview()
        assert page.preview.document().toHtml().count("<td") == 0

        source.dirty = False        # nodes are born dirty; start from clean
        window.graph.set_param(source.id, "columns", 2)
        qtbot.waitUntil(
            lambda: page.preview.document().toHtml().count("<td") == 4,
            timeout=2000)
        assert not source.dirty          # ...and it never ran to do it

    def test_a_report_card_re_renders(self, window):
        source = window.graph.add_node(
            window.registry.instantiate("flograph.viz.chart_per_value"))
        card = window.graph.add_node(
            window.registry.instantiate("flograph.viz.report_card"))
        window.graph.connect(source.id, "figures", card.id, "a")
        window.engine.cache.set(source.id, {"figures": self.figures()}, 0.0)
        window.graph.set_param(card.id, "text", "![[a]]")

        item = window.scene.node_items[card.id]
        window._refresh_report_cards()
        assert item._report_view.document().toHtml().count("<td") == 0
        window.graph.set_param(source.id, "columns", 2)
        # a param edit schedules the re-render rather than doing it inline,
        # so a burst of them costs one pass — fire the pending one
        window._refresh_report_cards()
        assert item._report_view.document().toHtml().count("<td") == 4

    def test_a_report_tile_re_renders(self, window):
        from flograph.core import Page, Tile
        source = window.graph.add_node(
            window.registry.instantiate("flograph.viz.chart_per_value"))
        card = window.graph.add_node(
            window.registry.instantiate("flograph.viz.report_card"))
        window.graph.connect(source.id, "figures", card.id, "a")
        window.engine.cache.set(source.id, {"figures": self.figures()}, 0.0)
        window.graph.set_param(card.id, "text", "![[a]]")
        window.graph.add_page(Page(id="b", title="Board"))
        window.graph.add_tile("b", Tile(id="t", node_id=card.id, port="text"))

        tile = window._dashboard_pages["b"].scene.tile_items["t"]
        assert tile._report_view.document().toHtml().count("<td") == 0
        window.graph.set_param(source.id, "columns", 2)
        assert tile._report_view.document().toHtml().count("<td") == 4
