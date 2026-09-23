"""AE3: a table styled a block of rows at a time looks exactly as it did
styled a whole column at a time.

The card now evaluates a rule only for the block of rows being drawn,
with the whole table as `pool_frame`. Anything a rule measures across a
column — its range, a pool, a `by` column, autocolour's wheel, a shared
spark scale — must still come from the whole table, or the first block
and the tenth would disagree about what "green" means. Each rule below
is evaluated both ways and must match cell for cell."""
import numpy as np
import pandas as pd
import pytest

from flograph.core.table_format import (column_stats, evaluate_column,
                                        evaluate_rows, parse_rules,
                                        split_rules)

BLOCK = 7          # small and odd, so blocks end mid-pattern


@pytest.fixture(scope="module")
def frame():
    rng = np.random.default_rng(3)
    n = 60
    df = pd.DataFrame({
        "revenue": rng.normal(1000, 400, n).round(2),
        "units": rng.integers(-20, 200, n),
        "score": rng.integers(0, 100, n),
        "region": rng.choice(["north", "south", "east", "west"], n),
        "status": rng.choice(["ok", "late", "fail"], n),
        "note": rng.choice(["", "call back", "vip"], n),
    })
    for m in range(1, 7):
        df[f"m{m:02d}"] = rng.normal(100, 30, n).round(1)
    df.loc[5, "revenue"] = np.nan
    return df


RULES = [
    "revenue scale green",
    "revenue scale red yellow green",
    "units bar blue",
    "units bar blue only",
    "score icons traffic",
    "score icons arrows reverse",
    "score >= 90 => bg green, bold",
    "status = fail => bg red",
    "region autocolour",
    "region autocolour pill",
    "status iconmap: ok=✓ green, late=! orange, fail=✗ red",
    "region scale green by revenue",
    "region bar blue by units",
    "revenue format $,.0f",
    "region tooltip note",
    "trend spark from m01..m06",
    "trend spark shared from m01..m06",
    "m01 scale green",
]


def _whole(df, column, rule):
    return evaluate_column(df[column], [rule], column_stats(df[column]),
                           frame=df)


def _blocks(df, column, rule):
    stats = column_stats(df[column])
    memo: dict = {}
    out = []
    for start in range(0, len(df), BLOCK):
        rows = df.iloc[start:start + BLOCK]
        out.extend(evaluate_column(rows[column], [rule], stats, frame=rows,
                                   pool_frame=df, memo=memo))
    return out


@pytest.mark.parametrize("line", RULES)
def test_blocks_match_the_whole_column(frame, line):
    df = frame.copy()
    rule = parse_rules(line)[0]
    column = line.split()[0]
    if column not in df.columns:
        df[column] = np.nan       # a spark drawn in a column of its own
    whole = _whole(df, column, rule)
    assert any(style is not None for style in whole), \
        f"{line!r} styled nothing — the comparison would be vacuous"
    assert _blocks(df, column, rule) == whole


def test_row_rules_match_too(frame):
    _cols, rows = split_rules(parse_rules("status = fail => row red"))
    whole = evaluate_rows(frame, rows)
    parts = []
    for start in range(0, len(frame), BLOCK):
        parts.extend(evaluate_rows(frame.iloc[start:start + BLOCK], rows))
    assert parts == whole


def test_a_measurement_is_made_once_per_rule(frame, monkeypatch):
    """The memo is what keeps block evaluation from being worse than
    what it replaced: without it every block re-measured the whole
    column's autocolour wheel."""
    from flograph.core import table_format

    calls = []
    real = table_format.auto_colors
    monkeypatch.setattr(table_format, "auto_colors",
                        lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    _blocks(frame, "region", parse_rules("region autocolour")[0])
    assert len(calls) == 1


def test_a_pooled_rule_matches_too(frame):
    """A matrix heatmap shades every cell column against all of them at
    once (`Rule.pool`, set by core.matrix) — measured on the whole table."""
    rule = parse_rules("m01 scale green")[0]
    rule.pool = ["m01", "m02", "m03", "m04"]
    whole = _whole(frame, "m01", rule)
    assert _blocks(frame, "m01", rule) == whole
    alone = _whole(frame, "m01", parse_rules("m01 scale green")[0])
    assert whole != alone, "the pool changed nothing — the test proves nothing"
