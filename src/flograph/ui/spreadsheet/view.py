"""SpreadsheetView: Excel-style grid interaction, shared by the canvas
card, the pop-out editor and a dashboard tile.

Mouse first: click a column header or row number to select it, drag across
headers to select several, right-click anything for the commands that apply
there, and use a column's ▾ button to sort or filter it. Every command is
one QAction in ``actions.SheetActions`` — the ribbon, the right-click menus
and the keyboard all trigger the same objects, so a command reads, behaves
and is explained the same wherever it is found.

Keyboard (Excel's keys): Enter commits and moves down, Tab moves right,
typing replaces, F2 edits in place, Delete clears, Ctrl+D / Ctrl+R fill
down / right, Ctrl+C/X/V work on rectangular selections (TSV + HTML + an
internal format that keeps formulas and shifts their relative references on
paste), Ctrl+Shift+V pastes values only, Shift+Space / Ctrl+Space select
rows / columns, Ctrl++ / Ctrl+- insert / delete them, Alt+Shift+arrows move
them, Ctrl+arrows jump to the edge of the data, Ctrl+F / Ctrl+H find and
replace, Ctrl+Shift+L filters, Alt+Down opens a cell's dropdown list, F9
submits held edits.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (QEvent, QItemSelection, QItemSelectionModel,
                            QMimeData, QPoint, QRect, QSettings, Qt, QTimer,
                            Signal)
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemDelegate, QAbstractItemView,
                               QApplication, QTableView,
                               QToolTip)

from flograph.core.sheet import COLUMN_TYPES, set_extra_date_formats, translate

from .clipboard import (MIME_CELLS, block_to_html, block_to_tsv, decode_cells,
                        encode_cells, parse_paste_text)
from .delegates import CellEdit, SheetDelegate
from .model import SheetModel

_ORG = "flograph"
_APP = "flograph"
AUTOSIZE_SETTING = "table_node/autosize_columns"
DATE_FORMATS_SETTING = "table_node/date_formats"

# How long after the last change the automatic column fit runs. Short enough
# to feel immediate when you stop typing, long enough that a burst of edits
# (a paste, holding a key, fill-down) pays for one fit rather than one each.
AUTOFIT_IDLE_MS = 120


def autosize_default_enabled() -> bool:
    """Settings > Table Node: fit columns to content automatically."""
    return QSettings(_ORG, _APP).value(AUTOSIZE_SETTING, True, bool)


def set_autosize_default(enabled: bool) -> None:
    QSettings(_ORG, _APP).setValue(AUTOSIZE_SETTING, bool(enabled))


def date_formats_setting() -> str:
    """Settings > Table Node: extra strptime date formats, comma-separated."""
    return str(QSettings(_ORG, _APP).value(DATE_FORMATS_SETTING, "") or "")


def set_date_formats_setting(text: str) -> None:
    QSettings(_ORG, _APP).setValue(DATE_FORMATS_SETTING, str(text))
    _apply_date_formats(text)


def _apply_date_formats(text: str) -> None:
    set_extra_date_formats(
        part.strip() for part in str(text).replace("\n", ",").split(","))


# custom formats saved in a previous session take effect as soon as any
# spreadsheet UI loads (the engine's date columns parse via pandas anyway)
_apply_date_formats(date_formats_setting())


def paint_hidden_mark(painter, rect, before: bool, after: bool,
                      vertical: bool) -> None:
    """Excel's mark where rows or columns are hidden: a short blue double
    bar on the header edge they sit behind (double-click it to unhide)."""
    painter.save()
    painter.setPen(QPen(QColor("#60a5fa"), 1))
    if vertical:          # a row header: bars along the top/bottom edge
        x0, x1 = rect.left() + 4, rect.right() - 4
        if before:
            painter.drawLine(x0, rect.top(), x1, rect.top())
            painter.drawLine(x0, rect.top() + 2, x1, rect.top() + 2)
        if after:
            painter.drawLine(x0, rect.bottom(), x1, rect.bottom())
            painter.drawLine(x0, rect.bottom() - 2, x1, rect.bottom() - 2)
    else:                 # a column header: bars down the left/right edge
        y0, y1 = rect.top() + 4, rect.bottom() - 4
        if before:
            painter.drawLine(rect.left(), y0, rect.left(), y1)
            painter.drawLine(rect.left() + 2, y0, rect.left() + 2, y1)
        if after:
            painter.drawLine(rect.right(), y0, rect.right(), y1)
            painter.drawLine(rect.right() - 2, y0, rect.right() - 2, y1)
    painter.restore()


def _sheet_header_class():
    """SheetHeader, built on first use: data_table is the older module and
    must not depend on this package loading."""
    global _SheetHeader
    if _SheetHeader is not None:
        return _SheetHeader
    from ..data_table import TooltipHeader

    class SheetHeader(TooltipHeader):
        """The column header, with a ▾ button on every column — Excel's
        filter button, always there, so sorting and filtering a column is
        one click on the column itself. The button lights blue while the
        column is filtered. A click anywhere else on a header selects the
        column, as a spreadsheet's does."""

        menu_button_clicked = Signal(int)
        BUTTON_W = 15
        # The height of the band holding the names. Taller than that while
        # rows are frozen — the panes cover the rest (see freeze.py).
        band_height = None

        def __init__(self, view) -> None:
            super().__init__(Qt.Horizontal, view)
            self._view = view
            self._hover = -1
            self.setMouseTracking(True)
            # Excel's table headers: the name at the left, the ▾ at the right
            self.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        def button_rect(self, section: int) -> QRect:
            x = self.sectionViewportPosition(section)
            w = self.sectionSize(section)
            bw = min(self.BUTTON_W, max(w - 4, 0))
            band = self.band_height or self.height()
            return QRect(x + w - bw - 2, 3, bw, band - 6)

        def _button_at(self, pos) -> int:
            if not getattr(self._view, "show_column_buttons", True):
                return -1
            section = self.logicalIndexAt(pos)
            if section >= 0 and self.button_rect(section).contains(pos):
                return section
            return -1

        def paintSection(self, painter, rect, section) -> None:
            super().paintSection(painter, rect, section)
            hidden = getattr(self._view, "column_user_hidden", None)
            if hidden is not None:
                count = self.count()
                before = section > 0 and hidden(section - 1)
                after = (section + 1 < count and hidden(section + 1)
                         and all(hidden(c) for c in range(section + 1,
                                                          count)))
                if before or after:
                    paint_hidden_mark(painter, rect, before, after,
                                      vertical=False)
            if not getattr(self._view, "show_column_buttons", True):
                return
            button = self.button_rect(section)
            if button.width() < 8:
                return
            painter.save()
            # a name long enough to reach the button stops short of it,
            # rather than running underneath
            from .. import theme
            under = button.adjusted(-3, -1, 0, 1).intersected(
                rect.adjusted(1, 1, -1, -1))
            painter.fillRect(under, theme.NODE_HEADER)
            painter.setRenderHint(QPainter.Antialiasing, True)
            filtered = self._view.is_column_filtered(section)
            if filtered or self._hover == section:
                fill = QColor("#60a5fa") if filtered else QColor("#4b4f5c")
                fill.setAlpha(90 if filtered else 160)
                painter.setPen(Qt.NoPen)
                painter.setBrush(fill)
                painter.drawRoundedRect(button, 3, 3)
            pen = QPen(QColor("#93c5fd") if filtered else QColor("#9ca3af"),
                       1.4)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            cx, cy = button.center().x(), button.center().y()
            if filtered:   # a small funnel: this column is filtered
                painter.drawLine(QPoint(cx - 4, cy - 3), QPoint(cx + 4, cy - 3))
                painter.drawLine(QPoint(cx - 4, cy - 3), QPoint(cx - 1, cy + 1))
                painter.drawLine(QPoint(cx + 4, cy - 3), QPoint(cx + 1, cy + 1))
                painter.drawLine(QPoint(cx, cy + 1), QPoint(cx, cy + 4))
            else:
                painter.drawLine(QPoint(cx - 3, cy - 1), QPoint(cx, cy + 2))
                painter.drawLine(QPoint(cx, cy + 2), QPoint(cx + 3, cy - 1))
            painter.restore()

        def sectionSizeFromContents(self, section):
            size = super().sectionSizeFromContents(section)
            if getattr(self._view, "show_column_buttons", True):
                size.setWidth(size.width() + self.BUTTON_W + 2)
            return size

        def mousePressEvent(self, event) -> None:
            if event.button() == Qt.LeftButton:
                section = self._button_at(event.position().toPoint())
                if section >= 0:
                    event.accept()
                    self.menu_button_clicked.emit(section)
                    return
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event) -> None:
            hover = self._button_at(event.position().toPoint())
            if hover != self._hover:
                self._hover = hover
                self.viewport().update()
            super().mouseMoveEvent(event)

        def leaveEvent(self, event) -> None:
            if self._hover != -1:
                self._hover = -1
                self.viewport().update()
            super().leaveEvent(event)

        def viewportEvent(self, event) -> bool:
            if (event.type() == QEvent.ToolTip
                    and self._button_at(event.pos()) >= 0):
                from ..data_table import show_tooltip
                show_tooltip(event.globalPos(),
                             "Sort and filter this column", self)
                return True
            return super().viewportEvent(event)

    _SheetHeader = SheetHeader
    return SheetHeader


_SheetHeader = None


