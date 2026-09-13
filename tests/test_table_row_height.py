"""Row height as a formatting rule: `height 40` for every row, and
`=> height 40` for the rows a test picks — on the card, and on paper, where
Qt's rich text has no row height at all and a tall row is made of padding.
"""
import re

import pandas as pd
import pytest

from flograph.core import sparkline as sp
from flograph.core.table_format import (parse_rules, quote_column,
                                        row_height_of, rule_summary,
                                        style_payload)
from flograph.core.table_html import frame_to_html

FRAME = pd.DataFrame({"name": ["a", "b", "c"],
                      "status": ["ok", "late", "ok"],
                      "units": [1, 2, 3]})

MONTHS = pd.DataFrame({"region": ["North", "South"],
                       "jan": [10, 5], "feb": [12, 4], "mar": [9, 7],
                       "apr": [15, 6]})


class TestParsing:
    def test_a_line_of_its_own_is_every_row(self):
        (rule,) = parse_rules("height 40")
        assert rule.mode == "row_height" and rule.row_height == 40
        assert rule.columns == []

    def test_px_is_accepted(self):
        assert parse_rules("height 40px")[0].row_height == 40

    def test_after_an_arrow_it_is_the_rows_a_test_picks(self):
        (rule,) = parse_rules("status = late => row red, height 48")
        assert rule.mode == "highlight" and rule.scope == "row"
        assert rule.row_height == 48

    def test_a_height_is_a_style_on_its_own(self):
        (rule,) = parse_rules("status = late => height 30")
        assert rule.row_height == 30 and rule.bg is None

    def test_naming_columns_says_why_it_cannot(self):
        with pytest.raises(ValueError, match="one height across the table"):
            parse_rules("units height 40")

    @pytest.mark.parametrize("line", ["height 5", "height 9000",
                                      "status = late => height tall"])
    def test_out_of_range_or_not_a_number(self, line):
        with pytest.raises(ValueError):
            parse_rules(line)

    def test_a_column_called_height_is_still_a_column(self):
        (rule,) = parse_rules("height scale green")
        assert rule.mode == "color_scale" and rule.columns == ["height"]
        assert quote_column("height") == '"height"'

    def test_the_last_height_line_wins(self):
        assert row_height_of(parse_rules("height 30\nheight 50")) == 50

    def test_it_travels_the_style_port(self):
        payload = style_payload({"format_rules":
                                 "height 40\nstatus = late => height 60"})
        found = [(r["mode"], r.get("row_height")) for r in payload["rules"]]
        assert ("row_height", 40) in found and ("highlight", 60) in found

    def test_the_rules_manager_says_it(self):
        assert "40px tall" in rule_summary(parse_rules("height 40")[0])
        assert "48px tall" in rule_summary(
            parse_rules("status = late => row red, height 48")[0])

    def test_the_rules_box_does_not_call_it_a_mistake(self):
        from flograph.core.text_assist import lint_table_rules
        assert lint_table_rules(
            "height 40\nstatus = late => height 60") == []


@pytest.mark.usefixtures("qapp")
class TestOnTheCard:
    def view(self, qtbot, text, frame=FRAME):
        from flograph.ui.data_table import DataTableView
        from flograph.ui.inspector.pandas_model import PandasModel
        view = DataTableView()
        qtbot.addWidget(view)
        view.setModel(PandasModel(frame, rules=parse_rules(text)))
        view.resize(500, 320)
        view.show()
        return view

    @staticmethod
    def heights(view):
        return [view.rowHeight(r) for r in range(view.model().rowCount())]

    def test_every_row_takes_the_height(self, qtbot):
        view = self.view(qtbot, "height 44")
        qtbot.waitUntil(lambda: self.heights(view) == [44, 44, 44],
                        timeout=2000)

    def test_a_compact_height_is_allowed(self, qtbot):
        view = self.view(qtbot, "height 14")
        qtbot.waitUntil(lambda: self.heights(view) == [14, 14, 14],
                        timeout=2000)

    def test_only_the_rows_a_test_picks_grow(self, qtbot):
        view = self.view(qtbot, "status = late => height 60")
        qtbot.waitUntil(lambda: view.rowHeight(1) == 60, timeout=2000)
        assert view.rowHeight(0) < 60 and view.rowHeight(2) < 60

    def test_a_picked_row_beats_the_table_height(self, qtbot):
        view = self.view(qtbot, "height 30\nstatus = late => height 70")
        qtbot.waitUntil(lambda: self.heights(view) == [30, 70, 30],
                        timeout=2000)

    def test_a_mark_on_a_line_of_its_own_is_never_cut_off(self, qtbot):
        plain = self.view(qtbot, "status = late => icon ! amber above")
        short = self.view(qtbot,
                          "height 14\nstatus = late => icon ! amber above")
        qtbot.waitUntil(lambda: plain.rowHeight(1) > 14, timeout=2000)
        qtbot.waitUntil(lambda: short.rowHeight(1) == plain.rowHeight(1),
                        timeout=2000)

    def test_a_spark_on_its_own_grows_with_the_row(self, qtbot):
        from PySide6.QtGui import QColor

        def ink_height(text):
            view = self.view(qtbot, text, frame=MONTHS)
            view.setColumnWidth(5, 160)
            qtbot.waitUntil(lambda: view.rowHeight(0) > 0, timeout=2000)
            image = view.viewport().grab().toImage()
            cell = view.visualRect(view.model().index(0, 5))
            target = QColor(sp.DEFAULT_COLOR)
            ys = [y for x in range(cell.left(), cell.right())
                  for y in range(cell.top(), cell.bottom())
                  if all(abs(a - b) < 40 for a, b in zip(
                      QColor(image.pixel(x, y)).getRgb()[:3],
                      target.getRgb()[:3]))]
            assert ys, "no spark was painted"
            return max(ys) - min(ys)

        short = ink_height("trend spark from jan..apr")
        tall = ink_height("height 80\ntrend spark from jan..apr")
        assert tall > short * 2


