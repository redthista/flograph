"""Formula engine: tokenizer/parser/evaluator, dependencies, translate."""
import pytest

from flograph.core.sheet import (ColumnSpec, FormulaError, Sheet, cell_name,
                                 col_index, col_letters, evaluate_sheet,
                                 translate)


def calc(formula, data=(("",),)):
    """Evaluate one formula against a grid: the data rows become columns
    A.., and the formula lands in an extra column on row 1."""
    rows = [list(r) for r in data]
    width = max(len(r) for r in rows)
    for row in rows:
        row += [""] * (width - len(row)) + [""]
    rows[0][width] = formula
    columns = [ColumnSpec(col_letters(i)) for i in range(width + 1)]
    return evaluate_sheet(Sheet(columns, rows)).values[0][width]


def code_of(value):
    assert isinstance(value, FormulaError), f"expected an error, got {value!r}"
    return value.code


class TestArithmetic:
    def test_precedence(self):
        assert calc("=1+2*3") == 7
        assert calc("=(1+2)*3") == 9

    def test_power_is_left_associative(self):
        assert calc("=2^3^2") == 64

    def test_unary_minus_binds_tighter_than_power(self):
        assert calc("=-2^2") == 4   # Excel quirk: (-2)^2

    def test_double_negation_and_percent(self):
        assert calc("=--5") == 5
        assert calc("=50%") == 0.5
        assert calc("=200%%") == 0.02

    def test_division(self):
        assert calc("=7/2") == 3.5
        assert code_of(calc("=1/0")) == "#DIV/0!"

    def test_numeric_text_coerces(self):
        assert calc('="3"+2') == 5

    def test_non_numeric_text_errors(self):
        assert code_of(calc('="abc"+1')) == "#VALUE!"


class TestTextAndLogic:
    def test_concat_operator(self):
        assert calc('="foo"&"bar"') == "foobar"
        assert calc('=1&2') == "12"

    def test_string_quote_escape(self):
        assert calc('="He said ""hi"""') == 'He said "hi"'

    def test_comparisons(self):
        assert calc("=1<2") is True
        assert calc("=2<=2") is True
        assert calc("=1<>2") is True
        assert calc('="ABC"="abc"') is True   # case-blind like Excel

    def test_mixed_type_equality_is_false(self):
        assert calc('=1="one"') is False
        assert calc('=1<>"one"') is True

    def test_true_false_literals(self):
        assert calc("=TRUE") is True
        assert calc("=NOT(FALSE)") is True


class TestReferences:
    def test_simple_ref(self):
        assert calc("=A1*2", [["21"]]) == 42

    def test_refs_are_case_insensitive(self):
        assert calc("=a1+A2", [["1"], ["2"]]) == 3

    def test_absolute_ref(self):
        assert calc("=$A$1", [["9"]]) == 9

    def test_blank_is_zero_in_math_and_empty_in_concat(self):
        assert calc("=A1+1", [[""]]) == 1
        assert calc('=A1&"x"', [[""]]) == "x"

    def test_out_of_grid_scalar_ref(self):
        assert code_of(calc("=Z99")) == "#REF!"
        assert code_of(calc("=1+Z99")) == "#REF!"

    def test_range_sum_and_clamping(self):
        grid = [["1"], ["2"], ["3"]]
        assert calc("=SUM(A1:A3)", grid) == 6
        assert calc("=SUM(A1:A999)", grid) == 6   # ranges clamp to the grid

    def test_range_in_scalar_context_errors(self):
        assert code_of(calc("=A1:A2+1", [["1"], ["2"]])) == "#VALUE!"


