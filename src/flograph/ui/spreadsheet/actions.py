"""Every command a Table grid offers, once.

Each command is one QAction carrying its label, its glyph, its shortcut,
and an explanation in plain words of what it does to the table. The
ribbon's buttons, the three right-click menus (cell, row number, column
header) and the keyboard all trigger these same objects — so a command is
named, explained, enabled and greyed out identically wherever someone
finds it, and adding one means adding it here.

Shortcuts are shown on the actions but never registered as Qt shortcuts:
a grid on a canvas card shares its window with the canvas's own Ctrl+C,
Ctrl+D and Ctrl+R, and two live shortcuts on one key cancel each other out
("ambiguous shortcut"). The view claims the keys it owns in its
ShortcutOverride and triggers the action itself — see `for_key`.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QKeyCombination, QObject, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence

from flograph.core.sheet import COLUMN_TYPES

from .icons import sheet_icon

# What each column type means, for the Type menu's tooltips.
TYPE_HELP = {
    "auto": "Numbers become numbers, anything else stays text — the "
            "column guesses.",
    "text": "Everything is text, even 007 and 1e5. Nothing is converted.",
    "number": "Decimal numbers. Anything else turns red and goes out as "
              "missing.",
    "integer": "Whole numbers. Anything else turns red and goes out as "
               "missing.",
    "date": "Dates (2026-10-07, 7/10/2026, 7 Oct 2026…). The cell editor "
            "is a calendar.",
    "bool": "TRUE / FALSE, shown as a tick box.",
}


def currency_format() -> dict:
    """Currency in the machine's own money: £ in the UK, € in France."""
    from PySide6.QtCore import QLocale
    symbol = QLocale().currencySymbol(QLocale.CurrencySymbol) or "$"
    return {"kind": "currency", "symbol": symbol, "decimals": 2,
            "thousands": True, "negative": "minus"}


def fill_color_menu(menu, view, ink: bool) -> None:
    """Swatches for Fill Colour (ink=False) or Font Colour (ink=True)."""
    from PySide6.QtGui import QColor, QIcon, QPixmap
    from flograph.core.sheet.cellfmt import FILLS, INKS
    apply = view.set_ink if ink else view.set_fill
    none = menu.addAction("Automatic" if ink else "No Fill")
    none.setToolTip("Take the colour off: the cell's usual "
                    + ("text colour." if ink else "background."))
    none.triggered.connect(lambda: apply(None))
    menu.addSeparator()
    for name, hex_color in (INKS if ink else FILLS):
        pix = QPixmap(14, 14)
        pix.fill(QColor(hex_color))
        action = menu.addAction(QIcon(pix), name)
        action.setToolTip(hex_color)
        action.triggered.connect(lambda _=False, h=hex_color: apply(h))
    menu.addSeparator()
    more = menu.addAction("More Colours…")
    start = view.current_format().get("color" if ink else "fill",
                                      "#fde68a")

    def pick():
        chosen = view.pick_color("Font Colour" if ink else "Fill Colour",
                                 start)
        if chosen:
            apply(chosen)
    more.triggered.connect(pick)


def fill_number_format_menu(menu, view) -> None:
    """The Number Format list: each entry shows how a sample reads under it,
    the column's current format ticked."""
    from flograph.core.sheet.numfmt import DATE_PATTERNS, clean
    from .menus import heading, submenu
    model = view.sheet_model()
    cols = view.target_columns()
    current = clean(model.column_format(cols[0])) if model and cols else None
    sample = 1234.5678

    presets = [
        ("General", None, "1234.5678"),
        ("Number", {"kind": "number", "decimals": 2, "thousands": True},
         "1,234.57"),
        ("Currency", currency_format(), None),
        ("Percent", {"kind": "percent", "decimals": 0}, "12%"),
        ("Scientific", {"kind": "scientific", "decimals": 2}, "1.23E+3"),
    ]
    heading(menu, "Number")
    from flograph.core.sheet.numfmt import format_value_as
    for label, fmt, shown in presets:
        if shown is None:
            shown = format_value_as(sample, fmt)[0]
        action = menu.addAction(f"{label}\t{shown}")
        action.setCheckable(True)
        action.setChecked(clean(fmt) == current if fmt else current is None)
        action.triggered.connect(
            lambda _=False, f=fmt: view.apply_format(f))
    dates = submenu(menu, "Date")
    for label, pattern in DATE_PATTERNS:
        fmt = {"kind": "date", "pattern": pattern}
        action = dates.addAction(label)
        action.setCheckable(True)
        action.setChecked(clean(fmt) == current)
        action.triggered.connect(
            lambda _=False, f=fmt: view.apply_format(f))
    menu.addSeparator()
    menu.addAction(view.actions["dec_more"])
    menu.addAction(view.actions["dec_less"])
    menu.addAction(view.actions["format_cells"])


def tip(title: str, body: str, shortcut: str = "") -> str:
    """A command's tooltip: what it is, what it does, and its key."""
    keys = (f"<br><span style='color:#9ca3af'>Shortcut: {shortcut}</span>"
            if shortcut else "")
    # <qt> marks it rich text, which Qt's tooltip wraps to a sane width
    return f"<qt><b>{title}</b><br>{body}{keys}</qt>"


