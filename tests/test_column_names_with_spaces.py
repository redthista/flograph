"""Column names with spaces in them, in the Transform nodes that read names
out of typed text — and Conditional Column's `and` / `or`."""
import pandas as pd
import pytest

from flograph.core import compile_run
from flograph.core.column_refs import (as_typed, backticked, quote_bare_columns,
                                       split_assignment, split_keyword)
from tests.conftest import FakeContext


def run_node(registry, type_id, params=None, **inputs):
    spec = registry.get(type_id)
    values = spec.default_params()
    values.update(params or {})
    return compile_run(spec.source, f"test-{type_id}")(
        FakeContext(params=values), **inputs)


@pytest.fixture
def prices():
    return pd.DataFrame({"unit price": [1.0, 2.0, 3.0],
                         "qty": [3, 4, 5],
                         "name": ["a", "unit price", "c"]})


class TestHelpers:
    def test_an_assignment_splits_at_its_own_equals(self):
        assert split_assignment("`line total` = `unit price` * qty") == (
            "line total", "`unit price` * qty")
        assert split_assignment("flag = a == b") == ("flag", "a == b")
        assert split_assignment("x = 'a=b'") == ("x", "'a=b'")

    def test_a_comparison_is_not_an_assignment(self):
        assert split_assignment("a >= b") is None
        assert split_assignment("a == b") is None

    def test_bare_names_with_spaces_get_backticks(self):
        assert quote_bare_columns(
            "unit price * qty > 5 and name == 'unit price'",
            ["unit price", "qty", "name"]) == (
            "`unit price` * qty > 5 and name == 'unit price'")

    def test_the_longest_name_wins(self):
        assert quote_bare_columns(
            "unit price usd + unit price",
            ["unit price", "unit price usd"]) == (
            "`unit price usd` + `unit price`")

    def test_already_backticked_and_longer_words_are_left(self):
        assert quote_bare_columns("`unit price` + unit prices",
                                  ["unit price"]) == "`unit price` + unit prices"

    def test_backticked_only_when_needed(self):
        assert backticked("qty") == "qty"
        assert backticked("price($)") == "`price($)`"
        assert backticked("class") == "`class`"

    def test_the_picker_types_names_bare_where_they_can_be(self):
        assert as_typed("qty") == "qty"
        assert as_typed("unit price") == "unit price"
        assert as_typed("price ($)") == "price ($)"
        assert as_typed("price($)") == "`price($)`"
        assert as_typed("class") == "`class`"

    def test_and_splits_outside_quotes_only(self):
        assert split_keyword("a = 'x and y' AND b = 2", "and") == [
            "a = 'x and y'", "b = 2"]


class TestExpression:
    TYPE = "flograph.transform.expression"

    def test_a_backticked_target_is_named_as_written(self, registry, prices):
        """pandas names it BACKTICK_QUOTED_STRING_line_total."""
        out = run_node(registry, self.TYPE,
                       {"expressions": "`line total` = `unit price` * qty"},
                       table=prices)
        assert out["line total"].tolist() == [3.0, 8.0, 15.0]
        assert not any("BACKTICK" in c for c in out.columns)

    def test_names_with_spaces_can_go_bare(self, registry, prices):
        out = run_node(registry, self.TYPE,
                       {"expressions": "line total = unit price * qty\n"
                                       "double = line total * 2"},
                       table=prices)
        assert out["double"].tolist() == [6.0, 16.0, 30.0]

    def test_a_comparison_on_the_right_is_kept(self, registry, prices):
        out = run_node(registry, self.TYPE,
                       {"expressions": "big = qty >= 4"}, table=prices)
        assert out["big"].tolist() == [False, True, True]

    def test_every_placeholder_example_runs(self, registry):
        """The placeholder is the node's instructions; each line of it has
        to work as shown."""
        spec = registry.get(self.TYPE)
        example = next(p for p in spec.params
                       if p.name == "expressions").placeholder
        df = pd.DataFrame({"revenue": [100.0, 250.0], "cost": [60.0, 300.0],
                           "unit price": [2.5, 4.0], "qty": [10, 200],
                           "region": ["North", "South"],
                           "price($)": [1.0, 2.0]})
        out = run_node(registry, self.TYPE, {"expressions": example}, table=df)
        assert out["line total"].tolist() == [25.0, 800.0]
        assert out["north"].tolist() == [True, False]
        assert out["gap"].tolist() == [40.0, 50.0]
        assert out["euros"].tolist() == pytest.approx([0.92, 1.84])

    def test_a_line_that_assigns_nothing_says_so(self, registry, prices):
        with pytest.raises(ValueError, match="new_column = expression"):
            run_node(registry, self.TYPE, {"expressions": "qty * 2"},
                     table=prices)


