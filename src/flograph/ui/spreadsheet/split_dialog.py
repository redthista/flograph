"""Text to Columns… — Excel's wizard as one dialog.

Split the current column at a character (comma, semicolon, tab, space or
your own) or at fixed positions; a preview shows the first rows as they
will land and a line says how many columns it makes. The new columns go
right of the original; unless *Keep the original column* is ticked, the
first part replaces it. Names can be typed (comma-separated). One undo
step.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog,
                               QDialogButtonBox, QFormLayout, QFrame,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QRadioButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from flograph.core.sheet import split as splitting

from .menus import real_window

_PREVIEW_ROWS = 8


class SplitDialog(QDialog):
    def __init__(self, view, col: int, parent=None) -> None:
        super().__init__(parent)
        self._view = view
        self._model = model = view.sheet_model()
        self._col = col
        self._base = model.sheet.columns[col].name
        self._values = [model.value_text(r, col)
                        for r in range(model.rowCount())]
        self._names_typed = False
        self.setWindowTitle(f"Text to Columns — {self._base}")

        layout = QVBoxLayout(self)
        intro = QLabel(f"Split <b>{self._base}</b> into several columns. "
                       "The new columns go to its right.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        how = QGroupBox("Split")
        how_lay = QVBoxLayout(how)
        self.delimited = QRadioButton("At a character — a comma, a space, "
                                      "a tab …")
        self.fixed = QRadioButton("At fixed positions — the same number "
                                  "of characters on every row")
        how_lay.addWidget(self.delimited)
        seps = QHBoxLayout()
        seps.setContentsMargins(24, 0, 0, 0)
        self._seps = {}
        for key, label, _char in splitting.SEPARATORS:
            box = QCheckBox(label)
            self._seps[key] = box
            seps.addWidget(box)
        self.other_box = QCheckBox("Other")
        self.other = QLineEdit()
        self.other.setMaximumWidth(60)
        self.other.setPlaceholderText("e.g. |")
        seps.addWidget(self.other_box)
        seps.addWidget(self.other)
        seps.addStretch(1)
        how_lay.addLayout(seps)
        opts = QHBoxLayout()
        opts.setContentsMargins(24, 0, 0, 0)
        self.merge = QCheckBox("Treat repeated separators as one")
        self.quote = QCheckBox('Keep "quoted, text" together')
        self.quote.setChecked(True)
        opts.addWidget(self.merge)
        opts.addWidget(self.quote)
        opts.addStretch(1)
        how_lay.addLayout(opts)
        how_lay.addWidget(self.fixed)
        fixed_row = QHBoxLayout()
        fixed_row.setContentsMargins(24, 0, 0, 0)
        fixed_row.addWidget(QLabel("Break after characters"))
        self.breaks = QLineEdit()
        self.breaks.setPlaceholderText("e.g. 3, 8")
        fixed_row.addWidget(self.breaks, 1)
        how_lay.addLayout(fixed_row)
        layout.addWidget(how)

        form = QFormLayout()
        self.trim = QCheckBox("Trim spaces from each part")
        self.trim.setChecked(True)
        self.keep = QCheckBox("Keep the original column")
        form.addRow(self.trim)
        form.addRow(self.keep)
        self.names = QLineEdit()
        self.names.setToolTip("Names for the new columns, separated by "
                              "commas. Leave a name out to get a numbered "
                              "one.")
        form.addRow("Names", self.names)
        layout.addLayout(form)

        result = QFrame()
        result.setFrameShape(QFrame.StyledPanel)
        rlay = QVBoxLayout(result)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("font-weight: 600;")
        rlay.addWidget(self.status)
        self.preview = QTableWidget()
        self.preview.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview.setSelectionMode(QAbstractItemView.NoSelection)
        self.preview.setFocusPolicy(Qt.NoFocus)
        self.preview.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.preview.verticalHeader().setDefaultSectionSize(22)
        rlay.addWidget(self.preview)
        layout.addWidget(result)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                        | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Split")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        guess = splitting.guess_separator(self._values)
        key = {sep: k for k, _l, sep in splitting.SEPARATORS}.get(guess)
        if guess is not None and key is None:
            self.other_box.setChecked(True)
            self.other.setText(guess)
        else:
            self._seps[key or "comma"].setChecked(True)
        self.delimited.setChecked(True)

        for box in (self.delimited, self.fixed, self.other_box, self.merge,
                    self.quote, self.trim, self.keep, *self._seps.values()):
            box.toggled.connect(self._refresh)
        self.other.textChanged.connect(self._other_typed)
        self.breaks.textChanged.connect(self._breaks_typed)
        self.names.textEdited.connect(self._names_edited)
        self._refresh()
        self.resize(560, 0)

    # -------------------------------------------------------------- state

    def options(self):
        """The split options, or a sentence saying what is missing."""
        trim = self.trim.isChecked()
        if self.fixed.isChecked():
            breaks = splitting.parse_breaks(self.breaks.text())
            if isinstance(breaks, str):
                return breaks
            return {"mode": "fixed", "breaks": breaks, "trim": trim}
        seps = [char for key, _l, char in splitting.SEPARATORS
                if self._seps[key].isChecked()]
        if self.other_box.isChecked() and self.other.text():
            seps.append(self.other.text())
        if not seps:
            return "Tick at least one separator."
        return {"mode": "delimited", "separators": seps,
                "merge": self.merge.isChecked(),
                "quote": '"' if self.quote.isChecked() else "",
                "trim": trim}

    def parts(self):
        opts = self.options()
        if isinstance(opts, str):
            return opts
        return splitting.split_values(self._values, **opts)

    def chosen_names(self, width: int) -> list[str]:
        keep = self.keep.isChecked()
        defaults = splitting.new_names(
            self._base, width,
            [n for i, n in enumerate(self._model.sheet.column_names())
             if i != self._col or keep],
            keep)
        typed = [n.strip() for n in self.names.text().split(",")]
        if not self._names_typed:
            return defaults
        return [typed[i] if i < len(typed) and typed[i] else defaults[i]
                for i in range(width)]

    def _other_typed(self, text: str) -> None:
        if text and not self.other_box.isChecked():
            self.other_box.setChecked(True)     # refreshes
        else:
            self._refresh()

    def _breaks_typed(self, _text: str) -> None:
        if not self.fixed.isChecked():
            self.fixed.setChecked(True)          # refreshes
        else:
            self._refresh()

    def _names_edited(self, _text: str) -> None:
        self._names_typed = True
        self._refresh()

    def _refresh(self, *_args) -> None:
        is_fixed = self.fixed.isChecked()
        for box in (*self._seps.values(), self.other_box, self.other,
                    self.merge, self.quote):
            box.setEnabled(not is_fixed)
        self.breaks.setEnabled(is_fixed)
        ok = self.buttons.button(QDialogButtonBox.Ok)
        parts = self.parts()
        if isinstance(parts, str):
            self.status.setText(parts)
            self.status.setStyleSheet("font-weight: 600; color: #f87171;")
            ok.setEnabled(False)
            self.preview.setRowCount(0)
            self.preview.setColumnCount(0)
            QTimer.singleShot(0, self, self._fit)
            return
        width = len(parts[0]) if parts else 1
        names = self.chosen_names(width)
        if not self._names_typed:
            self.names.setText(", ".join(names))
        clash = self._clash(names)
        self.status.setStyleSheet("font-weight: 600;" if not clash
                                  else "font-weight: 600; color: #f87171;")
        if clash:
            self.status.setText(clash)
        elif width < 2:
            self.status.setText("Nothing to split — no row has the "
                                "separator. Try another.")
        else:
            made = width if self.keep.isChecked() else width - 1
            self.status.setText(
                f"Makes {width} columns from {len(parts)} rows — "
                f"{made} new beside {self._base}"
                + (", which stays as it is." if self.keep.isChecked()
                   else ", which takes the first part.")
                + (f" (At most {splitting.MAX_PARTS} parts.)"
                   if width >= splitting.MAX_PARTS else ""))
        ok.setEnabled(width >= 2 and not clash)
        self._fill_preview(parts, names)
        QTimer.singleShot(0, self, self._fit)

    def _clash(self, names: list[str]) -> str:
        others = {n.casefold() for i, n in
                  enumerate(self._model.sheet.column_names())
                  if i != self._col or self.keep.isChecked()}
        seen = set()
        for name in names:
            low = name.casefold()
            if low in others or low in seen:
                return f"There is already a column called “{name}”."
            seen.add(low)
        return ""

    def _fill_preview(self, parts, names) -> None:
        table = self.preview
        rows = parts[:_PREVIEW_ROWS]
        table.clear()
        table.setRowCount(len(rows))
        table.setColumnCount(len(names))
        table.setHorizontalHeaderLabels(names)
        table.setVerticalHeaderLabels([str(i + 1) for i in range(len(rows))])
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                table.setItem(r, c, QTableWidgetItem(text))
        table.setFixedHeight(table.horizontalHeader().sizeHint().height()
                             + 22 * len(rows) + 2 * table.frameWidth() + 2)

    def _fit(self) -> None:
        layout = self.layout()
        layout.activate()
        height = (layout.totalHeightForWidth(self.width())
                  if layout.hasHeightForWidth()
                  else layout.totalSizeHint().height())
        self.setMinimumHeight(height)
        self.resize(self.width(), height)


def text_to_columns(view) -> None:
    model = view.sheet_model()
    current = view.currentIndex()
    if model is None or model.read_only or not current.isValid():
        return
    col = current.column()
    dialog = SplitDialog(view, col, real_window(view))
    if dialog.exec():
        parts = dialog.parts()
        if isinstance(parts, str):
            return
        names = dialog.chosen_names(len(parts[0]))
        model.split_column(col, parts, names, dialog.keep.isChecked())
