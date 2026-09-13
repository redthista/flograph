"""Sparklines in a table: a row's numbers drawn as a chart the size of a word.

Four layers, tested where each can be wrong on its own: the drawing
(core/sparkline — where every line, bar and dot goes), the rule (parsing,
which columns it reads, the column it makes), the card (the model, the
delegate's pixels, the column's width) and the page (the SVG a report
prints, which has to survive Qt's markdown pass).
"""
import xml.etree.ElementTree as ET

import pandas as pd
import pytest

from flograph.core import sparkline as sp
from flograph.core.table_format import (
    Rule, column_stats, evaluate_column, for_paper, on_white, parse_rules,
    quote_column, rules_from_style, series_columns, spark_projection,
    style_payload, style_report)
from flograph.core.table_html import frame_to_html

MONTHS = pd.DataFrame({
    "region": ["North", "South", "East"],
    "jan": [10, 5, None],
    "feb": [12, -4, 3.0],
    "mar": [9, 7, None],
    "apr": [15, 6, None],
})


def spark(values, **kw):
    return sp.Spark(values=list(values), **kw)


# ------------------------------------------------------------ the drawing

class TestGeometry:
    def test_fewer_than_two_numbers_draw_nothing(self):
        assert sp.geometry(spark([None, 3, None]), 60, 16) is None

    def test_a_blank_is_a_gap_not_a_zero(self):
        shapes = sp.geometry(spark([1, 2, None, 4, 5]), 60, 16)
        assert len(shapes.lines) == 2
        # nothing is drawn at the floor for the missing value
        assert all(len(points) == 2 for points, _c, _w in shapes.lines)

    def test_a_lone_value_between_gaps_is_a_dot(self):
        shapes = sp.geometry(spark([1, 2, None, 4, None]), 60, 16)
        assert len(shapes.lines) == 1 and len(shapes.dots) == 1

    def test_the_high_point_sits_at_the_top(self):
        shapes = sp.geometry(spark([1, 9, 3]), 60, 16)
        points = shapes.lines[0][0]
        assert min(points, key=lambda p: p[1]) == points[1]

    def test_marks_land_on_their_points_in_their_colours(self):
        shapes = sp.geometry(spark([4, 9, 1, 5], marks=[["high", None],
                                                      ["low", "#123456"]]),
                             60, 16)
        colours = [c for _x, _y, _r, c in shapes.dots]
        assert sp.MARK_COLORS["high"] in colours and "#123456" in colours

    def test_bars_grow_from_zero_and_negatives_hang_below(self):
        shapes = sp.geometry(spark([3, -2], kind="bars"), 40, 20)
        (_x1, y1, _w1, h1, c1), (_x2, y2, _w2, h2, c2) = shapes.rects
        assert y1 + h1 == pytest.approx(y2)       # both meet at zero
        assert c2 == sp.NEGATIVE_COLOR and c1 == sp.DEFAULT_COLOR

    def test_winloss_is_up_or_down_whatever_the_size(self):
        shapes = sp.geometry(spark([100, -1, 3], kind="winloss"), 30, 20)
        heights = {round(h, 3) for _x, _y, _w, h, _c in shapes.rects}
        assert len(heights) == 1

    def test_a_smooth_curve_never_passes_the_real_high(self):
        points = [(0, 10), (10, 2), (20, 9), (30, 3)]
        top = min(y for _x, y in points)
        bottom = max(y for _x, y in points)
        for c1, c2, _end in sp.curve(points):
            assert top <= c1[1] <= bottom and top <= c2[1] <= bottom

    def test_a_shared_scale_keeps_a_small_row_small(self):
        own = sp.geometry(spark([1, 2]), 60, 20).lines[0][0]
        shared = sp.geometry(spark([1, 2], low=0, high=100), 60, 20).lines[0][0]
        assert own[1][1] < shared[1][1]           # higher on its own scale

    def test_a_reference_line_is_a_dashed_guide(self):
        shapes = sp.geometry(spark([1, 5], ref=3.0), 60, 20)
        assert any(dashed for _y, _c, dashed in shapes.guides)

    def test_the_svg_is_well_formed(self):
        text = sp.svg(spark([1, 3, 2], kind="area", smooth=True,
                            marks=[["last", None]]), 60, 16)
        root = ET.fromstring(text)
        assert root.tag.endswith("svg")

    def test_the_summary_names_the_columns(self):
        text = sp.summary([10, None, 15, 9], ["jan", "feb", "mar", "apr"])
        assert "jan 10 → apr 9" in text and "high 15 (mar)" in text

    def test_reference_mean_and_median(self):
        assert sp.reference("mean", [1, 2, 6]) == 3
        assert sp.reference("median", [1, 2, 6, None]) == 2
        assert sp.reference(0.0, [5]) == 0.0


