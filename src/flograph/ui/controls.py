"""Input controls: the widgets behind `NODE["card"] == "control"` nodes.

A control node has no output to render — it *is* the input. The user drags
a slider or picks a date, that lands in the node's `value` param through the
undo stack, and everything downstream re-runs. The point is dashboards you
can hand to someone who will never open the model canvas: they turn the
knobs, the charts answer.

One widget serves both hosts. The canvas card (`ui/canvas/node_item.py`)
and the dashboard tile (`ui/dashboard/tile_item.py`) each build one of these
and connect the same two signals, so a control behaves identically wherever
it is placed and neither host knows what a slider is.

Adding a control shape means adding a class here, naming it in
`core.script.CONTROL_KINDS` so node scripts may declare it, and writing a
node script under `flograph/nodes/input/`; adding a control *node* built on
an existing shape means only the script. Each shape reads a fixed set of well-known params:

    every shape   value              the live value; what the node outputs
                  caption            label drawn above the widget
    slider        minimum maximum step decimals
    range         minimum maximum step decimals  (value is a JSON pair)
    number        minimum maximum step decimals prefix suffix
    text          placeholder multiline
    date          minimum maximum    ISO bounds, blank for unbounded
    toggle        text               the label beside the tick box
    choice        items              newline-separated options

Any of those settings can also arrive down a wire: the host resolves the
node's own input ports into a dict keyed by port name and hands it to
set_upstream(), and `_wired(port, fallback)` prefers it over the typed
param. That is what lets a slider take its range from a column instead of
from constants somebody typed.

Values are plain JSON-safe scalars, so they serialize with the project and
undo like any other param.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QDate, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QDoubleSpinBox, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QSizePolicy, QSlider, QStyle,
    QStyleOptionButton, QStyleOptionSlider, QToolButton, QVBoxLayout, QWidget,
)

from . import theme

ISO_FORMAT = "yyyy-MM-dd"

# QLineEdit defaults to a 32767-character cap and enforces it *silently* —
# setText and paste both truncate with no signal, no exception and no visible
# sign. That is fine for a name or a separator, and quietly destructive for
# any field a whole value can be pasted into: a base64-encoded image (an
# Image node's source, or a Text control feeding one) runs to hundreds of
# thousands of characters, and a truncated one still starts with valid PNG
# or GIF magic, so it half-renders instead of failing. Anywhere a user can
# paste an arbitrary value, lift the cap.
UNCAPPED_TEXT = 2_000_000_000  # ~INT_MAX; QLineEdit allocates nothing up front

# Ticked colour for a Toggle's box — the theme has no accent of its own, and
# the wire colour for a bool port is a warning red, wrong for "on".
CHECK_ON = QColor("#3b82f6")

# A change waiting for Apply: the same amber as a dirty node's LED, so
# "not reached the flow yet" reads the same everywhere it is said.
PENDING = QColor("#f59e0b")
# An editor holding a value the node will refuse
INVALID = QColor("#ef4444")


def _ink_on(colour: QColor) -> str:
    """Near-black or white, whichever stays readable on `colour` — the
    slicer's rule (`slicer_list.ink_on`), not imported from it because the
    slicer's module imports the canvas, which imports this one."""
    luminance = (0.299 * colour.red() + 0.587 * colour.green()
                 + 0.114 * colour.blue()) / 255
    return "#111827" if luminance > 0.6 else "#ffffff"

# Natural size for a control card on the canvas and a tile on a dashboard.
# Chosen so the widget plus its caption fits without scrolling.
CONTROL_SIZES: dict[str, tuple[float, float]] = {
    "slider": (240.0, 96.0),
    "range": (260.0, 96.0),
    "number": (200.0, 84.0),
    "text": (240.0, 84.0),
    "date": (200.0, 84.0),
    "toggle": (200.0, 76.0),
    "choice": (220.0, 84.0),
}
DEFAULT_CONTROL_SIZE = (220.0, 90.0)


def control_size(kind: str) -> tuple[float, float]:
    return CONTROL_SIZES.get(kind, DEFAULT_CONTROL_SIZE)


def qdate_to_iso(date: QDate) -> str:
    return date.toString(ISO_FORMAT) if date.isValid() else ""


def iso_to_qdate(value) -> Optional[QDate]:
    """A stored "YYYY-MM-DD" as a QDate, or None when it's blank or
    unparseable — a control should fall back to its own default rather than
    refuse to draw because someone hand-edited the param."""
    text = str(value or "").strip()
    if not text:
        return None
    date = QDate.fromString(text[:10], ISO_FORMAT)
    return date if date.isValid() else None


def option_list(raw) -> list[str]:
    """The options a choice control offers, from its newline-separated
    `items` param — the same parse the node's run() uses."""
    from flograph.core.controls import lines_to_values
    return lines_to_values(raw)


def accent_of(params: dict) -> QColor:
    """A control's accent: its own `accent` param, or the blue every
    control has always used. A garbled colour falls back rather than
    painting black."""
    colour = QColor(str((params or {}).get("accent") or ""))
    return colour if colour.isValid() else QColor(CHECK_ON)


