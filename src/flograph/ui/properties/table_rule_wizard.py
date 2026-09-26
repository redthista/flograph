"""The **Rules** dialog behind the button on a table's conditional-formatting
box.

`RuleManager` lists every rule currently applied and lets you add one
(guided by `RuleBuilder`), edit, remove or reorder it. It edits the rules
text a line at a time, so comments and anything hand-typed it doesn't
recognise are left exactly where they are. `RuleBuilder` knows nothing about
the graph — the caller hands it the column names to offer.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QAction, QColor, QFont, QIcon, QKeySequence, QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QColorDialog, QComboBox,
    QDialog,
    QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QSpinBox, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from flograph.core import sparkline as _sparkline
from flograph.core.images import DATA_PREFIX, picture_uri
from flograph.core.table_format import (
    DEFAULT_PALETTE, MAX_PICTURE_SIZE, MAX_ROW_HEIGHT, MAX_RULE_WIDTH,
    MAX_SPARK_WIDTH, MIN_PICTURE_SIZE, MIN_ROW_HEIGHT, MIN_RULE_WIDTH,
    MIN_SPARK_WIDTH, PALETTES, _is_glob, abbreviate_pictures, bar_token,
    fill_token, glyph_token, parse_rule_lines, quote_column, rule_summary,
    scale_token,
)
from flograph.ui.emoji_font import apply_emoji_font, with_emoji

_SINGLE = QAbstractItemView.SelectionMode.SingleSelection
_MULTI = QAbstractItemView.SelectionMode.MultiSelection

_SCALES = [("Green (low → high)", "green"), ("Blue (low → high)", "blue"),
           ("Red (low → high)", "red"), ("Red → Green", "red-green"),
           ("Red → Yellow → Green", "red-yellow-green"),
           ("Diverging (blue ↔ red)", "diverging")]
# (label, DSL token, swatch colour) for the ColorChoice dropdowns. The
# swatch is a readable stand-in — the table paints its own dark fills.
_FILL_CHOICES = [("Red", "red", "#b3524f"), ("Amber", "amber", "#b0902f"),
                 ("Green", "green", "#4f9d5b"), ("Grey", "grey", "#6b6f78"),
                 ("Blue", "blue", "#4a7ab3"), ("Purple", "purple", "#7d5aa8")]
_GLYPH_CHOICES = [("Green", "green", "#5cb85c"), ("Amber", "amber", "#e0a83d"),
                  ("Red", "red", "#d9534f"), ("Blue", "blue", "#4a90d9"),
                  ("Grey", "grey", "#9aa0a6")]
#: A tile behind a picture: the vivid glyph colours, and the two grounds a
#: logo is most often drawn for.
_TILE_CHOICES = ([("White", "white", "#ffffff"), ("Black", "black", "#000000")]
                 + _GLYPH_CHOICES)
_BAR_CHOICES = [("Blue", "blue", "#3b6299"), ("Green", "green", "#2e7d46"),
                ("Orange", "orange", "#b9722e"), ("Purple", "purple", "#7d5aa8"),
                ("Red", "red", "#a4373a"), ("Grey", "grey", "#5b5f68")]
_OPS = [("is greater than", ">"), ("is ≥", ">="), ("is less than", "<"),
        ("is ≤", "<="), ("equals", "="), ("does not equal", "!="),
        ("contains", "contains"), ("starts with", "starts"),
        ("ends with", "ends"), ("matches (regex)", "matches"),
        ("is between", "between"), ("is empty", "empty"),
        ("is not empty", "notempty")]
#: What a pattern may say, wherever a rule compares a written value with
#: a cell's. Kept in one place because the condition box and the value→icon
#: map both say it, and they must not say it differently.
_WILDCARD_HELP = (
    "A value may be a pattern: * for any run of characters, ? for any one, "
    "[abc] for one of a set. \"In quotes\" means the characters themselves, "
    "which is how a value that really contains a * is written. Matching is "
    "case-sensitive, the same as a column pattern.")

_ICON_SETS = [("Traffic lights  ● ● ●", "traffic"),
              ("Arrows  ▼ ▬ ▲", "arrows"),
              ("Tick / dash / cross  ✓ – ✗", "check")]
_GLYPHS = ["✓", "✗", "!", "●", "▲", "▼", "★", "?", "→", "–"]
_MAP_COLOURS = ["green", "amber", "red", "blue", "grey", "(none)"]
_NUMBER_PRESETS = ["", ",.0f", ",.2f", ".1%", "$,.0f", "$,.2f"]

_KINDS = ["Colour scale", "Auto colour by category", "Data bars",
          "Sparkline", "Highlight cells / rows", "Icons", "Pictures",
          "Number format", "Tooltip from another column", "Hide columns",
          "Show only these columns", "Column layout", "Wrap text",
          "Row height", "Totals & groups"]

#: The kind combo's index, by name. The stack's pages are added in this
#: order and `_line` dispatches on it, so the number appears in three
#: places at once — which is exactly the sort of thing that survives one
#: insertion and quietly breaks on the next.
(K_SCALE, K_AUTO, K_BAR, K_SPARK, K_HIGHLIGHT, K_ICONS, K_PICTURE, K_NUMBER,
 K_TIP, K_HIDE, K_SHOW, K_LAYOUT, K_WRAP, K_HEIGHT,
 K_TOTALS) = range(len(_KINDS))

#: Which rows a highlight draws on — the `on …` style word. Empty is the
#: data rows, which is all a rule could draw on before total rows.
_ON_CHOICES = [("the data rows", ""),
               ("every total row (grand, group, subtotal)", "totals"),
               ("the grand total", "total"),
               ("the subtotals (group rows and the rows under them)",
                "subtotals"),
               ("the data rows and every total row", "all")]
#: …and the kinds each one stands for, to read a rule back in.
_ON_KINDS = {"": (), "totals": ("total", "group", "subtotal"),
             "total": ("total",), "subtotals": ("group", "subtotal"),
             "all": ("data", "total", "group", "subtotal")}

#: The Totals & groups page's "What" choices, one per line it writes.
_TOTAL_WHAT = [("Total row — every number column", "blanket"),
               ("How these columns are totalled", "column"),
               ("Group rows by these columns", "group"),
               ("Where subtotals go", "subtotal"),
               ("How total rows look", "style")]
_TOTAL_PLACES = [("at the bottom", "bottom"), ("at the top", "top"),
                 ("top and bottom", "both"), ("no total row", "none")]
_SUB_PLACES = [("on the group's row", "above"),
               ("on a row under the group", "below"),
               ("both", "both"), ("none", "none")]
_GROUP_STARTS = [("open", "open"), ("folded", "closed"),
                 ("outer level open", "first")]
_STYLE_ROWS = [("the grand total", "total"),
               ("subtotal rows (group rows and the rows under them)",
                "subtotal"),
               ("group header rows", "group"),
               ("every total row", "totals")]

#: Where an `image` rule's pictures go. The empty token is "where they
#: belong": in place of the value when the pictures *are* the column's
#: values, left of it when they come from another column — which is what
#: the rule does when it names no place.
_PICTURE_PLACES = [("in place of its value — or left, from another column",
                    ""),
                   ("left of the value", "left"),
                   ("right of the value", "right"),
                   ("above the value", "above"),
                   ("below the value", "below"),
                   ("in place of the value", "in")]
#: The shape a picture is cut to; empty draws it as it is.
_PICTURE_SHAPES = [("as it is", ""), ("square", "square"),
                   ("rounded square", "rounded"), ("circle", "circle")]

_SPARK_KIND_CHOICES = [("Line", "line"), ("Area", "area"), ("Step", "step"),
                       ("Bars", "bars"), ("Win / loss", "winloss"),
                       ("Dots", "dots")]
_SPARK_CHOICES = [(name.capitalize(), name, _sparkline.COLORS[name])
                  for name in ("blue", "green", "red", "amber", "orange",
                               "purple", "teal", "pink", "grey")]
#: How a spark's columns are chosen. A range is what a wide table of
#: months wants, and the one a pick-list cannot say without ticking twelve
#: boxes; a pattern survives next year's columns arriving.
_SPARK_READ_CHOICES = [("A range of columns", "range"),
                       ("Columns matching a pattern", "pattern"),
                       ("These columns", "list")]
_SPARK_MARKS = [("first", "First"), ("last", "Last"), ("high", "High"),
                ("low", "Low"), ("points", "Every point")]
_SPARK_FATE_CHOICES = [("Leave them showing", ""),
                       ("Hide them", "hide"),
                       ("Hide them, and put this column where they were",
                        "replace")]
#: Typed as well as picked, so the editable combo's *text* is the value.
_SPARK_REFS = ["none", "0", "mean", "median"]

# both icon modes share the one "Icons" page; the page's own Style toggle
# picks between the graduated set and a value→icon map.
_MODE_KIND = {"color_scale": K_SCALE, "auto_color": K_AUTO,
              "sparkline": K_SPARK,
              "data_bar": K_BAR, "highlight": K_HIGHLIGHT, "icons": K_ICONS,
              "icon_map": K_ICONS, "number_format": K_NUMBER,
              "tooltip": K_TIP, "hide": K_HIDE, "show": K_SHOW,
              "column_width": K_LAYOUT, "align": K_LAYOUT,
              "header_label": K_LAYOUT, "wrap": K_WRAP,
              "row_height": K_HEIGHT, "image": K_PICTURE,
              "total": K_TOTALS, "subtotal": K_TOTALS, "group": K_TOTALS,
              "total_style": K_TOTALS}

#: The palettes an auto colour can spend, newest-friendly names first.
#: Taken from `PALETTES` rather than listed here, so a palette added to
#: the chart side turns up in this combo without a second edit.
_PALETTE_CHOICES = [(name.capitalize(), name) for name in
                    ([DEFAULT_PALETTE] + sorted(set(PALETTES) -
                                                {DEFAULT_PALETTE}))]

#: What an auto colour draws. The empty token is the default (a pill),
#: which is what a category wants: a lozenge round the value rather than a
#: column flooded with one of eight saturated chart colours.
_AUTO_SHAPE_CHOICES = [("A pill round each value", ""),
                       ("Fill the cell", "fill"),
                       ("Colour the text only", "text")]


def _combo(pairs) -> QComboBox:
    box = QComboBox()
    for label, token in pairs:
        box.addItem(label, token)
    return box


_THIS_COLUMN = "(this column)"
#: What the note-column combo says before one is picked. A tooltip rule is
#: the one "another column" rule with no meaning for "(this column)" — a
#: cell explaining itself is the value already in front of you.
_PICK_A_COLUMN = "— pick a column —"


def _other_col_value(box: QComboBox) -> str:
    """The column name chosen in an "another column" combo, or "" for the
    default "(this column)"."""
    data = box.currentData()
    if data:
        return str(data)
    text = box.currentText().strip()
    # both placeholders mean "nothing chosen". Matched by text because an
    # editable combo (a Table Style node, with no upstream columns to
    # offer) carries typed text and no data at all.
    return "" if text in ("", _THIS_COLUMN, _PICK_A_COLUMN) else text


def _pick_data(combo: QComboBox, token) -> None:
    index = combo.findData(token)
    if index >= 0:
        combo.setCurrentIndex(index)


def _only(box) -> str:
    return " only" if box.isChecked() else ""


def _spark_token(colour) -> str:
    """A spark colour as the rule writes it: its preset name when it has
    one, else the hex it was given."""
    if not colour:
        return ""
    for name, value in _sparkline.COLORS.items():
        if value.lower() == str(colour).lower():
            return name
    return str(colour)


#: Where a mark sits in its cell, as the wizard offers it. "left" is the
#: empty token because it is the default and writing it would only make
#: every generated line longer.
_PLACES = [("left of the value", ""), ("right of the value", "right"),
           ("above the value", "above"), ("below the value", "below"),
           ("in place of the value", "in")]


def _place(box) -> str:
    token = box.currentData()
    return f" {token}" if token else ""


def _glyph_text(edit) -> str:
    """What an icon box holds, as a rule writes it.

    A pasted picture goes in as bare base64: a ``data:`` prefix holds a
    comma and SVG markup holds spaces, and an icon map's pairs are split on
    both. Anything else is the typed glyph with its spaces taken out.
    """
    typed = edit.text()
    uri = picture_uri(typed)
    return DATA_PREFIX.sub("", uri) if uri else "".join(typed.split())


def _pill(box) -> str:
    return " pill" if box.isChecked() else ""


def _cols_text(names) -> str:
    return ", ".join(quote_column(str(n).strip()) for n in names if str(n).strip())


def _looks_hex(token: str) -> bool:
    s = str(token or "").strip()
    return s.startswith("#") and len(s) in (4, 7)


def _tile_token(colour) -> str:
    """A tile colour as the wizard offers it: its preset's name, else the
    hex, else "(none)"."""
    if not colour:
        return "(none)"
    for _label, token, value in _TILE_CHOICES:
        if value.lower() == str(colour).lower():
            return token
    return str(colour)


def _show_picture(edit: QLineEdit) -> None:
    """A picture pasted into an icon box, previewed at the front of the box
    — the text in it is only base64, which says nothing to anyone."""
    for action in list(edit.actions()):
        edit.removeAction(action)
    uri = picture_uri(edit.text())
    edit.setToolTip(abbreviate_pictures(edit.text()) if uri else "")
    if uri is None:
        return
    from flograph.ui.table_delegate import picture_pixmap
    pixmap = picture_pixmap(uri, 16, 16, edit.devicePixelRatioF())
    if pixmap is not None:
        edit.addAction(QIcon(pixmap), QLineEdit.LeadingPosition)


class _PictureEdit(QLineEdit):
    """An icon cell that takes a picture as well as a glyph.

    Paste a picture — a screenshot, an image copied from a browser, a
    picture file copied in a file manager, base64 or SVG markup — or drop
    one on it, and it goes in as a small base64 picture, shrunk to icon size
    so the rule and the flow stay light. Text that isn't a picture pastes
    as text, as it always did.
    """

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setAcceptDrops(True)

    def take_picture(self, mime) -> bool:
        """Put the picture `mime` holds in the cell. False when it has none."""
        from flograph.ui.image_paste import icon_source
        source = icon_source(mime)
        if source is None:
            return False
        # one mark per cell: a picture replaces whatever was typed
        self.setText(source)
        self.setCursorPosition(0)
        return True

    def keyPressEvent(self, event) -> None:
        if (event.matches(QKeySequence.Paste)
                and self.take_picture(QApplication.clipboard().mimeData())):
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:
        menu = self.createStandardContextMenu()
        from flograph.ui.image_paste import icon_source
        if icon_source(QApplication.clipboard().mimeData()) is not None:
            first = menu.actions()[0] if menu.actions() else None
            action = QAction("Paste Picture", menu)
            action.triggered.connect(
                lambda: self.take_picture(QApplication.clipboard().mimeData()))
            menu.insertAction(first, action)
            menu.insertSeparator(first)
        menu.exec(event.globalPos())
        menu.deleteLater()

    def dragEnterEvent(self, event) -> None:
        from flograph.ui.image_paste import icon_source
        if icon_source(event.mimeData()) is not None:
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        if self.take_picture(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dropEvent(event)


def _swatch(colour: str) -> QIcon:
    pm = QPixmap(14, 14)
    c = QColor(colour)
    pm.fill(c if c.isValid() else QColor("#888888"))
    return QIcon(pm)


class ColorChoice(QWidget):
    """A colour dropdown: a few named presets, each with a swatch, plus
    **Custom…** which opens the system colour picker (hex, RGB, HSV and
    screen-pick — all of Qt's dialog). :meth:`value` is the preset name,
    a ``#rrggbb`` string, or ``"(none)"``; :meth:`set_value` takes any of
    those back."""

    changed = Signal()
    _CUSTOM = "\x00custom"

    def __init__(self, choices, allow_none: bool = False, parent=None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._combo = QComboBox()
        self._names = {tok for _lbl, tok, _hex in choices}
        if allow_none:
            self._combo.addItem("(none)", "(none)")
        for label, token, hexv in choices:
            self._combo.addItem(_swatch(hexv), label, token)
        self._combo.insertSeparator(self._combo.count())
        self._combo.addItem("Custom…", self._CUSTOM)
        self._custom_row = None            # index of the picked-colour item
        self._prev = self._combo.currentIndex()
        self._combo.activated.connect(self._on_activated)
        self._combo.currentIndexChanged.connect(self._on_changed)
        lay.addWidget(self._combo)

    # -------------------------------------------------------------- value
    def value(self) -> str:
        data = self._combo.currentData()
        return "" if data in (None, self._CUSTOM) else str(data)

    def set_value(self, token) -> None:
        token = str(token or "").strip()
        idx = self._combo.findData(token)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        elif _looks_hex(token):
            self._set_custom(QColor(token))
        elif token in ("", "(none)"):
            self._combo.setCurrentIndex(0)
        self._prev = self._combo.currentIndex()

    # ----------------------------------------------------------- internal
    def _on_changed(self, idx: int) -> None:
        if self._combo.itemData(idx) != self._CUSTOM:
            self._prev = idx
            self.changed.emit()

    def _on_activated(self, idx: int) -> None:
        if self._combo.itemData(idx) != self._CUSTOM:
            return
        start = self._combo.itemData(self._prev)
        initial = QColor(start if _looks_hex(str(start)) else "#4a7ab3")
        picked = QColorDialog.getColor(initial, self, "Pick a colour")
        if picked.isValid():
            self._set_custom(picked)
            self.changed.emit()
        else:
            self._combo.setCurrentIndex(self._prev)

    def _set_custom(self, colour: QColor) -> None:
        hexv = colour.name()
        if self._custom_row is None:
            self._custom_row = self._combo.count()
            self._combo.addItem(_swatch(hexv), hexv, hexv)
        else:
            self._combo.setItemText(self._custom_row, hexv)
            self._combo.setItemIcon(self._custom_row, _swatch(hexv))
            self._combo.setItemData(self._custom_row, hexv)
        self._combo.setCurrentIndex(self._custom_row)


class RuleBuilder(QDialog):
    """Build (or edit) one rule; ``line()`` is the DSL it produces."""

    def __init__(self, columns, parent=None, rule=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit rule" if rule else "New rule")
        self.setModal(True)
        self._columns = [str(c) for c in (columns or [])]

        outer = QVBoxLayout(self)
        self._kind = QComboBox()
        self._kind.addItems(_KINDS)
        top = QFormLayout()
        top.addRow("Rule", self._kind)
        outer.addLayout(top)

        self._col_list = QListWidget()
        self._col_list.setSelectionMode(_MULTI)
        self._col_list.setMaximumHeight(120)
        for name in self._columns:
            self._col_list.addItem(QListWidgetItem(name))
        self._col_edit = QLineEdit()
        self._col_label = QLabel("Columns")
        cform = QFormLayout()
        if self._columns:
            cform.addRow(self._col_label, self._col_list)
            self._col_edit.setPlaceholderText(
                "…or a name / pattern:  20*,  Q?_sales,  *total*")
            cform.addRow("", self._col_edit)
        else:
            self._col_edit.setPlaceholderText(
                "column name or pattern — several, comma separated")
            cform.addRow(self._col_label, self._col_edit)
        outer.addLayout(cform)

        self._stack = QStackedWidget()
        self._build_scale_page()
        self._build_auto_page()
        self._build_bar_page()
        self._build_spark_page()
        self._build_highlight_page()
        self._build_icons_page()
        self._build_picture_page()
        self._build_number_page()
        self._build_tip_page()
        self._build_hide_page()
        self._build_show_page()
        self._build_layout_page()
        self._build_wrap_page()
        self._build_height_page()
        self._build_totals_page()
        outer.addWidget(self._stack)

        outer.addWidget(QLabel("Rule text:"))
        self._preview = QLabel()
        self._preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._preview.setWordWrap(True)
        # the font is set, not styled: a style sheet's font-family wins over
        # the widget font, and this one has to carry the emoji fallback so a
        # glyph rule previews as the glyph rather than as a gap
        mono = QFont(self._preview.font())
        mono.setStyleHint(QFont.Monospace)
        mono.setFamily("monospace")
        self._preview.setFont(with_emoji(mono))
        self._preview.setStyleSheet("padding: 6px; "
                                    "border: 1px solid palette(mid);")
        outer.addWidget(self._preview)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        outer.addWidget(self._buttons)

        self._kind.currentIndexChanged.connect(self._on_kind)
        self._kind.currentIndexChanged.connect(self._refresh)
        self._col_list.itemSelectionChanged.connect(self._refresh)
        self._col_edit.textChanged.connect(self._refresh)
        self._on_kind()
        if rule is not None:
            self._load(rule)
        self._refresh()

    # ------------------------------------------------------------- public

    def line(self) -> str:
        return self._line()

    # ------------------------------------------------------------- columns

    def _chosen_columns(self) -> list[str]:
        picks = ([i.text() for i in self._col_list.selectedItems()]
                 if self._columns else [])
        typed = [c.strip() for c in self._col_edit.text().split(",") if c.strip()]
        seen, out = set(), []
        for c in picks + typed:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out

    def _columns_text(self) -> str:
        return _cols_text(self._chosen_columns())

    def _other_col_combo(self) -> QComboBox:
        """A combo offering "(this column)" then every column name — for a
        rule that can take its deciding value from a different column."""
        box = QComboBox()
        box.setEditable(not self._columns)
        box.addItem(_THIS_COLUMN, None)
        for name in self._columns:
            box.addItem(name, name)
        box.currentIndexChanged.connect(self._refresh)
        if box.isEditable():
            box.editTextChanged.connect(self._refresh)
        return box

    def _set_other_col(self, box: QComboBox, name) -> None:
        if not name:
            box.setCurrentIndex(0)
            return
        idx = box.findData(str(name))
        if idx >= 0:
            box.setCurrentIndex(idx)
        elif box.isEditable():
            box.setCurrentText(str(name))

    def _select_columns(self, names) -> None:
        names = [str(n) for n in names]
        if not self._columns:
            self._col_edit.setText(", ".join(names))
            return
        known = set(self._columns)
        for i in range(self._col_list.count()):
            item = self._col_list.item(i)
            item.setSelected(item.text() in names)
        # a pattern, or a name this table doesn't list, goes in the field
        self._col_edit.setText(", ".join(n for n in names if n not in known))

    # ---------------------------------------------------------- type pages

    def _only_box(self, label: str) -> QCheckBox:
        """The `only` modifier: draw the format instead of the value.

        The value is still in the table — it sorts, copies and exports as
        it always did — so the wording says *hide*, not *remove*.
        """
        box = QCheckBox(label)
        box.setToolTip("The value is still there for sorting, copying and "
                       "export — it just isn't shown.")
        box.toggled.connect(self._refresh)
        return box

    def _place_combo(self) -> QComboBox:
        """Where this rule's mark goes.

        Per rule, not per cell: a cell shows as many marks as the rules
        give it, so two rules are how a cell gets one on each side.
        """
        box = _combo(_PLACES)
        box.setToolTip(
            "A cell can carry a mark on each side and a line above and "
            "below — that is one rule each, not one rule with four boxes.")
        box.currentIndexChanged.connect(self._refresh)
        return box

    def _pill_box(self, label: str) -> QCheckBox:
        box = QCheckBox(label)
        box.setToolTip(
            "A coloured lozenge. With no text of its own it wraps the "
            "cell's value; give it text and it stands beside the value.")
        box.toggled.connect(self._refresh)
        return box

    def _build_scale_page(self) -> None:
        page = QWidget()
        f = QFormLayout(page)
        self._scale = _combo(_SCALES)
        self._scale.currentIndexChanged.connect(self._refresh)
        f.addRow("Colours", self._scale)
        self._scale_by = self._other_col_combo()
        f.addRow("Colour by", self._scale_by)
        self._scale_only = self._only_box("colour only — hide the value")
        f.addRow("", self._scale_only)
        self._stack.addWidget(page)

    def _build_auto_page(self) -> None:
        """Auto colour by category — the one rule that names no values.

        There is no value list here on purpose. The whole point is that
        the categories are not known when the rule is written, so anything
        this page offered to type would be a map (an `iconmap` /
        `colormap`) wearing the wrong name.
        """
        page = QWidget()
        f = QFormLayout(page)
        self._auto_palette = _combo(_PALETTE_CHOICES)
        self._auto_palette.currentIndexChanged.connect(self._refresh)
        f.addRow("Palette", self._auto_palette)
        self._auto_shape = _combo(_AUTO_SHAPE_CHOICES)
        self._auto_shape.currentIndexChanged.connect(self._refresh)
        f.addRow("Draw it as", self._auto_shape)
        self._auto_by = self._other_col_combo()
        f.addRow("Categories from", self._auto_by)
        self._auto_only = self._only_box("colour only — hide the value")
        f.addRow("", self._auto_only)
        hint = QLabel(
            "Every distinct value takes its own colour from the palette — "
            "nothing to name in advance. The colours are handed out in "
            "sorted order, so they stay put when a new row arrives.")
        hint.setWordWrap(True)
        f.addRow("", hint)
        self._stack.addWidget(page)

    def _build_bar_page(self) -> None:
        page = QWidget()
        f = QFormLayout(page)
        self._bar = ColorChoice(_BAR_CHOICES)
        self._bar.changed.connect(self._refresh)
        f.addRow("Bar colour", self._bar)
        self._bar_by = self._other_col_combo()
        f.addRow("Size by", self._bar_by)
        self._bar_only = self._only_box("bar only — hide the value")
        f.addRow("", self._bar_only)
        self._stack.addWidget(page)

    def _column_combo(self) -> QComboBox:
        """A combo of every column — typed into instead where there are no
        columns to offer (a Table Style node, with no table upstream)."""
        box = QComboBox()
        box.setEditable(not self._columns)
        for name in self._columns:
            box.addItem(name, name)
        box.currentIndexChanged.connect(self._refresh)
        if box.isEditable():
            box.editTextChanged.connect(self._refresh)
        return box

    def _build_spark_page(self) -> None:
        """A sparkline: which columns it reads across the row, and how it is
        drawn. The column list at the top is where it is *drawn* — so a name
        the table does not have is a column of its own."""
        page = QWidget()
        f = QFormLayout(page)
        self._spark_read = _combo(_SPARK_READ_CHOICES)
        self._spark_read.currentIndexChanged.connect(self._sync_spark_read)
        f.addRow("Read", self._spark_read)

        self._spark_start = self._column_combo()
        self._spark_end = self._column_combo()
        # blank until picked: first-to-last would quietly read every
        # numeric column in the table, totals included
        self._spark_start.setCurrentIndex(-1)
        self._spark_end.setCurrentIndex(-1)
        self._spark_range = QWidget()
        rl = QHBoxLayout(self._spark_range)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self._spark_start, 1)
        rl.addWidget(QLabel("to"))
        rl.addWidget(self._spark_end, 1)
        f.addRow("Columns", self._spark_range)

        self._spark_pattern = QLineEdit()
        self._spark_pattern.setPlaceholderText("sales_*   ·   20??   ·   m*")
        self._spark_pattern.textChanged.connect(self._refresh)
        f.addRow("Pattern", self._spark_pattern)

        self._spark_pick = QWidget()
        pl = QVBoxLayout(self._spark_pick)
        pl.setContentsMargins(0, 0, 0, 0)
        self._spark_list = QListWidget()
        self._spark_list.setSelectionMode(_MULTI)
        self._spark_list.setMaximumHeight(96)
        for name in self._columns:
            self._spark_list.addItem(QListWidgetItem(name))
        self._spark_list.itemSelectionChanged.connect(self._refresh)
        self._spark_list.setVisible(bool(self._columns))
        pl.addWidget(self._spark_list)
        self._spark_names = QLineEdit()
        self._spark_names.setPlaceholderText(
            "…or names, comma separated, in the order to read them")
        self._spark_names.textChanged.connect(self._refresh)
        pl.addWidget(self._spark_names)
        f.addRow("These", self._spark_pick)

        self._spark_kind = _combo(_SPARK_KIND_CHOICES)
        self._spark_kind.currentIndexChanged.connect(self._refresh)
        f.addRow("Kind", self._spark_kind)
        self._spark_colour = ColorChoice(_SPARK_CHOICES)
        self._spark_colour.changed.connect(self._refresh)
        f.addRow("Colour", self._spark_colour)
        self._spark_negative = ColorChoice(_SPARK_CHOICES, allow_none=True)
        self._spark_negative.changed.connect(self._refresh)
        f.addRow("Below zero", self._spark_negative)

        marks = QWidget()
        ml = QHBoxLayout(marks)
        ml.setContentsMargins(0, 0, 0, 0)
        self._spark_marks: dict = {}
        for token, label in _SPARK_MARKS:
            box = QCheckBox(label)
            box.toggled.connect(self._refresh)
            ml.addWidget(box)
            self._spark_marks[token] = box
        ml.addStretch(1)
        f.addRow("Mark", marks)
        #: a mark's colour from a rule being edited — kept so opening and
        #: saving a hand-typed `high green` does not quietly lose the green
        self._spark_mark_colours: dict = {}

        self._spark_ref = QComboBox()
        self._spark_ref.setEditable(True)
        self._spark_ref.addItems(_SPARK_REFS)
        self._spark_ref.setToolTip("A dashed line at a number, or at the "
                                   "row's mean or median")
        self._spark_ref.editTextChanged.connect(self._refresh)
        f.addRow("Reference line", self._spark_ref)

        flags = QWidget()
        fl = QHBoxLayout(flags)
        fl.setContentsMargins(0, 0, 0, 0)
        self._spark_shared = QCheckBox("One scale for every row")
        self._spark_shared.setToolTip(
            "Off, each row fills its own height, which shows its shape best. "
            "On, the lines can be compared by height too.")
        self._spark_smooth = QCheckBox("Smooth")
        self._spark_thick = QCheckBox("Thick")
        self._spark_tall = QCheckBox("Tall")
        for box in (self._spark_shared, self._spark_smooth,
                    self._spark_thick, self._spark_tall):
            box.toggled.connect(self._refresh)
            fl.addWidget(box)
        fl.addStretch(1)
        f.addRow("", flags)

        self._spark_width = QSpinBox()
        self._spark_width.setRange(MIN_SPARK_WIDTH - 1, MAX_SPARK_WIDTH)
        self._spark_width.setSpecialValueText("auto")
        self._spark_width.setSuffix(" px")
        self._spark_width.setValue(MIN_SPARK_WIDTH - 1)
        self._spark_width.valueChanged.connect(self._refresh)
        f.addRow("Width", self._spark_width)

        self._spark_place = self._place_combo()
        f.addRow("Beside a value", self._spark_place)
        self._spark_fate = _combo(_SPARK_FATE_CHOICES)
        self._spark_fate.currentIndexChanged.connect(self._refresh)
        f.addRow("Columns it reads", self._spark_fate)

        hint = QLabel(
            "Drawn in a column the table doesn't have — type a new name "
            "above — it gets a column of its own, holding the row's latest "
            "number. Drawn in one it has, it sits beside the value like an "
            "icon. A blank is a gap in the line, never a zero.")
        hint.setWordWrap(True)
        f.addRow("", hint)
        self._spark_form = f
        self._stack.addWidget(page)
        self._sync_spark_read()

    def _sync_spark_read(self) -> None:
        """Show only the inputs the chosen way of picking columns uses."""
        mode = self._spark_read.currentData()
        for widget, wanted in ((self._spark_range, "range"),
                               (self._spark_pattern, "pattern"),
                               (self._spark_pick, "list")):
            widget.setVisible(mode == wanted)
            label = self._spark_form.labelForField(widget)
            if label is not None:
                label.setVisible(mode == wanted)
        self._refresh()

    def _spark_series(self) -> str:
        """The text after `from`, or "" when nothing is chosen yet."""
        mode = self._spark_read.currentData()
        if mode == "range":
            start = self._spark_start.currentText().strip()
            end = self._spark_end.currentText().strip()
            return (f"{quote_column(start)}..{quote_column(end)}"
                    if start and end else "")
        if mode == "pattern":
            return self._spark_pattern.text().strip()
        picks = ([i.text() for i in self._spark_list.selectedItems()]
                 if self._columns else [])
        typed = [c.strip() for c in self._spark_names.text().split(",")
                 if c.strip()]
        return _cols_text(list(dict.fromkeys(picks + typed)))

    def _load_spark(self, rule) -> None:
        _pick_data(self._spark_kind, rule.spark_kind or "line")
        self._spark_colour.set_value(_spark_token(rule.color) or "blue")
        self._spark_negative.set_value(_spark_token(rule.negative_color)
                                       or "(none)")
        self._spark_mark_colours = {}
        for entry in rule.marks or []:
            if len(entry) > 1 and entry[1]:
                self._spark_mark_colours[entry[0]] = entry[1]
        for token, box in self._spark_marks.items():
            box.setChecked(any(entry[0] == token
                               for entry in rule.marks or []))
        ref = rule.ref
        self._spark_ref.setCurrentText(
            "none" if ref is None else
            (_sparkline.format_number(ref) if isinstance(ref, (int, float))
             else str(ref)))
        self._spark_shared.setChecked(bool(rule.shared))
        self._spark_smooth.setChecked(bool(rule.smooth))
        self._spark_thick.setChecked(bool(rule.thick))
        self._spark_tall.setChecked(bool(rule.tall))
        self._spark_width.setValue(rule.spark_width or MIN_SPARK_WIDTH - 1)
        place = "in" if rule.hide_value else rule.glyph_where
        _pick_data(self._spark_place, "" if place in (None, "left") else place)
        _pick_data(self._spark_fate, rule.take_sources or "")

        entries = [str(e) for e in rule.series or []]
        known = set(self._columns)
        if (len(entries) == 1 and ".." in entries[0]
                and entries[0] not in known):
            start, _dots, end = entries[0].partition("..")
            _pick_data(self._spark_read, "range")
            for box, name in ((self._spark_start, start.strip().strip('"')),
                              (self._spark_end, end.strip().strip('"'))):
                idx = box.findData(name)
                if idx >= 0:
                    box.setCurrentIndex(idx)
                elif box.isEditable():
                    box.setCurrentText(name)
        elif len(entries) == 1 and _is_glob(entries[0]):
            _pick_data(self._spark_read, "pattern")
            self._spark_pattern.setText(entries[0])
        else:
            _pick_data(self._spark_read, "list")
            for i in range(self._spark_list.count()):
                item = self._spark_list.item(i)
                item.setSelected(item.text() in entries)
            self._spark_names.setText(", ".join(
                e for e in entries if e not in known or not self._columns))
        self._sync_spark_read()

    def _spark_line(self, cols: str) -> str:
        series = self._spark_series()
        if not series:
            return ""
        words = [f"{cols} spark"]
        kind = self._spark_kind.currentData()
        if kind != "line":
            words.append(kind)
        colour = self._spark_colour.value()
        if colour and colour != "blue":
            words.append(colour)
        negative = self._spark_negative.value()
        if negative and negative != "(none)":
            words += ["negative", negative]
        for token, box in self._spark_marks.items():
            if box.isChecked():
                words.append(token)
                chosen = self._spark_mark_colours.get(token)
                if chosen:
                    words.append(_spark_token(chosen))
        ref = self._spark_ref.currentText().strip().lower()
        if ref and ref != "none":
            if ref not in ("mean", "median") and _sparkline.number(ref) is None:
                return ""          # not a line the rule could read
            words += ["ref", ref]
        for word, box in (("shared", self._spark_shared),
                          ("smooth", self._spark_smooth),
                          ("thick", self._spark_thick),
                          ("tall", self._spark_tall)):
            if box.isChecked():
                words.append(word)
        width = self._spark_width.value()
        if width >= MIN_SPARK_WIDTH:
            words.append(f"{width}px")
        place = self._spark_place.currentData()
        if place:
            words.append(place)
        fate = self._spark_fate.currentData()
        if fate:
            words.append(fate)
        return " ".join(words) + f" from {series}"

    def _build_highlight_page(self) -> None:
        page = QWidget()
        f = QFormLayout(page)
        self._op = _combo(_OPS)
        self._val1 = QLineEdit()
        self._val2 = QLineEdit()
        vrow = QWidget()
        vl = QHBoxLayout(vrow)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.addWidget(self._val1)
        self._and = QLabel("and")
        vl.addWidget(self._and)
        vl.addWidget(self._val2)
        # (none) is offered because a highlight need not paint anything: an
        # `=> icon ✓ right` rule has no fill at all, and without a way to
        # say so, opening one to edit it would give it a fill it never had.
        # A fresh rule still opens on Red — set below, after the widget.
        self._fill = ColorChoice(_FILL_CHOICES, allow_none=True)
        self._fill.set_value("red")
        self._fill.changed.connect(self._refresh)
        self._bold = QCheckBox("bold text")
        self._scope = QComboBox()
        self._scope.addItems(["this cell", "the whole row"])
        for w in (self._op, self._scope):
            w.currentIndexChanged.connect(self._refresh)
        for w in (self._val1, self._val2):
            w.textChanged.connect(self._refresh)
        self._bold.toggled.connect(self._refresh)
        self._op.currentIndexChanged.connect(self._sync_highlight_inputs)
        self._hl_test = self._other_col_combo()
        f.addRow("Test column", self._hl_test)
        f.addRow("When the value", self._op)
        f.addRow("", vrow)
        f.addRow("Fill", self._fill)
        self._hl_pill = self._pill_box("draw the fill as a pill")
        self._hl_badge = QLineEdit()
        self._hl_badge.setPlaceholderText(
            "text in the pill — leave blank to wrap the value")
        self._hl_badge.textChanged.connect(self._refresh)
        self._hl_place = self._place_combo()
        # One glyph placed by a condition — `= 1 => icon ✓ green`. The
        # parser has always taken it; without a row here, editing such a
        # rule in the manager rebuilt it from the widgets and dropped it.
        self._hl_icon = _PictureEdit()
        apply_emoji_font(self._hl_icon)
        self._hl_icon.setPlaceholderText(
            "a character, an emoji (✓, →, 🙂), or paste / drop a picture")
        self._hl_icon.textChanged.connect(self._refresh)
        self._hl_icon.textChanged.connect(
            lambda _t, e=self._hl_icon: _show_picture(e))
        self._hl_icon_color = ColorChoice(_GLYPH_CHOICES, allow_none=True)
        self._hl_icon_color.changed.connect(self._refresh)
        f.addRow("", self._hl_pill)
        f.addRow("Pill text", self._hl_badge)
        f.addRow("Icon", self._hl_icon)
        f.addRow("Icon colour", self._hl_icon_color)
        f.addRow("Place", self._hl_place)
        # Text colour: the one thing a highlight could always do (`fg`) and
        # the dialog had no control for.
        self._hl_fg = ColorChoice(_GLYPH_CHOICES, allow_none=True)
        self._hl_fg.set_value("(none)")
        self._hl_fg.changed.connect(self._refresh)
        f.addRow("Text colour", self._hl_fg)
        f.addRow("Apply to", self._scope)
        self._hl_on = _combo(_ON_CHOICES)
        self._hl_on.setToolTip(
            "Total rows are left alone by a rule unless it says otherwise — "
            "a total is always the biggest number, and would light up every "
            "test. Choose them here to colour or mark a total by its value.")
        self._hl_on.currentIndexChanged.connect(self._refresh)
        f.addRow("Draw on", self._hl_on)
        f.addRow("", self._bold)
        self._hl_height = self._height_spin("unchanged")
        self._hl_height.setToolTip(
            "Make the rows this test picks taller (or shorter). A row is one "
            "height, so it applies to the whole row either way.")
        f.addRow("Row height", self._hl_height)
        self._stack.addWidget(page)

    def _build_icons_page(self) -> None:
        """One page for both icon rules. **Style** picks between a graduated
        3-tier set (ranked into thirds) and an explicit value → icon map;
        **Decided by** is the column that drives either, this one or another.
        """
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        head = QFormLayout()
        self._icon_style = QComboBox()
        self._icon_style.addItem("Graduated set — rank into 3 tiers", "set")
        self._icon_style.addItem("Map exact values to icons", "map")
        head.addRow("Style", self._icon_style)
        self._icon_by = self._other_col_combo()
        head.addRow("Decided by", self._icon_by)
        self._icon_only = self._only_box("icon only — hide the value")
        head.addRow("", self._icon_only)
        self._icon_pill = self._pill_box("in a pill")
        head.addRow("", self._icon_pill)
        self._icon_place = self._place_combo()
        head.addRow("Place", self._icon_place)
        self._icon_shape = _combo(_PICTURE_SHAPES)
        self._icon_shape.setToolTip(
            "For pictures pasted into the map: the shape they are cut to. "
            "A picture given a colour sits on a tile of that colour.")
        self._icon_shape.currentIndexChanged.connect(self._refresh)
        head.addRow("Picture shape", self._icon_shape)
        v.addLayout(head)

        # -- graduated set
        self._icon_set_box = QWidget()
        sf = QFormLayout(self._icon_set_box)
        sf.setContentsMargins(0, 0, 0, 0)
        self._iconset = _combo(_ICON_SETS)
        self._icon_reverse = QCheckBox("reverse (high = red)")
        self._iconset.currentIndexChanged.connect(self._refresh)
        self._icon_reverse.toggled.connect(self._refresh)
        sf.addRow("Icon set", self._iconset)
        sf.addRow("", self._icon_reverse)
        sf.addRow(QLabel("Split at the deciding column's lower / upper third."))
        v.addWidget(self._icon_set_box)

        # -- value → icon map
        self._icon_map_box = QWidget()
        mv = QVBoxLayout(self._icon_map_box)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.addWidget(QLabel("Value → icon  (type any character or emoji, "
                            "or paste a picture as base64):"))
        self._map = QTableWidget(0, 3)
        self._map.setHorizontalHeaderLabels(["value", "icon", "colour"])
        self._map.horizontalHeaderItem(0).setToolTip(
            _WILDCARD_HELP + " A value the map names outright wins over a "
            "pattern, and among patterns the first row that matches wins.")
        self._map.setMaximumHeight(150)
        self._map.horizontalHeader().setStretchLastSection(True)
        self._map.cellChanged.connect(self._refresh)
        mv.addWidget(self._map)
        row = QHBoxLayout()
        add = QPushButton("＋ row")
        rm = QPushButton("－ row")
        add.clicked.connect(lambda: (self._add_map_row(), self._refresh()))
        rm.clicked.connect(self._remove_map_row)
        row.addWidget(add)
        row.addWidget(rm)
        row.addStretch(1)
        mv.addLayout(row)
        self._add_map_row()
        self._add_map_row()
        v.addWidget(self._icon_map_box)

        self._icon_style.currentIndexChanged.connect(self._sync_icon_style)
        self._icon_by.currentIndexChanged.connect(self._sync_icon_style)
        self._stack.addWidget(page)

    def _add_map_row(self, value: str = "", glyph: str = "",
                     colour: str = "(none)") -> None:
        r = self._map.rowCount()
        self._map.insertRow(r)
        self._map.setItem(r, 0, QTableWidgetItem(value))
        gedit = _PictureEdit(glyph)
        apply_emoji_font(gedit)  # so a typed emoji shows as itself, not a gap
        gedit.setPlaceholderText("a character, an emoji (T, →, 🙂), or "
                                 "paste / drop a picture")
        gedit.textChanged.connect(self._refresh)
        gedit.textChanged.connect(lambda _t, e=gedit: _show_picture(e))
        _show_picture(gedit)
        self._map.setCellWidget(r, 1, gedit)
        cbox = ColorChoice(_GLYPH_CHOICES, allow_none=True)
        cbox.set_value(colour or "(none)")
        cbox.changed.connect(self._refresh)
        self._map.setCellWidget(r, 2, cbox)

    def _build_picture_page(self) -> None:
        """Pictures from a column: the column's own values drawn as the
        pictures they are, or another column's beside this one's."""
        page = QWidget()
        v = QVBoxLayout(page)
        f = QFormLayout()
        f.setContentsMargins(0, 0, 0, 0)
        self._pic_from = self._other_col_combo()
        self._pic_from.currentIndexChanged.connect(self._sync_picture)
        self._pic_from.editTextChanged.connect(self._sync_picture)
        f.addRow("Pictures from", self._pic_from)
        self._pic_place = _combo(_PICTURE_PLACES)
        self._pic_place.currentIndexChanged.connect(self._refresh)
        f.addRow("Place", self._pic_place)
        self._pic_size = QSpinBox()
        self._pic_size.setRange(MIN_PICTURE_SIZE - 1, MAX_PICTURE_SIZE)
        self._pic_size.setSpecialValueText("as tall as the row")
        self._pic_size.setValue(MIN_PICTURE_SIZE - 1)
        self._pic_size.setSuffix(" px")
        self._pic_size.setToolTip(
            "How tall each picture is drawn. Taller than a line of text "
            "makes those rows taller; left alone, a picture fits the row — "
            "so a Row height rule makes every picture bigger at once.")
        self._pic_size.valueChanged.connect(self._refresh)
        f.addRow("Size", self._pic_size)
        self._pic_shape = _combo(_PICTURE_SHAPES)
        self._pic_shape.setToolTip(
            "Cut each picture to a shape — a circle turns a photo into an "
            "avatar.")
        self._pic_shape.currentIndexChanged.connect(self._refresh)
        f.addRow("Shape", self._pic_shape)
        self._pic_tile = ColorChoice(_TILE_CHOICES, allow_none=True)
        self._pic_tile.set_value("(none)")
        self._pic_tile.setToolTip(
            "A coloured tile behind each picture, with the picture set in "
            "from its edge — for icons drawn on a plain or clear ground.")
        self._pic_tile.changed.connect(self._refresh)
        f.addRow("Tile colour", self._pic_tile)
        self._pic_hide = QCheckBox("hide the picture column")
        self._pic_hide.setToolTip(
            "The pictures are still read from it — the base64 column just "
            "isn't shown beside them.")
        self._pic_hide.toggled.connect(self._refresh)
        f.addRow("", self._pic_hide)
        v.addLayout(f)
        hint = QLabel(
            "A column holding pictures as base64 text — or as data:image "
            "addresses — shows each one as the picture it is.\n\n"
            "Pick another column above to put its picture beside this "
            "column's value, the way an icon sits: a logo beside a name. "
            "A cell whose value isn't a picture shows its text as usual.\n\n"
            "For one picture chosen by a value, paste it into an icon cell "
            "on the Icons page instead.")
        hint.setWordWrap(True)
        v.addWidget(hint)
        v.addStretch(1)
        self._stack.addWidget(page)
        self._sync_picture()

    def _sync_picture(self) -> None:
        """`hide` names the column the pictures come from, so it is only
        offered once there is one."""
        other = bool(_other_col_value(self._pic_from))
        self._pic_hide.setEnabled(other)
        if not other:
            self._pic_hide.setChecked(False)
        self._refresh()

    def _remove_map_row(self) -> None:
        if self._map.rowCount():
            self._map.removeRow(self._map.rowCount() - 1)
        self._refresh()

    def _build_number_page(self) -> None:
        page = QWidget()
        f = QFormLayout(page)
        self._numfmt = QComboBox()
        self._numfmt.setEditable(True)
        self._numfmt.addItems(_NUMBER_PRESETS)
        self._numfmt.setCurrentText(",.0f")
        self._numfmt.editTextChanged.connect(self._refresh)
        self._numfmt.currentIndexChanged.connect(self._refresh)
        self._numfmt_sample = QLabel()
        f.addRow("Format", self._numfmt)
        f.addRow("1234.5 →", self._numfmt_sample)
        self._stack.addWidget(page)

    def _build_tip_page(self) -> None:
        page = QWidget()
        v = QVBoxLayout(page)
        f = QFormLayout()
        f.setContentsMargins(0, 0, 0, 0)
        self._tip_by = self._other_col_combo()
        # "(this column)" is what every other `by` combo offers and is the
        # one thing this rule cannot mean: a cell explaining itself is the
        # value you are already looking at
        self._tip_by.setItemText(0, _PICK_A_COLUMN)
        f.addRow("Note column", self._tip_by)
        v.addLayout(f)
        hint = QLabel(
            "Resting on a cell shows the matching value from the note "
            "column — a comment that explains the number without taking a "
            "column of the table to say it.\n\n"
            "The note column keeps showing unless you also hide it: put "
            "`hide` on a line of its own, so nothing disappears from a rule "
            "that never mentioned it.\n\n"
            "A cell that is *also* too narrow for its value shows both — "
            "the note, then the full value under it.")
        hint.setWordWrap(True)
        v.addWidget(hint)
        self._stack.addWidget(page)

    def _build_hide_page(self) -> None:
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(QLabel(
            "The chosen columns stay in the data (a rule can still read them) "
            "but are not shown in this table."))
        self._stack.addWidget(page)

    def _build_show_page(self) -> None:
        page = QWidget()
        v = QVBoxLayout(page)
        hint = QLabel(
            "Only the chosen columns are shown, and they are shown in the "
            "order this rule names them — which is the one way to reorder a "
            "table without a Select Columns node in front of it.\n\n"
            "Ticking the list above names them in the table's own order. To "
            "put them in a different one, clear the ticks and type the names "
            "into the box in the order you want, comma separated: the rule "
            "text below always shows exactly what will be written.\n\n"
            "The data is untouched either way — every column still leaves "
            "the card's table port, in its original order.")
        hint.setWordWrap(True)
        v.addWidget(hint)
        self._stack.addWidget(page)

    def _build_wrap_page(self) -> None:
        page = QWidget()
        v = QVBoxLayout(page)
        v.addWidget(QLabel(
            "Long text runs onto more lines instead of being cut off, and "
            "each row grows to fit it.\n\nThis one is not per column: a row "
            "is as tall as its tallest cell, so it applies to the whole "
            "table. Pair it with a fixed width on the column you want "
            "narrow."))
        page.findChild(QLabel).setWordWrap(True)
        self._stack.addWidget(page)

    def _height_spin(self, unset: "str | None" = None) -> QSpinBox:
        """A row height in pixels. With `unset`, one step below the least
        is that word — how a spin box says "leave it alone"."""
        box = QSpinBox()
        box.setRange(MIN_ROW_HEIGHT - (1 if unset else 0), MAX_ROW_HEIGHT)
        if unset:
            box.setSpecialValueText(unset)
            box.setValue(MIN_ROW_HEIGHT - 1)
        else:
            box.setValue(40)
        box.setSuffix(" px")
        box.valueChanged.connect(self._refresh)
        return box

    def _build_height_page(self) -> None:
        """How tall every row is. For only the rows a test picks, the
        highlight page has a Row height of its own."""
        page = QWidget()
        f = QFormLayout(page)
        self._height = self._height_spin()
        f.addRow("Every row", self._height)
        hint = QLabel(
            "Every row this tall — taller to give sparklines room, or "
            "shorter for a compact table.\n\nFor only the rows that pass a "
            "test, use Highlight cells / rows and set its Row height.\n\n"
            "A mark above or below a value, or a tall sparkline, still gets "
            "the room it needs, so nothing is cut off.")
        hint.setWordWrap(True)
        f.addRow("", hint)
        self._stack.addWidget(page)

    def _build_totals_page(self) -> None:
        """Total rows and grouped rows — core/table_totals.py. One page with
        a What switch, because each line is small and they are read
        together: a total, how a column is totalled, the grouping, where
        its subtotals go, and how any of those rows look."""
        from flograph.core.table_totals import AGGREGATIONS, AGGREGATION_HELP
        page = QWidget()
        f = QFormLayout(page)
        self._total_what = _combo(_TOTAL_WHAT)
        f.addRow("What", self._total_what)
        self._total_how = QComboBox()
        for name in AGGREGATIONS:
            self._total_how.addItem(f"{name} — {AGGREGATION_HELP[name]}",
                                    name)
        self._total_how.addItem("none — leave it blank", "none")
        self._total_how.addItem("write some text instead", "text")
        self._total_text = QLineEdit()
        self._total_place = _combo(_TOTAL_PLACES)
        self._sub_place = _combo(_SUB_PLACES)
        self._group_start = _combo(_GROUP_STARTS)
        self._style_rows = _combo(_STYLE_ROWS)
        self._total_fill = ColorChoice(_FILL_CHOICES, allow_none=True)
        self._total_fill.set_value("blue")
        self._total_ink = ColorChoice(_GLYPH_CHOICES, allow_none=True)
        self._total_ink.set_value("(none)")
        self._total_bold = QCheckBox("bold text")
        self._total_bold.setChecked(True)
        self._total_hint = QLabel()
        self._total_hint.setWordWrap(True)
        self._total_rows = {}
        for label, widget in (("Total by", self._total_how),
                              ("Text", self._total_text),
                              ("Placed", self._total_place),
                              ("Subtotals go", self._sub_place),
                              ("Groups start", self._group_start),
                              ("Rows", self._style_rows),
                              ("Fill", self._total_fill),
                              ("Text colour", self._total_ink),
                              ("", self._total_bold)):
            f.addRow(label, widget)
            self._total_rows[widget] = f.labelForField(widget)
        f.addRow("", self._total_hint)
        for box in (self._total_what, self._total_how, self._total_place,
                    self._sub_place, self._group_start, self._style_rows):
            box.currentIndexChanged.connect(self._sync_totals)
        self._total_text.textChanged.connect(self._refresh)
        self._total_fill.changed.connect(self._refresh)
        self._total_ink.changed.connect(self._refresh)
        self._total_bold.toggled.connect(self._refresh)
        self._stack.addWidget(page)
        self._sync_totals()

    def _sync_totals(self) -> None:
        what = self._total_what.currentData()
        how = self._total_how.currentData()
        shown = {
            "blanket": (self._total_how, self._total_text, self._total_place),
            "column": (self._total_how, self._total_text),
            "group": (self._group_start,),
            "subtotal": (self._sub_place, self._total_text),
            "style": (self._style_rows, self._total_fill, self._total_ink,
                      self._total_bold),
        }[what]
        for widget, label in self._total_rows.items():
            visible = widget in shown
            if widget is self._total_text and what == "column":
                visible = how == "text"
            widget.setVisible(visible)
            if label is not None:
                label.setVisible(visible)
        self._total_text.setPlaceholderText(
            {"blanket": "the label — Total, Grand total…",
             "column": "what the total row says here — All regions…",
             "subtotal": "what follows a group's name — Total, Subtotal…"
             }.get(what, ""))
        self._total_hint.setText({
            "blanket": "A row totalling every number column. Pick columns "
                       "under 'How these columns are totalled' to total one "
                       "differently — a later line wins for its columns.",
            "column": "How the chosen columns are totalled, on the total row "
                      "and on every subtotal. A total in the column's own "
                      "units (a sum, an average) takes its number format.",
            "group": "Rows sharing a value gather under a header row you "
                     "can click to fold. Several columns nest, outermost "
                     "first. The grouping columns move into the group "
                     "column.",
            "subtotal": "Where each group's subtotals are written. Groups "
                        "only have subtotals for columns that are totalled.",
            "style": "Colours every cell of those rows. To colour a total "
                     "by its value, use Highlight cells / rows and set Draw "
                     "on.",
        }[what])
        if self._kind.currentIndex() == K_TOTALS:
            self._on_kind()
        self._refresh()

    def _totals_line(self, cols: str) -> str:
        what = self._total_what.currentData()
        how = self._total_how.currentData()
        text = self._total_text.text().strip().replace('"', "")
        if what == "blanket":
            parts = ["total"]
            if how not in ("none", "text"):
                parts.append(how)
            place = self._total_place.currentData()
            if place != "bottom" or len(parts) == 1:
                parts.append(place)
            if text:
                parts.append(f'"{text}"')
            return " ".join(parts)
        if what == "column":
            if not cols:
                return ""
            if how == "text":
                return f'{cols} total "{text}"' if text else ""
            return f"{cols} total {how}"
        if what == "group":
            if not cols:
                return ""
            start = self._group_start.currentData()
            return f"group {cols}" + (f" {start}" if start != "open" else "")
        if what == "subtotal":
            line = f"subtotal {self._sub_place.currentData()}"
            return line + (f' "{text}"' if text else "")
        parts = []
        fill = self._total_fill.value()
        if fill and fill != "(none)":
            parts.append(f"bg {fill}")
        ink = self._total_ink.value()
        if ink and ink != "(none)":
            parts.append(f"fg {ink}")
        if self._total_bold.isChecked():
            parts.append("bold")
        if not parts:
            return ""
        return f"{self._style_rows.currentData()} => {', '.join(parts)}"

    def _load_totals(self, rule) -> None:
        if rule.mode == "group":
            _pick_data(self._total_what, "group")
            _pick_data(self._group_start, rule.total_place or "open")
        elif rule.mode == "subtotal":
            _pick_data(self._total_what, "subtotal")
            _pick_data(self._sub_place, rule.total_place or "above")
            self._total_text.setText(rule.label or "")
        elif rule.mode == "total_style":
            _pick_data(self._total_what, "style")
            kinds = set(rule.rows_on or ())
            _pick_data(self._style_rows,
                       "totals" if len(kinds) == 3 else
                       "subtotal" if kinds == {"group", "subtotal"} else
                       next(iter(kinds), "total"))
            self._total_fill.set_value(fill_token(rule.bg) if rule.bg
                                       else "(none)")
            self._total_ink.set_value(glyph_token(rule.fg) if rule.fg
                                      else "(none)")
            self._total_bold.setChecked(bool(rule.bold))
        elif rule.columns:
            _pick_data(self._total_what, "column")
            if rule.total_text is not None:
                _pick_data(self._total_how, "text")
                self._total_text.setText(rule.total_text)
            else:
                _pick_data(self._total_how, rule.total_agg or "sum")
        else:
            _pick_data(self._total_what, "blanket")
            _pick_data(self._total_how, rule.total_agg or "none")
            _pick_data(self._total_place, rule.total_place or "bottom")
            self._total_text.setText(rule.label or "")
        self._sync_totals()

    def _build_layout_page(self) -> None:
        """Width, alignment and header label.

        One property per rule, chosen here rather than set all at once: a
        rule is one line, and a page that wrote three of them from one
        press would have nothing sensible to show when you came back to
        edit any one of them.
        """
        page = QWidget()
        f = QFormLayout(page)
        self._layout_prop = QComboBox()
        self._layout_prop.addItem("Fixed width", "width")
        self._layout_prop.addItem("Alignment", "align")
        self._layout_prop.addItem("Header label", "label")
        f.addRow("Set", self._layout_prop)

        self._layout_width = QSpinBox()
        # one step below the legal minimum is the "auto" position — how a
        # spin box says "unset", and here how a rule says "back to fitting
        # the content" over an earlier pattern rule
        self._layout_width.setRange(MIN_RULE_WIDTH - 1, MAX_RULE_WIDTH)
        self._layout_width.setSpecialValueText("auto — fit the content")
        self._layout_width.setSuffix(" px")
        self._layout_width.setValue(120)
        f.addRow("Width", self._layout_width)

        self._layout_align = _combo([("Left", "left"), ("Right", "right"),
                                     ("Centre", "center")])
        f.addRow("Align", self._layout_align)

        self._layout_label = QLineEdit()
        self._layout_label.setPlaceholderText(
            "shown instead of the column's own name")
        apply_emoji_font(self._layout_label)
        f.addRow("Header label", self._layout_label)

        self._layout_note = QLabel(
            "Layout rules shape the column, not the values: sorting, "
            "Ctrl+C and exports all still use the real name and the real "
            "numbers.")
        self._layout_note.setWordWrap(True)
        f.addRow("", self._layout_note)

        self._layout_prop.currentIndexChanged.connect(self._sync_layout_prop)
        self._layout_prop.currentIndexChanged.connect(self._refresh)
        self._layout_width.valueChanged.connect(self._refresh)
        self._layout_align.currentIndexChanged.connect(self._refresh)
        self._layout_label.textChanged.connect(self._refresh)
        self._layout_form = f
        self._stack.addWidget(page)
        self._sync_layout_prop()

    def _sync_layout_prop(self) -> None:
        """Show only the input the chosen property uses."""
        prop = self._layout_prop.currentData()
        for widget, wanted in ((self._layout_width, "width"),
                               (self._layout_align, "align"),
                               (self._layout_label, "label")):
            widget.setVisible(prop == wanted)
            label = self._layout_form.labelForField(widget)
            if label is not None:
                label.setVisible(prop == wanted)

    # ------------------------------------------------------------- reactive

    def _on_kind(self) -> None:
        idx = self._kind.currentIndex()
        self._stack.setCurrentIndex(idx)
        # `wrap` is the one rule that takes no columns — offering the picker
        # anyway would promise something the rule cannot keep
        table_wide = idx in (K_WRAP, K_HEIGHT) or (
            idx == K_TOTALS and self._total_what.currentData()
            in ("blanket", "subtotal", "style"))
        self._col_list.setEnabled(not table_wide)
        self._col_edit.setEnabled(not table_wide)
        if idx == K_ICONS:
            self._sync_icon_style()
            return
        self._col_label.setText("Whole table" if table_wide else
                                "Draw in" if idx in (K_SPARK, K_PICTURE)
                                else "Columns")
        if self._columns:
            self._col_list.setSelectionMode(_MULTI)

    def _sync_icon_style(self) -> None:
        """Show the graduated-set fields or the value-map table, and — for
        the map, whose source must be one column — pin column selection to
        a single pick when 'Decided by' is left on '(this column)'."""
        is_map = self._icon_style.currentData() == "map"
        self._icon_set_box.setVisible(not is_map)
        self._icon_map_box.setVisible(is_map)
        single = is_map and not _other_col_value(self._icon_by)
        self._col_label.setText("Shown in column" if single else "Columns")
        if self._columns:
            self._col_list.setSelectionMode(_SINGLE if single else _MULTI)
        self._refresh()

    def _sync_highlight_inputs(self) -> None:
        op = self._op.currentData()
        self._val1.setVisible(op not in ("empty", "notempty"))
        two = op == "between"
        self._val2.setVisible(two)
        self._and.setVisible(two)
        # only the two that compare a whole value take a pattern; contains
        # and matches are their own kinds of partial match already
        wild = op in ("=", "!=")
        self._val1.setPlaceholderText("late  ·  late*  ·  A?  ·  \"10*\""
                                      if wild else "")
        self._val1.setToolTip(_WILDCARD_HELP if wild else "")
        self._refresh()

    def _refresh(self) -> None:
        if not hasattr(self, "_buttons"):
            return
        if hasattr(self, "_numfmt_sample"):
            self._numfmt_sample.setText(self._number_sample())
        line = self._line()
        # a pasted picture is shortened for show — the line itself keeps it
        self._preview.setText(abbreviate_pictures(line)
                              or "— fill in the fields above —")
        self._buttons.button(QDialogButtonBox.Ok).setEnabled(bool(line))

    def _number_sample(self) -> str:
        spec = self._numfmt.currentText().strip()
        try:
            prefix = ""
            if spec[:1] in "$€£¥":
                prefix, spec = spec[0], spec[1:]
            return prefix + format(1234.5, spec) if spec else "1234.5"
        except ValueError:
            return "(invalid format)"

    # ------------------------------------------------------------- prefill

    def _load(self, rule) -> None:
        self._kind.setCurrentIndex(_MODE_KIND.get(rule.mode, 0))
        self._on_kind()
        self._select_columns(rule.columns)
        for box in (self._scale_only, self._bar_only, self._icon_only,
                    self._auto_only):
            box.setChecked(bool(rule.hide_value))
        if rule.mode == "color_scale":
            _pick_data(self._scale, scale_token(rule.low, rule.mid, rule.high))
            self._set_other_col(self._scale_by, rule.source)
        elif rule.mode == "auto_color":
            _pick_data(self._auto_palette, rule.palette or DEFAULT_PALETTE)
            _pick_data(self._auto_shape,
                       "text" if rule.ink_only
                       else ("" if rule.as_pill else "fill"))
            self._set_other_col(self._auto_by, rule.source)
        elif rule.mode == "tooltip":
            self._set_other_col(self._tip_by, rule.source)
        elif rule.mode == "sparkline":
            self._load_spark(rule)
        elif rule.mode in ("total", "subtotal", "group", "total_style"):
            self._load_totals(rule)
            self._select_columns(rule.columns)
        elif rule.mode == "data_bar":
            self._bar.set_value(bar_token(rule.color))
            self._set_other_col(self._bar_by, rule.source)
        elif rule.mode == "highlight":
            _pick_data(self._op, rule.op or "=")
            self._sync_highlight_inputs()
            value = rule.value
            if isinstance(value, (list, tuple)) and len(value) == 2:
                self._val1.setText(str(value[0]))
                self._val2.setText(str(value[1]))
            elif value is not None:
                self._val1.setText(str(value))
            self._fill.set_value(fill_token(rule.bg) or "(none)")
            self._hl_fg.set_value(glyph_token(rule.fg) if rule.fg
                                  else "(none)")
            kinds = tuple(rule.rows_on or ())
            _pick_data(self._hl_on, next(
                (w for w, k in _ON_KINDS.items()
                 if set(k) == set(kinds)), ""))
            self._bold.setChecked(bool(rule.bold))
            self._hl_height.setValue(rule.row_height or MIN_ROW_HEIGHT - 1)
            self._scope.setCurrentIndex(1 if rule.scope == "row" else 0)
            self._set_other_col(self._hl_test, rule.source)
            # The mark and where it sits. Left out, these were rebuilt from
            # whatever the widgets happened to hold, so editing a rule threw
            # its icon away and put its place back to the left.
            self._hl_pill.setChecked(bool(rule.as_pill))
            if rule.as_pill:
                self._hl_badge.setText(rule.glyph or "")
            else:
                self._hl_icon.setText(rule.glyph or "")
                self._hl_icon_color.set_value(
                    glyph_token(rule.glyph_color) or "(none)")
            _pick_data(self._hl_place,
                       "" if rule.glyph_where in (None, "left")
                       else rule.glyph_where)
        elif rule.mode == "icons":
            _pick_data(self._icon_style, "set")
            _pick_data(self._iconset, rule.icon_set or "traffic")
            self._icon_reverse.setChecked(bool(rule.reverse))
            self._set_other_col(self._icon_by, rule.source)
            self._load_icon_place(rule)
            self._sync_icon_style()
        elif rule.mode == "icon_map":
            _pick_data(self._icon_style, "map")
            self._load_icon_place(rule)
            # `source` is the deciding column; show it as "(this column)"
            # only when it is the single column the icon is drawn in.
            src = rule.source if rule.source not in rule.columns else None
            self._set_other_col(self._icon_by, src)
            _pick_data(self._icon_shape, rule.picture_shape or "")
            self._map.setRowCount(0)
            for value, pair in (rule.mapping or {}).items():
                glyph = pair[0] if pair else ""
                colour = glyph_token(pair[1]) if len(pair) > 1 and pair[1] else ""
                self._add_map_row(value, glyph, colour)
            if not self._map.rowCount():
                self._add_map_row()
            self._sync_icon_style()
        elif rule.mode == "image":
            self._set_other_col(self._pic_from, rule.source)
            # `only` from another column is its picture in place of the value
            place = rule.glyph_where or ("in" if rule.hide_value
                                         and rule.source else "")
            _pick_data(self._pic_place, place)
            self._pic_size.setValue(rule.picture_size or MIN_PICTURE_SIZE - 1)
            _pick_data(self._pic_shape, rule.picture_shape or "")
            self._pic_tile.set_value(_tile_token(rule.picture_tile))
            self._sync_picture()
            self._pic_hide.setChecked(rule.take_sources == "hide")
        elif rule.mode == "number_format":
            self._numfmt.setCurrentText(rule.number_spec or "")
        elif rule.mode == "row_height":
            self._height.setValue(rule.row_height or 40)
        elif rule.mode == "column_width":
            _pick_data(self._layout_prop, "width")
            self._layout_width.setValue(rule.width or MIN_RULE_WIDTH - 1)
            self._sync_layout_prop()
        elif rule.mode == "align":
            _pick_data(self._layout_prop, "align")
            _pick_data(self._layout_align, rule.align or "left")
            self._sync_layout_prop()
        elif rule.mode == "header_label":
            _pick_data(self._layout_prop, "label")
            self._layout_label.setText(rule.label or "")
            self._sync_layout_prop()

    def _load_icon_place(self, rule) -> None:
        """Where an icon rule's mark sits, and whether it is in a pill.

        Shared by both icon kinds because both write the same two tokens,
        and neither read them back — an `icons … pill right` came home as
        a plain set on the left, which is what made editing a rule mean
        setting it up again.
        """
        _pick_data(self._icon_place,
                   "" if rule.glyph_where in (None, "left")
                   else rule.glyph_where)
        self._icon_pill.setChecked(bool(rule.as_pill))

    # -------------------------------------------------------- line builder

    @staticmethod
    def _by(box: QComboBox) -> str:
        """The ``  by <column>`` DSL tail for an "another column" combo,
        or ``""`` when it is on "(this column)"."""
        name = _other_col_value(box)
        return f" by {quote_column(name)}" if name else ""

    def _line(self) -> str:
        kind = self._kind.currentIndex()
        cols = self._columns_text()
        if kind == K_TIP:
            note = _other_col_value(self._tip_by)
            return (f"{cols} tooltip {quote_column(note)}"
                    if cols and note else "")
        if kind == K_HIDE:
            return f"hide {cols}" if cols else ""
        if kind == K_SHOW:
            return f"show {cols}" if cols else ""
        if kind == K_WRAP:
            return "wrap"          # table-wide: it names no columns
        if kind == K_HEIGHT:
            return f"height {self._height.value()}"   # table-wide too
        if kind == K_TOTALS:
            return self._totals_line(cols)
        if not cols:
            return ""
        if kind == K_SCALE:
            return (f"{cols} scale {self._scale.currentData()}"
                    f"{self._by(self._scale_by)}{_only(self._scale_only)}")
        if kind == K_AUTO:
            # the shape word goes before the `by` clause, or the column
            # name the clause hands back would swallow it
            shape = self._auto_shape.currentData()
            return (f"{cols} autocolour {self._auto_palette.currentData()}"
                    f"{' ' + shape if shape else ''}"
                    f"{self._by(self._auto_by)}{_only(self._auto_only)}")
        if kind == K_SPARK:
            return self._spark_line(cols)
        if kind == K_BAR:
            return (f"{cols} bar {self._bar.value()}"
                    f"{self._by(self._bar_by)}{_only(self._bar_only)}")
        if kind == K_HIGHLIGHT:
            op = self._op.currentData()
            words = {">": ">", ">=": ">=", "<": "<", "<=": "<=", "=": "=",
                     "!=": "!=", "contains": "contains", "starts": "starts with",
                     "ends": "ends with", "matches": "matches",
                     "empty": "is empty", "notempty": "is not empty"}
            test = _other_col_value(self._hl_test)
            subject = f"{cols} if {quote_column(test)}" if test else cols
            if op in ("empty", "notempty"):
                cond = f"{subject} {words[op]}"
            elif op == "between":
                v1, v2 = self._val1.text().strip(), self._val2.text().strip()
                if not v1 or not v2:
                    return ""
                cond = f"{subject} between {v1} {v2}"
            else:
                value = self._val1.text().strip()
                if not value:
                    return ""
                cond = f"{subject} {words[op]} {value}"
            # One style chunk per thing the rule draws, joined with commas —
            # the shape `_parse_style_tokens` reads. A list rather than a
            # built-up string because a highlight can now say several things
            # at once (a fill, a mark, bold, a height) and every one of them
            # has to survive being read back in and written out again.
            fill = self._fill.value()
            fill = "" if fill == "(none)" else fill
            row_scope = self._scope.currentIndex() == 1
            place = self._hl_place.currentData()
            parts: list = []
            if row_scope:
                # a row highlight paints every cell of the row, so the
                # parser refuses a pill or an icon on it — a fill it must
                # have, or there is nothing to paint the row with
                parts.append(f"row {fill or 'grey'}")
            elif self._hl_pill.isChecked():
                badge = self._hl_badge.text().strip()
                parts.append(" ".join(
                    ["pill"] + ([fill] if fill else [])
                    + ([f'"{badge}"'] if badge else [])
                    + ([place] if place else [])))
            elif fill:
                parts.append(f"bg {fill}")
            glyph = "" if row_scope else _glyph_text(self._hl_icon)
            if glyph:
                colour = self._hl_icon_color.value()
                parts.append(" ".join(
                    ["icon", glyph]
                    + ([colour] if colour and colour != "(none)" else [])
                    # a pill has already spent the place on itself
                    + ([place] if place and not self._hl_pill.isChecked()
                       else [])))
            ink = self._hl_fg.value()
            if ink and ink != "(none)":
                parts.append(f"fg {ink}")
            if self._bold.isChecked():
                parts.append("bold")
            asked = self._hl_height.value()
            if asked >= MIN_ROW_HEIGHT:
                parts.append(f"height {asked}")
            on = self._hl_on.currentData()
            if parts and on:
                parts.append(f"on {on}")
            return f"{cond} => {', '.join(parts)}" if parts else ""
        if kind == K_ICONS:
            decider = _other_col_value(self._icon_by)
            if self._icon_style.currentData() == "map":
                chosen = self._chosen_columns()
                source = quote_column(decider or (chosen[0] if chosen else ""))
                pairs = []
                for r in range(self._map.rowCount()):
                    item = self._map.item(r, 0)
                    value = item.text().strip() if item else ""
                    if (self._map.cellWidget(r, 1) is None
                            or self._map.cellWidget(r, 2) is None):
                        # a row mid-insert: its item is set (which says the
                        # cell changed) before its editors exist
                        continue
                    glyph = _glyph_text(self._map.cellWidget(r, 1))
                    colour = self._map.cellWidget(r, 2).value()
                    if not value or not glyph:
                        continue
                    pairs.append(f"{value}={glyph}"
                                 + ("" if colour == "(none)" else f" {colour}"))
                if not source or not pairs:
                    return ""
                # `only` leads here: a trailing one would be read as the
                # last pair's colour
                only = "only " if self._icon_only.isChecked() else ""
                where = self._icon_place.currentData()
                lead = only + (f"{where} " if where else "")
                lead += "pill " if self._icon_pill.isChecked() else ""
                shape = self._icon_shape.currentData()
                lead += f"{shape} " if shape else ""
                return (f"{cols} iconmap {lead}{source}: "
                        + ", ".join(pairs))
            rev = " reverse" if self._icon_reverse.isChecked() else ""
            by = f" by {quote_column(decider)}" if decider else ""
            # before the `by` clause, or the column name would swallow them
            trail = _pill(self._icon_pill) + _place(self._icon_place)
            return (f"{cols} icons {self._iconset.currentData()}{rev}{trail}"
                    f"{by}{_only(self._icon_only)}")
        if kind == K_PICTURE:
            source = _other_col_value(self._pic_from)
            place = self._pic_place.currentData()
            size = self._pic_size.value()
            shape = self._pic_shape.currentData()
            tile = self._pic_tile.value()
            words = ((f" {place}" if place else "")
                     + (f" {size}px" if size >= MIN_PICTURE_SIZE else "")
                     + (f" {shape}" if shape else "")
                     + (f" on {tile}" if tile and tile != "(none)" else ""))
            if not source:
                return f"{cols} image{words}"
            hide = " hide" if self._pic_hide.isChecked() else ""
            return f"{cols} image{words} from {quote_column(source)}{hide}"
        if kind == K_NUMBER:
            spec = self._numfmt.currentText().strip()
            return f"{cols} format {spec}" if spec else ""
        if kind == K_LAYOUT:
            prop = self._layout_prop.currentData()
            if prop == "width":
                value = self._layout_width.value()
                asked = ("auto" if value < MIN_RULE_WIDTH else str(value))
                return f"{cols} width {asked}"
            if prop == "align":
                return f"{cols} align {self._layout_align.currentData()}"
            text = self._layout_label.text().strip()
            # quoted, because a header is prose: "Revenue (£m), net" would
            # otherwise read as a second column name after the comma
            return f'{cols} label "{text}"' if text else ""
        return ""


class RuleManager(QDialog):
    """The list of applied rules, with add / edit / remove / reorder."""

    def __init__(self, text: str, columns, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Conditional formatting rules")
        self.setModal(True)
        self.resize(520, 380)
        self._columns = list(columns or [])
        # each entry: [raw line, Rule | None, error | None]
        self._entries = [list(e) for e in parse_rule_lines(text)]

        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "Rules apply top to bottom — a later rule wins where two touch "
            "the same cell."))
        body = QHBoxLayout()
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._sync_buttons)
        self._list.itemDoubleClicked.connect(lambda *_: self._edit())
        body.addWidget(self._list, 1)

        side = QVBoxLayout()
        self._add_btn = QPushButton("＋  Add rule")
        self._edit_btn = QPushButton("Edit…")
        self._dup_btn = QPushButton("Duplicate")
        self._del_btn = QPushButton("Remove")
        self._up_btn = QPushButton("Move up")
        self._down_btn = QPushButton("Move down")
        self._add_btn.clicked.connect(self._add)
        self._edit_btn.clicked.connect(self._edit)
        self._dup_btn.clicked.connect(self._duplicate)
        self._del_btn.clicked.connect(self._remove)
        self._up_btn.clicked.connect(lambda: self._move(-1))
        self._down_btn.clicked.connect(lambda: self._move(1))
        for b in (self._add_btn, self._edit_btn, self._dup_btn, self._del_btn,
                  self._up_btn, self._down_btn):
            side.addWidget(b)
        side.addStretch(1)
        body.addLayout(side)
        outer.addLayout(body)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._reload()

    # ------------------------------------------------------------- result

    def result_text(self) -> str:
        return "\n".join(e[0] for e in self._entries)

    # ------------------------------------------------------------- list

    def _reload(self) -> None:
        row = self._list.currentRow()
        self._list.clear()
        for raw, rule, error in self._entries:
            if rule is not None:
                item = QListWidgetItem(rule_summary(rule))
            elif error is not None:
                item = QListWidgetItem(
                    f"⚠  {abbreviate_pictures(raw.strip())}   "
                    f"({abbreviate_pictures(error)})")
                item.setForeground(Qt.red)
            else:                                   # comment / blank
                item = QListWidgetItem(raw.strip() or "(blank line)")
                item.setForeground(Qt.gray)
            self._list.addItem(item)
        self._list.setCurrentRow(min(row, self._list.count() - 1))
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        row = self._list.currentRow()
        has = row >= 0
        rule = self._entries[row][1] if has else None
        self._edit_btn.setEnabled(rule is not None)
        self._dup_btn.setEnabled(rule is not None)
        self._del_btn.setEnabled(has)
        self._up_btn.setEnabled(row > 0)
        self._down_btn.setEnabled(0 <= row < len(self._entries) - 1)

    # ------------------------------------------------------------- actions

    def _add(self) -> None:
        dlg = RuleBuilder(self._columns, self)
        if dlg.exec() == QDialog.Accepted and dlg.line():
            self._entries.append(self._entry_for(dlg.line()))
            self._reload()
            self._list.setCurrentRow(len(self._entries) - 1)

    def _edit(self) -> None:
        row = self._list.currentRow()
        if row < 0 or self._entries[row][1] is None:
            return
        dlg = RuleBuilder(self._columns, self, rule=self._entries[row][1])
        if dlg.exec() == QDialog.Accepted and dlg.line():
            self._entries[row] = self._entry_for(dlg.line())
            self._reload()

    def _duplicate(self) -> None:
        row = self._list.currentRow()
        if row < 0 or self._entries[row][1] is None:
            return
        self._entries.insert(row + 1, self._entry_for(self._entries[row][0]))
        self._reload()
        self._list.setCurrentRow(row + 1)

    def _remove(self) -> None:
        row = self._list.currentRow()
        if row >= 0:
            del self._entries[row]
            self._reload()

    def _move(self, delta: int) -> None:
        row = self._list.currentRow()
        target = row + delta
        if 0 <= row < len(self._entries) and 0 <= target < len(self._entries):
            self._entries[row], self._entries[target] = (
                self._entries[target], self._entries[row])
            self._reload()
            self._list.setCurrentRow(target)

    @staticmethod
    def _entry_for(line: str) -> list:
        parsed = parse_rule_lines(line)
        return list(parsed[0]) if parsed else [line, None, None]
