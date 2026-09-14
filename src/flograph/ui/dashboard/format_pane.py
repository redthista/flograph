"""FormatPane: the panel down the right of a dashboard page that says how
the page and its visuals look.

Two sections, the Power BI arrangement. **Selected visual** formats the
tiles that are selected, on their own. **Page** sets the background and the
look every tile on the page takes: frame, corners, fill, padding, shadow,
title. A setting left on *Page* for a tile follows the page's, and one left
on *Default* for the page follows the card tiles always were, so a page is
made coherent by setting its look once and overriding only the exceptions.
See core.tile_style for the model.

Every change is one undo step through the stack; a spin box stepped five
times is one step, not five (see SetPageLookCommand). The pane writes
nothing behind the model's back — it edits through commands and redraws
from the graph's events, so undo, a load and another page's edits all reach
it the same way.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDoubleSpinBox, QFormLayout, QFrame,
    QLabel, QLineEdit, QMenu, QPushButton, QScrollArea,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from flograph.core.tile_style import (
    CARD_LOOK, LIMITS, NOTE_LOOK, PAGE_FIELDS, TRANSPARENT, TileStyle,
    clean_background, resolve,
)

from ..commands import SetPageLookCommand, SetTileStylesCommand

#: Colours that sit well together on a dashboard: dark grounds and light
#: ones, and a handful of accents. Custom… takes any other.
SWATCHES = (
    ("Ink", "#17181c"), ("Charcoal", "#1b1c20"), ("Slate", "#2a2c33"),
    ("Graphite", "#363943"), ("Steel", "#4b5563"), ("Silver", "#9ca3af"),
    ("Cloud", "#e5e7eb"), ("Mist", "#f3f4f6"), ("White", "#ffffff"),
    ("Navy", "#1e3a5f"), ("Blue", "#2563eb"), ("Teal", "#0d9488"),
    ("Green", "#16a34a"), ("Amber", "#d97706"), ("Red", "#dc2626"),
    ("Violet", "#7c3aed"),
)
_SWATCH_NAMES = {hexv: name for name, hexv in SWATCHES}

#: (step, decimals, suffix) for each number field.
_NUMBER_SPECS = {
    "frame_width": (0.5, 1, " px"),
    "radius": (1.0, 0, " px"),
    "padding": (1.0, 0, " px"),
    "title_size": (0.5, 1, " pt"),
}

#: The fields, grouped as the pane shows them: (group, rows), each row
#: (field, widget kind, label).
GROUPS = (
    ("Title", (
        ("title", "toggle", "Show title"),
        ("title_text", "text", "Title text"),
        ("title_size", "number", "Text size"),
        ("title_bold", "toggle", "Bold"),
        ("title_align", "align", "Alignment"),
        ("title_color", "colour", "Text colour"),
        ("title_background", "colour", "Bar colour"),
    )),
    ("Frame", (
        ("frame", "toggle", "Show frame"),
        ("frame_color", "colour", "Colour"),
        ("frame_width", "number", "Width"),
        ("radius", "number", "Corners"),
    )),
    ("Background", (
        ("background", "colour", "Fill"),
        ("padding", "number", "Padding"),
        ("shadow", "toggle", "Shadow"),
    )),
    ("Buttons", (
        ("maximize", "toggle", "Maximize button"),
    )),
)

#: Kinds a format does not apply to — see TileItem.styleable.
_STYLE_FREE = ("button", "pagelinks")


def colour_name(value) -> str:
    if value is None:
        return "theme"
    if value == TRANSPARENT:
        return "Transparent"
    return _SWATCH_NAMES.get(value, value)


def _swatch_icon(value) -> QIcon:
    pixmap = QPixmap(14, 14)
    if value == TRANSPARENT or value is None:
        # a checkerboard: the conventional picture of "nothing here"
        pixmap.fill(QColor("#ffffff"))
        painter = QPainter(pixmap)
        for x in range(0, 14, 7):
            for y in range(0, 14, 7):
                if (x + y) // 7 % 2 == 0:
                    painter.fillRect(x, y, 7, 7, QColor("#c7c7c7"))
        painter.end()
    else:
        pixmap.fill(QColor(value))
    return QIcon(pixmap)


def _number_text(value: float, decimals: int) -> str:
    text = f"{value:.{decimals}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


# ----------------------------------------------------------------- fields


class ColourField(QToolButton):
    """A colour, picked from a menu: the inherited one, Transparent where a
    field allows it, the swatches, and Custom… for Qt's colour dialog."""

    changed = Signal(object)   # "#rrggbb", TRANSPARENT, or None to inherit

    def __init__(self, allow_transparent: bool, parent=None) -> None:
        super().__init__(parent)
        self._value: Optional[str] = None
        self._inherited: Optional[str] = None
        self._word = "Default"
        self.setPopupMode(QToolButton.InstantPopup)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        menu = QMenu(self)
        self._inherit_action = menu.addAction("Default")
        self._inherit_action.triggered.connect(lambda: self.pick(None))
        if allow_transparent:
            clear = menu.addAction(_swatch_icon(TRANSPARENT), "Transparent")
            clear.triggered.connect(lambda: self.pick(TRANSPARENT))
        menu.addSeparator()
        for name, hexv in SWATCHES:
            action = menu.addAction(_swatch_icon(hexv), name)
            action.triggered.connect(lambda _=False, v=hexv: self.pick(v))
        menu.addSeparator()
        custom = menu.addAction("Custom…")
        custom.triggered.connect(self._custom)
        self.setMenu(menu)
        self._refresh()

    def value(self) -> Optional[str]:
        return self._value

    def set_value(self, value, inherited, word: str) -> None:
        self._value = value
        self._inherited = inherited
        self._word = word
        self._refresh()

    def pick(self, value) -> None:
        if value == self._value:
            return
        self._value = value
        self._refresh()
        self.changed.emit(value)

    def _custom(self) -> None:
        start = self._value or self._inherited
        initial = QColor(start if start and start != TRANSPARENT
                         else "#4a7ab3")
        picked = QColorDialog.getColor(initial, self.window(), "Pick a colour")
        if picked.isValid():
            self.pick(picked.name())

    def _refresh(self) -> None:
        inherited = f"{self._word} ({colour_name(self._inherited)})"
        self._inherit_action.setText(inherited)
        if self._value is None:
            self.setText(inherited)
            self.setIcon(_swatch_icon(self._inherited))
        else:
            self.setText(colour_name(self._value))
            self.setIcon(_swatch_icon(self._value))


