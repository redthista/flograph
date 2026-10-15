"""core.ai_disclosure: what the Flo Assistant may see. The tests that
matter are the leak tests — they dump everything described at a level and
check that what must not leave is nowhere in it."""
import json

import pandas as pd
import pytest

from flograph.core import ai_disclosure as d
from flograph.core.ai_disclosure import ColumnRule, Disclosure, Privacy

SECRET_NAMES = ["Alice Smith", "Bob Jones", "Carol King"]


@pytest.fixture
def table():
    return pd.DataFrame({
        "customer": SECRET_NAMES * 10,
        "email": ["a@x.com", "b@y.org", "c@z.net"] * 10,
        "salary": [51234.5, 62000.0, 70999.25] * 10,
        "region": ["North", "South", "North"] * 10,
        "joined": pd.to_datetime(["2021-01-05", "2022-03-01", "2023-07-19"] * 10),
    })


def _dump(obj) -> str:
    return json.dumps(obj, default=str)


class TestLevels:
    def test_structure_says_only_that_it_is_a_table(self, table):
        out = Disclosure(d.STRUCTURE).describe(table)
        assert out == {"kind": "table"}

    def test_schema_has_names_types_and_shape_no_values(self, table):
        out = Disclosure(d.SCHEMA).describe(table)
        assert out["rows"] == 30 and out["columns_count"] == 5
        assert [(c["name"], c["type"]) for c in out["columns"]] == [
            ("customer", "text"), ("email", "text"), ("salary", "number"),
            ("region", "text"), ("joined", "datetime")]
        dumped = _dump(out)
        for value in SECRET_NAMES + ["North", "51234.5", "a@x.com"]:
            assert value not in dumped

    def test_profile_has_ranges_and_kinds_but_no_text_values(self, table):
        out = Disclosure(d.PROFILE).describe(table)
        cols = {c["name"]: c for c in out["columns"]}
        assert cols["salary"]["min"] == 51234.5 and cols["salary"]["max"] == 70999.25
        assert cols["joined"]["min"].startswith("2021-01-05")
        assert cols["email"]["looks_like"] == "email address"
        assert "categories" in cols["region"]["looks_like"]
        assert cols["customer"]["distinct"] == 3
        assert cols["customer"]["empty_percent"] == 0.0
        dumped = _dump(out)
        for value in SECRET_NAMES + ["North", "South", "a@x.com"]:
            assert value not in dumped

    def test_levels_above_profile_are_not_served_yet(self):
        assert Disclosure(d.ANALYSE).level == d.PROFILE
        assert d.effective_level(5) == d.PROFILE

    def test_effective_level_is_the_lowest(self):
        assert d.effective_level(2, None, None) == 2
        assert d.effective_level(2, 1, None) == 1
        assert d.effective_level(1, 2, 2) == 1     # the flow can't raise it
        assert d.effective_level(2, 2, 0) == 0


class TestColumnRules:
    def test_sensitive_keeps_name_and_type_but_no_values(self, table):
        privacy = Privacy(columns={"salary": ColumnRule(sensitive=True)})
        cols = {c["name"]: c for c in
                Disclosure(d.PROFILE, privacy).describe(table)["columns"]}
        assert cols["salary"]["type"] == "number" and cols["salary"]["sensitive"]
        assert "min" not in cols["salary"] and "max" not in cols["salary"]
        assert "51234" not in _dump(cols["salary"])

    def test_alias_hides_the_name_everywhere(self, table):
        privacy = Privacy(columns={
            "customer": ColumnRule(alias="col_1", hint="person name")})
        disclosure = Disclosure(d.PROFILE, privacy)
        out = disclosure.describe(table)
        assert out["columns"][0]["name"] == "col_1"
        assert out["columns"][0]["hint"] == "person name"
        assert "customer" not in _dump(out)
        assert disclosure.scrub("Group by customer, sum salary") == \
            "Group by col_1, sum salary"

    def test_aliases_come_back_as_real_names(self):
        privacy = Privacy(columns={"customer": ColumnRule(alias="col_1")})
        disclosure = Disclosure(d.SCHEMA, privacy)
        assert disclosure.unalias({"x": "col_1", "cols": ["col_1", "col_10"],
                                   "expr": "col_1 != ''"}) == {
            "x": "customer", "cols": ["customer", "col_10"],
            "expr": "customer != ''"}

    def test_structure_hides_every_known_name(self, table):
        disclosure = Disclosure(d.STRUCTURE)
        disclosure.describe(table)   # learns the names
        assert disclosure.scrub("Bar chart of salary by region") == \
            "Bar chart of <column> by <column>"
        assert disclosure.scrub("salaryman") == "salaryman"  # whole words only