class SheetActions(QObject):
    """The commands of one SpreadsheetView. Built by the view on first use
    (`view.actions`); `refresh()` re-reads what is enabled and checked, and
    the view calls it whenever the selection, the data or the host moves."""

    def __init__(self, view) -> None:
        super().__init__(view)
        self._view = view
        self._actions: dict[str, QAction] = {}
        self._keyed: list[QAction] = []
        self._rules: dict[str, Callable[[], bool]] = {}
        self._checks: dict[str, Callable[[], bool]] = {}
        self._watched_stack = None
        self._build()
        self.refresh()

    # ------------------------------------------------------------ access

    def __getitem__(self, name: str) -> QAction:
        return self._actions[name]

    def get(self, name: str) -> Optional[QAction]:
        return self._actions.get(name)

    def names(self) -> list[str]:
        return list(self._actions)

    def for_key(self, event) -> Optional[QAction]:
        """The action a key press triggers, or None. Matches the way a key
        arrives on most keyboards: Ctrl++ comes in as Ctrl+Shift+= on a US
        layout and as Ctrl+Shift+Plus on others, so Shift is also tried
        away for a key that is not a letter."""
        mods = event.modifiers() & ~Qt.KeypadModifier
        key = event.key()
        if key in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta,
                   Qt.Key_unknown):
            return None
        try:
            qkey = Qt.Key(key)
        except ValueError:
            return None

        def seq(m, k) -> QKeySequence:
            return QKeySequence(QKeyCombination(m, k))

        candidates = [seq(mods, qkey)]
        unshifted = mods & ~Qt.ShiftModifier
        letter = Qt.Key_A <= key <= Qt.Key_Z
        if mods & Qt.ShiftModifier and not letter and qkey not in (
                Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right,
                Qt.Key_Space):
            candidates.append(seq(unshifted, qkey))
        if qkey == Qt.Key_Equal and mods & Qt.ShiftModifier:
            candidates.append(seq(unshifted, Qt.Key_Plus))
        for action in self._keyed:
            for sequence in action.shortcuts():
                if any(sequence.matches(c) == QKeySequence.ExactMatch
                       for c in candidates):
                    return action
        return None

    # ----------------------------------------------------------- building

    def _add(self, name: str, text: str, icon: Optional[str], body: str,
             handler: Callable, *, keys=(), keyed: bool = True,
             enabled: Optional[Callable[[], bool]] = None,
             checked: Optional[Callable[[], bool]] = None,
             short: str = "") -> QAction:
        action = QAction(text, self)
        action.setObjectName(f"sheet_{name}")
        if icon:
            action.setIcon(sheet_icon(icon))
        sequences = [QKeySequence(k) for k in keys]
        if sequences:
            action.setShortcuts(sequences)
            action.setShortcutContext(Qt.WidgetShortcut)
            action.setShortcutVisibleInContextMenu(True)
        shown = sequences[0].toString(QKeySequence.NativeText) if sequences \
            else ""
        action.setToolTip(tip(text.replace("…", ""), body, shown))
        action.setStatusTip(body)
        action.setIconText(short or text.replace("…", ""))
        action.setProperty("explanation", body)
        if checked is not None:
            action.setCheckable(True)
            action.toggled.connect(lambda on, h=handler: h(on))
            self._checks[name] = checked
        else:
            action.triggered.connect(lambda _=False, h=handler: h())
        if enabled is not None:
            self._rules[name] = enabled
        if sequences and keyed:
            self._keyed.append(action)
        self._actions[name] = action
        return action

    def _build(self) -> None:
        v = self._view

        def edit() -> bool:
            return v.editable

        def picked() -> bool:
            return v.editable and bool(v.selected_rows())

        def model():
            return v.sheet_model()

        # ---- clipboard
        self._add("cut", "Cut", "cut",
                  "Copy the selected cells and clear them.",
                  v.cut_selection, keys=["Ctrl+X"], keyed=False,
                  enabled=picked)
        self._add("copy", "Copy", "copy",
                  "Copy the selected cells. Pasted back into this grid, "
                  "formulas come with them and adjust to where they land; "
                  "pasted into Excel or Sheets, the values go.",
                  v.copy_selection, keys=["Ctrl+C"], keyed=False,
                  enabled=lambda: bool(v.selected_rows()))
        self._add("paste", "Paste", "paste",
                  "Paste at the selected cell. Paste from Excel or Sheets "
                  "too; the grid grows to fit.",
                  v.paste_clipboard, keys=["Ctrl+V"], keyed=False,
                  enabled=edit)
        self._add("paste_values", "Paste Values", "paste_values",
                  "Paste what the copied cells show, not their formulas — "
                  "the numbers stay put when the cells they came from "
                  "change.",
                  v.paste_values, keys=["Ctrl+Shift+V"], enabled=edit,
                  short="Values")
        self._add("paste_special", "Paste Special…", "paste_special",
                  "Paste with choices: values or formulas, add, subtract, "
                  "multiply or divide into the numbers already there, skip "
                  "the copy's empty cells, or turn rows into columns.",
                  v.open_paste_special, keys=["Ctrl+Alt+V"],
                  enabled=lambda: edit() and v.can_paste(),
                  short="Special")
        self._add("paste_transpose", "Paste Transposed", "paste_transpose",
                  "Paste with the copied rows turned into columns and the "
                  "columns into rows.",
                  v.paste_transposed,
                  enabled=lambda: edit() and v.can_paste(),
                  short="Transpose")
        # ---- font and alignment (a cell's own look; display only)
        def own(key):
            return lambda: bool(v.current_format().get(key))

        for flag, label, key, body in (
                ("b", "Bold", "Ctrl+B", "Make the selected cells bold."),
                ("i", "Italic", "Ctrl+I", "Make the selected cells italic."),
                ("u", "Underline", "Ctrl+U",
                 "Underline the selected cells.")):
            self._add(f"fmt_{flag}", label, f"fmt_{flag}",
                      body + " Again to take it off. Only the look changes.",
                      lambda on, f=flag: v.format_selection(**{f: on}),
                      keys=[key], checked=own(flag), enabled=edit)
        self._add("fmt_wrap", "Wrap Text", "fmt_wrap",
                  "Let long text in the selected cells run onto more lines; "
                  "the row grows to fit. Again to keep it on one line.",
                  lambda on: v.format_selection(wrap=on),
                  checked=own("wrap"), enabled=edit, short="Wrap")
        for side, label in (("left", "Align Left"), ("center", "Center"),
                            ("right", "Align Right")):
            self._add(f"align_{side}", label, f"align_{side}",
                      f"{label} the selected cells' text. Again to go back "
                      "to the usual: numbers right, text left.",
                      lambda on, s=side: v.set_align(s, on),
                      checked=lambda s=side: v.current_format().get(
                          "align") == s, enabled=edit)
        self._add("fill_color", "Fill Colour", "fill_color",
                  "Colour the selected cells' background. Pick a colour, "
                  "No Fill to take it off, or More Colours….",
                  lambda: v.set_fill(getattr(v, "last_fill", "#fde68a")),
                  enabled=edit, short="Fill")
        self._add("font_color", "Font Colour", "font_color",
                  "Colour the selected cells' text. Pick a colour, "
                  "Automatic to take it off, or More Colours….",
                  lambda: v.set_ink(getattr(v, "last_ink", "#ef4444")),
                  enabled=edit, short="Colour")
        self._add("clear_formats", "Clear Formats", "clear_formats",
                  "Take bold, colours and alignment off the selected cells. "
                  "The values stay.",
                  v.clear_cell_formats,
                  enabled=lambda: edit() and any(
                      v.sheet_model().cell_format(*cell)
                      for cell in v.format_targets()) if v.sheet_model()
                  else False, short="Clear")
        painter = self._add(
            "format_painter", "Format Painter", "format_painter",
            "Copy a look — bold, colours, alignment — to other cells: "
            "select the cells that have it, click this, then click or drag "
            "over the cells to paint. Double-click to paint several places; "
            "Esc to stop.",
            lambda on: v.start_painter() if on else v.stop_painter(),
            checked=lambda: v.painting, enabled=edit, short="Painter")
        painter.double_clicked = lambda: v.start_painter(sticky=True)
        self._add("copy_headers", "Copy with Headers", "copy_headers",
                  "Copy the selection with the column names on top, for "
                  "pasting into another spreadsheet. With nothing selected, "
                  "copies the whole table.",
                  v.copy_selection_with_headers, keys=["Ctrl+Shift+C"],
                  short="With Headers")

        # ---- undo (the host's stack: the app's on a card, the dialog's own)
        self._add("undo", "Undo", "undo",
                  "Take back the last change to the table — one cell, one "
                  "paste or one command at a time.",
                  lambda: self._stack_do("undo"), keys=["Ctrl+Z"],
                  keyed=False, enabled=lambda: self._stack_can("undo"))
        self._add("redo", "Redo", "redo",
                  "Put back the change Undo took away.",
                  lambda: self._stack_do("redo"), keys=["Ctrl+Y"],
                  keyed=False, enabled=lambda: self._stack_can("redo"))

        # ---- rows
        self._add("row_above", "Insert Rows Above", "row_above",
                  "Insert as many blank rows as are selected, above them. "
                  "Formulas below keep pointing at the same cells.",
                  lambda: v.insert_rows(below=False), keys=["Ctrl++"],
                  keyed=False, enabled=edit, short="Above")
        self._add("row_below", "Insert Rows Below", "row_below",
                  "Insert as many blank rows as are selected, below them.",
                  lambda: v.insert_rows(below=True), enabled=edit,
                  short="Below")
        self._add("row_delete", "Delete Rows", "row_delete",
                  "Delete every row the selection touches. A formula that "
                  "pointed into a deleted row shows #REF!. Undo brings the "
                  "rows back.",
                  v.delete_rows, keys=["Ctrl+-"], keyed=False,
                  enabled=lambda: picked() and model() is not None
                  and 0 < len(v.target_rows()) < model().rowCount(),
                  short="Delete")
        self._add("row_up", "Move Rows Up", "row_up",
                  "Move the selected rows up one place.",
                  lambda: v.move_rows(-1), keys=["Alt+Shift+Up"],
                  enabled=lambda: picked() and bool(v.target_rows())
                  and v.target_rows()[0] > 0,
                  short="Up")
        self._add("row_down", "Move Rows Down", "row_down",
                  "Move the selected rows down one place.",
                  lambda: v.move_rows(1), keys=["Alt+Shift+Down"],
                  enabled=lambda: picked() and model() is not None
                  and bool(v.target_rows())
                  and v.target_rows()[-1] < model().rowCount() - 1,
                  short="Down")
        self._add("select_row", "Select Whole Rows", "select_row",
                  "Widen the selection to the whole of its rows — or click "
                  "a row number.",
                  v.select_selection_rows, keys=["Shift+Space"],
                  enabled=lambda: bool(v.selected_rows()), short="Rows")
        self._add("header", "Use Row as Column Names", "header",
                  "Rename the columns from this row's values and remove the "
                  "row — for pasted data that brought its headings with it.",
                  v.promote_current_row, enabled=picked,
                  short="Row → Names")

        # ---- columns
        self._add("col_left", "Insert Columns Left", "col_left",
                  "Insert as many blank columns as are selected, to their "
                  "left.",
                  lambda: v.insert_columns(right=False), enabled=edit,
                  short="Left")
        self._add("col_right", "Insert Columns Right", "col_right",
                  "Insert as many blank columns as are selected, to their "
                  "right.",
                  lambda: v.insert_columns(right=True), enabled=edit,
                  short="Right")
        self._add("col_delete", "Delete Columns", "col_delete",
                  "Delete every column the selection touches, cells, name "
                  "and type. Undo brings them back.",
                  v.delete_columns,
                  enabled=lambda: edit() and model() is not None
                  and 0 < len(v.target_columns()) < model().columnCount(),
                  short="Delete")
        self._add("col_move_left", "Move Columns Left", "col_move_left",
                  "Move the selected columns one place left.",
                  lambda: v.move_columns(-1), keys=["Alt+Shift+Left"],
                  enabled=lambda: edit() and bool(v.target_columns())
                  and v.target_columns()[0] > 0, short="Left")
        self._add("col_move_right", "Move Columns Right", "col_move_right",
                  "Move the selected columns one place right.",
                  lambda: v.move_columns(1), keys=["Alt+Shift+Right"],
                  enabled=lambda: edit() and bool(v.target_columns())
                  and model() is not None
                  and v.target_columns()[-1] < model().columnCount() - 1,
                  short="Right")
        self._add("select_col", "Select Whole Columns", "select_col",
                  "Widen the selection to the whole of its columns — or "
                  "click a column's name.",
                  v.select_selection_columns, keys=["Ctrl+Space"],
                  enabled=lambda: bool(v.selected_columns()), short="Columns")
        self._add("select_all", "Select All", "select_all",
                  "Select every cell.", v.selectAll, keys=["Ctrl+A"],
                  keyed=False)
        self._add("rename", "Rename Column…", "rename",
                  "Give the column a new name — or double-click its "
                  "header. Formulas using [Name] follow it.",
                  v.rename_current_column,
                  enabled=lambda: edit() and bool(v.target_columns()),
                  short="Rename")
        type_group = QActionGroup(self)
        for col_type in COLUMN_TYPES:
            action = self._add(
                f"type_{col_type}", col_type.capitalize(), None,
                TYPE_HELP[col_type],
                lambda on, t=col_type: self._set_type(t, on),
                enabled=lambda: edit() and bool(v.target_columns()),
                checked=lambda t=col_type: self._current_type() == t)
            type_group.addAction(action)
        self._add("col_type", "Column Type", "col_type",
                  "What kind of values the column holds. It decides how the "
                  "column leaves the node: numbers, dates, TRUE/FALSE or "
                  "text. Values that don't fit turn red.",
                  lambda: None,
                  enabled=lambda: edit() and bool(v.target_columns()),
                  short="Type")
        self._add("dropdown", "Dropdown List…", "dropdown",
                  "Give the column a list of values to pick from. Each cell "
                  "then opens as a dropdown (Alt+Down from the keyboard); "
                  "make the list strict and anything else turns red.",
                  v.edit_column_list,
                  enabled=lambda: edit() and bool(v.target_columns()),
                  short="Dropdown")
        self._add("validation", "Data Validation…", "validation",
                  "Limit what a column will take: whole numbers 1 to 100, "
                  "a date after today, text of at most 10 characters, or "
                  "never blank. A value that breaks the rule turns red — "
                  "or a typed one can be turned away.",
                  v.edit_validation,
                  enabled=lambda: edit() and bool(v.target_columns()),
                  short="Validation")
        self._add("next_problem", "Next Problem", "next_problem",
                  "Go to the next cell that is red or shows an error, with "
                  "what is wrong beside it — a broken rule, a value that "
                  "doesn't fit its column, a formula error.",
                  v.next_problem,
                  enabled=lambda: v.model() is not None
                  and v.model().rowCount() > 0,
                  short="Problems")
        self._add("open_dropdown", "Open Cell's List", None,
                  "Open the dropdown of a cell in a column with a list.",
                  v.open_cell_dropdown, keys=["Alt+Down"], enabled=edit)

        # ---- smart insert/delete (the keys Excel puts on Ctrl++ / Ctrl+-)
        self._add("insert_smart", "Insert", None,
                  "Insert rows — or columns, when whole columns are "
                  "selected.", v.insert_smart,
                  keys=["Ctrl++", "Ctrl+="], enabled=edit)
        self._add("delete_smart", "Delete", None,
                  "Delete rows — or columns, when whole columns are "
                  "selected.", v.delete_smart, keys=["Ctrl+-"],
                  enabled=picked)

        # ---- editing
        self._add("clear", "Clear Contents", "clear",
                  "Empty the selected cells. Rows and columns stay where "
                  "they are.",
                  v.delete_selection, keys=["Delete"], keyed=False,
                  enabled=picked, short="Clear")
        self._add("fill_down", "Fill Down", "fill_down",
                  "Copy the top cell of the selection into the cells below "
                  "it, adjusting formulas row by row (=A1 becomes =A2, =A3…). "
                  "With one row selected, fills from the row above.",
                  v.fill_down_selection, keys=["Ctrl+D"], enabled=picked,
                  short="Down")
        self._add("fill_right", "Fill Right", "fill_right",
                  "Copy the left cell of the selection across, adjusting "
                  "formulas column by column.",
                  v.fill_right_selection, keys=["Ctrl+R"], enabled=picked,
                  short="Right")
        self._add("define_name", "Define Name…", "define_name",
                  "Give the selected cells a name, so formulas can say "
                  "=SUM(Sales) instead of =SUM(B2:B40). Typing a new name "
                  "in the box left of the formula bar does it too.",
                  v.define_name, enabled=edit, short="Define Name")
        self._add("name_manager", "Name Manager…", "name_manager",
                  "Every defined name: what it refers to and holds now — "
                  "add, change or delete them.",
                  v.manage_names, enabled=edit, short="Name Manager")
        self._add("goto", "Go To…", "goto",
                  "Jump to a cell or a range: type B4, B2:D10, a column's "
                  "name, B:D for whole columns or 3:5 for whole rows.",
                  v.go_to, keys=["Ctrl+G"])
        self._add("goto_special", "Go To Special…", "goto_special",
                  "Select every cell of a kind — formulas, values you "
                  "typed, blanks, errors, problem cells — in the selection, "
                  "or in the whole table when one cell is selected.",
                  v.go_to_special, short="Special")
        for kind, label, body in (
                ("formulas", "Formulas",
                 "Select every cell that holds a formula — to check them "
                 "over, or to see what is worked out and what is typed."),
                ("constants", "Constants",
                 "Select every cell with a value typed in (not a formula)."),
                ("blanks", "Blanks",
                 "Select every empty cell. Then type a value and press "
                 "Ctrl+Enter to fill them all at once."),
                ("errors", "Errors",
                 "Select every cell showing an error such as #DIV/0! or "
                 "#REF!."),
                ("problems", "Problem Cells",
                 "Select every cell shown red — a value its column's type, "
                 "dropdown list or validation rule doesn't allow."),
                ("notes", "Notes",
                 "Select every cell with a note (the red corner).")):
            self._add(f"select_{kind}", f"Select {label}", f"select_{kind}",
                      body + " Looks inside the selection when it is more "
                      "than one cell.",
                      lambda k=kind: v.select_special(k), short=label)
        self._add("note_edit", "New Note…", "note",
                  "Write a note on the current cell — for whoever reads the "
                  "table next. A red corner marks it; hover to read it. It "
                  "never changes the value or what flows on.",
                  v.edit_note, keys=["Shift+F2"], enabled=edit,
                  short="Note")
        self._add("note_delete", "Delete Note", "note_delete",
                  "Take the note off the selected cells.",
                  v.delete_notes,
                  enabled=lambda: edit() and bool(v.note_targets()),
                  short="Delete")
        self._add("note_next", "Next Note", "note_next",
                  "Go to the next cell with a note and show it.",
                  v.next_note,
                  enabled=lambda: bool(v.sheet_model()
                                       and v.sheet_model().note_cells()),
                  short="Next")
        self._add("fill_series", "Fill Series…", "fill_series",
                  "Fill the selection with a series from its first cell — "
                  "1, 2, 3 …, 2, 4, 8 …, a date each month or each weekday "
                  "— with a step and an optional stop value. With one cell "
                  "selected, fills on to the stop value.",
                  v.fill_series,
                  enabled=lambda: edit() and v.currentIndex().isValid(),
                  short="Series")
        self._add("find", "Find…", "find",
                  "Find a value or a piece of a formula. Enter goes to the "
                  "next match.",
                  lambda: v.find_replace(False), keys=["Ctrl+F"])
        self._add("replace", "Replace…", "replace",
                  "Find text and replace it — in the selection or the whole "
                  "table, as one undoable change.",
                  lambda: v.find_replace(True), keys=["Ctrl+H"],
                  enabled=edit)

        # ---- sort and filter
        self._add("sort_asc", "Sort A → Z", "sort_asc",
                  "Sort every row by the selected column, smallest first. "
                  "Numbers sort as numbers and dates as dates; blanks go "
                  "last. This reorders the table itself.",
                  lambda: v.sort_current(True),
                  enabled=lambda: edit() and bool(v.target_columns()),
                  short="A → Z")
        self._add("sort_desc", "Sort Z → A", "sort_desc",
                  "Sort every row by the selected column, largest first.",
                  lambda: v.sort_current(False),
                  enabled=lambda: edit() and bool(v.target_columns()),
                  short="Z → A")
        self._add("sort_custom", "Custom Sort…", "sort_custom",
                  "Sort by several columns at once — Region A → Z, then "
                  "Total largest first — or by a dropdown list's own "
                  "order. Each level breaks the ties of the one above.",
                  v.custom_sort,
                  enabled=lambda: edit() and v.model() is not None
                  and v.model().columnCount() > 0,
                  short="Custom")
        self._add("sort_clear", "Undo Sort", None,
                  "Put the rows back in the order they had before you "
                  "started sorting.",
                  v.clear_sort,
                  enabled=lambda: edit() and v.has_active_sort)
        self._add("filter", "Filter Column…", "filter",
                  "Choose which values of this column to show — or click "
                  "the ▾ on its header. Filtering hides rows in the grid "
                  "only: the table the node sends on still has every row.",
                  self._filter_current, keys=["Ctrl+Shift+L"],
                  enabled=lambda: bool(v.selected_columns()), short="Filter")
        self._add("filter_value", "Filter by This Value", "filter",
                  "Show only the rows whose value in this column matches "
                  "this cell.",
                  v.filter_by_current_value,
                  enabled=lambda: v.currentIndex().isValid())
        self._add("split", "Text to Columns…", "split",
                  "Split the current column into several — at a comma, a "
                  "space or any character, or at fixed positions. A "
                  "preview shows the first rows before anything changes.",
                  v.text_to_columns,
                  enabled=lambda: edit() and v.currentIndex().isValid(),
                  short="Split")
        self._add("row_height", "Row Height…", "row_height",
                  "Set the selected rows' height in pixels. Dragging the "
                  "border under a row number does it too.",
                  v.set_row_height_dialog,
                  enabled=lambda: edit() and bool(v.target_rows()),
                  short="Row Height")
        self._add("row_autofit", "AutoFit Row Height", "row_autofit",
                  "Put the selected rows back to their usual height — or "
                  "tall enough for wrapped text. Double-clicking the border "
                  "under a row number does it too.",
                  v.autofit_rows,
                  enabled=lambda: edit() and bool(v.target_rows()),
                  short="Fit Rows")

        def any_hidden() -> bool:
            return any(v.hidden_count())

        self._add("row_hide", "Hide Rows", "row_hide",
                  "Put the selected rows out of sight. They stay in the "
                  "table and still go down the flow; a mark on the row "
                  "numbers shows where they are.",
                  v.hide_selected_rows, keys=["Ctrl+9"],
                  enabled=lambda: edit() and bool(v.target_rows()),
                  short="Hide Rows")
        self._add("row_unhide", "Unhide Rows", "row_unhide",
                  "Show the hidden rows within the selection or right "
                  "beside it — select the rows either side of them.",
                  v.unhide_selected_rows, keys=["Ctrl+Shift+9"],
                  enabled=lambda: edit() and v.hidden_count()[0] > 0,
                  short="Unhide Rows")
        self._add("col_hide", "Hide Columns", "col_hide",
                  "Put the selected columns out of sight. They stay in the "
                  "table and still flow on; a mark on the column headers "
                  "shows where they are.",
                  v.hide_selected_columns, keys=["Ctrl+0"],
                  enabled=lambda: edit() and bool(v.target_columns()),
                  short="Hide Columns")
        self._add("col_unhide", "Unhide Columns", "col_unhide",
                  "Show the hidden columns within the selection or right "
                  "beside it. Double-clicking the mark on the header does "
                  "it too.",
                  v.unhide_selected_columns, keys=["Ctrl+Shift+0"],
                  enabled=lambda: edit() and v.hidden_count()[1] > 0,
                  short="Unhide Columns")
        self._add("unhide_all", "Unhide All", "unhide_all",
                  "Show every hidden row and column.",
                  v.unhide_all, enabled=lambda: edit() and any_hidden(),
                  short="Unhide All")

        def has_groups() -> bool:
            model = v.sheet_model()
            return bool(model is not None and model.groups)

        self._add("group", "Group Rows", "group",
                  "Group the selected rows so they can be folded away under "
                  "a − button in the margin — detail rows under a summary. "
                  "Groups can sit inside groups.",
                  v.group_selected_rows,
                  enabled=lambda: edit() and bool(v.target_rows()),
                  short="Group")
        self._add("ungroup", "Ungroup Rows", "ungroup",
                  "Take the selected rows out of their group (one level at "
                  "a time).",
                  v.ungroup_selected_rows,
                  enabled=lambda: edit() and has_groups(), short="Ungroup")
        self._add("hide_detail", "Hide Detail", "hide_detail",
                  "Fold away the group the current row is in.",
                  lambda: v.set_detail(False), enabled=has_groups,
                  short="Hide")
        self._add("show_detail", "Show Detail", "show_detail",
                  "Unfold the group whose + is on the current row.",
                  lambda: v.set_detail(True), enabled=has_groups,
                  short="Show")
        self._add("collapse_all", "Collapse All", "collapse_all",
                  "Fold every group, leaving the summary rows.",
                  lambda: v.fold_all(True), enabled=has_groups,
                  short="Collapse")
        self._add("expand_all", "Expand All", "expand_all",
                  "Unfold every group.", lambda: v.fold_all(False),
                  enabled=has_groups, short="Expand")
        self._add("clear_outline", "Clear Outline", "clear_outline",
                  "Remove every group. The rows themselves stay.",
                  v.clear_outline, enabled=lambda: edit() and has_groups(),
                  short="Clear")
        self._add("dedupe", "Remove Duplicates…", "dedupe",
                  "Remove rows that repeat an earlier row on the columns "
                  "you tick — the first of each set stays. Shows how many "
                  "will go first, and can just select them instead.",
                  v.remove_duplicates,
                  enabled=lambda: edit() and bool(v.sheet_model())
                  and v.sheet_model().rowCount() > 1,
                  short="Duplicates")
        self._add("filter_clear", "Clear All Filters", "filter_clear",
                  "Show every row again.", v.clear_filters,
                  enabled=lambda: v.filtered, short="Clear")

        # ---- number formats (how values read; never what they are)
        def cols_ok() -> bool:
            return edit() and bool(v.target_columns())

        self._add("format_cells", "Format Cells…", "format",
                  "Choose how the column's values read — decimal places, "
                  "thousands separators, currency, percent, red or "
                  "bracketed negatives, how dates are written. Only the "
                  "look changes: the values, formulas and what flows on "
                  "stay as they are.",
                  v.format_cells, keys=["Ctrl+1"], enabled=cols_ok,
                  short="Format")
        self._add("number_format", "Number Format", "format",
                  "Pick a format for the column from the list — each shows "
                  "how a value will read.",
                  lambda: None, enabled=cols_ok, short="Format")
        self._add("fmt_currency", "Currency", "fmt_currency",
                  "Show the column as money: a currency symbol, thousands "
                  "separators and two decimal places. Typing £1,200 into it "
                  "stores 1200.",
                  lambda: v.apply_format(currency_format()),
                  enabled=cols_ok, short="Currency")
        self._add("fmt_percent", "Percent", "fmt_percent",
                  "Show the column as percentages: 0.25 reads 25%. Typing "
                  "25% into it stores 0.25.",
                  lambda: v.apply_format({"kind": "percent", "decimals": 0}),
                  enabled=cols_ok, short="Percent")
        self._add("fmt_thousands", "Thousands Separator", "fmt_thousands",
                  "Show numbers with thousands separators and two decimal "
                  "places: 1234.5 reads 1,234.50.",
                  lambda: v.apply_format({"kind": "number", "decimals": 2,
                                          "thousands": True}),
                  enabled=cols_ok, short="Thousands")
        self._add("dec_more", "Increase Decimal", "dec_more",
                  "Show one more decimal place.",
                  lambda: v.step_decimals(1), enabled=cols_ok,
                  short="More Decimals")
        self._add("dec_less", "Decrease Decimal", "dec_less",
                  "Show one fewer decimal place. The value keeps all its "
                  "digits — only what you see is rounded.",
                  lambda: v.step_decimals(-1), enabled=cols_ok,
                  short="Fewer Decimals")
        self._add("fmt_general", "General", None,
                  "No format: numbers show as they are.",
                  lambda: v.apply_format(None), enabled=cols_ok)

        # ---- the Total Row
        self._add("totals_row", "Total Row", "totals",
                  "A row of totals under the grid — Sum, Average, Count and "
                  "more, chosen per column (click a total to change it). "
                  "With a filter on, only the rows it shows are counted. "
                  "Display only: the table the node sends on has no total "
                  "row.",
                  v.toggle_totals, keys=["Ctrl+Shift+T"],
                  checked=lambda: bool(model() and model().show_totals),
                  enabled=edit, short="Total Row")
        self._add("total_menu", "Total", "totals",
                  "What the Total Row shows under the selected columns.",
                  lambda: None,
                  enabled=lambda: edit() and bool(v.target_columns()),
                  short="Total")

        # ---- conditional formatting (Show Table's rules)
        def can_format() -> bool:
            return v.host.can_format() and bool(v.target_columns())

        self._add("cond_format", "Conditional Formatting", "cond_format",
                  "Colour cells by their values — colour scales, data bars, "
                  "icon sets, or highlight the cells that meet a test. Each "
                  "choice adds a rule in Show Table's rules language, which "
                  "the Conditional formatting box in Properties shows and "
                  "edits. Rules only paint: values are never changed.",
                  lambda: None, enabled=can_format, short="Conditional")
        self._add("cf_manage", "Manage Rules…", "cf_manage",
                  "Every conditional-formatting rule on this table, to add, "
                  "edit, reorder and remove — Show Table's rule builder.",
                  self._manage_rules,
                  enabled=lambda: v.host.can_format(), short="Rules")

        # ---- view
        self._add("freeze", "Freeze Panes", "freeze",
                  "Keep the rows above and the columns left of the selected "
                  "cell in place while the rest scrolls.",
                  v.freeze_panes, enabled=edit, short="Panes")
        self._add("freeze_row", "Freeze Top Row", "freeze_row",
                  "Keep the first row in view while scrolling down.",
                  v.freeze_top_row, enabled=edit, short="Top Row")
        self._add("freeze_col", "Freeze First Column", "freeze_col",
                  "Keep the first column in view while scrolling across — "
                  "for a column of names or ids.",
                  v.freeze_first_column, enabled=edit, short="First Column")
        self._add("unfreeze", "Unfreeze Panes", "unfreeze",
                  "Let every row and column scroll again.",
                  v.unfreeze,
                  enabled=lambda: edit() and model() is not None
                  and any(model().freeze), short="Unfreeze")
        self._add("fit", "Fit Column Width", "fit",
                  "Size the selected columns to their contents — or "
                  "double-click a column's right edge.",
                  lambda: v.autosize_columns(v.target_columns() or None),
                  short="Fit")
        self._add("fit_all", "Fit All Columns", "fit",
                  "Size every column to its contents.",
                  lambda: v.autosize_columns(), short="Fit All")
        self._add("show_formulas", "Show Formulas", "show_formulas",
                  "Show each cell's formula instead of its result, to check "
                  "how a sheet is worked out. Only changes what you see.",
                  v.set_show_formulas, keys=["Ctrl+`"],
                  checked=lambda: v.show_formulas, short="Formulas")

        # ---- formulas
        self._add("reference", "Function Reference", "reference",
                  "Every function the formulas know, with what it takes and "
                  "an example.",
                  self._show_reference, short="Reference")
        self._add("insert_function", "Insert Function", "fx",
                  "Start a formula in the selected cell with a function — "
                  "pick one from the list.",
                  lambda: None, enabled=edit, short="Function")

        # ---- applying edits
        self._add("submit", "Submit", "submit",
                  "Send your edits into the flow and update what depends "
                  "on this table. Until then the flow keeps using the "
                  "table as it was last submitted.",
                  self._submit, keys=["F9"],
                  enabled=lambda: bool(v.host.pending_text()))
        self._add("discard", "Discard Edits", "discard",
                  "Throw away the edits not yet submitted and go back to "
                  "the table the flow is using. Undo brings them back.",
                  lambda: v.host.discard(),
                  enabled=lambda: bool(v.host.pending_text()),
                  short="Discard")
        self._add("auto", "Auto-apply Edits", "auto",
                  "On: every edit goes straight into the flow. Off: edits "
                  "wait until you Submit — for a table at the start of a "
                  "big flow, where each change would otherwise start a "
                  "long re-run.",
                  self._set_auto,
                  checked=lambda: v.host.mode() == "live",
                  enabled=lambda: v.host.can_hold(), short="Auto-apply")
        self._add("open_editor", "Open Full Editor", "expand",
                  "Open this table in a window of its own, with the full "
                  "ribbon and room to work.",
                  lambda: v.host.open_editor(),
                  enabled=lambda: v.host.can_open_editor(), short="Expand")

    # ---------------------------------------------------------- handlers

    def _current_type(self) -> str:
        model = self._view.sheet_model()
        cols = self._view.target_columns()
        return model.column_type(cols[0]) if model and cols else ""

    def _set_type(self, col_type: str, on: bool) -> None:
        model = self._view.sheet_model()
        if not on or model is None:
            return
        for col in self._view.target_columns():
            model.set_column_type(col, col_type)

    def _manage_rules(self) -> None:
        from .cond_format import manage_rules
        manage_rules(self._view)

    def _filter_current(self) -> None:
        cols = self._view.target_columns()
        if cols:
            self._view.open_column_filter(cols[0])

    def _show_reference(self) -> None:
        from .tools import FormulaReferenceDialog
        FormulaReferenceDialog(self._view.window()).show()

    def _submit(self) -> None:
        self._view.commit_open_editor()
        self._view.host.submit()

    def _set_auto(self, on: bool) -> None:
        host = self._view.host
        wanted = "live" if on else "submit"
        if host.mode() != wanted:
            self._view.commit_open_editor()
            host.set_mode(wanted)

    def _stack(self):
        return self._view.host.undo_stack()

    def _stack_can(self, what: str) -> bool:
        stack = self._stack()
        if stack is None:
            return False
        return stack.canUndo() if what == "undo" else stack.canRedo()

    def _stack_do(self, what: str) -> None:
        stack = self._stack()
        if stack is not None:
            stack.undo() if what == "undo" else stack.redo()

    # ------------------------------------------------------------ refresh

    def refresh(self) -> None:
        """Re-read which commands apply right now."""
        stack = self._stack()
        if stack is not self._watched_stack:
            if self._watched_stack is not None:
                try:
                    self._watched_stack.indexChanged.disconnect(self._on_stack)
                except (RuntimeError, TypeError):
                    pass
            self._watched_stack = stack
            if stack is not None:
                stack.indexChanged.connect(self._on_stack)
        for name, rule in self._rules.items():
            try:
                self._actions[name].setEnabled(bool(rule()))
            except (IndexError, RuntimeError):
                self._actions[name].setEnabled(False)
        # say how many: "Delete 3 Rows" is what will happen, "Delete Rows"
        # leaves the user to count
        rows = len(self._view.target_rows()) or 1
        cols = len(self._view.target_columns()) or 1
        for name, (one, many, n) in {
                "row_above": ("Insert Row Above", "Insert {n} Rows Above", rows),
                "row_below": ("Insert Row Below", "Insert {n} Rows Below", rows),
                "row_delete": ("Delete Row", "Delete {n} Rows", rows),
                "row_up": ("Move Row Up", "Move {n} Rows Up", rows),
                "row_down": ("Move Row Down", "Move {n} Rows Down", rows),
                "col_left": ("Insert Column Left",
                             "Insert {n} Columns Left", cols),
                "col_right": ("Insert Column Right",
                              "Insert {n} Columns Right", cols),
                "col_delete": ("Delete Column", "Delete {n} Columns", cols),
                "col_move_left": ("Move Column Left",
                                  "Move {n} Columns Left", cols),
                "col_move_right": ("Move Column Right",
                                   "Move {n} Columns Right", cols),
        }.items():
            self._actions[name].setText(one if n == 1 else many.format(n=n))
        # Auto-apply says which way it is: a lit button alone leaves a new
        # user guessing whether lit means "applying" or "holding"
        auto = self._actions["auto"]
        live = self._view.host.mode() == "live"
        auto.setIconText("Auto-apply: On" if live else "Auto-apply: Off")
        auto.setToolTip(tip(
            "Auto-apply edits — " + ("on" if live else "off"),
            ("Every edit goes straight into the flow. Turn it off to hold "
             "edits until you Submit — for a table at the start of a big "
             "flow, where each change would otherwise start a long re-run.")
            if live else
            ("Edits wait until you press Submit (F9); the flow keeps using "
             "the table as last submitted. Turn it on to send every edit "
             "straight into the flow again (anything waiting goes with "
             "it).")))
        for name, rule in self._checks.items():
            action = self._actions[name]
            want = bool(rule())
            if action.isChecked() != want:
                action.blockSignals(True)
                action.setChecked(want)
                action.blockSignals(False)
                # toggled stays quiet (it would run the command); changed
                # lets a ribbon button show the new state
                action.changed.emit()
        self.changed_hook()

    def _on_stack(self, _index: int) -> None:
        self.refresh()

    def changed_hook(self) -> None:
        """Replaced by a ribbon that wants to hear about a refresh."""
        for listener in list(getattr(self, "_listeners", ())):
            listener()

    def listen(self, callback) -> None:
        if not hasattr(self, "_listeners"):
            self._listeners = []
        self._listeners.append(callback)