# ---------------------------------------------------------------- the rule

class TestParsing:
    def test_the_plain_form(self):
        (rule,) = parse_rules("trend spark from jan..apr")
        assert rule.mode == "sparkline" and rule.columns == ["trend"]
        assert rule.series == ["jan..apr"] and rule.spark_kind == "line"

    def test_every_setting_in_any_order(self):
        (rule,) = parse_rules(
            "trend spark tall bars green negative red ref mean high amber "
            "low shared smooth thick 90px right replace from jan, feb, mar")
        assert rule.spark_kind == "bars"
        assert rule.color == sp.COLORS["green"]
        assert rule.negative_color == sp.COLORS["red"]
        assert rule.ref == "mean"
        assert rule.marks == [["high", sp.COLORS["amber"]], ["low", None]]
        assert (rule.shared, rule.smooth, rule.thick, rule.tall) == (
            True, True, True, True)
        assert rule.spark_width == 90 and rule.glyph_where == "right"
        assert rule.take_sources == "replace"
        assert rule.series == ["jan", "feb", "mar"]

    def test_hide_can_follow_the_column_list(self):
        (rule,) = parse_rules("trend spark from jan..apr hide")
        assert rule.take_sources == "hide" and rule.series == ["jan..apr"]

    def test_a_column_called_hide_in_the_list_survives(self):
        (rule,) = parse_rules("trend spark from jan, hide")
        assert rule.take_sources is None and rule.series == ["jan", "hide"]

    def test_the_list_may_hold_names_that_read_like_keywords(self):
        (rule,) = parse_rules("trend spark from label, sort, tip")
        assert rule.mode == "sparkline"
        assert rule.series == ["label", "sort", "tip"]

    def test_ends_is_first_and_last(self):
        (rule,) = parse_rules("t spark ends from a, b")
        assert [m[0] for m in rule.marks] == ["first", "last"]

    def test_the_dict_round_trip_keeps_a_zero_reference(self):
        (rule,) = parse_rules("t spark ref 0 from a, b")
        again = Rule.from_dict(rule.to_dict())
        assert again.ref == 0.0

    @pytest.mark.parametrize("line, words", [
        ("trend spark jan..apr", "needs the columns"),
        ("trend spark wobbly from a, b", "don't understand 'wobbly'"),
        ("trend spark ref from a, b", "'ref' needs"),
        ("trend spark 5000px from a, b", "outside"),
        ("trend spark negative from a, b", "needs a colour"),
    ])
    def test_mistakes_say_what_is_wrong(self, line, words):
        with pytest.raises(ValueError, match=words):
            parse_rules(line)

    def test_a_column_named_spark_is_quoted(self):
        assert quote_column("spark") == '"spark"'


class TestWhichColumns:
    def test_a_range_is_inclusive_in_table_order(self):
        assert series_columns(["jan..mar"], MONTHS) == ["jan", "feb", "mar"]

    def test_a_range_written_backwards_reads_backwards(self):
        assert series_columns(["mar..jan"], MONTHS) == ["mar", "feb", "jan"]

    def test_a_range_across_a_text_column_leaves_it_out(self):
        assert series_columns(["region..feb"], MONTHS) == ["jan", "feb"]

    def test_a_pattern_takes_numeric_columns_but_not_its_own(self):
        frame = MONTHS.assign(j_total=1)
        assert series_columns(["j*"], frame, exclude=["j_total"]) == ["jan"]

    def test_a_named_column_is_read_even_if_it_is_text(self):
        assert series_columns(["region", "jan"], MONTHS) == ["region", "jan"]


