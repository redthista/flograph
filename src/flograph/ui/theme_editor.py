"""Tools ▸ Theme Customiser: edit every colour and style choice of a theme.

Two views of one thing. **Colours** is a list of every setting with a colour
swatch, a hex box and the right control for each. **Text** is the whole theme
as TOML in the code editor, every colour shown on a swatch of itself, with a
colour dialog on double-click. Either one changes the same *override* table —
only what differs from the theme it started from — and the app previews it
live by handing `theme.apply_theme` a theme built from base + overrides.

Nothing is written until **Save theme**; closing without saving puts the saved
theme back. A saved theme is an ordinary `<user data dir>/themes/<name>.toml`
that lists just its differences (`themes.save_user`), so it can be shared,
hand-edited, and used as `based_on` by another.
"""
from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDialog,
    QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QListWidget, QPushButton, QSpinBox, QTabWidget, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import theme
from .editor.code_editor import CodeEditor
from .editor.theme_text import (HexColourPicker, ThemeTextHighlighter,
                                swatch_selections)
from .themes import (BUILTIN, SECTIONS, ThemeError, load, meta, save_user,
                     slug, with_overrides)
from .themes.check import check
from .themes.reference import describe
from .themes.text import (CHOICES, DEFAULT_RANGE, RANGES, SECTION_TITLES,
                          find_colour, full_text, parse_text)

PREVIEW_DELAY_MS = 250
TAB_COLOURS, TAB_TEXT = 0, 1


def nice(key: str) -> str:
    """`CANVAS_BG` / `tab_selected` -> `Canvas bg` / `Tab selected`."""
    return key.replace("_", " ").lower().capitalize()


def is_colour(value) -> bool:
    return (isinstance(value, str) and value.startswith("#")
            and QColor(value).isValid())


class _Row(QWidget):
    """The value editor of one setting: a swatch + hex box for a colour, a
    spin box / tick box / drop-down otherwise, and a button that puts the
    base theme's value back."""

    def __init__(self, section: str, key: str, value, on_edit, on_reset):
        super().__init__()
        self._on_edit = on_edit
        self._section, self._key = section, key
        self._silent = False
        self._last = value if is_colour(value) else "#000000"
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.swatch = self.hex = self.spin = self.tick = self.combo = None
        if is_colour(value):
            self.swatch = QPushButton()
            self.swatch.setFixedSize(34, 20)
            self.swatch.setCursor(Qt.PointingHandCursor)
            self.swatch.setToolTip("Pick a colour")
            self.swatch.clicked.connect(self._pick)
            self.hex = QLineEdit()
            self.hex.setMaxLength(7)
            self.hex.setFixedWidth(76)
            self.hex.editingFinished.connect(self._typed)
            lay.addWidget(self.swatch)
            lay.addWidget(self.hex)
        elif isinstance(value, bool):
            self.tick = QCheckBox()
            self.tick.toggled.connect(lambda v: self._emit(bool(v)))
            lay.addWidget(self.tick)
        elif isinstance(value, float):
            self.spin = QDoubleSpinBox()
            self.spin.setRange(0.0, 1.0)
            self.spin.setSingleStep(0.02)
            self.spin.setDecimals(2)
            self.spin.valueChanged.connect(lambda v: self._emit(float(v)))
            lay.addWidget(self.spin)
        elif isinstance(value, int):
            self.spin = QSpinBox()
            self.spin.setRange(*RANGES.get(key, DEFAULT_RANGE))
            self.spin.setSuffix(" px")
            self.spin.valueChanged.connect(lambda v: self._emit(int(v)))
            lay.addWidget(self.spin)
        else:
            self.combo = QComboBox()
            self.combo.addItems(list(CHOICES.get(key, (str(value),))))
            self.combo.currentTextChanged.connect(self._emit)
            lay.addWidget(self.combo)
        lay.addStretch(1)
        self.reset = QToolButton()
        self.reset.setText("↺")
        self.reset.setToolTip("Put back the starting theme's value")
        self.reset.setAutoRaise(True)
        self.reset.clicked.connect(lambda: on_reset(section, key))
        lay.addWidget(self.reset)
        self.set_value(value)

    def set_value(self, value) -> None:
        self._silent = True
        try:
            if self.swatch is not None:
                self._last = value
                self.hex.setText(value)
                self.swatch.setStyleSheet(
                    f"QPushButton {{ background: {value};"
                    " border: 1px solid #808080; border-radius: 3px; }")
            elif self.tick is not None:
                self.tick.setChecked(bool(value))
            elif self.spin is not None:
                self.spin.setValue(value)
            elif self.combo is not None:
                self.combo.setCurrentText(str(value))
        finally:
            self._silent = False

    def _emit(self, value) -> None:
        if not self._silent:
            self._on_edit(self._section, self._key, value)

    def _pick(self) -> None:
        start = QColor(self._last)
        dialog = QColorDialog(start, self.window())
        dialog.setWindowTitle(nice(self._key))
        dialog.currentColorChanged.connect(self._set_from_colour)
        if dialog.exec() != QDialog.Accepted:
            self._set_from_colour(start)      # cancelled: back to where it was

    def _set_from_colour(self, colour: QColor) -> None:
        if colour.isValid():
            value = colour.name().lower()
            self.set_value(value)
            self._emit(value)

    def _typed(self) -> None:
        text = self.hex.text().strip()
        if len(text) == 6 and not text.startswith("#"):
            text = "#" + text
        if len(text) == 7 and is_colour(text):
            self.set_value(text.lower())
            self._emit(text.lower())
        else:                       # not a colour: put back what was there
            self.hex.setText(self._last)


