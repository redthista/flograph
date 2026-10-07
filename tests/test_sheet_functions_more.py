"""The wider function library, through real formulas on a real sheet:
lookups, conditional aggregates, IFERROR and the IS… checks, maths, text and
dates, and date arithmetic."""
from datetime import date

import pytest

from flograph.core.sheet import (FUNCTION_CATEGORIES, FUNCTION_HELP,
                                 FUNCTION_NAMES, evaluate_sheet, parse_sheet)
from flograph.core.sheet.values import FormulaError

# Region  Product  Units  Price   Date
ROWS = [
    ["North", "Widget", "10", "2.5", "2026-01-05"],
    ["South", "Gadget", "4", "9.99", "2026-01-12"],
    ["North", "Gizmo", "7", "14", "2026-02-01"],
    ["East", "Widget", "", "2.5", "2026-03-15"],
    ["South", "Widget", "20", "2.5", "2026-03-31"],
]


def calc(formula):
    """Evaluate `formula` in a spare column of the table above."""
    sheet = parse_sheet({
        "columns": [{"name": n} for n in
                    ("Region", "Product", "Units", "Price", "Date", "X")],
        "rows": [row + [""] for row in ROWS]})
    sheet.rows[0][5] = formula
    result = evaluate_sheet(sheet)
    return result.values[0][5]


@pytest.mark.parametrize("formula,want", [
    # conditional aggregates
    ('=SUMIF([Region], "North", [Units])', 17.0),
    ('=SUMIF(C1:C5, ">5")', 37.0),
    ('=SUMIFS([Units], [Region], "South", [Product], "Wid*")', 20.0),
    ('=COUNTIF([Product], "Widget")', 3.0),
    ('=COUNTIF([Units], "<>")', 4.0),
    ('=COUNTIFS([Region], "North", [Price], ">=10")', 1.0),
    ('=AVERAGEIF([Product], "Widget", [Price])', 2.5),
    ('=MAXIFS([Units], [Region], "North")', 10.0),
    ('=MINIFS([Price], [Product], "<>Widget")', 9.99),
    ("=COUNTBLANK(C1:C5)", 1.0),
    ('=COUNTIF([Date], ">2026-02-01")', 2.0),
    # lookups
    ('=VLOOKUP("Gizmo", B1:D5, 3, FALSE)', 14.0),
    ('=XLOOKUP("Gadget", [Product], [Region])', "South"),
    ('=XLOOKUP("Nope", [Product], [Region], "none")', "none"),
    ('=MATCH("East", [Region], 0)', 4.0),
    ("=INDEX(A1:D5, 3, 2)", "Gizmo"),
    ("=INDEX([Product], 2)", "Gadget"),
    ('=CHOOSE(2, "lo", "mid", "hi")', "mid"),
    ("=VLOOKUP(5, {}, 2)".format("C1:D2"), FormulaError("#N/A")),
    # logic and errors
    ("=IFERROR(1/0, 99)", 99.0),
    ('=IFNA(MATCH("zz", [Region], 0), "missing")', "missing"),
    ('=IFS(C1>50, "big", C1>5, "mid", TRUE, "small")', "mid"),
    ('=SWITCH(A1, "South", 1, "North", 2, 0)', 2.0),
    ("=ISBLANK(C4)", True),
    ("=ISNUMBER(C1)", True),
    ("=ISTEXT(A1)", True),
    ("=ISERROR(1/0)", True),
    ("=XOR(TRUE, FALSE)", True),
    # maths
    ("=ROUNDUP(2.341, 1)", 2.4),
    ("=ROUNDDOWN(-2.349, 2)", -2.34),
    ("=INT(-2.5)", -3.0),
    ("=SUMPRODUCT([Units], [Price])", 25 + 39.96 + 98 + 50),
    ("=MEDIAN(C1:C5)", 8.5),
    ("=LARGE([Units], 2)", 10.0),
    ("=SMALL([Units], 1)", 4.0),
    ("=RANK(C3, [Units])", 3.0),
    ("=LOG(8, 2)", 3.0),
    ("=PRODUCT(2, 3, 4)", 24.0),
    # text
    ('=SUBSTITUTE("a-b-c", "-", " ")', "a b c"),
    ('=SUBSTITUTE("a-b-c", "-", " ", 2)', "a-b c"),
    ('=FIND("g", "Gadget")', 4.0),
    ('=SEARCH("g", "Gadget")', 1.0),
    ('=REPLACE("Widget", 1, 3, "Gad")', "Gadget"),
    ('=PROPER("hello wide world")', "Hello Wide World"),
    ('=REPT("ab", 3)', "ababab"),
    ('=TEXTJOIN(", ", TRUE, A1:A3)', "North, South, North"),
    ('=VALUE("£1,200")', 1200.0),
    ('=VALUE("25%")', 0.25),
    ('=TEXT(1234.5, "#,##0.00")', "1,234.50"),
    ('=TEXT(0.256, "0.0%")', "25.6%"),
    ('=TEXT(E1, "dd/mm/yyyy")', "05/01/2026"),
    ('=TEXT(E1, "d mmm yyyy")', "5 Jan 2026"),
    ('=EXACT("a", "A")', False),
    # dates
    ("=DATE(2026, 13, 1)", "2027-01-01"),
    ("=DATE(2026, 3, 0)", "2026-02-28"),
    ("=YEAR(E1)", 2026.0),
    ("=MONTH(E3)", 2.0),
    ("=DAY(E5)", 31.0),
    ("=WEEKDAY(E1)", 2.0),           # 5 Jan 2026 is a Monday
    ("=WEEKDAY(E1, 2)", 1.0),
    ("=EDATE(E5, 1)", "2026-04-30"),
    ("=EOMONTH(E1, 1)", "2026-02-28"),
    ("=DAYS(E2, E1)", 7.0),
    ('=DATEDIF("2020-05-10", "2026-03-01", "Y")', 5.0),
    ('=DATEDIF("2020-05-10", "2026-03-01", "YM")', 9.0),
    ("=NETWORKDAYS(E1, E2)", 6.0),
    # date arithmetic
    ("=E1+7", "2026-01-12"),
    ("=E2-E1", 7.0),
    ("=E3-1", "2026-01-31"),
    ('=E1="5/1/2026"', True),
])
def test_formula(formula, want):
    got = calc(formula)
    if isinstance(want, FormulaError):
        assert isinstance(got, FormulaError) and got.code == want.code
    elif isinstance(want, float):
        assert got == pytest.approx(want)
    else:
        assert got == want


def test_today():
    assert calc("=TODAY()") == date.today().isoformat()


def test_lookup_ignores_errors_elsewhere_in_the_table():
    sheet = parse_sheet({"columns": [{"name": "k"}, {"name": "v"},
                                     {"name": "x"}],
                         "rows": [["a", "=1/0", ""], ["b", "2", ""],
                                  ["", "", '=VLOOKUP("b", A1:B2, 2, FALSE)']]})
    assert evaluate_sheet(sheet).values[2][2] == 2.0


def test_every_function_is_documented_in_a_category():
    documented = {entry[0] for entry in FUNCTION_HELP}
    assert set(FUNCTION_NAMES) - {"AVG"} <= documented   # AVG: an alias
    assert all(entry[4] in FUNCTION_CATEGORIES for entry in FUNCTION_HELP)
    assert len(FUNCTION_NAMES) > 90
