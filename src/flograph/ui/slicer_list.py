"""Shared checkbox/radio list for Slicer nodes — hosted by the canvas card
and by dashboard tiles. The widget only reflects and reports ticks; the
host commits the emitted param value and triggers the downstream re-run."""
from __future__ import annotations

import json

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QGridLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QStyle, QStyleOptionButton, QStyleOptionViewItem, QStyledItemDelegate,
    QToolButton, QWidget,
)

from . import theme

# How many checkbox rows to *build at once*. Not a cap on the column: the
# full value list is held in the widget and every value is reachable through
# the search box, which re-renders to the matches. QListWidget builds one
# child per row, so materialising tens of thousands of them at once locks the
# UI up while it works and scrolls badly afterwards — this bounds that cost
# without bounding what the slicer can filter on. Ticks on values outside the
# rendered window are kept (they live in `_selected`, not in the rows) and
# reported, so nothing is lost by a value not currently having a row.
RENDER_BUDGET = 500
MODES = ("multi", "single")


class _IndicatorDelegate(QStyledItemDelegate):
    """Swaps each row's check indicator for a radio button in single mode.

    Qt has no "exclusive" list widget, so single mode is still checkboxes
    underneath — but a checkbox promises you can tick several, which single
    mode then silently undoes. Every tool this borrows from (Power BI, Excel)
    draws radios there, so the widget does too. Purely cosmetic: check state
    is still what the list stores and reports.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.radio = False

    def paint(self, painter, option, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        has_check = bool(opt.features
                         & QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator)
        if not self.radio or not has_check:
            super().paint(painter, option, index)
            return

        style = opt.widget.style() if opt.widget else QApplication.style()
        # both measured while the indicator is still declared: dropping it is
        # what lets the row draw without a checkbox, but it also collapses the
        # column the indicator occupied, sliding the label left over the radio
        rect = style.subElementRect(
            QStyle.SE_ItemViewItemCheckIndicator, opt, opt.widget)
        text_left = style.subElementRect(
            QStyle.SE_ItemViewItemText, opt, opt.widget).left()
        checked = opt.checkState == Qt.Checked

        opt.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        opt.checkState = Qt.Unchecked
        # measured rather than assumed: the gap a style leaves around the
        # indicator is a style detail, and the text layout is linear in
        # rect.left, so re-indenting by the difference lands it exactly back
        collapsed_left = style.subElementRect(
            QStyle.SE_ItemViewItemText, opt, opt.widget).left()
        opt.rect = option.rect.adjusted(text_left - collapsed_left, 0, 0, 0)
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)

        button = QStyleOptionButton()
        button.rect = rect
        button.state = QStyle.State_Enabled | (
            QStyle.State_On if checked else QStyle.State_Off)
        style.drawPrimitive(
            QStyle.PE_IndicatorRadioButton, button, painter, opt.widget)


def selected_param_values(raw) -> list[str]:
    """The ticked values of a Slicer's "selected" param as strings. Lives in
    core so the widget, the node's run() and the engine's introspection all
    read a hand-edited param the same way."""
    from flograph.core.controls import selected_values
    return selected_values(raw)


class SlicerListWidget(QListWidget):
    # the new "selected" param value: a JSON array, or "" for nothing ticked
    selection_committed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"QListWidget {{ background: {theme.NODE_BODY.name()};"
            f" color: {theme.NODE_TEXT.name()}; border: none;"
            f" font-size: 9pt; }}"
            f"QListWidget::item {{ padding: 1px 2px; }}")
        self._syncing = False
        self._mode = "multi"
        self._filter_text = ""
        # the full picture, independent of which rows are currently built:
        self._all_values: list[str] = []
        self._selected: set[str] = set()
        self._delegate = _IndicatorDelegate(self)
        self.setItemDelegate(self._delegate)
        self.itemChanged.connect(self._on_item_changed)

    def _indicator_rect(self, item: QListWidgetItem) -> QRect:
        """Where this row's tick box is drawn, in viewport coordinates."""
        option = QStyleOptionViewItem()
        self.initViewItemOption(option)
        option.rect = self.visualItemRect(item)
        option.features |= \
            QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        return self.style().subElementRect(
            QStyle.SE_ItemViewItemCheckIndicator, option, self)

    def mouseReleaseEvent(self, event) -> None:
        """Clicking anywhere on a row ticks it, not just the tick box itself.
        A slicer row reads as one target — Power BI and Excel both treat it
        that way — and hitting a 14px box is needless precision. The box is
        left to the base class, which already toggles it; doing both would
        toggle twice and cancel out."""
        position = event.position().toPoint()
        item = self.itemAt(position)
        if item is not None and item.flags() & Qt.ItemIsUserCheckable \
                and not self._indicator_rect(item).contains(position):
            item.setCheckState(Qt.Unchecked
                               if item.checkState() == Qt.Checked
                               else Qt.Checked)
        super().mouseReleaseEvent(event)

    def set_options(self, values: list[str], selected: set[str]) -> None:
        """Take a column's unique values and the ticked set, then render the
        rows. Every tick re-runs the slicer and lands back here (the options
        come from the freshly-cached upstream table), so the current search
        filter is preserved — otherwise the list would silently reset to
        "everything visible" mid-search on the first tick."""
        self._all_values = list(values)
        present = set(self._all_values)
        self._selected = {v for v in selected if v in present}
        self._rebuild_rows()

    def _matching_values(self) -> list[str]:
        """The values that pass the current search filter, in column order.
        No filter → every value."""
        needle = self._filter_text.lower()
        if not needle:
            return list(self._all_values)
        return [v for v in self._all_values if needle in v.lower()]

    def _rebuild_rows(self) -> None:
        """Build QListWidgetItems for the values worth showing right now:
        the search matches, plus any ticked value (so a tick always has a
        visible row), capped at RENDER_BUDGET with a trailing note for the
        remainder. `_selected` — not the rows — is the record of what's
        ticked, so values past the cap keep their state."""
        needle = self._filter_text.lower()
        visible = [v for v in self._all_values
                   if (not needle or needle in v.lower()
                       or v in self._selected)]
        shown, hidden = visible[:RENDER_BUDGET], visible[RENDER_BUDGET:]
        self._syncing = True
        try:
            self.clear()
            for value in shown:
                item = QListWidgetItem(value)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.Checked if value in self._selected else Qt.Unchecked)
                self.addItem(item)
            if hidden:
                note = QListWidgetItem(
                    f"… {len(hidden):,} more — search to narrow the list"
                    if not needle
                    else f"… {len(hidden):,} more match — refine the search")
                note.setFlags(Qt.NoItemFlags)
                self.addItem(note)
        finally:
            self._syncing = False

    def set_mode(self, mode: str) -> None:
        """"multi" (any number of ticks) or "single" (radio-style: ticking
        one clears the rest, and clicking the ticked value again clears it).
        Flipping from multi to single with more than one value already
        ticked trims down to the first, so the card and the "selected" param
        it commits never disagree about how many values are active."""
        mode = mode if mode in MODES else "multi"
        entering_single = mode == "single" and self._mode != "single"
        self._mode = mode
        self._delegate.radio = mode == "single"
        self.viewport().update()
        if entering_single:
            self._trim_to_single_selection()

    def _trim_to_single_selection(self) -> None:
        if len(self._selected) <= 1:
            return
        first = next((v for v in self._all_values if v in self._selected), None)
        self._selected = {first} if first is not None else set()
        self._rebuild_rows()
        self._commit()

    def sync_checks(self, selected: set[str]) -> None:
        """Re-apply the ticked set without re-emitting — for when the param
        changes elsewhere (properties panel, undo)."""
        present = set(self._all_values)
        self._selected = {v for v in selected if v in present}
        self._rebuild_rows()

    def set_filter(self, text: str) -> None:
        """Narrow the list to values matching `text` (case-insensitive
        substring). Ticked values stay listed whether or not they match, and
        ticks on values with no row still count — `_selected` holds them, not
        the rows. Remembered and re-applied by `set_options`, so a tick
        mid-search doesn't reset the list."""
        self._filter_text = text.strip()
        self._rebuild_rows()

    def select_all(self) -> None:
        """Tick every value matching the current search — a no-op in single
        mode. Reaches matches with no row too, not just the ones on screen."""
        if self._mode == "single":
            return
        self._selected |= set(self._matching_values())
        self._rebuild_rows()
        self._commit()

    def clear_all(self) -> None:
        """Untick every value matching the current search."""
        self._selected -= set(self._matching_values())
        self._rebuild_rows()
        self._commit()

    def selected_values(self) -> list[str]:
        """The ticked values, in column order — including any whose row is
        outside the render window or the current search."""
        return [v for v in self._all_values if v in self._selected]

    def selection_summary(self) -> str:
        """"N/M" ticked-of-total for a compact status label; "" when there
        are no values yet."""
        total = len(self._all_values)
        if not total:
            return ""
        return f"{len(self._selected)}/{total}"

    def _on_item_changed(self, item) -> None:
        if self._syncing:
            return
        value = item.text()
        checked = item.checkState() == Qt.Checked
        if self._mode == "single" and checked:
            self._selected = {value}
            self._syncing = True
            try:
                for i in range(self.count()):
                    other = self.item(i)
                    if other is not item \
                            and other.flags() & Qt.ItemIsUserCheckable:
                        other.setCheckState(Qt.Unchecked)
            finally:
                self._syncing = False
        elif checked:
            self._selected.add(value)
        else:
            self._selected.discard(value)
        self._commit()

    def _commit(self) -> None:
        selected = self.selected_values()
        self.selection_committed.emit(json.dumps(selected) if selected else "")


