"""Qt's HTML said in fewer bytes (ui/report/compact.py).

A report's web page is Qt's toHtml, and Qt spells out every declaration on
every element: a table cell came to ~480 bytes of style for a word of text.
The pass that shortens it may only drop what a browser ignores and fold
what it reads the same either way — and must leave the text the themes'
`[style*=…]` selectors look for. (Checked against Chromium's computed
styles for every element, under every theme, when it was written; these
pin the rules that made that true.)
"""
import re

import pandas as pd
import pytest

from flograph.ui.report.compact import compact_qt_html

QT_CELL = (
    '<td style=" padding-left:7; padding-right:7; padding-top:3; '
    'padding-bottom:3; border-top:1px; border-right:1px; border-bottom:1px; '
    'border-left:1px; border-top-color:#999999; border-right-color:#999999; '
    'border-bottom-color:#999999; border-left-color:#999999; '
    'border-top-style:solid; border-right-style:solid; '
    'border-bottom-style:solid; border-left-style:solid;">'
    '<p style=" margin-top:0px; margin-bottom:0px; margin-left:0px; '
    'margin-right:0px; -qt-block-indent:0; text-indent:0px;">'
    "<span style=\" font-family:'sans-serif'; font-size:11pt;\">west</span>"
    "</p></td>")


def styles(html):
    return re.findall(r'style="([^"]*)"', html)


class TestACell:
    def test_a_qt_cell_shrinks_to_what_a_browser_reads(self):
        out = compact_qt_html(QT_CELL)
        assert styles(out) == [" border:1px solid #999999;", " margin:0px;",
                               " font-family:'sans-serif'; font-size:11pt;"]
        assert len(out) < len(QT_CELL) / 2.5
        assert "west" in out

    def test_a_padding_without_a_unit_goes_but_zero_stays(self):
        # standards mode throws `7` away; `0` is valid and beats a td's 1px
        out = compact_qt_html('<td style=" padding-left:0; padding-right:6; '
                              'padding-top:0; padding-bottom:0;">x</td>')
        assert styles(out) == [" padding-left:0; padding-top:0; "
                               "padding-bottom:0;"]

    def test_four_equal_paddings_fold(self):
        out = compact_qt_html('<td style=" padding-left:0; padding-right:0; '
                              'padding-top:0; padding-bottom:0;">x</td>')
        assert styles(out) == [" padding:0;"]

    def test_four_equal_border_colours_fold(self):
        out = compact_qt_html(
            '<td style=" border-top-color:#000000; border-right-color:#000000;'
            ' border-bottom-color:#000000; border-left-color:#000000;">x</td>')
        assert styles(out) == [" border-color:#000000;"]

    def test_a_style_left_empty_is_dropped(self):
        out = compact_qt_html('<p style=" -qt-block-indent:0;">x</p>')
        assert out == "<p>x</p>"


class TestWhatAThemeReads:
    def test_a_quote_keeps_its_margins_as_written(self):
        quote = ('<p style=" margin-top:12px; margin-bottom:12px; '
                 'margin-left:40px; margin-right:40px; -qt-block-indent:0;">')
        out = compact_qt_html(quote)
        assert "margin-left:40px; margin-right:40px" in out

    def test_a_span_s_own_colour_keeps_its_leading_space(self):
        out = compact_qt_html('<span style=" font-weight:700; '
                              'color:#ff0000;">x</span>')
        assert '[style*=" color:"]' and " color:#ff0000;" in out

    def test_a_columns_block_keeps_border_style_none(self):
        table = ('<table style=" border-style:none; margin-top:0px; '
                 'margin-bottom:0px; margin-left:0px; margin-right:0px;">')
        out = compact_qt_html(table)
        assert "border-style:none" in out and "margin:0px" in out


class TestWhenNotToFold:
    def test_unequal_sides_stay(self):
        style = (' margin-top:12px; margin-bottom:0px; margin-left:0px; '
                 'margin-right:0px;')
        assert styles(compact_qt_html(f'<p style="{style}">')) == [style]

    def test_a_shorthand_among_the_sides_blocks_the_fold(self):
        # border-right:1px resets the right colour: moving the colours
        # together past it would change what wins
        style = (' border-top-color:red; border-right:1px; '
                 'border-right-color:red; border-bottom-color:red; '
                 'border-left-color:red;')
        assert styles(compact_qt_html(f'<td style="{style}">')) == [style]

    def test_a_colour_before_its_width_blocks_the_border_fold(self):
        style = (' border-top-color:red; border-top:1px; border-right:1px; '
                 'border-bottom:1px; border-left:1px; border-right-color:red;'
                 ' border-bottom-color:red; border-left-color:red; '
                 'border-top-style:solid; border-right-style:solid; '
                 'border-bottom-style:solid; border-left-style:solid;')
        out = styles(compact_qt_html(f'<td style="{style}">'))[0]
        assert "border:" not in out

    def test_text_indent_stays_when_the_document_indents(self):
        html = ('<p style=" text-indent:20px;">a</p>'
                '<p style=" text-indent:0px;">b</p>')
        assert "text-indent:0px" in compact_qt_html(html)

    def test_text_indent_zero_goes_when_nothing_indents(self):
        assert "text-indent" not in compact_qt_html(
            '<p style=" text-indent:0px;">b</p>')

    def test_a_data_uri_is_not_cut_at_its_semicolon(self):
        style = (' background-image:url(data:image/png;base64,AAAA); '
                 '-qt-x:1;')
        out = compact_qt_html(f'<td style="{style}">')
        assert styles(out) == [" background-image:url("
                               "data:image/png;base64,AAAA);"]

    def test_text_that_looks_like_a_style_is_not_touched(self):
        # Qt writes `"` in text as &quot; — but a style= in an attribute
        # other than a tag's own is not a style either
        html = '<p title="x style=&quot;a&quot;">style="-qt-x:1;"</p>'
        assert compact_qt_html(html) == html


class TestTheWebPage:
    @pytest.fixture(autouse=True)
    def _app(self, qapp):
        pass

    def render(self, monkeypatch, body, frame):
        from flograph.ui.report import render as R
        monkeypatch.setattr(R._Resolver, "_table_style",
                            lambda self, ref: ((), (), ()))
        monkeypatch.setattr(R._Resolver, "_table_totals",
                            lambda self, ref: (None, None))
        return R.render_body(body, lambda ref, port: (frame, None, None),
                             live=True)

    def test_a_report_page_is_much_smaller(self, monkeypatch):
        import flograph.ui.report.compact as C
        from flograph.ui.report.html import report_html
        frame = pd.DataFrame({"a": range(30), "b": list("xyz") * 10})
        rendered = self.render(monkeypatch, "# T\n\n![[T]]\n", frame)
        small = report_html(rendered, "R")
        monkeypatch.setattr(C, "compact_qt_html", lambda html: html)
        big = report_html(rendered, "R")
        assert len(small) < len(big) / 2.5
        assert "-qt-" not in small and "padding-left:7" not in small

    def test_what_the_themes_select_on_survives(self, monkeypatch):
        from flograph.ui.report.html import report_html
        body = ("> a quote\n\n`code`\n\n```columns\nleft\n---\nright\n"
                "```\n\n![[T]]\n")
        html = report_html(self.render(monkeypatch, body,
                                       pd.DataFrame({"a": [1]})), "R")
        for text in ("margin-left:40px; margin-right:40px",
                     "font-family:'monospace'", "font-family:'sans-serif'",
                     "border-style:none"):
            assert text in html, text