class SpreadsheetView(QTableView):
    # the filter changed — overlays and the ribbon redraw
    filter_changed = Signal()

    # Class-level defaults: Qt calls back into overrides (updateGeometries,
    # resizeEvent) while the constructor is still installing the header,
    # before __init__ has set these.
    _frozen = None
    _actions = None
    _host = None
    _show_formulas = False
    _filters: dict = {}
    _filtered_rows: frozenset = frozenset()
    _folded_rows: frozenset = frozenset()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Replaced before anything attaches to it, and set up the way
        # QTableView sets up its own. On a Table card or tile its tooltips
        # then land by the pointer rather than at the top of the page
        # (AA3) — see data_table.tooltip_host.
        self.show_column_buttons = True
        self._filters: dict[int, set] = {}
        self._filtered_rows: set[int] = set()
        header = _sheet_header_class()(self)
        header.setSectionsClickable(True)
        header.setHighlightSections(True)
        self.setHorizontalHeader(header)
        header.menu_button_clicked.connect(self.open_column_filter)
        from .outline_header import OutlineHeader
        self.setVerticalHeader(OutlineHeader(self))
        self.verticalHeader().setSectionsClickable(True)
        self.verticalHeader().setHighlightSections(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setEditTriggers(QAbstractItemView.DoubleClicked
                             | QAbstractItemView.EditKeyPressed
                             | QAbstractItemView.AnyKeyPressed)
        self.setItemDelegate(SheetDelegate(self))
        self.setTabKeyNavigation(True)
        self.horizontalHeader().setDefaultSectionSize(72)
        self.verticalHeader().setDefaultSectionSize(22)

        header = self.horizontalHeader()
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self._column_menu)
        header.sectionDoubleClicked.connect(self.rename_column)
        # double-click a column border: Qt fits that column; when it's part
        # of a multi-column selection, fit the whole selection
        header.sectionHandleDoubleClicked.connect(self._autosize_from_handle)
        # (the row header's handle: unhide rows hidden just below)

        # A header click selects the column, as in a spreadsheet — the
        # column is then what Delete, Move and Insert act on. Sorting lives
        # on the column's ▾ button, the ribbon and the right-click menu.
        # (Read-only tables elsewhere still sort on a header click; there
        # is nothing to select a column *for* in those.)
        self._presort_rows: Optional[list[list[str]]] = None
        # the Sort dialog's last levels, by column name, for next time
        self.sort_levels_used: list[tuple[str, bool, bool]] = []
        self._sorting = False

        self._actions = None
        self._host = None
        self._show_formulas = False
        self._frozen = None   # freeze.FrozenPanes, made on first freeze

        rows = self.verticalHeader()
        rows.sectionHandleDoubleClicked.connect(
            self._row_handle_double_clicked)
        rows.setContextMenuPolicy(Qt.CustomContextMenu)
        rows.customContextMenuRequested.connect(self._row_menu)

        # column widths persist into the sheet; a drag emits sectionResized
        # per pixel, so pending widths debounce into one commit
        self._applying_widths = False
        self._pending_widths: dict[int, int] = {}
        # See set_defer_autosize: a canvas card puts off fitting its columns
        # until something actually paints it.
        self._defer_autosize = False
        self._autosize_pending = False
        self._width_commit_timer = QTimer(self)
        self._width_commit_timer.setSingleShot(True)
        self._width_commit_timer.setInterval(300)
        self._width_commit_timer.timeout.connect(self._persist_pending_widths)
        header.sectionResized.connect(self._on_section_resized)
        # row heights: a drag persists like a width; wrapped rows re-fit
        # when the columns they wrap in change width
        self._applying_heights = False
        self._pending_heights: dict[int, int] = {}
        self._sized_rows: set = set()
        self._height_commit_timer = QTimer(self)
        self._height_commit_timer.setSingleShot(True)
        self._height_commit_timer.setInterval(300)
        self._height_commit_timer.timeout.connect(
            self._persist_pending_heights)
        self.verticalHeader().sectionResized.connect(self._on_row_resized)
        self._refit_timer = QTimer(self)
        self._refit_timer.setSingleShot(True)
        self._refit_timer.setInterval(60)
        self._refit_timer.timeout.connect(self.apply_row_heights)
        header.sectionResized.connect(
            lambda *_a: self._refit_timer.start()
            if self.sheet_model() is not None
            and self.sheet_model().wrapped_rows() else None)

        # See _maybe_autofit: the automatic fit coalesces instead of running
        # once per edited cell.
        self._autofit_timer = QTimer(self)
        self._autofit_timer.setSingleShot(True)
        self._autofit_timer.setInterval(AUTOFIT_IDLE_MS)
        self._autofit_timer.timeout.connect(self._run_autofit)

        # the fill handle, and dragging rows/columns by their headers
        from .drag import FillHandle, HeaderMove
        self._fill = FillHandle(self)
        self._row_move = HeaderMove(self, self.verticalHeader(), "row")
        self._col_move = HeaderMove(self, self.horizontalHeader(), "col")
        for bar in (self.verticalScrollBar(), self.horizontalScrollBar()):
            bar.valueChanged.connect(self._fill.refresh)
        header.sectionResized.connect(self._fill.refresh)
        self.verticalHeader().sectionResized.connect(self._fill.refresh)

    def setModel(self, model) -> None:
        old = self.sheet_model()
        if old is not None:
            old.modelReset.disconnect(self._sync_column_widths)
            old.dataChanged.disconnect(self._maybe_autofit)
            old.modelReset.disconnect(self._forget_sort)
            old.sheet_edited.disconnect(self._forget_sort)
        if old is not None:
            old.modelAboutToBeReset.disconnect(self._before_reset)
            old.modelReset.disconnect(self._after_reset)
            old.outline_changed.disconnect(self._apply_outline)
            old.dataChanged.disconnect(self._apply_outline)
            old.dataChanged.disconnect(self._apply_hidden)
            old.dataChanged.disconnect(self._refit_soon)
            old.row_heights_changed.disconnect(self.apply_row_heights)
            old.dataChanged.disconnect(self._reapply_filter)
            old.freeze_changed.disconnect(self._apply_freeze)
            old.edit_refused.disconnect(self._edit_refused)
        super().setModel(model)
        self._filters = {}
        self._filtered_rows = set()
        self._forget_sort()
        if isinstance(model, SheetModel):
            model.modelReset.connect(self._sync_column_widths)
            model.dataChanged.connect(self._maybe_autofit)
            model.modelReset.connect(self._forget_sort)
            model.sheet_edited.connect(self._forget_sort)
            model.modelAboutToBeReset.connect(self._before_reset)
            model.modelReset.connect(self._after_reset)
            model.outline_changed.connect(self._apply_outline)
            model.dataChanged.connect(self._apply_outline)
            model.dataChanged.connect(self._apply_hidden)
            model.dataChanged.connect(self._refit_soon)
            model.row_heights_changed.connect(self.apply_row_heights)
            model.dataChanged.connect(self._reapply_filter)
            model.freeze_changed.connect(self._apply_freeze)
            model.edit_refused.connect(self._edit_refused)
            self._sync_column_widths()
            self._folded_rows = frozenset()
            self._apply_outline()
            self._apply_freeze()
            self._shown_hidden_rows = frozenset()
            self._apply_hidden()
            self._sized_rows = set()
            self.apply_row_heights()
        if isinstance(model, SheetModel) and getattr(self, "_fill", None):
            model.dataChanged.connect(self._fill.refresh)
            model.modelReset.connect(self._fill.refresh)
        if self.selectionModel() is not None:
            self.selectionModel().selectionChanged.connect(
                self._selection_moved)
            self.selectionModel().currentChanged.connect(
                self._selection_moved)
            self.selectionModel().currentChanged.connect(self._show_hint)

    def sheet_model(self) -> Optional[SheetModel]:
        model = self.model()
        return model if isinstance(model, SheetModel) else None

    # ------------------------------------------------------- header sort

    def _header_sort(self, col: int, mode: str, levels=None) -> None:
        """A header click resolved to a sort. asc/desc reorder the rows
        (one undo step each), "levels" sorts by several columns at once;
        clear restores the order captured before the first sort of this
        run."""
        model = self.sheet_model()
        if model is None or model.read_only:
            return
        self._sorting = True
        try:
            if mode == "clear":
                if self._presort_rows is not None:
                    model.restore_order(self._presort_rows)
                self._presort_rows = None
            else:
                if self._presort_rows is None:
                    self._presort_rows = [list(r) for r in model.sheet.rows]
                if mode == "levels":
                    model.sort_levels(levels)
                else:
                    model.sort_by(col, mode == "asc")
        finally:
            self._sorting = False

    def sort_with_levels(self, levels) -> None:
        """Sort by several columns: ``[(col, ascending, by_list), ...]``,
        the most important first."""
        if levels:
            self._header_sort(0, "levels", levels)

    def custom_sort(self) -> None:
        """Data ▸ Custom Sort…: the Sort dialog."""
        from .sort_dialog import custom_sort
        custom_sort(self)

    def _forget_sort(self, *_) -> None:
        """Drop the saved pre-sort order and the header indicator — any
        change to the rows we did not make ourselves invalidates it."""
        if self._sorting:
            return
        self._presort_rows = None

    def clear_sort(self) -> None:
        """Menu entry point: restore the pre-sort row order."""
        self._header_sort(0, "clear")

    def sort_column(self, col: int, ascending: bool) -> None:
        self._header_sort(col, "asc" if ascending else "desc")

    def sort_current(self, ascending: bool) -> None:
        cols = self.target_columns()
        if cols:
            self.sort_column(cols[0], ascending)

    @property
    def has_active_sort(self) -> bool:
        return self._presort_rows is not None

    def dataChanged(self, top_left, bottom_right, roles=()) -> None:
        """Refresh the changed cells, but leave the one being typed into
        alone.

        QTableView answers a change by re-reading the model into whatever
        editor is open over it. That is right for a change the user just
        made and wrong for one arriving from elsewhere — a linked run
        landing, an undo — which would swap half-typed text out from under
        them. The edited cell is hidden behind its editor and needs no
        repaint, so hand Qt the changed area with that one cell cut out of
        it: up to four rectangles, none of them containing the editor.
        """
        model = self.model()
        current = self.currentIndex()
        editing = (current
                   if (model is not None and current.isValid()
                       and self.state() == QAbstractItemView.EditingState
                       and top_left.row() <= current.row() <= bottom_right.row()
                       and top_left.column() <= current.column()
                       <= bottom_right.column())
                   else None)
        if editing is None:
            super().dataChanged(top_left, bottom_right, roles)
            return
        row, col = editing.row(), editing.column()
        top, left = top_left.row(), top_left.column()
        bottom, right = bottom_right.row(), bottom_right.column()
        for r0, c0, r1, c1 in ((top, left, row - 1, right),
                               (row + 1, left, bottom, right),
                               (row, left, row, col - 1),
                               (row, col + 1, row, right)):
            if r0 <= r1 and c0 <= c1:
                super().dataChanged(model.index(r0, c0),
                                    model.index(r1, c1), roles)

    # ---------------------------------------------------------- selection

    def _selection_rect(self) -> Optional[tuple[int, int, int, int]]:
        """Bounding (row0, col0, row1, col1) of the selection (or current
        cell). Gaps in a ctrl-click selection are included, like Excel."""
        selection = self.selectionModel()
        indexes = selection.selectedIndexes() if selection else []
        if not indexes:
            current = self.currentIndex()
            if not current.isValid():
                return None
            indexes = [current]
        rows = [index.row() for index in indexes]
        cols = [index.column() for index in indexes]
        return min(rows), min(cols), max(rows), max(cols)

    def _step_current(self, drow: int, dcol: int) -> None:
        model = self.model()
        if model is None:
            return
        current = self.currentIndex()
        row = (current.row() if current.isValid() else 0) + drow
        col = (current.column() if current.isValid() else 0) + dcol
        row = max(0, min(row, model.rowCount() - 1))
        col = max(0, min(col, model.columnCount() - 1))
        index = model.index(row, col)
        self.setCurrentIndex(index)
        if self.selectionModel() is not None:
            self.selectionModel().select(
                index, QItemSelectionModel.ClearAndSelect)

    # ---------------------------------------------------------- clipboard

    def copy_selection(self) -> None:
        model = self.sheet_model()
        rect = self._selection_rect()
        if model is None or rect is None:
            return
        row0, col0, row1, col1 = rect
        values = [[model.value_text(r, c) for c in range(col0, col1 + 1)]
                  for r in range(row0, row1 + 1)]
        sources = [[model.cell_source(r, c) for c in range(col0, col1 + 1)]
                   for r in range(row0, row1 + 1)]
        styles = [[model.cell_format(r, c) or None
                   for c in range(col0, col1 + 1)]
                  for r in range(row0, row1 + 1)]
        mime = QMimeData()
        mime.setText(block_to_tsv(values))
        mime.setHtml(block_to_html(values))
        mime.setData(MIME_CELLS, encode_cells((row0, col0), sources, styles))
        QApplication.clipboard().setMimeData(mime)

    def copy_selection_with_headers(self) -> None:
        """Like copy_selection, but with a column-header row on top — for
        pasting into a spreadsheet outside the app. With nothing selected,
        copies the whole table rather than a lone current cell, so the
        button works as a get-everything action without a Ctrl+A first. No
        internal cell format goes on the clipboard, unlike copy_selection: a
        header row would throw off paste_clipboard's relative-reference
        shifting, and this action isn't meant for repasting into the grid
        anyway."""
        model = self.sheet_model()
        if model is None or model.rowCount() == 0 or model.columnCount() == 0:
            return
        selection = self.selectionModel()
        rect = (self._selection_rect()
                if selection is not None and selection.hasSelection() else None)
        row0, col0, row1, col1 = rect or (
            0, 0, model.rowCount() - 1, model.columnCount() - 1)
        headers = [model.headerData(c, Qt.Horizontal, Qt.DisplayRole)
                  for c in range(col0, col1 + 1)]
        values = [[model.value_text(r, c) for c in range(col0, col1 + 1)]
                  for r in range(row0, row1 + 1)]
        block = [headers] + values
        mime = QMimeData()
        mime.setText(block_to_tsv(block))
        mime.setHtml(block_to_html(block))
        QApplication.clipboard().setMimeData(mime)

    def cut_selection(self) -> None:
        self.copy_selection()
        self.delete_selection()

    def delete_selection(self) -> None:
        model = self.sheet_model()
        if model is None:
            return
        selection = self.selectionModel()
        indexes = selection.selectedIndexes() if selection else []
        if not indexes and self.currentIndex().isValid():
            indexes = [self.currentIndex()]
        model.clear_cells((index.row(), index.column()) for index in indexes)

    def paste_clipboard(self) -> None:
        model = self.sheet_model()
        if model is None:
            return
        rect = self._selection_rect()
        row0, col0 = (rect[0], rect[1]) if rect else (0, 0)
        mime = QApplication.clipboard().mimeData()
        if mime is None:
            return

        if mime.hasFormat(MIME_CELLS):
            decoded = decode_cells(mime.data(MIME_CELLS).data())
            if decoded is not None:
                origin, cells = decoded
                # an in-app paste brings the copied cells' formats, a plain
                # cell's "none" too, as Excel's does
                styles = self.clipboard_styles() or [[None] * len(row)
                                                     for row in cells]
                if (len(cells) == 1 and len(cells[0]) == 1 and rect
                        and (rect[2] > row0 or rect[3] > col0)):
                    # one copied cell over a bigger selection: replicate,
                    # shifting relative refs per target cell
                    block = [[translate(cells[0][0], r - origin[0],
                                        c - origin[1])
                              for c in range(col0, rect[3] + 1)]
                             for r in range(row0, rect[2] + 1)]
                    styles = [[styles[0][0]] * len(block[0])
                              for _ in block]
                else:
                    block = [[translate(text, row0 - origin[0],
                                        col0 - origin[1]) for text in row]
                             for row in cells]
                model.set_cells((row0, col0), block, cell_formats=styles)
                return

        block = parse_paste_text(mime.text())
        if not block:
            return
        if (len(block) == 1 and len(block[0]) == 1 and rect
                and (rect[2] > row0 or rect[3] > col0)):
            block = [[block[0][0]] * (rect[3] - col0 + 1)
                     for _ in range(rect[2] - row0 + 1)]
        model.set_cells((row0, col0), block)

    def fill_series(self) -> None:
        """Home ▸ Fill ▸ Series…: the Series dialog."""
        if self.editable and self._selection_rect() is not None:
            from .series_dialog import fill_series
            fill_series(self)

    def write_series(self, plan, down: bool) -> None:
        """Write a Fill Series plan — [(first cell, values after it)] — as
        one edit, growing the table when a series runs past its end."""
        model = self.sheet_model()
        if model is None or not plan:
            return
        r0 = min(origin[0] for origin, _v in plan)
        c0 = min(origin[1] for origin, _v in plan)
        if down:
            r1 = max(origin[0] + len(v) for origin, v in plan)
            c1 = max(origin[1] for origin, _v in plan)
        else:
            r1 = max(origin[0] for origin, _v in plan)
            c1 = max(origin[1] + len(v) for origin, v in plan)
        block = [[None] * (c1 - c0 + 1) for _ in range(r1 - r0 + 1)]
        for (row, col), values in plan:
            for k, value in enumerate(values, start=1):
                r, c = (row + k, col) if down else (row, col + k)
                block[r - r0][c - c0] = value
        model.set_cells((r0, c0), block)

    def fill_down_selection(self) -> None:
        """Ctrl+D: fill the selection from its top row; with a single row
        selected, fill from the row above (like Excel)."""
        model = self.sheet_model()
        rect = self._selection_rect()
        if model is None or rect is None:
            return
        row0, col0, row1, col1 = rect
        cols = range(col0, col1 + 1)
        if row1 > row0:
            model.fill_down(row0, row1, cols)
        elif row0 > 0:
            model.fill_down(row0 - 1, row0, cols)

    def edit_current(self) -> None:
        current = self.currentIndex()
        if current.isValid():
            self.edit(current)

    # ------------------------------------------------- column widths / fit

    def sizeHintForColumn(self, col: int) -> int:
        """Fit-to-contents leaves wrapped text alone: a wrapped cell is
        meant to run onto more lines, not to stretch its column (Excel's
        AutoFit does the same). A column holding any is as wide as its
        saved width (or the usual), its name, or its unwrapped cells need —
        so turning Wrap Text on in a column the fit had stretched brings it
        back in and the text wraps."""
        model = self.sheet_model()
        if model is None or not any(c == col for _r, c in
                                    model.sheet.styles if model.wraps(_r, c)):
            return super().sizeHintForColumn(col)
        from PySide6.QtWidgets import QStyleOptionViewItem
        delegate = self.itemDelegate()
        option = QStyleOptionViewItem()
        option.initFrom(self)
        widest = 0
        for row in range(min(model.rowCount(), 1000)):
            if model.wraps(row, col) or self.isRowHidden(row):
                continue
            widest = max(widest, delegate.sizeHint(
                option, model.index(row, col)).width())
        header = self.horizontalHeader()
        spec = model.sheet.columns[col]
        base = int(spec.width) if spec.width else header.defaultSectionSize()
        return max(widest + 2 * self.showGrid(), base,
                   header.sectionSizeHint(col))

    def autosize_columns(self, cols=None, persist: bool = True) -> None:
        """Fit columns to their content and header text (all by default).
        persist=False (the automatic mode) resizes without writing the new
        widths into the sheet."""
        model = self.sheet_model()
        if model is None:
            return
        cols = list(cols) if cols is not None else range(model.columnCount())
        frozen = self._frozen if (self._frozen is not None
                                  and self._frozen.cols) else None
        widths = {}
        self._applying_widths = True
        try:
            for col in cols:
                if frozen is not None and col < frozen.cols:
                    # hidden here, shown in its pane: measured there
                    widths[col] = frozen.fit_column(col)
                else:
                    self.resizeColumnToContents(col)
                    widths[col] = self.columnWidth(col)
        finally:
            self._applying_widths = False
        if model.show_totals:
            # a total is often the widest thing in its column (a sum is
            # bigger than any one value): fit it too, in the bold it is
            # drawn in, or it is cut off under the grid
            from PySide6.QtGui import QFont, QFontMetrics
            font = QFont(self.font())
            font.setBold(True)
            metrics = QFontMetrics(font)
            for col in cols:
                text = model.total_text(col)
                need = metrics.horizontalAdvance(text) + 14 if text else 0
                if need > widths.get(col, 0):
                    widths[col] = need
                    if frozen is not None and col < frozen.cols:
                        pane = frozen.panes().get("cols")
                        if pane is not None:
                            pane.setColumnWidth(col, need)
                    else:
                        self.setColumnWidth(col, need)
        if frozen is not None:
            frozen.relayout()
        if persist:
            model.set_column_widths(widths)

    def _hidden_run_after(self, section: int, rows: bool) -> list[int]:
        """The user-hidden rows/columns right after `section` — what a
        double-click on the header edge between them unhides."""
        model = self.sheet_model()
        if model is None:
            return []
        count = model.rowCount() if rows else model.columnCount()
        hidden = (model.hidden_rows if rows else
                  {c for c in range(count) if model.column_hidden(c)})
        out = []
        i = section + 1
        while i < count and i in hidden:
            out.append(i)
            i += 1
        return out

    def _row_handle_double_clicked(self, section: int) -> None:
        run = self._hidden_run_after(section, rows=True)
        model = self.sheet_model()
        if model is None or not self.editable:
            return
        if run:
            model.unhide_rows(run)
            return
        # Excel: double-click a row border to fit the row (and the rest of
        # the selection with it)
        self.autofit_rows(self._selected_sections(section, pick_row=True))

    def _autosize_from_handle(self, section: int) -> None:
        run = self._hidden_run_after(section, rows=False)
        model = self.sheet_model()
        if run and model is not None and self.editable:
            # the edge where columns are hidden: bring them back, as Excel
            model.unhide_columns(run)
            return
        cols = self._selected_sections(section, pick_row=False)
        if len(cols) > 1:
            self.autosize_columns(cols)

    def set_defer_autosize(self, defer: bool) -> None:
        """Put off the automatic column fit until this view is first painted.

        For a view embedded in a canvas card. Fitting reads every cell to
        measure it, and on a canvas holding many Table nodes that was a
        large share of the cost of opening the project — spent on cards that
        are mostly off-screen and may never be looked at. A view inside a
        QGraphicsProxyWidget is only painted when it is actually on screen,
        so waiting for that skips the work entirely for the rest.

        Not for a standalone view (the pop-out editor, tests): there is one
        of those and the user is looking at it.
        """
        self._defer_autosize = defer

    def paintEvent(self, event) -> None:
        if self._autosize_pending:
            self._autosize_pending = False
            # not inline: resizing columns changes geometry, and doing that
            # part-way through a paint invites recursion
            QTimer.singleShot(0, lambda: self.autosize_columns(persist=False))
        super().paintEvent(event)

    def _sync_column_widths(self) -> None:
        """On load/reset: apply the widths stored with the node, or re-fit
        everything when the default-autosize setting is on."""
        model = self.sheet_model()
        if model is None:
            return
        if autosize_default_enabled():
            if self._defer_autosize:
                self._autosize_pending = True
            else:
                self.autosize_columns(persist=False)
            return
        self._applying_widths = True
        try:
            header = self.horizontalHeader()
            for col, spec in enumerate(model.sheet.columns):
                width = int(spec.width) if spec.width \
                    else header.defaultSectionSize()
                # never narrower than the column's own name: the 72px
                # default, and some stored widths, swallow a longer header
                self.setColumnWidth(
                    col, max(width, header.sectionSizeHint(col)))
        finally:
            self._applying_widths = False

    def _maybe_autofit(self, *_args) -> None:
        """Re-fit after a change — but once the typing stops, not per cell.

        A single edit re-evaluates the whole sheet, so the model reports the
        whole grid as changed; fitting every column in response means reading
        every row of every column. Measured on a 300x12 sheet that was 53 ms
        of the 63 ms a keystroke cost, and it grows with the sheet — exactly
        the wrong shape for a table people type into. Coalescing loses
        nothing: the fit is a display convenience, and the settled result is
        identical.
        """
        if autosize_default_enabled():
            self._autofit_timer.start()

    def _run_autofit(self) -> None:
        if autosize_default_enabled() and self.sheet_model() is not None:
            self.autosize_columns(persist=False)

    def _on_section_resized(self, col: int, _old: int, new: int) -> None:
        if self._applying_widths or new <= 0 or self.sheet_model() is None:
            return
        self._pending_widths[col] = new
        self._width_commit_timer.start()

    def _on_row_resized(self, row: int, _old: int, new: int) -> None:
        if new <= 0:
            # a row hidden here (a frozen one shows in a pane instead, a
            # filtered or folded one is out of sight): not a height
            return
        if self._frozen is not None:
            for pane in self._frozen.panes().values():
                if pane.rowHeight(row) != new:
                    pane.setRowHeight(row, new)
        if self._applying_heights or new <= 0 or self.sheet_model() is None:
            return
        self._pending_heights[row] = new
        self._height_commit_timer.start()

    def _persist_pending_heights(self) -> None:
        model = self.sheet_model()
        pending, self._pending_heights = self._pending_heights, {}
        if model is not None and pending:
            model.set_row_heights(pending)

    def apply_row_heights(self, *_args) -> None:
        """Each row at its height: set by hand, else tall enough for its
        wrapped text, else the usual. Only rows that need it are touched,
        so a big table pays nothing for this."""
        model = self.sheet_model()
        if model is None:
            return
        manual = model.row_heights
        wrapped = model.wrapped_rows()
        default = self.verticalHeader().defaultSectionSize()
        rows = (self._sized_rows | set(manual) | wrapped)
        self._applying_heights = True
        try:
            for row in sorted(rows):
                if row >= model.rowCount():
                    continue
                if row in manual:
                    height = manual[row]
                elif row in wrapped:
                    height = max(default, self._wrapped_height(row))
                else:
                    height = default
                if self.rowHeight(row) != height:
                    self.setRowHeight(row, height)
                if self._frozen is not None:
                    for pane in self._frozen.panes().values():
                        if pane.rowHeight(row) != height:
                            pane.setRowHeight(row, height)
        finally:
            self._applying_heights = False
        self._sized_rows = {r for r in rows if r < model.rowCount()
                            and (r in manual or r in wrapped)}

    def _wrapped_height(self, row: int) -> int:
        """How tall a row's wrapped cells need it to be: each one's text
        laid out across its column's width, in its own font. (Qt's size
        hint for a row measures without the column's width, so it never
        wraps.)"""
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QFontMetrics
        model = self.sheet_model()
        tallest = 0
        for col in range(model.columnCount()):
            if not model.wraps(row, col) or self.isColumnHidden(col):
                continue
            index = model.index(row, col)
            text = str(index.data(Qt.DisplayRole) or "")
            if not text:
                continue
            font = self.font()
            role_font = index.data(Qt.FontRole)
            if role_font is not None:
                font = role_font.resolve(font)
            width = max(8, self.columnWidth(col) - 8)
            box = QFontMetrics(font).boundingRect(
                QRect(0, 0, width, 100_000), int(Qt.TextWordWrap), text)
            tallest = max(tallest, box.height() + 6)
        return tallest

    def editing_row_needs(self, row: int, height: int) -> None:
        """An open editor's lines need this much: grow the row to it while
        typing (shrinking back as lines go, never below the row's own
        height). Not saved — the row settles when the editor closes."""
        model = self.sheet_model()
        if model is None or not 0 <= row < model.rowCount():
            return
        base = getattr(self, "_editing_base", None)
        if base is None or base[0] != row:
            base = (row, self.rowHeight(row))
            self._editing_base = base
        target = max(base[1], height)
        if self.rowHeight(row) != target:
            self._applying_heights = True
            try:
                self.setRowHeight(row, target)
            finally:
                self._applying_heights = False
            self._sized_rows.add(row)

    def _editor_closed(self) -> None:
        """Settle a row an editor grew: fitted to what was kept, or back
        to what it was."""
        if getattr(self, "_editing_base", None) is not None:
            self._editing_base = None
            self.apply_row_heights()

    def set_row_height_dialog(self) -> None:
        """Row Height…: a height in pixels for the selected rows."""
        from PySide6.QtWidgets import QInputDialog
        from flograph.core.sheet.schema import ROW_HEIGHT_RANGE
        from .menus import real_window
        model = self.sheet_model()
        rows = self.target_rows()
        if model is None or not rows or not self.editable:
            return
        lo, hi = ROW_HEIGHT_RANGE
        height, ok = QInputDialog.getInt(
            real_window(self), "Row Height",
            f"Height of {len(rows)} row{'s' if len(rows) != 1 else ''}, in "
            f"pixels (usual: {self.verticalHeader().defaultSectionSize()}):",
            self.rowHeight(rows[0]), lo, hi)
        if ok:
            model.set_row_heights({r: height for r in rows})

    def autofit_rows(self, rows=None) -> None:
        """AutoFit Row Height: forget the heights set by hand, so the rows
        go back to the usual height — or tall enough for wrapped text."""
        model = self.sheet_model()
        rows = self.target_rows() if rows is None else rows
        if model is None or not rows or not self.editable:
            return
        model.set_row_heights({r: None for r in rows})
        self.apply_row_heights()

    def _persist_pending_widths(self) -> None:
        model = self.sheet_model()
        pending, self._pending_widths = self._pending_widths, {}
        if model is not None and pending:
            model.set_column_widths(pending)

    # ----------------------------------------------------------- keyboard

    def _owns_shortcut(self, event) -> bool:
        if (event.matches(QKeySequence.Copy) or event.matches(QKeySequence.Cut)
                or event.matches(QKeySequence.Paste)):
            return True
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace, Qt.Key_F2):
            return True
        mods = event.modifiers()
        if (event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right)
                and mods & Qt.ControlModifier):
            return True
        return self.actions.for_key(event) is not None

    def viewportEvent(self, event) -> bool:
        """A cell's tooltip — its formula, or what is wrong with its value —
        shown by the pointer, which on a card Qt's own tooltip is not
        (AA3; see data_table.tooltip_host)."""
        if event.type() != QEvent.ToolTip:
            return super().viewportEvent(event)
        from ..data_table import show_tooltip
        model = self.model()
        index = self.indexAt(event.pos())
        text = (model.data(index, Qt.ToolTipRole)
                if model is not None and index.isValid() else None)
        if text:
            show_tooltip(event.globalPos(), str(text), self.viewport())
        else:
            QToolTip.hideText()
        return True

    def event(self, event) -> bool:
        # claim these keys before the window-level QActions (Duplicate,
        # Rename Node, canvas copy/paste) can swallow them
        if event.type() == QEvent.ShortcutOverride and self._owns_shortcut(event):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape and self._fill.dragging:
            self._fill.cancel()
            event.accept()
            return
        if event.key() == Qt.Key_Escape and self.painting:
            self.stop_painter()
            event.accept()
            return
        action = self.actions.for_key(event)
        if action is not None:
            if action.isEnabled():
                action.trigger()
            event.accept()
            return
        if event.matches(QKeySequence.Copy):
            self.copy_selection()
            event.accept()
            return
        if event.matches(QKeySequence.Cut):
            self.cut_selection()
            event.accept()
            return
        if event.matches(QKeySequence.Paste):
            self.paste_clipboard()
            event.accept()
            return
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selection()
            event.accept()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.state() == QAbstractItemView.EditingState:
                # An open editor already owns Enter: the delegate commits it
                # and closes with SubmitModelCache, which steps down in
                # closeEditor() below. Stepping here as well moved the
                # current cell out from under the editor before that commit
                # landed, leaving Qt to commit an editor the view had
                # already released ("commitData called with an editor that
                # does not belong to this view").
                super().keyPressEvent(event)
                return
            self._step_current(-1 if event.modifiers() & Qt.ShiftModifier else 1, 0)
            event.accept()
            return
        if event.key() == Qt.Key_F2:
            self.edit_current()
            event.accept()
            return
        arrows = {Qt.Key_Up: (-1, 0), Qt.Key_Down: (1, 0),
                  Qt.Key_Left: (0, -1), Qt.Key_Right: (0, 1)}
        mods = event.modifiers() & ~Qt.KeypadModifier
        if (event.key() in arrows and mods & Qt.ControlModifier
                and not mods & (Qt.AltModifier | Qt.MetaModifier)):
            self.jump(*arrows[event.key()],
                      extend=bool(mods & Qt.ShiftModifier))
            event.accept()
            return
        super().keyPressEvent(event)

    def commitData(self, editor) -> None:
        # Ctrl+Enter commits without moving down; with several cells
        # selected, what was typed goes into all of them as one edit
        # (Excel's way to fill the blanks that Go To Special picked)
        delegate = self.itemDelegate()
        if getattr(delegate, "ctrl_enter", False):
            delegate.ctrl_enter = False
            self._stay_after_edit = True
            cells = self._fill_targets()
            text = self._editor_text(editor) if cells else None
            if text is not None:
                current = self.currentIndex()
                self.sheet_model().fill_cells(
                    cells, text, (current.row(), current.column()))
                return
        super().commitData(editor)

    def _fill_targets(self) -> list:
        """The selected cells a Ctrl+Enter fills — none unless more than
        one, and never a row a filter hides."""
        selection = self.selectionModel()
        if selection is None or self.sheet_model() is None:
            return []
        cells = [(i.row(), i.column()) for i in selection.selectedIndexes()
                 if not self.row_filtered(i.row())]
        return cells if len(cells) > 1 else []

    @staticmethod
    def _editor_text(editor):
        from PySide6.QtWidgets import QDateEdit, QLineEdit
        if isinstance(editor, QDateEdit):
            return editor.date().toString("yyyy-MM-dd")
        if isinstance(editor, (QLineEdit, CellEdit)):
            return editor.text()
        return None

    def closeEditor(self, editor, hint) -> None:
        QTimer.singleShot(0, self, self._editor_closed)
        if getattr(self, "_stay_after_edit", False):
            # Ctrl+Enter keeps the selection and the current cell, as Excel
            self._stay_after_edit = False
            super().closeEditor(editor, QAbstractItemDelegate.NoHint)
            return
        # Enter in a cell editor: commit, then move down like Excel
        if hint == QAbstractItemDelegate.SubmitModelCache:
            super().closeEditor(editor, QAbstractItemDelegate.NoHint)
            self._step_current(1, 0)
            return
        super().closeEditor(editor, hint)

    # ------------------------------------------------------- header menus

    def _selected_sections(self, clicked: int, pick_row: bool) -> list[int]:
        """The clicked row/column plus any others in the selection that
        contains it (so multi-select delete works)."""
        selection = self.selectionModel()
        indexes = selection.selectedIndexes() if selection else []
        sections = sorted({index.row() if pick_row else index.column()
                           for index in indexes})
        return sections if clicked in sections else [clicked]

    def _touched_sections(self, pick_row: bool) -> list[int]:
        selection = self.selectionModel()
        indexes = selection.selectedIndexes() if selection else []
        if not indexes and self.currentIndex().isValid():
            indexes = [self.currentIndex()]
        return sorted({index.row() if pick_row else index.column()
                       for index in indexes})

    def selected_rows(self) -> list[int]:
        """Every row the selection touches (or the current cell's row), so
        a toolbar's delete acts on what the user picked; [] when nothing
        is picked at all."""
        return self._touched_sections(pick_row=True)

    def selected_columns(self) -> list[int]:
        """Every column the selection touches — see selected_rows."""
        return self._touched_sections(pick_row=False)

    def _column_menu(self, pos) -> None:
        from .. import menu_guard
        if menu_guard.settling():
            return   # leftovers of a menu that just closed — see menu_guard
        header = self.horizontalHeader()
        col = header.logicalIndexAt(pos)
        if self.sheet_model() is None or col < 0:
            return
        if col not in self.selected_columns() or not self.whole_columns_selected():
            self.select_columns([col])
        from .menus import column_menu
        column_menu(self, header, pos)

    def _row_menu(self, pos) -> None:
        from .. import menu_guard
        if menu_guard.settling():
            return   # leftovers of a menu that just closed — see menu_guard
        header = self.verticalHeader()
        row = header.logicalIndexAt(pos)
        if self.sheet_model() is None or row < 0:
            return
        if row not in self.selected_rows() or not self.whole_rows_selected():
            self.select_rows([row])
        from .menus import row_menu
        row_menu(self, header, pos)

    def contextMenuEvent(self, event) -> None:
        """A right-click on a cell. Not the viewport's customContextMenu
        signal: a scroll area routes its viewport's context-menu event to
        itself, so that signal never fires. The position arrives in viewport
        coordinates, which is what the menu wants."""
        event.accept()
        self._cell_menu(event.pos())

    def _cell_menu(self, pos) -> None:
        from .. import menu_guard
        if menu_guard.settling():
            return   # leftovers of a menu that just closed — see menu_guard
        index = self.indexAt(pos)
        if self.sheet_model() is None:
            return
        if index.isValid() and not self.selectionModel().isSelected(index):
            # right-clicking outside the selection moves it there, as in
            # Excel; inside it, the menu acts on the whole selection
            self.setCurrentIndex(index)
        from .menus import cell_menu
        cell_menu(self, self.viewport(), pos)

    # ------------------------------------------------------ commands/host

    @property
    def actions(self):
        """Every command this grid offers, as QActions — see actions.py."""
        if self._actions is None:
            from .actions import SheetActions
            self._actions = SheetActions(self)
        return self._actions

    def set_host(self, host) -> None:
        """Who owns the grid: answers Submit/Discard and live/held, and can
        open the full editor. See binding.SheetHost."""
        self._host = host
        self.actions.refresh()

    @property
    def host(self):
        from .binding import SheetHost
        return self._host if self._host is not None else SheetHost()

    @property
    def editable(self) -> bool:
        model = self.sheet_model()
        return model is not None and not model.read_only

    def commit_open_editor(self) -> None:
        """Commit a cell still being typed into, before a command reads the
        table (Submit, switching to auto-apply). Qt only commits an editor
        when it loses focus, and a click on the ribbon does not take it."""
        if self.state() != QAbstractItemView.EditingState:
            return
        focus = QApplication.focusWidget()
        if focus is not None and focus is not self and self.isAncestorOf(focus):
            self.setFocus()

    # --------------------------------------------- fill handle / drag geometry

    def _row_top(self, row: int) -> int:
        model = self.sheet_model()
        n = model.rowCount()
        if row < n:
            return self.rowViewportPosition(row)
        last = n - 1
        return (self.rowViewportPosition(last) + self.rowHeight(last)
                + (row - n) * self.verticalHeader().defaultSectionSize())

    def _col_left(self, col: int) -> int:
        model = self.sheet_model()
        n = model.columnCount()
        if col < n:
            return self.columnViewportPosition(col)
        last = n - 1
        return (self.columnViewportPosition(last) + self.columnWidth(last)
                + (col - n) * self.horizontalHeader().defaultSectionSize())

    # Grid coordinates are the view widget's own: they take in the frozen
    # panes, which sit beside the viewport rather than inside it, so one
    # outline (and one fill handle) can run across frozen and scrolling
    # cells alike.

    def _viewport_origin(self, table=None) -> QPoint:
        table = table or self
        return table.viewport().mapTo(self, QPoint(0, 0))

    def _frozen_pane(self, kind: str):
        frozen = self._frozen
        if frozen is None or not frozen.active:
            return None
        return frozen.panes().get(kind)

    def _grid_x(self, col: int, end: bool = False) -> int:
        """The left (or, with `end`, right) edge of a column in grid
        coordinates — past the last column too, where a fill adds some."""
        n = self.sheet_model().columnCount()
        frozen = self._frozen
        if frozen is not None and col < frozen.cols and col < n:
            pane = (self._frozen_pane("cols")
                    or self._frozen_pane("corner"))
            if pane is not None:
                x = pane.columnViewportPosition(col)
                if end:
                    x += pane.columnWidth(col)
                return x + self._viewport_origin(pane).x()
        origin = self._viewport_origin().x()
        x = (self.columnViewportPosition(col) + self.columnWidth(col)
             if end and col < n else self._col_left(col + 1 if end else col))
        # a scrolling column passed under the frozen ones stops at their edge
        return max(x + origin, origin) if self._frozen_cols() else x + origin

    def _grid_y(self, row: int, end: bool = False) -> int:
        n = self.sheet_model().rowCount()
        frozen = self._frozen
        if frozen is not None and row < frozen.rows and row < n:
            pane = (self._frozen_pane("rows")
                    or self._frozen_pane("corner"))
            if pane is not None:
                y = pane.rowViewportPosition(row)
                if end:
                    y += pane.rowHeight(row)
                return y + self._viewport_origin(pane).y()
        origin = self._viewport_origin().y()
        y = (self.rowViewportPosition(row) + self.rowHeight(row)
             if end and row < n else self._row_top(row + 1 if end else row))
        return max(y + origin, origin) if self._frozen_rows() else y + origin

    def _frozen_cols(self) -> int:
        return self._frozen.cols if self._frozen is not None else 0

    def _frozen_rows(self) -> int:
        return self._frozen.rows if self._frozen is not None else 0

    def cells_grid_rect(self, r0: int, c0: int, r1: int, c1: int
                        ) -> Optional[QRect]:
        """Where cells r0..r1 × c0..c1 are, in grid coordinates — frozen
        panes and past the end of the grid included."""
        model = self.sheet_model()
        if model is None or not model.rowCount() or not model.columnCount():
            return None
        left, right = self._grid_x(c0), self._grid_x(c1, end=True)
        top, bottom = self._grid_y(r0), self._grid_y(r1, end=True)
        return QRect(left, top, max(right - left, 0), max(bottom - top, 0))

    def cells_area(self) -> QRect:
        """The part of the grid that shows cells — the viewport and the
        frozen panes beside it — in grid coordinates."""
        area = self.viewport().geometry()
        for pane in (self._frozen.panes().values()
                     if self._frozen is not None and self._frozen.active
                     else ()):
            if pane.isVisible():
                area = area.united(QRect(self._viewport_origin(pane),
                                         pane.viewport().size()))
        return area

    def selection_grid_rect(self) -> Optional[QRect]:
        rect = self._selection_rect()
        if rect is None:
            return None
        return self.cells_grid_rect(*rect)

    def fill_handle_grid_rect(self) -> Optional[QRect]:
        """The fill handle: a small square on the selection's bottom-right
        corner, while the grid can be edited — in a frozen pane too."""
        if not self.editable:
            return None
        rect = self.selection_grid_rect()
        if rect is None or rect.width() <= 0 or rect.height() <= 0:
            return None
        corner = rect.bottomRight()
        if not self.cells_area().adjusted(-1, -1, 1, 1).contains(corner):
            return None      # scrolled out of sight: nothing to grab
        return QRect(corner.x() - 3, corner.y() - 3, 7, 7)

    # the same three on the viewport's own coordinates

    def cells_pixel_rect(self, r0: int, c0: int, r1: int, c1: int
                         ) -> Optional[QRect]:
        rect = self.cells_grid_rect(r0, c0, r1, c1)
        return None if rect is None else rect.translated(
            -self._viewport_origin())

    def selection_pixel_rect(self) -> Optional[QRect]:
        rect = self.selection_grid_rect()
        return None if rect is None else rect.translated(
            -self._viewport_origin())

    def fill_handle_rect(self) -> Optional[QRect]:
        rect = self.fill_handle_grid_rect()
        return None if rect is None else rect.translated(
            -self._viewport_origin())

    def totals_bar(self, parent=None):
        """The Total Row for this grid, for a host to lay out directly
        under it (totals.py). Shows itself while the sheet's Total Row is
        on."""
        from .totals import TotalsBar
        return TotalsBar(self, parent)

    def toggle_totals(self, on: bool) -> None:
        model = self.sheet_model()
        if model is not None and self.editable:
            model.set_show_totals(on)

    def drop_line(self, line) -> None:
        """Where dragged rows/columns will land: ("row"|"col", pixel in grid
        coordinates, the header it crosses), or None to take it away."""
        self._fill.overlay.drop_line = line
        self._fill.refresh()

    def _selection_moved(self, *_args) -> None:
        if getattr(self, "_fill", None) is not None:
            self._fill.refresh()
        if self._actions is not None:
            self._actions.refresh()

    # --------------------------------------------------------- selection

    def select_rows(self, rows) -> None:
        model = self.sheet_model()
        if model is None or not rows or not model.columnCount():
            return
        selection = QItemSelection()
        last = model.columnCount() - 1
        for row in rows:
            selection.select(model.index(row, 0), model.index(row, last))
        current = self.currentIndex()
        col = current.column() if current.isValid() else 0
        self.selectionModel().setCurrentIndex(
            model.index(rows[0], col), QItemSelectionModel.NoUpdate)
        self.selectionModel().select(selection,
                                     QItemSelectionModel.ClearAndSelect)

    def select_columns(self, cols) -> None:
        model = self.sheet_model()
        if model is None or not cols or not model.rowCount():
            return
        selection = QItemSelection()
        last = model.rowCount() - 1
        for col in cols:
            selection.select(model.index(0, col), model.index(last, col))
        current = self.currentIndex()
        row = current.row() if current.isValid() else 0
        self.selectionModel().setCurrentIndex(
            model.index(row, cols[0]), QItemSelectionModel.NoUpdate)
        self.selectionModel().select(selection,
                                     QItemSelectionModel.ClearAndSelect)

    def target_rows(self) -> list[int]:
        """The rows a row command acts on: every row the selection touches —
        except when whole columns are selected, which touch every row but
        mean "this column"; then just the current cell's row."""
        if self.whole_columns_selected() and not self.whole_rows_selected():
            current = self.currentIndex()
            return [current.row()] if current.isValid() else []
        return [r for r in self.selected_rows() if not self.row_filtered(r)]

    def target_columns(self) -> list[int]:
        """The columns a column command acts on — see target_rows."""
        if self.whole_rows_selected() and not self.whole_columns_selected():
            current = self.currentIndex()
            return [current.column()] if current.isValid() else []
        return self.selected_columns()

    def select_selection_rows(self) -> None:
        """Shift+Space: widen the selection to whole rows."""
        self.select_rows(self.selected_rows())

    def select_selection_columns(self) -> None:
        """Ctrl+Space: widen the selection to whole columns."""
        self.select_columns(self.selected_columns())

    def whole_rows_selected(self) -> bool:
        selection = self.selectionModel()
        rows = self.selected_rows()
        return bool(selection is not None and rows) and all(
            selection.isRowSelected(r) for r in rows)

    def whole_columns_selected(self) -> bool:
        selection = self.selectionModel()
        cols = self.selected_columns()
        return bool(selection is not None and cols) and all(
            selection.isColumnSelected(c) for c in cols)

    # ------------------------------------------------- rows and columns

    def insert_rows(self, below: bool = False) -> None:
        """Insert as many rows as are selected, above (or below) them —
        Excel's rule, so selecting three rows and inserting adds three."""
        model = self.sheet_model()
        if model is None or not self.editable:
            return
        rows = self.target_rows()
        if not rows:
            at, count = model.rowCount(), 1
        else:
            count = len(rows)
            at = rows[-1] + 1 if below else rows[0]
        model.insert_rows_at(at, count)
        self.select_rows(list(range(at, at + count)))

    def insert_columns(self, right: bool = False) -> None:
        model = self.sheet_model()
        if model is None or not self.editable:
            return
        cols = self.target_columns()
        if not cols:
            at, count = model.columnCount(), 1
        else:
            count = len(cols)
            at = cols[-1] + 1 if right else cols[0]
        model.insert_columns_at(at, count)
        self.select_columns(list(range(at, at + count)))

    def delete_rows(self) -> None:
        model = self.sheet_model()
        rows = self.target_rows()
        if model is None or not rows or not self.editable:
            return
        model.remove_rows_at(rows)
        self.select_rows([min(rows[0], model.rowCount() - 1)])

    def delete_columns(self) -> None:
        model = self.sheet_model()
        cols = self.target_columns()
        if model is None or not cols or not self.editable:
            return
        model.remove_columns_at(cols)
        self.select_columns([min(cols[0], model.columnCount() - 1)])

    def insert_smart(self) -> None:
        """Ctrl++: columns when whole columns are selected, else rows."""
        if self.whole_columns_selected() and not self.whole_rows_selected():
            self.insert_columns()
        else:
            self.insert_rows()

    def delete_smart(self) -> None:
        """Ctrl+-: columns when whole columns are selected, else rows."""
        if self.whole_columns_selected() and not self.whole_rows_selected():
            self.delete_columns()
        else:
            self.delete_rows()

    def move_rows(self, delta: int) -> None:
        """Move the selected rows up (-1) or down (+1) one place, keeping
        them selected so the move can be repeated."""
        model = self.sheet_model()
        rows = self.target_rows()
        if model is None or not rows or not self.editable:
            return
        start = rows[0] + delta
        if start < 0 or start + len(rows) > model.rowCount():
            return
        cols = self.target_columns()
        whole = self.whole_rows_selected()
        model.move_rows(rows, start)
        moved = list(range(start, start + len(rows)))
        if whole:
            self.select_rows(moved)
        else:
            self._select_block(moved[0], cols[0], moved[-1], cols[-1])

    def move_columns(self, delta: int) -> None:
        model = self.sheet_model()
        cols = self.target_columns()
        if model is None or not cols or not self.editable:
            return
        start = cols[0] + delta
        if start < 0 or start + len(cols) > model.columnCount():
            return
        rows = self.target_rows()
        whole = self.whole_columns_selected()
        model.move_columns(cols, start)
        moved = list(range(start, start + len(cols)))
        if whole:
            self.select_columns(moved)
        else:
            self._select_block(rows[0], moved[0], rows[-1], moved[-1])

    def _select_block(self, r0: int, c0: int, r1: int, c1: int) -> None:
        model = self.sheet_model()
        if model is None:
            return
        self.selectionModel().setCurrentIndex(
            model.index(r0, c0), QItemSelectionModel.NoUpdate)
        self.selectionModel().select(
            QItemSelection(model.index(r0, c0), model.index(r1, c1)),
            QItemSelectionModel.ClearAndSelect)

    # ------------------------------------------------------------ editing

    def fill_right_selection(self) -> None:
        """Ctrl+R: fill the selection from its left column; with one column
        selected, fill from the column to its left (like Excel)."""
        model = self.sheet_model()
        rect = self._selection_rect()
        if model is None or rect is None:
            return
        row0, col0, row1, col1 = rect
        rows = [r for r in range(row0, row1 + 1) if not self.row_filtered(r)]
        if col1 > col0:
            model.fill_right(col0, col1, rows)
        elif col0 > 0:
            model.fill_right(col0 - 1, col0, rows)

    def paste_values(self) -> None:
        """Ctrl+Shift+V: paste what the copied cells *show*, not their
        formulas — Excel's Paste Values."""
        model = self.sheet_model()
        mime = QApplication.clipboard().mimeData()
        if model is None or mime is None or not mime.hasText():
            return
        block = parse_paste_text(mime.text())
        if not block:
            return
        rect = self._selection_rect()
        row0, col0 = (rect[0], rect[1]) if rect else (0, 0)
        model.set_cells((row0, col0), block)

    def clipboard_cells(self):
        """What is on the clipboard as cells: (values, sources, origin).
        `values` is what the copied cells showed; `sources` and `origin`
        are the raw cells and where they came from when they were copied in
        this app (None otherwise). None when there is nothing to paste."""
        mime = QApplication.clipboard().mimeData()
        if mime is None:
            return None
        values = parse_paste_text(mime.text()) if mime.hasText() else []
        sources = origin = None
        if mime.hasFormat(MIME_CELLS):
            decoded = decode_cells(mime.data(MIME_CELLS).data())
            if decoded is not None:
                origin, sources = decoded
                if not values:
                    values = sources
        if not values:
            return None
        return values, sources, origin

    def clipboard_styles(self):
        """The formats of cells copied in this app, or None."""
        from .clipboard import decode_styles
        mime = QApplication.clipboard().mimeData()
        if mime is None or not mime.hasFormat(MIME_CELLS):
            return None
        return decode_styles(mime.data(MIME_CELLS).data())

    def can_paste(self) -> bool:
        """Something pasteable is on the clipboard — a cheap look at its
        formats, for enabling buttons."""
        mime = QApplication.clipboard().mimeData()
        return mime is not None and (mime.hasText()
                                     or mime.hasFormat(MIME_CELLS))

    def paste_special(self, what: str = "all", op: str = "none",
                      skip_blanks: bool = False,
                      transpose: bool = False) -> bool:
        """Paste with Paste Special's choices (see core.sheet.paste) as one
        undo step. False when there was nothing to paste."""
        from flograph.core.sheet.paste import arrange_block, special_block
        model = self.sheet_model()
        cells = self.clipboard_cells()
        if model is None or cells is None or not self.editable:
            return False
        values, sources, origin = cells
        rect = self._selection_rect()
        row0, col0 = (rect[0], rect[1]) if rect else (0, 0)
        fill_to = ((rect[2] - row0 + 1, rect[3] - col0 + 1)
                   if rect else None)
        styles = self.clipboard_styles()
        if styles is None and sources is not None:
            styles = [[None] * len(row) for row in sources]
        if what == "formats":
            if styles is None:
                return False
            model.paste_formats((row0, col0), arrange_block(
                styles, transpose=transpose, fill_to=fill_to))
            return True
        block = special_block(
            values=values, sources=sources, origin=origin, at=(row0, col0),
            target=lambda r, c: (model.cell_source(r, c),
                                 model.computed_value(r, c)),
            what=what, op=op, skip_blanks=skip_blanks, transpose=transpose,
            fill_to=fill_to)
        if not block:
            return False
        formats = None
        if what == "all" and op == "none" and styles is not None:
            formats = arrange_block(styles, transpose=transpose,
                                    fill_to=fill_to)
            formats = [[False if text is None else fmt
                        for text, fmt in zip(line, fmts)]
                       for line, fmts in zip(block, formats)]
        model.set_cells((row0, col0), block, cell_formats=formats)
        return True

    def paste_transposed(self) -> None:
        """Paste with the copied rows turned into columns."""
        self.paste_special(transpose=True)

    def open_paste_special(self) -> None:
        """Home ▸ Paste Special… (Ctrl+Alt+V): the dialog."""
        if self.editable:
            from .paste_dialog import paste_special
            paste_special(self)

    def jump(self, drow: int, dcol: int, extend: bool = False) -> None:
        """Ctrl+arrow: to the edge of the run of filled cells, or to the
        next filled cell past a gap, or to the grid's edge — Excel's rule.
        With Shift, the selection stretches to where it lands."""
        model = self.sheet_model()
        current = self.currentIndex()
        if model is None or not current.isValid():
            return
        row, col = current.row(), current.column()
        n_rows, n_cols = model.rowCount(), model.columnCount()

        def filled(r, c):
            return bool(model.cell_source(r, c).strip())

        def inside(r, c):
            return 0 <= r < n_rows and 0 <= c < n_cols

        r, c = row + drow, col + dcol
        if not inside(r, c):
            return
        if filled(row, col) and filled(r, c):
            while inside(r + drow, c + dcol) and filled(r + drow, c + dcol):
                r, c = r + drow, c + dcol
        else:
            while inside(r + drow, c + dcol) and not filled(r, c):
                r, c = r + drow, c + dcol
        target = model.index(r, c)
        if extend:
            rect = self._selection_rect() or (row, col, row, col)
            self.selectionModel().setCurrentIndex(
                target, QItemSelectionModel.NoUpdate)
            self.selectionModel().select(
                QItemSelection(model.index(min(rect[0], r), min(rect[1], c)),
                               model.index(max(rect[2], r), max(rect[3], c))),
                QItemSelectionModel.ClearAndSelect)
        else:
            self.setCurrentIndex(target)
            self.selectionModel().select(
                target, QItemSelectionModel.ClearAndSelect)
        self.scrollTo(target)

    def rename_current_column(self) -> None:
        cols = self.target_columns()
        if cols:
            self.rename_column(cols[0])

    def rename_column(self, col: int) -> None:
        model = self.sheet_model()
        if model is None or not 0 <= col < model.columnCount() or model.read_only:
            return
        current = model.sheet.columns[col].name
        from .menus import ask_text
        name = ask_text(self, "Rename column",
                        "New name for this column. Formulas that use "
                        f"[{current}] or [@{current}] follow the new name.",
                        current)
        if name and name != current:
            model.rename_column(col, name)

    def promote_current_row(self) -> None:
        model = self.sheet_model()
        rows = self.target_rows()
        if model is not None and rows:
            model.promote_row_to_header(rows[0])

    # ----------------------------------------------------- number formats

    def apply_format(self, fmt) -> None:
        """Give the selected columns a number format (None for General)."""
        model = self.sheet_model()
        cols = self.target_columns()
        if model is not None and cols and self.editable:
            model.set_column_format(cols, fmt)

    def step_decimals(self, delta: int) -> None:
        """Excel's Increase / Decrease Decimal, on the selected columns."""
        from flograph.core.sheet.numfmt import step_decimals
        model = self.sheet_model()
        cols = self.target_columns()
        if model is None or not cols or not self.editable:
            return
        current = self.currentIndex()
        shown = (model.index(current.row(), current.column()).data()
                 if current.isValid() else None)
        model.set_column_format(
            cols, step_decimals(model.column_format(cols[0]), delta,
                                str(shown) if shown is not None else None))

    def format_cells(self) -> None:
        """Ctrl+1: the Format Cells dialog for the selected columns."""
        cols = self.target_columns()
        if cols and self.editable:
            from .numfmt_dialog import edit_number_format
            edit_number_format(self, cols)

    # ---------------------------------------------------- data validation

    def edit_validation(self) -> None:
        """Data ▸ Validation…: what the selected columns will take."""
        cols = self.target_columns()
        if cols and self.editable:
            from .validation_dialog import edit_validation
            edit_validation(self, cols)

    # ----------------------------------------------------- find & select

    def select_cells(self, cells, note: str = "") -> None:
        """Select exactly these cells — joined into runs down each column,
        so thousands select at once — make the first one current, scroll to
        it and say `note` beside it."""
        from PySide6.QtCore import QItemSelection, QItemSelectionModel
        model = self.sheet_model()
        selection = self.selectionModel()
        cells = sorted(set(cells))
        if model is None or selection is None or not cells:
            return
        by_col: dict[int, list[int]] = {}
        for r, c in cells:
            by_col.setdefault(c, []).append(r)
        chosen = QItemSelection()
        for c, rows in by_col.items():
            start = prev = rows[0]
            for r in rows[1:] + [None]:
                if r is not None and r == prev + 1:
                    prev = r
                    continue
                chosen.select(model.index(start, c), model.index(prev, c))
                if r is not None:
                    start = prev = r
        first = model.index(*cells[0])
        selection.setCurrentIndex(first, QItemSelectionModel.NoUpdate)
        selection.select(chosen, QItemSelectionModel.ClearAndSelect)
        self.scrollTo(first)
        if note:
            self.say(note)

    def select_rect(self, rect) -> None:
        """Select (row0, col0, row1, col1), its top-left cell current."""
        r0, c0, r1, c1 = rect
        self.select_cells([(r, c) for r in range(r0, r1 + 1)
                           for c in range(c0, c1 + 1)
                           if not self.row_filtered(r) or r == r0])

    def say(self, text: str) -> None:
        """A note by the current cell, or at the grid's corner when that
        cell is out of sight."""
        from PySide6.QtWidgets import QToolTip
        index = self.currentIndex()
        rect = self.visualRect(index) if index.isValid() else None
        if rect is not None and rect.isValid() \
                and self.viewport().rect().intersects(rect):
            self.cell_note(index, text)
            return
        where = self.viewport().mapToGlobal(self.viewport().rect().topLeft())
        QToolTip.showText(where, text, self.viewport(), msecShowTime=4000)

    def _special_scope(self):
        """Go To Special looks inside the selection when it is more than one
        cell, else at the whole sheet — Excel's rule."""
        selection = self.selectionModel()
        indexes = selection.selectedIndexes() if selection else []
        if len(indexes) > 1:
            return [(i.row(), i.column()) for i in indexes]
        return None

    def select_special(self, kind: str, types=None) -> int:
        """Home ▸ Find & Select: select every cell of one kind (see
        core.sheet.select). Returns how many were selected."""
        from flograph.core.sheet import select as pick
        model = self.sheet_model()
        if model is None:
            return 0
        n_rows, n_cols = model.rowCount(), model.columnCount()

        def filled(r, c):
            return bool(model.cell_source(r, c).strip())

        current = self.currentIndex()
        if kind == "region":
            if not current.isValid():
                return 0
            rect = pick.current_region(n_rows, n_cols, filled,
                                       current.row(), current.column())
            self.select_rect(rect)
            r0, c0, r1, c1 = rect
            self.say(f"{r1 - r0 + 1} × {c1 - c0 + 1} cells selected — the "
                     "block of data around this cell.")
            return (r1 - r0 + 1) * (c1 - c0 + 1)
        if kind == "last":
            spot = pick.last_cell(n_rows, n_cols, filled)
            if spot is None:
                self.say("The table is empty.")
                return 0
            self.select_cells([spot], "The last row and column with data.")
            return 1
        cells = pick.special_cells(
            n_rows, n_cols, model.cell_source, model.computed_value, kind,
            types if types is not None else pick.TYPES,
            within=self._special_scope(), skip_row=self.row_filtered,
            problem=lambda r, c: model.cell_problem(r, c) is not None,
            noted=lambda r, c: bool(model.note(r, c)))
        if cells:
            self.select_cells(cells, pick.found_text(kind, len(cells)))
        else:
            self.say(pick.found_text(kind, 0))
        return len(cells)

    def go_to(self) -> None:
        """Home ▸ Find & Select ▸ Go To… (Ctrl+G)."""
        from .goto_dialog import go_to
        go_to(self)

    def define_name(self) -> None:
        """Formulas ▸ Define Name: a name for the selected cells."""
        from .names_dialog import name_manager
        name_manager(self, new=True)

    def manage_names(self) -> None:
        from .names_dialog import name_manager
        name_manager(self)

    def go_to_special(self) -> None:
        """Home ▸ Find & Select ▸ Go To Special…"""
        from .goto_dialog import go_to_special
        go_to_special(self)

    def cell_note(self, index, text: str, msecs: int = 4000) -> None:
        """A note beside a cell — Excel's yellow box. A tooltip, because a
        tooltip is a real window and so works on a canvas card too."""
        from PySide6.QtWidgets import QToolTip
        rect = self.visualRect(index)
        if not text or not rect.isValid():
            return
        where = self.viewport().mapToGlobal(rect.bottomRight())
        QToolTip.showText(where, text, self.viewport(), rect, msecs)

    def _show_hint(self, current, _previous=None) -> None:
        model = self.sheet_model()
        if model is None or not current.isValid() or not self.hasFocus():
            return
        rule = model.column_validation(current.column())
        if rule and rule.get("hint"):
            name = model.sheet.columns[current.column()].name
            self.cell_note(current, f"<b>{name}</b><br>{rule['hint']}")

    def _edit_refused(self, row: int, col: int, text: str, why: str) -> None:
        """A Stop rule turned a typed value away: back into the cell with
        the text still there to fix, and the reason beside it."""
        model = self.sheet_model()
        if model is None:
            return
        index = model.index(row, col)

        def again() -> None:
            if self.model() is not model:
                return
            self.setCurrentIndex(index)
            self.edit(index)
            from PySide6.QtWidgets import QApplication, QLineEdit
            editor = QApplication.focusWidget()
            if isinstance(editor, (QLineEdit, CellEdit)):
                editor.setText(text)
                editor.selectAll()
            self.cell_note(index, f"<b>Not kept</b><br>{why}<br>"
                                  "<span style='color:#9ca3af'>Fix it, or "
                                  "Esc to leave the cell as it was.</span>",
                           6000)

        QTimer.singleShot(0, again)

    def next_problem(self) -> None:
        """Data ▸ Next Problem: on to the next cell that is red or shows an
        error — a broken rule, a value that doesn't fit its type or list,
        a formula error — with what is wrong beside it."""
        model = self.sheet_model()
        if model is None:
            return
        cells = [(r, c) for r, c in model.problem_cells()
                 if not self.row_filtered(r)]
        if not cells:
            from PySide6.QtWidgets import QToolTip
            QToolTip.showText(
                self.viewport().mapToGlobal(self.viewport().rect().center()),
                "No problems — every cell fits its column.", self.viewport())
            return
        current = self.currentIndex()
        here = ((current.row(), current.column()) if current.isValid()
                else (-1, -1))
        after = [cell for cell in cells if cell > here]
        target = after[0] if after else cells[0]
        index = model.index(*target)
        self.setCurrentIndex(index)
        self.scrollTo(index)
        place = cells.index(target) + 1
        self.cell_note(index, f"<b>Problem {place} of {len(cells)}</b><br>"
                              f"{model.cell_problem(*target)}", 6000)

    # ------------------------------------------------------ cell formats

    # ---------------------------------------------------- format painter

    @property
    def painting(self) -> bool:
        return getattr(self, "_painter", None) is not None

    def start_painter(self, sticky: bool = False) -> None:
        """Format Painter: pick up the selected cells' look; the next cells
        clicked or dragged over get it. `sticky` (a double-click on the
        button) keeps the brush until Esc or the button again."""
        model = self.sheet_model()
        rect = self._selection_rect()
        if model is None or rect is None or not self.editable:
            return
        r0, c0, r1, c1 = rect
        block = [[model.cell_format(r, c) or None for c in range(c0, c1 + 1)]
                 for r in range(r0, r1 + 1)]
        self._painter = {"block": block, "sticky": sticky}
        from .icons import sheet_icon
        from PySide6.QtGui import QCursor
        brush = sheet_icon("format_painter").pixmap(20, 20)
        cursor = QCursor(brush, 3, 17)
        self.viewport().setCursor(cursor)
        if self._frozen is not None:
            for pane in self._frozen.panes().values():
                pane.viewport().setCursor(cursor)
        self.say("Click or drag over the cells to paint"
                 + (" — Esc when you're done." if sticky else "."))
        if self._actions is not None:
            self._actions.refresh()

    def stop_painter(self) -> None:
        self._painter = None
        self.viewport().unsetCursor()
        if self._frozen is not None:
            for pane in self._frozen.panes().values():
                pane.viewport().unsetCursor()
        if self._actions is not None:
            self._actions.refresh()

    def painter_landed(self) -> None:
        """The mouse let go over the grid: paint the selection with the
        picked-up look, the source's pattern repeated across it."""
        painter = getattr(self, "_painter", None)
        model = self.sheet_model()
        if painter is None or model is None:
            return
        selection = self.selectionModel()
        cells = {(i.row(), i.column())
                 for i in (selection.selectedIndexes() if selection else [])}
        if not cells and self.currentIndex().isValid():
            cells = {(self.currentIndex().row(), self.currentIndex().column())}
        if cells:
            block = painter["block"]
            h, w = len(block), len(block[0])
            r0 = min(r for r, _c in cells)
            c0 = min(c for _r, c in cells)
            r1 = max(r for r, _c in cells)
            c1 = max(c for _r, c in cells)
            out = [[block[(r - r0) % h][(c - c0) % w] if (r, c) in cells
                    else False for c in range(c0, c1 + 1)]
                   for r in range(r0, r1 + 1)]
            model.paste_formats((r0, c0), out)
        if not painter["sticky"]:
            self.stop_painter()

    def format_targets(self) -> list[tuple[int, int]]:
        """The cells a Font/Alignment command acts on: the selection, or
        the current cell."""
        selection = self.selectionModel()
        indexes = selection.selectedIndexes() if selection else []
        if not indexes and self.currentIndex().isValid():
            indexes = [self.currentIndex()]
        return sorted({(i.row(), i.column()) for i in indexes})

    def current_format(self) -> dict:
        model = self.sheet_model()
        current = self.currentIndex()
        if model is None or not current.isValid():
            return {}
        return model.cell_format(current.row(), current.column())

    def format_selection(self, **changes) -> None:
        """Bold, a fill, centred … on every selected cell, one undo step."""
        model = self.sheet_model()
        if model is not None and self.editable:
            model.format_cells(self.format_targets(), **changes)

    def set_fill(self, color) -> None:
        if color:
            self.last_fill = color
        self.format_selection(fill=color)

    def set_ink(self, color) -> None:
        if color:
            self.last_ink = color
        self.format_selection(color=color)

    def set_align(self, side, on: bool = True) -> None:
        self.format_selection(align=side if on else None)

    def clear_cell_formats(self) -> None:
        """Clear Formats: back to a plain cell — the value stays."""
        model = self.sheet_model()
        if model is not None and self.editable:
            model.clear_formats(self.format_targets())

    def pick_color(self, title: str, start: str):
        """More Colours…: the system colour picker; None when cancelled."""
        from PySide6.QtWidgets import QColorDialog
        from .menus import real_window
        color = QColorDialog.getColor(QColor(start), real_window(self),
                                      title)
        return color.name() if color.isValid() else None

    # ----------------------------------------------------- grouped rows

    def group_selected_rows(self) -> None:
        """Rows & Columns ▸ Group: the selected rows become a group."""
        model = self.sheet_model()
        rows = self.target_rows()
        if model is None or not rows or not self.editable:
            return
        why = model.group_rows(min(rows), max(rows))
        if why:
            self.say(why)
        else:
            n = max(rows) - min(rows) + 1
            self.say(f"Grouped {n} row{'s' if n != 1 else ''} — click − in "
                     "the margin to fold them away.")

    def ungroup_selected_rows(self) -> None:
        """Rows & Columns ▸ Ungroup: one level off the selected rows."""
        model = self.sheet_model()
        rows = self.target_rows()
        if model is None or not rows or not self.editable:
            return
        if not model.ungroup_rows(min(rows), max(rows)):
            self.say("Those rows aren't in a group.")

    def _detail_group(self):
        from flograph.core.sheet.outline import innermost_at
        model = self.sheet_model()
        current = self.currentIndex()
        if model is None or not current.isValid():
            return None
        return innermost_at(model.groups, current.row(), model.rowCount())

    def set_detail(self, show: bool) -> None:
        """Hide Detail / Show Detail: fold or unfold the group the current
        row is in (or whose button it is on)."""
        model = self.sheet_model()
        if model is None:
            return
        if show:
            # unfold the deepest folded group whose button is here
            from flograph.core.sheet.outline import button_row, level_of
            row = self.currentIndex().row()
            folded = [g for g in model.groups if g.collapsed
                      and button_row(g, model.rowCount()) == row]
            if folded:
                model.set_folded([max(folded, key=lambda g: level_of(
                    model.groups, g))], False)
                return
        group = self._detail_group()
        if group is not None:
            model.set_folded([group], not show)

    def toggle_group(self, group) -> None:
        model = self.sheet_model()
        if model is not None:
            model.set_folded([group], not group.collapsed)

    def fold_all(self, folded: bool) -> None:
        """Collapse All / Expand All."""
        model = self.sheet_model()
        if model is not None:
            model.set_folded(model.groups, folded)

    def fold_level(self, level: int) -> None:
        """The 1 2 3 buttons: show the outline down to `level` — every
        group deeper than it folded, the rest open."""
        from flograph.core.sheet.outline import level_of
        model = self.sheet_model()
        if model is None:
            return
        groups = model.groups
        model.set_folded([g for g in groups if level_of(groups, g) >= level],
                         True)
        model.set_folded([g for g in groups if level_of(groups, g) < level],
                         False)

    def clear_outline(self) -> None:
        model = self.sheet_model()
        if model is not None and self.editable:
            model.clear_outline()

    def duplicate_rows(self, cols) -> list[int]:
        """Rows shown that repeat an earlier shown row on `cols`."""
        from flograph.core.sheet.dedupe import duplicate_rows
        model = self.sheet_model()
        if model is None:
            return []
        shown = [r for r in range(model.rowCount())
                 if not self.row_filtered(r)]
        return duplicate_rows(model.rowCount(), cols, model.value_text,
                              rows=shown)

    def text_to_columns(self) -> None:
        """Data ▸ Text to Columns…: split the current column."""
        if self.editable and self.currentIndex().isValid():
            from .split_dialog import text_to_columns
            text_to_columns(self)

    def remove_duplicates(self) -> None:
        """Data ▸ Remove Duplicates…: the dialog."""
        if self.editable:
            from .dedupe_dialog import remove_duplicates
            remove_duplicates(self)

    def drop_duplicates(self, cols) -> int:
        """Remove the duplicate rows on `cols` as one undo step and say
        how many went."""
        from flograph.core.sheet.dedupe import summary
        model = self.sheet_model()
        if model is None:
            return 0
        dupes = self.duplicate_rows(cols)
        shown = sum(1 for r in range(model.rowCount())
                    if not self.row_filtered(r))
        if dupes:
            model.remove_rows_at(dupes)
        self.say(summary(len(dupes), shown - len(dupes)))
        return len(dupes)

    def select_duplicates(self, cols) -> int:
        """Select the duplicate rows on `cols`, to look at first."""
        model = self.sheet_model()
        dupes = self.duplicate_rows(cols)
        if model is None or not dupes:
            self.say("No duplicates.")
            return 0
        self.select_cells([(r, c) for r in dupes
                           for c in range(model.columnCount())],
                          f"{len(dupes)} duplicate "
                          f"{'row' if len(dupes) == 1 else 'rows'} selected "
                          "— the first of each set is not.")
        return len(dupes)

    def edit_note(self) -> None:
        """Right-click ▸ New Note… / Edit Note… (Shift+F2): the current
        cell's note."""
        current = self.currentIndex()
        if current.isValid() and self.editable:
            from .note_dialog import edit_note
            edit_note(self, current.row(), current.column())

    def note_targets(self) -> list[tuple[int, int]]:
        """The selected cells (or the current one) that carry a note."""
        model = self.sheet_model()
        if model is None:
            return []
        selection = self.selectionModel()
        indexes = selection.selectedIndexes() if selection else []
        if not indexes and self.currentIndex().isValid():
            indexes = [self.currentIndex()]
        noted = set(model.note_cells())
        return sorted({(i.row(), i.column()) for i in indexes} & noted)

    def delete_notes(self) -> None:
        """Delete Note: off every selected cell that has one."""
        model = self.sheet_model()
        if model is not None and self.editable:
            model.delete_notes(self.note_targets())

    def next_note(self) -> None:
        """Next Note: on to the next cell with a note, showing it."""
        model = self.sheet_model()
        if model is None:
            return
        cells = [cell for cell in model.note_cells()
                 if not self.row_filtered(cell[0])]
        if not cells:
            self.say("No notes yet — right-click a cell ▸ New Note… to add "
                     "one.")
            return
        current = self.currentIndex()
        here = ((current.row(), current.column()) if current.isValid()
                else (-1, -1))
        after = [cell for cell in cells if cell > here]
        target = after[0] if after else cells[0]
        index = model.index(*target)
        self.setCurrentIndex(index)
        self.scrollTo(index)
        import html as _html
        body = _html.escape(model.note(*target)).replace("\n", "<br>")
        place = cells.index(target) + 1
        self.cell_note(index, f"<b>Note {place} of {len(cells)}</b><br>"
                              f"{body}", 6000)

    def edit_column_list(self) -> None:
        """Data ▸ Dropdown List… for the current column."""
        cols = self.target_columns()
        if cols:
            from .dropdown import edit_dropdown_list
            edit_dropdown_list(self, cols[0])

    def open_cell_dropdown(self) -> None:
        """Alt+Down, or a click on the ▾: the column's list, to pick from."""
        model = self.sheet_model()
        current = self.currentIndex()
        if model is None or not current.isValid() or not self.editable:
            return
        if model.column_choices(current.column())[0]:
            from .dropdown import open_choice_list
            open_choice_list(self, current)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            self.painter_landed()

    def mousePressEvent(self, event) -> None:
        """A click on the ▾ of a dropdown cell opens its list."""
        index = self.indexAt(event.position().toPoint())
        model = self.sheet_model()
        if (event.button() == Qt.LeftButton and index.isValid()
                and index == self.currentIndex() and model is not None
                and model.column_choices(index.column())[0]):
            from .delegates import caret_rect
            if caret_rect(self.visualRect(index)).contains(
                    event.position().toPoint()):
                event.accept()
                self.open_cell_dropdown()
                return
        super().mousePressEvent(event)

    def start_formula(self, text: str) -> None:
        """Open the current cell's editor with `text` typed in — Insert
        Function's "=SUM(" — and the cursor after it."""
        current = self.currentIndex()
        if not current.isValid() or not self.editable:
            return
        from .delegates import SheetDelegate
        SheetDelegate.last_editor = None
        if not self.edit(current, QAbstractItemView.EditKeyPressed, None):
            return
        editor = SheetDelegate.last_editor
        import shiboken6
        if editor is not None and shiboken6.isValid(editor):
            editor.setText(text)
            editor.setFocus()

    def find_replace(self, replace: bool = False) -> None:
        from .find import open_find
        open_find(self, replace)

    def find_next(self, text: str, *, match_case: bool = False,
                  whole_cell: bool = False, backwards: bool = False) -> bool:
        """Move to the next cell whose formula or shown value holds `text`,
        wrapping at the end. False when no cell matches."""
        model = self.sheet_model()
        if model is None or not text:
            return False
        n_rows, n_cols = model.rowCount(), model.columnCount()
        total = n_rows * n_cols
        if not total:
            return False
        current = self.currentIndex()
        start = (current.row() * n_cols + current.column()
                 if current.isValid() else -1)
        needle = text if match_case else text.casefold()

        def hit(r, c) -> bool:
            for hay in (model.cell_source(r, c), model.value_text(r, c)):
                hay = hay if match_case else hay.casefold()
                if (hay == needle) if whole_cell else (needle in hay):
                    return True
            return False

        step = -1 if backwards else 1
        for i in range(1, total + 1):
            flat = (start + step * i) % total
            r, c = divmod(flat, n_cols)
            if self.row_filtered(r):
                continue
            if hit(r, c):
                index = model.index(r, c)
                self.setCurrentIndex(index)
                self.selectionModel().select(
                    index, QItemSelectionModel.ClearAndSelect)
                self.scrollTo(index)
                return True
        return False

    # ------------------------------------------------------ show formulas

    @property
    def show_formulas(self) -> bool:
        return self._show_formulas

    def set_show_formulas(self, flag: bool) -> None:
        """Ctrl+`: show every cell's formula instead of its value — for
        checking a sheet over, as in Excel. A view setting, never saved."""
        self._show_formulas = bool(flag)
        delegate = self.itemDelegate()
        if hasattr(delegate, "show_formulas"):
            delegate.show_formulas = self._show_formulas
        self.viewport().update()
        if self._frozen is not None:
            self._frozen.repaint_panes()
        self.actions.refresh()

    # ------------------------------------------------------------ filters

    def is_column_filtered(self, col: int) -> bool:
        return col in self._filters

    @property
    def filtered(self) -> bool:
        return bool(self._filters)

    def column_filter(self, col: int) -> Optional[set]:
        return self._filters.get(col)

    def set_column_filter(self, col: int, allowed: Optional[set]) -> None:
        """Show only rows whose value in `col` is in `allowed` (as shown);
        None shows every row again. A view of the table, not an edit: the
        rows are hidden here, and the Table still sends every one of them
        down the flow."""
        if allowed is None:
            self._filters.pop(col, None)
        else:
            self._filters[col] = set(allowed)
        self._reapply_filter()

    def clear_filters(self) -> None:
        if self._filters:
            self._filters = {}
            self._reapply_filter()

    def filter_by_current_value(self) -> None:
        """Keep only the rows whose value in this column matches the current
        cell's — the quickest filter there is."""
        model = self.sheet_model()
        current = self.currentIndex()
        if model is None or not current.isValid():
            return
        self.set_column_filter(
            current.column(),
            {model.value_text(current.row(), current.column())})

    def row_filtered(self, row: int) -> bool:
        """Is this row out of sight — hidden by a filter, or inside a
        folded group? Commands that leave hidden rows alone ask this. (Not
        the same as isRowHidden: a frozen row is hidden in the grid because
        a pane shows it.)"""
        return (row in self._filtered_rows or row in self._folded_rows
                or row in self._user_hidden_rows())

    def _user_hidden_rows(self):
        model = self.sheet_model()
        return model.hidden_rows if model is not None else ()

    def column_user_hidden(self, col: int) -> bool:
        model = self.sheet_model()
        return model is not None and model.column_hidden(col)

    def _apply_hidden(self, *_args) -> None:
        """Show the rows and columns the user hid as hidden — and the
        rest as shown — alongside the filter, folds and frozen panes."""
        model = self.sheet_model()
        if model is None:
            return
        rows = frozenset(model.hidden_rows)
        if rows != getattr(self, "_shown_hidden_rows", frozenset()):
            self._shown_hidden_rows = rows
            current = self.currentIndex()
            if current.isValid() and current.row() in rows:
                spare = next((r for r in range(model.rowCount())
                              if not self.row_filtered(r)), None)
                if spare is not None:
                    self.setCurrentIndex(model.index(spare, current.column()))
            self._sync_hidden_rows()
        frozen = self._frozen.cols if self._frozen is not None else 0
        header = self.horizontalHeader()
        changed = False
        for col in range(model.columnCount()):
            want = model.column_hidden(col) or col < frozen
            if header.isSectionHidden(col) != want:
                self.setColumnHidden(col, want)
                changed = True
        if changed and self._frozen is not None:
            self._frozen.sync_rows()
        self.horizontalHeader().viewport().update()
        self.verticalHeader().viewport().update()

    def _refit_soon(self, *_args) -> None:
        """An edit can change what a wrapped row needs, or turn wrapping on
        or off: re-fit once things settle."""
        model = self.sheet_model()
        if model is not None and (model.wrapped_rows() or self._sized_rows
                                  or model.row_heights):
            self._refit_timer.start()

    def hide_selected_rows(self) -> None:
        """Hide Rows (Ctrl+9): out of sight, still in the table."""
        model = self.sheet_model()
        rows = self.target_rows()
        if model is not None and rows and self.editable \
                and not model.hide_rows(rows):
            self.say("At least one row has to stay in sight.")

    def hide_selected_columns(self) -> None:
        """Hide Columns (Ctrl+0): out of sight, still sent on."""
        model = self.sheet_model()
        cols = self.target_columns()
        if model is not None and cols and self.editable \
                and not model.hide_columns(cols):
            self.say("At least one column has to stay in sight.")

    def _around(self, picked, hidden, count):
        """The hidden ones inside the span of `picked`, or right beside
        it — so selecting the rows either side (or just one next to them)
        brings them back, as Excel does."""
        if not picked:
            return []
        lo, hi = min(picked), max(picked)
        out = [i for i in range(lo, hi + 1) if i in hidden]
        i = lo - 1
        while i >= 0 and i in hidden:
            out.append(i)
            i -= 1
        i = hi + 1
        while i < count and i in hidden:
            out.append(i)
            i += 1
        return sorted(out)

    def unhide_selected_rows(self) -> None:
        """Unhide Rows (Ctrl+Shift+9): the hidden rows within or beside
        the selection."""
        model = self.sheet_model()
        if model is None or not self.editable:
            return
        rows = self._around(self.selected_rows(), model.hidden_rows,
                            model.rowCount())
        if not model.unhide_rows(rows):
            self.say("No hidden rows there — select the rows either side "
                     "of them, or use Unhide All.")

    def unhide_selected_columns(self) -> None:
        model = self.sheet_model()
        if model is None or not self.editable:
            return
        hidden = {c for c in range(model.columnCount())
                  if model.column_hidden(c)}
        cols = self._around(self.selected_columns(), hidden,
                            model.columnCount())
        if not model.unhide_columns(cols):
            self.say("No hidden columns there — select the columns either "
                     "side of them, or use Unhide All.")

    def unhide_all(self) -> None:
        model = self.sheet_model()
        if model is not None and self.editable:
            model.unhide_rows()
            model.unhide_columns()

    def hidden_count(self) -> tuple[int, int]:
        model = self.sheet_model()
        if model is None:
            return 0, 0
        return (len(model.hidden_rows),
                sum(1 for c in range(model.columnCount())
                    if model.column_hidden(c)))

    def _apply_outline(self, *_args) -> None:
        """Hide the rows of folded groups and size the outline gutter."""
        from flograph.core.sheet.outline import hidden_rows
        model = self.sheet_model()
        if model is None:
            return
        folded = hidden_rows(model.groups)
        header = self.verticalHeader()
        if hasattr(header, "outline_changed"):
            header.outline_changed()
        if folded == self._folded_rows:
            return
        self._folded_rows = frozenset(folded)
        current = self.currentIndex()
        if current.isValid() and current.row() in folded:
            # the current cell was folded away: onto the group's button row
            from flograph.core.sheet.outline import button_row, innermost_at
            group = max((g for g in model.groups if g.collapsed
                         and g.covers(current.row())),
                        key=lambda g: g.end - g.start)
            row = button_row(group, model.rowCount())
            if 0 <= row < model.rowCount():
                self.setCurrentIndex(model.index(row, current.column()))
        self._sync_hidden_rows()

    def _reapply_filter(self, *_args) -> None:
        model = self.sheet_model()
        if model is None:
            return
        if not self._filters and not self._filtered_rows:
            return
        self._filters = {c: v for c, v in self._filters.items()
                         if c < model.columnCount()}
        self._filtered_rows = {
            row for row in range(model.rowCount())
            if any(model.value_text(row, col) not in allowed
                   for col, allowed in self._filters.items())}
        self._sync_hidden_rows()

    def _sync_hidden_rows(self) -> None:
        """Show and hide rows for the filter, the folded groups and the
        frozen panes together."""
        model = self.sheet_model()
        if model is None:
            return
        frozen_rows = self._frozen.rows if self._frozen is not None else 0
        for row in range(model.rowCount()):
            hide = self.row_filtered(row) or row < frozen_rows
            if self.isRowHidden(row) != hide:
                self.setRowHidden(row, hide)
        self.horizontalHeader().viewport().update()
        if self._frozen is not None:
            self._frozen.sync_rows()
        self.filter_changed.emit()
        if self._actions is not None:
            self._actions.refresh()

    def open_column_filter(self, col: int) -> None:
        """The ▾ on a column header: sort, and pick the values to show."""
        from .filter import open_filter_popup
        open_filter_popup(self, col)

    def visible_row_count(self) -> int:
        model = self.sheet_model()
        if model is None:
            return 0
        return sum(1 for row in range(model.rowCount())
                   if not self.row_filtered(row))

    # ------------------------------------------------------------- freeze

    def freeze_panes(self) -> None:
        """Freeze the rows above and the columns left of the current cell —
        Excel's Freeze Panes."""
        model = self.sheet_model()
        current = self.currentIndex()
        if model is None:
            return
        row = current.row() if current.isValid() else 0
        col = current.column() if current.isValid() else 0
        model.set_freeze(row, col)

    def freeze_top_row(self) -> None:
        model = self.sheet_model()
        if model is not None:
            model.set_freeze(1, 0)

    def freeze_first_column(self) -> None:
        model = self.sheet_model()
        if model is not None:
            model.set_freeze(0, 1)

    def unfreeze(self) -> None:
        model = self.sheet_model()
        if model is not None:
            model.set_freeze(0, 0)

    def _apply_freeze(self) -> None:
        model = self.sheet_model()
        rows, cols = model.freeze if model is not None else (0, 0)
        if (rows or cols) and self._frozen is None:
            from .freeze import FrozenPanes
            self._frozen = FrozenPanes(self)
        if self._frozen is not None:
            self._frozen.set_counts(rows, cols)
            self.apply_row_heights()     # the panes take the same heights
        if self._actions is not None:
            self._actions.refresh()

    def _before_reset(self) -> None:
        """Remember where the user is: a reset (a paste, a sort, an insert,
        an undo) otherwise drops the current cell and the selection, and
        the next paste or command would land at A1."""
        current = self.currentIndex()
        selection = self.selectionModel()
        self._kept_place = (
            (current.row(), current.column()) if current.isValid() else None,
            [(r.top(), r.left(), r.bottom(), r.right())
             for r in selection.selection()] if selection else [])

    def _restore_place(self) -> None:
        kept = getattr(self, "_kept_place", None)
        self._kept_place = None
        model = self.sheet_model()
        selection = self.selectionModel()
        if not kept or model is None or selection is None:
            return
        rows, cols = model.rowCount(), model.columnCount()
        if not rows or not cols:
            return
        from PySide6.QtCore import QItemSelection, QItemSelectionModel
        current, ranges = kept
        chosen = QItemSelection()
        for top, left, bottom, right in ranges:
            if top >= rows or left >= cols:
                continue
            chosen.select(model.index(top, left),
                          model.index(min(bottom, rows - 1),
                                      min(right, cols - 1)))
        if current is not None:
            index = model.index(min(current[0], rows - 1),
                                min(current[1], cols - 1))
            selection.setCurrentIndex(index, QItemSelectionModel.NoUpdate)
        if not chosen.isEmpty():
            selection.select(chosen, QItemSelectionModel.ClearAndSelect)

    def _after_reset(self) -> None:
        self._restore_place()
        self._reapply_filter()
        self._folded_rows = frozenset()
        self._apply_outline()
        self._apply_freeze()
        self._shown_hidden_rows = frozenset()
        self._apply_hidden()
        self._sized_rows = set()
        self.apply_row_heights()

    @property
    def frozen_panes(self):
        return self._frozen

    def edit(self, index, trigger=None, event=None):
        """A cell under a frozen pane is edited in the pane — an editor
        opened here would sit behind it, out of sight."""
        if trigger is None:
            return super().edit(index)
        if self._frozen is not None:
            pane = self._frozen.pane_for(index)
            if pane is not None:
                return pane.edit(index, trigger, event)
        return super().edit(index, trigger, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._frozen is not None:
            self._frozen.relayout()

    def updateGeometries(self) -> None:
        super().updateGeometries()
        if self._frozen is not None:
            self._frozen.relayout()

    def moveCursor(self, action, modifiers):
        """With panes frozen, the arrow keys still walk the whole grid —
        Qt's own would skip the frozen rows, which are hidden here."""
        if self._frozen is None or not self._frozen.active:
            return super().moveCursor(action, modifiers)
        steps = {QAbstractItemView.MoveUp: (-1, 0),
                 QAbstractItemView.MoveDown: (1, 0),
                 QAbstractItemView.MoveLeft: (0, -1),
                 QAbstractItemView.MoveRight: (0, 1),
                 QAbstractItemView.MoveNext: (0, 1),
                 QAbstractItemView.MovePrevious: (0, -1)}
        model = self.sheet_model()
        current = self.currentIndex()
        if action not in steps or model is None or not current.isValid():
            return super().moveCursor(action, modifiers)
        drow, dcol = steps[action]
        row, col = current.row(), current.column()
        while True:
            row, col = row + drow, col + dcol
            if not (0 <= row < model.rowCount()
                    and 0 <= col < model.columnCount()):
                return current
            if not self.row_filtered(row):
                return model.index(row, col)

    def scrollTo(self, index, hint=QAbstractItemView.EnsureVisible) -> None:
        """Frozen cells are always in view; scroll for the rest so a cell
        never ends up hidden in under a frozen pane."""
        if self._frozen is not None and self._frozen.active:
            index = self._frozen.scroll_target(index)
            if index is None:
                return
        super().scrollTo(index, hint)
