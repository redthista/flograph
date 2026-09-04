"""An HTML visual on a report page looks like it does on its card.

A webview node returns HTML. Until this, a report received that string and
inlined it *as markdown*: Qt's rich text engine kept the words and threw
the design away. Now the page carries a picture of the card, taken by the
same Chromium the card draws in, at the card's own pixel size.

The end-to-end tests need Qt WebEngine and skip where it is unavailable;
the sizing tests are arithmetic and always run.
"""
import pytest

from flograph.core import Graph, NodeRegistry
from flograph.engine.cache import OutputCache
from flograph.ui.report import html_snapshot
from flograph.ui.report.render import (HTML_CARD_SIZE, MAX_IMAGE_SCALE,
                                       PRINT_DPI, html_geometry, html_image,
                                       render_report)

PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;padding:0;background:#1e3a8a;color:#fff;
  font-family:sans-serif}
.kpi{display:flex;gap:12px;padding:20px}
.kpi div{background:#7c3aed;border-radius:10px;padding:14px 18px;flex:1}
</style></head><body><h1 style="padding:0 20px">Sales</h1>
<div class="kpi"><div>£1.2m</div><div>412</div><div>18%</div></div>
</body></html>"""


@pytest.fixture
def web_graph():
    """A Show Web View node that has produced `PAGE`."""
    registry = NodeRegistry()
    registry.load_builtins()
    graph, cache = Graph(), OutputCache()
    node = graph.add_node(registry.instantiate("flograph.viz.show_web"))
    graph.set_label(node.id, "Dashboard")
    port = node.spec.outputs[0].name
    cache.set(node.id, {port: PAGE}, 0.0)
    return graph, cache, node


class TestGeometry:
    """The card's pixel size is the layout; the placement only sets how
    dense the picture is. A wider page would re-wrap the HTML, not sharpen
    it — the same split plotly_geometry draws."""

    def test_the_cards_own_size_is_the_layout_size(self):
        width, height, _s = html_geometry({"width": 520, "height": 300}, 510,
                                          for_print=False)
        assert (width, height) == (520, 300)

    def test_a_card_with_no_size_falls_back(self):
        width, height, _s = html_geometry({}, 510, for_print=False)
        assert (width, height) == HTML_CARD_SIZE

    def test_a_nonsense_size_falls_back(self):
        width, height, _s = html_geometry({"width": "", "height": 0}, 510,
                                          for_print=False)
        assert (width, height) == HTML_CARD_SIZE

    def test_print_aims_at_the_print_dpi(self):
        """A card wide enough that the density cap doesn't bite: the
        picture lands at PRINT_DPI for the width it is placed at."""
        _w, _h, scale = html_geometry({"width": 700}, 510, for_print=True)
        assert 700 * scale == pytest.approx(510 / 72 * PRINT_DPI, rel=0.01)

    def test_a_small_card_is_capped_rather_than_blown_up(self):
        """A 420px card on a full-width page would want 5x; the cap holds
        it at 4, which is still ~210dpi on paper."""
        _w, _h, scale = html_geometry({"width": 420}, 510, for_print=True)
        assert scale == MAX_IMAGE_SCALE

    def test_the_density_is_capped(self):
        _w, _h, scale = html_geometry({"width": 300}, 5000, for_print=True)
        assert scale == MAX_IMAGE_SCALE

    def test_a_ratio_moves_only_the_height(self):
        width, height, _s = html_geometry({"width": 480, "height": 300}, 510,
                                          for_print=False, aspect=16 / 9)
        assert width == 480
        assert height == round(480 / (16 / 9))

    def test_a_scale_multiplier_pushes_the_density_up(self):
        _w, _h, plain = html_geometry({"width": 400}, 510, for_print=False)
        _w, _h, dense = html_geometry({"width": 400}, 510, for_print=False,
                                      scale_mult=2.0)
        assert dense > plain


class TestSnapshot:
    """Real Chromium, printed to PDF and rasterised — a screen grab of a
    web view comes back blank."""

    def test_a_page_becomes_a_png(self, qtbot):
        html_snapshot.clear_cache()
        data = html_snapshot.snapshot(PAGE, 400, 300)
        if data is None:
            pytest.skip("Qt WebEngine could not render here")
        assert data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_the_png_has_the_size_it_was_asked_for(self, qtbot):
        from PySide6.QtGui import QImage

        data = html_snapshot.snapshot(PAGE, 420, 320)
        if data is None:
            pytest.skip("Qt WebEngine could not render here")
        image = QImage()
        assert image.loadFromData(data, "PNG")
        assert (image.width(), image.height()) == (420, 320)

    def test_scale_multiplies_the_pixels_not_the_layout(self, qtbot):
        from PySide6.QtGui import QImage

        data = html_snapshot.snapshot(PAGE, 420, 320, 2.0)
        if data is None:
            pytest.skip("Qt WebEngine could not render here")
        image = QImage()
        image.loadFromData(data, "PNG")
        assert (image.width(), image.height()) == (840, 640)

    def test_the_pages_own_colours_survive(self, qtbot):
        """Chromium's print path drops element backgrounds unless told
        otherwise, and a dashboard card is mostly background."""
        from PySide6.QtGui import QImage

        data = html_snapshot.snapshot(PAGE, 400, 300)
        if data is None:
            pytest.skip("Qt WebEngine could not render here")
        image = QImage()
        image.loadFromData(data, "PNG")
        seen = {image.pixel(x, y)
                for x in range(0, image.width(), 7)
                for y in range(0, image.height(), 7)}
        assert len(seen) > 3, "the snapshot looks like a blank page"

    def test_the_second_ask_is_served_from_cache(self, qtbot):
        html_snapshot.clear_cache()
        first = html_snapshot.snapshot(PAGE, 300, 200)
        if first is None:
            pytest.skip("Qt WebEngine could not render here")
        assert html_snapshot.snapshot(PAGE, 300, 200) is first

    def test_the_cache_is_bounded(self, qtbot):
        html_snapshot.clear_cache()
        if html_snapshot.snapshot(PAGE, 200, 150) is None:
            pytest.skip("Qt WebEngine could not render here")
        for extra in range(html_snapshot.CACHE_LIMIT + 3):
            html_snapshot.snapshot(PAGE, 200 + extra, 150)
        assert len(html_snapshot._CACHE) <= html_snapshot.CACHE_LIMIT


class TestInAReport:
    def test_an_html_visual_becomes_a_picture(self, qtbot, web_graph):
        graph, cache, _node = web_graph
        rendered = render_report("Before\n\n![[Dashboard]]\n\nAfter",
                                 graph, cache)
        html = rendered.document.toHtml()
        if "<img" not in html:
            pytest.skip("Qt WebEngine could not render here")
        assert rendered.problems == []
        assert len(rendered.images) == 1
        # …and not the raw markup, which is what used to land on the page
        assert "background:#1e3a8a" not in html

    def test_the_picture_is_a_real_document_resource(self, qtbot, web_graph):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QTextDocument

        graph, cache, _node = web_graph
        rendered = render_report("![[Dashboard]]", graph, cache)
        if "<img" not in rendered.document.toHtml():
            pytest.skip("Qt WebEngine could not render here")
        resource = rendered.document.resource(QTextDocument.ImageResource,
                                              QUrl("embed:0"))
        assert resource is not None and not resource.isNull()

    def test_the_card_size_decides_the_layout(self, qtbot, web_graph):
        """Widening the card re-lays-out the HTML, exactly as it does on
        the canvas — so the report follows the card, not the page."""
        graph, cache, node = web_graph
        node.params["width"] = 700
        node.params["height"] = 300
        rendered = render_report("![[Dashboard]]", graph, cache)
        if not rendered.images:
            pytest.skip("Qt WebEngine could not render here")
        image = rendered.images[0]
        assert image.width() / image.height() == pytest.approx(700 / 300,
                                                               rel=0.02)

    def test_a_ratio_option_reshapes_it(self, qtbot, web_graph):
        graph, cache, _node = web_graph
        rendered = render_report("![[Dashboard|ratio=16:9]]", graph, cache)
        if not rendered.images:
            pytest.skip("Qt WebEngine could not render here")
        image = rendered.images[0]
        assert image.width() / image.height() == pytest.approx(16 / 9,
                                                               rel=0.02)

    def test_an_undrawable_visual_says_so_on_the_page(self, monkeypatch,
                                                     web_graph):
        """No WebEngine: the report still opens, with the gap named. The
        old fallback — inlining the HTML as markdown — is the bug."""
        graph, cache, _node = web_graph
        monkeypatch.setattr(html_snapshot, "snapshot", lambda *a, **k: None)
        rendered = render_report("![[Dashboard]]", graph, cache)
        text = rendered.document.toPlainText()
        assert "could not be drawn" in text
        assert rendered.problems

    def test_a_plain_string_node_is_still_markdown(self, qtbot):
        """Only a *webview card* is photographed. A node that returns prose
        must keep dropping into the page as markdown."""
        registry = NodeRegistry()
        registry.load_builtins()
        graph, cache = Graph(), OutputCache()
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_label(node.id, "Note")
        cache.set(node.id, {"value": "## Heading\n\nSome prose."}, 0.0)

        rendered = render_report("![[Note]]", graph, cache)
        assert "Some prose." in rendered.document.toPlainText()
        assert rendered.images == []


class TestHtmlImage:
    def test_a_value_that_is_not_html_gives_nothing(self):
        assert html_image(None, {}, 510, False) is None

    def test_the_page_comes_from_the_shared_coercion(self, monkeypatch):
        """The card, Open in Browser and the report must build the same
        page — one function, so they cannot drift."""
        seen = {}

        def fake(html, width, height, scale=1.0):
            seen["html"] = html
            return b"png"

        monkeypatch.setattr(html_snapshot, "snapshot", fake)
        html_image("<b>hi</b>", {"width": 400, "height": 300}, 510, False)
        from flograph.core import html as core_html
        assert seen["html"] == core_html.to_html("<b>hi</b>")
