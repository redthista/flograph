"""Filter Rows: Column/Match/Value conditions on text, numbers and dates,
the rejected-port switch, the Advanced query, and the hint for a bad
pattern in one."""
import pandas as pd
import pytest

from tests.test_column_names_with_spaces import run_node

TYPE = "flograph.transform.filter_rows"


@pytest.fixture
def fruit():
    return pd.DataFrame({
        "product name": ["Apple pie", "banana", "pineapple", None,
                         "a*b", "Pear"],
        "qty": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
    })


def text(registry, df, match, value, **extra):
    params = {"column": "product name",
              "match": match, "value": value, **extra}
    return run_node(registry, TYPE, params, table=df)


def names(out, port="filtered"):
    col = out[port]["product name"]
    return col.astype(object).where(col.notna(), None).tolist()


class TestTextMatch:
    def test_contains_ignores_case_by_default(self, registry, fruit):
        assert names(text(registry, fruit, "contains", "apple")) == [
            "Apple pie", "pineapple"]

    def test_match_case(self, registry, fruit):
        out = text(registry, fruit, "contains", "apple", case_sensitive=True)
        assert names(out) == ["pineapple"]

    def test_does_not_contain_keeps_blanks(self, registry, fruit):
        out = text(registry, fruit, "does not contain", "apple")
        assert names(out) == ["banana", None, "a*b", "Pear"]

    @pytest.mark.parametrize("match,value,expected", [
        ("starts with", "pine", ["pineapple"]),
        ("ends with", "PIE", ["Apple pie"]),
        ("equals", "pear", ["Pear"]),
        ("equals", "pea", []),
        ("does not equal", "pear",
         ["Apple pie", "banana", "pineapple", None, "a*b"]),
    ])
    def test_matches(self, registry, fruit, match, value, expected):
        assert names(text(registry, fruit, match, value)) == expected

    def test_star_and_question_are_wildcards(self, registry, fruit):
        assert names(text(registry, fruit, "equals", "*apple*")) == [
            "Apple pie", "pineapple"]
        assert names(text(registry, fruit, "equals", "p?ar")) == ["Pear"]
        # A leading * is what raised "nothing to repeat" in a Query.
        assert names(text(registry, fruit, "contains", "*pie")) == [
            "Apple pie"]

    def test_other_symbols_are_literal(self, registry):
        df = pd.DataFrame({"product name": ["a.b", "axb", "(x)"]})
        assert names(text(registry, df, "contains", "a.b")) == ["a.b"]
        assert names(text(registry, df, "contains", "(")) == ["(x)"]

    def test_numbers_match_as_they_read(self, registry, fruit):
        out = run_node(registry, TYPE, {"column": "qty",
                                        "match": "equals", "value": "3"},
                       table=fruit)
        assert out["filtered"]["qty"].tolist() == [3.0]

    def test_empty_text_keeps_everything(self, registry, fruit):
        assert len(text(registry, fruit, "contains", "")["filtered"]) == 6

    def test_unknown_column_says_so(self, registry, fruit):
        with pytest.raises(ValueError, match="No column named 'nope'"):
            run_node(registry, TYPE, {"column": "nope",
                                      "value": "x"}, table=fruit)


class TestRejected:
    def test_on_by_default(self, registry, fruit):
        out = text(registry, fruit, "contains", "apple")
        assert len(out["rejected"]) == 4

    def test_off_leaves_an_empty_table(self, registry, fruit):
        out = text(registry, fruit, "contains", "apple", keep_rejected=False)
        assert len(out["filtered"]) == 2
        assert out["rejected"].empty
        assert list(out["rejected"].columns) == list(fruit.columns)

    def test_off_in_query_mode(self, registry, fruit):
        out = run_node(registry, TYPE, {"query": "qty > 4",
                                        "keep_rejected": False}, table=fruit)
        assert len(out["filtered"]) == 2 and out["rejected"].empty


class TestQuery:
    def test_a_query_on_its_own_as_before(self, registry, fruit):
        out = run_node(registry, TYPE, {"query": "qty > 4"}, table=fruit)
        assert len(out["filtered"]) == 2 and len(out["rejected"]) == 4

    def test_a_condition_and_a_query_must_both_pass(self, registry, fruit):
        out = text(registry, fruit, "contains", "apple", query="qty > 1")
        assert names(out) == ["pineapple"]
        assert len(out["rejected"]) == 5

    def test_a_bad_pattern_gets_a_hint(self, registry, fruit):
        with pytest.raises(ValueError, match="Column, Match and Value"):
            run_node(registry, TYPE, {
                "query": "`product name`.str.contains('*apple*')"},
                table=fruit)


def cond(registry, df, column, match, value, **extra):
    return run_node(registry, TYPE, {"column": column,
                                     "match": match, "value": value, **extra},
                    table=df)["filtered"]


