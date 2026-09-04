"""The Qt-free rule model behind the Table Style node."""
import math

import pandas as pd
import pytest

from flograph.core.table_format import (
    CellStyle, Rule, _column_list, column_matches, column_stats, evaluate_column,
    evaluate_rows, expand_columns, merge_styles, parse_op_value, parse_rules,
    parse_rules_lenient, quote_column, readable_fg, rules_from_style,
    style_payload, style_report, split_rules,
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

    def test_trailing_comment_is_stripped(self):
        (rule,) = parse_rules("revenue scale green   # the money column")
        assert rule.mode == "color_scale" and rule.columns == ["revenue"]

    def test_trailing_comment_keeps_a_hex_colour(self):
        (rule,) = parse_rules("score >= 90 => bg #2e7d46  # pass")
        assert rule.bg == "#2e7d46"

    def test_hash_without_a_following_space_is_not_a_comment(self):
        (rule,) = parse_rules('"col#1" scale green')
        assert rule.columns == ["col#1"]


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


class TestColumnsWithSpaces:
    @pytest.mark.parametrize("text,expected", [
        ("a, b", ["a", "b"]),
        ("unit price", ["unit price"]),
        ('a, "b, c", d', ["a", "b, c", "d"]),
        ('"scale"', ["scale"]),
    ])
    def test_column_list(self, text, expected):
        assert _column_list(text) == expected

    def test_space_column_before_keyword(self):
        (rule,) = parse_rules("gross margin scale green")
        assert rule.columns == ["gross margin"]

    def test_space_column_in_a_condition(self):
        (rule,) = parse_rules("gross margin contains loss => bg amber")
        assert rule.columns == ["gross margin"] and rule.op == "contains"

    def test_quoted_column_disambiguates_a_keyword_name(self):
        (rule,) = parse_rules('"scale" >= 1 => bg red')
        assert rule.columns == ["scale"]

    def test_quoted_iconmap_source(self):
        (rule,) = parse_rules('growth iconmap "service level": ok=+ green')
        assert rule.source == "service level"

    def test_quote_column_only_when_needed(self):
        assert quote_column("revenue") == "revenue"
        assert quote_column("unit price") == '"unit price"'
        assert quote_column("scale") == '"scale"'


class TestMergeStyles:
    def test_extra_layers_on_top_of_base(self):
        base = style_payload({"format_rules": "a scale green"})
        extra = style_payload({"format_rules": "b bar blue"})
        merged = merge_styles(base, extra)
        assert [r["mode"] for r in merged["rules"]] == ["color_scale", "data_bar"]

    def test_hide_lists_union_and_errors_concatenate(self):
        base = style_payload({"format_rules": "hide x\nq bad !"})
        extra = style_payload({"format_rules": "hide y", "hide": "x, z"})
        merged = merge_styles(base, extra)
        assert merged["hide"] == ["x", "y", "z"]
        assert len(merged["errors"]) == 1

    def test_none_and_bare_list_accepted(self):
        assert merge_styles(None, None) == {"rules": [], "hide": [], "errors": []}
        merged = merge_styles([{"mode": "color_scale", "columns": ["a"]}], None)
        assert len(merged["rules"]) == 1


class TestStylePayloadAndReport:
    def test_style_payload_shape(self):
        payload = style_payload({"format_rules": "a scale green\nb bad line !"})
        assert isinstance(payload["rules"], list) and len(payload["rules"]) == 1
        assert len(payload["errors"]) == 1

    def test_hide_param_and_dsl_line_both_feed_hide(self):
        payload = style_payload({"format_rules": "hide fromline",
                                 "hide": "fromparam, fromline"})
        assert payload["hide"] == ["fromline", "fromparam"]

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


class TestIconMap:
    def test_parses_source_and_mapping(self):
        (rule,) = parse_rules(
            "growth iconmap sla: breach=✗ red, ok=✓ green")
        assert rule.mode == "icon_map" and rule.columns == ["growth"]
        assert rule.source == "sla"
        assert rule.mapping["breach"][0] == "✗"
        assert rule.mapping["ok"] == ["✓", "#5cb85c"]   # vivid glyph green

    def test_evaluates_against_another_column(self):
        df = pd.DataFrame({"growth": [0.1, -0.2, 0.3],
                           "sla": ["ok", "breach", "ok"]})
        (rule,) = parse_rules("growth iconmap sla: breach=✗ red, ok=✓ green")
        styles = evaluate_column(df["growth"], [rule], column_stats(df["growth"]),
                                 frame=df)
        assert styles[0].icon == "✓" and styles[1].icon == "✗"
        assert styles[2].icon == "✓"

    def test_composes_with_a_data_bar_on_the_same_column(self):
        df = pd.DataFrame({"g": [1.0, 2.0], "s": ["ok", "bad"]})
        rules = parse_rules("g bar blue\ng iconmap s: bad=! red, ok=. green")
        styles = evaluate_column(df["g"], rules, column_stats(df["g"]), frame=df)
        assert styles[1].bar is not None and styles[1].icon == "!"

    def test_missing_mapping_body_raises(self):
        with pytest.raises(ValueError, match="value=icon"):
            parse_rules("g iconmap s:")


class TestFromAnotherColumn:
    def test_scale_by_clause_sets_source(self):
        (rule,) = parse_rules("product scale green by revenue")
        assert rule.mode == "color_scale" and rule.columns == ["product"]
        assert rule.source == "revenue"

    def test_bar_and_icons_by_clause(self):
        bar, icons = parse_rules("p bar blue by units\np icons traffic by score")
        assert bar.source == "units" and bar.color == "#3b6299"
        assert icons.source == "score" and icons.icon_set == "traffic"

    def test_icons_reverse_and_by_together(self):
        (rule,) = parse_rules("p icons traffic reverse by score")
        assert rule.reverse is True and rule.source == "score"

    def test_by_with_no_preset(self):
        (rule,) = parse_rules("p icons by score")
        assert rule.icon_set == "traffic" and rule.source == "score"

    def test_from_is_an_alias_for_by(self):
        (rule,) = parse_rules('p scale blue from "gross margin"')
        assert rule.source == "gross margin"

    def test_highlight_if_clause_tests_another_column(self):
        (rule,) = parse_rules("product if revenue < 0 => bg red")
        assert rule.mode == "highlight" and rule.columns == ["product"]
        assert rule.source == "revenue" and rule.op == "<" and rule.value == 0

    def test_highlight_when_is_an_alias_and_carries_row_scope(self):
        (rule,) = parse_rules("product if status = closed => row grey")
        assert rule.scope == "row" and rule.source == "status"
        assert rule.columns == ["product"]

    def test_if_inside_a_quoted_value_is_not_a_clause(self):
        (rule,) = parse_rules('notes contains "if only" => bg amber')
        assert rule.op == "contains" and rule.source is None

    def test_scale_decides_on_the_source_column(self):
        df = pd.DataFrame({"product": ["a", "b", "c"], "revenue": [0, 50, 100]})
        (rule,) = parse_rules("product scale blue by revenue")
        styles = evaluate_column(df["product"], [rule],
                                 column_stats(df["product"]), frame=df)
        assert styles[0].bg == rule.low and styles[2].bg == rule.high

    def test_data_bar_sized_by_the_source_column(self):
        df = pd.DataFrame({"product": ["a", "b"], "units": [10.0, 40.0]})
        (rule,) = parse_rules("product bar blue by units")
        styles = evaluate_column(df["product"], [rule],
                                 column_stats(df["product"]), frame=df)
        assert styles[1].bar == pytest.approx(1.0)

    def test_highlight_cell_uses_the_if_column(self):
        df = pd.DataFrame({"product": ["a", "b", "c"], "revenue": [5, -1, 9]})
        (rule,) = parse_rules("product if revenue < 0 => bg red")
        styles = evaluate_column(df["product"], [rule],
                                 column_stats(df["product"]), frame=df)
        assert styles[0] is None and styles[1].bg == "#5c2b2b" and styles[2] is None

    def test_whole_row_highlight_tested_on_the_if_column(self):
        df = pd.DataFrame({"product": ["a", "b"], "status": ["ok", "closed"]})
        _, row_rules = split_rules(parse_rules("product if status = closed => row grey"))
        styles = evaluate_rows(df, row_rules)
        assert styles[0] is None and styles[1].bg == "#3a3d44"

    def test_style_report_flags_an_unknown_by_column(self):
        payload = style_payload({"format_rules": "product scale green by nope"})
        report = style_report(payload, pd.DataFrame({"product": ["a"]}))
        assert any("nope" in m for m in report)

    def test_source_round_trips_through_the_style_port(self):
        (rule,) = parse_rules("product bar blue by units")
        (back,) = rules_from_style([rule.to_dict()])
        assert back.source == "units"


class TestWildcardColumns:
    def test_column_matches_exact_and_glob(self):
        assert column_matches(["revenue"], "revenue")
        assert not column_matches(["revenue"], "revenues")
        assert column_matches(["20*"], "2021")
        assert column_matches(["Q?_sales"], "Q3_sales")
        assert not column_matches(["20*"], "sales_2021")
        assert column_matches([], "x") is False

    def test_expand_columns_keeps_plain_drops_unmatched_glob(self):
        cols = ["2019", "2020", "2021", "region"]
        assert expand_columns(["202*"], cols) == ["2020", "2021"]
        assert expand_columns(["20*"], cols) == ["2019", "2020", "2021"]
        assert expand_columns(["region", "no_such"], cols) == ["region", "no_such"]
        assert expand_columns(["*", "region"], cols) == cols  # order + dedup

    def test_glob_is_case_sensitive(self):
        assert not column_matches(["q*"], "Q1")

    def test_parse_keeps_a_glob_as_a_column_entry(self):
        (rule,) = parse_rules("20* scale green")
        assert rule.columns == ["20*"]

    def test_scale_applies_to_every_matching_column(self):
        df = pd.DataFrame({"2020": [0, 10], "2021": [0, 10], "name": ["a", "b"]})
        (rule,) = parse_rules("20* scale blue")
        for col in ("2020", "2021"):
            styles = evaluate_column(df[col], [rule], column_stats(df[col]))
            assert styles[1].bg == rule.high
        # the rule simply doesn't fire on a non-matching column
        assert not column_matches(rule.columns, "name")

    def test_row_highlight_with_a_glob_tests_the_first_match(self):
        df = pd.DataFrame({"q1_flag": ["ok", "bad"], "q2_flag": ["x", "y"]})
        _, row_rules = split_rules(parse_rules("q?_flag = bad => row red"))
        styles = evaluate_rows(df, row_rules)
        assert styles[0] is None and styles[1].bg == "#5c2b2b"

    def test_style_report_flags_a_glob_that_matches_nothing(self):
        payload = style_payload({"format_rules": "9999_* scale green"})
        report = style_report(payload, pd.DataFrame({"2021": [1]}))
        assert any("matched no column" in m for m in report)

    def test_style_report_is_clean_when_the_glob_matches(self):
        payload = style_payload({"format_rules": "20* bar blue"})
        assert style_report(payload, pd.DataFrame({"2021": [1]})) == []


class TestHide:
    def test_hide_line_becomes_a_hide_rule(self):
        (rule,) = parse_rules("hide helper1, helper2")
        assert rule.mode == "hide" and rule.columns == ["helper1", "helper2"]

    def test_style_payload_separates_hide_from_rules(self):
        payload = style_payload({
            "format_rules": "a scale green\nhide secret\nb bar blue"})
        assert [r["mode"] for r in payload["rules"]] == ["color_scale", "data_bar"]
        assert payload["hide"] == ["secret"]

    def test_hide_with_no_column_is_an_error(self):
        payload = style_payload({"format_rules": "hide"})
        assert payload["hide"] == [] and len(payload["errors"]) == 1


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
