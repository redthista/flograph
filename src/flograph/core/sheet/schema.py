"""Grid schema for the Table node: typed columns plus string cells.

The persisted form (the node's ``data`` param) is JSON:

    {"version": 2,
     "columns": [{"name": "Price", "type": "number"}, ...],
     "rows": [["1.5", "=A1*2"], ...]}

Cells are always strings — literal entry text or a formula source starting
with ``=``. Computed values are never persisted; they are re-derived from
the sources on every evaluation. :func:`parse_sheet` also accepts the older
v1 shape (``{"columns": ["A"], "rows": [...]}``, plain string column names)
and arbitrary junk, falling back to a minimal empty grid.
"""
from __future__ import annotations

import json
import string
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

COLUMN_TYPES = ("auto", "text", "number", "integer", "date", "bool")

_DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
                 "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y",
                 "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%y", "%m/%d/%y",
                 "%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y",
                 "%b %d, %Y", "%B %d, %Y",
                 "%d-%b-%y", "%d-%b-%Y", "%d-%B-%y", "%d-%B-%Y")

# user-supplied strptime patterns (Settings > Table Node), tried first so
# they win over the built-ins for ambiguous input
_extra_date_formats: tuple[str, ...] = ()


def set_extra_date_formats(formats) -> None:
    global _extra_date_formats
    _extra_date_formats = tuple(
        str(f).strip() for f in formats if str(f).strip())


def extra_date_formats() -> tuple[str, ...]:
    return _extra_date_formats


def normalize_date(text) -> Optional[str]:
    """Recognised date text normalized to ISO (YYYY-MM-DD, keeping a time
    part when present), or None when it isn't a date we can read.
    Custom formats are tried before the built-ins; day-first formats win
    over month-first for ambiguous dates."""
    text = ("" if text is None else str(text)).strip()
    if not text:
        return None
    for fmt in (*_extra_date_formats, *_DATE_FORMATS):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if parsed.hour or parsed.minute or parsed.second:
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        return parsed.strftime("%Y-%m-%d")
    return None


def is_formula(text) -> bool:
    """A cell holds a formula when it starts with "=" (a lone "=" is text)."""
    return isinstance(text, str) and text.startswith("=") and text != "="


def next_column_name(existing: list[str]) -> str:
    """First free single letter, then C1, C2, ... (matches the historic
    behaviour of the canvas card)."""
    for letter in string.ascii_uppercase:
        if letter not in existing:
            return letter
    i = 1
    while f"C{i}" in existing:
        i += 1
    return f"C{i}"


@dataclass
class ColumnSpec:
    name: str
    type: str = "auto"
    width: Optional[int] = None   # editor column width in px; None = default


@dataclass
class Sheet:
    columns: list[ColumnSpec] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)

    @property
    def n_rows(self) -> int:
        return len(self.rows)

    @property
    def n_cols(self) -> int:
        return len(self.columns)

    def column_names(self) -> list[str]:
        return [col.name for col in self.columns]

    def cell(self, row: int, col: int) -> str:
        return self.rows[row][col]

    def set_cell(self, row: int, col: int, text) -> None:
        self.rows[row][col] = "" if text is None else str(text)

    # ------------------------------------------------------ structural ops

    def insert_rows(self, at: int, count: int = 1) -> None:
        at = max(0, min(at, self.n_rows))
        for _ in range(count):
            self.rows.insert(at, ["" for _ in self.columns])

    def insert_column(self, at: int, name: Optional[str] = None,
                      col_type: str = "auto") -> str:
        at = max(0, min(at, self.n_cols))
        if not name:
            name = next_column_name(self.column_names())
        self.columns.insert(at, ColumnSpec(str(name), col_type))
        for row in self.rows:
            row.insert(at, "")
        return name

    def remove_rows(self, indices) -> None:
        for i in sorted(set(indices), reverse=True):
            if 0 <= i < len(self.rows):
                del self.rows[i]

    def remove_columns(self, indices) -> None:
        for i in sorted(set(indices), reverse=True):
            if 0 <= i < len(self.columns):
                del self.columns[i]
                for row in self.rows:
                    del row[i]

    def rename_column(self, index: int, name: str) -> None:
        self.columns[index].name = str(name)

    def set_column_type(self, index: int, col_type: str) -> None:
        if col_type not in COLUMN_TYPES:
            valid = ", ".join(COLUMN_TYPES)
            raise ValueError(f"unknown column type {col_type!r} (valid: {valid})")
        self.columns[index].type = col_type

    def ensure_size(self, n_rows: int, n_cols: int) -> None:
        """Grow (never shrink) to hold at least n_rows x n_cols cells."""
        while self.n_cols < n_cols:
            self.insert_column(self.n_cols)
        if self.n_rows < n_rows:
            self.insert_rows(self.n_rows, n_rows - self.n_rows)

    def sort_by(self, col: int, ascending: bool = True) -> None:
        """Reorder rows by a column, numbers before text, blanks last.

        Formula references are NOT rewritten — like a plain Excel sort,
        formulas keep pointing at the same cell addresses.
        """
        if not 0 <= col < self.n_cols:
            return

        def key(row: list[str]):
            text = row[col].strip()
            if text == "":
                return (2, 0.0, "")
            try:
                return (0, float(text), "")
            except ValueError:
                return (1, 0.0, text.casefold())

        self.rows.sort(key=key, reverse=not ascending)

    def copy(self) -> "Sheet":
        return Sheet(
            columns=[ColumnSpec(c.name, c.type, c.width) for c in self.columns],
            rows=[list(row) for row in self.rows],
        )


