"""CSV editor that retains text values and requires explicit decoding."""
import csv
import io
import re
import math

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QAction, QKeySequence, QTextDocument, QTextOption, QAbstractTextDocumentLayout, QPalette

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QDialogButtonBox, QMessageBox, QCheckBox, QMenu, QInputDialog, QStyledItemDelegate, QStyleOptionViewItem, QStyle, QApplication,
)


class CsvTextDelegate(QStyledItemDelegate):
    """Measure and draw with one wrapping policy, including unbroken tokens."""
    def __init__(self, view):
        super().__init__(view)
        self.view = view

    def document(self, option, width):
        document = QTextDocument()
        document.setDocumentMargin(0)
        document.setDefaultFont(option.font)
        text_option = document.defaultTextOption()
        text_option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        document.setDefaultTextOption(text_option)
        document.setPlainText(option.text)
        document.setTextWidth(max(1, width))
        return document

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        if not self.view.wordWrap():
            return size
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        document = self.document(opt, self.view.columnWidth(index.column()) - 9)
        return QSize(size.width(), math.ceil(document.size().height()) + 4)

    def paint(self, painter, option, index):
        if not self.view.wordWrap():
            return super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        document = self.document(opt, opt.rect.width() - 8)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        context = QAbstractTextDocumentLayout.PaintContext()
        context.palette = opt.palette
        if opt.state & QStyle.State_Selected:
            context.palette.setColor(QPalette.Text, opt.palette.color(QPalette.HighlightedText))
        painter.save()
        painter.setClipRect(opt.rect)
        painter.translate(opt.rect.left() + 4, opt.rect.top() + 2)
        document.documentLayout().draw(painter, context)
        painter.restore()


