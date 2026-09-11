"""New group (AB4): a name for a section of the tab bar, and its colour.

A dialog rather than the one-line name prompt it replaced, because a group
is made once and named once, and that is the moment someone has a colour
in mind for it too. The colour starts at Automatic — the section takes the
colour of its first coloured page, what a group did before it could have
one of its own.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout,
)

from .. import theme
from ..properties.colour_row import ColourRow

AUTOMATIC = "Automatic"


class GroupDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New group")
        self._colour = ""
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Sales")
        form.addRow("Name:", self.name_edit)
        self.colour_row = ColourRow(
            self._set_colour, lambda: self._set_colour(""),
            start=theme.SELECTION_OUTLINE.name(),
            clear_tip="Back to automatic")
        self.colour_row.set_colour("", none_label=AUTOMATIC)
        form.addRow("Colour:", self.colour_row)
        layout.addLayout(form)
        hint = QLabel("Automatic takes the colour of the group's first "
                      "coloured page. The pages keep their own colours "
                      "either way.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid);")
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ok = buttons.button(QDialogButtonBox.Ok)
        self._ok.setEnabled(False)   # a group is its name; no name, no group
        self.name_edit.textChanged.connect(
            lambda text: self._ok.setEnabled(bool(text.strip())))

    def _set_colour(self, colour: str) -> None:
        self._colour = colour
        self.colour_row.set_colour(colour, none_label=AUTOMATIC)

    def name(self) -> str:
        return self.name_edit.text().strip()

    def colour(self) -> str:
        """"#rrggbb", or "" for automatic."""
        return self._colour