def parse_sheet(raw) -> Sheet:
    """Tolerant reader: v2 dicts, v1 string-column dicts, JSON strings of
    either, or junk (falls back to a minimal grid)."""
    if isinstance(raw, Sheet):
        return raw
    parsed = raw if isinstance(raw, dict) else None
    if parsed is None:
        try:
            parsed = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}

    columns_raw = parsed.get("columns")
    if not isinstance(columns_raw, list) or not columns_raw:
        columns_raw = ["A", "B"]
    columns: list[ColumnSpec] = []
    for entry in columns_raw:
        if isinstance(entry, dict):
            name = entry.get("name")
            name = str(name) if name not in (None, "") else next_column_name(
                [c.name for c in columns])
            col_type = entry.get("type")
            width = entry.get("width")
            width = int(width) if isinstance(width, (int, float)) and width > 0 else None
            columns.append(ColumnSpec(
                name, col_type if col_type in COLUMN_TYPES else "auto", width))
        else:
            columns.append(ColumnSpec(str(entry)))

    rows_raw = parsed.get("rows")
    if not isinstance(rows_raw, list) or not rows_raw:
        rows_raw = [["" for _ in columns]]
    rows: list[list[str]] = []
    for row in rows_raw:
        if not isinstance(row, (list, tuple)):
            continue
        fixed = [str(v) if v is not None else "" for v in row][:len(columns)]
        fixed += [""] * (len(columns) - len(fixed))
        rows.append(fixed)
    if not rows:
        rows = [["" for _ in columns]]
    return Sheet(columns, rows)


def sheet_to_dict(sheet: Sheet) -> dict:
    columns = []
    for col in sheet.columns:
        entry = {"name": col.name, "type": col.type}
        if col.width:
            entry["width"] = int(col.width)
        columns.append(entry)
    return {
        "version": 2,
        "columns": columns,
        "rows": [list(row) for row in sheet.rows],
    }


def sheet_to_json(sheet: Sheet) -> str:
    return json.dumps(sheet_to_dict(sheet))


def validate_cell(text, col_type: str) -> Optional[str]:
    """Why a literal cell doesn't fit its column type, or None when it does.
    Blank cells and formulas always pass (formulas are checked at eval)."""
    text = ("" if text is None else str(text)).strip()
    if not text or is_formula(text) or col_type in ("auto", "text"):
        return None
    if col_type == "number":
        try:
            float(text)
            return None
        except ValueError:
            return f"{text!r} is not a number"
    if col_type == "integer":
        try:
            int(text)
            return None
        except ValueError:
            return f"{text!r} is not a whole number"
    if col_type == "date":
        if normalize_date(text) is not None:
            return None
        return f"{text!r} is not a recognised date (try YYYY-MM-DD)"
    if col_type == "bool":
        if text.upper() in ("TRUE", "FALSE"):
            return None
        return f"{text!r} is not TRUE/FALSE"
    return None
