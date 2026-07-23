"""Sheet schema: tolerant parsing, structural ops, validation, formatting."""
import json

from flograph.core.sheet import (COLUMN_TYPES, ColumnSpec, FormulaError,
                                 Sheet, format_value, is_formula,
                                 literal_value, next_column_name,
                                 normalize_date, parse_sheet, sheet_to_dict,
                                 sheet_to_json, validate_cell)


class TestParseSheet:
    def test_v1_shape_upgrades(self):
        raw = json.dumps({"columns": ["x", "y"], "rows": [["1", "2"]]})
        sheet = parse_sheet(raw)
        assert [c.name for c in sheet.columns] == ["x", "y"]
        assert all(c.type == "auto" for c in sheet.columns)
        assert sheet.rows == [["1", "2"]]
        assert sheet_to_dict(sheet)["version"] == 2

    def test_v2_round_trip(self):
        sheet = Sheet([ColumnSpec("Price", "number"), ColumnSpec("Qty", "integer")],
                      [["1.5", "=A1*2"]])
        again = parse_sheet(sheet_to_json(sheet))
        assert again == sheet

    def test_junk_falls_back_to_minimal_grid(self):
        for raw in ("not json", "", None, "[1,2]", json.dumps({"rows": 7})):
            sheet = parse_sheet(raw)
            assert [c.name for c in sheet.columns] == ["A", "B"]
            assert sheet.rows == [["", ""]]

    def test_rows_padded_and_truncated(self):
        raw = json.dumps({"columns": ["a", "b"],
                          "rows": [["1"], ["1", "2", "3"], "bogus", [None, 5]]})
        sheet = parse_sheet(raw)
        assert sheet.rows == [["1", ""], ["1", "2"], ["", "5"]]

    def test_column_widths_round_trip(self):
        sheet = Sheet([ColumnSpec("a", "auto", 120), ColumnSpec("b")],
                      [["", ""]])
        data = sheet_to_dict(sheet)
        assert data["columns"][0]["width"] == 120
        assert "width" not in data["columns"][1]
        assert parse_sheet(json.dumps(data)) == sheet

    def test_junk_width_is_ignored(self):
        raw = json.dumps({"version": 2,
                          "columns": [{"name": "a", "width": "wide"},
                                      {"name": "b", "width": -5}],
                          "rows": [["", ""]]})
        assert all(c.width is None for c in parse_sheet(raw).columns)

    def test_unknown_column_type_becomes_auto(self):
        raw = json.dumps({"version": 2,
                          "columns": [{"name": "x", "type": "quantum"}],
                          "rows": [["1"]]})
        assert parse_sheet(raw).columns[0].type == "auto"


class TestStructuralOps:
    def make(self):
        return Sheet([ColumnSpec("A"), ColumnSpec("B")],
                     [["1", "2"], ["3", "4"]])

    def test_insert_and_remove_rows(self):
        sheet = self.make()
        sheet.insert_rows(1, 2)
        assert sheet.n_rows == 4 and sheet.rows[1] == ["", ""]
        sheet.remove_rows([1, 2])
        assert sheet.rows == [["1", "2"], ["3", "4"]]

    def test_insert_column_in_middle(self):
        sheet = self.make()
        name = sheet.insert_column(1, "mid", "number")
        assert name == "mid"
        assert [c.name for c in sheet.columns] == ["A", "mid", "B"]
        assert sheet.rows[0] == ["1", "", "2"]

    def test_insert_column_auto_names(self):
        sheet = self.make()
        assert sheet.insert_column(2) == "C"

    def test_remove_columns(self):
        sheet = self.make()
        sheet.remove_columns([0])
        assert [c.name for c in sheet.columns] == ["B"]
        assert sheet.rows == [["2"], ["4"]]

    def test_ensure_size_only_grows(self):
        sheet = self.make()
        sheet.ensure_size(4, 3)
        assert (sheet.n_rows, sheet.n_cols) == (4, 3)
        sheet.ensure_size(1, 1)
        assert (sheet.n_rows, sheet.n_cols) == (4, 3)

    def test_sort_numbers_text_blanks(self):
        sheet = Sheet([ColumnSpec("A")], [["banana"], ["10"], [""], ["2"]])
        sheet.sort_by(0)
        assert [r[0] for r in sheet.rows] == ["2", "10", "banana", ""]
        sheet.sort_by(0, ascending=False)
        assert [r[0] for r in sheet.rows] == ["", "banana", "10", "2"]

    def test_copy_is_deep(self):
        sheet = self.make()
        clone = sheet.copy()
        clone.set_cell(0, 0, "changed")
        clone.rename_column(0, "renamed")
        assert sheet.cell(0, 0) == "1"
        assert sheet.columns[0].name == "A"


