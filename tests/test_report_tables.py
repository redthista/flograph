"""A table on a report page: the card's controls, and the card's formatting.

Two things used to stop at the canvas. A frame reached the page as a
markdown table, so `![[Sales|width=50%]]` did nothing (markdown has no
width), and every conditional-formatting rule the Show Table card was
displaying — the heatmap, the bars, the highlighted rows, the number
formats, the hidden helper columns — was simply absent.
"""
import pytest

pd = pytest.importorskip("pandas")

from flograph.core import Graph, NodeRegistry  # noqa: E402
from flograph.core.table_format import (PAPER_TINT, for_paper,  # noqa: E402
                                        parse_rules, paper_tint,
                                        style_payload)
from flograph.core.table_html import frame_to_html  # noqa: E402
from flograph.engine.cache import OutputCache  # noqa: E402
from flograph.ui.report.render import TABLE_ROWS, render_report  # noqa: E402

FRAME = pd.DataFrame({
    "region": ["North", "South", "East"],
    "revenue": [1240000, 610000, 880000],
    "orders": [412, 233, 300],
    "status": ["ok", "fail", "ok"],
    "_tmp": [1, 2, 3],
})


def table_node(rules: str = "", frame=FRAME):
    """A Show Table node that has run, with its style on the style port."""
    registry = NodeRegistry()
    registry.load_builtins()
    graph, cache = Graph(), OutputCache()
    node = graph.add_node(registry.instantiate("flograph.viz.show_table"))
    graph.set_label(node.id, "Sales")
    style = style_payload({"format_rules": rules, "hide": ""})
    cache.set(node.id, {"table": frame, "style": style}, 0.0)
    return graph, cache, node


def html_of(body: str, graph, cache) -> str:
    return render_report(body, graph, cache).document.toHtml()


class TestTheCardsFormatting:
    def test_a_heatmap_colours_the_cells(self):
        graph, cache, _n = table_node("revenue scale green")
        html = html_of("![[Sales]]", graph, cache)
        assert "background-color:#" in html.replace(" ", "")

    def test_a_row_highlight_colours_the_whole_row(self):
        graph, cache, _n = table_node("status = fail => row red")
        html = html_of("![[Sales]]", graph, cache).replace(" ", "")
        # the red fill, tinted for paper, on more than one cell of the row
        tint = paper_tint("#5c2b2b").lstrip("#")
        assert html.lower().count(tint) >= 2

    def test_a_number_format_reaches_the_page(self):
        graph, cache, _n = table_node("revenue format $,.0f")
        assert "$1,240,000" in html_of("![[Sales]]", graph, cache)

    def test_a_hidden_column_is_not_on_the_page(self):
        graph, cache, _n = table_node("hide _tmp*")
        assert "_tmp" not in html_of("![[Sales]]", graph, cache)

    def test_a_keep_list_reaches_the_page_in_its_own_order(self):
        """A page that printed the card's columns in the frame's order
        rather than the card's would be the same failure as printing the
        wrong ones — just harder to spot."""
        import re
        graph, cache, _n = table_node("show status, region")
        html = html_of("![[Sales]]", graph, cache)
        # Qt's own toHtml() rewrites the header cells, so read the words out
        # of the <thead> block rather than matching the tags that went in
        head = re.search(r"<thead>(.*?)</thead>", html, re.S).group(1)
        words = [w for w in re.sub(r"<[^>]+>", " ", head).split()
                 if w in set(FRAME.columns)]
        assert words == ["status", "region"]

    def test_a_data_bar_is_drawn(self):
        graph, cache, _n = table_node("orders bar blue")
        html = html_of("![[Sales]]", graph, cache)
        # the bar is a nested table, so the page holds more than one
        assert html.lower().count("<table") >= 2

    def test_an_icon_reaches_the_page(self):
        graph, cache, _n = table_node("orders icons traffic")
        text = render_report("![[Sales]]", graph, cache).document.toPlainText()
        assert any(glyph in text for glyph in "●▲▼")

    def test_an_unstyled_table_still_renders(self):
        graph, cache, _n = table_node("")
        html = html_of("![[Sales]]", graph, cache)
        assert "<table" in html and "North" in html

    def test_a_table_with_no_style_port_still_renders(self):
        """Not every frame comes from a Show Table — a plain node's output
        must land on the page as a table all the same."""
        registry = NodeRegistry()
        registry.load_builtins()
        graph, cache = Graph(), OutputCache()
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_label(node.id, "Plain")
        cache.set(node.id, {"value": FRAME}, 0.0)
        html = html_of("![[Plain]]", graph, cache)
        assert "<table" in html and "South" in html


