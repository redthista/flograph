"""The Chart rules language (core/chart_rules.py) and the three Plotly
nodes' Chart rules box.

Two halves, as the table's formatting rules have: the language reads a line
into a Rule, and a Rule lands on a figure. The bargain throughout is that a
line nobody can read is *reported and skipped* — never an error that stops
the chart drawing.
"""
import pandas as pd
import pytest

from flograph.core import NodeRegistry, chart_rules, compile_run
from tests.conftest import FakeContext

px = pytest.importorskip("plotly.express")

SHOW = "flograph.viz.show_plotly"
PER_VALUE = "flograph.viz.chart_per_value_plotly"
STYLE = "flograph.viz.plotly_style"


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def table():
    return pd.DataFrame({
        "month": ["Jan", "Feb", "Mar"] * 2,
        "line": ["A"] * 3 + ["B"] * 3,
        "units": [10, 20, 30, 5, 8, 11],
        "margin": [0.1, 0.2, 0.3, 0.15, 0.25, 0.35],
    })


@pytest.fixture
def history():
    return pd.DataFrame({"month": ["Jan", "Feb", "Mar"], "units": [12, 18, 26]})


def one(text):
    rules, problems = chart_rules.parse(text)
    assert not problems, problems
    assert len(rules) == 1
    return rules[0]


def chart(registry, params, table, compare=None, type_id=SHOW):
    spec = registry.get(type_id)
    values = spec.default_params()
    if type_id == PER_VALUE:
        values.update(split_by="line", x="month", y="units")
    else:
        values.update(kind="bar", x="month", y="units")
    values.update(params)
    ctx = FakeContext(params=values)
    out = compile_run(spec.source, "t")(ctx, table=table, compare=compare)
    figure = out["figure"] if type_id == SHOW else out["figures"][0]
    return figure, ctx


def traces(figure):
    return {trace.name: trace for trace in figure.data}


class TestReadingALine:
    def test_blanks_and_comments_are_not_rules(self):
        rules, problems = chart_rules.parse("\n# just a note\n   \n")
        assert not rules and not problems

    def test_a_trailing_comment_is_dropped_but_a_hex_colour_is_not(self):
        rule = one('series total line #ef4444   # the total')
        assert rule.opts["colour"] == "#ef4444"

    def test_an_unknown_verb_is_named_and_skipped(self):
        rules, problems = chart_rules.parse("legend bottom\nwibble x\n")
        assert len(rules) == 1
        assert "'wibble' is not a chart rule" in problems[0]
        assert "line 2" in problems[0]

    def test_a_word_the_verb_does_not_know_is_named(self):
        _, problems = chart_rules.parse("legend sideways")
        assert "legend does not understand 'sideways'" in problems[0]

    def test_parse_rule_lines_keeps_every_line_for_the_wizard(self):
        lines = chart_rules.parse_rule_lines("legend bottom\n# note\nwibble")
        assert [bool(rule) for _, rule, _ in lines] == [True, False, False]
        assert lines[2][2]

    def test_lint_is_the_line_numbers_and_why(self):
        assert chart_rules.lint("legend bottom\nwibble") == [
            (2, chart_rules.lint("legend bottom\nwibble")[0][1])]


class TestSeriesGrammar:
    def test_a_column(self):
        rule = one("series margin")
        assert rule.opts["column"] == "margin"
        assert rule.opts["style"] == "line" and rule.opts["axis"] == "left"

    def test_an_aggregate_with_how_where_and_a_label(self):
        rule = one('series total from compare dashed grey right thick '
                   'as "Last year"')
        assert rule.opts["aggregate"] == "total"
        assert rule.opts["source"] == "compare"
        assert rule.opts["style"] == "dashed"
        assert rule.opts["colour"] == "#6b7280"
        assert rule.opts["axis"] == "right"
        assert rule.opts["width"] == 3
        assert rule.opts["label"] == "Last year"

    def test_named_columns_to_total(self):
        rule = one("series total of units, margin line")
        assert rule.opts["columns"] == ["units", "margin"]
        assert rule.opts["style"] == "line"

    def test_series_wants_something_to_plot(self):
        _, problems = chart_rules.parse("series")
        assert "series wants something to plot" in problems[0]