def _pixel_at(widget, global_pos):
    """The colour painted at `global_pos`, read from a render of the window
    rather than from the screen (a Wayland client may not read the screen).
    A web view card renders blank this way; it has no theme colours."""
    top = widget.window()
    pixmap = top.grab()
    at = top.mapFromGlobal(global_pos)
    ratio = pixmap.devicePixelRatio()
    x, y = int(at.x() * ratio), int(at.y() * ratio)
    image = pixmap.toImage()
    if not (0 <= x < image.width() and 0 <= y < image.height()):
        return None
    return image.pixelColor(x, y).name().lower()


# What a canvas item is styled by, by class name (the canvas paints from the
# theme directly, so there is no widget colour to read back).
_CANVAS_KEYS = {
    "NodeItem": ("Node", [("canvas", k) for k in (
        "NODE_BODY", "NODE_HEADER", "NODE_BORDER", "NODE_TEXT",
        "NODE_SUBTEXT", "SELECTION_OUTLINE", "NODE_HEADER_BROKEN",
        "NODE_BORDER_BROKEN", "BYPASS", "PIN_STALE", "PIN_HELD")]
        + [("status", k) for k in ("idle", "queued", "running", "done",
                                   "error")]),
    "PortItem": ("Port (colour is its data type)",
                 [("wires", k) for k in ("any", "dataframe", "series",
                                         "number", "string", "bool",
                                         "object", "figure", "flow")]),
    "ConnectionItem": ("Wire",
                       [("canvas", k) for k in ("WIRE_VALID", "WIRE_INVALID",
                                                "WIRE_PENDING")]
                       + [("wires", k) for k in ("any", "dataframe", "series",
                                                 "number", "string", "bool",
                                                 "object", "figure", "flow")]),
    "FrameItem": ("Frame", [("canvas", "FRAME_TITLE")]
                  + [("frame", k) for k in ("FRAME_FILL", "FRAME_TITLE_BAR",
                                            "FRAME_FOLDED", "FRAME_CHIP",
                                            "FRAME_CHIP_HOVER")]),
    "TileItem": ("Dashboard tile", [("canvas", "NODE_BODY"),
                                    ("canvas", "NODE_BORDER"),
                                    ("canvas", "NODE_TEXT"),
                                    ("canvas", "NODE_HEADER")]),
    "ShapeItem": ("Shape", [("canvas", "FRAME_TITLE"),
                            ("canvas", "NODE_BORDER")]),
}
_CANVAS_BACKGROUND = ("Canvas background", [("canvas", "CANVAS_BG"),
                                            ("canvas", "GRID_FINE"),
                                            ("canvas", "GRID_COARSE")])