class TestFunctions:
    def test_aggregates(self):
        grid = [["1", "x"], ["2", ""], ["3", "4"]]
        assert calc("=AVERAGE(A1:A3)", grid) == 2
        assert calc("=MIN(A1:A3)", grid) == 1
        assert calc("=MAX(A1:B3)", grid) == 4
        assert calc("=COUNT(A1:B3)", grid) == 4   # numbers only
        assert calc("=COUNTA(A1:B3)", grid) == 5  # non-blank cells

    def test_round_half_away_from_zero(self):
        assert calc("=ROUND(2.5)") == 3
        assert calc("=ROUND(-2.5)") == -3
        assert calc("=ROUND(1.234, 2)") == 1.23

    def test_math_functions(self):
        assert calc("=ABS(-3)") == 3
        assert calc("=SQRT(9)") == 3
        assert code_of(calc("=SQRT(-1)")) == "#NUM!"
        assert calc("=POWER(2, 10)") == 1024
        assert calc("=MOD(-3, 2)") == 1   # sign follows divisor
        assert code_of(calc("=MOD(1, 0)")) == "#DIV/0!"
        assert calc("=FLOOR(7, 2)") == 6
        assert calc("=CEILING(7, 2)") == 8

    def test_text_functions(self):
        assert calc('=CONCAT("a", 1, TRUE)') == "a1TRUE"
        assert calc('=LEN("hello")') == 5
        assert calc('=UPPER("hi")') == "HI"
        assert calc('=LOWER("HI")') == "hi"
        assert calc('=TRIM("  a   b ")') == "a b"
        assert calc('=LEFT("hello", 2)') == "he"
        assert calc('=RIGHT("hello", 2)') == "lo"
        assert calc('=MID("hello", 2, 3)') == "ell"

    def test_logical_functions(self):
        assert calc("=AND(TRUE, 1)") is True
        assert calc("=AND(TRUE, 0)") is False
        assert calc("=OR(FALSE, 1)") is True
        assert calc("=IF(2>1, \"yes\", \"no\")") == "yes"

    def test_if_only_evaluates_taken_branch(self):
        assert calc("=IF(TRUE, 1, 1/0)") == 1
        assert calc("=IF(FALSE, 1/0, 2)") == 2

    def test_function_names_case_insensitive(self):
        assert calc("=sum(1, 2)") == 3

    def test_semicolon_argument_separator(self):
        assert calc("=SUM(1; 2)") == 3

    def test_unknown_function(self):
        assert code_of(calc("=NOPE(1)")) == "#NAME?"

    def test_wrong_arity(self):
        assert code_of(calc("=MID(\"x\")")) == "#VALUE!"

    def test_errors_propagate_through_aggregates(self):
        grid = [["=1/0"], ["2"]]
        assert code_of(calc("=SUM(A1:A2)", grid)) == "#DIV/0!"


class TestSheetEvaluation:
    def test_dependency_order_is_free(self):
        # C1 depends on B1 depends on A1, declared in reverse
        sheet = Sheet([ColumnSpec("A"), ColumnSpec("B"), ColumnSpec("C")],
                      [["2", "=A1+1", "=B1+1"]])
        result = evaluate_sheet(sheet)
        assert result.values[0] == [2, 3, 4]
        assert result.errors == {}

    def test_direct_cycle(self):
        sheet = Sheet([ColumnSpec("A"), ColumnSpec("B")],
                      [["=B1", "=A1"]])
        result = evaluate_sheet(sheet)
        assert code_of(result.values[0][0]) == "#CYCLE!"
        assert code_of(result.values[0][1]) == "#CYCLE!"
        assert set(result.errors) == {(0, 0), (0, 1)}

    def test_self_reference_cycle(self):
        sheet = Sheet([ColumnSpec("A")], [["=A1"]])
        assert code_of(evaluate_sheet(sheet).values[0][0]) == "#CYCLE!"

    def test_cell_feeding_off_a_cycle_is_flagged(self):
        sheet = Sheet([ColumnSpec("A"), ColumnSpec("B"), ColumnSpec("C")],
                      [["=B1", "=A1", "=A1+1"]])
        assert code_of(evaluate_sheet(sheet).values[0][2]) == "#CYCLE!"

    def test_syntax_error_shows_as_error_cell(self):
        sheet = Sheet([ColumnSpec("A")], [["=1+"]])
        result = evaluate_sheet(sheet)
        assert code_of(result.values[0][0]) == "#ERROR!"
        assert (0, 0) in result.errors

    def test_lone_equals_is_text(self):
        sheet = Sheet([ColumnSpec("A")], [["="]])
        assert evaluate_sheet(sheet).values[0][0] == "="


