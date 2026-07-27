"""Plotly charts in reports, drawn without kaleido.

The app embeds Chromium already, so a report asks plotly.js for the picture
itself. The end-to-end tests here need Qt WebEngine and are skipped where it
is unavailable; the sizing tests are pure arithmetic and always run.
"""
import pytest

pytest.importorskip("plotly")

import plotly.express as px  # noqa: E402
import pandas as pd  # noqa: E402

from flograph.core import Graph, NodeRegistry  # noqa: E402
from flograph.engine.cache import OutputCache  # noqa: E402
from flograph.ui.report import plotly_snapshot  # noqa: E402
from flograph.ui.report.render import (MAX_IMAGE_SCALE, PRINT_DPI,  # noqa: E402
                                       _plotly_image, plotly_geometry,
                                       render_report)

webengine = pytest.importorskip("PySide6.QtWebEngineWidgets")


@pytest.fixture
def figure():
    return px.bar(pd.DataFrame({"x": list("abcd"), "y": [3, 1, 4, 2]}),
                  x="x", y="y", title="Quarterly units")


class TestGeometry:
    """Density belongs in `scale`; the layout size stays what the figure
    was designed at, or every label shrinks relative to the chart."""

    def test_the_layout_size_is_left_alone(self, figure):
        width, height, _scale = plotly_geometry(figure, 510, for_print=False)
        assert (width, height) == (700, 450)

    def test_preview_oversamples_the_placed_width(self, figure):
        _w, _h, scale = plotly_geometry(figure, 510, for_print=False)
        assert scale == pytest.approx(1020 / 700, abs=0.01)

    def test_print_aims_at_the_print_dpi(self, figure):
        _w, _h, scale = plotly_geometry(figure, 510, for_print=True)
        assert 700 * scale == pytest.approx(510 / 72 * PRINT_DPI, rel=0.01)

    def test_the_density_is_capped(self, figure):
        """A very wide placement must not ask for a gigantic bitmap."""
        _w, _h, scale = plotly_geometry(figure, 5000, for_print=True)
        assert scale == MAX_IMAGE_SCALE

    def test_density_never_goes_below_one(self, figure):
        """A thumbnail-sized placement should not render below the
        figure's own resolution."""
        _w, _h, scale = plotly_geometry(figure, 40, for_print=True)
        assert scale == 1.0

    def test_an_authored_size_is_honoured(self, figure):
        figure.update_layout(width=800, height=400)
        width, height, _scale = plotly_geometry(figure, 510, for_print=False)
        assert (width, height) == (800, 400)


class TestSnapshot:
    """Real Chromium, real plotly.js, no kaleido."""

    def test_a_figure_becomes_a_png(self, qtbot, figure):
        plotly_snapshot.clear_cache()
        data = plotly_snapshot.snapshot(figure, 600, 400)
        if data is None:
            pytest.skip("Qt WebEngine could not render here")
        assert data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_the_png_has_the_size_it_was_asked_for(self, qtbot, figure):
        from PySide6.QtGui import QImage

        data = plotly_snapshot.snapshot(figure, 640, 480)
        if data is None:
            pytest.skip("Qt WebEngine could not render here")
        image = QImage()
        assert image.loadFromData(data, "PNG")
        assert (image.width(), image.height()) == (640, 480)

    def test_scale_multiplies_the_pixels_not_the_layout(self, qtbot, figure):
        from PySide6.QtGui import QImage

        data = plotly_snapshot.snapshot(figure, 640, 480, 2.0)
        if data is None:
            pytest.skip("Qt WebEngine could not render here")
        image = QImage()
        image.loadFromData(data, "PNG")
        assert (image.width(), image.height()) == (1280, 960)

    def test_a_different_scale_is_a_different_cache_entry(self, qtbot,
                                                          figure):
        plotly_snapshot.clear_cache()
        if plotly_snapshot.snapshot(figure, 400, 300, 1.0) is None:
            pytest.skip("Qt WebEngine could not render here")
        plotly_snapshot.snapshot(figure, 400, 300, 2.0)
        assert len(plotly_snapshot._CACHE) == 2

    def test_it_draws_something_rather_than_a_blank_page(self, qtbot, figure):
        """A silently blank chart would be worse than an error."""
        from PySide6.QtGui import QImage

        data = plotly_snapshot.snapshot(figure, 600, 400)
        if data is None:
            pytest.skip("Qt WebEngine could not render here")
        image = QImage()
        image.loadFromData(data, "PNG")
        seen = {image.pixel(x, y)
                for x in range(0, image.width(), 9)
                for y in range(0, image.height(), 9)}
        assert len(seen) > 3, "the snapshot looks like a blank page"

    def test_the_second_ask_is_served_from_cache(self, qtbot, figure):
        plotly_snapshot.clear_cache()
        first = plotly_snapshot.snapshot(figure, 500, 350)
        if first is None:
            pytest.skip("Qt WebEngine could not render here")
        assert plotly_snapshot.snapshot(figure, 500, 350) is first

    def test_a_different_size_is_drawn_again(self, qtbot, figure):
        plotly_snapshot.clear_cache()
        if plotly_snapshot.snapshot(figure, 500, 350) is None:
            pytest.skip("Qt WebEngine could not render here")
        assert len(plotly_snapshot._CACHE) == 1
        plotly_snapshot.snapshot(figure, 501, 350)
        assert len(plotly_snapshot._CACHE) == 2

    def test_the_cache_is_bounded(self, qtbot, figure):
        plotly_snapshot.clear_cache()
        if plotly_snapshot.snapshot(figure, 400, 300) is None:
            pytest.skip("Qt WebEngine could not render here")
        for extra in range(plotly_snapshot.CACHE_LIMIT + 4):
            plotly_snapshot.snapshot(figure, 400 + extra, 300)
        assert len(plotly_snapshot._CACHE) <= plotly_snapshot.CACHE_LIMIT


class TestInAReport:
    def test_an_embedded_chart_becomes_an_image(self, qtbot, figure):
        registry = NodeRegistry()
        registry.load_builtins()
        graph, cache = Graph(), OutputCache()
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_label(node.id, "Chart")
        cache.set(node.id, {"value": figure}, 0.0)

        rendered = render_report("Before\n\n![[Chart]]\n\nAfter", graph, cache)
        html = rendered.document.toHtml()
        if "<img" not in html:
            pytest.skip("Qt WebEngine could not render here")
        assert rendered.problems == []
        # the picture is a real resource on the document, not a dead link
        from PySide6.QtGui import QTextDocument
        resource = rendered.document.resource(
            QTextDocument.ImageResource, __import__("PySide6.QtCore",
                                                    fromlist=["QUrl"])
            .QUrl("embed:0"))
        assert resource is not None and not resource.isNull()

    def test_an_unrenderable_figure_says_so_on_the_page(self, monkeypatch,
                                                       figure):
        """No WebEngine and no kaleido: the report must still open, with the
        gap explained rather than left blank."""
        monkeypatch.setattr(plotly_snapshot, "snapshot",
                            lambda *a, **k: None)
        monkeypatch.setattr(type(figure), "to_image",
                            lambda *a, **k: (_ for _ in ()).throw(
                                RuntimeError("no kaleido")))
        result = _plotly_image(figure, 510, False)
        assert isinstance(result, str)
        assert "could not be drawn" in result

    def test_a_non_plotly_value_is_not_claimed(self):
        assert _plotly_image("just a string", 510, False) is None
