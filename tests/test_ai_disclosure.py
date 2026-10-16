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

    def test_nothing_above_all_my_data(self):
        assert Disclosure(9).level == d.FULL
        assert d.effective_level(9) == d.FULL

    def test_effective_level_is_the_lowest(self):
        assert d.effective_level(2, None, None) == 2
        assert d.effective_level(2, 1, None) == 1
        assert d.effective_level(1, 2, 2) == 1     # the flow can't raise it
        assert d.effective_level(2, 2, 0) == 0


class TestColumnRules:
    def _cols(self, table, level, **modes):
        privacy = Privacy(columns={k: ColumnRule(v) for k, v in modes.items()})
        out = Disclosure(level, privacy).describe(table)
        return out, {c["name"]: c for c in out.get("columns", [])}

    def test_hidden_is_left_out_entirely(self, table):
        out, cols = self._cols(table, d.PROFILE, salary=d.HIDDEN)
        assert "salary" not in cols and "51234" not in _dump(out)
        assert out["columns_count"] == len(table.columns) - 1
        assert "salary" not in _dump(out)

    def test_a_hidden_name_is_scrubbed_from_every_string(self, table):
        disclosure = Disclosure(d.SCHEMA, Privacy(columns={
            "salary": ColumnRule(d.HIDDEN)}), known_columns=table.columns)
        assert disclosure.scrub("Bar chart of salary by region") == \
            "Bar chart of <column> by region"

    def test_name_only_is_the_default(self, table):
        _, cols = self._cols(table, d.SCHEMA)
        assert "values" not in cols["region"]

    def test_values_are_shared_only_when_asked(self, table):
        _, cols = self._cols(table, d.SCHEMA, region=d.VALUES)
        assert cols["region"]["values"]
        assert "values" not in cols["customer"]

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

    def test_at_nothing_names_and_typed_text_are_hidden(self):
        disclosure = Disclosure(d.STRUCTURE, known_columns=["salary"])
        assert disclosure.param_value(["salary", "Jane"]) == [
            "<column>", "<text, 4 characters>"]
        assert disclosure.param_value("x") == "<text, 1 character>"

    def test_from_column_names_up_typed_text_goes_as_typed(self):
        disclosure = Disclosure(d.SCHEMA, known_columns=["region"])
        assert disclosure.param_value('region == "North"', "string") == \
            'region == "North"'

    def test_a_hidden_column_in_a_setting_is_scrubbed(self):
        disclosure = Disclosure(d.SCHEMA, Privacy(columns={
            "salary": ColumnRule(d.HIDDEN)}), known_columns=["salary"])
        assert disclosure.param_value("salary > 10", "string") == "<column> > 10"


class TestPrivacy:
    def test_round_trip_and_defaults_write_nothing(self):
        assert Privacy().to_dict() == {} and Privacy().is_default()
        assert Privacy().effective == d.SCHEMA
        privacy = Privacy(2, {"a": ColumnRule(d.HIDDEN), "b": ColumnRule(),
                              "c": ColumnRule(d.VALUES)})
        data = privacy.to_dict()
        assert data == {"level": 2, "columns": {"a": "hidden", "c": "values"}}
        assert Privacy.from_dict(data).to_dict() == data

    def test_older_settings_convert_on_the_safe_side(self):
        old = Privacy.from_dict({"level": 2, "hide_text": True, "columns": {
            "a": {"sensitive": True}, "b": {"alias": "col_2", "hint": "x"},
            "c": {"share_values": True}, "d": {}}})
        assert old.level == d.STRUCTURE            # only Nothing hides typed text
        assert old.mode("a") == old.mode("b") == d.HIDDEN
        assert old.mode("c") == d.VALUES and old.mode("d") == d.NAME

    def test_junk_is_tolerated(self):
        assert Privacy.from_dict({"level": "high", "columns": {"a": 3}}).to_dict() == {}
        assert Privacy.from_dict(None).is_default()

    def test_saved_with_the_flow(self, registry):
        from flograph.core.serialization import graph_from_dict, graph_to_dict
        from flograph.core.graph import Graph
        graph = Graph()
        graph.ai_privacy = Privacy(1, {"a": ColumnRule(d.HIDDEN)}).to_dict()
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