class TestPaperPalette:
    """The card's fills are built for a dark grid. On white they have to be
    re-grounded, or "low" on a heatmap prints as a near-black block."""

    def test_a_fill_is_tinted_towards_white(self):
        [rule] = parse_rules("score > 1 => bg green")
        assert paper_tint(rule.bg) != rule.bg
        assert paper_tint(rule.bg).lower() > rule.bg.lower()   # lighter hex

    def test_the_text_colour_is_recomputed_for_the_new_ground(self):
        from flograph.core.table_format import CellStyle
        printed = for_paper(CellStyle(bg="#5c2b2b", fg="#e5e7eb"))
        assert printed.fg == "#1b1c20"      # dark ink on a light tint

    def test_a_colour_asked_for_by_name_is_kept_not_replaced(self):
        from flograph.core.table_format import CellStyle
        printed = for_paper(CellStyle(fg="#88ff88"))
        assert printed.fg != "#88ff88"      # darkened to be visible
        assert printed.fg.startswith("#")

    def test_nothing_is_none_safe(self):
        assert for_paper(None) is None

    def test_the_tint_is_the_documented_one(self):
        assert 0 < PAPER_TINT < 1


class TestTheControls:
    def test_width_reaches_the_table(self):
        graph, cache, _n = table_node("")
        wide = html_of("![[Sales]]", graph, cache)
        narrow = html_of("![[Sales|width=50%]]", graph, cache)
        assert 'width="510"' in wide
        assert 'width="255"' in narrow

    def test_rows_cuts_the_table_and_says_so(self):
        frame = pd.DataFrame({"n": range(100)})
        graph, cache, _n = table_node("", frame)
        rendered = render_report("![[Sales|rows=5]]", graph, cache)
        text = rendered.document.toPlainText()
        assert "Showing 5 of 100 rows" in text
        assert rendered.problems == []

    def test_the_default_row_cap_still_applies(self):
        frame = pd.DataFrame({"n": range(100)})
        graph, cache, _n = table_node("", frame)
        text = render_report("![[Sales]]", graph, cache).document.toPlainText()
        assert f"Showing {TABLE_ROWS} of 100 rows" in text

    def test_a_nonsense_row_count_is_reported(self):
        graph, cache, _n = table_node("")
        rendered = render_report("![[Sales|rows=lots]]", graph, cache)
        assert rendered.problems

    def test_the_one_chart_only_option_on_a_table_says_so(self):
        """`ratio` is the only one a table cannot take: it has no shape to
        be redrawn at, being exactly as tall as its rows."""
        graph, cache, _n = table_node("")
        rendered = render_report("![[Sales|ratio=16:9]]", graph, cache)
        assert any("ratio only applies to a chart" in p
                   for p in rendered.problems)

    def test_the_other_options_no_longer_complain_on_a_table(self):
        graph, cache, _n = table_node("")
        rendered = render_report(
            "![[Sales|width=50%|height=200|scale=0.8|rows=5]]", graph, cache)
        assert rendered.problems == []


class TestFrameToHtml:
    """The builder itself, without a report around it."""

    def test_a_series_becomes_a_one_column_table(self):
        html = frame_to_html(pd.Series([1, 2], name="a"))
        assert "<th" in html and ">a<" in html

    def test_missing_values_are_blank_not_nan(self):
        html = frame_to_html(pd.DataFrame({"a": [1.0, None]}))
        assert "nan" not in html.lower()

    def test_the_markup_of_a_value_cannot_escape_its_cell(self):
        html = frame_to_html(pd.DataFrame({"a": ["<b>bold</b>"]}))
        assert "&lt;b&gt;" in html and "<b>bold" not in html

    def test_numbers_are_right_aligned(self):
        html = frame_to_html(pd.DataFrame({"a": [1, 2]}))
        assert 'align="right"' in html

    def test_an_empty_frame_says_so_rather_than_raising(self):
        assert "no columns" in frame_to_html(pd.DataFrame())

    def test_a_narrow_table_puts_the_bar_under_its_value(self):
        """Side by side, the number and the bar share one line's width, and
        Qt pays for a narrow column by wrapping the number to one digit a
        line. Under it costs a row of height and keeps the figure."""
        rules = parse_rules("a bar blue")
        frame = pd.DataFrame({"a": [412, 233], "b": ["x", "y"]})
        wide = frame_to_html(frame, rules, width=510)
        narrow = frame_to_html(frame, rules, width=240)
        assert "<div align=" in narrow
        assert "<div align=" not in wide

    def test_rules_can_be_left_dark_for_a_dark_ground(self):
        rules = parse_rules("a scale green")
        light = frame_to_html(pd.DataFrame({"a": [1, 5]}), rules)
        dark = frame_to_html(pd.DataFrame({"a": [1, 5]}), rules, paper=False)
        assert light != dark


class TestFormatOnlyOnPaper:
    """A rule that replaces the value with its format does so in the report
    too — the page has to look like the card it came from."""

    def test_a_bar_only_column_prints_the_bar_and_no_number(self):
        frame = pd.DataFrame({"units": [412, 233]})
        html = frame_to_html(frame, parse_rules("units bar blue only"))
        assert "412" not in html and "233" not in html
        assert "width=" in html          # the bar's track is still drawn

    def test_an_icon_only_column_prints_the_icon_centred(self):
        frame = pd.DataFrame({"sla": ["breach"], "flag": ["breach"]})
        html = frame_to_html(
            frame, parse_rules("flag iconmap only sla: breach=✗ red"))
        assert "✗" in html and 'align="center"' in html
        # the value is gone from the flag column, not from the table
        assert html.count("breach") == 1

    def test_without_only_the_value_still_prints(self):
        frame = pd.DataFrame({"units": [412]})
        assert "412" in frame_to_html(frame, parse_rules("units bar blue"))


