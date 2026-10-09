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
import math
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
    # what reads as a date has changed: forget what was worked out
    _date_cache.clear()
    from .values import clear_date_cache
    clear_date_cache()


# text -> its ISO date (or None). Reading a date tries up to two dozen
# strptime patterns, and a big sheet asks about the same few texts over
# and over, every recalculation. Cleared when the formats change.
_date_cache: dict = {}
_DATE_CACHE_MAX = 50_000


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
    try:
        return _date_cache[text]
    except KeyError:
        pass
    result = _normalize_date(text)
    if len(_date_cache) >= _DATE_CACHE_MAX:
        _date_cache.clear()
    _date_cache[text] = result
    return result


def _normalize_date(text: str) -> Optional[str]:
    for fmt in (*_extra_date_formats, *_DATE_FORMATS):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if parsed.hour or parsed.minute or parsed.second:
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        return parsed.strftime("%Y-%m-%d")
    return None


_TRUEISH = {"true", "1", "yes", "y", "t"}
_FALSEISH = {"false", "0", "no", "n", "f", ""}


def _finite_float(text: str) -> float:
    """``float(text)`` but ``nan`` / ``inf`` / ``1e999`` count as unparseable.

    A non-finite sort key breaks ``list.sort``'s total ordering and scrambles
    the whole column, so those cells are treated like any other non-number.
    """
    value = float(text)  # raises ValueError on non-numeric text
    if not math.isfinite(value):
        raise ValueError(text)
    return value


def _sort_key(text: str, col_type: str) -> tuple[bool, int, float, str]:
    """Sort key for one cell: ``(present, rank, number, text)``.

    ``present`` is False for blank/unparseable cells (they sort last).
    ``rank`` only matters for ``auto`` columns, where it keeps numbers
    before dates before text.
    """
    if text == "":
        return (False, 0, 0.0, "")

    if col_type in ("number", "integer"):
        try:
            return (True, 0, _finite_float(text), "")
        except ValueError:
            return (False, 0, 0.0, "")
    if col_type == "bool":
        low = text.casefold()
        if low in _TRUEISH:
            return (True, 0, 1.0, "")
        if low in _FALSEISH:
            return (True, 0, 0.0, "")
        return (False, 0, 0.0, "")
    if col_type == "date":
        iso = normalize_date(text)
        return (True, 0, 0.0, iso) if iso else (False, 0, 0.0, "")
    if col_type == "text":
        return (True, 0, 0.0, text.casefold())

    # auto: sort each value as whatever it looks like
    try:
        return (True, 0, _finite_float(text), "")
    except ValueError:
        pass
    iso = normalize_date(text)
    if iso:
        return (True, 1, 0.0, iso)
    return (True, 2, 0.0, text.casefold())


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
    # A dropdown list: the cell editor offers these values. ``strict``
    # flags anything else red, like Excel's data validation "Stop"; off, the
    # list is a suggestion and other values are welcome.
    choices: list[str] = field(default_factory=list)
    strict: bool = False
    # How the column's values read (core/sheet/numfmt.py) — display only;
    # None is General. Never changes a value or what flows on.
    format: Optional[dict] = None
    # What the Total Row shows under this column (core/table_totals
    # AGGREGATIONS: "sum", "average", "count", …), or None for nothing.
    total: Optional[str] = None
    # Data validation (core/sheet/validation.py): limits a typed value must
    # keep, whether it may be blank, a hint and an error text. Flags or
    # turns away; never changes a value or what flows on.
    validation: Optional[dict] = None
    # Hidden by the user (right-click ▸ Hide): still there, still sent on,
    # just out of sight in the grid.
    hidden: bool = False


