"""A big Table recalculates quickly, and the shortcuts that make it quick
give exactly what the plain way gives.

The engine shares one value per range between every formula that reads it,
and SUMIF/COUNTIF/the …IFS family and the exact lookups keep indexes and
answers on that shared value. The parity tests below evaluate every formula
a second time with a plain cell reader — no shared ranges, so no indexes —
over deliberately awkward data, and expect the same value everywhere."""
import random
import time

import pytest

from flograph.core.sheet import SheetEvaluator, evaluate_sheet, parse_sheet
from flograph.core.sheet.formula import (bind_column_refs, evaluate,
                                         parse_formula)
from flograph.core.sheet.schema import set_extra_date_formats
from flograph.core.sheet.values import FormulaError

KEYS = ["North", "north", "NORTH ", "South", "5", "5.0", "05", "", "TRUE",
        "2026-10-07", "7 Oct 2026", "07/10/2026", "N*", "So?th", "x~*y",
        "x*y", "=North", "<>South", ">3", "<=2026-10-07", "0", "-0"]
NUMBERS = ["1", "2.5", "", "abc", "-3", "1e2", "TRUE", "0", "7"]

FORMULAS = [
    "=SUMIF([Key], [@Key], [Num])",
    "=SUMIF([Key], [@Key])",
    "=COUNTIF([Key], [@Key])",
    "=AVERAGEIF([Key], [@Key], [Num])",
    "=SUMIFS([Num], [Key], [@Key], [Num], \">0\")",
    "=COUNTIFS([Key], [@Key], [Grp], [@Grp])",
    "=AVERAGEIFS([Num], [Grp], [@Grp])",
    "=MAXIFS([Num], [Key], [@Key])",
    "=MINIFS([Num], [Grp], [@Grp], [Key], [@Key])",
    "=COUNTIF([Num], [@Num])",
    "=SUMIF([Num], [@Num], [Num])",
    "=IFERROR(MATCH([@Key], [Key], 0), \"none\")",
    "=IFERROR(XLOOKUP([@Key], [Key], [Grp]), \"none\")",
    "=IFERROR(XLOOKUP([@Key], [Key], [Grp], \"-\", 0, -1), \"none\")",
    "=IFERROR(VLOOKUP([@Key], A1:C40, 3, FALSE), \"none\")",
    "=IFERROR(MATCH([@Num], [Num], 0), \"none\")",
]


def _sheet(n_rows=40, seed=7):
    rnd = random.Random(seed)
    rows = []
    for i in range(n_rows):
        rows.append([rnd.choice(KEYS), rnd.choice(NUMBERS),
                     rnd.choice(["a", "b", "c", "B"]),
                     FORMULAS[i % len(FORMULAS)]])
    columns = [{"name": "Key", "type": "text" if seed % 2 else "auto"},
               {"name": "Num"}, {"name": "Grp"}, {"name": "Out"}]
    return parse_sheet({"version": 2, "columns": columns, "rows": rows})


def _plain(sheet, result, row, col):
    """The cell's formula again, with no shared ranges — every function
    scans, as it did before the shortcuts."""
    ast = bind_column_refs(parse_formula(sheet.rows[row][col]), row,
                           sheet.column_names(), sheet.n_rows)

    def get_cell(r, c):
        return result.values[r][c]

    return evaluate(ast, get_cell, (sheet.n_rows, sheet.n_cols))


def _same(a, b):
    if isinstance(a, FormulaError) or isinstance(b, FormulaError):
        return isinstance(a, FormulaError) and a == b
    return a == b


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_shortcuts_agree_with_the_plain_scan(seed):
    sheet = _sheet(seed=seed)
    result = evaluate_sheet(sheet)
    for row in range(sheet.n_rows):
        fast = result.values[row][3]
        plain = _plain(sheet, result, row, 3)
        assert _same(fast, plain), (sheet.rows[row], fast, plain)


def test_extra_date_formats_take_effect_at_once():
    """Dates are remembered; changing the formats must forget them."""
    sheet = parse_sheet({"version": 2, "columns": [{"name": "D"},
                                                   {"name": "Next"}],
                         "rows": [["2026.10.07", "=[@D]+1"]]})
    assert evaluate_sheet(sheet).values[0][1] != "2026-10-08"
    try:
        set_extra_date_formats(["%Y.%m.%d"])
        assert evaluate_sheet(sheet).values[0][1] == "2026-10-08"
    finally:
        set_extra_date_formats([])
    assert evaluate_sheet(sheet).values[0][1] != "2026-10-08"


def test_a_formula_inside_the_range_it_reads_is_a_cycle():
    sheet = parse_sheet({"version": 2, "columns": [{"name": "A"}],
                         "rows": [["1"], ["=SUM([A])"], ["2"]]})
    result = evaluate_sheet(sheet)
    assert result.values[1][0].code == "#CYCLE!"


