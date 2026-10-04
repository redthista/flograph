"""Action Buttons in a report page, and `apponly::` lines.

A button embedded with `![[Label]]` is drawn only in the report page's own
preview — the one render a click can come back from — and is left out of
everything that leaves the app. An `apponly::` line is the words that go
with it: shown in the preview, gone from the PDF and the HTML.
"""
import pandas as pd
import pytest

from flograph.core import Graph, NodeRegistry
from flograph.core.report import (app_only_lines, button_href,
                                  button_target)
from flograph.engine.cache import OutputCache
from flograph.ui.report.html import report_html, web_buttons
from flograph.ui.report.render import render_report


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def env(registry):
    graph = Graph()
    cache = OutputCache()
    total = graph.add_node(registry.instantiate("flograph.util.constant"))
    graph.set_label(total.id, "Total")
    cache.set(total.id, {"value": 3500}, 0.0)
    button = graph.add_node(
        registry.instantiate("flograph.util.action_button"))
    graph.set_label(button.id, "Refresh Data")
    return graph, cache, button


class TestAppOnlyLines:
    BODY = "# Sales\n\napponly:: Click the button for today's figures.\n\nDone.\n"

    def test_the_app_keeps_the_words_and_drops_the_tag(self):
        out = app_only_lines(self.BODY, in_app=True)
        assert "Click the button for today's figures." in out
        assert "apponly" not in out

    def test_an_export_drops_the_whole_line(self):
        out = app_only_lines(self.BODY, in_app=False)
        assert "Click the button" not in out
        assert out == "# Sales\n\n\nDone.\n"

    def test_the_tag_is_case_blind_and_may_be_indented(self):
        body = "  AppOnly::  hidden\nkept"
        assert app_only_lines(body, in_app=False) == "kept"
        assert app_only_lines(body, in_app=True) == "   hidden\nkept"

    def test_a_tag_inside_a_code_block_is_an_example(self):
        body = "```\napponly:: an example\n```\n"
        assert app_only_lines(body, in_app=False) == body
        assert app_only_lines(body, in_app=True) == body

    def test_a_tag_mid_line_is_just_text(self):
        body = "write apponly:: at the start of a line"
        assert app_only_lines(body, in_app=False) == body

    def test_the_last_line_goes_without_a_newline(self):
        assert app_only_lines("kept\napponly:: gone", in_app=False) == "kept\n"


class TestTheLink:
    def test_round_trip(self):
        assert button_target(button_href("abc123")) == "abc123"

    def test_anything_else_is_not_a_button(self):
        assert button_target("page:Costs") == ""
        assert button_target("https://example.com") == ""
        assert button_target("") == ""


def _anchors(document):
    hrefs = []
    block = document.begin()
    while block.isValid():
        pieces = block.begin()
        while not pieces.atEnd():
            fmt = pieces.fragment().charFormat()
            if fmt.isAnchor():
                hrefs.append(fmt.anchorHref())
            pieces += 1
        block = block.next()
    return hrefs


class TestRendering:
    BODY = "apponly:: Press it to refresh.\n\n![[Refresh Data]]\n\nTotal: ![[Total]]\n"

    def test_the_preview_draws_a_clickable_button(self, env):
        graph, cache, button = env
        rendered = render_report(self.BODY, graph, cache, page_links=True,
                                 in_app=True)
        text = rendered.document.toPlainText()
        assert "Refresh Data" in text
        assert "Press it to refresh." in text
        assert button_href(button.id) in _anchors(rendered.document)
        assert not rendered.problems

    def test_an_export_has_no_button_and_no_app_only_line(self, env):
        graph, cache, _button = env
        rendered = render_report(self.BODY, graph, cache)
        text = rendered.document.toPlainText()
        assert "Refresh Data" not in text
        assert "Press it to refresh" not in text
        assert "3,500" in text or "3500" in text
        assert not _anchors(rendered.document)
        # no "hasn't run" complaint: a button has no output, and that is
        # not a problem to report on an export
        assert not rendered.problems

    def test_saved_html_carries_no_button(self, env):
        graph, cache, _button = env
        html = report_html(render_report(self.BODY, graph, cache, live=True))
        assert "flograph-button:" not in html
        assert "fg-button" not in html

    def test_the_web_preview_gets_a_real_button(self, env):
        graph, cache, button = env
        rendered = render_report(self.BODY, graph, cache, page_links=True,
                                 live=True, in_app=True)
        html = report_html(rendered)
        assert f'<a class="fg-button" href="{button_href(button.id)}">' \
               '▶ Refresh Data</a>' in html
        assert "a.fg-button" in html          # its style came with it

    def test_a_label_is_escaped(self, env, registry):
        graph, cache, button = env
        graph.set_label(button.id, "Go <now>")
        rendered = render_report("![[Go <now>]]", graph, cache,
                                 page_links=True, in_app=True)
        assert "Go <now>" in rendered.document.toPlainText()


