"""The web page's live charts and tables (ui/report/live.py).

A report written out as HTML used to be the PDF's document as Qt writes
it: every Plotly chart a photograph, every table a grid nobody could sort
or search. Rendered `live`, the resolver keeps the figure and the frame
beside each picture and table that asked for it (`|live`, `|search`), and
the HTML puts the live one back. Opt-in: an embed that asks for nothing is
exactly what the PDF has.

The paper half must not move at all, so the first tests are about what
does *not* change.
"""
import json
import re

import pandas as pd
import pytest

from flograph.core.report import parse_options
from flograph.core.table_format import parse_rules
from flograph.core.table_html import frame_to_html
from flograph.ui.report import render as R
from flograph.ui.report.html import report_html
from flograph.ui.report.live import _enclosing_table, make_live


def sales():
    return pd.DataFrame({
        "region": ["north"] * 3 + ["south"] * 3,
        "product": list("abcabc"),
        "revenue": [30, 50, 20, 10, 90, 40]})


def figure():
    go = pytest.importorskip("plotly.graph_objects")
    return go.Figure(go.Bar(x=["a", "b"], y=[1, 2]),
                     layout={"title": {"text": "Bars</b>"}})


def render(body, values, rules=None, monkeypatch=None, live=True):
    rules = rules or {}
    monkeypatch.setattr(R._Resolver, "_table_style",
                        lambda self, ref: (rules.get(ref, ()), (), ()))
    monkeypatch.setattr(R._Resolver, "_table_totals",
                        lambda self, ref: (None, None))
    return R.render_body(body, lambda ref, port: (values[ref], None, None),
                         live=live)


def _plain(rendered) -> str:
    return re.sub("[⁠​]", "", rendered.document.toPlainText())


class TestPaperIsUntouched:
    def test_not_live_keeps_nothing(self, qapp, monkeypatch):
        # asked for, but this render is for paper
        rendered = render("![[T|live]]", {"T": sales()},
                          monkeypatch=monkeypatch, live=False)
        assert rendered.live_charts == {} and rendered.live_tables == []
        assert "fg-table" not in report_html(rendered)

    def test_live_lays_out_the_same_document(self, qapp, monkeypatch):
        body = "# Head\n\n![[T|live]]\n\ntext"
        paper = render(body, {"T": sales()}, monkeypatch=monkeypatch,
                       live=False)
        live = render(body, {"T": sales()}, monkeypatch=monkeypatch)
        assert _plain(paper) == _plain(live)


class TestFlags:
    def test_live_and_search_are_known_flags(self):
        _, options, unknown = parse_options("live|search")
        assert options == {"live": True, "search": True}
        assert unknown == []


class TestLiveTables:
    def test_a_table_becomes_the_browser_table(self, qapp, monkeypatch):
        rendered = render("![[T|search|rows=4]]", {"T": sales()},
                          monkeypatch=monkeypatch)
        html = report_html(rendered)
        assert html.count('class="fg-table"') == 1
        assert 'data-fg-search="1"' in html and "--fg-rows:4" in html
        # the browser table keeps what Qt would have dropped
        assert "<th" in html and "<tbody>" in html
        assert "<script>" in html

    def test_a_live_table_carries_every_row(self, qapp, monkeypatch):
        big = pd.DataFrame({"n": range(120)})
        html = report_html(render("![[T|live]]", {"T": big},
                                  monkeypatch=monkeypatch))
        # paper would cut at 30 with a note; the page scrolls instead
        assert ">119<" in html
        assert "Showing" not in html

    def test_a_plain_embed_keeps_the_paper_table(self, qapp, monkeypatch):
        html = report_html(render("![[T]]", {"T": sales()},
                                  monkeypatch=monkeypatch))
        assert 'class="fg-table"' not in html
        assert "<script>" not in html

    def test_groups_are_tagged_and_folded_ones_kept(self):
        rules = parse_rules("total sum\ngroup region closed\n"
                            "subtotal below")
        html = frame_to_html(sales(), rules, live=True)
        assert html.count('data-fg-kind="group"') == 2
        assert html.count('data-fg-folded="1"') == 2
        # folded on the card, but the page needs the rows to unfold them
        assert ">90<" in html
        assert 'data-fg-kind="total"' in html
        assert 'data-fg-kind="subtotal" data-fg-level="0"' in html

    def test_a_styled_cell_is_not_boxed_in_the_browser(self):
        """Paper restates the grid line on a styled cell because Qt drops
        it; the browser has no grid, so the line would box only the cells a
        rule touched."""
        rules = parse_rules("revenue < 25 => fg red, icon ▼ red right")
        live = frame_to_html(sales(), rules, live=True)
        paper = frame_to_html(sales(), rules)
        assert "color:" in live and "1px solid #999" not in live
        assert "1px solid #999" in paper

    def test_paper_table_is_unchanged_by_the_live_option(self):
        rules = parse_rules("total sum\ngroup region")
        assert "data-fg" not in frame_to_html(sales(), rules)

    def test_a_table_in_columns_replaces_only_itself(self, qapp,
                                                     monkeypatch):
        body = "```columns\n![[T|live]]\n---\nbeside\n```\n"
        html = report_html(render(body, {"T": sales()},
                                  monkeypatch=monkeypatch))
        assert html.count('class="fg-table"') == 1
        assert "beside" in html     # the column layout survived


