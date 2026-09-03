"""The Properties panel for a selected canvas shape.

Everything about how a shape looks lives here — colours, line, text,
stacking — rather than behind a right-click menu, the same place a node's
params sit. Edits go through `scene.push_shape_style` / `push_shape_text`,
so each is its own undo step and the canvas redraws from the graph event.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QDoubleSpinBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QSpinBox, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from flograph.core import Graph

from .. import theme
from ..canvas.shape_item import KIND_LABELS, LINE_KINDS

_DEFAULT_STROKE = "#e5e7eb"


class _ColourRow(QWidget):
    """A colour swatch, plus a clear button when the colour is optional
    (fill, text colour — an empty value means 'none' or 'theme default')."""

    def __init__(self, on_pick, on_clear=None) -> None:
        super().__init__()
        self._value = ""
        self._on_pick = on_pick
        self._on_clear = on_clear
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        self._swatch = QPushButton()
        self._swatch.setFixedHeight(20)
        self._swatch.clicked.connect(self._pick)
        row.addWidget(self._swatch, 1)
        self._clear = None
        if on_clear is not None:
            self._clear = QPushButton("✕")
            self._clear.setFixedSize(20, 20)
            self._clear.setToolTip("Clear")
            self._clear.clicked.connect(lambda: on_clear())
            row.addWidget(self._clear)

    def set_colour(self, value: str, *, none_label: str) -> None:
        self._value = value
        border = QColor(theme.NODE_BORDER).name()
        if value:
            self._swatch.setText("")
            self._swatch.setStyleSheet(
                f"background: {value}; border: 1px solid {border};")
        else:
            self._swatch.setText(none_label)
            self._swatch.setStyleSheet(
                f"color: palette(mid); border: 1px solid {border};")
        if self._clear is not None:
            self._clear.setEnabled(bool(value))

    def _pick(self) -> None:
        start = QColor(self._value) if self._value else QColor(_DEFAULT_STROKE)
        colour = QColorDialog.getColor(start, self, "Pick a colour")
        if colour.isValid():
            self._on_pick(colour.name())


class ShapePropertiesPanel(QWidget):
    def __init__(self, graph: Graph, scene, parent=None) -> None:
        super().__init__(parent)
        self._graph = graph
        self._scene = scene
        self._shape_id: Optional[str] = None
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._placeholder = QLabel("No shape selected")
        self._placeholder.setStyleSheet("color: palette(mid);")
        layout.addWidget(self._placeholder)

        self._hint = QLabel("Right-click for stacking order and delete. "
                            "Drag a handle to resize.")
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: palette(mid); font-size: 8pt;")
        self._hint.hide()
        layout.addWidget(self._hint)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Property", "Value"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionResizeMode(QHeaderView.Interactive)
        self.tree.header().setStretchLastSection(True)
        self.tree.setColumnWidth(0, 120)
        self.tree.hide()
        layout.addWidget(self.tree, 1)

        self._kind_label = QLabel()

        self._text = QLineEdit()
        self._text.setPlaceholderText("label")
        self._text.editingFinished.connect(self._commit_text)

        self._stroke = _ColourRow(lambda c: self._push(stroke=c))
        self._fill = _ColourRow(lambda c: self._push(fill=c),
                                lambda: self._push(fill=""))
        self._text_colour = _ColourRow(lambda c: self._push(text_color=c),
                                       lambda: self._push(text_color=""))

        self._width = QDoubleSpinBox()
        self._width.setRange(0.5, 24.0)
        self._width.setSingleStep(0.5)
        self._width.valueChanged.connect(
            lambda v: self._push(stroke_width=float(v)))

        self._font = QSpinBox()
        self._font.setRange(0, 96)
        self._font.setSpecialValueText("auto")
        self._font.valueChanged.connect(
            lambda v: self._push(font_size=float(v)))

        self._dashed = QCheckBox("Dashed")
        self._dashed.toggled.connect(lambda on: self._push(dashed=on))
        self._visible = QCheckBox("Visible on the canvas")
        self._visible.toggled.connect(lambda on: self._push(hidden=not on))

        self._rows: list[QTreeWidgetItem] = []
        for label, widget in (
                ("Kind", self._kind_label),
                ("Text", self._text),
                ("Line colour", self._stroke),
                ("Fill", self._fill),
                ("Line width", self._width),
                ("Text colour", self._text_colour),
                ("Text size", self._font),
                ("", self._dashed),
                ("", self._visible)):
            item = QTreeWidgetItem([label, ""])
            self.tree.addTopLevelItem(item)
            self.tree.setItemWidget(item, 1, widget)
            self._rows.append(item)

        graph.events.shape_changed.connect(self._on_shape_changed)
        graph.events.shape_removed.connect(self._on_shape_removed)

    # ------------------------------------------------------------- populate

    def set_shape(self, shape_id: Optional[str]) -> None:
        self._shape_id = shape_id
        shape = self._graph.shapes.get(shape_id) if shape_id else None
        if shape is None:
            self._placeholder.show()
            self._hint.hide()
            self.tree.hide()
            return
        self._placeholder.hide()
        self._hint.show()
        self.tree.show()
        self._load(shape)

    def _load(self, shape) -> None:
        self._loading = True
        try:
            self._kind_label.setText(KIND_LABELS.get(shape.kind, shape.kind))
            is_line = shape.kind in LINE_KINDS
            self._text.setText(shape.text)
            self._stroke.set_colour(shape.stroke, none_label="default")
            self._fill.set_colour(shape.fill, none_label="none")
            self._text_colour.set_colour(shape.text_color,
                                         none_label="default")
            self._width.setValue(max(0.5, shape.stroke_width))
            self._font.setValue(int(shape.font_size))
            self._dashed.setChecked(shape.dashed)
            self._visible.setChecked(not shape.hidden)
            # a line/arrow carries no text or fill — hide those rows
            for item, hidden in (
                    (self._rows[1], is_line),   # Text
                    (self._rows[3], is_line),   # Fill
                    (self._rows[5], is_line),   # Text colour
                    (self._rows[6], is_line)):  # Text size
                item.setHidden(hidden)
        finally:
            self._loading = False

    # -------------------------------------------------------------- commits

    def _push(self, **fields) -> None:
        if self._loading or self._shape_id is None:
            return
        if self._shape_id not in self._graph.shapes:
            return
        self._scene.push_shape_style(self._shape_id, **fields)

    def _commit_text(self) -> None:
        if self._loading or self._shape_id is None:
            return
        shape = self._graph.shapes.get(self._shape_id)
        if shape is not None and self._text.text() != shape.text:
            self._scene.push_shape_text(self._shape_id, self._text.text())

    # -------------------------------------------------------------- events

    def _on_shape_changed(self, shape) -> None:
        if shape.id == self._shape_id and not self.tree.isHidden():
            self._load(shape)

    def _on_shape_removed(self, shape_id: str) -> None:
        if shape_id == self._shape_id:
            self.set_shape(None)