class TestNumbers:
    @pytest.fixture
    def df(self):
        return pd.DataFrame({"price": [1.5, 5.0, 10.0, None],
                             "as text": ["1.5", "5", "10", "n/a"]})

    @pytest.mark.parametrize("match,value,expected", [
        ("> greater than", "5", [10.0]),
        (">= greater than or equal", "5", [5.0, 10.0]),
        ("< less than", "5", [1.5]),
        ("<= less than or equal", "5", [1.5, 5.0]),
        ("equals", "5", [5.0]),
        ("does not equal", "5", [1.5, 10.0, None]),
    ])
    def test_number_column(self, registry, df, match, value, expected):
        out = cond(registry, df, "price", match, value)["price"]
        assert out.astype(object).where(out.notna(), None).tolist() == expected

    def test_numbers_held_as_text_compare_as_numbers(self, registry, df):
        # As text, "10" < "5"; as numbers it isn't. "n/a" never passes.
        assert cond(registry, df, "as text", "> greater than",
                    "2")["as text"].tolist() == ["5", "10"]

    def test_a_word_against_a_number_column_says_so(self, registry, df):
        with pytest.raises(ValueError, match="isn't a number"):
            cond(registry, df, "price", "> greater than", "lots")


class TestDates:
    @pytest.fixture
    def df(self):
        return pd.DataFrame({
            "when": pd.to_datetime(["2026-10-04 09:00", "2026-10-05 00:00",
                                    "2026-10-05 17:30", "2026-10-06 08:00",
                                    None]),
            "as text": ["2026-10-04", "05/10/2026", "5 Oct 2026 17:30",
                        "06/10/2026", "soon"],
        })

    def days(self, out, col="when"):
        return [str(v)[:16] for v in out[col]]

    def test_after_a_day_is_after_all_of_it(self, registry, df):
        assert self.days(cond(registry, df, "when", "> greater than",
                              "2026-10-05")) == ["2026-10-06 08:00"]

    def test_up_to_a_day_includes_all_of_it(self, registry, df):
        assert len(cond(registry, df, "when", "<= less than or equal",
                        "2026-10-05")) == 3

    def test_equals_a_day_matches_any_time_on_it(self, registry, df):
        assert len(cond(registry, df, "when", "equals", "2026-10-05")) == 2

    def test_a_time_compares_exactly(self, registry, df):
        assert self.days(cond(registry, df, "when", ">= greater than or equal",
                              "2026-10-05 12:00")) == [
            "2026-10-05 17:30", "2026-10-06 08:00"]

    @pytest.mark.parametrize("value", ["2026-10-05", "05/10/2026",
                                       "5 Oct 2026"])
    def test_iso_and_day_first_mean_the_same_day(self, registry, df, value):
        assert len(cond(registry, df, "when", "equals", value)) == 2

    def test_dates_held_as_text(self, registry, df):
        # 05/10/2026 is the 5th of October, not the 10th of May.
        assert cond(registry, df, "as text", ">= greater than or equal",
                    "2026-10-05")["as text"].tolist() == [
            "05/10/2026", "5 Oct 2026 17:30", "06/10/2026"]

    def test_time_zones(self, registry):
        df = pd.DataFrame({"when": pd.to_datetime(
            ["2026-10-04 23:00", "2026-10-05 10:00"]).tz_localize("UTC")})
        assert len(cond(registry, df, "when", ">= greater than or equal",
                        "2026-10-05")) == 1

    def test_not_a_date_says_so(self, registry, df):
        with pytest.raises(ValueError, match="isn't a date"):
            cond(registry, df, "when", "> greater than", "tomorrowish")


class TestBlank:
    @pytest.fixture
    def df(self):
        return pd.DataFrame({
            "name": ["a", "", "   ", None, "b"],
            "price": [1.0, None, 3.0, None, 0.0],
            "when": pd.to_datetime(["2026-10-05", None, "2026-10-06",
                                    None, None]),
        })

    @pytest.mark.parametrize("column,blank", [
        ("name", [1, 2, 3]), ("price", [1, 3]), ("when", [1, 3, 4]),
    ])
    def test_blank_and_not_blank(self, registry, df, column, blank):
        rows = set(range(len(df)))
        assert list(cond(registry, df, column, "is blank", "").index) == blank
        assert list(cond(registry, df, column, "is not blank", "").index) \
            == sorted(rows - set(blank))

    def test_a_value_left_over_is_ignored(self, registry, df):
        assert list(cond(registry, df, "price", "is blank", "5").index) == [1, 3]

    def test_needs_a_column(self, registry, df):
        with pytest.raises(ValueError, match="Pick the column"):
            cond(registry, df, "", "is blank", "")


def test_text_compares_alphabetically(registry):
    df = pd.DataFrame({"name": ["apple", "Banana", "cherry", None]})
    assert cond(registry, df, "name", ">= greater than or equal",
                "b")["name"].tolist() == ["Banana", "cherry"]
