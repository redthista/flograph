"""A report page's editors in colour (ui/report/syntax.py), a table's
`width=` on the web page, and the themes' look for plain tables."""
import re

import pandas as pd
import pytest
from PySide6.QtGui import QTextDocument

from flograph.ui.report import render as R
from flograph.ui.report.html import CSS_TEMPLATES, report_html
from flograph.ui.report.syntax import DARK, LIGHT, CssHighlighter, MarkdownHighlighter


def colours(document, line: int) -> dict:
    """{text: colour} of each coloured run on a line."""
    block = document.findBlockByNumber(line)
    return {block.text()[r.start:r.start + r.length]:
            r.format.foreground().color().name()
            for r in block.layout().formats()}


class TestMarkdownColour:
    def document(self, qapp, text, dark=False):
        document = QTextDocument()
        document.setPlainText(text)
        self._keep = MarkdownHighlighter(document, dark=dark, extra=lambda: ())
        self._keep.rehighlight()
        return document

    def test_an_embed_and_its_options(self, qapp):
        doc = self.document(qapp, "See ![[Sales|live|rows=12]] here")
        runs = colours(doc, 0)
        assert runs.get("Sales") == LIGHT["embed"]
        assert runs.get("|live|rows=12") == LIGHT["option"]

    def test_headings_blocks_and_tabs(self, qapp):
        doc = self.document(qapp, "# Title\n::: tabs Region\n== North\n:::")
        assert colours(doc, 0).get(" Title") == LIGHT["heading"]
        assert LIGHT["block"] in colours(doc, 1).values()
        assert LIGHT["block"] in colours(doc, 2).values()

    def test_code_is_code_but_columns_are_markdown(self, qapp):
        doc = self.document(qapp, "```python\n# not a heading\n```\n"
                                  "```columns\n# a heading\n---\nx\n```")
        assert colours(doc, 1) == {"# not a heading": LIGHT["code"]}
        assert colours(doc, 4).get(" a heading") == LIGHT["heading"]

    def test_front_matter_keys(self, qapp):
        doc = self.document(qapp, "---\ntitle: Q3\n---\n# Hi")
        assert colours(doc, 1).get("title") == LIGHT["key"]

    def test_the_dark_palette(self, qapp):
        doc = self.document(qapp, "# Title", dark=True)
        assert colours(doc, 0).get(" Title") == DARK["heading"]


class TestCssColour:
    def test_properties_numbers_and_swatches(self, qapp):
        document = QTextDocument()
        document.setPlainText("a.b:hover {\n  color: #ff0000;\n  width: 10px;\n}")
        highlighter = CssHighlighter(document)
        highlighter.rehighlight()
        assert colours(document, 1).get("color") == LIGHT["property"]
        assert colours(document, 2).get("10px") == LIGHT["number"]
        swatch = document.findBlockByNumber(1).layout().formats()
        assert any(r.format.background().color().name() == "#ff0000"
                   for r in swatch)
        assert colours(document, 0).get(":hover") == LIGHT["pseudo"]

    def test_a_comment_over_lines(self, qapp):
        document = QTextDocument()
        document.setPlainText("/* one\n two */\nb { color: red; }")
        highlighter = CssHighlighter(document)
        highlighter.rehighlight()
        assert colours(document, 1) == {" two */": LIGHT["comment"]}
        assert colours(document, 2).get("color") == LIGHT["property"]


def render(body, frame, live=True):
    return R.render_body(body, lambda ref, port: (frame, None, None),
                         live=live)


@pytest.fixture
def plain(monkeypatch):
    monkeypatch.setattr(R._Resolver, "_table_style",
                        lambda self, ref: ((), (), ()))
    monkeypatch.setattr(R._Resolver, "_table_totals",
                        lambda self, ref: (None, None))
    return pd.DataFrame({"a": [1, 2], "b": [3, 4]})


def first_table(html):
    return re.search(r"<table\b[^>]*>", html[html.find("<body"):]).group(0)


class TestTableWidth:
    def test_a_share_of_the_page(self, qapp, plain):
        html = report_html(render("![[T|width=90%]]", plain), "t")
        assert 'width="90%"' in first_table(html)

    def test_auto_is_as_wide_as_its_columns(self, qapp, plain):
        html = report_html(render("![[T|width=auto]]", plain), "t")
        assert "width=" not in first_table(html)
        paper = render("![[T|width=auto]]", plain, live=False)
        assert not paper.problems
        assert not re.search(r'<table[^>]*width="',
                             paper.document.toHtml())

    def test_none_is_as_wide_as_its_columns_on_the_web(self, qapp, plain):
        # Qt's width is the paper column's, 510 points — read as 510 pixels
        # it capped the table on a wide window
        html = report_html(render("![[T]]", plain), "t")
        assert "width=" not in first_table(html)

    def test_none_keeps_the_column_width_on_paper(self, qapp, plain):
        paper = render("![[T]]", plain, live=False)
        assert re.search(r'<table[^>]*width="\d+"', paper.document.toHtml())

    def test_points_stay_points(self, qapp, plain):
        html = report_html(render("![[T|width=280]]", plain), "t")
        assert re.search(r'width="\d+"', first_table(html))

    def test_no_reading_width_inside_a_cell(self):
        from flograph.ui.report.css_themes import COMPACT_CELLS
        assert "max-width: none" in COMPACT_CELLS

    def test_a_live_table_fills_its_share(self, qapp, plain):
        html = report_html(render("![[T|live|width=75%]]", plain), "t")
        assert re.search(r'class="fg-table"[^>]*data-fg-share[^>]*'
                         r'style="width:75%;', html)


class TestPlainTablesInTheThemes:
    @pytest.mark.parametrize("name", ["Compact", "Dashboard", "Midnight",
                                      "Ledger", "Terminal", "Aurora"])
    def test_each_live_theme_dresses_them(self, name):
        css = CSS_TEMPLATES[name]
        assert 'table[cellspacing="2"]' in css
        assert 'td[bgcolor="#cdced1"]' in css          # totals and groups
        assert 'table[bgcolor="#eceef1"]' in css       # a bar's track
        # a table's figures are not code
        assert "span[style*=\"font-family:'monospace'\"]:not(td *)" in css


class TestCompactCells:
    """A cell's value is a paragraph (Qt writes it so): a theme's paragraph
    spacing reached every row, and Aurora's plain rows came out 36px tall
    against 21px with no theme. Every starter theme now keeps it out."""

    @pytest.mark.parametrize("name", sorted(CSS_TEMPLATES))
    def test_every_theme_keeps_paragraph_spacing_out_of_cells(self, name):
        from flograph.ui.report.css_themes import COMPACT_CELLS
        css = CSS_TEMPLATES[name]
        # last, after the theme's own `p { margin }`, so it wins
        assert css.rstrip().endswith(COMPACT_CELLS.rstrip())

    @pytest.mark.parametrize("name", sorted(CSS_TEMPLATES))
    def test_no_theme_pads_every_cell(self, name):
        # a bare `td` rule also pads the little table inside a data bar
        assert not re.search(r"(?m)^td, th \{", CSS_TEMPLATES[name])

    def test_a_live_table_box_keeps_its_padding_inside_its_width(self):
        from flograph.ui.report.live import LIVE_CSS
        box = re.search(r"\.fg-table \{[^}]*\}", LIVE_CSS).group(0)
        assert "box-sizing: border-box" in box
