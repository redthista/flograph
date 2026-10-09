"""Sheet evaluation: dependency-ordered formula recalculation.

:func:`evaluate_sheet` works out a whole sheet from scratch, keeping
nothing — what the node's run() uses. :class:`SheetEvaluator` keeps what it
worked out (each formula and what it reads), so after an edit only the
formulas downstream of the changed cells are re-evaluated — what the grid
uses, so typing into a big table stays quick. A randomised test holds the
two to the same answers. What keeps a pass itself quick:

- each distinct formula text is parsed once (a column's formula is one
  text repeated down every row) — formula.parse_formula_cached;
- a range is one node in the dependency graph, depending on the formula
  cells inside it, so a column of ``SUMIF([Region], [@Region], [Total])``
  costs n edges rather than n²;
- a range's values are gathered once per pass and shared by every formula
  that reads it (safe: the graph puts every formula inside a range before
  anything that reads the range), and that shared value carries the
  indexes SUMIF/COUNTIF and the exact lookups build — so a column of them
  is a few scans, not one per row.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import deque
from dataclasses import dataclass, field

from .formula import (FormulaSyntaxError, bind_column_refs, cell_name,
                      evaluate, parse_formula_cached, refs_and_ranges,
                      translate)
from .schema import ColumnSpec, Sheet, is_formula
from .values import (ERR_CYCLE, ERR_REF, ERR_SYNTAX, FormulaError,
                     RangeValue, format_number)


@dataclass
class EvalResult:
    """values[r][c] is the computed cell value (float | str | bool | None,
    or a FormulaError); errors maps (row, col) -> human-readable message
    for every errored cell."""
    values: list
    errors: dict = field(default_factory=dict)


def literal_value(text, col_type: str = "auto"):
    """The value a non-formula cell contributes to formulas: blank -> None,
    numeric text -> float, TRUE/FALSE -> bool, everything else (or any cell
    of a text-typed column) -> the string itself."""
    if text is None:
        return None
    text = str(text)
    stripped = text.strip()
    if stripped == "":
        return None
    if col_type == "text":
        return text
    try:
        number = float(stripped)
    except ValueError:
        pass
    else:
        # float() also accepts "nan"/"inf" words; keep those as plain text
        if number == number and number not in (float("inf"), float("-inf")):
            return number
        return text
    if stripped.upper() == "TRUE":
        return True
    if stripped.upper() == "FALSE":
        return False
    return text


def _dtype_to_column_type(dtype: str) -> str:
    dtype = dtype.lower()
    if "bool" in dtype:
        return "bool"
    if "int" in dtype:
        return "integer"
    if "float" in dtype:
        return "number"
    if "datetime" in dtype:
        return "date"
    if dtype in ("string", "str"):
        return "text"
    return "auto"


def _import_cell_text(value, col_type: str) -> str:
    try:
        if value is None or value != value:   # NaN/NaT; pd.NA raises here
            return ""
    except Exception:
        return ""   # pd.NA refuses comparison — it's a missing value
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        return format_number(value)
    if isinstance(value, int):
        return str(value)
    if col_type == "date" and hasattr(value, "strftime"):
        if getattr(value, "hour", 0) or getattr(value, "minute", 0) \
                or getattr(value, "second", 0):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value.strftime("%Y-%m-%d")
    return str(value)


#: How many rows a Table grid will take from a linked input.
#:
#: A sheet is Python cell objects, not a frame: importing one costs a cell
#: per value, merging holds a second copy, and evaluating holds a third —
#: measured at ~7 GB for 5 million rows of five columns, before anything is
#: drawn, and more for a wider file. Past this the app dies rather than
#: draws, so the node refuses and says so instead. Show Table displays data
#: of any size; this node is a spreadsheet, and a spreadsheet has a size
#: past which it is the wrong tool.
MAX_LINKED_ROWS = 200_000


def sheet_from_dataframe(frame) -> Sheet:
    """Import a pandas DataFrame into a typed Sheet: dtypes map to column
    types and values become cell text (dates as ISO, bools as TRUE/FALSE).
    Duck-typed on purpose — this module must not import pandas."""
    columns = [ColumnSpec(str(name),
                          _dtype_to_column_type(str(frame[name].dtype)))
               for name in list(frame.columns)]
    rows = [[_import_cell_text(value, col.type)
             for value, col in zip(record, columns)]
            for record in frame.itertuples(index=False, name=None)]
    if not columns:
        return Sheet([ColumnSpec("A"), ColumnSpec("B")], [["", ""]])
    if not rows:
        rows = [["" for _ in columns]]
    return Sheet(columns, rows)


def merge_linked_sheet(base: Sheet, stored: Sheet) -> Sheet:
    """Refresh semantics for a Table fed by its input, like an Excel table
    with custom columns beside a Power Query load: input columns replace
    stored columns of the same name (keeping any stored width), while
    stored columns the input doesn't have — the user's additions — survive
    at the end, stretched to the new row count. When rows grow, a trailing
    formula fills down with shifted references; literals leave new rows
    blank. When rows shrink, extra cells drop off."""
    merged = base.copy()
    stored_by_name = {c.name: c for c in stored.columns}
    for col in merged.columns:
        mine = stored_by_name.get(col.name)
        if mine is None:
            continue
        if col.width is None and mine.width:
            col.width = mine.width
        # a dropdown list set on an input column is the user's, not the
        # input's — it survives the refresh like a width does
        col.choices, col.strict = list(mine.choices), mine.strict
        col.format = dict(mine.format) if mine.format else None
        col.total = mine.total
        col.validation = dict(mine.validation) if mine.validation else None
        col.hidden = mine.hidden
    merged.freeze_rows, merged.freeze_cols = (stored.freeze_rows,
                                              stored.freeze_cols)
    merged.show_totals = stored.show_totals
    merged.hidden_rows = {r for r in stored.hidden_rows
                          if r < merged.n_rows}
    merged.row_heights = {r: h for r, h in stored.row_heights.items()
                          if r < merged.n_rows}
    if stored.groups:
        from .outline import clamp
        merged.groups = clamp(
            [type(g)(g.start, g.end, g.collapsed) for g in stored.groups],
            merged.n_rows)

    base_names = {c.name for c in merged.columns}
    n_rows = merged.n_rows
    for idx, col in enumerate(stored.columns):
        if col.name in base_names:
            continue
        values = [stored.rows[r][idx] for r in range(stored.n_rows)]
        if not any(v.strip() for v in values):
            continue   # an all-blank column holds no work worth carrying
                       # (this also sheds a fresh grid's default A/B columns)
        cells = values[:n_rows]
        template = values[-1] if values else ""
        template_row = len(values) - 1
        for row in range(len(cells), n_rows):
            if is_formula(template):
                cells.append(translate(template, row - template_row, 0))
            else:
                cells.append("")
        merged.columns.append(ColumnSpec(
            col.name, col.type, col.width, list(col.choices), col.strict,
            dict(col.format) if col.format else None, col.total,
            dict(col.validation) if col.validation else None, col.hidden))
        for row in range(n_rows):
            merged.rows[row].append(cells[row])

    # notes stay on their column (by name) and row, as long as both remain
    by_name = {c.name: i for i, c in enumerate(merged.columns)}
    for attr in ("notes", "styles"):
        for (r, c), value in getattr(stored, attr).items():
            if c < stored.n_cols and r < n_rows:
                col = by_name.get(stored.columns[c].name)
                if col is not None:
                    getattr(merged, attr)[(r, col)] = value
    return merged


class _Cells:
    """``get_cell`` for one pass, and the shared value of each range."""

    __slots__ = ("values", "n_rows", "n_cols", "_ranges")

    def __init__(self, values, n_rows: int, n_cols: int) -> None:
        self.values = values
        self.n_rows, self.n_cols = n_rows, n_cols
        self._ranges: dict = {}

    def __call__(self, row: int, col: int):
        if not (0 <= row < self.n_rows and 0 <= col < self.n_cols):
            return FormulaError(
                ERR_REF, f"{cell_name(row, col)} is outside the table")
        return self.values[row][col]

    def range_value(self, rng) -> RangeValue:
        from .formula import clamp_range
        box = clamp_range(rng, (self.n_rows, self.n_cols))
        shared = self._ranges.get(box)
        if shared is None:
            if box is None:
                shared = RangeValue([], 1)
            else:
                r1, c1, r2, c2 = box
                values = self.values
                shared = RangeValue([values[r][c] for r in range(r1, r2 + 1)
                                     for c in range(c1, c2 + 1)],
                                    c2 - c1 + 1)
            shared.memo = {}
            self._ranges[box] = shared
        return shared


def evaluate_sheet(sheet: Sheet) -> EvalResult:
    """Every value of the sheet, from scratch."""
    return SheetEvaluator(sheet).result


def _error_text(value: FormulaError) -> str:
    return f"{value.code} — {value.detail}" if value.detail else value.code


class SheetEvaluator:
    """A sheet's values, kept up to date as cells change.

    Built, it evaluates the whole sheet. :meth:`update` then takes the
    cells that have changed since and re-evaluates only the formulas that
    read them — directly, through a range, or through other formulas —
    so typing into one cell of a big table costs what depends on that
    cell, not the whole table. Anything that changes the sheet's shape,
    column names or types goes back to a full pass, as does a change too
    big to be worth tracing.
    """

    def __init__(self, sheet: Sheet) -> None:
        self.full(sheet)

    # ------------------------------------------------------------ state

    def _signature(self, sheet: Sheet):
        return (sheet.n_rows, sheet.n_cols,
                tuple((c.name, c.type) for c in sheet.columns))

    def _compile(self, sheet: Sheet, r: int, c: int) -> None:
        """Read cell (r, c) afresh: its literal value, or its formula and
        what that formula reads (registered so a change can find it)."""
        text = sheet.rows[r][c]
        key = (r, c)
        self._forget(key)
        if is_formula(text):
            try:
                ast = bind_column_refs(parse_formula_cached(text), r,
                                       self._names, self._n_rows)
            except FormulaSyntaxError as exc:
                self.values[r][c] = FormulaError(ERR_SYNTAX, str(exc))
                return
            self.asts[key] = ast
            cells, ranges = refs_and_ranges(ast, self._bounds)
            self._reads[key] = (cells, ranges)
            for ref in cells:
                self._cell_readers.setdefault(ref, set()).add(key)
            for box in ranges:
                self._box_readers.setdefault(box, set()).add(key)
        else:
            self.values[r][c] = literal_value(text, sheet.columns[c].type)

    def _forget(self, key) -> None:
        self.asts.pop(key, None)
        reads = self._reads.pop(key, None)
        if reads is None:
            return
        cells, ranges = reads
        for ref in cells:
            readers = self._cell_readers.get(ref)
            if readers is not None:
                readers.discard(key)
                if not readers:
                    del self._cell_readers[ref]
        for box in ranges:
            readers = self._box_readers.get(box)
            if readers is not None:
                readers.discard(key)
                if not readers:
                    del self._box_readers[box]

    def full(self, sheet: Sheet) -> EvalResult:
        n_rows, n_cols = sheet.n_rows, sheet.n_cols
        self._n_rows, self._bounds = n_rows, (n_rows, n_cols)
        self._names = sheet.column_names()
        self._sig = self._signature(sheet)
        self.values: list[list] = [[None] * n_cols for _ in range(n_rows)]
        self.asts: dict = {}
        self._reads: dict = {}
        self._cell_readers: dict = {}
        self._box_readers: dict = {}
        self._stuck: set = set()     # formula cells left in a cycle
        for r in range(n_rows):
            for c in range(n_cols):
                self._compile(sheet, r, c)
        self._run(list(self.asts))
        self.errors = {}
        for r in range(n_rows):
            for c in range(n_cols):
                value = self.values[r][c]
                if isinstance(value, FormulaError):
                    self.errors[(r, c)] = _error_text(value)
        self.result = EvalResult(self.values, self.errors)
        return self.result

    # ------------------------------------------------------- evaluating

    def _run(self, keys: list) -> None:
        """Evaluate the formula cells `keys`, in dependency order among
        themselves (the cells they read outside `keys` are final). A range
        is a node of its own ("range", box): it waits for the formula
        cells of `keys` inside it, and what reads it waits for it — so a
        column of SUMIF([Region], …) is n edges, not n². What is left when
        nothing more can go is a cycle.

        A cell outside `keys` that an earlier pass left stuck in a cycle
        is never final: whatever reads it (directly or through a range)
        stays stuck too, as it would in a pass over the whole sheet."""
        asts = self.asts
        wanted = set(keys)
        # (a stuck cell since typed over with a value is no longer stuck)
        stuck_outside = {key for key in self._stuck - wanted if key in asts}
        rows_by_col: dict[int, list[int]] = {}
        for r, c in sorted(wanted):
            rows_by_col.setdefault(c, []).append(r)
        dependents: dict = {key: [] for key in wanted}
        indegree: dict = {key: 0 for key in wanted}

        def range_node(box):
            node = ("range", box)
            if node not in indegree:
                dependents[node] = []
                indegree[node] = 0
                r1, c1, r2, c2 = box
                for c in range(c1, c2 + 1):
                    rows = rows_by_col.get(c)
                    if not rows:
                        continue
                    for r in rows[bisect_left(rows, r1):
                                  bisect_right(rows, r2)]:
                        dependents[(r, c)].append(node)
                        indegree[node] += 1
                if any(r1 <= r <= r2 and c1 <= c <= c2
                       for r, c in stuck_outside):
                    indegree[node] += 1      # waits for good
            return node

        for key in wanted:
            cells, ranges = self._reads[key]
            for ref in cells:
                if ref == key:
                    indegree[key] += 1   # self-reference: an immediate cycle
                elif ref in wanted:
                    dependents[ref].append(key)
                    indegree[key] += 1
                elif ref in stuck_outside:
                    indegree[key] += 1   # reads a cycle: waits for good
            for box in ranges:
                node = range_node(box)
                dependents[node].append(key)
                indegree[key] += 1

        values = self.values
        get_cell = _Cells(values, *self._bounds)
        queue = deque(key for key, count in indegree.items() if count == 0)
        done = set()
        while queue:
            key = queue.popleft()
            if key[0] != "range":
                done.add(key)
                values[key[0]][key[1]] = evaluate(asts[key], get_cell,
                                                  self._bounds)
            for dependent in dependents[key]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    queue.append(dependent)
        left = wanted - done
        for key in left:
            values[key[0]][key[1]] = FormulaError(
                ERR_CYCLE, "circular reference")
        self._stuck = stuck_outside | left

    # ---------------------------------------------------------- updates

    def _readers_of(self, cell) -> set:
        """The formulas that read `cell`: by name, or through a range."""
        found = set(self._cell_readers.get(cell, ()))
        r, c = cell
        for box, readers in self._box_readers.items():
            r1, c1, r2, c2 = box
            if r1 <= r <= r2 and c1 <= c <= c2:
                found |= readers
        return found

    def update(self, sheet: Sheet, cells) -> EvalResult:
        """Bring the values up to date after `cells` — (row, col) pairs —
        changed in `sheet`. Falls back to a full pass when the sheet's
        shape, names or types changed, or the change is too big to trace
        cheaply."""
        cells = {(int(r), int(c)) for r, c in cells}
        n_rows, n_cols = self._bounds
        if (self._signature(sheet) != self._sig
                or len(cells) > max(64, (n_rows * n_cols) // 20)
                or any(not (0 <= r < n_rows and 0 <= c < n_cols)
                       for r, c in cells)):
            return self.full(sheet)
        for r, c in cells:
            self._compile(sheet, r, c)
        # everything downstream of the changed cells
        dirty: set = set()
        frontier = list(cells)
        seen = set(cells)
        while frontier:
            cell = frontier.pop()
            if cell in self.asts:
                dirty.add(cell)
            for reader in self._readers_of(cell):
                if reader not in seen:
                    seen.add(reader)
                    frontier.append(reader)
        self._run(list(dirty))
        for cell in seen:
            r, c = cell
            value = self.values[r][c]
            if isinstance(value, FormulaError):
                self.errors[cell] = _error_text(value)
            else:
                self.errors.pop(cell, None)
        self.result = EvalResult(self.values, self.errors)
        return self.result
