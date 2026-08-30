"""Read-only data tables you can copy out of.

The sheet page has had a proper clipboard for a while — TSV for anything,
HTML for Excel's rich paste, and an internal format so formulas survive an
in-app round trip. The *data* tables did not: the views on node cards,
dashboard tiles and the inspector were plain QTableViews, and Qt gives those
no copy handling whatsoever. Ctrl+C did nothing, and the column names — the
thing you most want when the destination is a spreadsheet — could not be
got out at all.

One subclass serves all four places rather than four sets of key handling.
It puts both flavours on the clipboard at once, so a text editor gets tab-
separated values and Excel gets a real table.

Values are taken from `Qt.EditRole`, falling back to `Qt.DisplayRole`. That
distinction is the whole reason a copy is not just a screen scrape: the
display rounds floats to six significant figures so a column reads cleanly,
and pasting those into a spreadsheet would silently discard precision from
every number in the table.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics, QGuiApplication, QKeySequence
from PySide6.QtWidgets import QMenu, QMessageBox, QTableView

from .spreadsheet.clipboard import block_to_html, block_to_tsv

# Above this, copying the whole table is worth a confirmation: a few million
# cells is a string of hundreds of megabytes and a noticeable pause, and
# nobody means to do it by mistake.
CONFIRM_ROWS = 50_000

# Column-fit bounds for the read-only view. A column is sized to the wider of
# its header and its visible content, then held between these: MIN keeps a
# column of short values wide enough to still show its name, MAX stops one
# long value or a long header from eating the whole viewport.
MIN_COL_WIDTH = 52
MAX_COL_WIDTH = 360
# How many of the paged-in rows the content measure samples. The model is
# lazy (500-row pages), and measuring every cell through the item delegate
# costs ~190 ms for a wide frame — far too much to spend on every graph run
# for every table card. A sample of the first rows sizes a column well
# enough; a stray wide value further down is a manual drag away.
FIT_SAMPLE_ROWS = 50


def cell_text(index) -> str:
    """One cell as it should land on the clipboard."""
    value = index.data(Qt.EditRole)
    if value is None:
        value = index.data(Qt.DisplayRole)
    return "" if value is None else str(value)


def headers_for(model, columns: list[int]) -> list[str]:
    return [str(model.headerData(col, Qt.Horizontal, Qt.DisplayRole) or "")
            for col in columns]


def selection_block(view: QTableView, with_headers: bool) -> list[list[str]]:
    """The selected cells as a rectangle of strings.

    A gappy selection is compacted to the rows and columns that were
    actually selected, so picking rows 1 and 4 copies them next to each
    other rather than dragging along the rows between. Cells inside that
    grid which were not selected come out blank. This is what a spreadsheet
    does, and the alternative — refusing — is an error message about
    something the user cannot see they did.
    """
    indexes = view.selectionModel().selectedIndexes() if view.selectionModel() else []
    if not indexes:
        return []
    rows = sorted({i.row() for i in indexes})
    columns = sorted({i.column() for i in indexes})
    model = view.model()
    picked = {(i.row(), i.column()): cell_text(i) for i in indexes}
    block = [[picked.get((row, col), "") for col in columns] for row in rows]
    if with_headers:
        block.insert(0, headers_for(model, columns))
    return block


def whole_block(view: QTableView, with_headers: bool = True) -> list[list[str]]:
    """Every row of the model, headers included.

    Goes to the source frame when the model exposes one, because the model
    itself only knows about the rows it has paged in — copying "the whole
    table" off a lazily loaded view would otherwise hand back the first
    five hundred rows and say nothing about it.
    """
    model = view.model()
    if model is None:
        return []
    frame = getattr(model, "dataframe", None)
    if callable(frame):
        return _frame_block(frame(), with_headers)
    columns = list(range(model.columnCount()))
    block = [[cell_text(model.index(row, col)) for col in columns]
             for row in range(model.rowCount())]
    if with_headers:
        block.insert(0, headers_for(model, columns))
    return block


def _frame_block(df, with_headers: bool) -> list[list[str]]:
    block = [["" if v is None else str(v) for v in row]
             for row in df.astype(object).where(df.notna(), None).values.tolist()]
    if with_headers:
        block.insert(0, [str(c) for c in df.columns])
    return block


def put_on_clipboard(block: list[list[str]]) -> bool:
    """Both formats at once. False when there was nothing to copy."""
    if not block:
        return False
    from PySide6.QtCore import QMimeData

    data = QMimeData()
    data.setText(block_to_tsv(block))
    data.setHtml(block_to_html(block))
    clipboard = QGuiApplication.clipboard()
    if clipboard is None:
        return False
    clipboard.setMimeData(data)
    return True


def full_row_count(view: QTableView) -> int:
    model = view.model()
    if model is None:
        return 0
    frame = getattr(model, "dataframe", None)
    return len(frame()) if callable(frame) else model.rowCount()


class DataTableView(QTableView):
    """A read-only table that answers Ctrl+C and offers a copy menu.

    Ctrl+C on a selection copies that selection, and includes the column
    names when the selection spans whole columns — selecting three cells in
    the middle of a frame does not want a header row, and selecting a
    column plainly does. With nothing selected it copies the whole table,
    headers and all, which is the case the menu is really there for.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

    # ----------------------------------------------------- column widths

    def setModel(self, model) -> None:
        """Set the model and fit the columns to it.

        A plain QTableView does no auto-sizing at all, so every column here
        sat at Qt's 100 px default — narrower than many headers, and the
        header is the thing you most want intact when the table is headed
        for a spreadsheet. Fitting on setModel is the one place all four
        callers (node cards, dashboard tiles, the inspector, the spec view)
        pass through.
        """
        super().setModel(model)
        if model is not None and model.columnCount() > 0:
            self.fit_columns_to_data()

    def fit_columns_to_data(self) -> None:
        """Size each column to the wider of its header and its sampled
        content, clamped to [MIN_COL_WIDTH, MAX_COL_WIDTH]."""
        model = self.model()
        if model is None:
            return
        header = self.horizontalHeader()
        metrics = QFontMetrics(self.font())
        rows = min(model.rowCount(), FIT_SAMPLE_ROWS)
        for col in range(model.columnCount()):
            width = header.sectionSizeHint(col)
            for row in range(rows):
                text = model.data(model.index(row, col), Qt.DisplayRole)
                if text:
                    width = max(width, metrics.horizontalAdvance(str(text)) + 16)
            self.setColumnWidth(
                col, max(MIN_COL_WIDTH, min(width, MAX_COL_WIDTH)))

    def keyPressEvent(self, event) -> None:
        """Ctrl+C here rather than through a QShortcut.

        A shortcut would be the obvious way and does not work: the table on
        a node card lives inside a QGraphicsProxyWidget, and an embedded
        widget is not in the window focus chain that Qt matches shortcuts
        against — so the shortcut silently never fires on exactly the table
        people reach for first. Key events do arrive, because the canvas
        view forwards them once a proxy widget has focus.
        """
        if event.matches(QKeySequence.Copy):
            self.copy_selection()
            event.accept()
            return
        if event.matches(QKeySequence.SelectAll):
            self.selectAll()
            event.accept()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------- copying

    def _selection_spans_whole_columns(self) -> bool:
        model = self.selectionModel()
        if model is None or self.model() is None:
            return False
        rows = {i.row() for i in model.selectedIndexes()}
        return len(rows) >= self.model().rowCount() > 0

    def copy_selection(self) -> bool:
        """Ctrl+C: the selection, or the whole table when there is none."""
        model = self.selectionModel()
        if model is None or not model.hasSelection():
            return self.copy_all()
        return put_on_clipboard(
            selection_block(self, self._selection_spans_whole_columns()))

    def copy_selection_with_headers(self) -> bool:
        model = self.selectionModel()
        if model is None or not model.hasSelection():
            return self.copy_all()
        return put_on_clipboard(selection_block(self, True))

    def copy_all(self) -> bool:
        rows = full_row_count(self)
        if rows > CONFIRM_ROWS and not self._confirm_large(rows):
            return False
        return put_on_clipboard(whole_block(self, True))

    def _confirm_large(self, rows: int) -> bool:
        answer = QMessageBox.question(
            self, "Copy whole table",
            f"This table has {rows:,} rows. Copying all of it may take a "
            f"moment and use a lot of memory.\n\nCopy anyway?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    # ---------------------------------------------------------------- menu

    def build_menu(self) -> QMenu:
        menu = QMenu(self)
        has_selection = (self.selectionModel() is not None
                         and self.selectionModel().hasSelection())
        copy = menu.addAction("Copy")
        copy.setShortcut(QKeySequence.Copy)
        copy.setEnabled(has_selection)
        copy.triggered.connect(self.copy_selection)

        with_headers = menu.addAction("Copy with Column Names")
        with_headers.setEnabled(has_selection)
        with_headers.triggered.connect(self.copy_selection_with_headers)

        menu.addSeparator()
        everything = menu.addAction("Copy Whole Table")
        everything.setEnabled(self.model() is not None
                              and self.model().columnCount() > 0)
        everything.triggered.connect(self.copy_all)

        select_all = menu.addAction("Select All")
        select_all.setShortcut(QKeySequence.SelectAll)
        select_all.setEnabled(everything.isEnabled())
        select_all.triggered.connect(self.selectAll)
        return menu

    def _show_menu(self, pos) -> None:
        self.build_menu().exec(self.viewport().mapToGlobal(pos))