class TestTheColumnItMakes:
    def test_a_new_column_holds_the_latest_number(self):
        frame, rules, hidden = spark_projection(
            MONTHS, parse_rules("trend spark from jan..apr"))
        assert list(frame.columns)[-1] == "trend"
        assert frame["trend"].tolist()[:2] == [15.0, 6.0]
        assert frame["trend"].tolist()[2] == 3.0      # latest *present*
        assert hidden == [] and rules[0].glyph_where == "in"

    def test_the_table_leaving_the_card_is_untouched(self):
        before = list(MONTHS.columns)
        spark_projection(MONTHS, parse_rules("trend spark from jan..apr"))
        assert list(MONTHS.columns) == before

    def test_replace_puts_it_where_the_sources_were(self):
        frame, _rules, hidden = spark_projection(
            MONTHS, parse_rules("trend spark from jan..apr replace"))
        assert list(frame.columns) == ["region", "trend", "jan", "feb",
                                       "mar", "apr"]
        assert hidden == ["jan", "feb", "mar", "apr"]

    def test_an_existing_column_keeps_its_value_and_gets_it_beside(self):
        frame, rules, _hidden = spark_projection(
            MONTHS, parse_rules("region spark from jan..apr"))
        assert list(frame.columns) == list(MONTHS.columns)
        assert rules[0].glyph_where is None             # left, like an icon

    def test_one_sparks_column_is_not_read_by_anothers_pattern(self):
        _frame, rules, _hidden = spark_projection(
            MONTHS, parse_rules("a spark from *\nb spark from *"))
        assert all("a" not in r.series for r in rules)

    def test_nothing_to_read_makes_no_column(self):
        frame, _rules, _hidden = spark_projection(
            MONTHS, parse_rules("x spark from nope..zip"))
        assert "x" not in frame.columns

    def test_a_placed_spark_on_a_new_column_shows_the_number(self):
        _frame, rules, _hidden = spark_projection(
            MONTHS, parse_rules("trend spark right from jan..apr"))
        assert rules[0].glyph_where == "right"


class TestEvaluation:
    def styles(self, text, frame=MONTHS):
        frame, rules, _hidden = spark_projection(frame, parse_rules(text))
        column = frame[rules[0].columns[0]]
        return evaluate_column(column, rules, column_stats(column),
                               frame=frame)

    def test_a_row_with_one_number_draws_nothing(self):
        assert self.styles("trend spark from jan..apr")[2] is None

    def test_standing_alone_it_hides_the_value_and_explains_itself(self):
        style = self.styles("trend spark from jan..apr")[0]
        (decoration,) = style.decorations
        assert decoration.where == "in" and style.hide_value
        assert "jan 10 → apr 15" in style.tooltip

    def test_beside_a_value_it_leaves_the_tooltip_alone(self):
        style = self.styles("region spark from jan..apr")[0]
        assert not style.hide_value and style.tooltip is None
        assert style.decorations[0].where == "left"

    def test_shared_measures_the_whole_column(self):
        style = self.styles("trend spark shared from jan..apr")[0]
        assert style.decorations[0].spark.low == -4.0
        assert style.decorations[0].spark.high == 15.0

    def test_it_composes_with_an_icon_on_the_same_cell(self):
        frame, rules, _h = spark_projection(MONTHS, parse_rules(
            "region spark from jan..apr\nregion = North => icon ✓ green right"))
        column = frame["region"]
        acc = None
        for rule in rules:
            part = evaluate_column(column, [rule], column_stats(column),
                                   frame=frame)[0]
            acc = part.over(acc) if part else acc
        assert [d.where for d in acc.decorations] == ["left", "right"]


