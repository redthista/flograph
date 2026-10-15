"""What the Flo Assistant may see of your data (Qt-free).

Everything the assistant sends to a model about a flow is built here, so
"what left the machine" has one answer and one set of tests. The rule this
module exists for: **the level is enforced by what can be built, not by
asking the model to behave.** A tool that would need more than the level
allows is not offered (`flo.tools` asks `allows()`), and every string that
does go out passes through `scrub()`.

The levels (`llm.profiles.LEVELS`): 0 structure, 1 schema, 2 profile —
3–5 (look-alike rows, real samples, running nodes) are not built yet and
are clamped to 2 here, so asking for more cannot accidentally get more.

The level in force is the lowest of three: the connection's ceiling (where
the data would go), the flow's own setting (saved in the file, so a flow
handed to someone keeps its "schema only"), and whatever the chat asks for.

Per column, on top of the level:

- **sensitive** — its values never go out at any level: no min/max, no
  inferred kind. The name and type still do, so the model can wire it up.
- **alias** — its *name* never goes out either. The model sees `col_7`
  (and the hint, if one is written) and the tool arguments it sends back
  are translated to the real name before anything runs.

At level 0 no column name goes out at all: any known name in a label, a
param or a description is replaced by `<column>`. Password params never go
out, and a file path goes out as its file name only — a folder path says a
great deal about whose data this is.

No pandas at module level (the core is imported headless and must stay
light); values are inspected by duck typing on what they offer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

STRUCTURE, SCHEMA, PROFILE, LOOKALIKE, SAMPLE, ANALYSE = range(6)
BUILT_MAX = PROFILE           # the highest level this module can serve
HIDDEN_COLUMN = "<column>"
HIDDEN_SECRET = "<hidden>"
# setting types whose value is whatever the user typed
_FREE_TEXT = {"", "string", "text", "date", "auto", "code", "expression"}

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_URL = re.compile(r"^(https?|ftp)://", re.IGNORECASE)
_PHONE = re.compile(r"^\+?[\d\s().-]{7,}$")
_POSTCODE_UK = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", re.IGNORECASE)
_PATHISH = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]|~[\\/]|\.{1,2}[\\/])")


@dataclass
class ColumnRule:
    sensitive: bool = False
    alias: str = ""
    hint: str = ""

    def is_default(self) -> bool:
        return not (self.sensitive or self.alias or self.hint)


@dataclass
class Privacy:
    """A flow's own privacy settings — saved in the .flograph."""
    # The most this flow allows, or None for "whatever the connection
    # allows". Lowering only: the level in force is never above the ceiling.
    level: Optional[int] = None
    columns: dict = field(default_factory=dict)   # real name -> ColumnRule
    # Text typed into settings (a filter's `name == "Jane"`, a date, a
    # query) is data too. On, it goes as `<text, N characters>` unless it
    # is just a column name, which the column rules already cover.
    hide_text: bool = False

    def is_default(self) -> bool:
        return self.level is None and not self.hide_text and all(
            rule.is_default() for rule in self.columns.values())

    def to_dict(self) -> dict:
        out: dict = {}
        if self.level is not None:
            out["level"] = self.level
        if self.hide_text:
            out["hide_text"] = True
        cols = {name: {k: v for k, v in vars(rule).items() if v}
                for name, rule in self.columns.items() if not rule.is_default()}
        if cols:
            out["columns"] = cols
        return out

    @classmethod
    def from_dict(cls, data: Any) -> "Privacy":
        if not isinstance(data, dict):
            return cls()
        level = data.get("level")
        try:
            level = None if level is None else max(0, min(int(level), ANALYSE))
        except (TypeError, ValueError):
            level = None
        columns = {}
        for name, raw in (data.get("columns") or {}).items():
            if isinstance(raw, dict):
                columns[str(name)] = ColumnRule(
                    sensitive=bool(raw.get("sensitive")),
                    alias=str(raw.get("alias") or ""),
                    hint=str(raw.get("hint") or ""))
        return cls(level, columns, bool(data.get("hide_text")))


def effective_level(ceiling: int, flow_level: Optional[int] = None,
                    chat_level: Optional[int] = None) -> int:
    """The lowest of the three, clamped to what is built."""
    level = int(ceiling)
    for lower in (flow_level, chat_level):
        if lower is not None:
            level = min(level, int(lower))
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


