"""Restored frames are re-laid-out, never re-interpreted.

pandas can hold a string column as Python objects or in an Arrow buffer. Old
cache blobs carry the Python layout, which on real project caches costs about
two-thirds more memory for identical data. Converting it is worth doing on the
way back off disk — but only as a change of *storage*. The tests that matter
here are the ones pinning what must NOT change.
"""
import numpy as np
import pandas as pd
import pytest

from flograph.engine import frames
from flograph.engine.frames import arrow_available, normalize_strings

pytestmark = pytest.mark.skipif(
    not arrow_available(), reason="pyarrow is an optional extra")


def python_backed(values, na_value=np.nan):
    return pd.Series(values).astype(
        pd.StringDtype(storage="python", na_value=na_value))


class TestStorageChanges:
    def test_switches_a_column_to_arrow(self):
        df = pd.DataFrame({"email": python_backed(["a@b.com", "c@d.com"])})
        assert df["email"].dtype.storage == "python"

        out = normalize_strings(df)
        assert out["email"].dtype.storage == "pyarrow"

    def test_it_actually_gets_smaller(self):
        """The whole reason this exists."""
        values = [f"user{i}@example-domain.com" for i in range(20_000)]
        df = pd.DataFrame({"email": python_backed(values)})
        before = df.memory_usage(deep=True).sum()
        after = normalize_strings(df).memory_usage(deep=True).sum()
        assert after < before

    def test_recurses_into_an_outputs_dict(self):
        outputs = {"table": pd.DataFrame({"s": python_backed(["x", "y"])})}
        assert normalize_strings(outputs)["table"]["s"].dtype.storage == "pyarrow"

    def test_recurses_into_a_list_of_frames(self):
        payload = [pd.DataFrame({"s": python_backed(["x"])}) for _ in range(2)]
        for frame in normalize_strings(payload):
            assert frame["s"].dtype.storage == "pyarrow"

    def test_handles_a_bare_series(self):
        assert normalize_strings(python_backed(["x"])).dtype.storage == "pyarrow"


class TestMeaningDoesNotChange:
    def test_values_survive(self):
        df = pd.DataFrame({"s": python_backed(["alpha", "beta", "gamma"])})
        out = normalize_strings(df)
        assert list(out["s"]) == ["alpha", "beta", "gamma"]

    def test_na_value_is_carried_across(self):
        """The trap. `astype("string[pyarrow]")` is the obvious way to write
        this and it silently flips the missing value from nan to pd.NA, which
        changes how every downstream node sees missing data."""
        df = pd.DataFrame({"s": python_backed(["a", None], na_value=np.nan)})
        assert df["s"].dtype.na_value is np.nan

        out = normalize_strings(df)
        assert out["s"].dtype.na_value is np.nan
        assert out["s"].isna().tolist() == [False, True]

    def test_pd_na_columns_keep_pd_na(self):
        df = pd.DataFrame({"s": pd.Series(["a", None], dtype=pd.StringDtype(
            storage="python", na_value=pd.NA))})
        out = normalize_strings(df)
        assert out["s"].dtype.na_value is pd.NA

    def test_comparisons_keep_their_result_dtype(self):
        df = pd.DataFrame({"s": python_backed(["a", "b"])})
        before = (df["s"] == "a").dtype
        after = (normalize_strings(df)["s"] == "a").dtype
        assert before == after

    def test_object_columns_are_left_alone(self):
        """object -> string is a change of meaning, not of layout: nan becomes
        pd.NA and comparisons start returning `boolean`. Never do it."""
        df = pd.DataFrame({"mixed": pd.Series(["a", 1, None], dtype=object)})
        out = normalize_strings(df)
        assert out["mixed"].dtype == object
        assert out["mixed"].tolist() == ["a", 1, None]

    def test_numeric_columns_are_left_alone(self):
        df = pd.DataFrame({"n": [1, 2, 3], "f": [1.5, 2.5, 3.5]})
        out = normalize_strings(df)
        assert out["n"].dtype == np.int64
        assert out["f"].dtype == np.float64


class TestNeverRaises:
    def test_no_op_without_pyarrow(self, monkeypatch):
        monkeypatch.setattr(frames, "arrow_available", lambda: False)
        df = pd.DataFrame({"s": python_backed(["x"])})
        assert normalize_strings(df)["s"].dtype.storage == "python"

    def test_a_hostile_value_comes_back_unchanged(self):
        class Awkward:
            @property
            def columns(self):
                raise RuntimeError("no")

        value = Awkward()
        assert normalize_strings(value) is value

    def test_values_it_knows_nothing_about(self):
        for value in (None, 42, "text", b"bytes"):
            assert normalize_strings(value) == value