@dataclass
class Sheet:
    columns: list[ColumnSpec] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    # Freeze panes: this many data rows / columns stay put while the rest
    # scrolls. View state, but it belongs to the table, so it is saved.
    freeze_rows: int = 0
    freeze_cols: int = 0
    # Excel's Total Row: a row of totals under the grid. Display only — it
    # is never part of the table the node sends on.
    show_totals: bool = False
    # Notes — Excel's red corner and hover box: (row, col) -> text. Each
    # follows its cell through sorts, moves, inserts and deletes; none is
    # part of what the node sends on.
    notes: dict = field(default_factory=dict)
    # Each cell's own look (core/sheet/cellfmt.py): (row, col) -> {"b":
    # True, "fill": "#fde68a", …}. Follows its cell like a note; display
    # only.
    styles: dict = field(default_factory=dict)
    # Grouped rows (core/sheet/outline.py): Excel's outline. The groups
    # are saved; whether each is folded is view state and is not.
    groups: list = field(default_factory=list)
    # Rows hidden by the user (right-click ▸ Hide). Like a hidden column,
    # only out of sight: the rows still go down the flow.
    hidden_rows: set = field(default_factory=set)
    # Rows the user made taller or shorter (drag the row border, Row
    # Height…): row -> pixels. Others are the usual height, or tall enough
    # for their wrapped text.
    row_heights: dict = field(default_factory=dict)

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

    # --------------------------------------------------------------- notes

    def note(self, row: int, col: int) -> str:
        return self.notes.get((row, col), "")

    def set_note(self, row: int, col: int, text) -> None:
        """Write a cell's note; blank text takes it off."""
        text = "" if text is None else str(text).strip()
        if text and 0 <= row < self.n_rows and 0 <= col < self.n_cols:
            self.notes[(row, col)] = text
        else:
            self.notes.pop((row, col), None)

    def _remap_notes(self, where, rows_move: bool = True) -> None:
        """Move every note and cell format to `where(row, col)`; None
        drops it. A change that moves rows (`rows_move`) carries the hidden
        rows along too."""
        if rows_move and self.hidden_rows:
            moved_rows = set()
            for r in self.hidden_rows:
                spot = where(r, -1)
                if spot is not None:
                    moved_rows.add(spot[0])
            self.hidden_rows = moved_rows
        if rows_move and self.row_heights:
            heights = {}
            for r, h in self.row_heights.items():
                spot = where(r, -1)
                if spot is not None:
                    heights[spot[0]] = h
            self.row_heights = heights
        for attr in ("notes", "styles"):
            extras = getattr(self, attr)
            if not extras:
                continue
            moved = {}
            for (r, c), value in extras.items():
                spot = where(r, c)
                if spot is not None:
                    moved[spot] = value
            setattr(self, attr, moved)

    def cell_format(self, row: int, col: int) -> Optional[dict]:
        return self.styles.get((row, col))

    def set_cell_format(self, row: int, col: int, fmt) -> None:
        from .cellfmt import clean
        fmt = clean(fmt)
        if fmt and 0 <= row < self.n_rows and 0 <= col < self.n_cols:
            self.styles[(row, col)] = fmt
        else:
            self.styles.pop((row, col), None)

    def _notes_follow_rows(self, before: list) -> None:
        """After the row lists were reordered (a sort, a move), send each
        note to wherever its row went — rows are the same list objects."""
        if not (self.notes or self.styles or self.hidden_rows
                or self.row_heights):
            return
        place = {id(row): i for i, row in enumerate(self.rows)}

        def where(r, c):
            if r >= len(before):
                return None
            new = place.get(id(before[r]))
            return None if new is None else (new, c)
        self._remap_notes(where)

    # ------------------------------------------------------ structural ops

    def _shift_formulas(self, axis: str, at: int, count: int) -> None:
        """Keep A1 references on the same cells after rows/columns moved
        (see formula.shift_for_structure)."""
        from .formula import shift_for_structure
        for row in self.rows:
            for c, text in enumerate(row):
                if is_formula(text):
                    row[c] = shift_for_structure(text, axis, at, count)

    def insert_rows(self, at: int, count: int = 1) -> None:
        at = max(0, min(at, self.n_rows))
        inside = at < self.n_rows   # an append moves no existing cell
        for _ in range(count):
            self.rows.insert(at, ["" for _ in self.columns])
        if inside:
            self._shift_formulas("row", at, count)
            self._remap_notes(lambda r, c: (r + count if r >= at else r, c))
            if self.groups:
                from .outline import after_insert
                self.groups = after_insert(self.groups, at, count)

    def insert_column(self, at: int, name: Optional[str] = None,
                      col_type: str = "auto") -> str:
        at = max(0, min(at, self.n_cols))
        inside = at < self.n_cols
        if not name:
            name = next_column_name(self.column_names())
        self.columns.insert(at, ColumnSpec(str(name), col_type))
        for row in self.rows:
            row.insert(at, "")
        if inside:
            self._shift_formulas("col", at, 1)
            self._remap_notes(lambda r, c: (r, c + 1 if c >= at else c),
                              rows_move=False)
        return name

    def remove_rows(self, indices) -> None:
        # highest first, one at a time, so each shift is against the sheet
        # as it stands after the deletions below it
        for i in sorted(set(indices), reverse=True):
            if 0 <= i < len(self.rows):
                del self.rows[i]
                self._shift_formulas("row", i, -1)
                self._remap_notes(lambda r, c, i=i: None if r == i else (
                    r - 1 if r > i else r, c))
                if self.groups:
                    from .outline import after_remove
                    self.groups = after_remove(self.groups, i)
        self.freeze_rows = min(self.freeze_rows, max(self.n_rows - 1, 0))
        if self.groups:
            from .outline import clamp
            self.groups = clamp(self.groups, self.n_rows)

    def remove_columns(self, indices) -> None:
        for i in sorted(set(indices), reverse=True):
            if 0 <= i < len(self.columns):
                del self.columns[i]
                for row in self.rows:
                    del row[i]
                self._shift_formulas("col", i, -1)
                self._remap_notes(lambda r, c, i=i: None if c == i else (
                    r, c - 1 if c > i else c), rows_move=False)
        self.freeze_cols = min(self.freeze_cols, max(self.n_cols - 1, 0))

    def move_rows(self, indices, to: int) -> None:
        """Move rows as a block (in their order) so they start at ``to`` in
        the sheet that results. Formulas keep their addresses, like a sort:
        moving data is not inserting and deleting it."""
        picked = sorted({i for i in indices if 0 <= i < self.n_rows})
        if not picked:
            return
        chosen = set(picked)
        block = [self.rows[i] for i in picked]
        rest = [row for i, row in enumerate(self.rows) if i not in chosen]
        to = max(0, min(to, len(rest)))
        before = self.rows
        self.rows = rest[:to] + block + rest[to:]
        self._notes_follow_rows(before)

    def move_columns(self, indices, to: int) -> None:
        """Move columns as a block to start at ``to`` — header, type, width
        and cells together. Column-name references follow by themselves."""
        picked = sorted({i for i in indices if 0 <= i < self.n_cols})
        if not picked:
            return
        chosen = set(picked)
        keep = [i for i in range(self.n_cols) if i not in chosen]
        to = max(0, min(to, len(keep)))
        order = keep[:to] + picked + keep[to:]
        self.columns = [self.columns[i] for i in order]
        self.rows = [[row[i] for i in order] for row in self.rows]
        new_col = {old: new for new, old in enumerate(order)}
        self._remap_notes(lambda r, c: (r, new_col[c]) if c in new_col
                          else None, rows_move=False)

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

    def set_rows(self, rows: list[list[str]]) -> None:
        """Replace every row wholesale — used to undo a sort back to a
        stored order. Caller guarantees the shape matches. Notes follow
        their rows by content — the stored rows are copies, not the same
        lists."""
        old = self.rows
        self.rows = [list(row) for row in rows]
        if not (self.notes or self.styles or self.hidden_rows
                or self.row_heights):
            return
        waiting: dict[tuple, list[int]] = {}
        for j, row in enumerate(self.rows):
            waiting.setdefault(tuple(row), []).append(j)
        new_of = {}
        for i, row in enumerate(old):
            spots = waiting.get(tuple(row))
            if spots:
                new_of[i] = spots.pop(0)
        self._remap_notes(lambda r, c: (new_of[r], c) if r in new_of
                          else None)

    def sort_by(self, col: int, ascending: bool = True) -> None:
        """Reorder rows by a column, aware of the column's type.

        A ``date`` column sorts chronologically, ``number``/``integer``
        numerically, ``bool`` false-before-true, ``text`` case-insensitive;
        an ``auto`` column sorts each value as whatever it parses as
        (numbers, then dates, then text). Blank and unparseable cells sort
        last in either direction.

        Formula references are NOT rewritten — like a plain Excel sort,
        formulas keep pointing at the same cell addresses.
        """
        if not 0 <= col < self.n_cols:
            return
        col_type = self.columns[col].type

        def key(row: list[str]):
            present, rank, number, text = _sort_key(row[col].strip(), col_type)
            # `present != ascending` keeps blanks/unparseable at the bottom
            # whichever way round the list gets reversed.
            return (present != ascending, rank, number, text)

        before = list(self.rows)
        self.rows.sort(key=key, reverse=not ascending)
        self._notes_follow_rows(before)

    def sort_by_list(self, col: int, ascending: bool = True) -> None:
        """Reorder rows by where each value sits in the column's dropdown
        list (Excel's custom-list sort): North, South, East, West rather
        than alphabetical. Values not on the list follow the listed ones,
        then blanks — in either direction."""
        if not 0 <= col < self.n_cols:
            return
        order: dict[str, int] = {}
        for i, choice in enumerate(self.columns[col].choices):
            order.setdefault(choice.casefold(), i)

        def key(row: list[str]):
            text = row[col].strip()
            if text == "":
                return (2, 0, "")
            place = order.get(text.casefold())
            if place is None:
                return (1, 0, text.casefold())
            return (0, place if ascending else -place, "")

        before = list(self.rows)
        self.rows.sort(key=key)
        self._notes_follow_rows(before)

    def sort_levels(self, levels) -> None:
        """Sort by several columns at once — Excel's Sort dialog.

        ``levels`` is ``[(col, ascending, by_list), ...]``, the most
        important first: rows are ordered by the first level, rows that tie
        on it by the second, and so on. Python's sort is stable, so sorting
        by the last level first and the first level last gives exactly
        that. ``by_list`` sorts by the column's dropdown order (see
        :meth:`sort_by_list`) when it has one.
        """
        valid = [(int(col), bool(asc), bool(by_list))
                 for col, asc, by_list in levels
                 if 0 <= int(col) < self.n_cols]
        for col, ascending, by_list in reversed(valid):
            if by_list and self.columns[col].choices:
                self.sort_by_list(col, ascending)
            else:
                self.sort_by(col, ascending)

    def copy(self) -> "Sheet":
        return Sheet(
            columns=[ColumnSpec(c.name, c.type, c.width, list(c.choices),
                                c.strict,
                                dict(c.format) if c.format else None,
                                c.total,
                                dict(c.validation) if c.validation else None,
                                c.hidden)
                     for c in self.columns],
            rows=[list(row) for row in self.rows],
            freeze_rows=self.freeze_rows, freeze_cols=self.freeze_cols,
            show_totals=self.show_totals, notes=dict(self.notes),
            styles={k: dict(v) for k, v in self.styles.items()},
            groups=[type(g)(g.start, g.end, g.collapsed)
                    for g in self.groups],
            hidden_rows=set(self.hidden_rows),
            row_heights=dict(self.row_heights),
        )