class TestOtherGrammar:
    def test_axis_takes_several_settings_at_once(self):
        rule = one('axis y title "Units" format ,.0f grid off range 0 100 log')
        assert rule.opts["title"] == "Units"
        assert rule.opts["format"] == ",.0f"
        assert rule.opts["grid"] is False
        assert rule.opts["range"] == [0.0, 100.0]
        assert rule.opts["log"] is True

    def test_axis_hide_is_the_whole_axis_its_title_or_its_ticks(self):
        assert one("axis x hide").opts["hide"] is True
        assert one("axis x hide title").opts["hide_title"] is True
        assert one("axis x hide ticks").opts["hide_ticks"] is True

    def test_axis_wants_a_real_axis(self):
        _, problems = chart_rules.parse("axis z hide")
        assert "axis wants x, y or y2" in problems[0]

    def test_a_two_word_legend_position(self):
        assert one("legend inside top right").opts["position"] == \
            "inside top right"

    def test_legend_border_takes_a_width_after_the_colour(self):
        rule = one("legend border #ccc 2")
        assert rule.opts["border"] == "#ccc"
        assert rule.opts["border_width"] == 2.0

    def test_title_note_and_reference_line(self):
        assert one('title "Sales" center').opts == {"text": "Sales",
                                                    "align": "center"}
        assert one('note "Draft" bottom right').opts["position"] == \
            "bottom right"
        rule = one('line at 100 on x dotted red label "Target"')
        assert rule.opts == {"axis": "x", "dash": "dot", "at": 100.0,
                             "colour": "#ef4444", "label": "Target"}

    def test_font_reads_family_size_and_colour_in_any_order(self):
        assert one("font 14 crimson Georgia").opts == {
            "size": 14.0, "colour": "crimson", "family": "Georgia"}

    def test_the_json_escape_hatches(self):
        assert one('layout {"bargap": 0.3}').opts["json"] == {"bargap": 0.3}
        _, problems = chart_rules.parse("traces {nope}")
        assert "traces is not valid JSON" in problems[0]
        _, problems = chart_rules.parse("config [1]")
        assert "wants a JSON object" in problems[0]


class TestOnAChart:
    def test_a_total_line_over_stacked_bars(self, registry, table):
        figure, ctx = chart(registry, {
            "color": "line", "barmode": "stack", "summarise": "sum",
            "chart_rules": 'series total line thick blue as "Total"'},
            table)
        total = traces(figure)["Total"]
        assert list(total.y) == [15, 28, 41]
        assert list(total.x) == ["Jan", "Feb", "Mar"]
        assert total.line.color == "#3b82f6" and total.line.width == 3

    def test_a_historic_total_from_the_compare_input(self, registry, table,
                                                     history):
        figure, _ = chart(registry, {
            "chart_rules": 'series total from compare dashed grey '
                           'as "Last year"'}, table, compare=history)
        last = traces(figure)["Last year"]
        assert list(last.y) == [12, 18, 26]
        assert last.line.dash == "dash"

    def test_from_compare_without_the_input_is_reported_not_raised(
            self, registry, table):
        figure, ctx = chart(registry, {
            "chart_rules": "series total from compare line"}, table)
        assert figure.data                       # the bars still drew
        assert any("compare input" in line for line in ctx.logs)

    def test_a_second_axis_is_made_and_titled(self, registry, table):
        figure, _ = chart(registry, {
            "chart_rules": 'series margin right dotted amber as "Margin"\n'
                           'axis y2 title "Margin" format .0%'}, table)
        assert traces(figure)["Margin"].yaxis == "y2"
        assert figure.layout.yaxis2.overlaying == "y"
        assert figure.layout.yaxis2.side == "right"
        assert figure.layout.yaxis2.title.text == "Margin"
        assert figure.layout.yaxis2.tickformat == ".0%"

    def test_axis_y_leaves_the_second_axis_alone(self, registry, table):
        figure, _ = chart(registry, {
            "chart_rules": 'series margin right line as "Margin"\n'
                           'axis y2 title "Margin"\n'
                           'axis y title "Units"'}, table)
        assert figure.layout.yaxis.title.text == "Units"
        assert figure.layout.yaxis2.title.text == "Margin"

    def test_a_column_summarised_away_is_taken_from_the_raw_rows(
            self, registry, table):
        figure, ctx = chart(registry, {
            "summarise": "sum", "color": "line",
            "chart_rules": 'series margin right line as "Margin"'}, table)
        assert list(traces(figure)["Margin"].y) == pytest.approx(
            [0.25, 0.45, 0.65])

    def test_styling_rules_reach_the_figure(self, registry, table):
        figure, _ = chart(registry, {
            "chart_rules": 'title "Units by month" center\n'
                           'legend bottom horizontal\n'
                           'axis x hide title\n'
                           'line at 25 dashed red label "Target"\n'
                           'note "draft" bottom right\n'
                           'background plot #ffffff\n'
                           'layout {"bargap": 0.4}'}, table)
        assert figure.layout.title.text == "Units by month"
        assert figure.layout.title.x == 0.5
        assert figure.layout.legend.orientation == "h"
        assert figure.layout.xaxis.title.text == ""
        assert len(figure.layout.shapes) == 1            # the reference line
        assert [a.text for a in figure.layout.annotations] == ["Target",
                                                               "draft"]
        assert figure.layout.plot_bgcolor == "#ffffff"
        assert figure.layout.bargap == 0.4

    def test_a_rule_wins_over_the_settings_row(self, registry, table):
        figure, _ = chart(registry, {
            "title": "From the box", "chart_rules": 'title "From a rule"'},
            table)
        assert figure.layout.title.text == "From a rule"

    def test_a_missing_column_is_logged_and_the_chart_still_draws(
            self, registry, table):
        figure, ctx = chart(registry, {
            "chart_rules": "series ghost line\nlegend bottom"}, table)
        assert figure.data
        assert figure.layout.legend.orientation == "h"   # the good line ran
        assert any("ghost" in line for line in ctx.logs)

    def test_bad_lines_never_stop_the_chart(self, registry, table):
        figure, ctx = chart(registry, {
            "chart_rules": "wibble\naxis y title\nseries"}, table)
        assert figure.data
        assert sum("chart rule skipped" in line for line in ctx.logs) == 3