class TestLayoutOnPaper:
    """Width, alignment and header labels have to reach the page, or the
    report stops looking like the card it was taken from."""

    FRAME = pd.DataFrame({"region": ["North"], "revenue": [482000]})

    def test_a_width_rule_sizes_the_printed_column(self):
        html = frame_to_html(self.FRAME, parse_rules("revenue width 160"))
        # on the header, which is the row Qt takes a column's width from
        assert '<th align="right" width="160">' in html

    def test_an_align_rule_beats_the_dtype(self):
        html = frame_to_html(self.FRAME, parse_rules("revenue align left"))
        assert '<td align="left"' in html and '<td align="right"' not in html

    def test_text_can_be_pushed_right(self):
        html = frame_to_html(self.FRAME, parse_rules("region align right"))
        assert html.count('align="right"') == 4      # both cells, both headers

    def test_a_label_renames_the_printed_header(self):
        html = frame_to_html(self.FRAME,
                             parse_rules('revenue label "Revenue (£)"'))
        assert "Revenue (£)" in html and ">revenue<" not in html

    def test_a_label_cannot_smuggle_markup_in(self):
        html = frame_to_html(self.FRAME,
                             parse_rules('revenue label "<b>bold</b>"'))
        assert "&lt;b&gt;" in html and "<b>bold" not in html

    def test_an_unstyled_table_is_unchanged(self):
        assert frame_to_html(self.FRAME) == frame_to_html(self.FRAME, [])


class TestTheHeaderTone:
    """The header row is toned on paper, whichever path drew the table.

    It used to be toned only under `fit`. A report is laid out twice — into
    a staged document whose `toHtml()` becomes the final document's text —
    and that round trip rewrites every `<th>` as a `<td>`, so the `th` rule
    in REPORT_CSS had nothing left to match. `fit_tables` rebuilds its
    tables from `frame_to_html` and re-sets real `<th>` into the document
    that carries the stylesheet, which is why exactly the fitted ones came
    out right. Pinned as "the two paths agree" rather than against a
    hard-coded grey, so changing the tone need not change the test.

    Scope: a table *flograph* draws — an `![[embed]]` of a card. A table
    typed into the page as markdown is not toned and cannot be by this
    route: Qt's markdown parser builds those with no `<thead>` and no
    `<th>` anywhere, so there is no header for a selector to find.
    """

    #: Enough rows that a `fit` low on the page has to trim some.
    LONG = pd.DataFrame({"region": [f"R{i}" for i in range(12)],
                         "revenue": list(range(12))})

    @staticmethod
    def _header_fills(html: str) -> list:
        """The bgcolor of every cell in the document's first `<thead>`."""
        import re
        head = re.search(r"<thead.*?</thead>", html, re.S)
        return re.findall(r'bgcolor="([^"]+)"', head.group(0)) if head else []

    def test_a_report_table_has_a_toned_header(self):
        graph, cache, _n = table_node()
        fills = self._header_fills(html_of("![[Sales]]", graph, cache))
        assert fills, "the header row carries no fill at all"
        assert len(set(fills)) == 1, f"header cells disagree: {fills}"

    def test_the_body_rows_are_not_toned_with_it(self):
        graph, cache, _n = table_node()
        html = html_of("![[Sales]]", graph, cache)
        # nothing but the header: an unstyled table's data cells are bare
        assert html.count("bgcolor=") == len(self._header_fills(html))

    def test_a_fitted_table_has_the_same_header_as_a_plain_one(self):
        """The bug, in one line: these two disagreed."""
        from flograph.core.page_setup import PageSetup

        setup = PageSetup()
        graph, cache, _n = table_node(frame=self.LONG)
        filler = "\n\n".join(["Lorem ipsum dolor sit amet."] * 30)
        body = f"# Report\n\n{filler}\n\n![[Sales{{}}]]\n"
        plain = render_report(body.format(""), graph, cache, setup=setup)
        fitted = render_report(body.format("|fit"), graph, cache, setup=setup)
        assert (self._header_fills(plain.document.toHtml())
                == self._header_fills(fitted.document.toHtml()))

    def test_the_tone_does_not_leak_into_a_nested_bar_table(self):
        """A data bar is a nested table inside a cell, and it paints its
        own cells — so the check is not "how many fills" but that the
        *header's* fill appears nowhere except the header."""
        graph, cache, _n = table_node("orders bar blue")
        html = html_of("![[Sales]]", graph, cache)
        fills = self._header_fills(html)
        assert fills, "the header row carries no fill at all"
        assert html.count(f'bgcolor="{fills[0]}"') == len(fills)
