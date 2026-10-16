"""What the Flo Assistant may see of your data (Qt-free).

Everything the assistant sends to a model about a flow is built here, so
"what left the machine" has one answer and one set of tests. The rule this
module exists for: **the level is enforced by what can be built, not by
asking the model to behave.** A tool that would need more than the level
allows is not offered (`flo.tools` asks `allows()`), and every string that
does go out passes through `scrub()`.

Two settings, both saved in the flow (`Privacy`), so a flow handed to
someone carries its rules:

- **The level** — what Flo can see of the data:
  - *Nothing from my data* (STRUCTURE): the flow's layout only. No column
    names — any known name in a label, a setting or a message goes as
    `<column>` — and no text typed into settings.
  - *Column names* (SCHEMA, the default): names and types, and settings as
    typed.
  - *Column names and summaries* (PROFILE): also, per column, how much is
    empty, how many distinct values, the lowest and highest value, and what
    it looks like.
  - *All my data* (FULL): the data itself — sample rows with every table,
    `rows()` to read more, the values of every category column, and error
    messages as they are. Only this level sends rows.
- **One rule per column**, on top of the level:
  - *Hidden* — the AI never learns the column exists: it is left out of
    every table description and its name goes as `<column>` everywhere.
  - *Name only* — the default.
  - *Name and values* — also its distinct values (the 100 most common), so
    it can filter on a category by its exact spelling. Not at Nothing.

Whatever the level, password settings never go out and a file path goes as
its file name only. Below All my data, quoted pieces of error messages go as
`<value>`. A Hidden column stays hidden at every level, rows included.

No pandas at module level (the core is imported headless and must stay
light); values are inspected by duck typing on what they offer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

STRUCTURE, SCHEMA, PROFILE, FULL = range(4)
BUILT_MAX = FULL              # the highest level this module can serve
SAMPLE_ROWS = 20              # rows that come with a table at FULL
MAX_ROWS = 200                # rows one rows() call may hand over
_MAX_CELL = 200               # characters of one cell
DEFAULT_LEVEL = SCHEMA
HIDDEN_COLUMN = "<column>"
HIDDEN_SECRET = "<hidden>"

# what each level is called, wherever a person reads it
LEVEL_NAMES = {
    STRUCTURE: "Nothing from my data",
    SCHEMA: "Column names",
    PROFILE: "Column names and summaries",
    FULL: "All my data",
}
# short keys, for the send log
LEVEL_KEYS = {STRUCTURE: "structure", SCHEMA: "schema", PROFILE: "profile",
              FULL: "all"}

# the rule per column
HIDDEN, NAME, VALUES = "hidden", "name", "values"
MODES = (HIDDEN, NAME, VALUES)
MODE_NAMES = {HIDDEN: "Hidden", NAME: "Name only", VALUES: "Name and values"}

# a quoted piece of an error message: 'x' or "x", on one line
_QUOTED = re.compile(r"""(['"])([^'"\n]{1,200})\1""")
# setting types whose value is whatever the user typed
_FREE_TEXT = {"", "string", "text", "date", "auto", "code", "expression"}

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_URL = re.compile(r"^(https?|ftp)://", re.IGNORECASE)
_PHONE = re.compile(r"^\+?[\d\s().-]{7,}$")
_POSTCODE_UK = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", re.IGNORECASE)
_PATHISH = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]|~[\\/]|\.{1,2}[\\/])")


@dataclass
class ColumnRule:
    mode: str = NAME

    def is_default(self) -> bool:
        return self.mode == NAME

    @property
    def hidden(self) -> bool:
        return self.mode == HIDDEN

    @property
    def shares_values(self) -> bool:
        return self.mode == VALUES


