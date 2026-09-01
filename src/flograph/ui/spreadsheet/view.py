"""SpreadsheetView: Excel-style grid interaction, shared by the canvas
card and the pop-out editor.

Keyboard: Enter commits and moves down, Tab moves right, typing replaces,
F2 edits in place, Delete clears, Ctrl+D fills down, Ctrl+C/X/V work on
rectangular selections (TSV + HTML + an internal format that keeps
formulas and shifts their relative references on paste). Header context
menus insert/delete/rename/retype/sort; double-click a column header to
rename it.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (QEvent, QItemSelectionModel, QMimeData, QSettings,
                            Qt, QTimer)
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QAbstractItemDelegate, QAbstractItemView,
                               QApplication, QInputDialog, QMenu, QTableView)

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


class SpreadsheetView(QTableView):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
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

        # click a header to sort it (asc -> desc -> clear); the cycler's
        # own timer keeps a sort click apart from a rename double-click
        from ..table_sort import HeaderSortCycler
        self._presort_rows: Optional[list[list[str]]] = None
        self._sorting = False
        self._sort_cycler = HeaderSortCycler(
            header, can_sort=lambda: (self.sheet_model() is not None
                                      and not self.sheet_model().read_only))
        self._sort_cycler.sortRequested.connect(self._header_sort)

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
        super().setModel(model)
        self._forget_sort()
        if isinstance(model, SheetModel):
            model.modelReset.connect(self._sync_column_widths)
            model.dataChanged.connect(self._maybe_autofit)
            model.modelReset.connect(self._forget_sort)
            model.sheet_edited.connect(self._forget_sort)
            self._sync_column_widths()

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
        self._sort_cycler.reset()

    def clear_sort(self) -> None:
        """Menu entry point: restore the pre-sort row order."""
        self._header_sort(0, "clear")
        self._sort_cycler.reset()

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
        self._applying_widths = True
        try:
            for col in cols:
                self.resizeColumnToContents(col)
        finally:
            self._applying_widths = False
        if persist:
            model.set_column_widths(
                {col: self.columnWidth(col) for col in cols})

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
        return (event.key() == Qt.Key_D
                and event.modifiers() & Qt.ControlModifier)

    def event(self, event) -> bool:
        # claim these keys before the window-level QActions (Duplicate,
        # Rename Node, canvas copy/paste) can swallow them
        if event.type() == QEvent.ShortcutOverride and self._owns_shortcut(event):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:
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
        if event.key() == Qt.Key_D and event.modifiers() & Qt.ControlModifier:
            self.fill_down_selection()
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

    def rename_column(self, col: int) -> None:
        model = self.sheet_model()
        if model is None or not 0 <= col < model.columnCount() or model.read_only:
            return
        current = model.sheet.columns[col].name
        name, ok = QInputDialog.getText(
            None, "Rename column", "Column name", text=current)
        if ok and name and name != current:
            model.rename_column(col, name)

    def _column_menu(self, pos) -> None:
        model = self.sheet_model()
        col = self.horizontalHeader().logicalIndexAt(pos)
        if model is None or col < 0:
            return
        cols = self._selected_sections(col, pick_row=False)
        menu = QMenu(self)
        if getattr(model, "read_only", False):
            # linked mode: layout tweaks only, the data belongs upstream
            menu.addAction("Resize to content",
                           lambda: self.autosize_columns(cols))
            menu.addAction("Resize all columns to content",
                           lambda: self.autosize_columns())
            menu.exec(self.horizontalHeader().mapToGlobal(pos))
            return
        menu.addAction("Rename…", lambda: self.rename_column(col))
        type_menu = menu.addMenu("Type")
        current_type = model.column_type(col)
        for col_type in COLUMN_TYPES:
            action = type_menu.addAction(col_type)
            action.setCheckable(True)
            action.setChecked(col_type == current_type)
            action.triggered.connect(
                lambda _=False, t=col_type: model.set_column_type(col, t))
        menu.addSeparator()
        menu.addAction("Insert column left",
                       lambda: model.insert_columns_at(col))
        menu.addAction("Insert column right",
                       lambda: model.insert_columns_at(col + 1))
        label = "Delete columns" if len(cols) > 1 else "Delete column"
        menu.addAction(label, lambda: model.remove_columns_at(cols))
        menu.addSeparator()
        fit_label = ("Resize columns to content" if len(cols) > 1
                     else "Resize to content")
        menu.addAction(fit_label, lambda: self.autosize_columns(cols))
        menu.addAction("Resize all columns to content",
                       lambda: self.autosize_columns())
        menu.addSeparator()
        menu.addAction("Sort ascending",
                       lambda: self._header_sort(col, "asc"))
        menu.addAction("Sort descending",
                       lambda: self._header_sort(col, "desc"))
        clear = menu.addAction("Clear sort", self.clear_sort)
        clear.setEnabled(self.has_active_sort)
        menu.exec(self.horizontalHeader().mapToGlobal(pos))

    def _row_menu(self, pos) -> None:
        model = self.sheet_model()
        row = self.verticalHeader().logicalIndexAt(pos)
        if model is None or row < 0 or model.read_only:
            return
        rows = self._selected_sections(row, pick_row=True)
        menu = QMenu(self)
        menu.addAction("Insert row above", lambda: model.insert_rows_at(row))
        menu.addAction("Insert row below",
                       lambda: model.insert_rows_at(row + 1))
        label = "Delete rows" if len(rows) > 1 else "Delete row"
        menu.addAction(label, lambda: model.remove_rows_at(rows))
        menu.addSeparator()
        menu.addAction("Promote to header",
                       lambda: model.promote_row_to_header(row))
        menu.exec(self.verticalHeader().mapToGlobal(pos))