class TestValidation:
    def test_number(self):
        assert validate_cell("1.5", "number") is None
        assert validate_cell("abc", "number") is not None

    def test_integer(self):
        assert validate_cell("42", "integer") is None
        assert validate_cell("3.7", "integer") is not None

    def test_date(self):
        assert validate_cell("2026-07-23", "date") is None
        assert validate_cell("23/07/2026", "date") is None
        assert validate_cell("not a date", "date") is not None

    def test_bool(self):
        assert validate_cell("TRUE", "bool") is None
        assert validate_cell("false", "bool") is None
        assert validate_cell("maybe", "bool") is not None

    def test_normalize_date(self):
        assert normalize_date("2026-07-23") == "2026-07-23"
        assert normalize_date("23/07/2026") == "2026-07-23"
        assert normalize_date("2026/07/23") == "2026-07-23"
        assert normalize_date("Jul 5, 2026") == "2026-07-05"
        assert normalize_date("5 July 2026") == "2026-07-05"
        assert normalize_date("07-Mar-12") == "2012-03-07"
        assert normalize_date("07-Mar-2012") == "2012-03-07"
        assert normalize_date("2026-07-23 14:30") == "2026-07-23 14:30:00"
        assert normalize_date("not a date") is None
        assert normalize_date("") is None

    def test_custom_date_formats_win_over_builtins(self):
        from flograph.core.sheet import set_extra_date_formats
        try:
            set_extra_date_formats(["%Y.%m.%d", "%m/%d/%Y"])
            assert normalize_date("2026.07.23") == "2026-07-23"
            # custom month-first beats the built-in day-first default
            assert normalize_date("03/04/2026") == "2026-03-04"
            assert validate_cell("2026.07.23", "date") is None
        finally:
            set_extra_date_formats([])
        assert normalize_date("2026.07.23") is None
        assert normalize_date("03/04/2026") == "2026-04-03"   # day-first again

    def test_formulas_and_blanks_always_pass(self):
        for col_type in COLUMN_TYPES:
            assert validate_cell("=A1+1", col_type) is None
            assert validate_cell("", col_type) is None

    def test_auto_and_text_accept_anything(self):
        assert validate_cell("whatever", "auto") is None
        assert validate_cell("whatever", "text") is None


class TestHelpers:
    def test_is_formula(self):
        assert is_formula("=1+1")
        assert not is_formula("=")
        assert not is_formula("plain")
        assert not is_formula(None)

    def test_next_column_name_wraps_to_c_numbers(self):
        import string
        assert next_column_name([]) == "A"
        assert next_column_name(["A", "B"]) == "C"
        all_letters = list(string.ascii_uppercase)
        assert next_column_name(all_letters) == "C1"
        assert next_column_name(all_letters + ["C1"]) == "C2"

    def test_literal_value(self):
        assert literal_value("5") == 5.0
        assert literal_value("TRUE") is True
        assert literal_value("") is None
        assert literal_value("hello") == "hello"
        assert literal_value("5", "text") == "5"
        assert literal_value("nan") == "nan"   # not a silent float NaN

    def test_format_value(self):
        assert format_value(None) == ""
        assert format_value(5.0) == "5"
        assert format_value(0.1 + 0.2) == "0.3"
        assert format_value(True) == "TRUE"
        assert format_value(FormulaError("#DIV/0!")) == "#DIV/0!"
