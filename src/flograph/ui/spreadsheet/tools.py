"""The chrome that turns a bare grid into a spreadsheet: the toolbar, the
formula bar, and the function reference behind the fx button.

These started out inside the pop-out editor, which was the only place a
Table could be worked on properly. Dashboard pages are used for data entry,
so the same tools have to be available where the data is actually typed —
and one implementation shared between the two is what keeps a formula
behaving identically wherever it is written.

Everything here drives a SpreadsheetView and its SheetModel and knows
nothing else: no graph, no undo stack, no dashboard. Hosts decide what
committing means by connecting to the model's ``sheet_edited``.
"""
from __future__ import annotations

import html
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QTextBrowser, QToolBar, QToolButton, QVBoxLayout,
                               QWidget)

from flograph.core.sheet import FUNCTION_HELP, cell_name

from .. import theme

from .completion import FormulaCompleter
from .model import SheetModel
from .view import SpreadsheetView


def reference_html() -> str:
    """The fx button's help page: references, operators, and the function
    table generated from core's FUNCTION_HELP."""
    rows = "".join(
        f"<tr><td><b>{html.escape(signature)}</b></td>"
        f"<td>{html.escape(description)}</td>"
        f"<td><code>{html.escape(example)}</code></td></tr>"
        for _name, signature, description, example in FUNCTION_HELP)
    return f"""
<h3>Formulas</h3>
<p>Start a cell with <code>=</code> to enter a formula. Reference cells
by column letter and row number (<code>A1</code>, <code>B3</code>); row 1
is the first data row. Pin a reference with <code>$</code>
(<code>$A$1</code>) so paste and fill-down don't shift it, and use
<code>A1:B5</code> ranges inside functions.</p>
<p><b>Reference columns by name</b> with <code>[@Price]</code> — this
row's value in the "Price" column — or <code>[Price]</code> for the whole
column inside aggregates: <code>=[@Price]*[@Qty]</code>,
<code>=SUM([Total])</code>. Names may contain spaces
(<code>[@value x]</code>) and match case-insensitively. Named references
don't shift on paste or fill-down, follow the column when you rename it,
and keep working when columns move — prefer them over letters whenever a
column has a meaningful name.</p>
<p><b>Operators:</b> <code>+ &nbsp;- &nbsp;* &nbsp;/ &nbsp;^</code> (power),
<code>&amp;</code> (join text), <code>%</code> (percent, <code>50%</code> is 0.5),
and comparisons <code>= &nbsp;&lt;&gt; &nbsp;&lt; &nbsp;&lt;= &nbsp;&gt; &nbsp;&gt;=</code>.</p>
<p>Errors show in the cell (<code>#DIV/0!</code>, <code>#REF!</code>,
<code>#CYCLE!</code>, …) — hover for the reason.</p>
<h3>Functions</h3>
<table cellspacing="0" cellpadding="4" border="0">
<tr><th align="left">Function</th><th align="left">What it does</th>
<th align="left">Example</th></tr>
{rows}
</table>
"""