# words in a widget's class/object name that point at settings of that name
_NAME_WORDS = ("dock", "tab", "menu", "status", "tool", "scroll", "title",
               "panel", "tip", "input", "combo", "line", "check", "button",
               "header", "list", "tree", "table", "editor", "gutter",
               "minimap", "log", "ribbon", "bar")

# a widget whose class says it belongs to a section of the theme
_SECTION_WORDS = (("titlebar", "chrome"), ("title_bar", "chrome"),
                  ("toolbar", "chrome"), ("windowframe", "chrome"),
                  ("codeeditor", "editor"), ("minimap", "canvas"),
                  ("graphicsview", "canvas"))

_STYLE_PROPS = (
    ("Text", re.compile(r"(?<![-\w])color\s*:\s*(#[0-9a-fA-F]{6})")),
    ("Background", re.compile(
        r"(?<![-\w])background(?:-color)?\s*:\s*(#[0-9a-fA-F]{6})")),
    ("Border", re.compile(
        r"(?<![-\w])border[-\w]*\s*:[^;{}]*?(#[0-9a-fA-F]{6})")),
)


class Element:
    """What was clicked: a name for it, and groups of settings that style
    it — (role, colour or None, [(section, key), ...])."""

    def __init__(self, title: str, groups: list) -> None:
        self.title = title
        self.groups = groups

    @property
    def keys(self) -> list:
        seen, out = set(), []
        for _, _, keys in self.groups:
            for key in keys:
                if key not in seen:
                    seen.add(key)
                    out.append(key)
        return out


def _canvas_element(widget, global_pos):
    """A canvas item (or the canvas itself) under the pointer, or None."""
    from PySide6.QtWidgets import QGraphicsView
    view = widget.parentWidget() if widget is not None else None
    if not isinstance(view, QGraphicsView):
        return None
    item = view.itemAt(view.mapFromGlobal(global_pos))
    while item is not None:
        for cls in type(item).__mro__:
            if cls.__name__ in _CANVAS_KEYS:
                label, keys = _CANVAS_KEYS[cls.__name__]
                return Element(label, [(label, None, keys)])
        item = item.parentItem()
    label, keys = _CANVAS_BACKGROUND
    return Element(label, [(label, None, keys)])


def element_at(global_pos, theme_) -> "Element | None":
    """The UI element under `global_pos` and the theme settings behind it.

    A canvas item is looked up by kind. Anything else is a widget: its
    colours are read off it — the pixel under the pointer (its background
    there), and `color:`/`background:`/`border:` in its own stylesheet or
    the nearest ancestor's — and matched to the settings that hold those
    colours, those whose names echo the widget's class ranked first."""
    from .themes.text import find_colour
    widget = QApplication.widgetAt(global_pos)
    if widget is None:
        return None
    found = _canvas_element(widget, global_pos)
    if found is not None:
        return found
    chain, w = [], widget
    while w is not None and len(chain) < 8:
        chain.append(w)
        w = w.parentWidget()
    name = (widget.objectName() or type(widget).__name__)
    words = " ".join(f"{type(c).__name__} {c.objectName()}"
                     for c in chain[:4]).lower()
    wanted = [word for word in _NAME_WORDS if word in words]

    own = {section for word, section in _SECTION_WORDS if word in words}

    def rank(key):
        low = key[1].lower()
        return (key[0] not in own,
                -sum(word in low or word in key[0] for word in wanted))

    colours = []                     # (role, hex)
    pixel = _pixel_at(widget, global_pos)
    if pixel:
        colours.append(("Background here", pixel))
    for role, pattern in _STYLE_PROPS:
        for c in chain:
            sheet = c.styleSheet()
            match = pattern.search(sheet) if sheet else None
            if match:
                colours.append((role, match.group(1).lower()))
                break
    groups, seen = [], set()
    for role, value in colours:
        if value in seen:
            continue
        seen.add(value)
        exact, near = find_colour(theme_, value)
        keys = sorted(exact, key=rank) if exact else [
            (s, k) for s, k, _ in near]
        label = role if exact else f"{role} (closest)"
        groups.append((label, value, keys))
    return Element(name, groups)


