"""Editable Qt model over a core Sheet, shared by the canvas card and the
pop-out editor.

The model owns a Sheet plus its cached evaluation; every user mutation
re-evaluates the whole sheet (milliseconds at this node's scale) and emits
one ``sheet_edited(dict)`` with the new persisted form — the host decides
what committing means (the card pushes an undo command per edit, the
dialog records local undo steps).
"""
from __future__ import annotations

import html
from typing import Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor

from flograph.core.sheet.numfmt import format_value_as, parse_typed
from flograph.core.sheet import validation as _validation

from ..table_delegate import BAR_ROLE, DECOR_ROLE, ICON_ROLE, NOTE_ROLE
from flograph.core.sheet import (COLUMN_TYPES, FormulaError, Sheet,
                                 SheetEvaluator, format_value, is_formula,
                                 normalize_date, parse_sheet,
                                 rename_column_in_formulas, sheet_to_dict,
                                 translate, validate_cell)

_ERROR_TEXT = QColor("#f87171")
_INVALID_BG = QColor(239, 68, 68, 45)

# Resolving an enum attribute like `Qt.DisplayRole` goes through PySide6's
# metaclass and costs ~1.9us on this build. That is nothing once, and a great
# deal here: Qt asks `data()` for seven roles per visible cell per repaint, so
# the role cascade below ran ~2,300 times for one scroll of a 300-row sheet.
# Measured, the cascade alone was 11.0us of the 11.8us a `data()` call took —
# the sheet logic it guards was noise beside it. Bound to plain ints at import,
# the same cascade costs 0.07us, and a card scrolls at Qt's floor instead of
# three times over it. The same reasoning applies to the flag and brush
# constants: build them once, not per cell.
_DISPLAY = int(Qt.DisplayRole)
_EDIT = int(Qt.EditRole)
_CHECK_STATE = int(Qt.CheckStateRole)
_TOOLTIP = int(Qt.ToolTipRole)
_FOREGROUND = int(Qt.ForegroundRole)
_BACKGROUND = int(Qt.BackgroundRole)
_ALIGNMENT = int(Qt.TextAlignmentRole)

_CHECKED = Qt.Checked
_UNCHECKED = Qt.Unchecked
_ALIGN_NUMBER = int(Qt.AlignRight | Qt.AlignVCenter)
_ERROR_BRUSH = QBrush(_ERROR_TEXT)
_NEGATIVE_BRUSH = QBrush(QColor("#f87171"))
_FONT = int(Qt.FontRole)


_BOLD_FONT = []   # made on first use: a QFont wants the application up


def _bold_font():
    if not _BOLD_FONT:
        from PySide6.QtGui import QFont
        font = QFont()
        font.setBold(True)
        _BOLD_FONT.append(font)
    return _BOLD_FONT[0]


_FONTS: dict = {}     # (bold, italic, underline) -> QFont, made on first use
_BRUSHES: dict = {}   # "#rrggbb" -> QBrush


def _font(bold: bool, italic: bool, underline: bool):
    """A font setting only these three, so the view's own size and family
    still apply (Qt resolves a role's font against the view's)."""
    key = (bold, italic, underline)
    if key not in _FONTS:
        from PySide6.QtGui import QFont
        font = QFont()
        if bold:
            font.setBold(True)
        if italic:
            font.setItalic(True)
        if underline:
            font.setUnderline(True)
        _FONTS[key] = font
    return _FONTS[key]


def _brush(hex_color: str) -> QBrush:
    if hex_color not in _BRUSHES:
        _BRUSHES[hex_color] = QBrush(QColor(hex_color))
    return _BRUSHES[hex_color]


_ALIGN = {"left": int(Qt.AlignLeft | Qt.AlignVCenter),
          "center": int(Qt.AlignHCenter | Qt.AlignVCenter),
          "right": int(Qt.AlignRight | Qt.AlignVCenter)}
_INVALID_BRUSH = QBrush(_INVALID_BG)

_TRUE_WORDS = {"true", "yes", "y", "1", "t", "x", "✓", "on"}
_FALSE_WORDS = {"false", "no", "n", "0", "f", "off"}

_VIEW_FLAGS = Qt.ItemIsEnabled | Qt.ItemIsSelectable
_EDIT_FLAGS = _VIEW_FLAGS | Qt.ItemIsEditable
_CHECKABLE = Qt.ItemIsUserCheckable


