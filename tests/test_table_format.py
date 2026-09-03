"""The Qt-free rule model behind the Table Style node."""
import math

import pandas as pd
import pytest

from flograph.core.table_format import (
    CellStyle, Rule, column_stats, evaluate_column, evaluate_rows,
    parse_op_value, parse_rules, parse_rules_lenient, readable_fg,
    rules_from_params, rules_from_style, style_payload, style_report,
    split_rules,
)


class TestParseRules:
    def test_blank_and_comment_lines_are_skipped(self):
        assert parse_rules("\n  \n# a note\n") == []

    def test_scale_preset(self):
        (rule,) = parse_rules("revenue scale red-yellow-green")
        assert rule.mode == "color_scale"
        assert rule.columns == ["revenue"]
        assert rule.low and rule.mid and rule.high

    def test_two_word_column_before_keyword(self):
        (rule,) = parse_rules("unit price bar blue")
        assert rule.mode == "data_bar"
        assert rule.columns == ["unit price"]
        assert rule.color == "#3b6299"

    def test_highlight_cell(self):
        (rule,) = parse_rules("score >= 90 => bg green, bold")
        assert rule.mode == "highlight" and rule.scope == "cell"
        assert rule.op == ">=" and rule.value == 90
        assert rule.bg == "#2e4d33" and rule.bold is True

    def test_text_condition(self):
        (rule,) = parse_rules("status contains fail => bg red")
        assert rule.op == "contains" and rule.value == "fail"

    def test_whole_row_rule(self):
        (rule,) = parse_rules("status = closed => row grey")
        assert rule.scope == "row" and rule.bg == "#3a3d44"

    def test_icons_and_format(self):
        icons, fmt = parse_rules("health icons traffic\namount format $,.0f")
        assert icons.mode == "icons" and icons.icon_set == "traffic"
        assert fmt.mode == "number_format" and fmt.number_spec == "$,.0f"

    def test_unknown_scale_raises_with_line_number(self):
        with pytest.raises(ValueError, match="line 1: unknown scale"):
            parse_rules("revenue scale mauve")

    def test_missing_operator_raises(self):
        with pytest.raises(ValueError, match="no operator"):
            parse_rules("score => bg red")

    def test_bare_keyword_no_column_raises(self):
        with pytest.raises(ValueError, match="line 1"):
            parse_rules("scale green")


class TestParseOpValue:
    @pytest.mark.parametrize("text,op,value", [
        ("> 90", ">", 90),
        (">=90", ">=", 90),
        ("contains fail", "contains", "fail"),
        ("is empty", "empty", None),
        ("between 10 20", "between", [10, 20]),
        ("closed", "=", "closed"),
    ])
    def test_forms(self, text, op, value):
        assert parse_op_value(text) == (op, value)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_op_value("   ")


class TestRulesFromParams:
    def test_structured_scale_then_text_box(self):
        rules, errors = rules_from_params({
            "cf_mode": "colour scale", "cf_columns": "a, b", "cf_scale": "blue",
            "format_rules": "c bar green",
        })
        assert [r.mode for r in rules] == ["color_scale", "data_bar"]
        assert rules[0].columns == ["a", "b"] and errors == []

    def test_structured_highlight_row_scope(self):
        (rules, _errors) = rules_from_params({
            "cf_mode": "highlight", "cf_columns": "status",
            "cf_test": "= closed", "cf_scope": "whole row", "cf_fill": "amber",
        })
        (rule,) = rules
        assert rule.scope == "row" and rule.op == "=" and rule.bg == "#5c4a24"

    def test_off_mode_yields_only_text_rules(self):
        assert rules_from_params({"cf_mode": "off"}) == ([], [])

    def test_bad_text_line_is_collected_not_raised(self):
        rules, errors = rules_from_params({
            "format_rules": "a scale green\nb scale bogus\nc bar blue"})
        assert [r.mode for r in rules] == ["color_scale", "data_bar"]
        assert len(errors) == 1 and "bogus" in errors[0]

    def test_bad_structured_highlight_test_is_collected(self):
        rules, errors = rules_from_params({
            "cf_mode": "highlight", "cf_columns": "x", "cf_test": ""})
        assert rules == [] and errors and "Highlight rule" in errors[0]


class TestStylePayloadAndReport:
    def test_style_payload_shape(self):
        payload = style_payload({"format_rules": "a scale green\nb bad line !"})
        assert isinstance(payload["rules"], list) and len(payload["rules"]) == 1
        assert len(payload["errors"]) == 1

    def test_style_report_carries_parse_errors_and_missing_columns(self):
        payload = style_payload({"format_rules": "known scale green\n?? bogus"})
        df = pd.DataFrame({"other": [1]})
        report = style_report(payload, df)
        assert any("bogus" in m for m in report)
        assert any("known" in m for m in report)   # names a column df lacks

    def test_style_report_clean_style_is_empty(self):
        payload = style_payload({"format_rules": "a scale green"})
        assert style_report(payload, pd.DataFrame({"a": [1]})) == []


def test_parse_rules_lenient_skips_bad_keeps_good():
    rules, errors = parse_rules_lenient("a scale green\nnonsense\nb bar blue")
    assert [r.mode for r in rules] == ["color_scale", "data_bar"]
    assert len(errors) == 1


