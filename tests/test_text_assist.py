"""The pop-out editor's lint and vocabulary per text box (core/text_assist):
the node's own parser run line by line, and tried against the first rows of
the table coming in when there is one."""
import pandas as pd

from flograph.core.text_assist import (
    TextAssist, assist_for, lint_conditional_column, lint_expression,
    lint_quality_gate, lint_rename, lint_table_rules,
)

SAMPLE = pd.DataFrame({"score": [95, 40], "unit price": [1.0, 2.0],
                       "qty": [1, 2], "region": ["n", "s"]})


def marks(found):
    return [(d.line, d.severity) for d in found]


class TestConditionalColumn:
    def test_good_rules_pass(self):
        assert lint_conditional_column(
            "score >= 90 and region = n => A\nunit price > 1 or qty = 2 => B\n"
            "=> C", SAMPLE) == []

    def test_a_line_with_no_operator(self):
        found = lint_conditional_column("score >= 90 => A\nregion north => x",
                                        SAMPLE)
        assert marks(found) == [(2, "error")]
        assert "no operator" in found[0].message
        # the line is the editor's to show; the node's "rule 2:" is dropped
        assert not found[0].message.startswith("rule")

    def test_an_unknown_column_is_a_warning(self):
        assert marks(lint_conditional_column("scor > 1 => x", SAMPLE)) == [
            (1, "warning")]

    def test_columns_arent_checked_without_a_table(self):
        assert lint_conditional_column("scor > 1 => x", None) == []

    def test_a_rule_after_the_fallback(self):
        found = lint_conditional_column("=> x\nscore > 1 => y", SAMPLE)
        assert marks(found) == [(2, "error")]
        assert "never match" in found[0].message

    def test_a_bad_pattern(self):
        assert marks(lint_conditional_column("region matches ([ => x",
                                             SAMPLE)) == [(1, "error")]

    def test_a_missing_result_column(self):
        assert marks(lint_conditional_column("score > 1 => @nope",
                                             SAMPLE)) == [(1, "warning")]


class TestExpression:
    def test_good_lines_pass(self):
        assert lint_expression("total = unit price * qty\ndouble = total * 2",
                               SAMPLE) == []

    def test_an_unknown_name_against_the_table(self):
        assert marks(lint_expression("x = nope * 2", SAMPLE)) == [(1, "error")]

    def test_a_line_that_assigns_nothing(self):
        found = lint_expression("qty * 2", None)
        assert marks(found) == [(1, "error")]
        assert "new_column = expression" in found[0].message

    def test_a_syntax_error_without_a_table(self):
        assert marks(lint_expression("x = (qty *", None)) == [(1, "error")]

    def test_only_the_names_on_record_still_catch_a_missing_column(self):
        """No rows in memory, just the column names the cache recorded."""
        names_only = SAMPLE.head(0)
        found = lint_expression("x = nope * 2", names_only)
        assert marks(found) == [(1, "warning")]
        assert "nope" in found[0].message
        assert lint_expression(
            "total = unit price * qty\ndouble = abs(total) * 2\n"
            "north = region == 'n'", names_only) == []

    def test_names_with_spaces_pass_without_a_table(self):
        assert lint_expression("total = unit price * qty\nflag = a and b",
                               None) == []


class TestQualityGate:
    def test_good_rules_pass(self):
        assert lint_quality_gate(
            "unit price >= 0\nregion in n | s\nqty between 0 and 9\n@rows >= 1",
            SAMPLE) == []

    def test_an_unknown_check(self):
        found = lint_quality_gate("qty sometimes", SAMPLE)
        assert marks(found) == [(1, "error")]
        assert "unknown check" in found[0].message

    def test_between_needs_two_bounds(self):
        assert marks(lint_quality_gate("qty between 1", SAMPLE)) == [(1, "error")]

    def test_a_bad_pattern(self):
        assert marks(lint_quality_gate("region regex ([", SAMPLE)) == [(1, "error")]

    def test_an_unknown_column_is_a_warning(self):
        assert marks(lint_quality_gate("nope not_null", SAMPLE)) == [(1, "warning")]


class TestRename:
    def test_marks(self):
        found = lint_rename("qty = quantity\nnope = x\nregion = quantity\n"
                            "just words", SAMPLE)
        assert marks(found) == [(2, "warning"), (3, "warning"), (4, "error")]


class TestTableRules:
    def test_a_style_the_rules_dont_have(self):
        found = lint_table_rules("score > 5 => bg green\nscore > 5 => sparkle")
        assert marks(found) == [(2, "error")]
        assert "sparkle" in found[0].message


class TestAssistFor:
    def test_a_known_box(self):
        assist = assist_for("flograph.transform.expression", "expressions")
        assert assist.lint is lint_expression
        assert "sqrt" in assist.keywords

    def test_a_box_with_a_rules_manager_speaks_the_rules_language(self):
        assist = assist_for("flograph.viz.show_table", "rules", rule_wizard=True)
        assert assist.lint is lint_table_rules
        assert "scale" in assist.keywords
        assert assist.quote("unit price") == '"unit price"'

    def test_an_unknown_box_gets_nothing(self):
        assert assist_for("user.thing", "notes") == TextAssist()