class TestTranslate:
    def test_relative_shift(self):
        assert translate("=A1+B2", 1, 1) == "=B2+C3"

    def test_pins_are_respected(self):
        assert translate("=$A$1+B2", 1, 0) == "=$A$1+B3"
        assert translate("=A$1+$B2", 1, 1) == "=B$1+$B3"

    def test_pushed_off_grid_becomes_ref_error(self):
        assert translate("=A1", -1, 0) == "=#REF!"

    def test_ranges_shift(self):
        assert translate("=SUM(A1:A3)", 0, 1) == "=SUM(B1:B3)"

    def test_strings_are_left_alone(self):
        assert translate('="A1"&B1', 1, 0) == '="A1"&B2'

    def test_non_formula_unchanged(self):
        assert translate("hello", 1, 1) == "hello"

    def test_broken_formula_unchanged(self):
        assert translate("=1+", 1, 1) == "=1+"


class TestColumnRefs:
    @staticmethod
    def named(columns, rows):
        return evaluate_sheet(Sheet([ColumnSpec(n) for n in columns],
                                    [list(r) for r in rows]))

    def test_this_row_reference(self):
        result = self.named(
            ["Price", "Qty", "Total"],
            [["10.5", "3", "=[@Price]*[@Qty]"],
             ["4", "5", "=[@Price]*[@Qty]"]])
        assert [row[2] for row in result.values] == [31.5, 20]

    def test_whole_column_in_aggregates(self):
        result = self.named(["Qty", "Sum"],
                            [["1", "=SUM([Qty])"], ["2", ""], ["3", ""]])
        assert result.values[0][1] == 6

    def test_names_with_spaces_and_case(self):
        result = self.named(["value x", "y"], [["21", "=[@VALUE X]*2"]])
        assert result.values[0][1] == 42

    def test_unknown_column_name(self):
        result = self.named(["a"], [["=[@nope]"]])
        assert code_of(result.values[0][0]) == "#NAME?"
        assert "nope" in result.errors[(0, 0)]

    def test_whole_column_self_reference_is_a_cycle(self):
        result = self.named(["t"], [["=SUM([t])"]])
        assert code_of(result.values[0][0]) == "#CYCLE!"

    def test_dependency_order_through_names(self):
        result = self.named(["a", "b", "c"],
                            [["2", "=[@a]+1", "=[@b]+1"]])
        assert result.values[0] == [2, 3, 4]

    def test_translate_leaves_named_refs_alone(self):
        assert translate("=[@Price]*A1", 2, 1) == "=[@Price]*B3"

    def test_rename_column_in_formulas(self):
        from flograph.core.sheet import rename_column_in_formulas
        assert (rename_column_in_formulas("=[@old]*[old]+A1", "old", "new")
                == "=[@new]*[new]+A1")
        assert (rename_column_in_formulas("=[@other]*2", "old", "new")
                == "=[@other]*2")
        assert rename_column_in_formulas("plain text", "old", "new") == "plain text"

    def test_unclosed_bracket_is_a_syntax_error(self):
        result = self.named(["a"], [["=[@a"]])
        assert code_of(result.values[0][0]) == "#ERROR!"


def test_function_help_covers_every_function():
    from flograph.core.sheet import FUNCTION_HELP, FUNCTION_NAMES
    documented = {name for name, *_ in FUNCTION_HELP}
    assert documented >= set(FUNCTION_NAMES) - {"AVG"}   # AVG = AVERAGE alias


class TestNames:
    def test_column_letters_round_trip(self):
        assert col_letters(0) == "A"
        assert col_letters(25) == "Z"
        assert col_letters(26) == "AA"
        for i in (0, 25, 26, 700):
            assert col_index(col_letters(i)) == i

    def test_cell_name(self):
        assert cell_name(2, 1) == "B3"
        assert cell_name(0, 26) == "AA1"