def _stylesheet(accent: Optional[QColor] = None) -> str:
    """Controls sit on a node card, not on the desktop, so their chrome has
    to match the card rather than the OS default."""
    accent = QColor(accent) if accent is not None else QColor(CHECK_ON)
    on = accent.name()
    return (
        # by object name, not a bare QWidget rule: that would cascade into
        # every child and repaint the spin box and combo popup too
        f"QWidget#control_root {{ background: {theme.NODE_BODY.name()}; }}"
        f"QLabel {{ color: {theme.NODE_TEXT.name()}; font-size: 9pt;"
        f" background: transparent; }}"
        # the caption names the control, so it reads as a label rather than
        # as a footnote: full size, a touch of weight, quieter colour
        f"QLabel#caption {{ color: {theme.NODE_SUBTEXT.name()};"
        f" font-size: 9pt; font-weight: 600; }}"
        f"QLabel#control_help {{ color: {theme.NODE_SUBTEXT.name()};"
        f" font-size: 9pt; }}"
        f"QLabel#control_help:hover {{ color: {on}; }}"
        # Drawn rather than left to the platform: a stock QSlider on a dark
        # card is a grey line with a grey nub, and nothing says how far
        # along it is. The filled part is the value; the knob matches Between.
        f"QSlider::groove:horizontal {{ height: 4px; border-radius: 2px;"
        f" background: {theme.NODE_HEADER.name()}; }}"
        f"QSlider::sub-page:horizontal {{ height: 4px; border-radius: 2px;"
        f" background: {on}; }}"
        f"QSlider::handle:horizontal {{ width: 13px; height: 13px;"
        f" margin: -5px 0; border-radius: 7px;"
        f" background: {theme.NODE_TEXT.name()};"
        f" border: 1px solid {theme.NODE_BORDER.name()}; }}"
        f"QSlider::handle:horizontal:focus, QSlider::handle:horizontal:hover"
        f" {{ border: 2px solid {on}; }}"
        # a choice shown as buttons: a segmented row, the pick filled in
        f"QToolButton#choice_button {{ color: {theme.NODE_TEXT.name()};"
        f" background: {theme.NODE_HEADER.name()};"
        f" border: 1px solid {theme.NODE_BORDER.name()};"
        f" border-radius: 3px; padding: 2px 8px; font-size: 9pt; }}"
        f"QToolButton#choice_button:hover {{ border-color: {on}; }}"
        f"QToolButton#choice_button:checked {{ background: {on};"
        f" border-color: {on}; color: {_ink_on(accent)}; }}"
        f"QRadioButton {{ color: {theme.NODE_TEXT.name()}; font-size: 9pt;"
        f" background: transparent; spacing: 6px; }}"
        # drawn for the tick box's reason: the platform's ring vanishes on a
        # dark card, and an empty ring is what says "you could pick this"
        f"QRadioButton::indicator {{ width: 12px; height: 12px;"
        f" border-radius: 7px; border: 1px solid {theme.NODE_SUBTEXT.name()};"
        f" background: {theme.NODE_HEADER.name()}; }}"
        f"QRadioButton::indicator:hover {{ border-color: {on}; }}"
        # same border width as unpicked, or the label jumps sideways
        f"QRadioButton::indicator:checked {{ border-color: {on};"
        f" background: qradialgradient(cx:0.5, cy:0.5, radius:0.5,"
        f" fx:0.5, fy:0.5, stop:0 {on}, stop:0.55 {on},"
        f" stop:0.65 {theme.NODE_HEADER.name()},"
        f" stop:1 {theme.NODE_HEADER.name()}); }}"
        # the range ends sit quietly beside the track; the value under the
        # handle is the number being read, so it stays full contrast
        f"QLabel#bound {{ color: {theme.NODE_SUBTEXT.name()};"
        f" font-size: 8pt; }}"
        f"QLabel#control_readout {{ color: {theme.NODE_TEXT.name()};"
        f" font-size: 8.5pt; font-weight: bold; }}"
        f"QWidget#readout_row {{ background: transparent; }}"
        f"QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QDateEdit,"
        f" QComboBox {{ background: {theme.NODE_BODY.name()};"
        f" color: {theme.NODE_TEXT.name()};"
        f" border: 1px solid {theme.NODE_BORDER.name()};"
        f" border-radius: 3px; padding: 2px 4px; font-size: 9pt; }}"
        # where the keyboard is, in the control's own colour
        f"QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,"
        f" QDoubleSpinBox:focus, QDateEdit:focus, QComboBox:focus"
        f" {{ border-color: {on}; }}"
        # set on an editor whose value is refused (a required box left
        # empty, text that misses its pattern) — after :focus, so it wins
        f"*[invalid=\"true\"] {{ border: 1px solid {INVALID.name()}; }}"
        f"QCheckBox {{ color: {theme.NODE_TEXT.name()}; font-size: 9pt;"
        f" background: transparent; spacing: 6px; }}"
        # The box is drawn explicitly. Left to the platform style on a dark
        # card it comes out as a bare tick floating in space when checked and
        # nothing at all when unchecked — an empty box is what tells someone
        # there is something here to click.
        f"QCheckBox::indicator {{ width: 14px; height: 14px;"
        f" border-radius: 3px; border: 1px solid {theme.NODE_SUBTEXT.name()};"
        f" background: {theme.NODE_HEADER.name()}; }}"
        f"QCheckBox::indicator:hover {{ border-color: {on}; }}"
        f"QCheckBox::indicator:checked {{ background: {on};"
        f" border-color: {on}; }}"
        f"QCheckBox::indicator:disabled {{ border-color:"
        f" {theme.NODE_BORDER.name()}; }}"
        # Apply / Reset ride the caption row: small, flat until hovered, so
        # a control that has nothing pending looks as it always did
        f"QWidget#caption_row {{ background: transparent; }}"
        f"QToolButton#control_apply, QToolButton#control_reset {{"
        f" color: {theme.NODE_TEXT.name()}; background: transparent;"
        f" border: 1px solid {theme.NODE_BORDER.name()};"
        f" border-radius: 3px; padding: 0px 5px; font-size: 8pt; }}"
        f"QToolButton#control_apply {{ border-color: {PENDING.name()};"
        f" color: {PENDING.name()}; font-weight: bold; }}"
        f"QToolButton#control_apply:hover, QToolButton#control_reset:hover"
        f" {{ background: {theme.NODE_HEADER.name()}; }}"
        f"QLabel#control_pending {{ color: {PENDING.name()};"
        f" font-size: 9pt; }}"
    )


class _TickBox(QCheckBox):
    """A checkbox whose tick is painted, not styled in.

    The box itself has to be drawn by the stylesheet — left to the platform
    style on a dark card it disappears — but a stylesheet can only put a tick
    inside it via `image: url(...)`, and Qt's stylesheet parser rejects an
    inline SVG data URI (it trips over the `;` and the markup). Shipping a
    .svg file would then have to survive the onefile build. Painting two
    lines is less machinery than either.
    """

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self.isChecked():
            return
        option = QStyleOptionButton()
        self.initStyleOption(option)
        box = self.style().subElementRect(
            QStyle.SE_CheckBoxIndicator, option, self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("white"), 1.9)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        # a tick as a fraction of the box, so it tracks any indicator size
        left, top = box.left(), box.top()
        w, h = box.width(), box.height()
        painter.drawPolyline([
            QPointF(left + w * 0.24, top + h * 0.52),
            QPointF(left + w * 0.43, top + h * 0.72),
            QPointF(left + w * 0.77, top + h * 0.30),
        ])


