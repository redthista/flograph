"""Whole-sheet evaluation: dependency-ordered formula recalculation.

The whole sheet is recalculated on every call — no incremental dirty
tracking. At the scale this node targets (a few thousand cells) a full
pass is milliseconds, and it keeps the engine stateless.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .formula import (FormulaSyntaxError, bind_column_refs, cell_name,
                      evaluate, parse_formula, refs_of, translate)
from .schema import ColumnSpec, Sheet, is_formula
from .values import (ERR_CYCLE, ERR_REF, ERR_SYNTAX, FormulaError,
                     format_number)


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
    stored_width = {c.name: c.width for c in stored.columns if c.width}
    for col in merged.columns:
        if col.width is None and col.name in stored_width:
            col.width = stored_width[col.name]

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
        merged.columns.append(ColumnSpec(col.name, col.type, col.width))
        for row in range(n_rows):
            merged.rows[row].append(cells[row])
    return merged


def evaluate_sheet(sheet: Sheet) -> EvalResult:
    n_rows, n_cols = sheet.n_rows, sheet.n_cols
    bounds = (n_rows, n_cols)

    column_names = sheet.column_names()
    asts: dict[tuple[int, int], object] = {}
    values: list[list] = [[None] * n_cols for _ in range(n_rows)]
    for r in range(n_rows):
        for c in range(n_cols):
            text = sheet.rows[r][c]
            if is_formula(text):
                try:
                    # [@name]/[name] refs resolve per cell, against this row
                    asts[(r, c)] = bind_column_refs(
                        parse_formula(text), r, column_names, n_rows)
                except FormulaSyntaxError as exc:
                    values[r][c] = FormulaError(ERR_SYNTAX, str(exc))
            else:
                values[r][c] = literal_value(text, sheet.columns[c].type)

    # ordering edges only matter between formula cells; references to
    # literal (or parse-error) cells read values that are already final
    dependents: dict[tuple[int, int], list] = {key: [] for key in asts}
    indegree: dict[tuple[int, int], int] = {key: 0 for key in asts}
    for key, ast in asts.items():
        for ref in refs_of(ast, bounds):
            if ref in asts and ref != key:
                dependents[ref].append(key)
                indegree[key] += 1
            elif ref == key:
                indegree[key] += 1   # self-reference: an immediate cycle

    def get_cell(row: int, col: int):
        if not (0 <= row < n_rows and 0 <= col < n_cols):
            return FormulaError(
                ERR_REF, f"{cell_name(row, col)} is outside the table")
        return values[row][col]

    queue = deque(key for key in asts if indegree[key] == 0)
    done = set()
    while queue:
        key = queue.popleft()
        done.add(key)
        values[key[0]][key[1]] = evaluate(asts[key], get_cell, bounds)
        for dependent in dependents[key]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                queue.append(dependent)
    for key in asts:
        if key not in done:
            values[key[0]][key[1]] = FormulaError(
                ERR_CYCLE, "circular reference")

    errors = {}
    for r in range(n_rows):
        for c in range(n_cols):
            value = values[r][c]
            if isinstance(value, FormulaError):
                errors[(r, c)] = (f"{value.code} — {value.detail}"
                                  if value.detail else value.code)
    return EvalResult(values, errors)
