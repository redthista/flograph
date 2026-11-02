"""The User Form schema is pure Python and agrees with its node scripts."""
import json

import pandas as pd
import pytest

from flograph.core import compile_run
from flograph.core.form import (Field, coerce, coerce_entry, default_entry,
                                parse_entry, parse_form_schema,
                                schema_from_upstream, schema_to_text)
from tests.conftest import FakeContext


class TestFormSchema:
    def test_parse_all_field_types_and_required_marker(self):
        fields = parse_form_schema(
            "name|text*|Full name|\n"
            "about|textarea|About|hello\n"
            "secret|password|Password|\n"
            "age|int|Age|18\n"
            "rate|float|Rate|1.5\n"
            "joined|date|Joined|2026-01-02\n"
            "active|toggle|Active|true\n"
            "team|choice|Team|north|north,south")

        assert [field.kind for field in fields] == [
            "text", "textarea", "password", "int", "float", "date",
            "toggle", "choice"]
        assert fields[0].required
        assert fields[-1].options == ("north", "south")
        assert default_entry(fields) == {
            "name": "", "about": "hello", "secret": "", "age": 18,
            "rate": 1.5, "joined": "2026-01-02", "active": True,
            "team": "north"}

    @pytest.mark.parametrize("raw,message", [
        ("name|unknown|Name|", "unknown field type"),
        ("name|text|Name|\nname|text|Again|", "duplicate field"),
        ("name|choice|Name||", "needs at least one option"),
        ("name", "expected name\\|type"),
    ])
    def test_bad_schemas_name_the_problem(self, raw, message):
        with pytest.raises(ValueError, match=message):
            parse_form_schema(raw)

    def test_schema_round_trips_quoted_delimiters(self):
        fields = [Field("person", "text", "Name | role", "a|b")]
        text = schema_to_text(fields)
        assert parse_form_schema(text) == fields

    @pytest.mark.parametrize("source", [
        "x|int|X|0\ny|text|Y|",
        [{"name": "x", "type": "int", "label": "X", "default": 0}],
        {"name": "x", "type": "int", "label": "X", "default": 0},
        pd.DataFrame([{"name": "x", "type": "int", "label": "X",
                       "default": 0}]),
    ])
    def test_schema_from_upstream_accepts_text_records_and_tables(self, source):
        fields = schema_from_upstream(source, "fallback|text|Fallback|")
        assert fields[0].name == "x"
        assert fields[0].kind == "int"

    def test_missing_upstream_uses_fallback(self):
        assert schema_from_upstream(None, "x|text|X|")[0].name == "x"

    @pytest.mark.parametrize("field,raw,expected", [
        (Field("x", "int", "X"), "12", 12),
        (Field("x", "float", "X"), "1.25", 1.25),
        (Field("x", "date", "X"), "2026-02-03", "2026-02-03"),
        (Field("x", "toggle", "X"), "yes", True),
        (Field("x", "choice", "X", options=("a", "b")), "b", "b"),
        (Field("x", "text", "X"), " hi ", " hi "),
    ])
    def test_coerce_returns_typed_json_safe_values(self, field, raw, expected):
        value = coerce(field, raw)
        assert value == expected
        json.dumps(value)

    def test_blank_optional_numbers_and_dates_stay_blank(self):
        assert coerce(Field("n", "int", "N"), "") is None
        assert coerce(Field("d", "date", "D"), "") == ""

    def test_required_and_malformed_values_are_actionable(self):
        required = Field("name", "text", "Name", required=True)
        with pytest.raises(ValueError, match="Name is required"):
            coerce(required, "  ")
        with pytest.raises(ValueError, match="whole number"):
            coerce(Field("age", "int", "Age"), "old")
        with pytest.raises(ValueError, match="finite"):
            coerce(Field("rate", "float", "Rate"), "inf")
        with pytest.raises(ValueError, match="not one of"):
            coerce(Field("team", "choice", "Team", options=("a",)), "b")
        with pytest.raises(ValueError, match="must be a date"):
            coerce(Field("day", "date", "Day"), "not-a-date")

    def test_parse_entry_checks_required_fields_and_drops_unknown_keys(self):
        fields = [Field("name", "text", "Name", required=True),
                  Field("age", "int", "Age")]
        assert parse_entry('{"name":"Ada","age":"12","extra":1}',
                           fields) == {"name": "Ada", "age": 12}
        with pytest.raises(ValueError, match="Name is required"):
            parse_entry('{"age":12}', fields)

    def test_empty_entry_is_allowed_before_first_submit(self):
        assert parse_entry("", [Field("name", "text", "Name", required=True)]) == {}

    def test_invalid_stored_json_fails_cleanly(self):
        with pytest.raises(ValueError, match="not valid JSON"):
            parse_entry("{", [])


class TestFormNodeScripts:
    def _run(self, registry, type_id, params=None, **inputs):
        spec = registry.get(type_id)
        values = spec.default_params()
        values.update(params or {})
        run = compile_run(spec.source, f"test-{type_id}")
        return run(FakeContext(params=values), **inputs)

    def test_user_form_returns_typed_submitted_entry(self, registry):
        result = self._run(
            registry, "flograph.input.user_form",
            {"fields": "age|int|Age|0", "value": '{"age":"23"}'})
        assert result == {"entry": {"age": 23}}

    def test_user_form_starts_with_an_empty_entry(self, registry):
        assert self._run(registry, "flograph.input.user_form",
                         {"fields": "name|text|Name|"}) == {"entry": {}}

    def test_user_form_rejects_invalid_stored_values(self, registry):
        with pytest.raises(ValueError, match="whole number"):
            self._run(registry, "flograph.input.user_form",
                      {"fields": "age|int|Age|0", "value": '{"age":"x"}'})

    def test_form_from_table_infers_types_and_unique_names(self, registry):
        table = pd.DataFrame({"Customer Name": ["Ada"], "age": [12],
                              "age!": [13], "active": [True],
                              "joined": pd.to_datetime(["2026-01-02"])})
        result = self._run(registry, "flograph.input.form_from_table",
                           table=table)
        fields = parse_form_schema(result["fields"])
        assert [(field.name, field.kind) for field in fields] == [
            ("customer_name", "text"), ("age", "int"), ("age_2", "int"),
            ("active", "toggle"), ("joined", "date")]
        assert [field.label for field in fields][0] == "Customer Name"

    def test_form_from_table_can_force_text(self, registry):
        table = pd.DataFrame({"age": [12]})
        result = self._run(registry, "flograph.input.form_from_table",
                           {"all_text": True}, table=table)
        assert parse_form_schema(result["fields"])[0].kind == "text"
