"""The chrome that turns a bare grid into a spreadsheet: the ribbon (see
ribbon.py), the formula bar, and the function reference behind fx.

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
from PySide6.QtCore import QSize
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QTextBrowser, QToolButton, QVBoxLayout,
                               QWidget)

from flograph.core.sheet import FUNCTION_HELP, cell_name

from .. import theme

from .completion import FormulaCompleter
from .model import SheetModel
from .view import SpreadsheetView


def reference_html() -> str:
    """The fx button's help page: references, operators, and the function
    table generated from core's FUNCTION_HELP."""
    from flograph.core.sheet import FUNCTION_CATEGORIES
    rows = ""
    for category in FUNCTION_CATEGORIES:
        entries = sorted((e for e in FUNCTION_HELP if e[4] == category),
                         key=lambda e: e[0])
        if not entries:
            continue
        rows += (f"<tr><td colspan='3'><br><b>{html.escape(category)}</b>"
                 f"</td></tr>")
        rows += "".join(
            f"<tr><td><b>{html.escape(signature)}</b></td>"
            f"<td>{html.escape(description)}</td>"
            f"<td><code>{html.escape(example)}</code></td></tr>"
            for _name, signature, description, example, _cat in entries)
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
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(4)

        from .icons import sheet_icon
        fx = QToolButton()
        fx.setIcon(sheet_icon("fx"))
        fx.setIconSize(QSize(18, 18))
        fx.setAutoRaise(True)
        fx.setToolTip("Every function the formulas know, with examples")
        fx.clicked.connect(self.show_reference)

        # Excel's name box: which cell the bar is showing
        self.cell_label = QLabel("A1")
        self.cell_label.setMinimumWidth(52)
        self.cell_label.setAlignment(Qt.AlignCenter)
        self.cell_label.setToolTip("The selected cell — column letter and "
                                   "row number, as formulas refer to it")
        # its own dark strip, like the ribbon above it: without a background
        # of its own the window's palette shows through (light in light mode)
        self.setObjectName("formula_bar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget#formula_bar { background: #25272e;"
            " border-bottom: 1px solid #14151a; }"
            "QLabel { background: #1f2026; color: #d6d8de;"
            " border: 1px solid #3a3d47; border-radius: 3px;"
            " padding: 2px 4px; font-size: 8.5pt; }"
            "QLineEdit { background: #1f2026; color: #e5e7eb;"
            " border: 1px solid #3a3d47; border-radius: 3px;"
            " padding: 2px 4px; }"
            "QLineEdit:focus { border-color: #60a5fa; }")

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
        model = view.model()
        if model is not None:
            # undo, Submit, a linked run: the cell changed under the bar
            model.dataChanged.connect(self._follow)
            model.modelReset.connect(self._follow)
        self.sync(view.currentIndex())

    def _follow(self, *_args) -> None:
        """Re-read the cell after a change from elsewhere — unless the bar
        is being typed into, when the typing wins until it is committed."""
        import shiboken6
        if shiboken6.isValid(self) and not self.edit.hasFocus():
            self.sync()

    def _model(self) -> Optional[SheetModel]:
        return self._view.sheet_model()

    def _column_names(self):
        model = self._model()
        return model.sheet.column_names() if model is not None else []

    def show_reference(self) -> None:
        if self._reference is None:
            # a real window, not a child of a card (canvas/popup_lift.py)
            from .menus import real_window
            self._reference = FormulaReferenceDialog(real_window(self))
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
    """Ribbon + formula bar + grid over a model someone else owns.

    The unit that gets embedded wherever a Table is edited in earnest: the
    pop-out editor, a dashboard tile, and a maximized dashboard page. The
    model is passed in rather than built here, so a maximized page can put a
    second workbench on the *same* model as the tile behind it and both stay
    in step without either knowing about the other.
    """

    def __init__(self, model: SheetModel, parent=None,
                 styled: bool = True, host=None,
                 ribbon_size: str = "auto") -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.view = SpreadsheetView(self)
        self.view.setModel(model)
        if styled:
            # through style_scroll_area, never setStyleSheet -- a stylesheet
            # applied directly costs the grid its scroll-blitting
            theme.style_scroll_area(self.view, theme.grid_stylesheet())
        if host is not None:
            self.view.set_host(host)
        from .ribbon import SheetRibbon
        self.toolbar = self.ribbon = SheetRibbon(self.view, ribbon_size, self)
        self.formula_bar = FormulaBar(self.view, self)

        layout.addWidget(self.toolbar)
        layout.addWidget(self.formula_bar)
        layout.addWidget(self.view, 1)
        self.totals = self.view.totals_bar(self)
        layout.addWidget(self.totals)

    def model(self) -> Optional[SheetModel]:
        return self.view.sheet_model()

    def sync(self) -> None:
        """Re-read the current cell — after an external change replaced the
        sheet (undo, a run refreshing a linked table) — and the ribbon's
        Submit state with it."""
        self.formula_bar.sync()
        self.view.actions.refresh()