class SheetModel(QAbstractTableModel):
    """Display shows computed values; Edit round-trips raw cell sources."""

    sheet_edited = Signal(dict)   # the new sheet dict, after a user mutation
    freeze_changed = Signal()     # freeze panes moved (by the user or a sync)
    totals_changed = Signal()     # the Total Row was turned on/off or changed
    # a typed value a column's Stop rule turned away: row, col, text, why
    edit_refused = Signal(int, int, str, str)
    # a group was folded or unfolded: view state, not an edit
    outline_changed = Signal()

    def __init__(self, sheet=None, parent=None) -> None:
        super().__init__(parent)
        self._sheet = parse_sheet(sheet) if sheet is not None else parse_sheet(None)
        # conditional formatting: the rules (Show Table's language, from the
        # node's `rules` param) and what they make of the current values
        self._rules_text = ""
        self._rules: list = []
        self._cf_clear()
        self._recalc()
        self._syncing = False
        self._read_only = False

    # ------------------------------------------------ conditional formatting

    def _recalc(self, changed=None) -> None:
        """Bring the values up to date. With `changed` — the (row, col)
        cells that are all that changed — only what reads them is
        re-evaluated (core/sheet/engine.SheetEvaluator); the evaluator
        itself falls back to a full pass when the change is structural."""
        evaluator = getattr(self, "_evaluator", None)
        if changed is not None and evaluator is not None:
            self._result = evaluator.update(self._sheet, changed)
        else:
            self._evaluator = SheetEvaluator(self._sheet)
            self._result = self._evaluator.result
        self._cf_clear()

    def _cf_clear(self) -> None:
        self._cf_frame = None
        self._cf_columns: dict = {}
        self._cf_rows = None
        self._cf_cells: dict = {}
        self._cf_memo: dict = {}

    @property
    def rules_text(self) -> str:
        return self._rules_text

    def set_rules(self, text) -> None:
        """Conditional formatting, in the rules language Show Table uses
        (core/table_format.py): `Units scale green`, `Total bar blue`,
        `Status = Open => bg amber`. Rules only paint — they never change a
        value — so this repaints and nothing else."""
        text = str(text or "")
        if text == self._rules_text:
            return
        from flograph.core.table_format import (LAYOUT_MODES, TOTAL_MODES,
                                                parse_rules_lenient)
        rules, _errors = parse_rules_lenient(text)
        # layout and totals rules shape a Show Table; a grid has its own
        # widths, sorting and no totals, so those lines are left to it
        self._rules = [r for r in rules if r.mode not in LAYOUT_MODES
                       and r.mode not in TOTAL_MODES]
        self._rules_text = text
        self._cf_clear()
        if self._sheet.n_rows and self._sheet.n_cols:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self._sheet.n_rows - 1, self._sheet.n_cols - 1))

    def _frame(self):
        """The computed values as a DataFrame, numbers as numbers — what the
        rule engine evaluates. Built on first need after a change."""
        if self._cf_frame is not None:
            return self._cf_frame
        import pandas as pd
        columns = {}
        for c, spec in enumerate(self._sheet.columns):
            values = [None if (v is None or v == ""
                               or isinstance(v, FormulaError)) else v
                      for v in (row[c] for row in self._result.values)]
            series = pd.Series(values, dtype=object)
            if spec.type not in ("text", "date", "bool"):
                numeric = pd.to_numeric(series, errors="coerce")
                if int(numeric.notna().sum()) == int(series.notna().sum()):
                    series = numeric
            columns[c] = series
        frame = pd.DataFrame(columns)
        frame.columns = self._sheet.column_names()
        self._cf_frame = frame
        return frame

    @staticmethod
    def _row_rule(rule) -> bool:
        return rule.mode == "highlight" and rule.scope == "row"

    def _column_styles(self, col: int) -> list:
        found = self._cf_columns.get(col)
        if found is not None:
            return found
        from flograph.core.table_format import (column_matches, column_stats,
                                                evaluate_column)
        frame = self._frame()
        name = self._sheet.columns[col].name
        series = frame.iloc[:, col]
        stats = None
        found = []
        for i, rule in enumerate(self._rules):
            if self._row_rule(rule):
                continue
            if rule.columns and not column_matches(rule.columns, name):
                continue
            if stats is None:
                stats = column_stats(series)
            try:
                styles = evaluate_column(series, [rule], stats, frame=frame,
                                         memo=self._cf_memo)
            except Exception:
                # this runs inside data(), mid-paint: an exception escaping
                # here takes the process down. One rule that cannot be drawn
                # is skipped and the rest still are (as in PandasModel).
                continue
            found.append((i, styles))
        self._cf_columns[col] = found
        return found

    def _row_styles(self) -> list:
        if self._cf_rows is not None:
            return self._cf_rows
        from flograph.core.table_format import evaluate_rows
        found = []
        frame = self._frame()
        for i, rule in enumerate(self._rules):
            if not self._row_rule(rule):
                continue
            try:
                found.append((i, evaluate_rows(frame, [rule])))
            except Exception:
                continue
        self._cf_rows = found
        return found

    def cell_style(self, row: int, col: int):
        """The CellStyle the rules give a cell, or None. Every rule that
        touches it, top to bottom — a later line wins, as in Show Table."""
        if not self._rules:
            return None
        key = (row, col)
        if key in self._cf_cells:
            return self._cf_cells[key]
        parts = []
        for i, styles in self._column_styles(col):
            if row < len(styles) and styles[row] is not None:
                parts.append((i, styles[row]))
        for i, styles in self._row_styles():
            if row < len(styles) and styles[row] is not None:
                parts.append((i, styles[row]))
        style = None
        for _i, part in sorted(parts, key=lambda t: t[0]):
            style = part.over(style)
        self._cf_cells[key] = style
        return style

    @property
    def read_only(self) -> bool:
        return self._read_only

    def set_read_only(self, flag: bool) -> None:
        """Linked mode: the grid displays upstream data and refuses edits."""
        if self._read_only != bool(flag):
            self._read_only = bool(flag)
            if self._sheet.n_rows and self._sheet.n_cols:
                self.dataChanged.emit(
                    self.index(0, 0),
                    self.index(self._sheet.n_rows - 1, self._sheet.n_cols - 1))

    # ------------------------------------------------------------- access

    @property
    def sheet(self) -> Sheet:
        return self._sheet

    def sheet_dict(self) -> dict:
        return sheet_to_dict(self._sheet)

    def column_type(self, col: int) -> str:
        if 0 <= col < self._sheet.n_cols:
            return self._sheet.columns[col].type
        return "auto"

    def column_choices(self, col: int) -> tuple[list[str], bool]:
        """A column's dropdown list and whether it is strict."""
        if 0 <= col < self._sheet.n_cols:
            spec = self._sheet.columns[col]
            return list(spec.choices), spec.strict
        return [], False

    def _invalid(self, row: int, col: int, source: str) -> Optional[str]:
        spec = self._sheet.columns[col]
        problem = validate_cell(source, spec.type, spec.choices, spec.strict)
        if problem or not spec.validation:
            return problem
        return _validation.check(source, spec.validation,
                                 self._row_has_data(row))

    def _row_has_data(self, row: int) -> bool:
        return any(text.strip() for text in self._sheet.rows[row])

    def cell_problem(self, row: int, col: int) -> Optional[str]:
        """What is wrong with a cell — a formula error, a value that doesn't
        fit its column's type or list, or a broken validation rule."""
        if not (0 <= row < self._sheet.n_rows
                and 0 <= col < self._sheet.n_cols):
            return None
        return (self._result.errors.get((row, col))
                or self._invalid(row, col, self._sheet.cell(row, col)))

    def problem_cells(self) -> list[tuple[int, int]]:
        """Every cell with a problem, row by row."""
        return [(r, c) for r in range(self._sheet.n_rows)
                for c in range(self._sheet.n_cols)
                if self.cell_problem(r, c)]

    def column_validation(self, col: int) -> Optional[dict]:
        if 0 <= col < self._sheet.n_cols:
            rule = self._sheet.columns[col].validation
            return dict(rule) if rule else None
        return None

    def set_column_validation(self, cols, rule) -> None:
        """Give columns a validation rule (None to remove it), one undo
        step. Values are untouched; only what is flagged changes."""
        if self._read_only:
            return
        rule = _validation.clean(rule)
        cols = [c for c in cols if 0 <= c < self._sheet.n_cols]
        if not cols:
            return

        def mutate(sheet: Sheet) -> None:
            for col in cols:
                sheet.columns[col].validation = dict(rule) if rule else None

        self._structural(mutate)

    def cell_source(self, row: int, col: int) -> str:
        if 0 <= row < self._sheet.n_rows and 0 <= col < self._sheet.n_cols:
            return self._sheet.cell(row, col)
        return ""

    def cell_error(self, row: int, col: int) -> Optional[str]:
        return self._result.errors.get((row, col))

    def computed_value(self, row: int, col: int):
        """The cell's computed value (number, text, bool, None or a
        FormulaError) — before any number format."""
        if 0 <= row < self._sheet.n_rows and 0 <= col < self._sheet.n_cols:
            return self._result.values[row][col]
        return None

    def value_text(self, row: int, col: int) -> str:
        """Computed display text, unformatted (what a copy, a filter and
        Paste Values carry — a number format is how it reads, not what it
        is)."""
        if 0 <= row < self._sheet.n_rows and 0 <= col < self._sheet.n_cols:
            return format_value(self._result.values[row][col])
        return ""

    def set_sheet(self, sheet) -> None:
        """Sync in externally-changed data (param change, undo/redo, the
        refresh at the end of a linked run).

        When the grid keeps its layout, the new values go in as a data
        change rather than a model reset. A reset drops the selection, the
        scroll position and any cell being typed into — bearable for an undo
        the user just asked for, but a linked table also gets one of these
        every time a run finishes, which on a slow flow arrives long after
        the edit that caused it and throws the user out of wherever they had
        moved on to.
        """
        parsed = parse_sheet(sheet)
        if sheet_to_dict(parsed) == sheet_to_dict(self._sheet):
            return
        # folds are view state: a group over the same rows stays folded
        # through an undo or a linked refresh
        folded = {(g.start, g.end) for g in self._sheet.groups
                  if g.collapsed}
        for group in parsed.groups:
            group.collapsed = (group.start, group.end) in folded
        froze = ((parsed.freeze_rows, parsed.freeze_cols)
                 != (self._sheet.freeze_rows, self._sheet.freeze_cols))
        in_place = self._same_layout(parsed)
        changed = self._changed_cells(parsed) if in_place else None
        self._syncing = True
        try:
            if not in_place:
                self.beginResetModel()
            self._sheet = parsed
            self._recalc(changed)
            if in_place:
                self.dataChanged.emit(
                    self.index(0, 0),
                    self.index(self._sheet.n_rows - 1,
                               self._sheet.n_cols - 1))
            else:
                self.endResetModel()
        finally:
            self._syncing = False
        if froze:
            self.freeze_changed.emit()
        self.totals_changed.emit()

    def _changed_cells(self, other: Sheet) -> Optional[list]:
        """The cells whose text differs between the grid's sheet and
        `other` (same shape), or None when the columns themselves differ —
        names, types — so only a full recalculation will do."""
        if [(c.name, c.type) for c in other.columns] != [
                (c.name, c.type) for c in self._sheet.columns]:
            return None
        changed = []
        for r, (new, old) in enumerate(zip(other.rows, self._sheet.rows)):
            if new != old:
                changed.extend((r, c) for c, (a, b) in enumerate(zip(new, old))
                               if a != b)
        return changed

    def _same_layout(self, other: Sheet) -> bool:
        """Can `other` replace the current sheet without a model reset?

        Only when the shape holds and every column keeps its name, type and
        stored width. Width is in there because the view applies stored
        widths on reset and nowhere else, so a change to one has to go the
        long way round; a linked refresh carries the widths through the
        merge unchanged, which is the case this fast path exists for.
        """
        if (other.n_rows != self._sheet.n_rows
                or other.n_cols != self._sheet.n_cols
                or not other.n_rows or not other.n_cols):
            return False
        return (other.show_totals == self._sheet.show_totals
                and other.freeze_rows == self._sheet.freeze_rows
                and other.freeze_cols == self._sheet.freeze_cols
                and all(new.name == old.name and new.type == old.type
                        and new.width == old.width
                        and new.choices == old.choices
                        and new.strict == old.strict
                        and new.format == old.format
                        and new.total == old.total
                        and new.validation == old.validation
                        for new, old in zip(other.columns,
                                            self._sheet.columns)))

    # ------------------------------------------------------ Qt model API

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else self._sheet.n_rows

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else self._sheet.n_cols

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        # the row header asks per visible row, so the same int-compare rule
        # as data() applies here
        role = int(role)
        if orientation == Qt.Horizontal:
            if role == _DISPLAY and section < self._sheet.n_cols:
                return self._sheet.columns[section].name
            if role == _TOOLTIP and section < self._sheet.n_cols:
                from flograph.core.sheet import col_letters
                col = self._sheet.columns[section]
                return (f"{col.name} — column {col_letters(section)}, "
                        f"type: {col.type} — reference as [@{col.name}]")
        elif role == _DISPLAY:
            return section + 1   # the same 1-based numbers formulas use
        return None

    def flags(self, index):
        if self._read_only:
            return _VIEW_FLAGS
        flags = _EDIT_FLAGS
        if (self.column_type(index.column()) == "bool"
                and not is_formula(self.cell_source(index.row(),
                                                    index.column()))):
            flags |= _CHECKABLE
        return flags

    def data(self, index, role=Qt.DisplayRole):
        # int() once, then integer compares: see the role constants above for
        # why this shape rather than `role == Qt.DisplayRole`
        role = int(role)
        row, col = index.row(), index.column()
        if not (0 <= row < self._sheet.n_rows and 0 <= col < self._sheet.n_cols):
            return None
        if role == NOTE_ROLE:
            return self._sheet.notes.get((row, col))
        source = self._sheet.cell(row, col)
        value = self._result.values[row][col]
        col_type = self.column_type(col)
        bool_check = col_type == "bool" and not is_formula(source)

        fmt = self._sheet.columns[col].format
        style = self.cell_style(row, col) if self._rules else None
        if role == _DISPLAY:
            if bool_check:
                return ""   # the checkbox is the display
            if style is not None:
                if style.hide_value:
                    return ""     # an `only` rule: the format is the cell
                if style.text is not None:
                    return style.text
            if fmt is not None:
                shown = format_value_as(value, fmt)
                if shown is not None:
                    return shown[0]
            return format_value(value)
        if role == _EDIT:
            return source
        if role == _CHECK_STATE and bool_check:
            # a blank bool cell is an unticked box, as in Excel — and goes
            # down the flow as FALSE (nodes/io/table.py), so what it shows
            # and what it sends agree
            if source.strip().upper() == "TRUE":
                return _CHECKED
            return _UNCHECKED
        if role == _TOOLTIP:
            note = self._sheet.notes.get((row, col))
            tip = self._cell_tip(row, col, source, style)
            if note:
                # the note first, as Excel's box shows it; what the cell
                # would say anyway under a line
                body = html.escape(note).replace("\n", "<br>")
                return (f"<b>Note</b><br>{body}"
                        + (f"<hr>{html.escape(tip)}" if tip else ""))
            return tip
        if role == _FOREGROUND:
            if isinstance(value, FormulaError):
                return _ERROR_BRUSH
            if style is not None and style.fg:
                return QBrush(QColor(style.fg))
            if fmt is not None:
                shown = format_value_as(value, fmt)
                if shown is not None and shown[1]:
                    return _NEGATIVE_BRUSH
            own = self._sheet.styles.get((row, col))
            if own and "color" in own:
                return _brush(own["color"])
            if (own and "fill" in own and not (style is not None
                                                and style.bg)
                    and not self._invalid(row, col, source)):
                # a fill without a chosen text colour: text that reads on
                # it (the theme's light text vanishes on a pale fill)
                from flograph.core.table_format import readable_fg
                return _brush(readable_fg(own["fill"]))
            return None
        if role == _BACKGROUND:
            if self._invalid(row, col, source):
                return _INVALID_BRUSH
            if style is not None and style.bg:
                return QBrush(QColor(style.bg))
            own = self._sheet.styles.get((row, col))
            if own and "fill" in own:
                return _brush(own["fill"])
            return None
        if role == _FONT:
            # the cell's own bold/italic/underline, with a conditional
            # rule's bold on top
            own = self._sheet.styles.get((row, col)) or {}
            bold = bool(own.get("b")) or bool(style is not None
                                              and style.bold)
            italic, underline = bool(own.get("i")), bool(own.get("u"))
            if bold or italic or underline:
                return _font(bold, italic, underline)
            return None
        if role == _ALIGNMENT:
            own = self._sheet.styles.get((row, col))
            if own and "align" in own:
                return _ALIGN[own["align"]]
        if style is not None:
            if role == BAR_ROLE:
                return ((style.bar, style.bar_color, style.bar_mode)
                        if style.bar is not None else None)
            if role == DECOR_ROLE:
                return ((style.decorations, style.pill, style.pill_fg)
                        if (style.decorations or style.pill) else None)
            if role == ICON_ROLE:
                if style.decorations:
                    first = style.decorations[0]
                    return (first.text, first.color)
                return None
        if role == _ALIGNMENT:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return _ALIGN_NUMBER
            return None
        return None

    def _cell_tip(self, row: int, col: int, source: str, style):
        error = self._result.errors.get((row, col))
        if error:
            return error
        invalid = self._invalid(row, col, source)
        if invalid:
            return invalid
        if style is not None and style.tooltip:
            return style.tooltip
        if is_formula(source):
            return source
        return None

    def setData(self, index, value, role=Qt.EditRole) -> bool:
        row, col = index.row(), index.column()
        if self._read_only:
            return False
        if not (0 <= row < self._sheet.n_rows and 0 <= col < self._sheet.n_cols):
            return False
        if role == Qt.CheckStateRole:
            checked = Qt.CheckState(value) == Qt.Checked
            return self._set_cell_text(row, col, "TRUE" if checked else "FALSE")
        if role == Qt.EditRole:
            text = "" if value is None else str(value)
            rule = self._sheet.columns[col].validation
            if rule and rule.get("stop"):
                # Excel's Stop alert: a typed value that breaks the rule is
                # turned away (the view puts the editor back to try again)
                typed = parse_typed(text, self._sheet.columns[col].format)
                row_has_data = typed.strip() != "" or any(
                    t.strip() for i, t in enumerate(self._sheet.rows[row])
                    if i != col)
                why = _validation.check(typed, rule, row_has_data)
                if why:
                    self.edit_refused.emit(row, col, text, why)
                    return False
            return self._set_cell_text(row, col, text)
        return False

    def _set_cell_text(self, row: int, col: int, text: str) -> bool:
        # a formatted column takes what its format looks like: "£1,200",
        # "25%" (core/sheet/numfmt.parse_typed)
        text = parse_typed(text, self._sheet.columns[col].format)
        if self._sheet.cell(row, col) == text:
            return True
        self._sheet.set_cell(row, col, text)
        self._after_mutation(changed=[(row, col)])
        return True

    # -------------------------------------------------------- cell edits

    def set_cells(self, origin: tuple[int, int], block: list[list[str]],
                  cell_formats=None) -> None:
        """Write a rectangular block of raw sources at origin, growing the
        grid as needed. A None in the block leaves that cell alone (Paste
        Special's Skip Blanks). `cell_formats`, when given, is a matching block
        of cell formats laid down in the same edit: a dict sets one, None
        clears it, False leaves it. One mutation -> one undo step."""
        if self._read_only:
            return
        if not block or all(text is None for row in block for text in row):
            return
        row0, col0 = origin
        formats = [c.format for c in self._sheet.columns]
        block = [[parse_typed(text, formats[col0 + dc])
                  if text is not None and col0 + dc < len(formats) else text
                  for dc, text in enumerate(row)] for row in block]
        self._structural(lambda sheet: self._paste_into(
            sheet, row0, col0, block, cell_formats))

    @staticmethod
    def _paste_into(sheet: Sheet, row0: int, col0: int,
                    block: list[list[str]], cell_formats=None) -> None:
        sheet.ensure_size(row0 + len(block),
                          col0 + max(len(r) for r in block))
        for dr, row in enumerate(block):
            for dc, text in enumerate(row):
                if text is not None:
                    sheet.set_cell(row0 + dr, col0 + dc, text)
        for dr, row in enumerate(cell_formats or ()):
            for dc, fmt in enumerate(row):
                if fmt is not False:
                    sheet.set_cell_format(row0 + dr, col0 + dc, fmt)

    def fill_cells(self, cells, text: str, anchor: tuple[int, int]) -> None:
        """Ctrl+Enter: `text`, typed at `anchor`, into every one of `cells`
        as one edit — a formula's relative references shift for each cell,
        as they would if it were copied there. Like paste, a value that
        breaks a Stop rule is flagged, not refused."""
        if self._read_only:
            return
        cells = [(r, c) for r, c in cells
                 if 0 <= r < self._sheet.n_rows and 0 <= c < self._sheet.n_cols]
        if not cells:
            return
        formats = [c.format for c in self._sheet.columns]

        def mutate(sheet: Sheet) -> None:
            for r, c in cells:
                value = translate(text, r - anchor[0], c - anchor[1])
                sheet.set_cell(r, c, parse_typed(value, formats[c]))
        self._structural(mutate, reset=False)

    def split_column(self, col: int, parts: list[list[str]],
                     names: list[str], keep: bool) -> None:
        """Text to Columns as one undo step: `parts` (a row of parts per
        row) land in new columns right of `col`, named `names`. Unless
        `keep`, the first part replaces the column itself, which then
        holds plain text (auto type, no format, list or rule)."""
        if self._read_only or not parts or not names:
            return
        if not 0 <= col < self._sheet.n_cols:
            return
        width = len(names)

        def mutate(sheet: Sheet) -> None:
            first = col + 1 if keep else col
            extra = width if keep else width - 1
            for i in range(extra):
                sheet.insert_column(col + 1 + i, names[i + (0 if keep
                                                            else 1)])
            if not keep:
                spec = sheet.columns[col]
                old = spec.name
                if names[0] != old:
                    # formulas follow the column, as on a rename
                    sheet.rename_column(col, names[0])
                    for row in sheet.rows:
                        for c, text in enumerate(row):
                            if is_formula(text):
                                row[c] = rename_column_in_formulas(
                                    text, old, names[0])
                spec.type = "auto"
                spec.format = spec.validation = None
                spec.choices, spec.strict = [], False
            for r, row in enumerate(parts[:sheet.n_rows]):
                for i in range(width):
                    sheet.set_cell(r, first + i,
                                   row[i] if i < len(row) else "")
        self._structural(mutate)

    # ---------------------------------------------------- grouped rows

    @property
    def groups(self) -> list:
        return self._sheet.groups

    def group_rows(self, start: int, end: int):
        """Data ▸ Group: rows start..end become a group, one undo step.
        Returns why not, or None."""
        from flograph.core.sheet.outline import add_group
        if self._read_only:
            return "The table is read-only."
        added = add_group(self._sheet.groups, start, end,
                          self._sheet.n_rows)
        if isinstance(added, str):
            return added

        def mutate(sheet: Sheet) -> None:
            sheet.groups = added
        self._structural(mutate, reset=False)
        self.outline_changed.emit()
        return None

    def ungroup_rows(self, start: int, end: int) -> bool:
        from flograph.core.sheet.outline import remove_group
        if self._read_only:
            return False
        kept = remove_group(self._sheet.groups, start, end)
        if len(kept) == len(self._sheet.groups):
            return False

        def mutate(sheet: Sheet) -> None:
            sheet.groups = kept
        self._structural(mutate, reset=False)
        self.outline_changed.emit()
        return True

    def clear_outline(self) -> None:
        if self._read_only or not self._sheet.groups:
            return

        def mutate(sheet: Sheet) -> None:
            sheet.groups = []
        self._structural(mutate, reset=False)
        self.outline_changed.emit()

    def set_folded(self, groups, folded: bool) -> None:
        """Fold or unfold groups. View state — not an edit: nothing goes
        out of date and nothing lands on the undo stack."""
        changed = False
        for group in groups:
            if group.collapsed != folded:
                group.collapsed = folded
                changed = True
        if changed:
            self.outline_changed.emit()

    # ----------------------------------------------------- cell formats

    def cell_format(self, row: int, col: int) -> dict:
        return dict(self._sheet.styles.get((row, col)) or {})

    def format_cells(self, cells, **changes) -> None:
        """Lay `changes` (b/i/u True or False, fill/color a hex or None,
        align a side or None) over each cell's own format — one undo
        step. Display only."""
        from flograph.core.sheet.cellfmt import merged
        if self._read_only:
            return
        cells = [(r, c) for r, c in cells
                 if 0 <= r < self._sheet.n_rows and 0 <= c < self._sheet.n_cols]
        new = {cell: merged(self._sheet.styles.get(cell), changes)
               for cell in cells}
        if all(new[cell] == self._sheet.styles.get(cell) for cell in cells):
            return

        def mutate(sheet: Sheet) -> None:
            for cell, fmt in new.items():
                sheet.set_cell_format(*cell, fmt)
        self._structural(mutate, reset=False)

    def clear_formats(self, cells) -> None:
        cells = [cell for cell in cells if cell in self._sheet.styles]
        if self._read_only or not cells:
            return

        def mutate(sheet: Sheet) -> None:
            for cell in cells:
                sheet.styles.pop(cell, None)
        self._structural(mutate, reset=False)

    def paste_formats(self, origin: tuple[int, int], block) -> None:
        """Lay a copied block of formats (None for a plain cell) at
        `origin` — Excel's paste carrying formats along. One undo step."""
        if self._read_only or not block:
            return
        row0, col0 = origin

        def mutate(sheet: Sheet) -> None:
            for dr, line in enumerate(block):
                for dc, fmt in enumerate(line):
                    if fmt is not False:          # False: leave this cell
                        sheet.set_cell_format(row0 + dr, col0 + dc, fmt)
        self._structural(mutate, reset=False)

    # ------------------------------------------------------------ notes

    def note(self, row: int, col: int) -> str:
        return self._sheet.note(row, col)

    def note_cells(self) -> list[tuple[int, int]]:
        return sorted(self._sheet.notes)

    def set_note(self, row: int, col: int, text: str) -> None:
        """Write, change or (blank text) take off a cell's note — one undo
        step. A note never changes the value or what flows on."""
        if self._read_only:
            return
        if (text or "").strip() == self._sheet.note(row, col):
            return
        self._structural(lambda sheet: sheet.set_note(row, col, text),
                         reset=False)

    def delete_notes(self, cells) -> None:
        cells = [cell for cell in cells if cell in self._sheet.notes]
        if self._read_only or not cells:
            return

        def mutate(sheet: Sheet) -> None:
            for cell in cells:
                sheet.notes.pop(cell, None)
        self._structural(mutate, reset=False)

    def clear_cells(self, cells) -> None:
        if self._read_only:
            return
        cells = [(r, c) for r, c in cells
                 if 0 <= r < self._sheet.n_rows and 0 <= c < self._sheet.n_cols]
        if not any(self._sheet.cell(r, c) for r, c in cells):
            return
        for r, c in cells:
            self._sheet.set_cell(r, c, "")
        self._after_mutation()

    def fill_down(self, row0: int, row1: int, cols) -> None:
        """Fill each selected column down from its top row, shifting
        relative formula references per row like Excel's Ctrl+D."""
        if self._read_only:
            return
        if row1 <= row0:
            return
        changed = False
        for col in cols:
            top = self._sheet.cell(row0, col)
            for row in range(row0 + 1, row1 + 1):
                text = translate(top, row - row0, 0)
                if self._sheet.cell(row, col) != text:
                    self._sheet.set_cell(row, col, text)
                    changed = True
        if changed:
            self._after_mutation()

    def fill_right(self, col0: int, col1: int, rows) -> None:
        """Ctrl+R: fill each selected row rightwards from its left cell,
        shifting relative references per column."""
        if self._read_only or col1 <= col0:
            return
        changed = False
        for row in rows:
            left = self._sheet.cell(row, col0)
            for col in range(col0 + 1, col1 + 1):
                text = translate(left, 0, col - col0)
                if self._sheet.cell(row, col) != text:
                    self._sheet.set_cell(row, col, text)
                    changed = True
        if changed:
            self._after_mutation()

    def fill_range(self, source: tuple, target: tuple,
                   series: bool = False) -> None:
        """The fill handle: extend `source` (r0, c0, r1, c1) to `target`,
        which grows it in one direction, by Excel's AutoFill rules
        (core/sheet/fill.py). Past the last row or column the grid grows.
        One mutation, so one undo step."""
        if self._read_only:
            return
        from flograph.core.sheet.fill import fill_values
        sr0, sc0, sr1, sc1 = source
        tr0, tc0, tr1, tc1 = target

        def mutate(sheet: Sheet) -> None:
            sheet.ensure_size(tr1 + 1, tc1 + 1)
            if tr1 > sr1 or tr0 < sr0:
                down = tr1 > sr1
                for col in range(sc0, sc1 + 1):
                    seed = [sheet.cell(r, col) for r in range(sr0, sr1 + 1)]
                    if down:
                        rows = range(sr1 + 1, tr1 + 1)
                    else:
                        seed.reverse()
                        rows = range(sr0 - 1, tr0 - 1, -1)
                    values = fill_values(seed, len(rows), along="row",
                                         backwards=not down, series=series)
                    for row, text in zip(rows, values):
                        sheet.set_cell(row, col, text)
            elif tc1 > sc1 or tc0 < sc0:
                right = tc1 > sc1
                for row in range(sr0, sr1 + 1):
                    seed = [sheet.cell(row, c) for c in range(sc0, sc1 + 1)]
                    if right:
                        cols = range(sc1 + 1, tc1 + 1)
                    else:
                        seed.reverse()
                        cols = range(sc0 - 1, tc0 - 1, -1)
                    values = fill_values(seed, len(cols), along="col",
                                         backwards=not right, series=series)
                    for col, text in zip(cols, values):
                        sheet.set_cell(row, col, text)

        grows = tr1 >= self._sheet.n_rows or tc1 >= self._sheet.n_cols
        self._structural(mutate, reset=grows)

    def replace_all(self, find: str, replace: str, *, match_case=False,
                    whole_cell=False, cells=None) -> int:
        """Replace text in cell sources (formulas included, as Excel does
        when looking in formulas). One undo step; returns how many cells
        changed. `cells` limits it to those (row, col) pairs."""
        if self._read_only or not find:
            return 0
        import re
        flags = 0 if match_case else re.IGNORECASE
        pattern = re.compile(
            ("^" + re.escape(find) + "$") if whole_cell else re.escape(find),
            flags)
        targets = (list(cells) if cells is not None else
                   [(r, c) for r in range(self._sheet.n_rows)
                    for c in range(self._sheet.n_cols)])
        changes = {}
        for r, c in targets:
            if not (0 <= r < self._sheet.n_rows and 0 <= c < self._sheet.n_cols):
                continue
            old = self._sheet.cell(r, c)
            new = pattern.sub(lambda _m: replace, old)
            if new != old:
                changes[(r, c)] = new
        if changes:
            def mutate(sheet: Sheet) -> None:
                for (r, c), text in changes.items():
                    sheet.set_cell(r, c, text)
            self._structural(mutate, reset=False)
        return len(changes)

    # ---------------------------------------------------- structural ops

    def insert_rows_at(self, at: int, count: int = 1) -> None:
        if self._read_only:
            return
        self.beginInsertRows(QModelIndex(), at, at + count - 1)
        self._sheet.insert_rows(at, count)
        self.endInsertRows()
        self._after_mutation(reset=False)

    def insert_columns_at(self, at: int, count: int = 1) -> None:
        if self._read_only:
            return
        self.beginInsertColumns(QModelIndex(), at, at + count - 1)
        for _ in range(count):
            self._sheet.insert_column(at)
        self.endInsertColumns()
        self._after_mutation(reset=False)

    def remove_rows_at(self, indices) -> None:
        if self._read_only:
            return
        indices = [i for i in indices if 0 <= i < self._sheet.n_rows]
        if not indices or len(set(indices)) >= self._sheet.n_rows:
            return   # never remove the last row
        self._structural(lambda sheet: sheet.remove_rows(indices))

    def remove_columns_at(self, indices) -> None:
        if self._read_only:
            return
        indices = [i for i in indices if 0 <= i < self._sheet.n_cols]
        if not indices or len(set(indices)) >= self._sheet.n_cols:
            return   # never remove the last column
        self._structural(lambda sheet: sheet.remove_columns(indices))

    def move_rows(self, indices, to: int) -> None:
        """Move rows as a block to start at `to` (formulas keep their
        addresses, as after a sort)."""
        if self._read_only:
            return
        self._structural(lambda sheet: sheet.move_rows(indices, to))

    def move_columns(self, indices, to: int) -> None:
        if self._read_only:
            return
        self._structural(lambda sheet: sheet.move_columns(indices, to))

    def set_column_choices(self, col: int, choices, strict: bool) -> None:
        """Give a column a dropdown list (empty to remove it)."""
        if self._read_only or not 0 <= col < self._sheet.n_cols:
            return
        choices = [str(c).strip() for c in choices if str(c).strip()]
        strict = bool(strict) and bool(choices)

        def mutate(sheet: Sheet) -> None:
            sheet.columns[col].choices = choices
            sheet.columns[col].strict = strict

        self._structural(mutate)

    def column_format(self, col: int) -> Optional[dict]:
        if 0 <= col < self._sheet.n_cols:
            fmt = self._sheet.columns[col].format
            return dict(fmt) if fmt else None
        return None

    def set_column_format(self, cols, fmt) -> None:
        """Give columns a number format (None for General). How values read,
        never what they are — one undo step for all the columns."""
        if self._read_only:
            return
        from flograph.core.sheet.numfmt import clean
        fmt = clean(fmt)
        cols = [c for c in cols if 0 <= c < self._sheet.n_cols]
        if not cols:
            return

        def mutate(sheet: Sheet) -> None:
            for col in cols:
                sheet.columns[col].format = dict(fmt) if fmt else None

        self._structural(mutate, reset=False)

    # ------------------------------------------------------------ Total Row

    @property
    def show_totals(self) -> bool:
        return self._sheet.show_totals

    def column_total(self, col: int) -> Optional[str]:
        if 0 <= col < self._sheet.n_cols:
            return self._sheet.columns[col].total
        return None

    def set_show_totals(self, flag: bool) -> None:
        """Excel's Total Row, on or off. Turned on for the first time, the
        last number column gets a Sum, as Excel gives it — a row of blanks
        would look like it did nothing."""
        flag = bool(flag)
        if self._read_only or flag == self._sheet.show_totals:
            return
        start = None
        if flag and not any(c.total for c in self._sheet.columns):
            frame = self._frame()
            for col in range(self._sheet.n_cols - 1, -1, -1):
                from pandas.api.types import is_numeric_dtype
                if is_numeric_dtype(frame.iloc[:, col].dtype) and \
                        frame.iloc[:, col].notna().any():
                    start = col
                    break

        def mutate(sheet: Sheet) -> None:
            sheet.show_totals = flag
            if start is not None:
                sheet.columns[start].total = "sum"

        self._structural(mutate, reset=False)
        self.totals_changed.emit()

    def set_column_total(self, cols, how: Optional[str]) -> None:
        """What the Total Row shows under these columns (None: nothing).
        Showing a total turns the row on."""
        if self._read_only:
            return
        from flograph.core.table_totals import canonical_agg
        how = canonical_agg(how) if how else None
        cols = [c for c in cols if 0 <= c < self._sheet.n_cols]
        if not cols:
            return

        def mutate(sheet: Sheet) -> None:
            for col in cols:
                sheet.columns[col].total = how
            if how:
                sheet.show_totals = True

        self._structural(mutate, reset=False)
        self.totals_changed.emit()

    def total_value(self, col: int, rows=None):
        """The total under a column, over `rows` (the ones a filter left
        showing; all of them when None), or None."""
        how = self.column_total(col)
        if not how:
            return None
        from flograph.core.table_totals import aggregate
        series = self._frame().iloc[:, col]
        if rows is not None:
            series = series.iloc[list(rows)]
        return aggregate(series, how)

    def total_text(self, col: int, rows=None) -> str:
        """The total as the Total Row shows it: in the column's number
        format when the total is in the column's units (a sum of money is
        money; a count of it is not)."""
        from flograph.core.table_totals import UNIT_AGGS
        value = self.total_value(col, rows)
        if value is None:
            return ""
        fmt = self._sheet.columns[col].format
        if fmt is not None and self.column_total(col) in UNIT_AGGS:
            shown = format_value_as(value, fmt)
            if shown is not None:
                return shown[0]
        if isinstance(value, float):
            return format_value(round(value, 10))
        return format_value(value)

    def set_freeze(self, rows: int, cols: int) -> None:
        """Freeze panes: this many data rows and columns stay in view."""
        if self._read_only:
            return
        rows = max(0, min(int(rows), self._sheet.n_rows - 1))
        cols = max(0, min(int(cols), self._sheet.n_cols - 1))
        if (rows, cols) == (self._sheet.freeze_rows, self._sheet.freeze_cols):
            return

        def mutate(sheet: Sheet) -> None:
            sheet.freeze_rows, sheet.freeze_cols = rows, cols

        self._structural(mutate, reset=False)
        self.freeze_changed.emit()

    @property
    def freeze(self) -> tuple[int, int]:
        return self._sheet.freeze_rows, self._sheet.freeze_cols

    def rename_column(self, col: int, name: str) -> None:
        if self._read_only:
            return
        name = str(name).strip()
        old = self._sheet.columns[col].name if 0 <= col < self._sheet.n_cols else ""
        if not name or not 0 <= col < self._sheet.n_cols or old == name:
            return
        self._sheet.rename_column(col, name)
        # formulas follow the column: [@old] / [old] refs rewrite to the
        # new name everywhere in the sheet
        for row in self._sheet.rows:
            for c in range(len(row)):
                if is_formula(row[c]):
                    row[c] = rename_column_in_formulas(row[c], old, name)
        self.headerDataChanged.emit(Qt.Horizontal, col, col)
        self._after_mutation(reset=False)

    def set_column_type(self, col: int, col_type: str) -> None:
        if self._read_only:
            return
        if (col_type not in COLUMN_TYPES
                or not 0 <= col < self._sheet.n_cols
                or self._sheet.columns[col].type == col_type):
            return

        def mutate(sheet: Sheet) -> None:
            sheet.set_column_type(col, col_type)
            if col_type == "date":
                # convert what we can read ("23/07/2026", "Jul 5, 2026", …)
                # to ISO; anything unreadable stays put and flags red
                for row in sheet.rows:
                    text = row[col]
                    if not text or is_formula(text):
                        continue
                    normalized = normalize_date(text)
                    if normalized is not None and normalized != text:
                        row[col] = normalized
            elif col_type == "bool":
                # yes/no, 1/0, y/n, true/false become TRUE/FALSE so they show
                # as tick boxes; anything else stays put and flags red
                for row in sheet.rows:
                    text = row[col].strip()
                    if not text or is_formula(text):
                        continue
                    low = text.casefold()
                    if low in _TRUE_WORDS:
                        row[col] = "TRUE"
                    elif low in _FALSE_WORDS:
                        row[col] = "FALSE"

        self._structural(mutate)

    def set_column_widths(self, widths: dict) -> None:
        """Persist editor column widths (px) into the sheet. Width changes
        don't affect cell values, so no recalculation happens."""
        if self._read_only:
            return
        changed = False
        for col, width in widths.items():
            width = int(width)
            if (0 <= col < self._sheet.n_cols and width > 0
                    and self._sheet.columns[col].width != width):
                self._sheet.columns[col].width = width
                changed = True
        if changed and not self._syncing:
            self.sheet_edited.emit(self.sheet_dict())

    def sort_by(self, col: int, ascending: bool = True) -> None:
        if self._read_only:
            return
        self._structural(lambda sheet: sheet.sort_by(col, ascending))

    def sort_levels(self, levels) -> None:
        """Several sort levels as one undo step (the Sort dialog)."""
        if self._read_only:
            return
        self._structural(lambda sheet: sheet.sort_levels(levels))

    def sort(self, column: int, order=Qt.AscendingOrder) -> None:
        """Header-click entry point (Qt calls it 'sort'). Routes through
        the same undoable structural path as the context menu."""
        self.sort_by(column, order == Qt.AscendingOrder)

    def restore_order(self, rows: list[list[str]]) -> None:
        """Put a stored row order back — the 'clear sort' step."""
        if self._read_only or not rows:
            return
        self._structural(lambda sheet: sheet.set_rows(rows))

    def promote_row_to_header(self, row: int) -> None:
        """Use a row's values as the column names and remove the row —
        for pasted data that arrived with its headers in row 1. Blank
        cells keep the current column name; the last remaining row is
        cleared instead of removed."""
        if self._read_only:
            return
        if not 0 <= row < self._sheet.n_rows:
            return
        names = [format_value(value).strip()
                 for value in self._result.values[row]]

        def mutate(sheet: Sheet) -> None:
            for col, name in enumerate(names):
                if name:
                    sheet.rename_column(col, name)
            if sheet.n_rows > 1:
                sheet.remove_rows([row])
            else:
                for col in range(sheet.n_cols):
                    sheet.set_cell(row, col, "")

        self._structural(mutate)

    # ----------------------------------------------------------- plumbing

    def _structural(self, mutate, reset: bool = True) -> None:
        """Apply `mutate` as one edit. `reset=False` for a change that keeps
        the grid's shape (replace, freeze), so the view keeps its place."""
        before = sheet_to_dict(self._sheet)
        if reset:
            self.beginResetModel()
        mutate(self._sheet)
        self._recalc()
        if reset:
            self.endResetModel()
        elif self._sheet.n_rows and self._sheet.n_cols:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self._sheet.n_rows - 1, self._sheet.n_cols - 1))
        if sheet_to_dict(self._sheet) != before and not self._syncing:
            self.sheet_edited.emit(self.sheet_dict())

    def _after_mutation(self, reset: bool = False, changed=None) -> None:
        self._recalc(None if reset else changed)
        if reset:
            self.beginResetModel()
            self.endResetModel()
        elif self._sheet.n_rows and self._sheet.n_cols:
            # a single edit can ripple through formulas anywhere
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self._sheet.n_rows - 1, self._sheet.n_cols - 1))
        if not self._syncing:
            self.sheet_edited.emit(self.sheet_dict())