class FormulaReferenceDialog(QDialog):
    """Non-modal so it can stay open beside the sheet being written."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Formula reference")
        self.setModal(False)
        self.resize(560, 520)
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setHtml(reference_html())
        layout.addWidget(browser)


class SheetToolbar(QToolBar):
    """Row/column/sort/fill actions for a SpreadsheetView.

    A QToolBar rather than a row of buttons because it collapses what does
    not fit into an overflow menu on its own — the same toolbar has to work
    across a 560px dashboard tile and a maximized 4K page.
    """

    def __init__(self, view: SpreadsheetView, parent=None) -> None:
        super().__init__(parent)
        self.setMovable(False)
        self.setFloatable(False)
        self._view = view

        model = view.sheet_model()

        def row() -> int:
            index = view.currentIndex()
            return index.row() if index.isValid() else 0

        def col() -> int:
            index = view.currentIndex()
            return index.column() if index.isValid() else 0

        self.addAction("+ Row above", lambda: model.insert_rows_at(row()))
        self.addAction("+ Row below", lambda: model.insert_rows_at(row() + 1))
        self.addAction("− Row", lambda: model.remove_rows_at([row()]))
        self.addSeparator()
        self.addAction("+ Column", lambda: model.insert_columns_at(col() + 1))
        self.addAction("− Column", lambda: model.remove_columns_at([col()]))
        self.addSeparator()
        self.addAction("Fill down", view.fill_down_selection)
        self.addAction("Fit columns", lambda: view.autosize_columns())
        self.addAction("Sort ↑", lambda: model.sort_by(col(), True))
        self.addAction("Sort ↓", lambda: model.sort_by(col(), False))
        self.addSeparator()
        copy_headers = self.addAction("Copy w/ Headers",
                                      view.copy_selection_with_headers)
        copy_headers.setToolTip(
            "Copy the selection to the clipboard with column headers on "
            "top — plain Ctrl+C leaves them out. Copies the whole table "
            "if nothing is selected")


class FormulaBar(QWidget):
    """Cell reference, the raw source of the current cell, and fx.

    Shows what a cell *is* rather than what it computes to, which is the
    only way to read a formula without first entering the cell — and the
    difference between a sheet you can audit and one you can only trust.
    """

    def __init__(self, view: SpreadsheetView, parent=None) -> None:
        super().__init__(parent)
        self._view = view
        self._reference: Optional[QDialog] = None

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        fx = QToolButton(text="fx")
        fx.setAutoRaise(True)
        fx.setToolTip("Show available formulas and examples")
        fx.clicked.connect(self.show_reference)

        self.cell_label = QLabel("A1")
        self.cell_label.setMinimumWidth(40)
        self.cell_label.setAlignment(Qt.AlignCenter)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText(
            "value or =formula — click fx for the function list")
        self.edit.editingFinished.connect(self.commit)
        FormulaCompleter(self.edit, self._column_names)

        row.addWidget(fx)
        row.addWidget(self.cell_label)
        row.addWidget(self.edit, 1)

        selection = view.selectionModel()
        if selection is not None:
            selection.currentChanged.connect(self.sync)
        self.sync(view.currentIndex())

    def _model(self) -> Optional[SheetModel]:
        return self._view.sheet_model()

    def _column_names(self):
        model = self._model()
        return model.sheet.column_names() if model is not None else []

    def show_reference(self) -> None:
        if self._reference is None:
            self._reference = FormulaReferenceDialog(self)
        self._reference.show()
        self._reference.raise_()
        self._reference.activateWindow()

    def sync(self, current=None, _previous=None) -> None:
        """Point the bar at a cell. Called on every selection change, and by
        hosts after an undo/redo has replaced the sheet underneath."""
        if current is None:
            current = self._view.currentIndex()
        model = self._model()
        if model is None or current is None or not current.isValid():
            self.cell_label.setText("")
            self.edit.clear()
            return
        self.cell_label.setText(cell_name(current.row(), current.column()))
        self.edit.setText(model.cell_source(current.row(), current.column()))

    def commit(self) -> None:
        current = self._view.currentIndex()
        model = self._model()
        if model is None or not current.isValid():
            return
        text = self.edit.text()
        if text != model.cell_source(current.row(), current.column()):
            model.setData(current, text, Qt.EditRole)
        self._view.setFocus()


class SheetWorkbench(QWidget):
    """Toolbar + formula bar + grid over a model someone else owns.

    The unit that gets embedded wherever a Table is edited in earnest: the
    pop-out editor, a dashboard tile, and a maximized dashboard page. The
    model is passed in rather than built here, so a maximized page can put a
    second workbench on the *same* model as the tile behind it and both stay
    in step without either knowing about the other.
    """

    def __init__(self, model: SheetModel, parent=None,
                 styled: bool = True) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.view = SpreadsheetView(self)
        self.view.setModel(model)
        if styled:
            # through style_scroll_area, never setStyleSheet -- a stylesheet
            # applied directly costs the grid its scroll-blitting
            theme.style_scroll_area(self.view, theme.grid_stylesheet())
        self.toolbar = SheetToolbar(self.view, self)
        self.formula_bar = FormulaBar(self.view, self)

        layout.addWidget(self.toolbar)
        layout.addWidget(self.formula_bar)
        layout.addWidget(self.view, 1)

    def model(self) -> Optional[SheetModel]:
        return self.view.sheet_model()

    def sync(self) -> None:
        """Re-read the current cell — after an external change replaced the
        sheet (undo, a run refreshing a linked table)."""
        self.formula_bar.sync()