class TestReporting:
    def test_the_column_it_makes_is_not_missing(self):
        payload = style_payload({"format_rules": "trend spark from jan..apr"})
        assert style_report(payload, MONTHS) == []

    def test_other_rules_may_use_the_column_it_makes(self):
        """`trend width 180` and `show region, trend` name a column the
        table does not have yet — the spark is making it, so neither is a
        mistake worth a line in the log."""
        payload = style_payload({"format_rules": (
            "trend spark from jan..apr\ntrend width 180\nshow region, trend")})
        assert style_report(payload, MONTHS) == []

    def test_a_range_to_nowhere_is_reported(self):
        payload = style_payload({"format_rules": "t spark from jan..dec"})
        messages = " ".join(style_report(payload, MONTHS))
        assert "dec" in messages and "no numeric column" in messages

    def test_paper_darkens_a_line_that_would_vanish(self):
        frame, rules, _h = spark_projection(
            MONTHS, parse_rules("trend spark yellow from jan..apr"))
        style = evaluate_column(frame["trend"], rules,
                                column_stats(frame["trend"]), frame=frame)[0]
        printed = for_paper(style).decorations[0].spark
        assert printed.color == on_white(sp.COLORS["yellow"])
        assert printed.color != sp.COLORS["yellow"]


# ---------------------------------------------------------------- the page

class TestOnPaper:
    def test_it_prints_as_an_svg_picture(self):
        html = frame_to_html(MONTHS, parse_rules("trend spark from jan..apr"))
        assert html.count("data:image/svg+xml;base64,") == 2   # 2 drawable rows
        assert ">trend</th>" in html

    @staticmethod
    def widths(html):
        import re
        return [float(w) for w in re.findall(
            r'<img src="data:image/svg\+xml;base64,[^"]*" width="([\d.]+)"',
            html)]

    def test_without_a_table_width_the_fixed_sizes(self):
        html = frame_to_html(MONTHS, parse_rules(
            "region spark right from jan..apr"))
        assert set(self.widths(html)) == {sp.PAPER_BESIDE}

    def test_a_wide_table_gives_a_spark_its_columns_room(self):
        html = frame_to_html(MONTHS, parse_rules(
            "region spark right from jan..apr\nhide jan, feb, mar, apr"),
            width=500)
        widths = self.widths(html)
        assert min(widths) > sp.PAPER_BESIDE * 2
        assert len(set(widths)) == 1          # one width: they line up

    def test_beside_a_value_leaves_the_value_its_room(self):
        # narrow enough that neither reaches PAPER_MAX_WIDTH, which would
        # make the two the same width for a reason that isn't the value.
        # The hidden columns go in the way a report hands them over — a
        # `hide` line in the rules is the style port's business, not this
        # builder's, and months left showing would squeeze both to the least.
        months = ["jan", "feb", "mar", "apr"]
        beside = self.widths(frame_to_html(
            MONTHS, parse_rules("region spark right from jan..apr"),
            hidden=months, width=200))
        alone = self.widths(frame_to_html(
            MONTHS, parse_rules("trend spark from jan..apr"),
            hidden=months + ["region"], width=200))
        assert sp.PAPER_MIN_WIDTH < beside[0] < alone[0] < sp.PAPER_MAX_WIDTH

    def test_a_narrow_table_still_draws_a_readable_spark(self):
        html = frame_to_html(MONTHS, parse_rules(
            "region spark right from jan..apr"), width=120)
        assert min(self.widths(html)) >= sp.PAPER_MIN_WIDTH

    def test_it_never_grows_past_the_most(self):
        html = frame_to_html(MONTHS, parse_rules(
            "trend spark from jan..apr\nhide jan, feb, mar, apr, region"),
            width=2000)
        assert max(self.widths(html)) <= sp.PAPER_MAX_WIDTH

    def test_a_named_width_wins(self):
        html = frame_to_html(MONTHS, parse_rules(
            "region spark 40px right from jan..apr"), width=500)
        assert set(self.widths(html)) == {30.0}

    @pytest.mark.usefixtures("qapp")
    @pytest.mark.parametrize("rules", [
        # text columns beside three sparks standing alone
        ("owner spark from jan..apr\nchange spark bars from jan..apr\n"
         "moves spark winloss from jan..apr\n"
         "hide jan, feb, mar, apr"),
        # sparks beside the values of every column
        ("region spark right from jan..apr\n"
         "label spark from jan..apr\nhide jan, feb, mar, apr"),
    ])
    def test_the_room_given_to_sparks_never_breaks_a_word(self, rules):
        """Promising the sparks a hair more than the table has makes Qt
        squeeze the text columns by breaking words: "Regio / n",
        "Centr / al". Every text line of the page must still be one line."""
        import re

        from flograph.core import Graph, NodeRegistry
        from flograph.engine.cache import OutputCache
        from flograph.ui.report.render import render_report

        frame = MONTHS.assign(region=["Northumberland", "Southampton",
                                      "East Anglia"],
                              label=["Central region", "Coastal", "West"])
        registry = NodeRegistry()
        registry.load_builtins()
        graph, cache = Graph(), OutputCache()
        node = graph.add_node(registry.instantiate("flograph.viz.show_table"))
        graph.set_label(node.id, "Sales")
        cache.set(node.id, {"table": frame,
                            "style": style_payload({"format_rules": rules})},
                  0.0)
        document = render_report("![[Sales]]", graph, cache).document
        width = re.search(r'<table[^>]*width="(\d+)"', document.toHtml())
        document.setTextWidth(float(width.group(1)) if width else 500.0)
        broken = []
        block = document.begin()
        while block.isValid():
            if block.text().strip() and block.layout().lineCount() > 1:
                broken.append(block.text())
            block = block.next()
        assert broken == []

    def test_replace_takes_the_months_off_the_page(self):
        html = frame_to_html(
            MONTHS, parse_rules("trend spark from jan..apr replace"))
        assert ">jan</th>" not in html and ">trend</th>" in html

    def test_it_survives_the_report_pass(self):
        from flograph.core import Graph, NodeRegistry
        from flograph.engine.cache import OutputCache
        from flograph.ui.report.render import render_report

        registry = NodeRegistry()
        registry.load_builtins()
        graph, cache = Graph(), OutputCache()
        node = graph.add_node(registry.instantiate("flograph.viz.show_table"))
        graph.set_label(node.id, "Sales")
        style = style_payload({"format_rules": "trend spark from jan..apr"})
        cache.set(node.id, {"table": MONTHS, "style": style}, 0.0)
        rendered = render_report("![[Sales]]", graph, cache)
        html = rendered.document.toHtml()
        assert "@@flograph-spark" not in html
        assert "data:image/svg+xml" in html