_NO_DEFAULT = object()


class ControlWidget(QWidget):
    """Base for every control shape.

    Subclasses build their editor in `_build()` and implement `_apply` /
    `_read`. The base owns the caption, the stylesheet, and the re-entrancy
    guard that stops a params-driven refresh from looking like a user edit —
    which would otherwise loop, because committing re-runs the node and the
    run pushes the value straight back down here.
    """

    # the node's new "value" param — a JSON-safe scalar
    value_committed = Signal(object)
    # the ✓ and ↺ on the caption row: the host decides what they mean
    # (ui.control_binding), the widget only says they were pressed
    apply_requested = Signal()
    reset_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._syncing = False
        self._params: dict = {}
        self._upstream: dict = {}
        # what Reset puts back; the host sets it from the node's spec. A
        # widget with no node behind it (a test) never offers a reset.
        self.value_default = _NO_DEFAULT
        self.setObjectName("control_root")
        self._accent = QColor(CHECK_ON)
        self.setStyleSheet(_stylesheet(self._accent))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(2)
        # The caption row carries the Apply/Reset buttons too, so a held
        # control costs no height: the card sizes every script declares
        # were chosen before there were any buttons to fit.
        self._caption_row = QWidget()
        self._caption_row.setObjectName("caption_row")
        row = QHBoxLayout(self._caption_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self._caption = QLabel("")
        self._caption.setObjectName("caption")
        self._caption.setWordWrap(True)
        self._caption.setTextFormat(Qt.RichText)
        row.addWidget(self._caption, 1)
        # the author's explanation, for whoever uses the dashboard: one
        # glyph that says "there is more to know", the words on hover
        self._help = QLabel("ⓘ")
        self._help.setObjectName("control_help")
        self._help.hide()
        row.addWidget(self._help)
        self._pending = QLabel("\u25cf")
        self._pending.setObjectName("control_pending")
        self._pending.setToolTip("Changed — not applied to the flow yet")
        row.addWidget(self._pending)
        self._reset_button = QToolButton()
        self._reset_button.setObjectName("control_reset")
        self._reset_button.setText("\u21ba")
        self._reset_button.setToolTip("Reset to the default value")
        self._reset_button.setFocusPolicy(Qt.NoFocus)
        self._reset_button.clicked.connect(self.reset_requested)
        row.addWidget(self._reset_button)
        self._apply_button = QToolButton()
        self._apply_button.setObjectName("control_apply")
        self._apply_button.setText("\u2713 Apply")
        self._apply_button.setToolTip("Send this change on to the flow")
        self._apply_button.setFocusPolicy(Qt.NoFocus)
        self._apply_button.clicked.connect(self.apply_requested)
        row.addWidget(self._apply_button)
        self._pending.hide()
        self._reset_button.hide()
        self._apply_button.hide()
        self._caption_row.hide()
        layout.addWidget(self._caption_row)
        self._layout = layout
        self._build()
        # the trailing stretch pins a short control to the top of its card.
        # A shape that wants to fill the card (multiline text) zeroes it.
        self._tail_stretch = layout.addStretch(1)

    # ---------------------------------------------------------- for subclasses

    def _build(self) -> None:
        raise NotImplementedError

    def _apply(self, params: dict) -> None:
        """Push params onto the editor. Never emits — the guard is held."""
        raise NotImplementedError

    def _read(self):
        """The editor's current value, as it should be stored."""
        raise NotImplementedError

    def _commit(self, *_args) -> None:
        """Editor changed by the user: report it, unless we're the ones who
        just moved it."""
        if not self._syncing:
            self.value_committed.emit(self._read())

    # ---------------------------------------------------------------- hosting

    def sync(self, params: dict) -> None:
        """Re-read everything from the node's params: the value, the caption
        and the shape's own settings (range, options, ...). Called on build,
        on undo/redo, and whenever the properties panel edits the node."""
        from flograph.core import control_apply as ca

        self._params = dict(params or {})
        # the card draws a held change, not the applied value: what you set
        # is what you see, and the pending dot says the flow has not got it
        shown = ca.shown_params(self._params)
        self._syncing = True
        try:
            accent = accent_of(self._params)
            if accent != self._accent:
                self._accent = accent
                self.setStyleSheet(_stylesheet(accent))
            self._sync_caption()
            self._apply(shown)
            self._sync_buttons(shown)
            self.refresh_validity()
        finally:
            self._syncing = False

    def _sync_caption(self) -> None:
        import html

        caption = str(self._params.get("caption", "") or "").strip()
        required = bool(self._params.get("required"))
        text = html.escape(caption)
        if required:
            # the asterisk is how every form says it, so say it that way
            text += f' <span style="color:{INVALID.name()}">*</span>'
        self._caption.setText(text)
        self._caption.setVisible(bool(caption) or required)
        help_text = str(self._params.get("help", "") or "").strip()
        self._help.setVisible(bool(help_text))
        self._help.setToolTip(help_text)
        self._caption.setToolTip(help_text)

    # ----------------------------------------------------------- validity

    def _primary(self) -> Optional[QWidget]:
        """The editor an invalid value is marked on; None for a shape that
        can never hold one."""
        return None

    def problem(self) -> Optional[str]:
        """Why the value on the control would be refused, or None. The base
        knows "required"; a shape adds its own (Text's pattern)."""
        from flograph.core import control_apply as ca

        if (self._params.get("required")
                and ca.is_blank(self._read())):
            return "Required — fill this in"
        return None

    def refresh_validity(self) -> None:
        """Outline the editor red, and say why on hover, when the value
        showing would be refused — before anyone runs anything."""
        editor = self._primary()
        if editor is None:
            return
        problem = self.problem()
        bad = problem is not None
        if bool(editor.property("invalid")) != bad:
            editor.setProperty("invalid", bad)
            # a dynamic-property selector only re-applies on a re-polish
            editor.style().unpolish(editor)
            editor.style().polish(editor)
        editor.setToolTip(problem or "")

    def _sync_buttons(self, shown: dict) -> None:
        from flograph.core import control_apply as ca

        mode = self._params.get("apply")
        pending = bool(ca.draft_text(self._params))
        self._pending.setVisible(pending)
        # "wait" leaves applying to a page's Apply button, so the field
        # stays a field; "button" puts the ✓ on the control itself
        self._apply_button.setVisible(pending and mode == ca.BUTTON)
        self._reset_button.setVisible(
            bool(self._params.get("show_reset"))
            and self.value_default is not _NO_DEFAULT
            and shown.get("value") != self.value_default)
        self._caption_row.setVisible(
            not self._caption.isHidden()
            or not self._pending.isHidden()
            or not self._apply_button.isHidden()
            or not self._reset_button.isHidden())

    def pending(self) -> bool:
        """Is a change waiting for Apply? (What the dot is showing.)"""
        return not self._pending.isHidden()

    def set_upstream(self, values: dict) -> None:
        """Settings a run supplied through this control's own input ports,
        keyed by port name. A port that isn't connected simply isn't in the
        dict, and the typed-in param stands. One mechanism for every shape,
        so a control that grows a new wired setting needs no host change."""
        self._upstream = dict(values or {})
        self.sync(self._params)

    def _wired(self, port: str, fallback):
        """What the wire says for `port`, or the param's own value."""
        value = self._upstream.get(port)
        return fallback if value is None else value

    def focus_editor(self) -> None:
        """Put the keyboard in the editor. Hosts call this when a control
        card is clicked, so a tile is usable in one click, not two."""


class SliderControl(ControlWidget):
    """A value along a track: the ends of the range labelled either side of
    it, and the current value riding under the handle.

    Putting the bounds where the track actually starts and stops means a
    reader can see the scale without opening the properties panel — which
    matters when the bounds are wired from data and nobody typed them. The
    value tracks the handle rather than sitting in a fixed corner, so it
    reads as "this position means 35" instead of as a separate number.

    Qt sliders are integer-only, so a float slider works in `step`-sized
    ticks internally and converts at the boundary; that also makes "step"
    mean the same thing for both, rather than being ignored for floats.
    """

    def _build(self) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        self._low_label = QLabel("")
        self._low_label.setObjectName("bound")
        self._high_label = QLabel("")
        self._high_label.setObjectName("bound")
        self._high_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setObjectName("control_slider")
        self._slider.valueChanged.connect(self._on_moved)
        self._slider.sliderReleased.connect(self._commit)
        row.addWidget(self._low_label)
        row.addWidget(self._slider, 1)
        row.addWidget(self._high_label)
        self._layout.addLayout(row)

        # The readout is positioned by hand, so it needs a strip of its own
        # rather than a layout slot — a layout would centre it on the card
        # instead of on the handle.
        self._readout_row = QWidget()
        self._readout_row.setObjectName("readout_row")
        self._readout_row.setFixedHeight(15)
        self._readout = QLabel("0", self._readout_row)
        self._readout.setObjectName("control_readout")
        self._layout.addWidget(self._readout_row)

        self._minimum, self._step, self._decimals = 0.0, 1.0, 0

    @staticmethod
    def _readout_left(centre: float, label_width: int, row_width: int) -> int:
        """Where the value label goes: centred on `centre`, but never past
        either end of the strip.

        The bound labels either side already inset the track far enough that
        a centred readout doesn't currently reach an edge — this keeps that
        from becoming a silent assumption about the layout.
        """
        return int(max(0, min(row_width - label_width,
                              centre - label_width / 2)))

    def _place_readout(self) -> None:
        """Centre the value under the slider handle.

        The handle rect comes from the style rather than from arithmetic on
        the value: the groove is inset by the handle's own width, so a
        computed position drifts further from the handle the nearer either
        end you get.
        """
        option = QStyleOptionSlider()
        self._slider.initStyleOption(option)
        handle = self._slider.style().subControlRect(
            QStyle.CC_Slider, option, QStyle.SC_SliderHandle, self._slider)
        self._readout.adjustSize()
        # both are children of this widget, so their x offsets are comparable
        centre = (self._slider.x() + handle.center().x()
                  - self._readout_row.x())
        self._readout.move(
            self._readout_left(centre, self._readout.width(),
                               self._readout_row.width()), 0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_readout()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._place_readout()

    def _apply(self, params: dict) -> None:
        from flograph.core.controls import as_number, clamp

        self._minimum = as_number(
            self._wired("minimum", params.get("minimum", 0)), 0.0)
        maximum = as_number(
            self._wired("maximum", params.get("maximum", 100)), 100.0)
        self._step = float(params.get("step", 1) or 1) or 1.0
        self._decimals = max(0, int(params.get("decimals", 0) or 0))
        if maximum < self._minimum:
            maximum = self._minimum
        self._slider.setMinimum(0)
        self._slider.setMaximum(max(0, round((maximum - self._minimum)
                                             / self._step)))
        self._slider.setSingleStep(1)
        self._slider.setPageStep(max(1, self._slider.maximum() // 10))
        value = clamp(as_number(params.get("value"), self._minimum),
                      self._minimum, maximum)
        if not self._slider.isSliderDown():
            # mid-drag the handle belongs to the user's finger: a run
            # finishing elsewhere must not snap it back to the stored value
            self._slider.setValue(
                max(0, min(self._slider.maximum(),
                           round((value - self._minimum) / self._step))))
        self._low_label.setText(self._format(self._minimum))
        self._high_label.setText(self._format(maximum))
        self._readout.setText(self._format(self._read()))
        self._place_readout()

    def _format(self, value) -> str:
        return f"{value:,.{self._decimals}f}" if self._decimals \
            else f"{int(value):,}"

    def _read(self):
        value = self._minimum + self._slider.value() * self._step
        return round(value, self._decimals) if self._decimals \
            else int(round(value))

    def _on_moved(self, *_args) -> None:
        """Every tick of the handle: show the new number, but only report it
        if this isn't a drag.

        A drag fires this once per pixel of travel. Committing there would
        re-run the whole downstream flow — and push an undo step — for every
        one of them, so dragging across a heavy model would queue dozens of
        runs and bury the undo stack. The release commits once, with the
        value the user actually let go on. Discrete changes (arrow keys, the
        wheel, clicking the groove) are not drags and still commit at once,
        because there is no later moment to wait for.
        """
        self._readout.setText(self._format(self._read()))
        self._place_readout()
        if not self._slider.isSliderDown():
            super()._commit()

    def focus_editor(self) -> None:
        self._slider.setFocus()


class RangeSlider(QWidget):
    """Two handles on one track, drawn by hand.

    Qt has no two-handled slider and no way to grow one: QSlider owns a
    single value all the way down into the style. So this is painted
    directly — which is also what lets the span between the handles be
    filled in, and that fill is the whole reason a range control reads at a
    glance instead of as two numbers that happen to be near each other.

    Values are integer step indices, exactly as QSlider works internally,
    and the control converts at the boundary. `isSliderDown` and `released`
    mirror QSlider's names so the "commit once, on release" rule that keeps
    a drag from queueing one run per pixel can be the same rule here.
    """

    moved = Signal()
    released = Signal()

    HANDLE_R = 6.5
    TRACK_H = 4.0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("range_slider")
        self.setMinimumHeight(20)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.StrongFocus)
        self._maximum = 100
        self._low = 0
        self._high = 100
        self._active = 1          # which handle the keyboard drives
        self._dragging = False
        self.accent = QColor(CHECK_ON)   # the span and the focus ring

    # -------------------------------------------------------------- values

    def maximum(self) -> int:
        return self._maximum

    def setMaximum(self, value: int) -> None:
        self._maximum = max(0, int(value))
        self.setValues(self._low, self._high)

    def values(self) -> tuple:
        return self._low, self._high

    def setValues(self, low: int, high: int) -> None:
        low = max(0, min(self._maximum, int(low)))
        high = max(0, min(self._maximum, int(high)))
        if low > high:
            low, high = high, low
        changed = (low, high) != (self._low, self._high)
        self._low, self._high = low, high
        if changed:
            self.update()

    def isSliderDown(self) -> bool:
        return self._dragging

    # ------------------------------------------------------------ geometry

    def _span(self) -> tuple:
        """The x range the handle centres travel between."""
        return self.HANDLE_R, max(self.HANDLE_R + 1,
                                  self.width() - self.HANDLE_R)

    def _x_for(self, step: int) -> float:
        left, right = self._span()
        if self._maximum <= 0:
            return left
        return left + (right - left) * step / self._maximum

    def _step_for(self, x: float) -> int:
        left, right = self._span()
        if right <= left or self._maximum <= 0:
            return 0
        ratio = (x - left) / (right - left)
        return max(0, min(self._maximum, round(ratio * self._maximum)))

    def handle_centres(self) -> tuple:
        return self._x_for(self._low), self._x_for(self._high)

    # ------------------------------------------------------------- drawing

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        left, right = self._span()
        mid = self.height() / 2
        track = QRectF(left, mid - self.TRACK_H / 2,
                       right - left, self.TRACK_H)
        painter.setBrush(theme.NODE_HEADER)
        painter.drawRoundedRect(track, self.TRACK_H / 2, self.TRACK_H / 2)

        low_x, high_x = self.handle_centres()
        painter.setBrush(self.accent)
        painter.drawRoundedRect(
            QRectF(low_x, track.top(), max(0.0, high_x - low_x), track.height()),
            self.TRACK_H / 2, self.TRACK_H / 2)

        for i, x in enumerate((low_x, high_x)):
            # Both handles keep the light fill: half of a handle's travel is
            # over the filled span, and one painted in the span's own colour
            # disappears into it exactly where it is being dragged. Focus is
            # a ring instead — the keyboard has to move a handle the user can
            # see it is about to move.
            focused = self.hasFocus() and i == self._active
            painter.setPen(QPen(self.accent, 2) if focused
                           else QPen(theme.NODE_BORDER, 1))
            painter.setBrush(theme.NODE_TEXT)
            painter.drawEllipse(QPointF(x, mid), self.HANDLE_R, self.HANDLE_R)
        painter.end()

    # --------------------------------------------------------- interaction

    def _nearest(self, x: float) -> int:
        low_x, high_x = self.handle_centres()
        if abs(x - low_x) == abs(x - high_x):
            # tied — which happens whenever the handles coincide, and the
            # range can only reopen if the click grabs the one it is
            # dragging away from
            return 0 if x < low_x else 1
        return 0 if abs(x - low_x) < abs(x - high_x) else 1

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        x = event.position().x()
        self._active = self._nearest(x)
        self._dragging = True
        self._drag_to(x)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._drag_to(event.position().x())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging and event.button() == Qt.LeftButton:
            self._dragging = False
            self.released.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _drag_to(self, x: float) -> None:
        step = self._step_for(x)
        low, high = self._low, self._high
        if self._active == 0:
            # Handles push past each other rather than blocking. Blocking
            # means a drag silently stops and the pointer walks away from
            # the handle; swapping keeps the grabbed handle under the
            # finger, which is what every range control does.
            if step > high:
                low, high, self._active = high, step, 1
            else:
                low = step
        else:
            if step < low:
                low, high, self._active = step, low, 0
            else:
                high = step
        before = (self._low, self._high)
        self.setValues(low, high)
        if (self._low, self._high) != before:
            self.moved.emit()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key_Tab, Qt.Key_Backtab):
            super().keyPressEvent(event)
            return
        if key == Qt.Key_Space:
            self._active = 1 - self._active     # swap which handle moves
            self.update()
            event.accept()
            return
        step = 0
        if key in (Qt.Key_Left, Qt.Key_Down):
            step = -1
        elif key in (Qt.Key_Right, Qt.Key_Up):
            step = 1
        elif key == Qt.Key_Home:
            step = -self._maximum
        elif key == Qt.Key_End:
            step = self._maximum
        if not step:
            super().keyPressEvent(event)
            return
        low, high = self._low, self._high
        if self._active == 0:
            low = min(high, low + step)
        else:
            high = max(low, high + step)
        before = (self._low, self._high)
        self.setValues(low, high)
        if (self._low, self._high) != before:
            # `moved` alone: the control commits on a move that is not part
            # of a drag, so emitting `released` here as well would push two
            # undo steps and queue two runs for one keystroke.
            self.moved.emit()
        event.accept()


class RangeControl(ControlWidget):
    """A low/high pair on one track — "everything between these two".

    Shares the slider's conventions deliberately: the bounds sit either side
    of the track, the values ride under the handles, and a drag commits once
    on release rather than once per pixel. The pair is stored as JSON in the
    single `value` param the host writes (see core.controls.range_values),
    so nothing about the hosting contract had to change to fit a control
    that means two numbers.
    """

    def _build(self) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        self._low_label = QLabel("")
        self._low_label.setObjectName("bound")
        self._high_label = QLabel("")
        self._high_label.setObjectName("bound")
        self._high_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._slider = RangeSlider()
        self._slider.moved.connect(self._on_moved)
        self._slider.released.connect(self._commit)
        row.addWidget(self._low_label)
        row.addWidget(self._slider, 1)
        row.addWidget(self._high_label)
        self._layout.addLayout(row)

        self._readout_row = QWidget()
        self._readout_row.setObjectName("readout_row")
        self._readout_row.setFixedHeight(15)
        self._readout = QLabel("", self._readout_row)
        self._readout.setObjectName("control_readout")
        self._layout.addWidget(self._readout_row)

        self._minimum, self._step, self._decimals = 0.0, 1.0, 0

    def _place_readout(self) -> None:
        """Centred between the two handles — on the span it describes rather
        than on the card, so it stays attached to what it is reporting."""
        low_x, high_x = self._slider.handle_centres()
        centre = (self._slider.x() + (low_x + high_x) / 2
                  - self._readout_row.x())
        self._readout.adjustSize()
        self._readout.move(
            SliderControl._readout_left(centre, self._readout.width(),
                                        self._readout_row.width()), 0)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_readout()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._place_readout()

    def _apply(self, params: dict) -> None:
        from flograph.core.controls import as_number, clamp, range_values

        self._minimum = as_number(
            self._wired("minimum", params.get("minimum", 0)), 0.0)
        maximum = as_number(
            self._wired("maximum", params.get("maximum", 100)), 100.0)
        self._step = float(params.get("step", 1) or 1) or 1.0
        self._decimals = max(0, int(params.get("decimals", 0) or 0))
        if maximum < self._minimum:
            maximum = self._minimum
        if self._slider.accent != self._accent:
            self._slider.accent = QColor(self._accent)
            self._slider.update()
        self._slider.setMaximum(
            max(0, round((maximum - self._minimum) / self._step)))

        low, high = range_values(params.get("value"), self._minimum, maximum)
        low = clamp(low, self._minimum, maximum)
        high = clamp(high, self._minimum, maximum)
        if not self._slider.isSliderDown():
            self._slider.setValues(self._to_step(low), self._to_step(high))
        self._low_label.setText(self._format(self._minimum))
        self._high_label.setText(self._format(maximum))
        self._update_readout()

    def _to_step(self, value: float) -> int:
        return max(0, min(self._slider.maximum(),
                          round((value - self._minimum) / self._step)))

    def _from_step(self, step: int) -> float:
        value = self._minimum + step * self._step
        return round(value, self._decimals) if self._decimals \
            else int(round(value))

    def _format(self, value) -> str:
        return f"{value:,.{self._decimals}f}" if self._decimals \
            else f"{int(value):,}"

    def _update_readout(self) -> None:
        low, high = self._read_pair()
        # an en dash, not a hyphen: these are numbers that may be negative
        self._readout.setText(f"{self._format(low)} – {self._format(high)}")
        self._place_readout()

    def _read_pair(self) -> tuple:
        low, high = self._slider.values()
        return self._from_step(low), self._from_step(high)

    def _read(self):
        import json
        return json.dumps(list(self._read_pair()))

    def _on_moved(self, *_args) -> None:
        self._update_readout()
        if not self._slider.isSliderDown():
            super()._commit()

    def focus_editor(self) -> None:
        self._slider.setFocus()


class NumberControl(ControlWidget):
    """A spin box. Integer when `decimals` is 0, which is the default."""

    def _build(self) -> None:
        self._spin = QDoubleSpinBox()
        self._spin.setObjectName("control_number")
        self._spin.setKeyboardTracking(False)  # commit on Enter/focus-out only
        self._spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._spin.valueChanged.connect(self._commit)
        self._layout.addWidget(self._spin)

    def _apply(self, params: dict) -> None:
        from flograph.core.controls import as_number, clamp

        decimals = max(0, int(params.get("decimals", 0) or 0))
        self._spin.setDecimals(decimals)
        low = as_number(self._wired("minimum", params.get("minimum", 0)), 0.0)
        high = as_number(
            self._wired("maximum", params.get("maximum", 100)), 100.0)
        if high < low:
            high = low
        self._spin.setMinimum(low)
        self._spin.setMaximum(high)
        self._spin.setSingleStep(float(params.get("step", 1) or 1) or 1.0)
        self._spin.setPrefix(str(params.get("prefix", "") or ""))
        self._spin.setSuffix(str(params.get("suffix", "") or ""))
        self._spin.setGroupSeparatorShown(bool(params.get("thousands", False)))
        self._spin.setValue(
            clamp(as_number(params.get("value"), low), low, high))

    def _read(self):
        value = self._spin.value()
        return value if self._spin.decimals() else int(round(value))

    def _primary(self):
        return self._spin

    def focus_editor(self) -> None:
        self._spin.setFocus()
        self._spin.selectAll()


class TextControl(ControlWidget):
    """Free text. `multiline` swaps the line edit for a text box."""

    #: how long typing must pause before "Search as you type" commits —
    #: long enough that a word is one run, short enough to feel live
    LIVE_TYPING_MS = 400

    def _build(self) -> None:
        from PySide6.QtCore import QTimer

        self._edit = QLineEdit()
        self._edit.setObjectName("control_text")
        self._edit.setMaxLength(UNCAPPED_TEXT)  # a Text node may carry base64
        # an ✕ inside the box: emptying a search is the commonest edit there
        # is, and select-all-delete is three gestures for it
        self._edit.setClearButtonEnabled(True)
        # editingFinished, not textEdited: one undo step per edit, not one
        # per keystroke, and no re-run of the whole flow per character
        self._edit.editingFinished.connect(self._commit)
        self._edit.textChanged.connect(lambda *_: self.refresh_validity())
        self._edit.textEdited.connect(self._typed)
        self._box = QPlainTextEdit()
        self._box.setObjectName("control_text_multiline")
        self._box.hide()
        self._box.focusOutEvent = self._box_focus_out
        self._box.textChanged.connect(self.refresh_validity)
        self._layout.addWidget(self._edit)
        self._layout.addWidget(self._box, 1)
        self._live = False
        self._pause = QTimer(self)
        self._pause.setSingleShot(True)
        self._pause.setInterval(self.LIVE_TYPING_MS)
        self._pause.timeout.connect(self._commit)

    def _typed(self, *_args) -> None:
        """A keystroke in the one-line box. Only "Search as you type" acts
        on it — and then only once typing pauses, so a word is one run."""
        if self._live:
            self._pause.start()

    def _box_focus_out(self, event) -> None:
        QPlainTextEdit.focusOutEvent(self._box, event)
        self._commit()

    def _set_tail_stretch(self, stretch: int) -> None:
        """How much of the card's free space the base class's trailing
        stretch takes. Multiline fills the whole card; single-line keeps the
        edit pinned to the top with the slack below it. The tail is always
        the last item in the layout — the base adds it after _build()."""
        self._layout.setStretch(self._layout.count() - 1, stretch)

    def _apply(self, params: dict) -> None:
        multiline = bool(params.get("multiline", False))
        self._edit.setVisible(not multiline)
        self._box.setVisible(multiline)
        self._set_tail_stretch(0 if multiline else 1)
        self._live = bool(params.get("live_typing", False)) and not multiline
        self._edit.setEchoMode(QLineEdit.Password if params.get("mask")
                               else QLineEdit.Normal)
        placeholder = str(
            self._wired("placeholder", params.get("placeholder", "")) or "")
        self._edit.setPlaceholderText(placeholder)
        self._box.setPlaceholderText(placeholder)
        text = str(params.get("value", "") or "")
        if self._edit.text() != text:
            self._edit.setText(text)
        if self._box.toPlainText() != text:
            self._box.setPlainText(text)

    def _read(self):
        # isHidden(), not isVisible(): a control inside a tile proxy that
        # hasn't been shown yet is not "visible", and asking the wrong
        # editor there would report a stale value
        return self._edit.text() if self._box.isHidden() \
            else self._box.toPlainText()

    def _primary(self):
        return self._edit if self._box.isHidden() else self._box

    def problem(self):
        from flograph.core.controls import pattern_problem

        return super().problem() or pattern_problem(
            self._read(), self._params.get("pattern", ""),
            self._params.get("pattern_message", ""))

    def focus_editor(self) -> None:
        target = self._edit if self._box.isHidden() else self._box
        target.setFocus()


class DateControl(ControlWidget):
    """A calendar picker storing an ISO "YYYY-MM-DD" string."""

    def _build(self) -> None:
        self._edit = QDateEdit()
        self._edit.setObjectName("control_date")
        self._edit.setCalendarPopup(True)
        self._edit.setDisplayFormat(ISO_FORMAT)
        self._edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._edit.dateChanged.connect(self._commit)
        # "No date" is Qt's special value: the picker's minimum, shown as
        # words. The ✕ sets it; only offered when Allow no date is ticked.
        self._clear = QToolButton()
        self._clear.setObjectName("control_reset")
        self._clear.setText("✕")
        self._clear.setToolTip("No date")
        self._clear.setFocusPolicy(Qt.NoFocus)
        self._clear.clicked.connect(self._to_blank)
        self._clear.hide()
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(self._edit, 1)
        row.addWidget(self._clear)
        self._layout.addLayout(row)
        self._blank_ok = False

    #: the earliest date Qt's calendar can show; "No date" sits on it when
    #: no lower bound is set
    _FIRST = QDate(1752, 9, 14)

    def _apply(self, params: dict) -> None:
        from flograph.core.controls import date_value

        low = iso_to_qdate(self._wired("minimum", params.get("minimum")))
        high = iso_to_qdate(self._wired("maximum", params.get("maximum")))
        self._blank_ok = bool(params.get("allow_blank", False))
        # set wide first: a new minimum above the old maximum is rejected
        self._edit.setDateRange(self._FIRST, QDate(7999, 12, 31))
        floor = low
        if self._blank_ok:
            # the blank is the day before the earliest real one, so it can
            # never be confused with a date someone could pick
            floor = low.addDays(-1) if low is not None else self._FIRST
            self._edit.setSpecialValueText("No date")
        else:
            self._edit.setSpecialValueText("")
        if floor is not None:
            self._edit.setMinimumDate(floor)
        if high is not None:
            self._edit.setMaximumDate(high)
        # what the flow will get: a picked day, else what the preset means
        shown = date_value(params.get("value"), params.get("preset", "fixed"),
                           params.get("days", 0), self._blank_ok)
        stored = iso_to_qdate(shown)
        if stored is None and self._blank_ok:
            self._edit.setDate(self._edit.minimumDate())
        else:
            self._edit.setDate(stored if stored is not None
                               else QDate.currentDate())
        self._clear.setVisible(self._blank_ok and not self._is_blank())

    def _is_blank(self) -> bool:
        return (self._blank_ok
                and self._edit.date() == self._edit.minimumDate())

    def _to_blank(self) -> None:
        self._edit.setDate(self._edit.minimumDate())

    def _read(self):
        return "" if self._is_blank() else qdate_to_iso(self._edit.date())

    def _primary(self):
        return self._edit

    def focus_editor(self) -> None:
        self._edit.setFocus()


class ToggleControl(ControlWidget):
    """A single tick box reporting True/False."""

    def _build(self) -> None:
        from .switch import Switch

        self._check = _TickBox("")
        self._check.setObjectName("control_toggle")
        self._check.toggled.connect(self._commit)
        self._layout.addWidget(self._check)
        # the same value, drawn as an on/off switch — for a setting that
        # reads as "on" rather than as an item ticked off a list
        # The label is its own QLabel: the Switch paints its text with the
        # chrome's metrics, which on a card's stylesheet font land on top of
        # the track. Clicking the label still flips it, as a tick box's does.
        self._switch_row = QWidget()
        self._switch_row.setObjectName("readout_row")
        row = QHBoxLayout(self._switch_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self._switch = Switch("")
        self._switch.setObjectName("control_switch")
        self._switch.toggled.connect(self._commit)
        self._switch_label = QLabel("")
        self._switch_label.mousePressEvent = \
            lambda _e: self._switch.click()
        row.addWidget(self._switch)
        row.addWidget(self._switch_label, 1)
        self._switch_row.hide()
        self._layout.addWidget(self._switch_row)

    def _shown(self):
        return self._check if self._switch_row.isHidden() else self._switch

    def _apply(self, params: dict) -> None:
        switch = params.get("style") == "switch"
        self._check.setVisible(not switch)
        self._switch_row.setVisible(switch)
        text = str(self._wired("text", params.get("text", "")) or "")
        checked = bool(params.get("value", False))
        self._check.setText(text)
        self._switch_label.setText(text)
        for box in (self._check, self._switch):
            box.setChecked(checked)

    def _read(self):
        return self._shown().isChecked()

    def focus_editor(self) -> None:
        self._shown().setFocus()


class ChoiceControl(ControlWidget):
    """A dropdown. Options come from an upstream run when one is wired in,
    otherwise from the `items` param — so a choice can be a fixed list the
    dashboard's author typed, or the live values of a column."""

    def _build(self) -> None:
        # a card-aware combo: a control sits on a canvas card or a dashboard
        # tile, where a plain one's list is drawn under the card in front of
        # it and placed by coordinates that mean nothing (canvas.popup_lift)
        from .canvas.popup_lift import CardComboBox
        self._combo = CardComboBox()
        self._combo.setObjectName("control_choice")
        self._combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._combo.activated.connect(self._commit)  # user choice only
        self._layout.addWidget(self._combo)
        # "buttons" and "radio": every option on show at once. Rebuilt only
        # when the options change, so a pick doesn't recreate what was
        # clicked while its own signal is still running.
        from PySide6.QtWidgets import QButtonGroup
        self._buttons = QWidget()
        self._buttons.setObjectName("choice_buttons")
        self._buttons.hide()
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.buttonClicked.connect(self._commit)
        self._layout.addWidget(self._buttons)
        self._built: tuple = ()

    def _entries(self, params: dict) -> list[tuple[str, str]]:
        """(label, value) for every option, in order: "(All)" first when it
        is on, then the options, then a stored pick no longer offered."""
        from flograph.core.controls import ALL_LABEL

        options = self._upstream.get("options")
        if options is None:
            options = option_list(params.get("items"))
        entries = [(ALL_LABEL, "")] if params.get("all_option") else []
        entries += [(str(o), str(o)) for o in options]
        current = str(params.get("value", "") or "")
        if current and current not in [v for _l, v in entries]:
            # the stored pick is no longer offered (upstream changed, or the
            # author edited the list) — keep it visible rather than silently
            # switching the dashboard to a different value
            entries.append((f"{current}  (not in list)", current))
        return entries

    def _apply(self, params: dict) -> None:
        style = params.get("style", "dropdown")
        entries = self._entries(params)
        current = str(params.get("value", "") or "")
        values = [v for _l, v in entries]
        index = values.index(current) if current in values else 0
        dropdown = style not in ("buttons", "radio")
        self._combo.setVisible(dropdown)
        self._buttons.setVisible(not dropdown)
        if dropdown:
            self._combo.clear()
            for label, value in entries:
                self._combo.addItem(label, value)
            self._combo.setCurrentIndex(index if entries else -1)
            return
        if self._built != (style, tuple(entries)):
            self._rebuild_buttons(style, entries)
        buttons = self._group.buttons()
        if buttons:
            buttons[min(index, len(buttons) - 1)].setChecked(True)

    def _rebuild_buttons(self, style: str, entries) -> None:
        from PySide6.QtWidgets import QRadioButton

        for button in self._group.buttons():
            self._group.removeButton(button)
            button.deleteLater()
        old = self._buttons.layout()
        if old is not None:
            QWidget().setLayout(old)    # the only way to drop a layout
        layout = QHBoxLayout(self._buttons) if style == "buttons" \
            else QVBoxLayout(self._buttons)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3 if style == "buttons" else 2)
        for i, (label, value) in enumerate(entries):
            if style == "buttons":
                button = QToolButton()
                button.setObjectName("choice_button")
                button.setCheckable(True)
                button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            else:
                button = QRadioButton()
            button.setText(label)
            button.setProperty("choice_value", value)
            self._group.addButton(button, i)
            layout.addWidget(button)
        if style == "radio":
            layout.addStretch(1)
        self._built = (style, tuple(entries))

    def _read(self):
        if not self._buttons.isHidden():
            button = self._group.checkedButton()
            return str(button.property("choice_value")) if button else ""
        stored = self._combo.currentData(Qt.UserRole)
        return stored if stored is not None else self._combo.currentText()

    def focus_editor(self) -> None:
        if self._buttons.isHidden():
            self._combo.setFocus()
        elif self._group.checkedButton() is not None:
            self._group.checkedButton().setFocus()


_CONTROLS = {
    "slider": SliderControl,
    "range": RangeControl,
    "number": NumberControl,
    "text": TextControl,
    "date": DateControl,
    "toggle": ToggleControl,
    "choice": ChoiceControl,
}


def build_control(kind: str, parent=None) -> Optional[ControlWidget]:
    """The widget for a control kind, or None for one this build doesn't
    know — a project saved by a newer flograph must still open."""
    factory = _CONTROLS.get(kind)
    return factory(parent) if factory is not None else None


def host_control(node, parent=None) -> Optional[ControlWidget]:
    """A node's control widget, ready to place: built for its shape, told
    its default (for Reset) and synced to its params. The canvas card and
    the dashboard tile both build theirs here, then wire it with
    `connect_control`, so the two can't differ in what a press does."""
    widget = build_control(node.spec.control or "", parent)
    if widget is None:
        return None
    from flograph.core.control_apply import default_value
    widget.value_default = default_value(node)
    widget.sync(node.params)
    return widget


def connect_control(widget: ControlWidget, graph_of, stack_of, node_id_of,
                    changed) -> None:
    """Wire a hosted control's three signals through ui.control_binding.

    The host passes callables rather than objects because a card or tile
    can outlive the scene it was built in (a page torn down mid-run) —
    each press asks for the graph and stack as they are now, and does
    nothing when either has gone. `changed(node_id)` is the host's cue that
    the flow's value moved and a re-run is wanted.
    """
    from . import control_binding as cb

    def run(op, *args) -> None:
        graph, stack, node_id = graph_of(), stack_of(), node_id_of()
        if graph is None or stack is None or node_id is None:
            return
        if op(graph, stack, node_id, *args):
            changed(node_id)

    widget.value_committed.connect(lambda value: run(cb.commit_value, value))
    widget.apply_requested.connect(lambda: run(cb.apply))
    widget.reset_requested.connect(lambda: run(cb.reset))
