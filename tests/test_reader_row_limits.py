"""Max rows on the readers that were missing it.

Working against a slice of something large is meant to be a deliberate
choice made at the step that reads the data — not something the app decides
behind your back, which for a flow whose whole job is showing real numbers
would be the wrong kind of helpful. read_csv, read_excel and read_json
already had this; Parquet and SQLite are the two where the big files
actually live.
"""
import sqlite3

import pandas as pd
import pytest

from flograph.core import compile_run
from tests.conftest import FakeContext


def frame(rows=50):
    return pd.DataFrame({"n": range(rows), "name": [f"r{i}" for i in range(rows)]})


def call(registry, type_id, **params):
    spec = registry.get(type_id)
    run = compile_run(spec.source, f"test-{type_id}")
    merged = spec.default_params()
    merged.update(params)
    return run(FakeContext(params=merged))


class TestSqlite:
    @pytest.fixture
    def db(self, tmp_path):
        path = tmp_path / "data.sqlite"
        with sqlite3.connect(path) as conn:
            frame().to_sql("rows", conn, index=False)
        return str(path)

    def test_table_mode_limits(self, registry, db):
        out = call(registry, "flograph.io.read_sqlite", path=db,
                   source="table", table="rows", nrows=5)
        assert len(out) == 5
        assert out["n"].tolist() == list(range(5))

    def test_query_mode_limits(self, registry, db):
        """The user's SQL is left alone and the rows are trimmed after."""
        out = call(registry, "flograph.io.read_sqlite", path=db,
                   source="query", query="SELECT * FROM rows", nrows=7)
        assert len(out) == 7

    def test_a_complicated_query_still_works(self, registry, db):
        """Why query mode trims rather than wrapping the statement: bolting a
        LIMIT onto somebody else's SQL breaks the moment it stops being a
        plain SELECT."""
        out = call(registry, "flograph.io.read_sqlite", path=db,
                   source="query",
                   query="WITH evens AS (SELECT * FROM rows WHERE n % 2 = 0) "
                         "SELECT * FROM evens",
                   nrows=4)
        assert len(out) == 4
        assert out["n"].tolist() == [0, 2, 4, 6]

    def test_zero_still_means_all(self, registry, db):
        out = call(registry, "flograph.io.read_sqlite", path=db,
                   source="table", table="rows", nrows=0)
        assert len(out) == 50

    def test_a_limit_beyond_the_end_is_not_an_error(self, registry, db):
        out = call(registry, "flograph.io.read_sqlite", path=db,
                   source="table", table="rows", nrows=500)
        assert len(out) == 50

    def test_a_table_name_with_a_quote_still_quotes(self, registry, tmp_path):
        """The limit is appended to SQL this node builds, so the quoting that
        was already there has to keep working around it."""
        path = tmp_path / "odd.sqlite"
        with sqlite3.connect(path) as conn:
            frame(9).to_sql('we"ird', conn, index=False)
        out = call(registry, "flograph.io.read_sqlite", path=str(path),
                   source="table", table='we"ird', nrows=3)
        assert len(out) == 3


class TestParquet:
    @pytest.fixture
    def path(self, tmp_path):
        target = tmp_path / "data.parquet"
        try:
            frame().to_parquet(target)
        except Exception as exc:                      # pragma: no cover
            pytest.skip(f"no parquet engine: {exc}")
        return str(target)

    def test_it_limits(self, registry, path):
        out = call(registry, "flograph.io.read_parquet", path=path, nrows=6)
        assert len(out) == 6
        assert out["n"].tolist() == list(range(6))

    def test_zero_still_means_all(self, registry, path):
        out = call(registry, "flograph.io.read_parquet", path=path, nrows=0)
        assert len(out) == 50

    def test_a_limit_beyond_the_end_is_not_an_error(self, registry, path):
        out = call(registry, "flograph.io.read_parquet", path=path, nrows=500)
        assert len(out) == 50

    def test_the_slice_is_its_own_frame(self, registry, path):
        """head() gives a view; a node's output is cached and handed to
        several downstream branches, so it has to own its data."""
        out = call(registry, "flograph.io.read_parquet", path=path, nrows=5)
        out.loc[out.index[0], "n"] = -1        # must not warn or reach a parent
        assert out["n"].iloc[0] == -1