@dataclass
class Privacy:
    """A flow's own privacy settings — saved in the .flograph."""
    level: Optional[int] = None                   # None: the default
    columns: dict = field(default_factory=dict)   # real name -> ColumnRule

    @property
    def effective(self) -> int:
        level = DEFAULT_LEVEL if self.level is None else int(self.level)
        return max(STRUCTURE, min(level, BUILT_MAX))

    def mode(self, column: str) -> str:
        rule = self.columns.get(column)
        return rule.mode if rule else NAME

    def names(self, mode: str) -> list[str]:
        return sorted(n for n, r in self.columns.items() if r.mode == mode)

    def is_default(self) -> bool:
        return self.level is None and all(
            rule.is_default() for rule in self.columns.values())

    def to_dict(self) -> dict:
        out: dict = {}
        if self.level is not None:
            out["level"] = self.level
        cols = {name: rule.mode for name, rule in self.columns.items()
                if not rule.is_default()}
        if cols:
            out["columns"] = cols
        return out

    @classmethod
    def from_dict(cls, data: Any) -> "Privacy":
        """Read a flow's settings — and the older, finer-grained ones (a
        sensitive or aliased column, hiding typed text), converted to the
        nearest rule that is at least as private."""
        if not isinstance(data, dict):
            return cls()
        level = data.get("level")
        try:
            level = None if level is None else max(0, min(int(level), BUILT_MAX))
        except (TypeError, ValueError):
            level = None
        if data.get("hide_text"):
            # typed text is only hidden at Nothing now
            level = STRUCTURE
        columns = {}
        for name, raw in (data.get("columns") or {}).items():
            mode = NAME
            if isinstance(raw, str) and raw in MODES:
                mode = raw
            elif isinstance(raw, dict):
                if raw.get("sensitive") or raw.get("alias"):
                    mode = HIDDEN
                elif raw.get("share_values"):
                    mode = VALUES
            columns[str(name)] = ColumnRule(mode)
        return cls(level, columns)


def effective_level(*limits: Optional[int]) -> int:
    """The lowest of the limits given (None ignored), clamped to what is
    built; the default level when none is given."""
    given = [int(x) for x in limits if x is not None]
    level = min(given) if given else DEFAULT_LEVEL
    return max(STRUCTURE, min(level, BUILT_MAX))


def _is_table(value) -> bool:
    return hasattr(value, "columns") and hasattr(value, "dtypes") \
        and hasattr(value, "shape")


def _is_series(value) -> bool:
    return hasattr(value, "dtype") and hasattr(value, "name") \
        and hasattr(value, "isna") and not _is_table(value)


def column_names(value) -> list[str]:
    """The column names a value carries, without touching its data."""
    if _is_table(value):
        return [str(c) for c in value.columns]
    if _is_series(value) and value.name is not None:
        return [str(value.name)]
    return []


def _kind_of(dtype) -> str:
    text = str(dtype).lower()
    if text.startswith("bool"):
        return "bool"
    if "int" in text:
        return "integer"
    if "float" in text or "decimal" in text:
        return "number"
    if "datetime" in text or text.startswith("date") or "timestamp" in text:
        return "datetime"
    if "timedelta" in text or "duration" in text:
        return "duration"
    if "category" in text:
        return "category"
    return "text"


def _plain(value) -> Any:
    """A number or date as JSON-friendly text, without numpy types."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, float):
        return round(value, 6)
    return value if isinstance(value, (int, str, bool)) else str(value)


def _infer_text_kind(series) -> str:
    """What a text column looks like holding, decided here from up to 200
    of its values — only the label leaves the machine."""
    try:
        sample = [str(v) for v in series.dropna().head(200).tolist()]
    except Exception:
        return ""
    if not sample:
        return ""
    for name, pattern in (("email address", _EMAIL), ("web address", _URL),
                          ("UK postcode", _POSTCODE_UK), ("phone number", _PHONE)):
        if sum(bool(pattern.match(v.strip())) for v in sample) >= 0.8 * len(sample):
            return name
    try:
        unique = len(set(sample))
    except TypeError:
        return ""
    if unique <= max(3, len(sample) // 10):
        return "a few repeated values (categories)"
    if unique == len(sample) and len(sample) >= 20:
        return "unique per row (an id or a name)"
    return "free text"


def _plotly_traces(value) -> Optional[list]:
    """(type, name, points) per trace of a Plotly figure, or None."""
    data = getattr(value, "data", None)
    if data is None or not hasattr(value, "layout") or not isinstance(
            data, (list, tuple)):
        return None
    out = []
    for trace in data:
        points = 0
        for key in ("y", "x", "values", "z", "r"):
            seq = getattr(trace, key, None)
            if seq is not None:
                try:
                    points = sum(1 for v in seq if v is not None and v == v)
                except TypeError:
                    points = 0
                break
        out.append((str(getattr(trace, "type", "") or ""),
                    str(getattr(trace, "name", "") or ""), points))
    return out


MAX_SHARED_VALUES = 100


def _shared_values(column) -> dict:
    """A shared column's distinct values, most common first, capped."""
    try:
        counts = column.dropna().astype(str).value_counts()
    except Exception:
        return {}
    values = [v if len(v) <= 80 else v[:77] + "..."
              for v in counts.index[:MAX_SHARED_VALUES]]
    out: dict = {"values": values}
    if len(counts) > MAX_SHARED_VALUES:
        out["values_not_shown"] = int(len(counts) - MAX_SHARED_VALUES)
    return out


