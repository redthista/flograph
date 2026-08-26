"""Everything about how one node looks, in one dialog.

Colour, mark, shape, port names, port collapsing and the canvas preview were
six separate entries on the node's right-click menu — half of them
conditional, so the menu changed shape depending on what you right-clicked
and none of them were findable by anyone who hadn't already found them. They
are one *Appearance…* item now.

**Live, not OK/Cancel.** Every control applies as you touch it, so the node
behind the dialog changes while you are choosing — which is the whole point
when the thing being chosen is what something looks like. Five of the six
already behaved this way from the menu; only the mark picker didn't.

Each change is its own undoable command, and the mark and colour commands
merge, so clicking through sixteen marks to find the right one is one step
back rather than sixteen.

**One node or a whole selection.** Opened from a multi-selection it shows the
first node's settings and writes every change to all of them, one undo step
apiece. Each control still only reaches the nodes it means something for: a
card has no square to mark and no shape to choose, so a mixed selection gets
its colour and its port names changed and keeps its cards as they were.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QCheckBox, QColorDialog, QComboBox,
    QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QRadioButton, QVBoxLayout, QWidget,
)

from .. import theme
from . import marks
from .node_item import (
    PREVIEW_TOGGLABLE_KINDS, card_kind, port_labels_on, renders_plain,
)

MARK_TEXT_MAX = 4  # characters; past that nothing legible fits in 60px
_SWATCH = 30
_COLUMNS = 6
_PREVIEW = 56  # the size the node draws a mark image at


class _MarkSwatch(QAbstractButton):
    """One cell of the grid: a mark, painted, that can be checked."""

    def __init__(self, name: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.name = name
        self.setCheckable(True)
        self.setFixedSize(QSize(_SWATCH + 8, _SWATCH + 8))
        self.setToolTip(marks.MARK_LABELS.get(name, name))
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isChecked():
            painter.setPen(QColor(theme.SELECTION_OUTLINE))
            painter.setBrush(QColor(theme.NODE_HEADER))
        else:
            painter.setPen(QColor(theme.NODE_BORDER))
            painter.setBrush(QColor(theme.NODE_BODY))
        painter.drawRoundedRect(rect, 5, 5)
        marks.draw(self.name, painter, rect.adjusted(7, 7, -7, -7),
                   QColor(theme.NODE_TEXT))


class AppearanceDialog(QDialog):
    """How a node — or a selection of them — looks. Applies live; there is
    nothing to confirm."""

    def __init__(self, scene, node_id,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._scene = scene
        self._graph = scene.graph
        # one id or a list of them; the first is the anchor, whose settings
        # the controls open showing and whose kind decides which sections
        # appear at all
        self._node_ids = [node_id] if isinstance(node_id, str) else list(node_id)
        self._node_id = self._node_ids[0]
        self._loading = True
        node = self._graph.node(self._node_id)
        self.setWindowTitle(
            f"Appearance — {node.label}" if len(self._node_ids) == 1
            else f"Appearance — {len(self._node_ids)} nodes")

        # A card's size is its content's and it has no square to mark, so the
        # shape and mark sections are simply absent for one. An identity-only
        # card (Variables) draws as an ordinary node and keeps both.
        self._plain = renders_plain(node)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        if self._plain:
            layout.addWidget(self._build_shape_group(node))
            layout.addWidget(self._build_mark_group(node))
        layout.addWidget(self._build_colour_group())
        layout.addWidget(self._build_ports_group(node))
        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self._load(node)
        self._loading = False

    # ------------------------------------------------------------- building

    def _build_shape_group(self, node) -> QWidget:
        group = QGroupBox("Shape")
        form = QFormLayout(group)
        self._shape_combo = QComboBox()
        self._shape_combo.setObjectName("appearance_shape_combo")
        for label, value in (("Canvas default", None),
                             ("Compact square", True),
                             ("Wide box", False)):
            self._shape_combo.addItem(label, value)
        self._shape_combo.currentIndexChanged.connect(self._push_shape)
        form.addRow("Draw this node as", self._shape_combo)
        return group

    def _build_mark_group(self, node) -> QWidget:
        default_name = marks.MARK_LABELS.get(
            marks.mark_for_category(node.spec.category), "default")
        group = QGroupBox("Mark")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        self._image_uri = ""
        self._default_radio = QRadioButton(f"Default ({default_name.lower()})")
        self._mark_radio = QRadioButton("Mark")
        self._text_radio = QRadioButton("Text")
        self._image_radio = QRadioButton("Image")
        for radio in (self._default_radio, self._mark_radio,
                      self._text_radio, self._image_radio):
            radio.setAutoExclusive(True)
            radio.toggled.connect(self._on_mark_mode_changed)

        layout.addWidget(self._default_radio)
        layout.addWidget(self._mark_radio)

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(20, 0, 0, 0)
        grid.setSpacing(4)
        self._swatches = QButtonGroup(self)
        self._swatches.setExclusive(True)
        for i, name in enumerate(marks.MARK_NAMES):
            swatch = _MarkSwatch(name)
            self._swatches.addButton(swatch, i)
            grid.addWidget(swatch, i // _COLUMNS, i % _COLUMNS)
        layout.addWidget(grid_host)

        layout.addWidget(self._text_radio)
        text_row = QHBoxLayout()
        text_row.setContentsMargins(20, 0, 0, 0)
        self._text_edit = QLineEdit()
        self._text_edit.setMaxLength(MARK_TEXT_MAX)
        self._text_edit.setFixedWidth(80)
        text_row.addWidget(self._text_edit)
        hint = QLabel(f"up to {MARK_TEXT_MAX} characters")
        hint.setEnabled(False)
        text_row.addWidget(hint)
        text_row.addStretch(1)
        layout.addLayout(text_row)

        layout.addWidget(self._image_radio)
        image_row = QHBoxLayout()
        image_row.setContentsMargins(20, 0, 0, 0)
        self._image_preview = QLabel()
        self._image_preview.setFixedSize(_PREVIEW, _PREVIEW)
        self._image_preview.setAlignment(Qt.AlignCenter)
        self._image_preview.setFrameShape(QFrame.StyledPanel)
        image_row.addWidget(self._image_preview)
        self._image_button = QPushButton("Choose…")
        self._image_button.clicked.connect(self._choose_image)
        image_row.addWidget(self._image_button)
        self._image_hint = QLabel("PNG, JPEG, SVG, animated GIF/WebP")
        self._image_hint.setEnabled(False)
        self._image_hint.setWordWrap(True)
        image_row.addWidget(self._image_hint, 1)
        layout.addLayout(image_row)

        # Picking a swatch or typing means you meant that row — having to
        # tick the radio first is a step nobody wants to be asked for.
        self._swatches.buttonClicked.connect(self._on_swatch_clicked)
        self._text_edit.textEdited.connect(self._on_text_edited)
        return group

    def _build_colour_group(self) -> QWidget:
        group = QGroupBox("Colour")
        row = QHBoxLayout(group)
        self._colour_button = QPushButton("Choose…")
        self._colour_button.setObjectName("appearance_colour_button")
        self._colour_button.clicked.connect(self._choose_colour)
        row.addWidget(self._colour_button)
        self._colour_swatch = QLabel()
        self._colour_swatch.setFixedSize(56, 20)
        self._colour_swatch.setFrameShape(QFrame.StyledPanel)
        row.addWidget(self._colour_swatch)
        self._colour_reset = QPushButton("Theme default")
        self._colour_reset.setObjectName("appearance_colour_reset")
        self._colour_reset.clicked.connect(self._reset_colour)
        row.addWidget(self._colour_reset)
        row.addStretch(1)
        return group

    def _build_ports_group(self, node) -> QWidget:
        group = QGroupBox("Ports and preview")
        form = QFormLayout(group)

        self._labels_combo = QComboBox()
        self._labels_combo.setObjectName("appearance_port_labels_combo")
        for label, value in (("Canvas default", None), ("Show", True),
                             ("Hide", False)):
            self._labels_combo.addItem(label, value)
        self._labels_combo.currentIndexChanged.connect(self._push_port_labels)
        form.addRow("Port names", self._labels_combo)

        self._flow_combo = QComboBox()
        self._flow_combo.setObjectName("appearance_flow_pins_combo")
        for label, value in (("Canvas default", None), ("Show", True),
                             ("Hide", False)):
            self._flow_combo.addItem(label, value)
        self._flow_combo.setToolTip(
            "The two pins an order edge is drawn between — \"run this node "
            "after that one\". Hidden unless something is wired to them.")
        self._flow_combo.currentIndexChanged.connect(self._push_flow_pins)
        form.addRow("Flow pins", self._flow_combo)

        # Only worth offering where it means something: one pin a side is
        # already as gathered as it gets.
        item = self._scene.node_items.get(self._node_id)
        self._collapse_check = None
        if item is not None and item.collapsible():
            self._collapse_check = QCheckBox("Gather the pins into the header")
            self._collapse_check.setObjectName("appearance_collapse_check")
            self._collapse_check.toggled.connect(self._push_collapsed)
            form.addRow("Collapse ports", self._collapse_check)

        self._preview_check = None
        if card_kind(node) in PREVIEW_TOGGLABLE_KINDS:
            self._preview_check = QCheckBox("Draw this node's contents")
            self._preview_check.setObjectName("appearance_preview_check")
            self._preview_check.toggled.connect(self._push_preview)
            form.addRow("Canvas preview", self._preview_check)
        return group

    # -------------------------------------------------------------- loading

    def _load(self, node) -> None:
        if self._plain:
            self._shape_combo.setCurrentIndex(
                max(0, self._shape_combo.findData(node.compact_view)))
            self._image_uri = node.mark_image
            if node.mark_image:
                self._image_radio.setChecked(True)
            elif node.mark_text.strip():
                self._text_radio.setChecked(True)
            elif node.mark in marks.MARK_NAMES:
                self._mark_radio.setChecked(True)
            else:
                self._default_radio.setChecked(True)
            if node.mark_text:
                self._text_edit.setText(node.mark_text)
            # Whatever the node draws today is the swatch that starts
            # selected, override or not, so the grid opens showing where you
            # are.
            current = marks.mark_for(node)
            for button in self._swatches.buttons():
                if button.name == current:
                    button.setChecked(True)
                    break
            self._refresh_preview()
        self._refresh_colour()
        self._labels_combo.setCurrentIndex(
            max(0, self._labels_combo.findData(node.port_labels)))
        self._flow_combo.setCurrentIndex(
            max(0, self._flow_combo.findData(node.flow_pins)))
        if self._collapse_check is not None:
            self._collapse_check.setChecked(bool(node.ports_collapsed))
        if self._preview_check is not None:
            self._preview_check.setChecked(bool(node.canvas_preview_enabled))

    def _node(self):
        return self._graph.nodes.get(self._node_id)

    # ------------------------------------------------------------ applying
    #
    # Every control goes through _apply. It answers the two questions a
    # selection raises — which of these nodes does this mean anything for,
    # and how does it come back off the undo stack — in one place, so the
    # individual push methods below stay one-liners whether they are writing
    # to one node or to nine.

    def _targets(self, predicate=None) -> list:
        """The nodes a control reaches: all of them, or the ones a predicate
        says the setting means something for."""
        nodes = [(i, self._graph.nodes.get(i)) for i in self._node_ids]
        return [i for i, node in nodes
                if node is not None and (predicate is None or predicate(node))]

    def _apply(self, text: str, push, predicate=None) -> None:
        """Send one change to every node it applies to.

        A single node is pushed bare, exactly as it was before this dialog
        learned to take a selection — which keeps the mark and colour
        commands merging, so trying marks on for size stays one step back
        rather than sixteen. Several become one macro; merging inside a macro
        is not a thing Qt does, so a selection pays sixteen steps for the same
        browse. That is the right way round: the undo entry then matches what
        was actually done to how many nodes.
        """
        targets = self._targets(predicate)
        if not targets:
            return
        if len(targets) == 1:
            push(targets[0])
            return
        stack = self._scene.undo_stack
        stack.beginMacro(f"{text} ({len(targets)})")
        for node_id in targets:
            push(node_id)
        stack.endMacro()

    # ------------------------------------------------------------- applying

    def _push_shape(self, _index: int) -> None:
        if self._loading:
            return
        value = self._shape_combo.currentData()
        # a card is drawn at its content's size either way, so the shape is
        # not a thing it has
        self._apply("change node view",
                    lambda i: self._scene.push_compact_view(i, value),
                    renders_plain)

    def _push_port_labels(self, _index: int) -> None:
        if self._loading:
            return
        from ..commands import SetPortLabelsCommand
        value = self._labels_combo.currentData()
        self._apply("change port names", lambda i: self._scene.undo_stack.push(
            SetPortLabelsCommand(self._graph, i, value)))

    def _push_flow_pins(self, _index: int) -> None:
        if self._loading:
            return
        from ..commands import SetFlowPinsCommand
        value = self._flow_combo.currentData()
        self._apply("change flow pins", lambda i: self._scene.undo_stack.push(
            SetFlowPinsCommand(self._graph, i, value)))

    def _push_collapsed(self, collapsed: bool) -> None:
        if self._loading:
            return
        from ..commands import SetPortsCollapsedCommand

        def collapsible(node) -> bool:
            item = self._scene.node_items.get(node.id)
            return item is not None and item.collapsible()

        self._apply("collapse ports", lambda i: self._scene.undo_stack.push(
            SetPortsCollapsedCommand(self._graph, i, collapsed)), collapsible)

    def _push_preview(self, enabled: bool) -> None:
        if self._loading:
            return
        from ..commands import SetPreviewEnabledCommand
        self._apply(
            "toggle canvas preview",
            lambda i: self._scene.undo_stack.push(
                SetPreviewEnabledCommand(self._graph, i, enabled)),
            lambda node: card_kind(node) in PREVIEW_TOGGLABLE_KINDS)

    def _push_mark(self) -> None:
        """Send whatever the mark controls now say. Merged by the command, so
        trying marks on for size is one undo step."""
        if self._loading:
            return
        node = self._node()
        if node is None:
            return
        chosen = self._current_mark()
        self._apply(
            "change node mark",
            lambda i: self._scene.push_node_mark(i, *chosen),
            # nothing to draw a mark on, and no point spending an undo step
            # on a node that already wears this one
            lambda target: (renders_plain(target)
                            and chosen != (target.mark, target.mark_text,
                                           target.mark_image)))

    def _current_mark(self) -> tuple[str, str, str]:
        """(mark, mark_text, mark_image) — all empty meaning "the default"."""
        if self._image_radio.isChecked() and self._image_uri:
            return "", "", self._image_uri
        if self._text_radio.isChecked():
            text = self._text_edit.text().strip()
            # an empty text box is not a choice — fall through to the default
            return ("", text, "") if text else ("", "", "")
        if self._mark_radio.isChecked():
            checked = self._swatches.checkedButton()
            if checked is not None:
                return checked.name, "", ""
        return "", "", ""

    def _on_mark_mode_changed(self, checked: bool) -> None:
        if checked:
            self._push_mark()

    def _on_swatch_clicked(self, _button) -> None:
        # setChecked fires the toggled handler only when the radio was *not*
        # already on, so the explicit push covers picking a second swatch.
        # _push_mark is a no-op when nothing actually changed.
        self._mark_radio.setChecked(True)
        self._push_mark()

    def _on_text_edited(self, _text: str) -> None:
        self._text_radio.setChecked(True)
        self._push_mark()

    def _choose_image(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Node mark image", "",
            "Images (*.png *.jpg *.jpeg *.gif *.webp *.svg *.bmp *.ico "
            "*.tif *.tiff);;All files (*)")
        if not path:
            return
        try:
            self._image_uri = marks.encode_mark_image(path)
        except marks.MarkImageError as exc:
            QMessageBox.warning(self, "Node mark", str(exc))
            return
        self._image_radio.setChecked(True)
        self._refresh_preview()
        self._push_mark()

    def _refresh_preview(self) -> None:
        """Show the picture at the size the node will draw it, so what you
        see here is what lands on the canvas."""
        if not self._image_uri:
            self._image_preview.clear()
            self._image_hint.setText("PNG, JPEG, SVG, animated GIF/WebP")
            return
        from flograph.core.images import resolve_source
        try:
            data, _mime, _path = resolve_source(self._image_uri)
        except (ValueError, OSError):
            self._image_preview.clear()
            return
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        if not pixmap.isNull():
            self._image_preview.setPixmap(pixmap.scaled(
                _PREVIEW, _PREVIEW, Qt.KeepAspectRatio,
                Qt.SmoothTransformation))
        # Stored inside the project file, so the size is the user's business
        self._image_hint.setText(
            f"{len(data) // 1000 or 1} KB, saved in the project")

    def _choose_colour(self) -> None:
        node = self._node()
        if node is None:
            return
        current = QColor(node.color) if node.color else QColor(
            theme.NODE_HEADER)
        colour = QColorDialog.getColor(current, self, "Node colour")
        if colour.isValid():
            name = colour.name()
            self._apply("change node colour",
                        lambda i: self._scene.push_node_color(i, name))
            self._refresh_colour()

    def _reset_colour(self) -> None:
        self._apply("reset node colour",
                    lambda i: self._scene.push_node_color(i, None))
        self._refresh_colour()

    def _refresh_colour(self) -> None:
        node = self._node()
        own = node.color if node is not None else None
        # theme colours are QColors and a node's own is a hex string; a
        # stylesheet wants the string form of either
        colour = QColor(own) if own else QColor(theme.NODE_HEADER)
        self._colour_swatch.setStyleSheet(
            f"background: {colour.name()}; "
            f"border: 1px solid {QColor(theme.NODE_BORDER).name()};")
        self._colour_reset.setEnabled(bool(own))