class TestOnEveryNode:
    def test_chart_per_value_draws_the_rules_on_each_panel(
            self, registry, table, history):
        spec = registry.get(PER_VALUE)
        values = spec.default_params()
        values.update(split_by="line", x="month", y="units",
                      chart_rules='series total line as "Total"\n'
                                  'series total from compare dotted '
                                  'as "Last year"')
        ctx = FakeContext(params=values)
        out = compile_run(spec.source, "t")(ctx, table=table, compare=history)
        assert len(out["figures"]) == 2
        for figure, expected in zip(out["figures"], ([10, 20, 30], [5, 8, 11])):
            assert list(traces(figure)["Total"].y) == expected
            # the compare table has no split column, so each panel gets it whole
            assert list(traces(figure)["Last year"].y) == [12, 18, 26]

    def test_chart_per_value_cuts_a_compare_table_that_splits(
            self, registry, table):
        compare = table.assign(units=table["units"] * 2)
        spec = registry.get(PER_VALUE)
        values = spec.default_params()
        values.update(split_by="line", x="month", y="units",
                      chart_rules='series total from compare line as "Was"')
        out = compile_run(spec.source, "t")(
            FakeContext(params=values), table=table, compare=compare)
        assert list(traces(out["figures"][0])["Was"].y) == [20, 40, 60]

    def test_plotly_style_applies_the_same_language(self, registry, table):
        figure = px.bar(table, x="month", y="units")
        spec = registry.get(STYLE)
        values = spec.default_params()
        values.update(chart_rules='legend bottom\naxis y title "Units"')
        out = compile_run(spec.source, "t")(
            FakeContext(params=values), figure=figure)
        assert out["figure"].layout.legend.orientation == "h"
        assert out["figure"].layout.yaxis.title.text == "Units"

    def test_a_series_on_plotly_style_says_where_it_belongs(self, registry,
                                                            table):
        figure = px.bar(table, x="month", y="units")
        spec = registry.get(STYLE)
        values = spec.default_params()
        values.update(chart_rules="series total line")
        ctx = FakeContext(params=values)
        out = compile_run(spec.source, "t")(ctx, figure=figure)
        assert len(out["figure"].data) == 1
        assert any("rather than on Plotly Style" in line for line in ctx.logs)

    def test_a_style_carries_its_rules_down_a_chain(self, registry, table):
        spec = registry.get(STYLE)
        first = spec.default_params()
        first.update(chart_rules='axis y title "Units"')
        upstream = compile_run(spec.source, "t")(FakeContext(params=first))
        second = spec.default_params()
        second.update(chart_rules="legend bottom")
        out = compile_run(spec.source, "t")(
            FakeContext(params=second), figure=px.bar(table, x="month",
                                                     y="units"),
            style=upstream["style"])
        assert out["figure"].layout.yaxis.title.text == "Units"
        assert out["figure"].layout.legend.orientation == "h"

    def test_the_box_is_on_all_three_nodes_with_completion_and_lint(
            self, registry):
        from flograph.core.text_assist import assist_for

        for type_id in (SHOW, PER_VALUE, STYLE):
            assert registry.get(type_id).param("chart_rules") is not None
            assist = assist_for(type_id, "chart_rules")
            assert "series" in assist.keywords
            assert assist.lint("wibble")

    def test_the_compare_input_is_optional_on_both_chart_nodes(self, registry,
                                                              table):
        for type_id in (SHOW, PER_VALUE):
            port = registry.get(type_id).input("compare")
            assert port is not None and port.optional
        # and a chart with nothing wired into it still runs
        figure, _ = chart(registry, {}, table)
        assert figure.data