class TestFilterRows:
    TYPE = "flograph.transform.filter_rows"

    @pytest.mark.parametrize("query", ["unit price > 1", "`unit price` > 1"])
    def test_bare_or_backticked(self, registry, prices, query):
        out = run_node(registry, self.TYPE, {"query": query}, table=prices)
        assert out["filtered"]["qty"].tolist() == [4, 5]

    def test_a_name_inside_a_string_stays_a_string(self, registry, prices):
        out = run_node(registry, self.TYPE, {"query": "name == 'unit price'"},
                       table=prices)
        assert out["filtered"]["qty"].tolist() == [4]


class TestConditionalColumn:
    TYPE = "flograph.transform.conditional_column"

    def _run(self, registry, df, rules):
        return run_node(registry, self.TYPE,
                        {"output_column": "out", "rules": rules},
                        table=df)["out"].tolist()

    def test_and(self, registry):
        df = pd.DataFrame({"region": ["North", "North", "South"],
                           "units": [150, 50, 150]})
        assert self._run(registry, df,
                         "region = North and units >= 100 => big\n=> small") \
            == ["big", "small", "small"]

    def test_or(self, registry):
        df = pd.DataFrame({"status": ["open", "pending", "closed"]})
        assert self._run(registry, df,
                         "status = open OR status = pending => live\n=> done") \
            == ["live", "live", "done"]

    def test_a_bare_value_repeats_the_column_and_operator(self, registry):
        df = pd.DataFrame({"status": ["open", "pending", "closed"]})
        assert self._run(registry, df,
                         "status = open or pending => live\n=> done") \
            == ["live", "live", "done"]

    def test_a_missing_column_repeats_the_last_one(self, registry):
        df = pd.DataFrame({"score": [40, 60, 90]})
        assert self._run(registry, df, "score > 50 and < 80 => middle\n=> -") \
            == ["-", "middle", "-"]

    def test_and_binds_tighter_than_or(self, registry):
        df = pd.DataFrame({"a": [1, 1, 0, 0], "b": [1, 0, 0, 0],
                           "c": [0, 0, 1, 0]})
        assert self._run(registry, df, "a = 1 and b = 1 or c = 1 => yes\n=> no") \
            == ["yes", "no", "yes", "no"]

    def test_a_quoted_value_keeps_its_and(self, registry):
        df = pd.DataFrame({"name": ["Tom and Jerry", "Tom"]})
        assert self._run(registry, df,
                         'name = "Tom and Jerry" => cartoon\n=> -') \
            == ["cartoon", "-"]

    def test_a_quoted_number_compares_as_text(self, registry):
        df = pd.DataFrame({"code": ["007", "7"]})
        assert self._run(registry, df, 'code = "007" => bond\n=> -') \
            == ["bond", "-"]
        assert self._run(registry, df, "code = 007 => bond\n=> -") \
            == ["bond", "bond"]

    def test_columns_with_spaces_bare_or_backticked(self, registry):
        df = pd.DataFrame({"unit price": [1, 9], "Profit and Loss": [-1, 5]})
        assert self._run(registry, df,
                         "unit price > 5 and Profit and Loss >= 0 => good\n=> -") \
            == ["-", "good"]
        assert self._run(registry, df,
                         "`unit price` > 5 or `Profit and Loss` < 0 => flag\n"
                         "=> -") == ["flag", "flag"]

    def test_a_result_column_in_backticks(self, registry):
        df = pd.DataFrame({"unit price": [1, 9]})
        assert self._run(registry, df, "`unit price` > 5 => @`unit price`\n=> 0") \
            == [0, 9]

    def test_a_missing_text_value_is_no_match(self, registry):
        df = pd.DataFrame({"region": pd.Series([None, "North"], dtype="string")})
        assert self._run(registry, df, "region = North => n\n=> -") == ["-", "n"]

    def test_junk_after_a_backticked_column(self, registry):
        df = pd.DataFrame({"unit price": [1]})
        with pytest.raises(ValueError, match="operator straight after"):
            self._run(registry, df, "`unit price` extra > 5 => x")


class TestDataQualityGate:
    TYPE = "flograph.transform.data_quality_gate"

    @pytest.mark.parametrize("rule", ["unit price >= 2", "`unit price` >= 2"])
    def test_a_column_with_spaces(self, registry, prices, rule):
        out = run_node(registry, self.TYPE, {"rules": rule}, table=prices)
        assert out["report"]["column"].tolist() == ["unit price"]
        assert out["report"]["violations"].tolist() == [1]


class TestRenameColumns:
    def test_backticked_names(self, registry, prices):
        out = run_node(registry, "flograph.transform.rename_columns",
                       {"mapping": "`unit price` = `price each`"}, table=prices)
        assert "price each" in out.columns
