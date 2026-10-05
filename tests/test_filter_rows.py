"""Filter Rows: Text match mode, the rejected-port switch, and the hint for a
bad pattern in a Query."""
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
    params = {"mode": "Text match", "column": "product name",
              "match": match, "text": value, **extra}
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
        out = run_node(registry, TYPE, {"mode": "Text match", "column": "qty",
                                        "match": "equals", "text": "3"},
                       table=fruit)
        assert out["filtered"]["qty"].tolist() == [3.0]

    def test_empty_text_keeps_everything(self, registry, fruit):
        assert len(text(registry, fruit, "contains", "")["filtered"]) == 6

    def test_unknown_column_says_so(self, registry, fruit):
        with pytest.raises(ValueError, match="No column named 'nope'"):
            run_node(registry, TYPE, {"mode": "Text match", "column": "nope",
                                      "text": "x"}, table=fruit)


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
    def test_still_the_default(self, registry, fruit):
        out = run_node(registry, TYPE, {"query": "qty > 4"}, table=fruit)
        assert len(out["filtered"]) == 2 and len(out["rejected"]) == 4

    def test_a_bad_pattern_gets_a_hint(self, registry, fruit):
        with pytest.raises(ValueError, match="Text match"):
            run_node(registry, TYPE, {
                "query": "`product name`.str.contains('*apple*')"},
                table=fruit)