class TestRulesFromStyle:
    def test_round_trips_dicts(self):
        original = parse_rules("a scale green\nb >= 1 => bg red")
        payload = [r.to_dict() for r in original]
        back = rules_from_style(payload)
        assert [r.mode for r in back] == ["color_scale", "highlight"]
        assert back[1].op == ">=" and back[1].value == 1

    def test_tolerates_junk(self):
        assert rules_from_style("not a list") == []
        assert rules_from_style([{"mode": "bogus"}, 42, None]) == []

    def test_zero_valued_threshold_survives_round_trip(self):
        (rule,) = parse_rules("x = 0 => bg red")
        (back,) = rules_from_style([rule.to_dict()])
        assert back.op == "=" and back.value == 0


class TestEvaluateColumn:
    def test_color_scale_endpoints(self):
        s = pd.Series([0.0, 5.0, 10.0])
        (rule,) = parse_rules("x scale blue")
        stats = column_stats(s)
        styles = evaluate_column(s, [rule], stats)
        assert styles[0].bg == rule.low
        assert styles[2].bg == rule.high
        assert styles[1].bg not in (rule.low, rule.high)

    def test_nan_is_never_styled(self):
        s = pd.Series([1.0, math.nan, 3.0])
        (rule,) = parse_rules("x scale green")
        styles = evaluate_column(s, [rule], column_stats(s))
        assert styles[1] is None

    def test_non_numeric_column_under_numeric_rule_is_all_none(self):
        s = pd.Series(["a", "b", "c"])
        (rule,) = parse_rules("x scale green")
        assert evaluate_column(s, [rule], column_stats(s)) == [None, None, None]

    def test_data_bar_fraction(self):
        s = pd.Series([0.0, 50.0, 100.0])
        (rule,) = parse_rules("x bar blue")
        styles = evaluate_column(s, [rule], column_stats(s))
        assert styles[0].bar == pytest.approx(0.0)
        assert styles[2].bar == pytest.approx(1.0)
        assert styles[1].bar == pytest.approx(0.5)

    def test_data_bar_negative_uses_negative_colour_and_centre_axis(self):
        s = pd.Series([-10.0, 0.0, 10.0])
        (rule,) = parse_rules("x bar blue")
        styles = evaluate_column(s, [rule], column_stats(s))
        assert styles[0].bar_color == "#a4373a" and styles[0].bar == -1.0
        assert styles[2].bar_color == "#3b6299" and styles[2].bar == 1.0
        assert all(st.bar_mode == "center" for st in styles if st)

    def test_data_bar_all_positive_is_left_anchored(self):
        s = pd.Series([10.0, 40.0])
        (rule,) = parse_rules("x bar blue")
        styles = evaluate_column(s, [rule], column_stats(s))
        assert all(st.bar_mode == "left" for st in styles)

    def test_highlight_between(self):
        s = pd.Series([5, 15, 25])
        (rule,) = parse_rules("x between 10 20 => bg blue")
        styles = evaluate_column(s, [rule], column_stats(s))
        assert styles[0] is None and styles[1].bg == "#26415c" and styles[2] is None

    def test_icons_three_tiers(self):
        s = pd.Series(list(range(9)))
        (rule,) = parse_rules("x icons traffic")
        styles = evaluate_column(s, [rule], column_stats(s))
        assert styles[0].icon == "●" and styles[0].icon_color == "#d9534f"
        assert styles[8].icon == "●" and styles[8].icon_color == "#5cb85c"

    def test_icons_reversed(self):
        s = pd.Series(list(range(9)))
        rule = parse_rules("x icons traffic")[0]
        rule.reverse = True
        styles = evaluate_column(s, [rule], column_stats(s))
        assert styles[0].icon_color == "#5cb85c"

    def test_currency_number_format(self):
        s = pd.Series([1234.5])
        (rule,) = parse_rules("x format $,.0f")
        assert evaluate_column(s, [rule], column_stats(s))[0].text == "$1,234"

    def test_number_format_sets_text_only(self):
        s = pd.Series([1234.5, 6789.0])
        (rule,) = parse_rules("x format ,.0f")
        styles = evaluate_column(s, [rule], column_stats(s))
        assert styles[0].text == "1,234" and styles[0].bg is None

    def test_later_rule_wins_on_overlap(self):
        s = pd.Series([100, 100])
        rules = parse_rules("x >= 1 => bg red\nx >= 1 => bg green")
        styles = evaluate_column(s, rules, column_stats(s))
        assert styles[0].bg == "#2e4d33"

    def test_stats_come_from_full_column_not_the_slice(self):
        full = pd.Series([0.0, 100.0])
        stats = column_stats(full)
        # a page showing only the middle value still scales against 0..100
        page = pd.Series([50.0])
        (rule,) = parse_rules("x scale blue")
        styles = evaluate_column(page, [rule], stats)
        assert styles[0].bg not in (rule.low, rule.high)


class TestEvaluateRows:
    def test_whole_row_highlight(self):
        df = pd.DataFrame({"status": ["ok", "closed", "ok"], "n": [1, 2, 3]})
        _, row_rules = split_rules(parse_rules("status = closed => row grey"))
        styles = evaluate_rows(df, row_rules)
        assert styles[0] is None and styles[1].bg == "#3a3d44" and styles[2] is None


def test_readable_fg_light_vs_dark():
    assert readable_fg("#ffffff") == "#1b1c20"
    assert readable_fg("#000000") == "#e5e7eb"
