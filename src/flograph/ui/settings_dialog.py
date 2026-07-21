"""General app Settings window (Tools > Settings…, Ctrl+,): a category list
on the left, one page per category on the right. Start here when adding a new
app-wide preference instead of a one-off menu toggle — add a page in
__init__ and it shows up in the nav automatically.

Non-modal and live-apply: pages bind straight to the setting they control
(e.g. an existing QAction's checked state, or MainWindow.set_lod_*) so a
toggle here takes effect immediately, the way it would from a menu — there's
no separate Save step.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QListWidget, QSpinBox,
    QStackedWidget, QVBoxLayout, QWidget,
)

from .canvas import grid


class SettingsDialog(QDialog):
    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(560, 520)

        self._nav = QListWidget()
        self._nav.setFixedWidth(150)
        self._pages = QStackedWidget()

        layout = QHBoxLayout(self)
        layout.addWidget(self._nav)
        layout.addWidget(self._pages, 1)

        self._add_page("General", self._build_general_page(window))
        self._add_page("Canvas", self._build_canvas_page(window))

        self._nav.currentRowChanged.connect(self._pages.setCurrentIndex)
        self._nav.setCurrentRow(0)

    def _add_page(self, name: str, page: QWidget) -> None:
        self._nav.addItem(name)
        self._pages.addWidget(page)

    @staticmethod
    def _hint(text: str) -> QLabel:
        """A de-emphasized description line under a control. Sized down
        rather than color-dimmed: a measured contrast check found palette
        roles meant for "dim" text (mid, placeholder-text) can drop well
        below readable contrast depending on the desktop theme, while
        full-contrast text at a smaller size reads as secondary everywhere."""
        label = QLabel(text)
        label.setWordWrap(True)
        font = label.font()
        font.setPointSizeF(font.pointSizeF() * 0.9)
        label.setFont(font)
        return label

    @staticmethod
    def _build_general_page(window) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        page_bar_row = QHBoxLayout()
        page_bar_row.addWidget(QLabel("Page bar position:"))
        page_bar_combo = QComboBox()
        page_bar_combo.setObjectName("page_bar_position_combo")
        positions = ["bottom", "top"]
        page_bar_combo.addItems([p.capitalize() for p in positions])
        page_bar_combo.setCurrentIndex(positions.index(window.page_bar_position))
        page_bar_combo.currentIndexChanged.connect(
            lambda index: window.set_page_bar_position(positions[index]))
        page_bar_row.addWidget(page_bar_combo)
        page_bar_row.addStretch(1)
        layout.addLayout(page_bar_row)
        layout.addWidget(SettingsDialog._hint(
            "Which edge of the window the Model/page tabs live on."))

        layout.addStretch(1)
        return page

    @staticmethod
    def _build_canvas_page(window) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        gpu_check = QCheckBox("GPU-Accelerated Canvas (experimental)")
        gpu_check.setObjectName("gpu_viewport_checkbox")
        gpu_check.setToolTip(window.action_gpu_viewport.toolTip())
        gpu_check.setChecked(window.action_gpu_viewport.isChecked())
        # bind both ways: the checkbox drives the action, and an automatic
        # fallback revert (GL unavailable) drives the checkbox back
        gpu_check.toggled.connect(window.action_gpu_viewport.setChecked)
        window.action_gpu_viewport.toggled.connect(gpu_check.setChecked)
        layout.addWidget(gpu_check)
        layout.addWidget(SettingsDialog._hint(
            "Renders the canvas through OpenGL instead of software "
            "rasterizing. Off by default; falls back automatically if this "
            "machine can't provide a working GL context. If a card "
            "(figure/table/webview) looks wrong after enabling, switch it "
            "back off here."))

        layout.addSpacing(12)

        lod_check = QCheckBox("Simplify nodes when zoomed out")
        lod_check.setObjectName("lod_enabled_checkbox")
        lod_check.setChecked(window.lod_enabled)
        layout.addWidget(lod_check)
        layout.addWidget(SettingsDialog._hint(
            "Below the zoom threshold, nodes hide their ports and embedded "
            "widgets (tables/figures) and paint as a flat rectangle — keeps "
            "large graphs responsive when zoomed way out. Turn off to "
            "always render full detail, at the cost of that speed."))

        threshold_row = QHBoxLayout()
        threshold_row.addWidget(QLabel("Zoom threshold:"))
        threshold_spin = QSpinBox()
        threshold_spin.setObjectName("lod_threshold_spinbox")
        # 10% is the canvas's minimum zoom (ZOOM_MIN in base_view.py) — below
        # that is a dead value, never reachable. 100% is the normal working
        # view — above that would blank nodes even at everyday zoom, which
        # reads as broken rather than a deliberate "simplify aggressively"
        # choice, so it's left out of the range entirely.
        threshold_spin.setRange(10, 100)
        threshold_spin.setSingleStep(5)
        threshold_spin.setSuffix("%")
        threshold_spin.setToolTip(
            "Simplify nodes below this zoom level (100% = actual size)")
        threshold_spin.setValue(round(window.lod_threshold * 100))
        threshold_spin.setEnabled(lod_check.isChecked())
        threshold_row.addWidget(threshold_spin)
        threshold_row.addStretch(1)
        layout.addLayout(threshold_row)

        lod_check.toggled.connect(window.set_lod_enabled)
        lod_check.toggled.connect(threshold_spin.setEnabled)
        threshold_spin.valueChanged.connect(
            lambda value: window.set_lod_threshold(value / 100.0))

        layout.addSpacing(12)

        snap_check = QCheckBox("Snap to Grid")
        snap_check.setObjectName("snap_enabled_checkbox")
        snap_check.setToolTip(
            "Snap moves and resizes to the grid (hold Ctrl to bypass)")
        snap_check.setChecked(window.snap_enabled)
        layout.addWidget(snap_check)

        grid_row = QHBoxLayout()
        grid_row.addWidget(QLabel("Grid resolution:"))
        grid_combo = QComboBox()
        grid_combo.setObjectName("grid_step_combo")
        selected = 0
        for index, (name, step) in enumerate(grid.GRID_PRESETS.items()):
            grid_combo.addItem(f"{name} ({int(step)} px)", step)
            if abs(step - window.grid_step) < 0.01:
                selected = index
        grid_combo.setCurrentIndex(selected)
        grid_combo.setEnabled(snap_check.isChecked())
        grid_row.addWidget(grid_combo)
        grid_row.addStretch(1)
        layout.addLayout(grid_row)
        layout.addWidget(SettingsDialog._hint(
            "Snapping applies to node/frame moves and resizes on the canvas "
            "and dashboard tiles."))

        snap_check.toggled.connect(window.set_snap_enabled)
        snap_check.toggled.connect(grid_combo.setEnabled)
        grid_combo.currentIndexChanged.connect(
            lambda index: window.set_grid_step(grid_combo.itemData(index)))

        layout.addStretch(1)
        return page
