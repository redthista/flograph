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


@pytest.fixture
def regions():
    return pd.DataFrame({"region": ["North", "south", "East", "West", None],
                         "units": [10, 20, 30, 40, 50]})


class TestOneOf:
    @pytest.mark.parametrize("value", ["North, South", "north\nSOUTH\n"])
    def test_commas_or_lines(self, registry, regions, value):
        out = cond(registry, regions, "region", "is one of", value)
        assert out["units"].tolist() == [10, 20]

    def test_not_one_of_keeps_blanks(self, registry, regions):
        out = cond(registry, regions, "region", "is not one of", "North,South")
        assert out["units"].tolist() == [30, 40, 50]

    def test_numbers(self, registry, regions):
        assert cond(registry, regions, "units", "is one of",
                    "20, 40")["units"].tolist() == [20, 40]

    def test_wildcards(self, registry, regions):
        assert cond(registry, regions, "region", "is one of",
                    "n*, *st")["units"].tolist() == [10, 30, 40]

    def test_a_wired_list(self, registry, regions):
        out = run_node(registry, TYPE, {"column": "region",
                                        "match": "is one of"},
                       table=regions, value=["East", "West"])
        assert out["filtered"]["units"].tolist() == [30, 40]


    def test_a_wired_table_uses_its_matching_column(self, registry, regions):
        other = pd.DataFrame({"region": ["West", "North", "West"],
                              "x": [1, 2, 3]})
        out = run_node(registry, TYPE, {"column": "region",
                                        "match": "is one of"},
                       table=regions, value=other)
        assert out["filtered"]["units"].tolist() == [10, 40]

    def test_a_wired_one_column_table_or_series(self, registry, regions):
        for wired in (pd.DataFrame({"name": ["East"]}),
                      pd.Series(["East", None])):
            out = run_node(registry, TYPE, {"column": "region",
                                            "match": "is one of"},
                           table=regions, value=wired)
            assert out["filtered"]["units"].tolist() == [30]

    def test_a_wired_table_with_no_matching_column(self, registry, regions):
        with pytest.raises(ValueError, match="needs a column named"):
            run_node(registry, TYPE, {"column": "region",
                                      "match": "is one of"}, table=regions,
                     value=pd.DataFrame({"a": [1], "b": [2]}))


class TestBetween:
    def test_numbers_both_ends_included(self, registry, regions):
        assert cond(registry, regions, "units", "between", "20",
                    value_to="40")["units"].tolist() == [20, 30, 40]

    def test_dates_include_the_whole_last_day(self, registry):
        df = pd.DataFrame({"when": pd.to_datetime(
            ["2026-09-30 23:00", "2026-10-01", "2026-10-31 18:00",
             "2026-11-01"], format="mixed")})
        out = cond(registry, df, "when", "between", "01/10/2026",
                   value_to="2026-10-31")
        assert len(out) == 2

    def test_needs_both_ends(self, registry, regions):
        with pytest.raises(ValueError, match="both ends"):
            cond(registry, regions, "units", "between", "20")

    def test_wired_from_a_between_slider(self, registry, regions):
        out = run_node(registry, TYPE, {"column": "units",
                                        "match": "between"},
                       table=regions, value=15, value_to=35.0)
        assert out["filtered"]["units"].tolist() == [20, 30]


class TestPattern:
    def test_a_regex(self, registry, regions):
        assert cond(registry, regions, "region", "matches pattern (regex)",
                    "^(n|s)")["units"].tolist() == [10, 20]

    def test_a_bad_regex_says_so(self, registry, regions):
        with pytest.raises(ValueError, match="isn't a valid pattern"):
            cond(registry, regions, "region", "matches pattern (regex)", "*x")