class TestOnPaper:
    @staticmethod
    def body_rows(html):
        return html.split("<tr>")[2:]        # past the header row

    def test_every_row_is_padded_towards_the_height(self):
        html = frame_to_html(FRAME, parse_rules("height 50"))
        rows = self.body_rows(html)
        assert len(rows) == 3
        assert all(row.count("padding-top:") == 3 for row in rows)

    def test_only_the_picked_rows_are_padded(self):
        rows = self.body_rows(frame_to_html(
            FRAME, parse_rules("status = late => height 50")))
        assert ["padding-top" in row for row in rows] == [False, True, False]

    def test_no_height_no_padding(self):
        assert "padding-top" not in frame_to_html(FRAME, parse_rules(
            "units scale green"))

    def test_a_spark_grows_with_the_row(self):
        html = frame_to_html(MONTHS, parse_rules(
            "height 60\ntrend spark from jan..apr"))
        heights = [float(h) for h in re.findall(
            r'<img src="data:image/svg\+xml;base64,[^"]*" width="[\d.]+" '
            r'height="([\d.]+)"', html)]
        assert heights and min(heights) >= 60 - 10

    @pytest.mark.usefixtures("qapp")
    def test_the_report_row_really_is_taller(self):
        from PySide6.QtGui import QTextTable

        from flograph.core import Graph, NodeRegistry
        from flograph.engine.cache import OutputCache
        from flograph.ui.report.render import render_report

        registry = NodeRegistry()
        registry.load_builtins()

        def table_height(rules):
            graph, cache = Graph(), OutputCache()
            node = graph.add_node(
                registry.instantiate("flograph.viz.show_table"))
            graph.set_label(node.id, "Sales")
            cache.set(node.id, {"table": FRAME, "style": style_payload(
                {"format_rules": rules})}, 0.0)
            document = render_report("![[Sales]]", graph, cache).document
            document.setTextWidth(600)
            table = next(f for f in document.rootFrame().childFrames()
                         if isinstance(f, QTextTable))
            return document.documentLayout().frameBoundingRect(table).height()

        plain = table_height("units scale green")
        tall = table_height("units scale green\nheight 60")
        # three rows, each well over twenty points taller
        assert tall - plain > 3 * 20


@pytest.mark.usefixtures("qapp")
class TestTheRulesDialog:
    COLUMNS = ["name", "status", "units"]

    def test_the_row_height_page(self, qtbot):
        from flograph.ui.properties.table_rule_wizard import (K_HEIGHT,
                                                              RuleBuilder)
        builder = RuleBuilder(self.COLUMNS)
        qtbot.addWidget(builder)
        builder._kind.setCurrentIndex(K_HEIGHT)
        builder._height.setValue(36)
        assert builder.line() == "height 36"
        assert parse_rules(builder.line())[0].row_height == 36

    def test_editing_a_height_line_keeps_it(self, qtbot):
        from flograph.ui.properties.table_rule_wizard import RuleBuilder
        builder = RuleBuilder(self.COLUMNS,
                              rule=parse_rules("height 52")[0])
        qtbot.addWidget(builder)
        assert builder.line() == "height 52"

    def test_a_highlight_keeps_its_height(self, qtbot):
        from flograph.ui.properties.table_rule_wizard import RuleBuilder
        (rule,) = parse_rules("status = late => row red, height 48")
        builder = RuleBuilder(self.COLUMNS, rule=rule)
        qtbot.addWidget(builder)
        (again,) = parse_rules(builder.line())
        assert (again.scope, again.row_height) == ("row", 48)

    def test_a_highlight_without_a_height_writes_none(self, qtbot):
        from flograph.ui.properties.table_rule_wizard import RuleBuilder
        (rule,) = parse_rules("status = late => bg red")
        builder = RuleBuilder(self.COLUMNS, rule=rule)
        qtbot.addWidget(builder)
        assert "height" not in builder.line()
