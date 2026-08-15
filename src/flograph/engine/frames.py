"""Storage-level normalisation of restored values.

Pandas can hold a string column two ways: as Python `str` objects, or in an
Arrow buffer. Both are the same dtype and behave identically; only the layout
differs. The Arrow layout is much cheaper -- on a real 2M-row project cache,
unpickling cost 1066 MB resident and normalising brought it to 641 MB.

Old cache blobs carry the Python layout because that is what pandas produced
when they were written; a current `read_csv` already yields the Arrow one. So
this is a migration for values coming back off disk, and it is deliberately
applied *only* there (see engine.cache_persistence): a value that a node just
computed is left exactly as the node produced it, because rewriting a running
node's output is a semantic decision and this module is an optimisation.

The one rule that matters: this changes *storage*, never meaning. A column is
only ever rewritten to the same StringDtype with the same `na_value` and a
different `storage`. The obvious-looking `astype("string[pyarrow]")` is wrong
for exactly this reason -- it also flips `na_value` from `nan` to `pd.NA`,
which changes how every downstream node sees missing data.
"""
from __future__ import annotations

import sys
from typing import Any


def arrow_available() -> bool:
    """Whether pyarrow can back a string column.

    A function rather than a module-level constant so tests can monkeypatch
    it; pyarrow is an optional extra (pyproject "parquet"), so the no-arrow
    path is a real configuration, not a hypothetical one.
    """
    try:
        import pyarrow  # noqa: F401
    except Exception:
        return False
    return True


def _target_dtype(dtype: Any) -> Any:
    """The Arrow-backed twin of `dtype`, or None if it should be left alone.

    Only pandas' own string dtype qualifies. `object` columns are excluded on
    purpose: object -> string is a change of meaning (nan becomes pd.NA,
    comparisons start returning `boolean` instead of `bool`), not a change of
    layout, and doing it behind the user's back would alter results.
    """
    pd = sys.modules.get("pandas")
    if pd is None or not isinstance(dtype, pd.StringDtype):
        return None
    if getattr(dtype, "storage", None) != "python":
        return None
    # Carry na_value across unchanged -- that is what keeps this a storage
    # change. Older pandas has no na_value on the dtype; there it is pd.NA.
    try:
        return pd.StringDtype(storage="pyarrow", na_value=dtype.na_value)
    except TypeError:
        return pd.StringDtype(storage="pyarrow")


def _normalize_frame(df: Any) -> Any:
    """Rewrite the Python-backed string columns of `df` in place.

    Column at a time, letting each old column go before taking the next. A
    whole-frame `.astype()` would hold both layouts of every column at once,
    which on the frames this exists for is a multi-GB spike in the middle of
    the operation meant to reduce memory.
    """
    for name in list(df.columns):
        # Duplicate column labels give back a frame, not a series, and there
        # is no single dtype to switch -- leave those alone rather than
        # guessing which one was meant.
        col = df[name]
        if getattr(col, "ndim", 1) != 1:
            continue
        target = _target_dtype(col.dtype)
        if target is None:
            continue
        try:
            df[name] = col.astype(target)
        except Exception:
            continue
    return df


def normalize_strings(value: Any) -> Any:
    """Best-effort storage normalisation of a node's cached outputs.

    Best-effort is load-bearing, exactly as it is for cache.estimate_size:
    this runs in the restore path, so anything it cannot convert is worth
    leaving alone, never raising. A cache that loads slightly fatter is a
    non-event; a cache that fails to load is a lost result.

    Recurses one level into the containers node outputs actually use (the
    outputs dict itself, and ports carrying a list of frames).
    """
    if not arrow_available():
        return value
    try:
        return _normalize(value)
    except Exception:
        return value


def _normalize(value: Any) -> Any:
    pd = sys.modules.get("pandas")
    if pd is None:
        return value
    if isinstance(value, pd.DataFrame):
        return _normalize_frame(value)
    if isinstance(value, pd.Series):
        target = _target_dtype(value.dtype)
        return value.astype(target) if target is not None else value
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_normalize(v) for v in value)
    return value