# ---------------------------------------------------------------- the card

@pytest.mark.usefixtures("qapp")
class TestOnTheCard:
    def model(self, text, frame=MONTHS):
        from flograph.ui.inspector.pandas_model import PandasModel
        return PandasModel(frame, rules=parse_rules(text))

    def test_the_model_carries_the_new_column_and_hides_the_sources(self):
        from PySide6.QtCore import Qt
        model = self.model("trend spark from jan..apr hide")
        headers = [model.headerData(c, Qt.Horizontal)
                   for c in range(model.columnCount())]
        assert headers == ["region", "trend"]
        index = model.index(0, 1)
        assert model.data(index, Qt.DisplayRole) == ""        # the spark only
        assert model.data(index, Qt.EditRole) == "15.0"       # copies a number

    def test_the_decoration_role_carries_the_spark(self):
        from flograph.ui.table_delegate import DECOR_ROLE
        model = self.model("trend spark from jan..apr")
        marks, _pill, _ink = model.data(model.index(0, 5), DECOR_ROLE)
        assert marks[0].spark is not None

    def test_sorting_the_new_column_sorts_by_the_latest_number(self):
        from PySide6.QtCore import Qt
        model = self.model("trend spark from jan..apr")
        model.sort(5, Qt.AscendingOrder)
        assert model.data(model.index(0, 0), Qt.DisplayRole) == "East"

    def grab(self, qtbot, text, column, width=160):
        from flograph.ui.data_table import DataTableView
        view = DataTableView()
        view.setModel(self.model(text))
        view.setColumnWidth(column, width)
        view.resize(700, 140)
        qtbot.addWidget(view)
        return view, view.viewport().grab().toImage(), view.visualRect(
            view.model().index(0, column))

    @staticmethod
    def ink(image, cell):
        from PySide6.QtGui import QColor
        target = QColor(sp.DEFAULT_COLOR)
        xs = [x for x in range(cell.left(), cell.right())
              for y in range(cell.top(), cell.bottom())
              if abs(QColor(image.pixel(x, y)).blue() - target.blue()) < 40
              and abs(QColor(image.pixel(x, y)).red() - target.red()) < 40
              and abs(QColor(image.pixel(x, y)).green() - target.green()) < 40]
        return xs

    def test_a_spark_on_its_own_spans_the_cell(self, qtbot):
        _view, image, cell = self.grab(qtbot, "trend spark from jan..apr", 5)
        xs = self.ink(image, cell)
        assert xs, "no spark was painted"
        assert max(xs) - min(xs) > cell.width() * 0.8

    def test_a_spark_beside_a_value_stays_on_the_left(self, qtbot):
        _view, image, cell = self.grab(
            qtbot, "region spark from jan..apr", 0, width=200)
        xs = self.ink(image, cell)
        assert xs and min(xs) < cell.left() + cell.width() * 0.2

    def test_a_spark_beside_a_value_grows_into_a_wide_cell(self, qtbot):
        """A fixed 64px left most of a wide cell empty round a stub."""
        _view, image, cell = self.grab(
            qtbot, "region spark right from jan..apr", 0, width=400)
        xs = self.ink(image, cell)
        assert xs and max(xs) - min(xs) > 64 + 100

    def test_the_value_keeps_its_room_beside_a_grown_spark(self, qtbot):
        from PySide6.QtGui import QFontMetrics
        from PySide6.QtWidgets import QStyleOptionViewItem
        view, _image, _cell = self.grab(
            qtbot, "region spark right from jan..apr", 0, width=400)
        index = view.model().index(0, 0)
        option = QStyleOptionViewItem()
        option.rect = view.visualRect(index)
        option.font = view.font()
        option.widget = view
        area = view.itemDelegate(index).value_area(option, index)
        assert area.width() >= QFontMetrics(view.font()).horizontalAdvance(
            "North")

    def test_a_tall_spark_makes_its_row_taller(self, qtbot):
        from flograph.ui.table_delegate import ConditionalFormatDelegate
        from PySide6.QtWidgets import QStyleOptionViewItem
        delegate = ConditionalFormatDelegate()
        short = self.model("trend spark from jan..apr")
        tall = self.model("trend spark tall from jan..apr")
        option = QStyleOptionViewItem()
        assert (delegate.sizeHint(option, tall.index(0, 5)).height()
                > delegate.sizeHint(option, short.index(0, 5)).height())

    @pytest.mark.parametrize("text", [
        "region spark below tall from jan..apr",
        "trend spark tall from jan..apr",
        # not a spark at all: a mark on a line of its own always asked the
        # delegate for a taller row, and the view never used to listen
        "region = North => icon ✓ green above",
    ])
    def test_the_row_really_grows_in_a_view(self, qtbot, text):
        from flograph.ui.data_table import DataTableView
        plain, grown = DataTableView(), DataTableView()
        for view, rules in ((plain, ""), (grown, text)):
            qtbot.addWidget(view)
            view.setModel(self.model(rules))
            view.resize(700, 200)
            view.show()
        qtbot.waitUntil(lambda: grown.rowHeight(0) > plain.rowHeight(0),
                        timeout=2000)

    def test_a_spark_column_is_given_room(self, qtbot):
        from flograph.ui.data_table import SPARK_ALONE_WIDTH, DataTableView
        view = DataTableView()
        qtbot.addWidget(view)
        view.setModel(self.model("t spark from jan..apr"))
        assert view.columnWidth(5) >= SPARK_ALONE_WIDTH