class ChoiceField(QComboBox):
    """A few fixed choices, the first always "inherit"."""

    changed = Signal(object)

    def __init__(self, choices, parent=None) -> None:
        super().__init__(parent)
        self._describe = dict(choices)
        self.addItem("Default", None)
        for value, label in choices:
            self.addItem(label, value)
        self.currentIndexChanged.connect(
            lambda index: self.changed.emit(self.itemData(index)))

    def value(self):
        return self.currentData()

    def set_value(self, value, inherited, word: str) -> None:
        self.blockSignals(True)
        described = self._describe.get(inherited, str(inherited)).lower()
        self.setItemText(0, f"{word} ({described})")
        index = 0
        for i in range(1, self.count()):
            data = self.itemData(i)
            if value is not None and data == value \
                    and type(data) is type(value):
                index = i
        self.setCurrentIndex(index)
        self.blockSignals(False)


class NumberField(QDoubleSpinBox):
    """A number, whose lowest step is "inherit" and says what that is."""

    changed = Signal(object)

    def __init__(self, name: str, parent=None) -> None:
        super().__init__(parent)
        low, high = LIMITS[name]
        step, decimals, suffix = _NUMBER_SPECS[name]
        self._suffix = suffix
        self.setDecimals(decimals)
        self.setSingleStep(step)
        self.setRange(low - step, high)
        self.setSuffix(suffix)
        # a value typed in is committed once, not once per keystroke
        self.setKeyboardTracking(False)
        self.valueChanged.connect(self._emit)

    def value_or_none(self):
        return None if self.value() <= self.minimum() else self.value()

    def contextMenuEvent(self, event) -> None:
        # a spin box's menu is its line edit's, and the same leftovers reach
        # it — see GuardedLineEdit
        from .. import menu_guard
        if menu_guard.stray(event):
            event.accept()
            return
        super().contextMenuEvent(event)

    def set_value(self, value, inherited, word: str) -> None:
        self.blockSignals(True)
        shown = _number_text(float(inherited), self.decimals())
        self.setSpecialValueText(f"{word} ({shown}{self._suffix})")
        self.setValue(self.minimum() if value is None else float(value))
        self.blockSignals(False)

    def _emit(self, value: float) -> None:
        self.changed.emit(None if value <= self.minimum() else value)