def test_web_buttons_leaves_a_page_without_one_alone():
    html = "<html><head></head><body><a href='x'>x</a></body></html>"
    assert web_buttons(html) == html


class TestTheWebPreviewHandsLinksOver:
    def test_app_links(self):
        from flograph.ui.report.web_preview import is_app_link
        assert is_app_link("page:Costs")
        assert is_app_link(button_href("n1"))
        assert not is_app_link("https://example.com")
        assert not is_app_link("#section")


class TestTheWindow:
    @pytest.fixture
    def window(self, qtbot, registry):
        from flograph.ui.mainwindow import MainWindow
        win = MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        return win

    def _chain(self, win):
        """source -> table, with a button naming the source."""
        source = win.registry.instantiate("flograph.util.constant")
        table = win.registry.instantiate("flograph.viz.show_table")
        button = win.registry.instantiate("flograph.util.action_button")
        for node in (source, table, button):
            win.graph.add_node(node)
        win.graph.set_label(source.id, "Source")
        win.graph.connect(source.id, "value", table.id,
                          table.spec.inputs[0].name)
        win.graph.set_param(button.id, "targets", "Source")
        return source, table, button

    def _runs(self, win, monkeypatch):
        calls = []
        monkeypatch.setattr(win.engine, "run_targets",
                            lambda targets, asked=None:
                            calls.append((list(targets), asked)))
        return calls

    def test_run_nodes_stops_at_the_named_nodes(self, window, monkeypatch):
        source, table, button = self._chain(window)
        calls = self._runs(window, monkeypatch)
        window._on_button_fired(button.id)
        assert calls == [([source.id], None)]

    def test_update_what_follows_brings_the_rest(self, window, monkeypatch):
        source, table, button = self._chain(window)
        window.graph.set_param(button.id, "downstream", True)
        calls = self._runs(window, monkeypatch)
        window._on_button_fired(button.id)
        assert calls == [([source.id, table.id], [source.id])]

    def test_a_click_in_the_report_fires_the_button(self, window,
                                                    monkeypatch):
        from flograph.core import Page
        source, table, button = self._chain(window)
        page = Page(id="r1", title="Report", kind="report",
                    body="![[%s]]" % button.label)
        window.graph.add_page(page)
        widget = window._dashboard_pages["r1"]
        calls = self._runs(window, monkeypatch)
        widget._follow_link(button_href(button.id))
        assert calls == [([source.id], None)]


def test_a_saved_report_does_not_wait_on_a_button_or_an_app_only_line(env):
    """Save Report is ordered after what its page embeds (core.reportlinks).
    A button never runs into the file and an app-only line never reaches it,
    so neither is a dependency — a button that had never run would otherwise
    have the saver refuse with "out of date"."""
    from flograph.core.reportlinks import embedded_nodes
    graph, _cache, button = env
    total = next(n for n in graph.nodes.values() if n.label == "Total")
    assert embedded_nodes(graph, "![[Refresh Data]]\n![[Total]]") == [total.id]
    assert embedded_nodes(graph, "apponly:: ![[Total]]") == []


class TestTheWebPreviewRoutesAppLinks:
    """Chromium never asks the page about a scheme it does not know, so the
    preview dresses each app link as an https address it does ask about."""

    def test_round_trip(self):
        from flograph.ui.report.web_preview import app_link_of, routed
        html = ('<a href="flograph-button:n1">Go</a> '
                '<a href="page:Sales%20North">North</a> '
                '<a href="https://example.com">web</a>')
        out = routed(html)
        hrefs = [h.split('"')[0] for h in out.split('href="')[1:]]
        assert [app_link_of(h) for h in hrefs] == [
            "flograph-button:n1", "page:Sales%20North", ""]
        assert 'href="https://example.com"' in out

    def test_an_ordinary_address_is_not_an_app_link(self):
        from flograph.ui.report.web_preview import APP_LINK, app_link_of
        assert app_link_of("https://example.com/") == ""
        # only the two kinds of app link, whatever the address carries
        assert app_link_of(APP_LINK + "file%3A%2F%2F%2Fetc%2Fpasswd") == ""