# --------------------------------------------------------------- the dialog

@pytest.mark.usefixtures("qapp")
class TestTheRulesDialog:
    def builder(self, columns=("region", "jan", "feb", "mar", "apr")):
        from flograph.ui.properties.table_rule_wizard import (K_SPARK,
                                                              RuleBuilder)
        dialog = RuleBuilder(list(columns))
        dialog._kind.setCurrentIndex(K_SPARK)
        return dialog

    def test_a_range_writes_a_line_that_parses(self, qtbot):
        dialog = self.builder()
        qtbot.addWidget(dialog)
        dialog._col_edit.setText("trend")
        dialog._spark_start.setCurrentIndex(1)
        dialog._spark_end.setCurrentIndex(4)
        dialog._spark_marks["last"].setChecked(True)
        dialog._spark_kind.setCurrentIndex(1)             # area
        line = dialog.line()
        assert line == "trend spark area last from jan..apr"
        (rule,) = parse_rules(line)
        assert rule.spark_kind == "area"

    def test_editing_a_rule_writes_the_same_rule_back(self, qtbot):
        from flograph.ui.properties.table_rule_wizard import RuleBuilder
        text = ("trend spark bars teal negative red high green low ref mean "
                "shared smooth 90px right replace from jan..apr")
        (rule,) = parse_rules(text)
        dialog = RuleBuilder(["region", "jan", "feb", "mar", "apr"],
                             rule=rule)
        qtbot.addWidget(dialog)
        (again,) = parse_rules(dialog.line())
        assert again.to_dict() == rule.to_dict()

    def test_a_pattern_without_a_table(self, qtbot):
        from flograph.ui.properties.table_rule_wizard import RuleBuilder
        (rule,) = parse_rules("trend spark from sales_* hide")
        dialog = RuleBuilder([], rule=rule)
        qtbot.addWidget(dialog)
        assert dialog.line() == "trend spark hide from sales_*"