class _Dropper(QObject):
    """Application-wide: while on, the pointer is a crosshair, a left click
    anywhere in the app reports the colour under it instead of doing what it
    normally does, and Esc (or a right click) gives up."""

    picked = Signal(QPoint)         # where, in global coordinates
    stopped = Signal()

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.active = False

    def start(self) -> None:
        if self.active:
            return
        self.active = True
        QApplication.setOverrideCursor(QCursor(Qt.CrossCursor))
        QApplication.instance().installEventFilter(self)

    def stop(self) -> None:
        if not self.active:
            return
        self.active = False
        QApplication.instance().removeEventFilter(self)
        QApplication.restoreOverrideCursor()
        self.stopped.emit()

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        if kind == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.stop()
            return True
        if kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
                    QEvent.MouseButtonDblClick):
            if kind == QEvent.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    where = event.globalPosition().toPoint()
                    self.stop()
                    self.picked.emit(where)
                else:
                    self.stop()
            return True                 # no click reaches the app meanwhile
        return False


class ThemeCustomiser(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.setWindowTitle("Theme Customiser")
        self.setModal(False)
        self.resize(620, 760)
        self._window = window
        self._user_dir = theme.user_dir()
        self._previewing = False
        self._base = None
        self._over: dict = {}
        self._rows: dict = {}
        self._text_seen = ""          # the text last read, to spot a real edit
        self._text_stale = True       # the text no longer shows _over
        self._tree_stale = False      # the list no longer shows _over

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(PREVIEW_DELAY_MS)
        self._timer.timeout.connect(self._preview)
        self._text_timer = QTimer(self)
        self._text_timer.setSingleShot(True)
        self._text_timer.setInterval(PREVIEW_DELAY_MS)
        self._text_timer.timeout.connect(self._text_edited)

        root = QVBoxLayout(self)
        form = QFormLayout()
        self.start = QComboBox()
        self._names = [p for p in theme.theme_prefs() if p != "system"]
        self.start.addItems([theme.theme_label(n) for n in self._names])
        form.addRow("Start from", self.start)
        self.label = QLineEdit()
        self.label.setPlaceholderText("Name your theme, then Save theme")
        form.addRow("Theme name", self.label)
        self.kind = QComboBox()
        self.kind.addItem("Light", "light")
        self.kind.addItem("Dark", "dark")
        self.kind.setToolTip("Tells Qt whether the window is light or dark, "
                             "which decides the look of native pieces such "
                             "as scroll bars and dialogs.")
        form.addRow("Kind", self.kind)
        root.addLayout(form)

        pick = QHBoxLayout()
        self.btn_dropper = QPushButton("⌖  Select element")
        self.btn_dropper.setToolTip(
            "Click this, then click any part of the app — a panel, a title "
            "bar, a menu, a node, a wire — and the settings that style it "
            "come up here. Esc cancels.")
        self.btn_dropper.clicked.connect(self._start_dropper)
        pick.addWidget(self.btn_dropper)
        pick.addStretch(1)
        root.addLayout(pick)
        self._dropper = _Dropper(self)
        self._dropper.picked.connect(self._selected)
        self._dropper.stopped.connect(self._dropper_stopped)
        self._picked_keys = None        # (section, key) set the list is cut to

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        # -- Colours
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 6, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter settings…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        box.addWidget(self.search)
        self.banner = QWidget()
        banner = QHBoxLayout(self.banner)
        banner.setContentsMargins(0, 0, 0, 0)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        banner.addWidget(self.banner_text, 1)
        show_all = QPushButton("Show all")
        show_all.clicked.connect(self._clear_pick)
        banner.addWidget(show_all)
        self.banner.hide()
        box.addWidget(self.banner)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        box.addWidget(self.tree, 1)
        self.tabs.addTab(page, "Colours")

        # -- Text
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 6, 0, 0)
        hint = QLabel("The whole theme as text. Edit a value, or "
                      "double-click a colour to pick one; the app follows "
                      "as you type.")
        hint.setWordWrap(True)
        box.addWidget(hint)
        self.text = CodeEditor()
        self.text.setObjectName("theme_text")
        self.text.set_highlighter(ThemeTextHighlighter(self.text.document()))
        self._picker = HexColourPicker(self.text)
        self.text.extra_selections_hook = (
            lambda: swatch_selections(self.text))
        self.text.textChanged.connect(self._text_timer.start)
        box.addWidget(self.text, 1)
        self.tabs.addTab(page, "Text")

        # -- Preview: labelled examples of the theme in force
        from .theme_preview import ThemePreview
        self.tabs.addTab(ThemePreview(), "Preview")
        self.tabs.currentChanged.connect(self._tab_changed)

        # what the selected setting does (from themes.reference)
        self.help = QLabel()
        self.help.setWordWrap(True)
        self.help.setTextFormat(Qt.PlainText)
        self.tree.currentItemChanged.connect(self._show_help)
        root.addWidget(self.help)

        # checks: contrast and sanity warnings for the theme as it stands
        self.checks_toggle = QPushButton()
        self.checks_toggle.setFlat(True)
        self.checks_toggle.setCheckable(True)
        self.checks_toggle.toggled.connect(
            lambda on: self.checks_list.setVisible(on))
        root.addWidget(self.checks_toggle, 0, Qt.AlignLeft)
        self.checks_list = QListWidget()
        self.checks_list.setMaximumHeight(110)
        self.checks_list.setWordWrap(True)
        self.checks_list.setVisible(False)
        self.checks_list.itemClicked.connect(self._check_clicked)
        root.addWidget(self.checks_list)

        self.note = QLabel()
        self.note.setWordWrap(True)
        root.addWidget(self.note)

        row = QHBoxLayout()
        self.btn_reset = QPushButton("Reset all")
        self.btn_reset.setToolTip("Back to the starting theme")
        self.btn_reset.clicked.connect(self._reset_all)
        self.btn_folder = QPushButton("Open themes folder")
        self.btn_folder.setToolTip("Where saved themes live: one .toml each")
        self.btn_folder.clicked.connect(self._open_folder)
        self.btn_save = QPushButton("Save theme")
        self.btn_save.setToolTip("Write the theme under the name above and "
                                 "switch to it")
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self._save)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        row.addWidget(self.btn_reset)
        row.addWidget(self.btn_folder)
        row.addStretch(1)
        row.addWidget(self.btn_save)
        row.addWidget(self.btn_close)
        root.addLayout(row)

        current = theme.current().name
        self._load_base(current if current in self._names else "dark")
        self.start.currentIndexChanged.connect(
            lambda i: self._load_base(self._names[i]))

    # -------------------------------------------------------------- model

    def _load_base(self, name: str) -> None:
        try:
            self._base = load(name, self._user_dir)
        except ThemeError as exc:
            QMessageBox.warning(self, "Theme Customiser", str(exc))
            return
        self._over = {}
        self.start.blockSignals(True)
        self.start.setCurrentIndex(self._names.index(name))
        self.start.blockSignals(False)
        self.label.setText(self._base.label if not self._base.builtin
                           else f"{self._base.label} custom")
        self.kind.setCurrentIndex(0 if self._base.kind == "light" else 1)
        self._rebuild_views()
        self._refresh_note()
        self._refresh_checks()
        if self._previewing:
            self._schedule()

    def _value(self, section: str, key: str):
        return self._over.get(section, {}).get(key,
                                               self._base.get(section, key))

    def _rebuild_views(self) -> None:
        self._build_tree()
        self._set_text()

    def _build_tree(self) -> None:
        self.tree.clear()
        self._rows = {}
        bold = QFont(self.tree.font())
        bold.setBold(True)
        for section in SECTIONS:
            items = self._base.section(section)
            if not items:
                continue
            top = QTreeWidgetItem([SECTION_TITLES.get(section, section)])
            top.setFont(0, bold)
            self.tree.addTopLevelItem(top)
            for key in items:
                child = QTreeWidgetItem([nice(key)])
                child.setData(0, Qt.UserRole, (section, key))
                child.setToolTip(0, describe(section, key))
                top.addChild(child)
                row = _Row(section, key, self._value(section, key),
                           self._edited, self._reset_one)
                self.tree.setItemWidget(child, 1, row)
                self._rows[(section, key)] = (child, row)
                self._mark(section, key)
            top.setExpanded(section in ("ui", "canvas"))
        self.tree.resizeColumnToContents(0)
        self.tree.setColumnWidth(0, max(self.tree.columnWidth(0), 190))
        self._tree_stale = False
        if self.search.text():
            self._filter(self.search.text())

    def _set_text(self) -> None:
        merged = with_overrides(self._base, self._over)
        # `_text_seen` first, so the textChanged this causes is recognised as
        # ours. Not blockSignals: that also silenced the editor's own
        # blockCountChanged, so its line-number gutter kept the width of an
        # empty box and covered the first character of every line.
        self._text_seen = full_text(merged)
        self.text.setPlainText(self._text_seen)
        self.text.set_diagnostics([])
        self._text_stale = False

    def _mark(self, section: str, key: str) -> None:
        child, row = self._rows[(section, key)]
        changed = key in self._over.get(section, {})
        font = QFont(self.tree.font())
        font.setBold(changed)
        child.setFont(0, font)
        row.reset.setEnabled(changed)
        row.reset.setVisible(changed)

    def _refresh_note(self) -> None:
        n = sum(len(v) for v in self._over.values())
        self.note.setText(
            f"{n} setting{'s' if n != 1 else ''} changed from "
            f"{self._base.label}. Changes show live; nothing is saved until "
            "you press Save theme." if n else
            "Pick a colour or edit the text to start. Changes show live; "
            "nothing is saved until you press Save theme.")

    # ------------------------------------------------------------ editing

    def _edited(self, section: str, key: str, value) -> None:
        if value == self._base.get(section, key):
            self._over.get(section, {}).pop(key, None)
        else:
            self._over.setdefault(section, {})[key] = value
        self._text_stale = True
        self._mark(section, key)
        self._refresh_note()
        self._schedule()

    def _reset_one(self, section: str, key: str) -> None:
        self._over.get(section, {}).pop(key, None)
        _, row = self._rows[(section, key)]
        row.set_value(self._base.get(section, key))
        self._text_stale = True
        self._mark(section, key)
        self._refresh_note()
        self._schedule()

    def _reset_all(self) -> None:
        self._over = {}
        self._rebuild_views()
        self.kind.setCurrentIndex(0 if self._base.kind == "light" else 1)
        self._refresh_note()
        self._schedule()

    def _filter(self, text: str) -> None:
        needle = text.strip().lower()
        only = self._picked_keys
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            shown = 0
            for j in range(top.childCount()):
                child = top.child(j)
                hit = (not needle or needle in child.text(0).lower()
                       or needle in top.text(0).lower())
                if only is not None:
                    hit = hit and child.data(0, Qt.UserRole) in only
                child.setHidden(not hit)
                shown += hit
            top.setHidden(shown == 0)
            if (needle or only is not None) and shown:
                top.setExpanded(True)

    # --------------------------------------------------------- eyedropper

    def _start_dropper(self) -> None:
        self.note.setText("Click the part of the app you want to change. "
                          "Esc cancels.")
        self._dropper.start()

    def _dropper_stopped(self) -> None:
        self.raise_()
        self.activateWindow()

    def _selected(self, where: QPoint) -> None:
        """An element was clicked in the app: take the list to the settings
        that style it (or move the text to the first of them)."""
        element = element_at(where, self._current())
        if element is None or not element.keys:
            self.note.setText("Nothing to change there — try another spot.")
            return
        self.select_element(element)

    def select_element(self, element: "Element") -> None:
        keys = [k for k in element.keys if k in self._rows]
        self._picked_keys = set(keys)
        lines = [f"{element.title}:"]
        for role, value, group in element.groups:
            names = [nice(k) for s, k in group[:4]]
            more = f" and {len(group) - 4} more" if len(group) > 4 else ""
            colour = f" {value}" if value else ""
            lines.append(f"{role}{colour} → {', '.join(names)}{more}")
        self.banner_text.setText("\n".join(lines))
        self.banner.show()
        self.note.setText(f"Selected {element.title}.")
        self._filter(self.search.text())
        if not keys:
            return
        first = keys[0]
        if self.tabs.currentIndex() == TAB_TEXT:
            found = self.text.document().find(f"{first[1]} = ")
            if not found.isNull():
                self.text.setTextCursor(found)
                self.text.centerCursor()
            return
        item = self._rows[first][0]
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)

    # -------------------------------------------- reference and checks

    def _show_help(self, item, _previous=None) -> None:
        key = item.data(0, Qt.UserRole) if item is not None else None
        self.help.setText(
            f"{key[0]}.{key[1]} — {describe(*key)}" if key else "")

    def _refresh_checks(self) -> None:
        """Contrast and sanity warnings for the theme as it now stands."""
        issues = check(self._current())
        self._issues = issues
        # what is wrong in the theme file itself comes first: those values
        # were ignored when it loaded
        broken = list(self._base.problems) if self._base is not None else []
        self._file_problems = len(broken)
        self.checks_list.clear()
        for message in broken:
            self.checks_list.addItem("⛔ ignored — " + message)
        for issue in issues:
            self.checks_list.addItem(issue.message)
        n = len(issues) + len(broken)
        self.checks_toggle.setText(
            ("⚠ " if n else "✓ ") + (
                f"{n} check{'s' if n != 1 else ''} to look at"
                if n else "Checks: text, focus ring, wires and selection are "
                          "all readable"))
        self.checks_toggle.setEnabled(bool(n))
        if not n:
            self.checks_toggle.setChecked(False)

    def _check_clicked(self, item) -> None:
        """Take the list to the settings a warning is about."""
        row = self.checks_list.row(item) - self._file_problems
        if row < 0:
            return                      # a file problem: nothing to jump to
        issue = self._issues[row]
        self.select_element(Element(
            "Check", [("Involved in this warning", None, list(issue.where))]))
        self.tabs.setCurrentIndex(TAB_COLOURS)

    def _clear_pick(self) -> None:
        self._picked_keys = None
        self.banner.hide()
        self._filter(self.search.text())

    # --------------------------------------------------------- text mode

    def _parse(self):
        return parse_text(self.text.toPlainText(), self._base)

    def _text_edited(self) -> None:
        """The text changed: if it reads, it *is* the override table now.

        Only a change of *content* counts. Re-theming the app re-colours
        this editor too, and Qt reports that as text changed; reacting to it
        read the (older) text back over the colour just picked, and its own
        preview re-themed the app again — a loop that was both the lag and
        the value changing back."""
        current = self.text.toPlainText()
        if current == self._text_seen:
            return
        self._text_seen = current
        result = self._parse()
        self.text.set_diagnostics(result.problems)
        if result.problems:
            first = result.problems[0]
            more = (f" (+{len(result.problems) - 1} more)"
                    if len(result.problems) > 1 else "")
            self.note.setText(f"Line {first.line}: {first.message}{more}. "
                              "The app keeps the last good version until "
                              "this is fixed.")
            return
        self._over = result.overrides
        self._tree_stale = True
        self._refresh_note()
        self._schedule()

    def _tab_changed(self, index: int) -> None:
        if index == TAB_TEXT:
            if self._text_stale:
                self._set_text()
            return
        self._text_timer.stop()
        result = self._parse()
        if result.problems:
            first = result.problems[0]
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(TAB_TEXT)
            self.tabs.blockSignals(False)
            self.text.set_diagnostics(result.problems)
            QMessageBox.warning(
                self, "Theme Customiser",
                f"Line {first.line}: {first.message}\n\nFix the text first "
                "to go back to the colour list.")
            return
        self._over = result.overrides
        if self._tree_stale:
            self._build_tree()
        self._refresh_note()

    # ------------------------------------------------------------ preview

    def _schedule(self) -> None:
        self._previewing = True
        self._timer.start()

    def _current(self):
        return with_overrides(self._base, self._over,
                              label=self.label.text().strip() or None,
                              kind=self.kind.currentData())

    def _preview(self) -> None:
        app = QApplication.instance()
        if app is not None:
            theme.apply_theme(app, self._base.name, custom=self._current())
        self._refresh_checks()

    # --------------------------------------------------------------- save

    def _open_folder(self) -> None:
        if self._user_dir is None:
            return
        self._user_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._user_dir)))

    def _save(self) -> None:
        label = self.label.text().strip()
        if not label:
            QMessageBox.information(self, "Theme Customiser",
                                    "Give the theme a name first.")
            self.label.setFocus()
            return
        if self._user_dir is None:
            QMessageBox.warning(self, "Theme Customiser",
                                "There is no folder to save themes in.")
            return
        # the text may be ahead of the model by a keystroke
        self._text_timer.stop()
        if self.tabs.currentIndex() == TAB_TEXT:
            result = self._parse()
            if result.problems:
                first = result.problems[0]
                QMessageBox.warning(
                    self, "Theme Customiser",
                    f"Line {first.line}: {first.message}\n\nFix it before "
                    "saving.")
                return
            self._over = result.overrides
        name = slug(label)
        target = self._user_dir / f"{name}.toml"
        if name not in BUILTIN and target.exists() and name != self._base.name:
            if QMessageBox.question(
                    self, "Theme Customiser",
                    f"A theme called {name}.toml already exists. "
                    "Replace it?") != QMessageBox.Yes:
                return
        # What the new file sits on: the theme being edited — or, when it is
        # being saved over itself, whatever *it* sat on, so its own earlier
        # changes are written out again rather than lost.
        if name == self._base.name and not self._base.builtin:
            based_on = meta(name, self._user_dir).get("based_on", "dark")
        else:
            based_on = self._base.name
        try:
            parent = load(based_on, self._user_dir)
        except ThemeError as exc:
            QMessageBox.warning(self, "Theme Customiser", str(exc))
            return
        final = self._current()
        diff = {}
        for section in SECTIONS:
            for key, value in final.section(section).items():
                if value != parent.values.get(section, {}).get(key):
                    diff.setdefault(section, {})[key] = value
        saved = save_user(self._user_dir, label, self.kind.currentData(),
                          based_on, diff)
        self._timer.stop()
        self._previewing = False
        self._window.set_theme_pref(saved)
        self._names = [p for p in theme.theme_prefs() if p != "system"]
        self.start.blockSignals(True)
        self.start.clear()
        self.start.addItems([theme.theme_label(n) for n in self._names])
        self.start.blockSignals(False)
        self._load_base(saved)
        self.note.setText(f"Saved as {saved}.toml in {self._user_dir} and in "
                          "use. It is in View ▸ Theme now.")

    # -------------------------------------------------------------- close

    def done(self, result: int) -> None:
        self._dropper.stop()
        self._timer.stop()
        self._text_timer.stop()
        if self._previewing:
            # an unsaved preview is on screen: put the saved theme back
            app = QApplication.instance()
            if app is not None:
                theme.apply_theme(app, self._window.theme_pref)
            self._previewing = False
        super().done(result)

    def closeEvent(self, event) -> None:
        self.done(QDialog.Rejected)
        event.accept()