class TestRelativeDates:
    @pytest.fixture
    def df(self):
        today = pd.Timestamp.now().normalize()
        days = [-40, -8, -7, -6, -1, 0, 1]
        return pd.DataFrame({
            "ago": days,
            "when": [today + pd.Timedelta(days=d, hours=9) for d in days],
            "as text": [(today + pd.Timedelta(days=d)).strftime("%d/%m/%Y")
                        for d in days],
        })

    def ago(self, out):
        return out["ago"].tolist()

    def test_today(self, registry, df):
        assert self.ago(cond(registry, df, "when", "equals", "today")) == [0]

    def test_yesterday_and_tomorrow(self, registry, df):
        assert self.ago(cond(registry, df, "when", "equals",
                             "yesterday")) == [-1]
        assert self.ago(cond(registry, df, "when", "equals",
                             "Tomorrow")) == [1]

    def test_today_minus_n(self, registry, df):
        assert self.ago(cond(registry, df, "when", ">= greater than or equal",
                             "today - 7")) == [-7, -6, -1, 0, 1]
        assert self.ago(cond(registry, df, "when", "< less than",
                             "today-1 week")) == [-40, -8]

    def test_last_n_days_includes_today(self, registry, df):
        # the last 7 days: today and the 6 before it
        assert self.ago(cond(registry, df, "when", "equals",
                             "last 7 days")) == [-6, -1, 0]

    def test_equals_on_dates_held_as_text(self, registry, df):
        assert self.ago(cond(registry, df, "as text", "equals",
                             "last 7 days")) == [-6, -1, 0]
        assert self.ago(cond(registry, df, "as text", "equals",
                             "today")) == [0]
        assert self.ago(cond(registry, df, "as text", "does not equal",
                             "today")) == [-40, -8, -7, -6, -1, 1]

    def test_on_dates_held_as_text(self, registry, df):
        assert self.ago(cond(registry, df, "as text", "<= less than or equal",
                             "today")) == [-40, -8, -7, -6, -1, 0]

    def test_this_month_and_year(self, registry):
        today = pd.Timestamp.now().normalize()
        first = today.replace(day=1)
        df = pd.DataFrame({"when": [first - pd.Timedelta(days=1), first,
                                    first + pd.offsets.MonthEnd(0)]})
        assert len(cond(registry, df, "when", "equals", "this month")) == 2
        assert len(cond(registry, df, "when", "equals", "last month")) == 1
        assert len(cond(registry, df, "when", "equals", "this year")) == (
            3 if today.month > 1 else 2)

    def test_a_year_and_a_month(self, registry):
        df = pd.DataFrame({"when": pd.to_datetime(
            ["2025-12-31", "2026-01-01", "2026-10-15", "2027-01-01"])})
        assert len(cond(registry, df, "when", "equals", "2026")) == 2
        assert len(cond(registry, df, "when", "> greater than", "2026")) == 1
        assert len(cond(registry, df, "when", "equals", "2026-10")) == 1

    def test_unknown_words_are_not_dates(self, registry, df):
        with pytest.raises(ValueError, match="isn't a date"):
            cond(registry, df, "when", "> greater than", "today - 3 fortnights")


class TestWiredValue:
    def test_replaces_the_box(self, registry, regions):
        out = run_node(registry, TYPE, {"column": "units",
                                        "match": "> greater than",
                                        "value": "999"},
                       table=regions, value=30)
        assert out["filtered"]["units"].tolist() == [40, 50]

    def test_a_date_control(self, registry):
        import datetime
        df = pd.DataFrame({"when": pd.to_datetime(
            ["2026-10-04", "2026-10-05 15:00", "2026-10-06"], format="mixed")})
        for wired in ("2026-10-05", datetime.date(2026, 10, 5),
                      pd.Timestamp("2026-10-05")):
            out = run_node(registry, TYPE, {"column": "when",
                                            "match": "equals"},
                           table=df, value=wired)
            assert len(out["filtered"]) == 1, wired

    def test_nothing_wired_uses_the_box(self, registry, regions):
        out = run_node(registry, TYPE, {"column": "units", "value": "20",
                                        "match": "equals"},
                       table=regions, value=None)
        assert out["filtered"]["units"].tolist() == [20]


class TestConditionsBox:
    def test_and_or_and_lines(self, registry, regions):
        out = run_node(registry, TYPE, {
            "conditions": "region = north or south or east\nunits >= 20"},
            table=regions)
        assert out["filtered"]["units"].tolist() == [20, 30]

    def test_matches_like_the_dropdowns(self, registry, regions):
        # case-insensitive, wildcards, blanks
        out = run_node(registry, TYPE, {
            "conditions": "region does not contain OR\nregion is not empty"},
            table=regions)
        assert out["filtered"]["units"].tolist() == [20, 30, 40]

    def test_dates_in_the_box(self, registry):
        df = pd.DataFrame({"when": pd.to_datetime(["2026-10-04",
                                                   "2026-10-05 15:00"], format="mixed")})
        out = run_node(registry, TYPE, {"conditions": "when = 2026-10-05"},
                       table=df)
        assert len(out["filtered"]) == 1

    def test_with_the_dropdowns(self, registry, regions):
        out = run_node(registry, TYPE, {
            "column": "units", "match": "< less than", "value": "40",
            "conditions": "region starts with n or ends with t"},
            table=regions)
        assert out["filtered"]["units"].tolist() == [10, 30]

    def test_a_bad_line_says_which(self, registry, regions):
        with pytest.raises(ValueError, match="Conditions line 2"):
            run_node(registry, TYPE, {"conditions": "units > 1\nnonsense"},
                     table=regions)


class TestSharedGrammar:
    def test_does_not_contain_parses(self):
        from flograph.core.conditions import parse_condition
        assert parse_condition("x", "name does not contain a") == [
            [("name", "not contains", "a", False)]]

    def test_conditional_column_gets_it_too(self, registry):
        df = pd.DataFrame({"name": ["apple", "pear"]})
        out = run_node(registry, "flograph.transform.conditional_column",
                       {"output_column": "c",
                        "rules": "name does not contain app => yes\n=> no"},
                       table=df)
        assert out["c"].tolist() == ["no", "yes"]