def _total_word(word) -> Optional[str]:
    """A stored Total Row choice, made safe (core/table_totals's names)."""
    if not word:
        return None
    from flograph.core.table_totals import canonical_agg
    return canonical_agg(word)


def _parse_hidden_rows(raw, n_rows: int) -> set:
    rows = {r for r in raw if isinstance(r, int) and not isinstance(r, bool)
            and 0 <= r < n_rows} if isinstance(raw, list) else set()
    return rows if len(rows) < n_rows else set()    # one row stays in sight


ROW_HEIGHT_RANGE = (8, 600)


def _parse_row_heights(raw, n_rows: int) -> dict:
    lo, hi = ROW_HEIGHT_RANGE
    out = {}
    for entry in raw if isinstance(raw, list) else ():
        if (isinstance(entry, (list, tuple)) and len(entry) == 2
                and all(isinstance(v, int) and not isinstance(v, bool)
                        for v in entry) and 0 <= entry[0] < n_rows):
            out[entry[0]] = max(lo, min(hi, entry[1]))
    return out


def _parse_groups(raw, n_rows: int) -> list:
    from .outline import parse
    return parse(raw, n_rows)


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
            choices = entry.get("choices")
            choices = ([str(c) for c in choices if str(c) != ""]
                       if isinstance(choices, list) else [])
            from .numfmt import clean
            from .validation import clean as clean_rule
            columns.append(ColumnSpec(
                name, col_type if col_type in COLUMN_TYPES else "auto", width,
                choices, bool(entry.get("strict")) and bool(choices),
                clean(entry.get("format")), _total_word(entry.get("total")),
                clean_rule(entry.get("validation")),
                entry.get("hidden") is True))
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
    freeze = parsed.get("freeze")
    freeze = freeze if isinstance(freeze, dict) else {}

    def _count(key: str, limit: int) -> int:
        value = freeze.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(0, min(int(value), limit))
        return 0

    notes = {}
    notes_raw = parsed.get("notes")
    for entry in notes_raw if isinstance(notes_raw, list) else ():
        if (isinstance(entry, (list, tuple)) and len(entry) == 3
                and all(isinstance(v, int) and not isinstance(v, bool)
                        for v in entry[:2])
                and 0 <= entry[0] < len(rows)
                and 0 <= entry[1] < len(columns)):
            text = str(entry[2] or "").strip()
            if text:
                notes[(entry[0], entry[1])] = text

    from .cellfmt import clean as clean_format
    styles = {}
    styles_raw = parsed.get("styles")
    for entry in styles_raw if isinstance(styles_raw, list) else ():
        if (isinstance(entry, (list, tuple)) and len(entry) == 3
                and all(isinstance(v, int) and not isinstance(v, bool)
                        for v in entry[:2])
                and 0 <= entry[0] < len(rows)
                and 0 <= entry[1] < len(columns)):
            fmt = clean_format(entry[2])
            if fmt:
                styles[(entry[0], entry[1])] = fmt

    return Sheet(columns, rows,
                 freeze_rows=_count("rows", max(len(rows) - 1, 0)),
                 freeze_cols=_count("cols", max(len(columns) - 1, 0)),
                 show_totals=bool(parsed.get("totals")), notes=notes,
                 styles=styles,
                 groups=_parse_groups(parsed.get("groups"), len(rows)),
                 hidden_rows=_parse_hidden_rows(parsed.get("hidden_rows"),
                                                len(rows)),
                 row_heights=_parse_row_heights(parsed.get("row_heights"),
                                                len(rows)))