def test_a_range_waits_for_the_formulas_inside_it():
    sheet = parse_sheet({"version": 2, "columns": [{"name": "A"},
                                                   {"name": "B"}],
                         "rows": [["=SUM(B1:B3)", "=1+1"],
                                  ["", "=B1*10"], ["", "=B2+1"]]})
    assert evaluate_sheet(sheet).values[0][0] == 2 + 20 + 21


def test_syntax_errors_are_still_errors_when_remembered():
    sheet = parse_sheet({"version": 2, "columns": [{"name": "A"}],
                         "rows": [["=1+"], ["=1+"]]})
    result = evaluate_sheet(sheet)
    assert result.values[0][0].code == result.values[1][0].code == "#ERROR!"


def test_a_big_sheet_with_a_conditional_column_is_quick():
    """20,000 rows with a SUMIF in every row took ~14 s when each one
    scanned the column; it is a fraction of that now. The bound is loose
    so a slow machine does not fail it — it catches a return to n²."""
    regions = ["North", "South", "East", "West"]
    rows = [[regions[i % 4], str(i % 25), "=[@Units]*2",
             "=SUMIF([Region], [@Region], [Total])"] for i in range(20_000)]
    sheet = parse_sheet({"version": 2, "columns": [
        {"name": "Region"}, {"name": "Units"}, {"name": "Total"},
        {"name": "Region total"}], "rows": rows})
    start = time.perf_counter()
    result = evaluate_sheet(sheet)
    assert time.perf_counter() - start < 6.0
    north = sum((i % 25) * 2 for i in range(0, 20_000, 4))
    assert result.values[0][3] == north


# ---------------------------------------------------------- incremental

EDITS = ["", "1", "2.5", "abc", "North", "=A1+1", "=B2*2", "=SUM([A])",
         "=SUM(A1:B3)", "=C1", "=C2+C3", "=A1+", "=[@A]+[@B]",
         "=SUMIF([B], [@B], [A])", "=COUNTIF([D], \"x\")", "x", "=D1",
         "=IF(A1>1, B1, C1)", "=A4", "TRUE", "2026-10-07", "=[@A]+7"]


def _values_equal(a, b):
    if isinstance(a, FormulaError) or isinstance(b, FormulaError):
        return (isinstance(a, FormulaError) and isinstance(b, FormulaError)
                and a.code == b.code)
    return a == b


@pytest.mark.parametrize("seed", range(8))
def test_incremental_matches_a_full_pass_after_every_edit(seed):
    """Random edits, one or a few cells at a time — formulas that read
    each other, ranges, cycles that come and go, syntax errors. After each,
    the kept values must be what a recalculation from scratch gives."""
    rnd = random.Random(seed)
    sheet = parse_sheet({"version": 2,
                         "columns": [{"name": n} for n in "ABCD"],
                         "rows": [[rnd.choice(EDITS) for _ in range(4)]
                                  for _ in range(6)]})
    kept = SheetEvaluator(sheet)
    for step in range(60):
        changed = set()
        for _ in range(rnd.choice([1, 1, 1, 2, 3])):
            r, c = rnd.randrange(sheet.n_rows), rnd.randrange(sheet.n_cols)
            sheet.rows[r][c] = rnd.choice(EDITS)
            changed.add((r, c))
        got = kept.update(sheet, changed)
        want = evaluate_sheet(sheet)
        for r in range(sheet.n_rows):
            for c in range(sheet.n_cols):
                assert _values_equal(got.values[r][c], want.values[r][c]), (
                    step, (r, c), sheet.rows, got.values[r][c],
                    want.values[r][c])
        assert set(got.errors) == set(want.errors), step


def test_a_shape_change_falls_back_to_a_full_pass():
    sheet = parse_sheet({"version": 2, "columns": [{"name": "A"}],
                         "rows": [["1"], ["=SUM([A])"]]})
    kept = SheetEvaluator(sheet)
    sheet.insert_rows(0, 1)
    sheet.rows[0][0] = "5"
    got = kept.update(sheet, [(0, 0)])
    assert got.values[2][0] == evaluate_sheet(sheet).values[2][0]


def test_one_edit_in_a_big_sheet_touches_only_what_reads_it():
    rows = [[str(i), "=[@A]*2", "=[@B]+1"] for i in range(20_000)]
    sheet = parse_sheet({"version": 2, "columns": [
        {"name": "A"}, {"name": "B"}, {"name": "C"}], "rows": rows})
    kept = SheetEvaluator(sheet)
    sheet.rows[500][0] = "7"
    start = time.perf_counter()
    got = kept.update(sheet, [(500, 0)])
    assert time.perf_counter() - start < 0.05
    assert got.values[500][2] == 15
