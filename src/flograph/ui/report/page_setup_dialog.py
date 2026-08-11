"""Page Setup for a report page: the sheet, the cover, the furniture.

Three tabs rather than one long form, because the three answer different
questions and are set at different times — the sheet once, the cover when
the report is being handed to someone, the header and footer when it is
long enough to need finding your way around.

The dialog edits a *copy* of the page's PageSetup and hands it back on
accept; committing it to the model (through the undo stack) is the caller's
job, which is what keeps this a plain QDialog with no graph in it.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QGridLayout, QGroupBox, QLabel, QLineEdit, QSpinBox,
    QTabWidget, QVBoxLayout, QWidget,
)

from flograph.core.page_setup import FIELDS, PAGE_SIZES, PageSetup

#: Written under the header and footer grids. The fields are the only part
#: of this dialog nobody could guess, so they are spelled out rather than
#: left to a tooltip.
_FIELD_HELP = "Fields: " + ", ".join(f"{token} — {what}"
                                     for token, what in FIELDS)


class PageSetupDialog(QDialog):
    def __init__(self, setup: PageSetup, page_title: str = "",
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Page Setup")
        self._setup = setup.copy() if setup is not None else PageSetup()
        self._page_title = page_title

        tabs = QTabWidget()
        tabs.addTab(self._sheet_tab(), "Page")
        tabs.addTab(self._cover_tab(), "Cover")
        tabs.addTab(self._bands_tab(), "Header && Footer")

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
            | QDialogButtonBox.RestoreDefaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(
            self._restore_defaults)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(self._summary)
        layout.addWidget(buttons)
        self.resize(520, 400)
        self._refresh_summary()

    # ------------------------------------------------------------- the sheet

    def _sheet_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self.size_box = QComboBox()
        for name in PAGE_SIZES:
            self.size_box.addItem(name, name)
        index = self.size_box.findData(self._setup.size)
        self.size_box.setCurrentIndex(max(0, index))
        self.size_box.currentIndexChanged.connect(self._refresh_summary)
        form.addRow("Size", self.size_box)

        self.orientation_box = QComboBox()
        self.orientation_box.addItem("Portrait", False)
        self.orientation_box.addItem("Landscape", True)
        self.orientation_box.setCurrentIndex(1 if self._setup.landscape else 0)
        self.orientation_box.currentIndexChanged.connect(self._refresh_summary)
        form.addRow("Orientation", self.orientation_box)

        margins = QGroupBox("Margins (mm)")
        grid = QGridLayout(margins)
        self.margin_boxes = {}
        for column, (name, label) in enumerate(
                (("margin_top", "Top"), ("margin_right", "Right"),
                 ("margin_bottom", "Bottom"), ("margin_left", "Left"))):
            box = QDoubleSpinBox()
            box.setRange(0.0, 100.0)
            box.setDecimals(1)
            box.setSingleStep(1.0)
            box.setValue(float(getattr(self._setup, name)))
            box.valueChanged.connect(self._refresh_summary)
            self.margin_boxes[name] = box
            grid.addWidget(QLabel(label), column // 2, (column % 2) * 2)
            grid.addWidget(box, column // 2, (column % 2) * 2 + 1)
        form.addRow(margins)
        return page

    # ------------------------------------------------------------- the cover

    def _cover_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)

        self.cover_check = QCheckBox("Start with a cover page")
        self.cover_check.setChecked(self._setup.cover)
        self.cover_check.toggled.connect(self._cover_toggled)
        form.addRow(self.cover_check)

        self.cover_title_edit = QLineEdit(self._setup.cover_title)
        self.cover_title_edit.setPlaceholderText(
            self._page_title or "the page's own title")
        form.addRow("Title", self.cover_title_edit)

        self.cover_subtitle_edit = QLineEdit(self._setup.cover_subtitle)
        self.cover_subtitle_edit.setPlaceholderText("optional line beneath")
        form.addRow("Subtitle", self.cover_subtitle_edit)

        self.cover_date_check = QCheckBox("Show today's date")
        self.cover_date_check.setChecked(self._setup.cover_date)
        form.addRow(self.cover_date_check)

        note = QLabel("The cover is a page of its own before the report, and "
                      "is not numbered. It is not part of the markdown, so "
                      "turning it off leaves what you wrote alone.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        form.addRow(note)

        self._cover_toggled(self._setup.cover)
        return page

    def _cover_toggled(self, on: bool) -> None:
        for widget in (self.cover_title_edit, self.cover_subtitle_edit,
                       self.cover_date_check):
            widget.setEnabled(bool(on))

    # --------------------------------------------------- headers and footers

    def _bands_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.band_edits = {}

        for band, label in (("header", "Header"), ("footer", "Footer")):
            group = QGroupBox(label)
            grid = QGridLayout(group)
            for column, side in enumerate(("left", "center", "right")):
                name = f"{band}_{side}"
                edit = QLineEdit(getattr(self._setup, name))
                edit.setPlaceholderText(side.capitalize())
                self.band_edits[name] = edit
                grid.addWidget(QLabel(side.capitalize()), 0, column)
                grid.addWidget(edit, 1, column)
            layout.addWidget(group)

        help_label = QLabel(_FIELD_HELP)
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: palette(mid);")
        layout.addWidget(help_label)

        self.first_page_check = QCheckBox(
            "Show the header and footer on the first page")
        self.first_page_check.setChecked(self._setup.bands_on_first_page)
        layout.addWidget(self.first_page_check)

        row = QFormLayout()
        self.first_number_box = QSpinBox()
        self.first_number_box.setRange(0, 9999)
        self.first_number_box.setValue(int(self._setup.first_page_number))
        row.addRow("Number the first page", self.first_number_box)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------ the result

    @property
    def _summary(self) -> QLabel:
        # built lazily so it can be added to the layout after the tabs that
        # feed it, while still existing when their signals first fire
        if not hasattr(self, "_summary_label"):
            self._summary_label = QLabel("")
            self._summary_label.setAlignment(Qt.AlignRight)
            self._summary_label.setStyleSheet("color: palette(mid);")
        return self._summary_label

    def _refresh_summary(self) -> None:
        """The one number nobody can work out in their head: how wide the
        text column ends up. It is also what decides how big a chart comes
        out, so it is worth showing while the margins are being typed."""
        setup = self._read()
        width, height = setup.body_mm()
        self._summary.setText(
            f"Text area {width:.0f} x {height:.0f} mm "
            f"({setup.body_width_points()} pt wide)")

    def _read(self) -> PageSetup:
        setup = self._setup.copy()
        setup.size = self.size_box.currentData()
        setup.landscape = bool(self.orientation_box.currentData())
        for name, box in self.margin_boxes.items():
            setattr(setup, name, float(box.value()))
        if hasattr(self, "cover_check"):
            setup.cover = self.cover_check.isChecked()
            setup.cover_title = self.cover_title_edit.text()
            setup.cover_subtitle = self.cover_subtitle_edit.text()
            setup.cover_date = self.cover_date_check.isChecked()
        if hasattr(self, "band_edits"):
            for name, edit in self.band_edits.items():
                setattr(setup, name, edit.text())
            setup.bands_on_first_page = self.first_page_check.isChecked()
            setup.first_page_number = int(self.first_number_box.value())
        setup.normalize()
        return setup

    def _restore_defaults(self) -> None:
        self._setup = PageSetup()
        defaults = self._setup
        self.size_box.setCurrentIndex(max(0, self.size_box.findData(
            defaults.size)))
        self.orientation_box.setCurrentIndex(1 if defaults.landscape else 0)
        for name, box in self.margin_boxes.items():
            box.setValue(float(getattr(defaults, name)))
        self.cover_check.setChecked(defaults.cover)
        self.cover_title_edit.setText(defaults.cover_title)
        self.cover_subtitle_edit.setText(defaults.cover_subtitle)
        self.cover_date_check.setChecked(defaults.cover_date)
        for name, edit in self.band_edits.items():
            edit.setText(getattr(defaults, name))
        self.first_page_check.setChecked(defaults.bands_on_first_page)
        self.first_number_box.setValue(int(defaults.first_page_number))
        self._refresh_summary()

    def result_setup(self) -> PageSetup:
        """What the dialog was left showing. Read after exec() returns
        Accepted."""
        return self._read()