class TestTheWizard:
    """The Chart Rules… dialog writes the same language it reads."""

    def _form(self, qtbot, line=""):
        from flograph.ui.properties.chart_rule_wizard import _RuleForm

        form = _RuleForm(line, ["month", "units", "margin"])
        qtbot.addWidget(form)
        return form

    def test_a_form_builds_a_series_line(self, qtbot):
        form = self._form(qtbot)
        form._verb.setCurrentIndex(form._verb.findData("series"))
        form._set("what", "total")
        form._set("source", "compare")
        form._set("style", "dashed")
        form._set("colour", "grey")
        form._set("label", "Last year")
        assert form.line() == 'series total from compare dashed grey ' \
                              'as "Last year"'
        # the left axis is the default, so it is not written into the line
        form._set("axis", "left")
        assert " left " not in form.line()

    def test_a_field_left_alone_adds_no_word(self, qtbot):
        form = self._form(qtbot)
        form._verb.setCurrentIndex(form._verb.findData("axis"))
        form._set("axis", "y")
        form._set("title", "Units")
        assert form.line() == 'axis y title "Units"'

    def test_an_existing_line_is_read_back_into_the_form(self, qtbot):
        form = self._form(qtbot, 'axis y hide ticks format ,.0f grid off')
        assert form._verb.currentData() == "axis"
        assert form._value("hide") == "ticks"
        assert form._value("format") == ",.0f"
        assert form._value("grid") == "off"
        # and it writes the line it read
        assert form.line() == 'axis y hide ticks format ,.0f grid off'

    def test_a_reference_line_round_trips(self, qtbot):
        form = self._form(qtbot, 'line at 100 on y dashed red label "Target"')
        assert form._verb.currentData() == "line"
        # a colour name is resolved as it is read, so the line comes back
        # saying the colour red *means* rather than the word
        assert form.line() == ('line at 100.0 on y dashed #ef4444 '
                               'label "Target"')

    def test_the_preview_shows_why_a_rule_is_wrong(self, qtbot):
        form = self._form(qtbot)
        form._verb.setCurrentIndex(form._verb.findData("margin"))
        form._set("left", "10")
        form._refresh_preview()
        assert "Fill the form in" in form._preview.text()

    def test_the_manager_lists_edits_and_reorders(self, qtbot):
        from flograph.ui.properties.chart_rule_wizard import ChartRuleManager

        dialog = ChartRuleManager('legend bottom\n# a note\nwibble x',
                                  ["month"])
        qtbot.addWidget(dialog)
        assert dialog._list.count() == 3
        assert dialog._list.item(2).text().startswith("\N{WARNING SIGN}")
        assert "not a chart rule" in dialog._list.item(2).toolTip()
        dialog._list.setCurrentRow(0)
        dialog._move(1)
        assert dialog.result_text().splitlines()[:2] == ["# a note",
                                                         "legend bottom"]
        dialog._remove()
        assert "legend bottom" not in dialog.result_text()

    def test_the_box_offers_the_wizard_on_every_plotly_node(self, registry):
        for type_id in (SHOW, PER_VALUE, STYLE):
            assert registry.get(type_id).param("chart_rules").wizard == "chart"