class TestNullableColumns:
    """The Table node types a number column `Float64` and an integer one
    `Int64`, whose blank is `pd.NA` — not None, not NaN. `float(pd.NA)`
    raises, and raised inside a card's data() it took the app down."""

    FRAME = pd.DataFrame({
        "region": ["North", "Central"],
        "jan": pd.array([10.0, 3.0], dtype="Float64"),
        "feb": pd.array([12.0, None], dtype="Float64"),
        "mar": pd.array([9, None], dtype="Int64"),
        "apr": pd.array([15.0, 6.0], dtype="Float64"),
    })

    @pytest.mark.parametrize("text", [
        "trend spark from jan..apr",
        "region spark below tall from jan..apr",
        "trend spark shared bars ref mean from jan..apr",
    ])
    def test_a_blank_is_still_a_gap(self, text):
        frame, rules, _h = spark_projection(self.FRAME, parse_rules(text))
        name = rules[0].columns[0]
        styles = evaluate_column(frame[name], rules, column_stats(frame[name]),
                                 frame=frame)
        values = styles[1].decorations[0].spark.values
        assert values == [3.0, None, None, 6.0]

    def test_the_new_column_holds_a_plain_number(self):
        frame, _rules, _h = spark_projection(
            self.FRAME, parse_rules("trend spark from jan..apr"))
        assert frame["trend"].tolist() == [15.0, 6.0]

    def test_it_prints(self):
        html = frame_to_html(self.FRAME,
                             parse_rules("trend spark from jan..apr"))
        assert html.count("data:image/svg+xml") == 2

    @pytest.mark.usefixtures("qapp")
    def test_the_card_draws_it(self, qtbot):
        from flograph.ui.data_table import DataTableView
        from flograph.ui.inspector.pandas_model import PandasModel
        from flograph.ui.table_delegate import DECOR_ROLE
        view = DataTableView()
        qtbot.addWidget(view)
        view.setModel(PandasModel(self.FRAME, rules=parse_rules(
            "region spark below tall from jan..apr")))
        view.show()
        marks, _pill, _ink = view.model().data(view.model().index(1, 0),
                                               DECOR_ROLE)
        assert marks[0].spark is not None


def test_the_rules_box_does_not_mark_a_spark_as_a_mistake():
    from flograph.core.text_assist import lint_table_rules
    assert lint_table_rules("trend spark area last from jan..apr") == []


def test_a_matrix_keeps_a_spark_and_its_months_can_be_read():
    from flograph.core.matrix import build_matrix
    long = pd.DataFrame({
        "region": ["N", "N", "S", "S"],
        "month": ["jan", "feb", "jan", "feb"],
        "sales": [1, 3, 2, 1],
    })
    matrix = build_matrix(long, ["region"], ["month"], ["sales"],
                          style=style_payload(
                              {"format_rules": "trend spark from *"}))
    rules = rules_from_style(matrix.style)
    frame, rules, _h = spark_projection(matrix.frame, rules)
    assert rules[0].series == ["jan", "feb"]
    assert frame["trend"].tolist() == [3.0, 1.0]