def sheet_to_dict(sheet: Sheet) -> dict:
    columns = []
    for col in sheet.columns:
        entry = {"name": col.name, "type": col.type}
        if col.width:
            entry["width"] = int(col.width)
        if col.choices:
            entry["choices"] = list(col.choices)
            if col.strict:
                entry["strict"] = True
        if col.format:
            entry["format"] = dict(col.format)
        if col.total:
            entry["total"] = col.total
        if col.validation:
            entry["validation"] = dict(col.validation)
        if col.hidden:
            entry["hidden"] = True
        columns.append(entry)
    out = {
        "version": 2,
        "columns": columns,
        "rows": [list(row) for row in sheet.rows],
    }
    # written only when set, so a sheet nobody froze saves as it always did
    if sheet.freeze_rows or sheet.freeze_cols:
        out["freeze"] = {"rows": sheet.freeze_rows, "cols": sheet.freeze_cols}
    if sheet.show_totals:
        out["totals"] = True
    if sheet.notes:
        out["notes"] = [[r, c, text]
                        for (r, c), text in sorted(sheet.notes.items())]
    if sheet.styles:
        out["styles"] = [[r, c, dict(fmt)]
                         for (r, c), fmt in sorted(sheet.styles.items())]
    if sheet.hidden_rows:
        out["hidden_rows"] = sorted(sheet.hidden_rows)
    if sheet.row_heights:
        out["row_heights"] = [[r, int(h)] for r, h in
                              sorted(sheet.row_heights.items())]
    if sheet.groups:
        # the ranges only: folding is view state, like a filter
        from .outline import to_list
        out["groups"] = to_list(sheet.groups)
    return out


def sheet_to_json(sheet: Sheet) -> str:
    return json.dumps(sheet_to_dict(sheet))


def validate_cell(text, col_type: str, choices=(),
                  strict: bool = False) -> Optional[str]:
    """Why a literal cell doesn't fit its column, or None when it does.
    Blank cells and formulas always pass (formulas are checked at eval).
    A strict dropdown list turns away anything not on it."""
    text = ("" if text is None else str(text)).strip()
    if text and not is_formula(text) and strict and choices:
        if text.casefold() not in {str(c).strip().casefold()
                                   for c in choices}:
            return f"{text!r} is not on this column's list"
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
