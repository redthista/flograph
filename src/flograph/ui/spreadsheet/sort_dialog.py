"""Custom Sort… — Excel's Sort dialog for a Table.

One line per level: *Sort by* a column, *then by* another to break its
ties, and so on — Region A → Z, then Total largest first. Each line's
Order list speaks the column's type ("Oldest to Newest" for a date,
"Smallest to Largest" for a number) and, for a column with a dropdown list,
offers the list's own order (North, South, East, West). OK sorts the rows
as one undo step; the levels are remembered for the next time the dialog
opens on that grid.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFrame,
                               QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from .icons import sheet_icon
from .menus import real_window

# (key, ascending, by_list) for each Order entry; the words depend on type
_ORDERS = {
    "number": ("Smallest to Largest", "Largest to Smallest"),
    "integer": ("Smallest to Largest", "Largest to Smallest"),
    "date": ("Oldest to Newest", "Newest to Oldest"),
    "bool": ("FALSE before TRUE", "TRUE before FALSE"),
    "text": ("A to Z", "Z to A"),
    "auto": ("A to Z (numbers first)", "Z to A"),
}
_HELP = ("Rows are put in order by the first level. Where rows tie on it — "
         "the same Region, say — the next level decides, and so on down. "
         "Blank cells always go last.")
_FOOT = ("Sorting reorders the table itself, hidden rows too. Formulas keep "
         "their cell addresses, as in Excel. Undo (Ctrl+Z) or Undo Sort puts "
         "the rows back.")


def order_choices(column) -> list[tuple[str, bool, bool]]:
    """The Order entries for a column: ``(label, ascending, by_list)``."""
    up, down = _ORDERS.get(column.type, _ORDERS["auto"])
    entries = [(up, True, False), (down, False, False)]
    if column.choices:
        sample = ", ".join(column.choices[:3])
        if len(column.choices) > 3:
            sample += ", …"
        entries += [(f"Dropdown list order ({sample})", True, True),
                    ("Dropdown list, reversed", False, True)]
    return entries


class _Level(QFrame):
    """One line of the dialog: the column to sort on and which way."""

    def __init__(self, dialog: "SortDialog", columns) -> None:
        super().__init__()
        self.setObjectName("sort_level")
        self._dialog = dialog
        self._columns = columns
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)
        self.caption = QLabel()
        self.caption.setFixedWidth(56)
        row.addWidget(self.caption)
        self.column = QComboBox()
        for i, spec in enumerate(columns):
            self.column.addItem(spec.name, i)
        self.column.setMinimumWidth(150)
        row.addWidget(self.column, 1)
        self.order = QComboBox()
        self.order.setMinimumWidth(190)
        row.addWidget(self.order, 1)
        self.column.currentIndexChanged.connect(self._column_changed)
        self.order.currentIndexChanged.connect(dialog._refresh)
        for widget in (self, self.caption, self.column, self.order):
            widget.installEventFilter(self)
        self._column_changed()

    def eventFilter(self, watched, event) -> bool:
        # clicking anywhere on a line (its lists included) makes it the one
        # Delete, Copy and the arrows act on
        if event.type() in (QEvent.MouseButtonPress, QEvent.FocusIn):
            self._dialog.select(self)
        return False

    @staticmethod
    def _key(ascending: bool, by_list: bool) -> str:
        # item data as text: Qt hands a tuple back as a list, and findData
        # never matches it again
        return ("list_" if by_list else "") + ("asc" if ascending else "desc")

    def _column_changed(self, *_args) -> None:
        keep = self.order.currentData()
        spec = self._columns[self.column.currentData()]
        self.order.blockSignals(True)
        self.order.clear()
        for label, ascending, by_list in order_choices(spec):
            self.order.addItem(label, self._key(ascending, by_list))
        if keep is not None:
            found = self.order.findData(keep)
            if found < 0:     # the list order went with the old column
                found = self.order.findData(keep.removeprefix("list_"))
            self.order.setCurrentIndex(max(0, found))
        self.order.blockSignals(False)
        self._dialog._refresh()

    def set_level(self, col: int, ascending: bool, by_list: bool) -> None:
        self.column.setCurrentIndex(max(0, self.column.findData(col)))
        found = self.order.findData(self._key(ascending, by_list))
        if found < 0:
            found = self.order.findData(self._key(ascending, False))
        self.order.setCurrentIndex(max(0, found))

    def level(self) -> tuple[int, bool, bool]:
        key = self.order.currentData() or "asc"
        return (self.column.currentData(), key.endswith("asc"),
                key.startswith("list_"))


class SortDialog(QDialog):
    def __init__(self, columns, levels, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sort")
        self._columns = columns
        self._levels: list[_Level] = []
        self._selected: Optional[_Level] = None

        layout = QVBoxLayout(self)
        intro = QLabel(_HELP)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        tools = QHBoxLayout()
        self.add_button = self._tool("row_below", "Add Level",
                                     "Add a level under the selected one "
                                     "to break its ties.", self.add_level)
        self.delete_button = self._tool("row_delete", "Delete Level",
                                        "Remove the selected level.",
                                        self.delete_level)
        self.copy_button = self._tool("copy", "Copy Level",
                                      "Add a copy of the selected level "
                                      "under it.", self.copy_level)
        self.up_button = self._tool("chevron_up", "",
                                    "Move the selected level up — it then "
                                    "counts for more.",
                                    lambda: self.move_level(-1))
        self.down_button = self._tool("chevron_down", "",
                                      "Move the selected level down.",
                                      lambda: self.move_level(1))
        for button in (self.add_button, self.delete_button, self.copy_button,
                       self.up_button, self.down_button):
            tools.addWidget(button)
        tools.addStretch(1)
        layout.addLayout(tools)

        heads = QHBoxLayout()
        heads.setContentsMargins(8, 0, 8, 0)
        spacer = QLabel()
        spacer.setFixedWidth(56)
        heads.addWidget(spacer)
        for text in ("Column", "Order"):
            label = QLabel(text)
            label.setStyleSheet("color: #9ca3af;")
            heads.addWidget(label, 1)
        layout.addLayout(heads)

        holder = QWidget()
        self._rows = QVBoxLayout(holder)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(2)
        self._rows.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        scroll.setMinimumHeight(150)
        layout.addWidget(scroll, 1)

        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color: #fbbf24;")
        layout.addWidget(self.warning)
        foot = QLabel(_FOOT)
        foot.setWordWrap(True)
        foot.setStyleSheet("color: #9ca3af;")
        layout.addWidget(foot)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                        | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Sort")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        for col, ascending, by_list in levels or [(0, True, False)]:
            self.add_level().set_level(col, ascending, by_list)
        self.select(self._levels[0])
        self.resize(560, 360)

    def _tool(self, icon: str, text: str, tip: str, slot) -> QPushButton:
        button = QPushButton(sheet_icon(icon), text)
        button.setToolTip(tip)
        button.clicked.connect(lambda _=False: slot())
        return button

    # ------------------------------------------------------------ levels

    def add_level(self, copy_of: Optional[_Level] = None) -> _Level:
        line = _Level(self, self._columns)
        if copy_of is not None:
            line.set_level(*copy_of.level())
        elif self._levels:
            # a new level starts on the first column not yet sorted on
            used = {lvl.level()[0] for lvl in self._levels}
            free = [i for i in range(len(self._columns)) if i not in used]
            line.set_level(free[0] if free else 0, True, False)
        at = (self._levels.index(self._selected) + 1
              if self._selected in self._levels else len(self._levels))
        self._levels.insert(at, line)
        self._rows.insertWidget(at, line)
        self.select(line)
        return line

    def copy_level(self) -> None:
        if self._selected is not None:
            self.add_level(self._selected)

    def delete_level(self) -> None:
        if self._selected is None or len(self._levels) <= 1:
            return
        at = self._levels.index(self._selected)
        line = self._levels.pop(at)
        line.setParent(None)
        line.deleteLater()
        self._selected = None
        self.select(self._levels[min(at, len(self._levels) - 1)])

    def move_level(self, step: int) -> None:
        if self._selected is None:
            return
        at = self._levels.index(self._selected)
        to = at + step
        if not 0 <= to < len(self._levels):
            return
        self._levels.insert(to, self._levels.pop(at))
        self._rows.removeWidget(self._selected)
        self._rows.insertWidget(to, self._selected)
        self._refresh()

    def select(self, line: _Level) -> None:
        self._selected = line
        self._refresh()

    def _refresh(self, *_args) -> None:
        for i, line in enumerate(self._levels):
            line.caption.setText("Sort by" if i == 0 else "Then by")
            line.setStyleSheet(
                "QFrame#sort_level { background: #2b3550;"
                " border: 1px solid #60a5fa; border-radius: 3px; }"
                if line is self._selected else
                "QFrame#sort_level { border: 1px solid transparent; }")
        at = (self._levels.index(self._selected)
              if self._selected in self._levels else -1)
        self.delete_button.setEnabled(len(self._levels) > 1)
        self.up_button.setEnabled(at > 0)
        self.down_button.setEnabled(0 <= at < len(self._levels) - 1)
        self.add_button.setEnabled(bool(self._columns))
        seen: dict[int, int] = {}
        twice = []
        for line in self._levels:
            col = line.level()[0]
            if col in seen and col not in twice:
                twice.append(col)
            seen.setdefault(col, 0)
        self.warning.setText(
            "" if not twice else
            ", ".join(self._columns[c].name for c in twice)
            + (" is" if len(twice) == 1 else " are")
            + " sorted on more than once — only the first of those levels "
              "counts.")

    def levels(self) -> list[tuple[int, bool, bool]]:
        return [line.level() for line in self._levels]


def custom_sort(view) -> None:
    """Open the Sort dialog on a grid and sort by what it returns."""
    model = view.sheet_model()
    if model is None or not view.editable or not model.sheet.columns:
        return
    columns = model.sheet.columns
    names = [c.name for c in columns]
    remembered = [(names.index(name), asc, by_list)
                  for name, asc, by_list in view.sort_levels_used
                  if name in names]
    if not remembered:
        cols = view.target_columns()
        remembered = [(cols[0] if cols else 0, True, False)]
    dialog = SortDialog(columns, remembered, real_window(view))
    if dialog.exec():
        levels = dialog.levels()
        view.sort_levels_used = [(names[c], asc, by_list)
                                 for c, asc, by_list in levels]
        view.sort_with_levels(levels)
