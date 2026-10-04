"""A live table's data bars, written for a browser (core/table_html.py).

Qt has no flex and no gradients, so on paper a bar is two tables inside the
cell — a value cell beside a track, the track a row of percentage-width
cells. A live table goes only to a browser, where that came to ~390 bytes
a cell and every theme had to reach into the nested tables to style it.
There it is one span: the value, then an `<i>` whose gradient is the bar.
"""
import re

import pandas as pd

from flograph.core.table_format import parse_rules
from flograph.core.table_html import frame_to_html
from flograph.ui.report.css_themes import LIVE_THEMES
from flograph.ui.report.html import CSS_TEMPLATES
from flograph.ui.report.live import LIVE_CSS


def table(rules, frame=None, **kw):
    frame = frame if frame is not None else pd.DataFrame(
        {"name": ["a", "b", "c"], "units": [0, 50, 100],
         "delta": [-1.0, 0.0, 1.0]})
    return frame_to_html(frame, parse_rules(rules), **kw)


def tracks(html):
    """Each bar's filled run, `--a`/`--b`, without its colour."""
    return [";".join(p for p in t.split(";") if not p.startswith("--c:"))
            for t in re.findall(r'<i style="([^"]*)"></i>', html)]


class TestTheLiveBar:
    def test_no_table_inside_a_cell(self):
        html = table("units bar", live=True)
        assert html.count("<table") == 1
        assert "fg-db" in html and "border:none" not in html

    def test_the_fill_is_the_value_s_share_of_the_track(self):
        assert tracks(table("units bar", live=True)) == [
            "--b:0%", "--b:50%", "--b:100%"]

    def test_every_bar_carries_its_colour(self):
        html = table("units bar green", live=True)
        assert len(re.findall(r'<i style="[^"]*--c:#', html)) == 3

    def test_a_centred_bar_grows_from_the_middle_either_way(self):
        # -1 fills the left half, 0 nothing, +1 the right half
        assert tracks(table("delta bar", live=True)) == [
            "--b:50%", "--a:50%;--b:50%", "--a:50%;--b:100%"]

    def test_only_draws_the_bar_alone(self):
        html = table("units bar only", live=True)
        cells = re.findall(r'<span class="fg-db">(.*?)</span>', html)
        assert cells and all(c.startswith("<i ") for c in cells)

    def test_the_value_keeps_its_column_s_alignment(self):
        html = table("units bar", live=True)
        assert re.search(r'<td align="right"><span class="fg-db"><span>50<',
                         html)

    def test_a_narrow_table_puts_the_track_under_its_value(self):
        assert "fg-db fg-under" in table("units bar", live=True, width=200)


class TestPaperIsUnchanged:
    def test_paper_keeps_its_tables(self):
        html = table("units bar")
        assert "fg-db" not in html
        assert 'bgcolor="#eceef1"' in html and html.count("<table") > 1


class TestMarksPinnedRight:
    RULE = "delta < 0 => icon ▼ red right"

    def test_live_is_two_spans(self):
        html = table(self.RULE, live=True)
        assert '<span class="fg-pr">' in html and html.count("<table") == 1

    def test_paper_is_a_table(self):
        assert '<span class="fg-pr">' not in table(self.RULE)


class TestLiveCells:
    def test_a_styled_cell_restates_no_grid_line(self):
        live = table("units > 10 => bg red", live=True)
        assert "border:" not in live
        assert "border:" in table("units > 10 => bg red")


class TestThemes:
    def test_every_theme_styles_the_new_track_not_the_old_one(self):
        for name, css in CSS_TEMPLATES.items():
            assert "table[bgcolor] {" not in css.replace(
                'table[bgcolor="#eceef1"] {', ""), name
        styled = [n for n, css in LIVE_THEMES.items()
                  if ".fg-db > i" in css]
        assert styled, "no theme recolours a live bar's track"

    def test_the_bar_s_class_is_its_own(self):
        # `.fg-bar` is the live table's search strip, `tr.fg-pin` a pinned
        # total row: the bar must not answer to either
        html = table("units bar", live=True)
        assert "fg-bar" not in html and "fg-pin" not in html
