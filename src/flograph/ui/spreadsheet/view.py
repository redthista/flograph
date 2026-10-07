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
from .delegates import SheetDelegate
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

        # A header click selects the column, as in a spreadsheet — the
        # column is then what Delete, Move and Insert act on. Sorting lives
        # on the column's ▾ button, the ribbon and the right-click menu.
        # (Read-only tables elsewhere still sort on a header click; there
        # is nothing to select a column *for* in those.)
        self._presort_rows: Optional[list[list[str]]] = None
        self._sorting = False

        self.viewport().setContextMenuPolicy(Qt.CustomContextMenu)
        self.viewport().customContextMenuRequested.connect(self._cell_menu)
        self._actions = None
        self._host = None
        self._show_formulas = False
        self._frozen = None   # freeze.FrozenPanes, made on first freeze

        rows = self.verticalHeader()
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

        # See _maybe_autofit: the automatic fit coalesces instead of running
        # once per edited cell.
        self._autofit_timer = QTimer(self)
        self._autofit_timer.setSingleShot(True)
        self._autofit_timer.setInterval(AUTOFIT_IDLE_MS)
        self._autofit_timer.timeout.connect(self._run_autofit)

    def setModel(self, model) -> None:
        old = self.sheet_model()
        if old is not None:
            old.modelReset.disconnect(self._sync_column_widths)
            old.dataChanged.disconnect(self._maybe_autofit)
            old.modelReset.disconnect(self._forget_sort)
            old.sheet_edited.disconnect(self._forget_sort)
        if old is not None:
            old.modelReset.disconnect(self._after_reset)
            old.dataChanged.disconnect(self._reapply_filter)
            old.freeze_changed.disconnect(self._apply_freeze)
        super().setModel(model)
        self._filters = {}
        self._filtered_rows = set()
        self._forget_sort()
        if isinstance(model, SheetModel):
            model.modelReset.connect(self._sync_column_widths)
            model.dataChanged.connect(self._maybe_autofit)
            model.modelReset.connect(self._forget_sort)
            model.sheet_edited.connect(self._forget_sort)
            model.modelReset.connect(self._after_reset)
            model.dataChanged.connect(self._reapply_filter)
            model.freeze_changed.connect(self._apply_freeze)
            self._sync_column_widths()
            self._apply_freeze()
        if self.selectionModel() is not None:
            self.selectionModel().selectionChanged.connect(
                self._selection_moved)
            self.selectionModel().currentChanged.connect(
                self._selection_moved)

    def sheet_model(self) -> Optional[SheetModel]:
        model = self.model()
        return model if isinstance(model, SheetModel) else None

    # ------------------------------------------------------- header sort

    def _header_sort(self, col: int, mode: str) -> None:
        """A header click resolved to a sort. asc/desc reorder the rows
        (one undo step each); clear restores the order captured before the
        first sort of this run."""
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
                model.sort_by(col, mode == "asc")
        finally:
            self._sorting = False

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
        mime = QMimeData()
        mime.setText(block_to_tsv(values))
        mime.setHtml(block_to_html(values))
        mime.setData(MIME_CELLS, encode_cells((row0, col0), sources))
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
                if (len(cells) == 1 and len(cells[0]) == 1 and rect
                        and (rect[2] > row0 or rect[3] > col0)):
                    # one copied cell over a bigger selection: replicate,
                    # shifting relative refs per target cell
                    block = [[translate(cells[0][0], r - origin[0],
                                        c - origin[1])
                              for c in range(col0, rect[3] + 1)]
                             for r in range(row0, rect[2] + 1)]
                else:
                    block = [[translate(text, row0 - origin[0],
                                        col0 - origin[1]) for text in row]
                             for row in cells]
                model.set_cells((row0, col0), block)
                return

        block = parse_paste_text(mime.text())
        if not block:
            return
        if (len(block) == 1 and len(block[0]) == 1 and rect
                and (rect[2] > row0 or rect[3] > col0)):
            block = [[block[0][0]] * (rect[3] - col0 + 1)
                     for _ in range(rect[2] - row0 + 1)]
        model.set_cells((row0, col0), block)

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
        if frozen is not None:
            frozen.relayout()
        if persist:
            model.set_column_widths(widths)

    def _autosize_from_handle(self, section: int) -> None:
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

    def closeEditor(self, editor, hint) -> None:
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

    def _selection_moved(self, *_args) -> None:
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
        """Is this row hidden by a filter? (Not the same as isRowHidden: a
        frozen row is hidden in the grid because a pane shows it.)"""
        return row in self._filtered_rows

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
        frozen_rows = self._frozen.rows if self._frozen is not None else 0
        for row in range(model.rowCount()):
            hide = row in self._filtered_rows or row < frozen_rows
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
        return model.rowCount() - len(self._filtered_rows)

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
        if self._actions is not None:
            self._actions.refresh()

    def _after_reset(self) -> None:
        self._reapply_filter()
        self._apply_freeze()

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
