"""Structural edits keep formulas honest: inserting or deleting rows and
columns rewrites A1 references the way Excel does, and the sheet's newer
settings (dropdown lists, freeze panes) survive a save and a linked refresh."""
from flograph.core.sheet import (Sheet, evaluate_sheet, merge_linked_sheet,
                                 parse_sheet, sheet_to_dict,
                                 shift_for_structure, validate_cell)
from flograph.core.sheet.schema import ColumnSpec


class TestShiftForStructure:
    def test_insert_rows_moves_references_at_or_past_the_gap(self):
        assert shift_for_structure("=A1+A3", "row", 1, 2) == "=A1+A5"

    def test_insert_moves_pinned_references_too(self):
        # a $ pin is about copying, not about the sheet changing shape
        assert shift_for_structure("=$A$3", "row", 0, 1) == "=$A$4"

    def test_delete_a_referenced_row_is_ref_error(self):
        assert shift_for_structure("=A2*2", "row", 1, -1) == "=#REF!*2"

    def test_delete_moves_later_references_back(self):
        assert shift_for_structure("=B5", "row", 1, -2) == "=B3"

    def test_range_shrinks_when_an_end_is_deleted(self):
        assert shift_for_structure("=SUM(A1:A5)", "row", 4, -1) == \
            "=SUM(A1:A4)"
        assert shift_for_structure("=SUM(A2:A5)", "row", 0, -2) == \
            "=SUM(A1:A3)"

    def test_range_grows_when_rows_inserted_inside(self):
        assert shift_for_structure("=SUM(A1:A5)", "row", 2, 3) == \
            "=SUM(A1:A8)"

    def test_range_fully_deleted_is_ref_error(self):
        assert shift_for_structure("=SUM(A2:A3)", "row", 1, -2) == \
            "=SUM(#REF!)"

    def test_columns(self):
        assert shift_for_structure("=A1+C1", "col", 1, 1) == "=A1+D1"
        assert shift_for_structure("=A1+C1", "col", 1, -1) == "=A1+B1"
        assert shift_for_structure("=B1", "col", 1, -1) == "=#REF!"

    def test_column_name_references_are_left_alone(self):
        src = "=[@Price]*SUM([Qty])"
        assert shift_for_structure(src, "row", 0, 1) == src
        assert shift_for_structure(src, "col", 0, -1) == src

    def test_non_formulas_untouched(self):
        assert shift_for_structure("A1", "row", 0, 1) == "A1"
        assert shift_for_structure("=(", "row", 0, 1) == "=("


class TestSheetStructure:
    def _sheet(self):
        return Sheet([ColumnSpec("a"), ColumnSpec("b")],
                     [["1", "=A3"], ["2", ""], ["3", "=SUM(A1:A3)"]])

    def test_delete_row_keeps_formula_on_its_cell(self):
        sheet = self._sheet()
        sheet.remove_rows([1])
        assert sheet.rows[0][1] == "=A2"
        assert sheet.rows[1][1] == "=SUM(A1:A2)"
        values = evaluate_sheet(sheet).values
        assert values[0][1] == 3.0 and values[1][1] == 4.0

    def test_insert_row_inside_keeps_formula_on_its_cell(self):
        sheet = self._sheet()
        sheet.insert_rows(0, 1)
        assert sheet.rows[1][1] == "=A4"

    def test_append_shifts_nothing(self):
        sheet = Sheet([ColumnSpec("a")], [["=SUM(A1:A999)"]])
        sheet.insert_rows(1, 2)
        assert sheet.rows[0][0] == "=SUM(A1:A999)"

    def test_move_rows_and_columns(self):
        sheet = Sheet([ColumnSpec("a"), ColumnSpec("b"), ColumnSpec("c")],
                      [["1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"]])
        sheet.move_rows([2], 0)
        assert [r[0] for r in sheet.rows] == ["7", "1", "4"]
        sheet.move_columns([0], 2)
        assert sheet.column_names() == ["b", "c", "a"]
        assert sheet.rows[0] == ["8", "9", "7"]


class TestChoicesAndFreeze:
    def test_round_trip(self):
        sheet = parse_sheet({
            "columns": [{"name": "status", "type": "text",
                         "choices": ["open", "closed"], "strict": True},
                        {"name": "n"}],
            "rows": [["open", "1"], ["closed", "2"]],
            "freeze": {"rows": 1, "cols": 1}})
        assert sheet.columns[0].choices == ["open", "closed"]
        assert sheet.columns[0].strict
        assert (sheet.freeze_rows, sheet.freeze_cols) == (1, 1)
        again = parse_sheet(sheet_to_dict(sheet))
        assert sheet_to_dict(again) == sheet_to_dict(sheet)

    def test_unset_freeze_is_not_written(self):
        assert "freeze" not in sheet_to_dict(parse_sheet(None))

    def test_strict_list_flags_values_off_it(self):
        assert validate_cell("Open", "text", ["open"], strict=True) is None
        assert "not on this column's list" in validate_cell(
            "maybe", "text", ["open"], strict=True)
        assert validate_cell("maybe", "text", ["open"], strict=False) is None
        assert validate_cell("", "text", ["open"], strict=True) is None

    def test_linked_refresh_keeps_the_users_list_and_freeze(self):
        base = Sheet([ColumnSpec("status")], [["open"], ["closed"]])
        stored = parse_sheet({
            "columns": [{"name": "status", "choices": ["open", "closed"]},
                        {"name": "note", "choices": ["ok", "chase"]}],
            "rows": [["open", "ok"]],
            "freeze": {"cols": 1}})
        merged = merge_linked_sheet(base, stored)
        assert merged.columns[0].choices == ["open", "closed"]
        assert merged.columns[1].choices == ["ok", "chase"]
        assert merged.freeze_cols == 1