class TestShareValues:
    TABLE = pd.DataFrame({"Test_Name": ["Hematocrit (HCT)", "TSH", "TSH"],
                          "Patient": ["a", "b", "c"]})

    def _cols(self, level, mode):
        disclosure = Disclosure(level, Privacy(columns={"Test_Name": ColumnRule(mode)}))
        return {c["name"]: c for c in disclosure.describe(self.TABLE)["columns"]}

    def test_most_common_first(self):
        cols = self._cols(d.SCHEMA, d.VALUES)
        assert cols["Test_Name"]["values"] == ["TSH", "Hematocrit (HCT)"]
        assert "values" not in cols["Patient"]

    def test_never_at_nothing(self):
        disclosure = Disclosure(d.STRUCTURE, Privacy(columns={
            "Test_Name": ColumnRule(d.VALUES)}))
        assert "Hematocrit" not in json.dumps(disclosure.describe(self.TABLE))

    def test_capped(self):
        table = pd.DataFrame({"c": [f"v{i}" for i in range(150)]})
        disclosure = Disclosure(d.SCHEMA, Privacy(columns={"c": ColumnRule(d.VALUES)}))
        col = disclosure.describe(table)["columns"][0]
        assert len(col["values"]) == 100 and col["values_not_shown"] == 50


class TestCharts:
    def test_a_chart_is_counted_not_shown(self):
        import plotly.graph_objects as go
        fig = go.Figure([go.Scatter(x=[1, 2, 3], y=[5.0, None, 7.0], name="HCT")])
        out = Disclosure(d.SCHEMA).describe(fig)
        assert out == {"kind": "chart", "traces": [
            {"type": "scatter", "name": "HCT", "points": 2}]}

    def test_an_empty_chart_says_so(self):
        import plotly.graph_objects as go
        out = Disclosure(d.SCHEMA).describe(go.Figure())
        assert out["traces"] == [] and "draws nothing" in out["note"]



class TestAllMyData:
    def test_tables_come_with_their_first_rows(self, table):
        out = Disclosure(d.FULL).describe(table)
        assert len(out["sample_rows"]) == d.SAMPLE_ROWS
        assert out["sample_rows"][0]["customer"] == SECRET_NAMES[0]
        assert "10 more" in out["more_rows"]

    def test_category_columns_bring_their_values(self, table):
        cols = {c["name"]: c for c in Disclosure(d.FULL).describe(table)["columns"]}
        assert sorted(cols["region"]["values"]) == ["North", "South"]

    def test_hidden_stays_hidden_rows_included(self, table):
        disclosure = Disclosure(d.FULL, Privacy(columns={"salary": ColumnRule(d.HIDDEN)}))
        out = disclosure.describe(table)
        assert "salary" not in _dump(out) and "51234" not in _dump(out)
        page = disclosure.rows(table, 0, 5)
        assert "salary" not in page["rows"][0] and page["total_rows"] == 30

    def test_rows_page_and_cap(self, table):
        disclosure = Disclosure(d.FULL)
        page = disclosure.rows(table, start=28, count=999)
        assert len(page["rows"]) == 2 and page["start"] == 28
        big = pd.DataFrame({"n": range(500)})
        assert len(disclosure.rows(big, 0, 999)["rows"]) == d.MAX_ROWS

    def test_no_rows_below_all_my_data(self, table):
        for level in (d.STRUCTURE, d.SCHEMA, d.PROFILE):
            disclosure = Disclosure(level)
            assert "sample_rows" not in disclosure.describe(table)
            assert "error" in disclosure.rows(table)

    def test_errors_as_they_are(self):
        text = "could not convert string to float: 'Jane Smith'"
        assert Disclosure(d.FULL).error_text(text) == text
        assert "Jane" not in Disclosure(d.PROFILE).error_text(text)

    def test_missing_cells_and_odd_cells(self):
        frame = pd.DataFrame({"a": [1.0, None], "b": [[1, 2], "x"]})
        rows = Disclosure(d.FULL).rows(frame)["rows"]
        assert rows[1]["a"] is None and rows[1]["b"] == "x"