class ManagedCsvEditor(QDialog):
    def __init__(self, name, data, metadata=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit CSV — {name}")
        self.resize(900, 600)
        self.original = data
        self.data = data
        self.initial_rows = None
        self.loaded_settings = None
        metadata = metadata or {}
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Edit cells as text. Right-click cells or headers for commands."))
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Encoding"))
        self.encoding = QComboBox(self)
        self.encoding.setEditable(True)
        self.encoding.addItems(["utf-8", "utf-8-sig", "latin-1", "cp1252", "utf-16"])
        self.encoding.setCurrentText(metadata.get("encoding") or ("utf-8-sig" if data.startswith(b"\xef\xbb\xbf") else "utf-8"))
        bar.addWidget(self.encoding)
        bar.addWidget(QLabel("Separator"))
        self.separator = QLineEdit(metadata.get("separator") or ("\\t" if name.lower().endswith(".tsv") else ","), self)
        self.separator.setMaximumWidth(80)
        bar.addWidget(self.separator)
        reload = QPushButton("Reload", self)
        reload.clicked.connect(self.reload)
        bar.addWidget(reload)
        self.wrap_text = QCheckBox("Wrap text", self)
        bar.addWidget(self.wrap_text)
        layout.addLayout(bar)
        self.message = QLabel(self)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.grid = QTableWidget(self)
        layout.addWidget(self.grid)
        self.grid.setWordWrap(False)
        self.grid.setItemDelegate(CsvTextDelegate(self.grid))
        self.compact_row_height = self.grid.fontMetrics().height() + 5
        self.grid.verticalHeader().setMinimumSectionSize(self.compact_row_height)
        self.grid.verticalHeader().setDefaultSectionSize(self.compact_row_height)
        self.grid.horizontalHeader().setResizeContentsPrecision(-1)
        self._loading = False
        self._changed_columns = set()
        self._column_timer = QTimer(self)
        self._column_timer.setSingleShot(True)
        self._column_timer.setInterval(80)
        self._column_timer.timeout.connect(self.fit_changed_columns)
        self._row_timer = QTimer(self)
        self._row_timer.setSingleShot(True)
        self._row_timer.setInterval(80)
        self._row_timer.timeout.connect(self.fit_rows)
        self.grid.itemChanged.connect(self.schedule_column_fit)
        self.grid.horizontalHeader().sectionResized.connect(
            lambda *_: self._row_timer.start() if self.wrap_text.isChecked() else None)
        self.wrap_text.toggled.connect(self.set_wrap)
        self.search_dialog = QDialog(self)
        self.search_dialog.setWindowTitle("Find and Replace")
        search_layout = QVBoxLayout(self.search_dialog)
        search = QHBoxLayout()
        search.addWidget(QLabel("Find"))
        self.find_text = QLineEdit(self.search_dialog)
        self.find_text.setPlaceholderText("Text to find")
        search.addWidget(self.find_text)
        search_layout.addLayout(search)
        replace_row = QHBoxLayout()
        replace_row.addWidget(QLabel("Replace with"))
        self.replace_text = QLineEdit(self.search_dialog)
        replace_row.addWidget(self.replace_text)
        search_layout.addLayout(replace_row)
        options = QHBoxLayout()
        self.match_case = QCheckBox("Match case", self.search_dialog)
        self.whole_cell = QCheckBox("Whole cell", self.search_dialog)
        options.addWidget(self.match_case)
        options.addWidget(self.whole_cell)
        search_layout.addLayout(options)
        self.commands = {}
        for key, label, callback, shortcut in [
                ("find_dialog", "Find and Replace…", self.show_find, "Ctrl+F"),
                ("find", "Find next", self.find_next, "F3"),
                ("replace", "Replace", self.replace_current, ""),
                ("replace_all", "Replace all", self.replace_all, ""),
                ("add_row", "Add row", lambda: self.grid.insertRow(self.grid.rowCount()), ""),
                ("add_column", "Add column…", self.add_column, ""),
                ("remove_rows", "Remove selected rows", self.remove_rows, ""),
                ("remove_columns", "Remove selected columns", self.remove_columns, ""),
                ("rename", "Rename column…", self.rename_column, "")]:
            action = QAction(label, self)
            action.triggered.connect(callback)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            self.addAction(action)
            self.commands[key] = action
        self.search_status = QLabel(self.search_dialog)
        search_layout.addWidget(self.search_status)
        buttons = QHBoxLayout()
        for key in ("find", "replace", "replace_all"):
            button = QPushButton(self.commands[key].text(), self.search_dialog)
            button.clicked.connect(self.commands[key].trigger)
            buttons.addWidget(button)
            self.search_dialog.addAction(self.commands[key])
        close = QPushButton("Close", self.search_dialog)
        close.clicked.connect(self.search_dialog.hide)
        buttons.addWidget(close)
        search_layout.addLayout(buttons)
        self.finished.connect(self.search_dialog.hide)
        self.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(lambda point: self.context_menu("cells", point))
        self.grid.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.horizontalHeader().customContextMenuRequested.connect(lambda point: self.context_menu("columns", point))
        self.grid.verticalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        self.grid.verticalHeader().customContextMenuRequested.connect(lambda point: self.context_menu("rows", point))
        replace_action = QAction(self)
        replace_action.setShortcut(QKeySequence("Ctrl+H"))
        replace_action.triggered.connect(lambda: self.show_find(replace=True))
        self.addAction(replace_action)
        self.find_text.returnPressed.connect(self.find_next)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        self.buttons.accepted.connect(self.save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        if not metadata.get("separator"):
            try:
                sample = data.decode(self.encoding.currentText())[:65536]
                delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
                self.separator.setText("\\t" if delimiter == "\t" else delimiter)
            except (UnicodeError, LookupError, csv.Error):
                # Sniffer sometimes rejects quoted multiline fields. Try
                # consistent multi-column parses before leaving the default.
                try:
                    sample = data.decode(self.encoding.currentText())[:65536]
                    candidates = []
                    for delimiter in (",", ";", "\t", "|"):
                        try:
                            rows = list(csv.reader(io.StringIO(sample, newline=""), delimiter=delimiter, strict=True))
                            widths = {len(row) for row in rows if row}
                            if len(widths) == 1 and next(iter(widths)) > 1:
                                candidates.append((next(iter(widths)), delimiter))
                        except csv.Error:
                            continue
                    if candidates:
                        delimiter = max(candidates)[1]
                        self.separator.setText("\\t" if delimiter == "\t" else delimiter)
                except (UnicodeError, LookupError):
                    pass
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self.load()

    def settings(self):
        separator = self.separator.text()
        separator = "\t" if separator == "\\t" else separator
        if len(separator) != 1:
            raise ValueError("Choose a single-character separator, or \\t for tab")
        return self.encoding.currentText().strip(), separator

    def rows(self):
        if not self.grid.columnCount():
            return [[]] if getattr(self, "_empty_header", False) and not self.grid.rowCount() else []
        headers = [self.grid.horizontalHeaderItem(c).text() if self.grid.horizontalHeaderItem(c) else ""
                   for c in range(self.grid.columnCount())]
        data = [[self.grid.item(r, c).text() if self.grid.item(r, c) else ""
                 for c in range(self.grid.columnCount())] for r in range(self.grid.rowCount())]
        return [headers, *data]

    def load(self):
        try:
            encoding, separator = self.settings()
            text = self.original.decode(encoding)
            rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=separator, strict=True))
            width = max((len(row) for row in rows), default=0)
            rows = [row + [""] * (width - len(row)) for row in rows]
            self._empty_header = bool(rows and not rows[0])
            self.grid.setRowCount(max(0, len(rows) - 1))
            self.grid.setColumnCount(width)
            if rows:
                self.grid.setHorizontalHeaderLabels(rows[0])
            self._loading = True
            for r, row in enumerate(rows[1:]):
                for c, value in enumerate(row):
                    self.grid.setItem(r, c, QTableWidgetItem(value))
            self._loading = False
            self.fit_columns()
            self.initial_rows = rows
            self.loaded_settings = encoding, separator
            self.message.setText("Changes are stored inside the project when you save this editor, and support Undo.")
            self.buttons.button(QDialogButtonBox.Save).setEnabled(True)
        except (UnicodeError, LookupError, ValueError, csv.Error) as exc:
            self.message.setText(f"Cannot read CSV: {exc}. Choose the encoding/separator and press Reload.")
            self.buttons.button(QDialogButtonBox.Save).setEnabled(False)

    def reload(self):
        if self.initial_rows is not None and self.rows() != self.initial_rows:
            if QMessageBox.question(self, "Discard CSV edits?", "Reload the original file and discard your edits?") != QMessageBox.Yes:
                return
        self.load()

    def fit_columns(self):
        self._changed_columns = set(range(self.grid.columnCount()))
        self.fit_changed_columns()

    def schedule_column_fit(self, item):
        if not self._loading:
            self._changed_columns.add(item.column())
            self._column_timer.start()

    def fit_changed_columns(self):
        columns, self._changed_columns = self._changed_columns, set()
        for column in sorted(columns):
            if column < self.grid.columnCount():
                self.grid.resizeColumnToContents(column)
                self.grid.setColumnWidth(column, max(50, min(480, self.grid.columnWidth(column))))
        if self.wrap_text.isChecked():
            self._row_timer.start()

    def set_wrap(self, enabled):
        self.grid.setWordWrap(enabled)
        self.grid.setTextElideMode(Qt.ElideNone if enabled else Qt.ElideRight)
        if enabled:
            self.fit_rows()
        else:
            self._row_timer.stop()
            height = self.compact_row_height
            for row in range(self.grid.rowCount()):
                self.grid.setRowHeight(row, height)

    def fit_rows(self):
        if self.wrap_text.isChecked():
            self.grid.resizeRowsToContents()

    def context_menu(self, kind, point):
        if kind == "columns":
            host = self.grid.horizontalHeader()
            column = host.logicalIndexAt(point)
            if column >= 0:
                if not any(index.column() == column for index in self.grid.selectedIndexes()):
                    self.grid.selectColumn(column)
                self._context_column = column
            keys = ["rename", "add_column", "remove_columns", "find_dialog", "find"]
            self.commands["rename"].setEnabled(column >= 0)
        elif kind == "rows":
            host = self.grid.verticalHeader()
            row = host.logicalIndexAt(point)
            if row >= 0 and not any(index.row() == row for index in self.grid.selectedIndexes()):
                self.grid.selectRow(row)
            keys = ["add_row", "remove_rows", "find_dialog", "find"]
        else:
            host = self.grid.viewport()
            item = self.grid.itemAt(point)
            if item is not None and not item.isSelected():
                self.grid.setCurrentItem(item)
            keys = ["find_dialog", "find", "add_row", "add_column", "remove_rows", "remove_columns"]
        menu = QMenu(self)
        for key in keys:
            menu.addAction(self.commands[key])
        menu.exec(host.mapToGlobal(point))
        menu.deleteLater()

    def add_column(self):
        name, ok = QInputDialog.getText(self, "Add CSV column", "Column name",
                                      text=f"Column {self.grid.columnCount() + 1}")
        if ok:
            column = self.grid.columnCount()
            self.grid.insertColumn(column)
            self.grid.setHorizontalHeaderItem(column, QTableWidgetItem(name))
            self._changed_columns.add(column)
            self.fit_changed_columns()

    def rename_column(self):
        column = getattr(self, "_context_column", self.grid.currentColumn())
        if column < 0 or column >= self.grid.columnCount():
            return
        header = self.grid.horizontalHeaderItem(column)
        name, ok = QInputDialog.getText(self, "Rename CSV column", "Column name",
                                      text=header.text() if header else "")
        if ok:
            self.grid.setHorizontalHeaderItem(column, QTableWidgetItem(name))
            self._changed_columns.add(column)
            self.fit_changed_columns()

    def remove_rows(self):
        for row in sorted({i.row() for i in self.grid.selectedIndexes()}, reverse=True):
            self.grid.removeRow(row)

    def remove_columns(self):
        columns = {i.column() for i in self.grid.selectedIndexes()}
        if not columns and not self.grid.rowCount() and hasattr(self, "_context_column"):
            columns.add(self._context_column)
        for column in sorted(columns, reverse=True):
            self.grid.removeColumn(column)

    def show_find(self, checked=False, *, replace=False):
        self.search_dialog.show()
        self.search_dialog.raise_()
        self.search_dialog.activateWindow()
        field = self.replace_text if replace else self.find_text
        field.setFocus()
        field.selectAll()

    def search_pattern(self):
        term = self.find_text.text()
        if not term:
            self.search_status.setText("Enter text to find")
            return None
        pattern = re.escape(term)
        if self.whole_cell.isChecked():
            pattern = r"\A" + pattern + r"\Z"
        return re.compile(pattern, 0 if self.match_case.isChecked() else re.IGNORECASE)

    def find_next(self):
        pattern = self.search_pattern()
        if pattern is None:
            return False
        columns = self.grid.columnCount()
        total = self.grid.rowCount() * columns
        current = self.grid.currentRow() * columns + self.grid.currentColumn() if self.grid.currentRow() >= 0 else -1
        for step in range(1, total + 1):
            index = (current + step) % total
            row, column = divmod(index, columns)
            item = self.grid.item(row, column)
            if item and pattern.search(item.text()):
                self.grid.setCurrentCell(row, column)
                self.grid.scrollToItem(item)
                self.search_status.setText(f"Row {row + 1}, column {column + 1}" + (" (wrapped)" if index <= current else ""))
                return True
        self.search_status.setText("No matches")
        return False

    def replace_current(self):
        pattern = self.search_pattern()
        if pattern is None:
            return
        item = self.grid.currentItem()
        if item is None or not pattern.search(item.text()):
            if not self.find_next():
                return
            item = self.grid.currentItem()
        replacement = self.replace_text.text()
        value, count = pattern.subn(lambda match: replacement, item.text(), count=1)
        item.setText(value)
        self.search_status.setText(f"{count} replacement")

    def replace_all(self):
        pattern = self.search_pattern()
        if pattern is None:
            return
        count = 0
        replacement = self.replace_text.text()
        self.grid.setUpdatesEnabled(False)
        try:
            for row in range(self.grid.rowCount()):
                for column in range(self.grid.columnCount()):
                    item = self.grid.item(row, column)
                    if item is None:
                        continue
                    value, changed = pattern.subn(lambda match: replacement, item.text())
                    if changed:
                        item.setText(value)
                        count += changed
        finally:
            self.grid.setUpdatesEnabled(True)
        self.search_status.setText(f"{count} replacements")

    def save(self):
        try:
            settings = self.settings()
            if settings != self.loaded_settings:
                raise ValueError("Press Reload after changing the encoding or separator")
            rows = self.rows()
            if rows == self.initial_rows:
                self.data = self.original
            else:
                text = io.StringIO(newline="")
                decoded = self.original.decode(settings[0])
                newline = "\r\n" if "\r\n" in decoded else "\n"
                csv.writer(text, delimiter=settings[1], lineterminator=newline).writerows(rows)
                self.data = text.getvalue().encode(settings[0])
            self.accept()
        except (UnicodeError, LookupError, ValueError, csv.Error) as exc:
            QMessageBox.warning(self, "Cannot save CSV", str(exc))