class Disclosure:
    """One assistant turn's view of the data: the level, the per-column
    rules, and the translation between real column names and what the
    model is shown."""

    def __init__(self, level: int, privacy: Optional[Privacy] = None,
                 known_columns: Iterable[str] = ()):
        self.level = max(STRUCTURE, min(int(level), BUILT_MAX))
        self.privacy = privacy or Privacy()
        self._known: set[str] = set()
        self._pattern: Optional[re.Pattern] = None
        self._alias_pattern: Optional[re.Pattern] = None
        self.learn(self.privacy.columns.keys())
        self.learn(known_columns)

    # -- names ----------------------------------------------------------------

    def allows(self, level: int) -> bool:
        return self.level >= level

    def rule(self, column: str) -> ColumnRule:
        return self.privacy.columns.get(column) or ColumnRule()

    def learn(self, names: Iterable[str]) -> None:
        """Remember column names so scrub() can catch them anywhere."""
        before = len(self._known)
        self._known.update(str(n) for n in names if str(n).strip())
        if len(self._known) != before:
            self._pattern = None

    def shown_name(self, column: str) -> str:
        if self.level < SCHEMA:
            return HIDDEN_COLUMN
        return self.rule(column).alias or column

    def _aliases(self) -> dict[str, str]:
        return {rule.alias: name for name, rule in self.privacy.columns.items()
                if rule.alias}

    @staticmethod
    def _word_pattern(words: Iterable[str]) -> Optional[re.Pattern]:
        words = sorted({w for w in words if w}, key=len, reverse=True)
        if not words:
            return None
        return re.compile(r"(?<![\w])(" + "|".join(map(re.escape, words))
                          + r")(?![\w])")

    def scrub(self, text: str) -> str:
        """An outgoing string with column names hidden as the level says."""
        if not text:
            return text
        if self.level < SCHEMA:
            names = self._known
        else:
            names = {n for n in self._known if self.rule(n).alias}
        if not names:
            return text
        if self._pattern is None or getattr(self, "_pattern_level", None) != self.level:
            self._pattern = self._word_pattern(names)
            self._pattern_level = self.level
        if self._pattern is None:
            return text
        return self._pattern.sub(lambda m: self.shown_name(m.group(1)), text)

    def unalias(self, value: Any) -> Any:
        """Tool arguments from the model, with aliases back to real names."""
        aliases = self._aliases()
        if not aliases:
            return value
        if self._alias_pattern is None:
            self._alias_pattern = self._word_pattern(aliases)
        pattern = self._alias_pattern

        def walk(item):
            if isinstance(item, str):
                return pattern.sub(lambda m: aliases[m.group(1)], item)
            if isinstance(item, list):
                return [walk(v) for v in item]
            if isinstance(item, dict):
                return {walk(k): walk(v) for k, v in item.items()}
            return item
        return walk(value)

    # -- params ---------------------------------------------------------------

    def param_value(self, value: Any, ptype: str = "") -> Any:
        """A node param as it may be shown."""
        if ptype == "password":
            return HIDDEN_SECRET if value else ""
        if isinstance(value, str) and self.privacy.hide_text \
                and ptype in _FREE_TEXT and value.strip() \
                and not self._only_columns(value):
            return f"<text, {len(value)} characters>"
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

    def _only_columns(self, value: str) -> bool:
        """A setting that just names columns ("region" or "a, b")."""
        parts = [part.strip() for part in value.split(",")]
        return any(parts) and all(part in self._known for part in parts if part)

    # -- values ---------------------------------------------------------------

    def describe(self, value: Any) -> dict:
        """A cached output as the level allows: its kind; then its shape and
        columns; then a profile of each column. Never a row."""
        if _is_table(value):
            self.learn(column_names(value))
            out: dict = {"kind": "table"}
            if self.level >= SCHEMA:
                rows, cols = value.shape
                out["rows"], out["columns_count"] = int(rows), int(cols)
                out["columns"] = [self._column(str(name), value[name])
                                  for name in value.columns]
            return out
        if _is_series(value):
            self.learn(column_names(value))
            out = {"kind": "column"}
            if self.level >= SCHEMA:
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
        return {"kind": type(value).__name__}

    def _column(self, name: str, series) -> dict:
        rule = self.rule(name)
        column = series
        if _is_table(column):            # duplicate column names give a frame
            column = column.iloc[:, 0]
        out: dict = {"name": self.shown_name(name),
                     "type": _kind_of(getattr(column, "dtype", ""))}
        if rule.alias and rule.hint:
            out["hint"] = rule.hint
        if rule.sensitive:
            out["sensitive"] = True
        if self.level < PROFILE:
            return out
        try:
            total = len(column)
            nulls = int(column.isna().sum())
            out["empty_percent"] = round(100.0 * nulls / total, 1) if total else 0.0
            out["distinct"] = int(column.nunique(dropna=True))
        except Exception:
            return out
        if rule.sensitive:
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
