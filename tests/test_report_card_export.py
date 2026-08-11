"""Idea A9: a report *card* can be exported and opened, like a report page.

A card is a report that never became a page — same markdown, same embeds,
same renderer — but it lives on the canvas, so it has no toolbar to carry
Export PDF or Open in Browser. Both now sit on its right-click menu.

Opening one in a browser needs the pictures inlined: a rendered report
holds its images as document resources under an "embed:N" URL, which means
nothing outside this process.
"""
import base64
import re

import pandas as pd
import pytest

from flograph.core import Graph
from flograph.core.page_setup import PageSetup
from flograph.ui.report.html import report_html
from flograph.ui.report.render import render_body, render_card


@pytest.fixture(autouse=True)
def _app(qapp):
    return qapp


@pytest.fixture
def figure():
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    fig = Figure(figsize=(4, 3))
    fig.add_subplot(111).plot([3, 1, 2])
    return fig


def rendered_with(value):
    return render_body("![[thing]]", lambda ref, port: (value, "", ""))


class TestSelfContainedHtml:

    def test_an_image_becomes_a_data_uri(self, figure):
        """The point of the whole module: written out as-is, every chart in
        the file would be a broken-image icon."""
        html = report_html(rendered_with(figure), "Report")
        assert 'src="data:image/png;base64,' in html
        assert "embed:" not in html

    def test_the_data_really_is_a_png(self, figure):
        html = report_html(rendered_with(figure), "Report")
        payload = re.search(r'src="data:image/png;base64,([^"]+)"',
                            html).group(1)
        assert base64.b64decode(payload)[:8] == b"\x89PNG\r\n\x1a\n"

    def test_several_images_are_not_confused(self, figure):
        """Index 1 is a prefix of index 10, so a careless replace would
        rewrite the wrong tag once a report passes ten pictures."""
        values = [figure] * 12
        rendered = render_body("![[charts]]",
                               lambda ref, port: (values, "", ""))
        html = report_html(rendered, "Report")
        assert len(rendered.images) == 12
        assert "embed:" not in html
        assert html.count('src="data:image/png;base64,') == 12

    def test_an_animation_keeps_moving(self):
        """A GIF is written out as the file it arrived as: the QImage beside
        it is only the poster frame, which is all paper can take, but a
        browser can do better and there is no reason to make it settle."""
        from flograph.core.images import to_data_uri
        from tests.test_report_animation import ANIMATED_GIF

        payload = {"path": None, "mime": "image/gif", "bytes": ANIMATED_GIF,
                   "data_uri": to_data_uri(ANIMATED_GIF, "image/gif"),
                   "source": ""}
        rendered = rendered_with(payload)
        assert rendered.animations, "the GIF was not recognised as animated"
        html = report_html(rendered, "Report")
        assert "data:image/gif;base64," in html
        assert "data:image/png" not in html   # the poster frame, not the GIF

    def test_a_report_with_no_pictures_is_left_alone(self):
        html = report_html(render_body("# Title\n\nJust words.\n",
                                       lambda ref, port: (None, "", "")),
                           "Report")
        assert "Just words." in html and "data:image" not in html

    def test_the_title_reaches_the_browser_tab(self):
        html = report_html(render_body("Text", lambda r, p: (None, "", "")),
                           "Quarterly Review")
        assert "<title>Quarterly Review</title>" in html
        assert html.count("<title>") == 1

    def test_a_title_with_markup_in_it_is_escaped(self):
        html = report_html(render_body("Text", lambda r, p: (None, "", "")),
                           "Q3 <script> & co")
        assert "&lt;script&gt;" in html and "<script>" not in html

    def test_no_title_is_not_an_error(self):
        assert report_html(render_body("Text", lambda r, p: (None, "", "")))


class TestRenderingACard:

    @pytest.fixture
    def env(self, registry):
        """A report card with a table wired into input "a"."""
        graph = Graph()
        from flograph.engine.cache import OutputCache
        cache = OutputCache()
        source = graph.add_node(
            registry.instantiate("flograph.util.constant"))
        card = graph.add_node(registry.instantiate("flograph.viz.report_card"))
        graph.connect(source.id, "value", card.id, "a")
        cache.set(source.id, {"value": pd.DataFrame({"n": [1, 2]})}, 0.0)
        return graph, cache, card

    def test_a_card_renders_at_whatever_width_it_is_given(self, env):
        graph, cache, card = env
        narrow = render_card("![[a]]", graph, cache, card.id, width=200)
        wide = render_card("![[a]]", graph, cache, card.id,
                           width=PageSetup().body_width_points())
        assert narrow.document is not None and wide.document is not None
        assert "n" in wide.document.toPlainText()

    def test_a_card_can_force_a_page_break_too(self, env):
        from PySide6.QtGui import QTextBlockFormat
        graph, cache, card = env
        document = render_card("One\n\n\\newpage\n\nTwo\n", graph, cache,
                               card.id).document
        last = document.lastBlock()
        assert last.text() == "Two"
        assert last.blockFormat().pageBreakPolicy() \
            == QTextBlockFormat.PageBreak_AlwaysBefore

    def test_exporting_a_card_writes_a_pdf(self, env, tmp_path):
        from flograph.ui.report.export import export_pdf
        graph, cache, card = env
        rendered = render_card("# Summary\n\n![[a]]\n", graph, cache, card.id,
                               width=PageSetup().body_width_points(),
                               image_scale=2.0)
        target = tmp_path / "card.pdf"
        export_pdf(rendered.document, str(target), title="Report")
        assert target.read_bytes()[:5] == b"%PDF-"


class TestOnTheMenu:

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

    def add_report_card(self, window, registry):
        node = window.graph.add_node(
            registry.instantiate("flograph.viz.report_card"))
        return node

    def test_a_card_renders_at_page_width_not_card_width(self, window,
                                                         registry, figure):
        """Card width is a canvas layout choice — how much room the node
        takes up next to its neighbours. It has nothing to do with the
        paper, and a narrow card must not export a narrow column down the
        middle of an A4 sheet."""
        source = window.graph.add_node(
            registry.instantiate("flograph.util.constant"))
        node = self.add_report_card(window, registry)
        window.graph.connect(source.id, "value", node.id, "a")
        window.engine.cache.set(source.id, {"value": figure}, 0.0)
        node.params["width"] = 240      # a deliberately narrow card
        node.params["text"] = "![[a]]"

        rendered = window._render_report_card(node.id, for_print=True)
        drawn = int(re.search(r'<img[^>]*width="(\d+)"',
                              rendered.document.toHtml()).group(1))
        assert drawn == PageSetup().body_width_points()

    def test_opening_a_card_in_a_browser_writes_a_file(self, window,
                                                       registry, monkeypatch):
        from PySide6.QtGui import QDesktopServices
        opened = []
        monkeypatch.setattr(QDesktopServices, "openUrl",
                            staticmethod(lambda url: opened.append(url)))
        node = self.add_report_card(window, registry)
        node.params["text"] = "# Card\n\nSome prose.\n"
        window._open_report_card_in_browser(node.id)
        assert opened, "nothing was handed to the desktop"
        path = opened[0].toLocalFile()
        assert path.endswith(".html")
        assert "Some prose." in open(path, encoding="utf-8").read()

    def test_a_missing_node_is_a_no_op(self, window):
        assert window._render_report_card("nope", for_print=False) is None
        window._open_report_card_in_browser("nope")
        window._export_report_card_pdf("nope")