class GuardedLineEdit(QLineEdit):
    """A line edit that won't answer a menu's leftovers with its own Cut /
    Copy / Paste menu. On Wayland a page tab's right-click arrives after
    the tab's menu has closed, at whatever is then under the pointer — and
    locking or unlocking a page puts these boxes there. See ui/menu_guard."""

    def contextMenuEvent(self, event) -> None:
        from .. import menu_guard
        if menu_guard.stray(event):
            event.accept()
            return
        super().contextMenuEvent(event)


class TextField(GuardedLineEdit):
    changed = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setClearButtonEnabled(True)
        self.editingFinished.connect(
            lambda: self.changed.emit(self.text() if self.text().strip()
                                      else None))

    def set_value(self, value, inherited, word: str) -> None:
        text = value or ""
        if text != self.text():
            self.blockSignals(True)
            self.setText(text)
            self.blockSignals(False)


def _make_field(name: str, kind: str) -> QWidget:
    if kind == "toggle":
        return ChoiceField(((True, "On"), (False, "Off")))
    if kind == "align":
        return ChoiceField((("left", "Left"), ("center", "Centre"),
                            ("right", "Right")))
    if kind == "number":
        return NumberField(name)
    if kind == "colour":
        return ColourField(allow_transparent=name in ("background",
                                                      "title_background"))
    return TextField()


class StyleForm(QWidget):
    """The rows for one TileStyle: the page's, or the selected tiles'."""

    changed = Signal(str, object)   # field name, new value (None = inherit)

    def __init__(self, inherit_word: str, fields=None, parent=None) -> None:
        super().__init__(parent)
        self._word = inherit_word
        self._fields: dict = {}
        self._forms: dict = {}     # field name -> the form its row is in
        self._groups: dict = {}
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)
        for group, rows in GROUPS:
            box = QWidget()
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(0, 0, 0, 0)
            box_layout.setSpacing(3)
            heading = QLabel(group.upper())
            heading.setStyleSheet("color: palette(mid); font-size: 8pt;"
                                  " font-weight: 600;")
            box_layout.addWidget(heading)
            form = QFormLayout()
            form.setContentsMargins(0, 0, 0, 0)
            form.setHorizontalSpacing(8)
            form.setVerticalSpacing(3)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            for name, kind, label in rows:
                if fields is not None and name not in fields:
                    continue
                field = _make_field(name, kind)
                field.changed.connect(
                    lambda value, name=name: self.changed.emit(name, value))
                form.addRow(label, field)
                self._fields[name] = field
                self._forms[name] = form
            box_layout.addLayout(form)
            column.addWidget(box)
            self._groups[group] = box

    def field(self, name: str):
        return self._fields[name]

    def set_values(self, own: TileStyle, inherited: TileStyle) -> None:
        for name, field in self._fields.items():
            field.set_value(getattr(own, name), getattr(inherited, name),
                            self._word)

    def set_group_visible(self, group: str, visible: bool) -> None:
        self._groups[group].setVisible(visible)

    def set_row_visible(self, name: str, visible: bool) -> None:
        self._forms[name].setRowVisible(self._fields[name], visible)

    def row_visible(self, name: str) -> bool:
        return not self._fields[name].isHidden()