class TestEnclosingTable:
    def test_innermost_table_around_the_marker(self):
        marker = R.table_marker(0)
        inner = f"<table><tr><td>{marker}x</td></tr></table>"
        html = f"<table><tr><td>{inner}</td><td>y</td></tr></table>"
        start, end = _enclosing_table(html, marker)
        assert html[start:end] == inner

    def test_a_bar_inside_the_table_does_not_end_it(self):
        marker = R.table_marker(0)
        html = (f"<table><tr><th>{marker}h</th></tr><tr><td>"
                "<table><tr><td>bar</td></tr></table></td></tr></table>")
        assert _enclosing_table(html, marker) == (0, len(html))

    def test_no_marker(self):
        assert _enclosing_table("<table></table>", R.table_marker(3)) is None


class TestLiveCharts:
    def test_a_plotly_chart_is_kept_beside_its_picture(self, qapp,
                                                       monkeypatch):
        rendered = render("![[C|live]]", {"C": figure()},
                          monkeypatch=monkeypatch)
        assert list(rendered.live_charts) == [0]
        html = report_html(rendered, plotly_src="plotly.js")
        assert 'class="fg-chart"' in html
        # the picture is still there, inlined, as the fallback
        box = re.search(r'<div class="fg-chart".*?</div>', html, re.S).group(0)
        assert 'src="data:image/png' in box
        assert '<script src="plotly.js"></script>' in html
        # a "</b>" in a title must not end the script element
        data = re.search(r'id="fg-fig-0">(.*?)</script>', html, re.S).group(1)
        assert json.loads(data)["layout"]["title"]["text"] == "Bars</b>"

    def test_a_plain_chart_stays_a_picture(self, qapp, monkeypatch):
        rendered = render("![[C]]", {"C": figure()},
                          monkeypatch=monkeypatch)
        assert rendered.live_charts == {}
        # and nothing live on the page means no Plotly in the file
        html = report_html(rendered)
        assert "fg-chart" not in html and len(html) < 1_000_000

    def test_plotly_is_inlined_once_for_a_file_you_keep(self, qapp,
                                                        monkeypatch):
        html = report_html(render("![[C|live]]\n\n![[C|live]]",
                                  {"C": figure()},
                                  monkeypatch=monkeypatch))
        assert html.count('class="fg-chart"') == 2
        # one copy of plotly.js, not one per chart
        assert html.count("Plotly.newPlot") <= 2
        assert len(html) < 2 * 4_000_000 + 500_000


class TestLiveThemes:
    def test_the_live_themes_are_offered(self):
        from flograph.ui.report.html import CSS_TEMPLATES
        for name in ("Compact", "Dashboard", "Midnight"):
            assert name in CSS_TEMPLATES
        # the old three are still there, in their old order, first
        assert list(CSS_TEMPLATES)[:3] == ["Clean", "Editorial", "Slate"]

    @pytest.mark.parametrize("name", ["Compact", "Dashboard", "Midnight"])
    def test_a_live_theme_themes_the_charts_too(self, name):
        from flograph.ui.report.css_themes import LIVE_THEMES
        css = LIVE_THEMES[name]
        for var in ("--fg-chart-paper", "--fg-chart-ink", "--fg-chart-grid",
                    "--fg-chart-font", "--chart-shape"):
            assert var + ":" in css
        # a data bar is a table inside a cell: only the outer cells are styled
        assert ".flograph-table > tbody > tr > td" in css
        assert css.count("{") == css.count("}")

    def test_the_page_script_reads_the_chart_variables(self):
        from flograph.ui.report.live import LIVE_JS
        for var in ("--fg-chart-paper", "--fg-chart-plot", "--fg-chart-ink",
                    "--fg-chart-grid", "--fg-chart-font"):
            assert var in LIVE_JS


def test_make_live_leaves_a_plain_report_alone():
    class Nothing:
        live_charts = {}
        live_tables = []
    assert make_live("<html><body>x</body></html>", Nothing()) \
        == "<html><body>x</body></html>"
