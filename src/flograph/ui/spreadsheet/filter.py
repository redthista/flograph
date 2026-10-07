"""A column's ▾: Excel's sort-and-filter popup.

Sort buttons on top, then a search box and a tick list of the column's
values with how many rows hold each, and OK. Ticking values *hides* the
other rows in this grid — it is a way of looking at the table, not a change
to it, so the Table still sends every row down the flow, and nothing is
saved. (To filter what flows on, wire a Filter Rows node after the Table.)

It opens as a popup window over the header (canvas/popup_lift.py explains
why a card's popups must be windows), and closes on a click elsewhere or
Escape like any menu.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout)

from .. import theme
from ..canvas.popup_lift import (DismissedByAClickElsewhere, _screen_for,
                                 popup_geometry)
from .icons import sheet_icon
from .menus import global_pos, real_window

BLANK = "(Blanks)"
_SELECT_ALL = "(Select All)"


def _sort_key(text: str):
    try:
        return (0, float(text), "")
    except ValueError:
        return (1, 0.0, text.casefold())


class FilterPopup(DismissedByAClickElsewhere, QFrame):
    def __init__(self, view, col: int) -> None:
        super().__init__()
        self.setObjectName("sheet_filter")
        self.setWindowFlags(Qt.Popup)
        self.setStyleSheet(
            f"QFrame#sheet_filter {{ background: {theme.NODE_BODY.name()};"
            f" border: 1px solid #3c3f49; }}"
            f"QLabel {{ color: #9ca3af; font-size: 8pt; }}"
            f"QListWidget {{ background: #202127; color: #e5e7eb;"
            f" border: 1px solid #3c3f49; }}"
            f"QLineEdit {{ background: #202127; color: #e5e7eb;"
            f" border: 1px solid #3c3f49; padding: 3px; }}"
            f"QPushButton {{ color: #e5e7eb; background: #34363f;"
            f" border: 1px solid #44475a; border-radius: 3px;"
            f" padding: 3px 10px; }}"
            f"QPushButton:hover {{ background: #3e414c; }}"
            f"QPushButton#filter_ok {{ background: #3b4a7a;"
            f" border-color: #60a5fa; }}")
        self._view, self._col = view, col
        model = view.sheet_model()
        name = model.sheet.columns[col].name

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        sorts = QHBoxLayout()
        for label, icon, ascending in (("Sort A → Z", "sort_asc", True),
                                       ("Sort Z → A", "sort_desc", False)):
            button = QPushButton(sheet_icon(icon), label)
            button.setToolTip(
                f"Sort every row by {name}, "
                f"{'smallest' if ascending else 'largest'} first. This "
                "reorders the table itself; Undo puts it back.")
            button.setEnabled(view.editable)
            button.clicked.connect(
                lambda _=False, a=ascending: self._sort(a))
            sorts.addWidget(button)
        layout.addLayout(sorts)

        layout.addWidget(QLabel(f"Show rows where {name} is:"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search values…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._search)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.itemChanged.connect(self._item_changed)
        layout.addWidget(self.list, 1)

        counts: dict[str, int] = {}
        for row in range(model.rowCount()):
            text = model.value_text(row, col)
            counts[text] = counts.get(text, 0) + 1
        allowed = view.column_filter(col)
        self._updating = True
        self._all = QListWidgetItem(_SELECT_ALL)
        self._all.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        self.list.addItem(self._all)
        for text in sorted(counts, key=lambda t: (t == "", _sort_key(t))):
            shown = text if text else BLANK
            item = QListWidgetItem(f"{shown}   ({counts[text]})")
            item.setData(Qt.UserRole, text)
            item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Checked if allowed is None or text in allowed
                               else Qt.Unchecked)
            self.list.addItem(item)
        self._updating = False
        self._sync_all()

        buttons = QHBoxLayout()
        clear = QPushButton("Clear Filter")
        clear.setToolTip(f"Show every row again, whatever {name} holds.")
        clear.setEnabled(allowed is not None)
        clear.clicked.connect(self._clear)
        ok = QPushButton("OK")
        ok.setObjectName("filter_ok")
        ok.setToolTip("Hide the rows whose value isn't ticked. Only this "
                      "grid changes: the Table still sends every row on.")
        ok.clicked.connect(self._apply)
        buttons.addWidget(clear)
        buttons.addStretch(1)
        buttons.addWidget(ok)
        layout.addLayout(buttons)
        self.resize(250, 330)

    def _values(self):
        for i in range(1, self.list.count()):
            yield self.list.item(i)

    def _search(self, text: str) -> None:
        needle = text.strip().casefold()
        for item in self._values():
            value = item.data(Qt.UserRole) or BLANK
            item.setHidden(bool(needle) and needle not in value.casefold())

    def _item_changed(self, item) -> None:
        if self._updating:
            return
        self._updating = True
        if item is self._all:
            state = item.checkState()
            for value in self._values():
                if not value.isHidden():
                    value.setCheckState(state)
        self._updating = False
        self._sync_all()

    def _sync_all(self) -> None:
        values = list(self._values())
        checked = sum(1 for v in values if v.checkState() == Qt.Checked)
        self._updating = True
        self._all.setCheckState(
            Qt.Checked if checked == len(values) else
            Qt.Unchecked if checked == 0 else Qt.PartiallyChecked)
        self._updating = False

    def _sort(self, ascending: bool) -> None:
        self.hide()
        self._view.sort_column(self._col, ascending)

    def _clear(self) -> None:
        self.hide()
        self._view.set_column_filter(self._col, None)

    def _apply(self) -> None:
        values = list(self._values())
        allowed = {v.data(Qt.UserRole) for v in values
                   if v.checkState() == Qt.Checked}
        self.hide()
        self._view.set_column_filter(
            self._col, None if len(allowed) == len(values) else allowed)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._apply()
            return
        super().keyPressEvent(event)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.deleteLater()


def open_filter_popup(view, col: int) -> None:
    model = view.sheet_model()
    if model is None or not 0 <= col < model.columnCount():
        return
    header = view.horizontalHeader()
    popup = FilterPopup(view, col)
    popup.setParent(real_window(view), Qt.Popup)
    x = header.sectionViewportPosition(col)
    top_left = global_pos(header, QPoint(x, 0))
    bottom = global_pos(header, QPoint(x, header.height()))
    anchor = QRect(top_left, QSize(max(header.sectionSize(col), 1),
                                   max(bottom.y() - top_left.y(), 1)))
    popup.setGeometry(popup_geometry(anchor, popup.size(),
                                     _screen_for(anchor.center())))
    popup.show()
    popup.search.setFocus()