class Section(QWidget):
    """A heading that folds its body away."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.setAutoRaise(True)
        self.toggle.setArrowType(Qt.DownArrow)
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setStyleSheet("QToolButton { font-weight: bold; }")
        self.toggle.toggled.connect(self._on_toggled)
        layout.addWidget(self.toggle)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(6, 0, 0, 4)
        self.body_layout.setSpacing(6)
        layout.addWidget(self.body)

    def set_title(self, title: str) -> None:
        self.toggle.setText(title)

    def _on_toggled(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)


# ------------------------------------------------------------------- pane


class FormatPane(QWidget):
    def __init__(self, graph, undo_stack, page_id: str, parent=None) -> None:
        super().__init__(parent)
        self._graph = graph
        self._undo = undo_stack
        self._page_id = page_id
        self._selection: list = []
        self.setMinimumWidth(230)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 6, 6, 6)
        outer.setSpacing(4)
        header = QLabel("Format")
        header.setStyleSheet("font-weight: bold;")
        outer.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 4, 0)
        column.setSpacing(10)

        # the selection first: picking a tile is what someone formatting a
        # page does most, and its settings should not be under the page's
        self.tile_section = Section("Selected Visual")
        self.selection_note = QLabel()
        self.selection_note.setWordWrap(True)
        self.selection_note.setStyleSheet("color: palette(mid);")
        self.tile_section.body_layout.addWidget(self.selection_note)
        self.tile_form = StyleForm("Page")
        self.tile_form.changed.connect(self._on_tile_field)
        self.tile_section.body_layout.addWidget(self.tile_form)
        self.reset_button = QPushButton("Reset to the Page's Format")
        self.reset_button.setToolTip("Take away this visual's own format, "
                                     "so it looks like the rest of the page")
        self.reset_button.clicked.connect(self._reset_selection)
        self.tile_section.body_layout.addWidget(self.reset_button)
        column.addWidget(self.tile_section)

        self.page_section = Section("Page")
        page_form = QFormLayout()
        page_form.setContentsMargins(0, 0, 0, 0)
        page_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.background = ColourField(allow_transparent=False)
        self.background.changed.connect(self._on_background)
        page_form.addRow("Background", self.background)
        self.page_section.body_layout.addLayout(page_form)
        caption = QLabel("Every visual on this page:")
        caption.setStyleSheet("color: palette(mid);")
        self.page_section.body_layout.addWidget(caption)
        self.page_form = StyleForm("Default", fields=PAGE_FIELDS)
        self.page_form.changed.connect(self._on_page_field)
        self.page_section.body_layout.addWidget(self.page_form)
        self.clear_all_button = QPushButton("Clear Every Visual's Own Format")
        self.clear_all_button.setToolTip(
            "Put every visual on this page back to the page's format")
        self.clear_all_button.clicked.connect(self._clear_all_tiles)
        self.page_section.body_layout.addWidget(self.clear_all_button)
        column.addWidget(self.page_section)
        column.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        events = graph.events
        self._event_subs = [
            (events.page_changed, self._on_page_changed),
            (events.tile_changed, self._on_tile_event),
            (events.tile_added, self._on_tile_event),
            (events.tile_removed, self._on_tile_event),
            (events.label_changed, self._on_label_changed),
        ]
        for event, callback in self._event_subs:
            event.connect(callback)
        self.refresh()

    def dispose(self) -> None:
        """Core events hold strong refs — disconnect on page removal."""
        for event, callback in self._event_subs:
            event.disconnect(callback)
        self._event_subs = []

    # -------------------------------------------------------------- model

    def _page(self):
        return self._graph.pages.get(self._page_id)

    def _kind(self, tile) -> Optional[str]:
        from ..canvas.node_item import card_kind
        node = self._graph.nodes.get(tile.node_id)
        return card_kind(node) if node is not None else None

    def targets(self) -> list:
        """The selected tiles a format applies to, in selection order."""
        page = self._page()
        if page is None:
            return []
        return [page.tiles[tile_id] for tile_id in self._selection
                if tile_id in page.tiles
                and self._kind(page.tiles[tile_id]) not in _STYLE_FREE]

    def set_selection(self, tile_ids) -> None:
        self._selection = list(tile_ids)
        self.refresh()

    def _on_page_changed(self, page) -> None:
        if page.id == self._page_id:
            self.refresh()

    def _on_tile_event(self, page_id: str, *args) -> None:
        if page_id == self._page_id:
            self.refresh()

    def _on_label_changed(self, node_id: str) -> None:
        # the title placeholder is the node's name
        self.refresh()

    # ------------------------------------------------------------ refresh

    def refresh(self) -> None:
        page = self._page()
        if page is None:
            return
        self.background.set_value(page.background, None, "Theme")
        self.page_form.set_values(page.tile_style, CARD_LOOK)
        self.clear_all_button.setEnabled(
            any(not tile.style.is_empty() for tile in page.tiles.values()))

        targets = self.targets()
        if not targets:
            self.tile_section.set_title("Selected Visual")
            self.tile_form.hide()
            self.reset_button.hide()
            self.selection_note.setText(
                "Buttons and page links draw their own face, so there is "
                "nothing on them to format."
                if self._selection else
                "Select a visual on the page to format it on its own. "
                "Anything left on “Page” follows the page's format below.")
            return

        first = targets[0]
        notes_only = all(self._kind(tile) == "note" for tile in targets)
        inherited = resolve(page.tile_style, None,
                            NOTE_LOOK if notes_only else CARD_LOOK)
        self.tile_form.set_values(first.style, inherited)
        # a note is its text, with no title bar to format — only the
        # colour its words are drawn in, which the title's text colour is
        for name in ("title", "title_text", "title_size", "title_bold",
                     "title_align", "title_background"):
            self.tile_form.set_row_visible(name, not notes_only)
        # nor anything to maximize
        self.tile_form.set_group_visible("Buttons", not notes_only)
        title = self.tile_form.field("title_text")
        node = self._graph.nodes.get(first.node_id)
        title.setPlaceholderText(node.label if node is not None else "")
        # one name for several tiles would name them all the same
        title.setEnabled(len(targets) == 1)
        self.tile_form.show()
        self.reset_button.show()
        self.reset_button.setEnabled(
            any(not tile.style.is_empty() for tile in targets))
        if len(targets) == 1:
            self.tile_section.set_title("Selected Visual")
            self.selection_note.setText(node.label if node is not None
                                        else "A visual whose node was deleted")
        else:
            self.tile_section.set_title(f"{len(targets)} Selected Visuals")
            self.selection_note.setText(
                "A change applies to all of them. The settings shown are "
                "the first one's.")

    # -------------------------------------------------------------- edits

    def _on_background(self, value) -> None:
        page = self._page()
        if page is None or clean_background(value) == page.background:
            return
        self._undo.push(SetPageLookCommand(
            self._graph, self._page_id, background=value, key="background",
            text="page background"))

    def _on_page_field(self, name: str, value) -> None:
        page = self._page()
        if page is None:
            return
        style = page.tile_style.with_value(name, value)
        if style == page.tile_style:
            return
        self._undo.push(SetPageLookCommand(
            self._graph, self._page_id, tile_style=style, key=name,
            text="format page"))

    def _on_tile_field(self, name: str, value) -> None:
        targets = self.targets()
        styles = {tile.id: tile.style.with_value(name, value)
                  for tile in targets}
        if all(styles[tile.id] == tile.style for tile in targets):
            return
        self._undo.push(SetTileStylesCommand(
            self._graph, self._page_id, styles, key=name,
            text="format visual" if len(styles) == 1 else "format visuals"))

    def _reset_selection(self) -> None:
        styles = {tile.id: TileStyle() for tile in self.targets()
                  if not tile.style.is_empty()}
        if styles:
            self._undo.push(SetTileStylesCommand(
                self._graph, self._page_id, styles,
                text="reset visual format"))

    def _clear_all_tiles(self) -> None:
        page = self._page()
        if page is None:
            return
        styles = {tile.id: TileStyle() for tile in page.tiles.values()
                  if not tile.style.is_empty()}
        if styles:
            self._undo.push(SetTileStylesCommand(
                self._graph, self._page_id, styles,
                text="clear visuals' own format"))