class SlicerToolbar(QWidget):
    """Compact search box + Select All / None row that drives a
    SlicerListWidget — a separate widget so both hosts (canvas card,
    dashboard tile) can lay it out above their list without the list itself
    changing shape."""

    #: below this widget width the All/None/count row drops under the search
    #: box instead of sitting beside it — so the card can be made narrow
    #: without the buttons clipping off the edge
    WRAP_BELOW = 190

    def __init__(self, target: SlicerListWidget, parent=None) -> None:
        super().__init__(parent)
        self._target = target
        # A grid rather than a box: the same four widgets are re-placed into
        # one row or two by _relayout as the card is resized.
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 2)
        self._grid.setHorizontalSpacing(2)
        self._grid.setVerticalSpacing(2)
        self._wrapped: bool | None = None

        search = QLineEdit()
        search.setPlaceholderText("Search…")
        search.setClearButtonEnabled(True)
        search.setMinimumWidth(0)
        search.textChanged.connect(target.set_filter)
        self._search = search

        select_all = QToolButton()
        select_all.setText("All")
        select_all.setToolTip("Select every visible value")
        select_all.clicked.connect(target.select_all)
        self._select_all = select_all

        clear = QToolButton()
        clear.setText("None")
        clear.setToolTip("Clear the selection")
        clear.clicked.connect(target.clear_all)
        self._clear = clear

        count = QLabel("")
        count.setToolTip("Values ticked, of the total on this column")
        self._count = count

        self._relayout(wrapped=False)

        self.setStyleSheet(
            f"QLineEdit {{ background: {theme.NODE_BODY.name()};"
            f" color: {theme.NODE_TEXT.name()};"
            f" border: 1px solid {theme.NODE_BORDER.name()};"
            f" border-radius: 3px; padding: 1px 3px; font-size: 8pt; }}"
            f"QToolButton {{ font-size: 8pt; padding: 1px 4px; }}"
            f"QLabel {{ color: {theme.NODE_SUBTEXT.name()}; font-size: 8pt; }}")

        target.selection_committed.connect(lambda _v: self.refresh_summary())

    def _relayout(self, wrapped: bool) -> None:
        """Place the four widgets in one row (wide) or two (narrow)."""
        if wrapped == self._wrapped:
            return
        self._wrapped = wrapped
        for w in (self._search, self._select_all, self._clear, self._count):
            self._grid.removeWidget(w)
        if wrapped:
            self._grid.addWidget(self._search, 0, 0, 1, 3)
            self._grid.addWidget(self._select_all, 1, 0)
            self._grid.addWidget(self._clear, 1, 1)
            self._grid.addWidget(self._count, 1, 2)
        else:
            self._grid.addWidget(self._search, 0, 0)
            self._grid.addWidget(self._select_all, 0, 1)
            self._grid.addWidget(self._clear, 0, 2)
            self._grid.addWidget(self._count, 0, 3)
        self._grid.setColumnStretch(0, 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout(wrapped=event.size().width() < self.WRAP_BELOW)

    def set_mode(self, mode: str) -> None:
        """Select All is meaningless once only one value can be picked."""
        self._select_all.setVisible(mode != "single")

    def refresh_summary(self) -> None:
        """Re-read the "N/M" count off the target list — hosts call this
        after repopulating it (set_options/sync_checks don't themselves
        emit selection_committed)."""
        self._count.setText(self._target.selection_summary())