class Disclosure:
    """One assistant turn's view of the data: the level and the rule per
    column, applied to everything that goes out."""

    def __init__(self, level: int, privacy: Optional[Privacy] = None,
                 known_columns: Iterable[str] = ()):
        self.level = max(STRUCTURE, min(int(level), BUILT_MAX))
        self.privacy = privacy or Privacy()
        self._known: set[str] = set()
        self._pattern: Optional[re.Pattern] = None
        self._pattern_key: Optional[tuple] = None
        self.learn(self.privacy.columns.keys())
        self.learn(known_columns)

    # -- names ----------------------------------------------------------------

    def allows(self, level: int) -> bool:
        return self.level >= level

    def rule(self, column: str) -> ColumnRule:
        return self.privacy.columns.get(column) or ColumnRule()

    def hides(self, column: str) -> bool:
        """Is this column's name kept from the model?"""
        return self.level < SCHEMA or self.rule(column).hidden

    def learn(self, names: Iterable[str]) -> None:
        """Remember column names so scrub() can catch them anywhere."""
        before = len(self._known)
        self._known.update(str(n) for n in names if str(n).strip())
        if len(self._known) != before:
            self._pattern = None

    def shown_name(self, column: str) -> str:
        return HIDDEN_COLUMN if self.hides(column) else column

    @staticmethod
    def _word_pattern(words: Iterable[str]) -> Optional[re.Pattern]:
        words = sorted({w for w in words if w}, key=len, reverse=True)
        if not words:
            return None
        return re.compile(r"(?<![\w])(" + "|".join(map(re.escape, words))
                          + r")(?![\w])")

    def scrub(self, text: str) -> str:
        """An outgoing string with every name the model may not see — all of
        them at Nothing, the hidden columns otherwise — replaced."""
        if not text:
            return text
        names = {n for n in self._known if self.hides(n)}
        if not names:
            return text
        key = (self.level, frozenset(names))
        if self._pattern is None or self._pattern_key != key:
            self._pattern = self._word_pattern(names)
            self._pattern_key = key
        if self._pattern is None:
            return text
        return self._pattern.sub(HIDDEN_COLUMN, text)

    def unalias(self, value: Any) -> Any:
        """Tool arguments from the model, as given — kept for callers from
        when columns could be renamed for the model."""
        return value

    # -- params ---------------------------------------------------------------

    def param_value(self, value: Any, ptype: str = "") -> Any:
        """A node param as it may be shown."""
        if ptype == "password":
            return HIDDEN_SECRET if value else ""
        if isinstance(value, str) and self.level < SCHEMA \
                and ptype in _FREE_TEXT and value.strip() \
                and not self._only_columns(value):
            # at Nothing, typed text is data too: a filter's "Jane Smith"
            return f"<text, {len(value)} character{'' if len(value) == 1 else 's'}>"
        if isinstance(value, str):
            if ptype.startswith(("file", "folder", "path", "save", "open")) \
                    or (_PATHISH.match(value) and len(value) < 400):
                value = re.split(r"[\\/]", value.rstrip("\\/"))[-1] or value
            return self.scrub(value)
        if isinstance(value, list):
            return [self.param_value(v) for v in value]
        if isinstance(value, dict):
            return {self.scrub(str(k)): self.param_value(v) for k, v in value.items()}
        return value

    def error_text(self, message: str) -> str:
        """A node's error, safe to send. Errors quote the data they choked
        on ("could not convert string to float: 'Jane Smith'"), so every
        quoted piece that is not a column name goes as '<value>'."""
        if self.level >= FULL:
            return self.scrub(message or "")
        def quoted(match: "re.Match") -> str:
            if match.group(2).strip() in self._known:
                return match.group(0)        # scrub() deals with the name
            return f"{match.group(1)}<value>{match.group(1)}"

        return self.scrub(_QUOTED.sub(quoted, message or ""))

    def _only_columns(self, value: str) -> bool:
        """A setting that just names columns ("region" or "a, b")."""
        parts = [part.strip() for part in value.split(",")]
        return any(parts) and all(part in self._known for part in parts if part)

    # -- values ---------------------------------------------------------------

    def describe(self, value: Any) -> dict:
        """A cached output as the level allows: its kind; then its shape and
        the columns it may see; then a summary of each; at FULL, its first
        rows too."""
        if _is_table(value):
            self.learn(column_names(value))
            out: dict = {"kind": "table"}
            if self.level >= SCHEMA:
                shown = [name for name in value.columns
                         if not self.rule(str(name)).hidden]
                out["rows"] = int(value.shape[0])
                out["columns_count"] = len(shown)
                out["columns"] = [self._column(str(name), value[name])
                                  for name in shown]
                if self.level >= FULL and shown:
                    out["sample_rows"] = self._rows(value[shown], 0, SAMPLE_ROWS)
                    if value.shape[0] > SAMPLE_ROWS:
                        out["more_rows"] = (f"{value.shape[0] - SAMPLE_ROWS} "
                                            "more — get_rows reads them")
            return out
        if _is_series(value):
            self.learn(column_names(value))
            out = {"kind": "column"}
            if self.level >= SCHEMA and not self.rule(str(value.name)).hidden:
                out["rows"] = int(len(value))
                out.update(self._column(str(value.name), value))
            return out
        if isinstance(value, bool):
            return {"kind": "bool"}
        if isinstance(value, (int, float)):
            return {"kind": "number"}
        if isinstance(value, str):
            out = {"kind": "text"}
            if self.level >= PROFILE:
                out["length"] = len(value)
            return out
        if isinstance(value, (list, tuple)):
            out = {"kind": "list", "length": len(value)}
            if value and self.level >= SCHEMA:
                out["first_item"] = self.describe(value[0])
            return out
        if isinstance(value, dict):
            out = {"kind": "mapping", "length": len(value)}
            if self.level >= SCHEMA:
                out["keys"] = [self.scrub(str(k)) for k in list(value)[:50]]
            return out
        if value is None:
            return {"kind": "nothing"}
        traces = _plotly_traces(value)
        if traces is not None:
            # what a chart draws, counted: a model can't look at it, and
            # without this an empty chart and a full one read the same
            out = {"kind": "chart", "traces": [
                {"type": kind, "name": self.scrub(name), "points": points}
                for kind, name, points in traces[:20]]}
            if not any(points for _, _, points in traces):
                out["note"] = "the chart draws nothing — check its x and y"
            return out
        return {"kind": type(value).__name__}

    def rows(self, value, start: int = 0, count: int = 50) -> dict:
        """Rows of a table, at FULL only — the hidden columns left out."""
        if self.level < FULL or not _is_table(value):
            return {"error": "rows are only shared at 'All my data'"}
        shown = [name for name in value.columns
                 if not self.rule(str(name)).hidden]
        start = max(0, int(start or 0))
        count = max(1, min(int(count or 50), MAX_ROWS))
        total = int(value.shape[0])
        return {"start": start, "total_rows": total,
                "rows": self._rows(value[shown], start, count) if shown else []}

    @staticmethod
    def _rows(table, start: int, count: int) -> list[dict]:
        out = []
        for _index, row in table.iloc[start:start + count].iterrows():
            record = {}
            for name, cell in row.items():
                try:
                    missing = bool(cell != cell)        # NaN / NaT
                except (TypeError, ValueError):
                    missing = False                     # a list in a cell
                cell = None if missing else _plain(cell)
                if isinstance(cell, str) and len(cell) > _MAX_CELL:
                    cell = cell[:_MAX_CELL - 3] + "..."
                record[str(name)] = cell
            out.append(record)
        return out

    def _column(self, name: str, series) -> dict:
        rule = self.rule(name)
        column = series
        if _is_table(column):            # duplicate column names give a frame
            column = column.iloc[:, 0]
        out: dict = {"name": name,
                     "type": _kind_of(getattr(column, "dtype", ""))}
        if rule.shares_values or (self.level >= FULL and out["type"] in (
                "text", "category", "bool")):
            shared = _shared_values(column)
            # at FULL every category column comes with its values; a column
            # of mostly different values is not a category, and its rows say
            # what it holds
            if rule.shares_values or "values_not_shown" not in shared:
                out.update(shared)
        if self.level < PROFILE:
            return out
        try:
            total = len(column)
            nulls = int(column.isna().sum())
            out["empty_percent"] = round(100.0 * nulls / total, 1) if total else 0.0
            out["distinct"] = int(column.nunique(dropna=True))
        except Exception:
            return out
        kind = out["type"]
        try:
            if kind in ("integer", "number", "datetime", "duration"):
                present = column.dropna()
                if len(present):
                    out["min"], out["max"] = _plain(present.min()), _plain(present.max())
            elif kind in ("text", "category"):
                lengths = column.dropna().astype(str).str.len()
                if len(lengths):
                    out["text_length"] = [int(lengths.min()), int(lengths.max())]
                looks = _infer_text_kind(column)
                if looks:
                    out["looks_like"] = looks
        except Exception:
            pass
        return out
