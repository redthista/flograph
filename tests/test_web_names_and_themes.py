"""A report web page's names — tab title, top-bar heading, icon — from Web
Layout or front matter, and the starter themes that dress it.

Front matter is the `---` block static-site generators put at the top of a
Markdown file: settings, not text, so it is taken off before anything is
drawn and never reaches paper. It wins over the page's Web Layout.
"""
import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import Graph
from flograph.core.graph import Page
from flograph.core.web_layout import WebSettings, split_front_matter
from flograph.ui.report import render as R
from flograph.ui.report.html import CSS_TEMPLATES, report_html


def render(body, live=True):
    return R.render_body(body, lambda ref, port: (None, None, None),
                         live=live)


class TestFrontMatter:
    TEXT = ("---\ntitle: \"Q3 Sales Review\"\nicon: 📊\nheading: Sales review\n"
            "side bar: open\npages: headings\nwidth: reading\ndepth: 2\n"
            "top-bar: yes\n---\n# Hello\n\nbody")

    def test_it_is_read_and_taken_off_the_text(self):
        meta, rest = split_front_matter(self.TEXT)
        assert meta["title"] == "Q3 Sales Review"      # quotes come off
        assert rest == "# Hello\n\nbody"

    def test_it_lays_over_the_page_settings(self):
        meta, _ = split_front_matter(self.TEXT)
        web = WebSettings(sidebar="closed", title="Old").with_front_matter(meta)
        assert web == WebSettings(sidebar="open", depth=2, topbar=True,
                                  paged="headings", width=820,
                                  title="Q3 Sales Review",
                                  heading="Sales review", icon="📊")

    @pytest.mark.parametrize("text", [
        "---\nJust a rule and a line\n---\n",        # not key: value
        "---\nauthor: me\n---\nx",                  # no key it knows
        "Intro\n---\ntitle: x\n---\n",              # not first
    ])
    def test_a_page_that_only_looks_like_it_keeps_its_text(self, text):
        assert split_front_matter(text) == ({}, text)

    def test_a_value_it_cannot_read_leaves_the_setting_alone(self):
        web = WebSettings(sidebar="open").with_front_matter(
            {"sidebar": "sideways", "depth": "lots", "width": "huge"})
        assert web == WebSettings(sidebar="open")

    def test_the_web_page_takes_its_names_and_icon(self, qapp):
        rendered = render("---\ntitle: Q3 Review\nicon: 📊\nheading: Sales\n"
                          "top bar: yes\n---\n# Hi\n\n## A\n\n## B")
        html = report_html(rendered, "Page title")
        assert "<title>Q3 Review</title>" in html
        assert '<link rel="icon" href="data:image/svg+xml,' in html
        assert '"topbar": true' in html and '"title": "Sales"' in html

    def test_paper_never_shows_it(self, qapp):
        rendered = render("---\ntitle: X\nsidebar: open\n---\n# Hi",
                          live=False)
        assert rendered.document.toPlainText().strip() == "Hi"

    def test_a_name_alone_leaves_the_page_as_it_was(self, qapp):
        rendered = render("# Plain")
        html = report_html(rendered, "t", web=WebSettings(title="Tab"))
        assert "<title>Tab</title>" in html
        assert "fg-layout-config" not in html

    def test_a_picture_icon_is_used_as_it_is(self):
        from flograph.ui.report.web_layout import icon_link
        assert icon_link("data:image/png;base64,AAAA") == \
            '<link rel="icon" href="data:image/png;base64,AAAA">'
        assert icon_link("") == ""

    def test_the_names_are_saved_with_the_page(self):
        web = WebSettings(title="Tab", heading="Bar", icon="📊")
        assert WebSettings.from_dict(web.to_dict()) == web


class TestNamesDialog:
    def test_it_sets_all_three_in_one_undo_step(self, qtbot, monkeypatch):
        from PySide6.QtWidgets import QDialog, QLineEdit
        from flograph.engine import ExecutionEngine
        from flograph.ui.report import ReportPage
        graph = Graph()
        graph.add_page(Page(id="p1", title="Q3", kind="report"))
        stack = QUndoStack()
        widget = ReportPage(graph, ExecutionEngine(graph), stack, "p1")
        qtbot.addWidget(widget)

        def fill(dialog):
            title, heading, icon = dialog.findChildren(QLineEdit)
            title.setText("Tab")
            heading.setText("Bar")
            icon.setText("📊")
            return QDialog.Accepted
        monkeypatch.setattr(QDialog, "exec", fill)
        widget.edit_web_names()
        assert graph.pages["p1"].web == WebSettings(title="Tab", heading="Bar",
                                                    icon="📊")
        stack.undo()
        assert graph.pages["p1"].web == WebSettings()
        widget.dispose()


class TestThemes:
    @pytest.mark.parametrize("name", ["Ledger", "Terminal", "Aurora"])
    def test_the_new_themes_are_offered_and_whole(self, name):
        css = CSS_TEMPLATES[name]
        assert css.count("{") == css.count("}")
        # each dresses the web layout and gives the charts a palette
        assert "details.fg-details" in css and ".fg-top" in css
        assert "--fg-chart-colors:" in css

    def test_a_backslash_in_the_css_is_written_as_it_is(self, qapp):
        # a replacement string read "\25B8" as a group reference and the
        # whole save failed
        css = '.a::before { content: "\\25B8"; }'
        html = report_html(render("# x"), "t", custom_css=css)
        assert css in html

    def test_live_charts_take_a_themes_palette(self):
        from flograph.ui.report.live import LIVE_JS
        assert "--fg-chart-colors" in LIVE_JS and "function recolor" in LIVE_JS
