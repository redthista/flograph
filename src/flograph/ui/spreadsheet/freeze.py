"""Freeze panes for a SpreadsheetView — Excel's, not Qt's example's.

Qt's frozen-column example lays a second view over the first column and
lets the grid scroll underneath it, so each column that scrolls left passes
*under* the frozen one and is hidden on its way. Excel does not do that:
the frozen part is simply not part of what scrolls. So here the frozen rows
and columns are hidden in the main grid, its viewport is pushed right and
down by their size, and up to three small panes show them. The room is
made by Qt itself: the grid's row-number header is widened by the frozen
columns' width and its column header heightened by the frozen rows', so
QTableView's own layout leaves the space and the panes cover the extra
header area. (Setting the viewport's margins directly fights QTableView,
which resets them on every layout.)

    ┌────┬───────────┬──────────────────────┐
    │    │ col pane  │  main header         │   col pane: the frozen
    ├────┼───────────┼──────────────────────┤   columns, scrolls with the
    │ corner pane    │  row pane            │   grid up and down
    ├────┼───────────┼──────────────────────┤   row pane: the frozen rows,
    │ main │ col pane│  main viewport       │   scrolls with it sideways
    │ rows │  (cont.)│  (scrolls both ways) │   corner: both frozen, plus
    └────┴───────────┴──────────────────────┘   the frozen rows' numbers

Every pane shares the grid's model and selection model, so a selection or
a current cell is one thing across all of them, and an edit in a frozen
cell is made in its pane (SpreadsheetView.edit routes it there — an editor
opened in the main grid would be behind the pane). Scrolling is per pixel
while anything is frozen, so the panes can follow the grid exactly.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QModelIndex, QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemDelegate, QAbstractItemView,
                               QFrame, QHeaderView, QTableView)

from .delegates import SheetDelegate

_EDGE = QColor("#6b7280")


class _Pane(QTableView):
    """One frozen pane: shows part of the grid, owns no state of its own."""

    def __init__(self, main, kind: str) -> None:
        super().__init__(main)
        self._main = main
        self.kind = kind
        self.setObjectName(f"frozen_{kind}")
        self.setModel(main.model())
        self.setSelectionModel(main.selectionModel())
        delegate = SheetDelegate(self)
        delegate.show_formulas = main.show_formulas
        self.setItemDelegate(delegate)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setSelectionMode(main.selectionMode())
        self.setSelectionBehavior(main.selectionBehavior())
        self.setEditTriggers(main.editTriggers())
        self.setShowGrid(main.showGrid())
        self.setStyleSheet(main.styleSheet())
        self.verticalHeader().setDefaultSectionSize(
            main.verticalHeader().defaultSectionSize())
        self.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.horizontalHeader().setHighlightSections(True)
        if kind == "cols":
            # the frozen columns' own header, ▾ buttons and all
            from .view import _sheet_header_class
            header = _sheet_header_class()(main)
            header.setParent(self)
            header.setSectionsClickable(True)
            header.setHighlightSections(True)
            self.setHorizontalHeader(header)
            header.menu_button_clicked.connect(main.open_column_filter)
            header.sectionResized.connect(self._column_resized)
            self.verticalHeader().hide()
        elif kind == "rows":
            self.horizontalHeader().hide()
            self.verticalHeader().hide()
        else:   # corner: the frozen rows' numbers live here
            self.horizontalHeader().hide()
            self.verticalHeader().setSectionsClickable(True)
            self.verticalHeader().setHighlightSections(True)
        self.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.horizontalHeader().customContextMenuRequested.connect(
            self._column_menu)
        self.horizontalHeader().sectionClicked.connect(
            lambda col: main.select_columns([col]))
        self.verticalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.verticalHeader().customContextMenuRequested.connect(
            self._row_menu)
        self.verticalHeader().sectionClicked.connect(
            lambda row: main.select_rows([row]))

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            self._main.painter_landed()     # the Format Painter's brush

    # The pane never takes the keyboard: the grid keeps it, and routes an
    # edit of a frozen cell back here.
    def mousePressEvent(self, event) -> None:
        self._main.setFocus()
        index = self.indexAt(event.position().toPoint())
        model = self._main.sheet_model()
        if (event.button() == Qt.LeftButton and index.isValid()
                and index == self.currentIndex() and model is not None
                and model.column_choices(index.column())[0]):
            from .delegates import caret_rect
            if caret_rect(self.visualRect(index)).contains(
                    event.position().toPoint()):
                event.accept()
                self._main.open_cell_dropdown()
                return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        self._main.keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        self._main.wheelEvent(event)

    def closeEditor(self, editor, hint) -> None:
        if hint == QAbstractItemDelegate.SubmitModelCache:
            super().closeEditor(editor, QAbstractItemDelegate.NoHint)
            self._main.setFocus()
            self._main._step_current(1, 0)
            return
        super().closeEditor(editor, hint)
        self._main.setFocus()

    def _column_resized(self, col: int, _old: int, new: int) -> None:
        if new > 0 and not getattr(self._main, "_applying_widths", False):
            model = self._main.sheet_model()
            if model is not None:
                model.set_column_widths({col: new})

    # menus: the grid's own, opened here
    def _guarded(self) -> bool:
        from .. import menu_guard
        return not menu_guard.settling()

    def _column_menu(self, pos) -> None:
        col = self.horizontalHeader().logicalIndexAt(pos)
        if col < 0 or not self._guarded():
            return
        if (col not in self._main.selected_columns()
                or not self._main.whole_columns_selected()):
            self._main.select_columns([col])
        from .menus import column_menu
        column_menu(self._main, self.horizontalHeader(), pos)

    def _row_menu(self, pos) -> None:
        row = self.verticalHeader().logicalIndexAt(pos)
        if row < 0 or not self._guarded():
            return
        if (row not in self._main.selected_rows()
                or not self._main.whole_rows_selected()):
            self._main.select_rows([row])
        from .menus import row_menu
        row_menu(self._main, self.verticalHeader(), pos)

    def contextMenuEvent(self, event) -> None:
        # see SpreadsheetView.contextMenuEvent for why not the signal
        event.accept()
        self._cell_menu(event.pos())

    def _cell_menu(self, pos) -> None:
        if not self._guarded():
            return
        index = self.indexAt(pos)
        if index.isValid() and not self.selectionModel().isSelected(index):
            self._main.setCurrentIndex(index)
        from .menus import cell_menu
        cell_menu(self._main, self.viewport(), pos)


class FrozenPanes:
    """The panes of one grid, and the arithmetic that lines them up."""

    def __init__(self, main) -> None:
        self._main = main
        self.rows = 0
        self.cols = 0
        self._panes: dict[str, _Pane] = {}
        self._edges = (QFrame(main), QFrame(main))
        for edge in self._edges:
            edge.setStyleSheet(f"background: {_EDGE.name()};")
            edge.hide()
        self._laying_out = False
        self._base: Optional[tuple] = None   # header sizes before freezing
        main.verticalScrollBar().valueChanged.connect(self._follow_v)
        main.horizontalScrollBar().valueChanged.connect(self._follow_h)
        main.horizontalHeader().sectionResized.connect(self._main_resized)

    # ------------------------------------------------------------- state

    @property
    def active(self) -> bool:
        return bool(self.rows or self.cols)

    def set_counts(self, rows: int, cols: int) -> None:
        main = self._main
        model = main.sheet_model()
        if model is None:
            return
        rows = max(0, min(rows, model.rowCount() - 1))
        cols = max(0, min(cols, model.columnCount() - 1))
        widths = self._column_widths(model)
        was_active = self.active
        self.rows, self.cols = rows, cols
        if self.active and not was_active:
            self._remember_headers()
        mode = (QAbstractItemView.ScrollPerPixel if self.active
                else QAbstractItemView.ScrollPerItem)
        main.setHorizontalScrollMode(mode)
        main.setVerticalScrollMode(mode)
        wanted = set()
        if cols:
            wanted.add("cols")
        if rows:
            wanted.add("rows")
            wanted.add("corner")
        for kind in ("cols", "rows", "corner"):
            if kind in wanted and kind not in self._panes:
                self._panes[kind] = _Pane(main, kind)
                fill = getattr(main, "_fill", None)
                if fill is not None:
                    # the fill handle can be on a frozen cell
                    fill.watch(self._panes[kind].viewport())
            elif kind not in wanted and kind in self._panes:
                pane = self._panes.pop(kind)
                pane.hide()
                pane.deleteLater()
        for pane in self._panes.values():
            if pane.model() is not model:
                pane.setModel(model)
                pane.setSelectionModel(main.selectionModel())
            for col in range(model.columnCount()):
                pane.setColumnWidth(col, widths[col])
        self.sync_rows(widths)
        if not self.active and was_active:
            self._restore_headers()

    def _remember_headers(self) -> None:
        main = self._main
        vh, hh = main.verticalHeader(), main.horizontalHeader()
        self._base = (vh.minimumWidth(), vh.maximumWidth(),
                      max(vh.width(), vh.sizeHint().width(), vh.minimumWidth()),
                      hh.minimumHeight(), hh.maximumHeight(),
                      max(hh.sizeHint().height(), hh.minimumHeight()),
                      vh.defaultAlignment(), hh.defaultAlignment())

    def _restore_headers(self) -> None:
        if self._base is None:
            return
        main = self._main
        vh, hh = main.verticalHeader(), main.horizontalHeader()
        (vmin, vmax, _vw, hmin, hmax, _hh, valign, halign) = self._base
        vh.setMinimumWidth(vmin)
        vh.setMaximumWidth(vmax)
        hh.setMinimumHeight(hmin)
        hh.setMaximumHeight(hmax)
        vh.setDefaultAlignment(valign)
        hh.setDefaultAlignment(halign)
        hh.band_height = None
        for edge in self._edges:
            edge.hide()
        self._base = None
        main.updateGeometries()

    @property
    def base_sizes(self) -> tuple[int, int]:
        """The row-number header's width and the column header's height as
        they were before freezing — where the panes line up."""
        if self._base is None:
            main = self._main
            return (main.verticalHeader().width(),
                    main.horizontalHeader().height())
        return self._base[2], self._base[5]

    def _column_widths(self, model) -> list[int]:
        """Every column's width as the user sees it: a frozen column is
        hidden in the grid (width 0 there), so its width comes from the pane
        showing it, or the width stored with the sheet."""
        main = self._main
        header = main.horizontalHeader()
        out = []
        for col in range(model.columnCount()):
            width = header.sectionSize(col) if not header.isSectionHidden(
                col) else 0
            if not width:
                pane = self._panes.get("cols") or self._panes.get("corner")
                if pane is not None and col < pane.model().columnCount():
                    width = pane.columnWidth(col)
            if not width:
                spec = model.sheet.columns[col]
                width = spec.width or header.defaultSectionSize()
            out.append(width)
        return out

    def sync_rows(self, widths=None) -> None:
        """Re-apply which rows and columns each view shows: the grid hides
        the frozen ones (they are in the panes), every view hides the rows
        the filter hides."""
        main = self._main
        model = main.sheet_model()
        if model is None:
            return
        if widths is None:
            widths = self._column_widths(model)
        n_rows, n_cols = model.rowCount(), model.columnCount()
        for row in range(n_rows):
            filtered = main.row_filtered(row)
            main.setRowHidden(row, filtered or row < self.rows)
            for kind, pane in self._panes.items():
                frozen_row = row < self.rows
                show = not filtered and (frozen_row if kind in
                                         ("rows", "corner") else True)
                pane.setRowHidden(row, not show)
        header = main.horizontalHeader()
        for col in range(n_cols):
            frozen_col = col < self.cols
            if frozen_col != header.isSectionHidden(col):
                main.setColumnHidden(col, frozen_col)
                if not frozen_col:
                    main.setColumnWidth(col, widths[col])
            for kind, pane in self._panes.items():
                show = frozen_col if kind in ("cols", "corner") else \
                    not frozen_col
                pane.setColumnHidden(col, not show)
        self.relayout()

    # ------------------------------------------------------------ layout

    def relayout(self) -> None:
        if self._laying_out:
            return
        self._laying_out = True
        try:
            self._relayout()
        finally:
            self._laying_out = False

    def _frozen_size(self) -> tuple[int, int]:
        pane = self._panes.get("cols") or self._panes.get("corner")
        width = (sum(pane.columnWidth(c) for c in range(self.cols)
                     if not pane.isColumnHidden(c)) if pane else 0)
        pane_r = self._panes.get("rows") or self._panes.get("corner")
        height = (sum(pane_r.rowHeight(r) for r in range(self.rows)
                      if not pane_r.isRowHidden(r)) if pane_r else 0)
        return width, height

    def _relayout(self) -> None:
        main = self._main
        if not self.active:
            return
        f = main.frameWidth()
        vh0, hh0 = self.base_sizes
        colw, rowh = self._frozen_size()
        vh, hh = main.verticalHeader(), main.horizontalHeader()
        if main.verticalHeader().isVisible():
            vh.setFixedWidth(vh0 + colw)
            # the numbers stay in the strip the pane leaves uncovered
            vh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        else:
            vh0 = 0
        hh.setFixedHeight(hh0 + rowh)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignTop)
        hh.band_height = hh0
        vg = main.viewport().geometry()

        cols = self._panes.get("cols")
        if cols is not None:
            cols.horizontalHeader().setFixedHeight(hh0)
            cols.horizontalHeader().band_height = hh0
            cols.setGeometry(f + vh0, f, colw, hh0 + rowh + vg.height())
            cols.show()
            cols.raise_()
        rows = self._panes.get("rows")
        if rows is not None:
            rows.setGeometry(vg.left(), f + hh0, vg.width(), rowh)
            rows.show()
            rows.raise_()
        corner = self._panes.get("corner")
        if corner is not None:
            corner.verticalHeader().setFixedWidth(max(vh0, 1))
            corner.verticalHeader().setVisible(vh0 > 0)
            corner.setGeometry(f, f + hh0, vh0 + colw, rowh)
            corner.show()
            corner.raise_()
        v_edge, h_edge = self._edges
        if self.cols:
            v_edge.setGeometry(f + vh0 + colw - 1, f, 1,
                               hh0 + rowh + vg.height())
            v_edge.show()
            v_edge.raise_()
        else:
            v_edge.hide()
        if self.rows:
            h_edge.setGeometry(f, f + hh0 + rowh - 1,
                               vh0 + colw + vg.width(), 1)
            h_edge.show()
            h_edge.raise_()
        else:
            h_edge.hide()
        self._follow_v(main.verticalScrollBar().value())
        self._follow_h(main.horizontalScrollBar().value())
        fill = getattr(main, "_fill", None)
        if fill is not None:
            fill.refresh()           # the outline draws over the panes

    def _follow_v(self, value: int) -> None:
        pane = self._panes.get("cols")
        if pane is not None:
            # the pane still has the frozen rows (under the corner), so its
            # unfrozen rows begin `rowh` lower: same pixel offset lines up
            pane.verticalScrollBar().setRange(
                0, max(value, pane.verticalScrollBar().maximum()))
            pane.verticalScrollBar().setValue(value)
        fill = getattr(self._main, "_fill", None)
        if fill is not None:
            fill.refresh()

    def _follow_h(self, value: int) -> None:
        pane = self._panes.get("rows")
        if pane is not None:
            pane.horizontalScrollBar().setRange(
                0, max(value, pane.horizontalScrollBar().maximum()))
            pane.horizontalScrollBar().setValue(value)

    def _main_resized(self, col: int, _old: int, new: int) -> None:
        if new <= 0:
            return
        for pane in self._panes.values():
            if pane.columnWidth(col) != new:
                pane.setColumnWidth(col, new)

    # ------------------------------------------------------------ queries

    def is_frozen(self, index) -> bool:
        return index.isValid() and (index.row() < self.rows
                                    or index.column() < self.cols)

    def pane_for(self, index) -> Optional[_Pane]:
        """The pane showing `index`, or None when the grid itself does."""
        if not self.is_frozen(index):
            return None
        if index.row() < self.rows:
            kind = "corner" if index.column() < self.cols else "rows"
        else:
            kind = "cols"
        return self._panes.get(kind)

    def scroll_target(self, index) -> Optional[QModelIndex]:
        """What the grid should scroll to so `index` is in view: frozen
        cells are always in view along their frozen direction, so only the
        other direction counts. None when nothing needs scrolling."""
        if not self.is_frozen(index):
            return index
        model = self._main.sheet_model()
        row_frozen = index.row() < self.rows
        col_frozen = index.column() < self.cols
        if row_frozen and col_frozen:
            return None
        if row_frozen:
            first = next((r for r in range(self.rows, model.rowCount())
                          if not self._main.row_filtered(r)), None)
            return None if first is None else model.index(first,
                                                          index.column())
        first_col = self.cols if self.cols < model.columnCount() else None
        return None if first_col is None else model.index(index.row(),
                                                          first_col)

    def header_for(self, col: int) -> Optional[QHeaderView]:
        if col < self.cols and "cols" in self._panes:
            return self._panes["cols"].horizontalHeader()
        return None

    def column_width(self, col: int) -> int:
        pane = self._panes.get("cols")
        return pane.columnWidth(col) if pane is not None else 0

    def fit_column(self, col: int) -> int:
        pane = self._panes.get("cols")
        if pane is None:
            return 0
        pane.resizeColumnToContents(col)
        return pane.columnWidth(col)

    def repaint_panes(self) -> None:
        for pane in self._panes.values():
            delegate = pane.itemDelegate()
            delegate.show_formulas = self._main.show_formulas
            pane.viewport().update()

    def panes(self) -> dict:
        return dict(self._panes)