class TestParams:
    def test_password_never_goes_out(self):
        assert Disclosure(d.PROFILE).param_value("sk-123", "password") == d.HIDDEN_SECRET
        assert Disclosure(d.PROFILE).param_value("", "password") == ""

    @pytest.mark.parametrize("path", [
        "/home/dan/payroll/2026/salaries.xlsx",
        r"C:\Users\Dan\Payroll\salaries.xlsx",
        "~/payroll/salaries.xlsx"])
    def test_paths_go_out_as_the_file_name(self, path):
        assert Disclosure(d.PROFILE).param_value(path) == "salaries.xlsx"

    def test_column_params_are_scrubbed(self):
        disclosure = Disclosure(d.STRUCTURE, known_columns=["salary"])
        assert disclosure.param_value(["salary", "x"]) == ["<column>", "x"]


class TestPrivacy:
    def test_round_trip_and_defaults_write_nothing(self):
        assert Privacy().to_dict() == {} and Privacy().is_default()
        privacy = Privacy(1, {"a": ColumnRule(sensitive=True),
                              "b": ColumnRule(), "c": ColumnRule(alias="col_3")})
        data = privacy.to_dict()
        assert data == {"level": 1, "columns": {"a": {"sensitive": True},
                                                "c": {"alias": "col_3"}}}
        assert Privacy.from_dict(data).to_dict() == data

    def test_junk_is_tolerated(self):
        assert Privacy.from_dict({"level": "high", "columns": {"a": 3}}).to_dict() == {}
        assert Privacy.from_dict(None).is_default()

    def test_saved_with_the_flow(self, registry):
        from flograph.core.serialization import graph_from_dict, graph_to_dict
        from flograph.core.graph import Graph
        graph = Graph()
        graph.ai_privacy = Privacy(1, {"a": ColumnRule(alias="col_1")}).to_dict()
        data = graph_to_dict(graph)
        assert graph_from_dict(data, registry).ai_privacy == graph.ai_privacy
        assert "ai_privacy" not in json.dumps(graph_to_dict(Graph()))


def test_other_kinds_of_value():
    disclosure = Disclosure(d.PROFILE)
    assert disclosure.describe(42) == {"kind": "number"}
    assert disclosure.describe("secret text") == {"kind": "text", "length": 11}
    assert disclosure.describe(None) == {"kind": "nothing"}
    series = pd.Series([1, 2, None], name="score")
    out = disclosure.describe(series)
    assert out["kind"] == "column" and out["name"] == "score" and out["max"] == 2.0
    assert disclosure.describe({"k": 1})["keys"] == ["k"]


class TestHideText:
    def test_typed_text_is_hidden_but_column_names_are_not(self):
        disclosure = Disclosure(d.SCHEMA, Privacy(hide_text=True),
                                known_columns=["region", "sales"])
        assert disclosure.param_value('region == "Jane Smith"', "string") \
            == "<text, 22 characters>"
        assert disclosure.param_value("region", "string") == "region"
        assert disclosure.param_value("region, sales", "text") == "region, sales"
        assert disclosure.param_value("bar", "choice") == "bar"
        assert disclosure.param_value("", "string") == ""

    def test_off_by_default_and_saved_in_the_flow(self):
        disclosure = Disclosure(d.SCHEMA, Privacy())
        assert disclosure.param_value('x == "Jane"', "string") == 'x == "Jane"'
        assert Privacy.from_dict({"hide_text": True}).to_dict() == {"hide_text": True}
        assert not Privacy.from_dict({}).hide_text


class TestErrorText:
    def test_quoted_values_are_withheld_column_names_kept(self):
        disclosure = Disclosure(d.SCHEMA, Privacy(), known_columns=["price"])
        out = disclosure.error_text(
            "could not convert string to float: 'Jane Smith' in column 'price'")
        assert "Jane" not in out
        assert out == ("could not convert string to float: '<value>' "
                       "in column 'price'")

    def test_structure_hides_the_column_too(self):
        disclosure = Disclosure(d.STRUCTURE, Privacy(), known_columns=["price"])
        out = disclosure.error_text('KeyError: "price"')
        assert "price" not in out
