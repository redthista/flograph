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

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QTextBrowser, QToolButton, QVBoxLayout,
                               QWidget)

from flograph.core.sheet import FUNCTION_HELP, cell_name

from .. import theme

from .completion import FormulaCompleter
from .model import SheetModel
from .view import SpreadsheetView

_BREAK = "\u21b5"    # how the one-line formula bar shows a line break


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


def summary_figures() -> list[str]:
    """The figures the selection summary shows — a choice of the user's,
    kept across sessions, Excel's three by default."""
    from PySide6.QtCore import QSettings
    from flograph.core.sheet.summary import DEFAULT_FIGURES, FIGURES
    stored = QSettings("flograph", "flograph").value(
        "spreadsheet/summary_figures")
    if stored is None:
        return list(DEFAULT_FIGURES)
    if isinstance(stored, str):
        stored = [stored] if stored else []
    known = {k for k, _label in FIGURES}
    return [k for k in stored if k in known]


def set_summary_figures(figures) -> None:
    from PySide6.QtCore import QSettings
    QSettings("flograph", "flograph").setValue(
        "spreadsheet/summary_figures", list(figures))


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
        fx.setIconSize(QSize(20, 20))
        fx.setAutoRaise(True)
        fx.setToolTip("Every function the formulas know, with examples")
        fx.clicked.connect(self.show_reference)

        # Excel's Name Box: which cell the bar is showing — and the names
        from .names_dialog import NameBox
        self.cell_label = NameBox()
        self.cell_label.setText("A1")
        self.cell_label.entered.connect(self._name_box_entered)
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
            "QLineEdit:focus { border-color: #60a5fa; }"
            "QComboBox { background: #1f2026; color: #d6d8de;"
            " border: 1px solid #3a3d47; border-radius: 3px;"
            " padding: 1px 4px; font-size: 8.5pt; min-width: 64px; }"
            "QComboBox QLineEdit { border: none; padding: 0; }"
            "QLabel#sheet_summary { background: transparent; border: none;"
            " color: #aeb2bc; padding: 0 2px; }")

        self.edit = QLineEdit()
        self.edit.setPlaceholderText(
            "value or =formula — click fx for the function list")
        self.edit.editingFinished.connect(self.commit)
        self.edit.setToolTip("The cell's value or formula. A line break in "
                             "the cell shows as ↵; Alt+Enter types one.")
        self.edit.installEventFilter(self)
        FormulaCompleter(self.edit, self._column_names, self._defined)

        # Excel's status bar: Average, Count and Sum of the selection
        self.summary = QLabel()
        self.summary.setObjectName("sheet_summary")
        self.summary.setContextMenuPolicy(Qt.CustomContextMenu)
        self.summary.customContextMenuRequested.connect(self._summary_menu)
        self.summary.setToolTip(
            "Of the selected cells: Count is the filled ones, the rest "
            "read the numbers only. Right-click to choose what shows.")
        self.summary.hide()
        self._summary_timer = QTimer(self)
        self._summary_timer.setSingleShot(True)
        self._summary_timer.setInterval(0)
        self._summary_timer.timeout.connect(self._show_summary)

        row.addWidget(fx)
        row.addWidget(self.cell_label)
        row.addWidget(self.edit, 1)
        row.addWidget(self.summary)

        selection = view.selectionModel()
        if selection is not None:
            selection.currentChanged.connect(self.sync)
            # the Name Box names a selection that is exactly a named range
            selection.selectionChanged.connect(self._show_where)
            selection.selectionChanged.connect(self._summary_timer.start)
        model = view.model()
        if model is not None:
            # undo, Submit, a linked run: the cell changed under the bar
            model.dataChanged.connect(self._follow)
            model.modelReset.connect(self._follow)
            model.dataChanged.connect(self._refresh_names)
            model.modelReset.connect(self._refresh_names)
            model.dataChanged.connect(self._summary_timer.start)
            model.modelReset.connect(self._summary_timer.start)
            self._refresh_names()
        self.sync(view.currentIndex())

    def eventFilter(self, obj, event) -> bool:
        if (obj is self.edit and event.type() == QEvent.KeyPress
                and event.key() == Qt.Key_F4):
            from .delegates import cycle_reference
            cycle_reference(self.edit)        # F4: B2 → $B$2 → B$2 → $B2
            return True
        if (obj is self.edit and event.type() == QEvent.KeyPress
                and event.key() in (Qt.Key_Return, Qt.Key_Enter)
                and event.modifiers() & Qt.AltModifier):
            self.edit.insert(_BREAK)          # Alt+Enter: a line break
            return True
        return super().eventFilter(obj, event)

    def _show_summary(self) -> None:
        import shiboken6
        if not shiboken6.isValid(self) or not shiboken6.isValid(self._view):
            return
        text = self._view.selection_summary_text(summary_figures())
        self.summary.setText(text)
        self.summary.setVisible(bool(text))

    def _summary_menu(self, pos) -> None:
        """Excel's Customize Status Bar: tick the figures to show."""
        from flograph.core.sheet.summary import FIGURES
        from .menus import new_menu
        menu = new_menu(self.summary)
        shown = set(summary_figures())
        for key, label in FIGURES:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(key in shown)
            action.toggled.connect(
                lambda on, k=key: self._toggle_figure(k, on))
        menu.exec(self.summary.mapToGlobal(pos))

    def _toggle_figure(self, key: str, on: bool) -> None:
        figures = [k for k in summary_figures() if k != key]
        if on:
            figures.append(key)
        set_summary_figures(figures)
        self._show_summary()

    def _show_where(self, *_args) -> None:
        """The Name Box: the name of the selected cells when they are
        exactly a named range (as Excel's does), else the current cell's
        address."""
        import shiboken6
        if not shiboken6.isValid(self) or self.cell_label.lineEdit().hasFocus():
            return
        model = self._model()
        current = self._view.currentIndex()
        if model is None or not current.isValid():
            return
        rect = self._view._selection_rect()
        for name in sorted(model.names, key=str.casefold):
            if model.name_box(name) == rect:
                self.cell_label.setText(name)
                return
        self.cell_label.setText(cell_name(current.row(), current.column()))

    def _refresh_names(self, *_args) -> None:
        import shiboken6
        model = self._model()
        if shiboken6.isValid(self) and model is not None:
            names = sorted(model.names)
            if names != getattr(self, "_shown_names", None):
                self._shown_names = names
                self.cell_label.set_names(names)
                self._show_where()

    def _name_box_entered(self, text: str) -> None:
        """A name or an address typed (or picked) in the Name Box: go
        there — or, a new name, name the selected cells with it."""
        from flograph.core.sheet import FUNCTION_NAMES
        from flograph.core.sheet import names as nm
        from flograph.core.sheet.select import parse_reference
        from .names_dialog import selection_target
        view, model = self._view, self._model()
        text = text.strip()
        if model is None or not text:
            return
        box = model.name_box(text)
        if box is None:
            found = parse_reference(text, [], model.rowCount(),
                                    model.columnCount())
            box = None if isinstance(found, str) else found
        if box is not None:
            view.select_rect(box)
            view.setFocus()
            return
        why = nm.check_name(text, model.names, FUNCTION_NAMES)
        target = nm.parse_target(selection_target(view))
        if why or target.startswith("!") or not view.editable:
            view.say(why or "Select the cells to name first.")
            self.sync()
            return
        model.define_name(text, target)
        view.say(f"{text} now stands for {nm.plain(target)} — use it in a "
                 f"formula: =SUM({text})")
        view.setFocus()

    def _follow(self, *_args) -> None:
        """Re-read the cell after a change from elsewhere — unless the bar
        is being typed into, when the typing wins until it is committed."""
        import shiboken6
        if shiboken6.isValid(self) and not self.edit.hasFocus():
            self.sync()

    def _model(self) -> Optional[SheetModel]:
        return self._view.sheet_model()

    def _defined(self):
        model = self._model()
        return sorted(model.names) if model is not None else []

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
        self._show_where()
        # one line: a line break in the cell shows as ↵
        self.edit.setText(model.cell_source(current.row(), current.column())
                          .replace("\n", _BREAK))

    def commit(self) -> None:
        current = self._view.currentIndex()
        model = self._model()
        if model is None or not current.isValid():
            return
        text = self.edit.text().replace(_BREAK, "\n")
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
