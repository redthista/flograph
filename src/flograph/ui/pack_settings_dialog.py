"""Tools ▸ Node Packs ▸ Settings… — the settings a pack declares.

A pack lists its settings in ``pack.toml`` (``[[settings]]``, see
core.packs.PackSetting) and reads them back with ``packs.settings(id)``;
this is the form between the two, built from the declarations, so a pack
gets a settings page without shipping any Qt of its own. Saving reloads the
packs, because what a setting changes is often a node's dropdown — a models
folder fills every model list — and those are built when a script loads.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from flograph.core import packs


class PackSettingsDialog(QDialog):
    def __init__(self, pack: packs.Pack, user_dir: Path, parent=None) -> None:
        super().__init__(parent)
        self.pack, self.user_dir = pack, Path(user_dir)
        self.setWindowTitle(f"{pack.name} Settings")
        self.resize(640, 0)
        self._editors: dict[str, tuple] = {}
        self._notes: list[QLabel] = []

        intro = QLabel(f"Settings for {pack.name} on this computer. They are "
                       "not saved in flows.")
        intro.setWordWrap(True)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        values = packs.read_settings(self.user_dir, pack)
        for setting in pack.settings:
            editor, read, write = self._editor(setting)
            write(values[setting.name])
            self._editors[setting.name] = (read, write, setting)
            field = editor
            if setting.help:
                field = QWidget()
                column = QVBoxLayout(field)
                column.setContentsMargins(0, 0, 0, 0)
                column.setSpacing(2)
                column.addWidget(editor)
                note = QLabel(setting.help)
                note.setWordWrap(True)
                note.setTextFormat(Qt.PlainText)
                note.setObjectName("pack_setting_help")
                note.setStyleSheet("color: palette(placeholder-text);")
                column.addWidget(note)
                self._notes.append(note)
            form.addRow(setting.label, field)

        buttons = QDialogButtonBox(QDialogButtonBox.Save
                                   | QDialogButtonBox.Cancel
                                   | QDialogButtonBox.RestoreDefaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(
            self._defaults)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addStretch(1)
        layout.addWidget(buttons)

    # ------------------------------------------------------------ editors

    def _editor(self, s: packs.PackSetting):
        """(widget, read(), write(value)) for one setting."""
        if s.type == "bool":
            box = QCheckBox()
            return box, box.isChecked, lambda v: box.setChecked(bool(v))
        if s.type == "int":
            spin = QSpinBox()
            spin.setRange(-2**31, 2**31 - 1)
            return spin, spin.value, lambda v: spin.setValue(int(v))
        if s.type == "float":
            spin = QDoubleSpinBox()
            spin.setRange(-1e12, 1e12)
            spin.setDecimals(4)
            return spin, spin.value, lambda v: spin.setValue(float(v))
        if s.type == "choice":
            combo = QComboBox()
            combo.addItems(s.options)
            return combo, combo.currentText, \
                lambda v: combo.setCurrentText(str(v))
        line = QLineEdit()
        line.setPlaceholderText(s.placeholder)
        line.setClearButtonEnabled(True)
        if s.type not in ("folder", "file"):
            return line, line.text, lambda v: line.setText(str(v))
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(line, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: self._browse(s, line))
        h.addWidget(browse)
        return row, lambda: line.text().strip(), \
            lambda v: line.setText(str(v))

    def _browse(self, s: packs.PackSetting, line: QLineEdit) -> None:
        start = line.text().strip() or str(Path.home())
        if s.type == "folder":
            got = QFileDialog.getExistingDirectory(self, s.label, start)
        else:
            got, _ = QFileDialog.getOpenFileName(self, s.label, start)
        if got:
            line.setText(got)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # A wrapped help line is measured before the form gives it a width,
        # so a two-line one came out cut in half. Once shown, the width is
        # real: give each the height that width needs, then fit the dialog.
        for note in self._notes:
            note.setMinimumHeight(note.heightForWidth(note.width()))
        layout = self.layout()
        need = (layout.totalHeightForWidth(self.width())
                if layout.hasHeightForWidth() else self.sizeHint().height())
        self.resize(self.width(), need)

    def _defaults(self) -> None:
        for read, write, setting in self._editors.values():
            write(setting.default)

    # ------------------------------------------------------------ result

    def values(self) -> dict:
        return {name: read() for name, (read, _w, _s) in self._editors.items()}

    def accept(self) -> None:
        packs.write_settings(self.user_dir, self.pack, self.values())
        super().accept()
