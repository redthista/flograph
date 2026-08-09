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
    QStyleOptionButton, QStyleOptionSlider, QVBoxLayout, QWidget,
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


def _stylesheet() -> str:
    """Controls sit on a node card, not on the desktop, so their chrome has
    to match the card rather than the OS default."""
    return (
        # by object name, not a bare QWidget rule: that would cascade into
        # every child and repaint the spin box and combo popup too
        f"QWidget#control_root {{ background: {theme.NODE_BODY.name()}; }}"
        f"QLabel {{ color: {theme.NODE_TEXT.name()}; font-size: 9pt;"
        f" background: transparent; }}"
        f"QLabel#caption {{ color: {theme.NODE_SUBTEXT.name()};"
        f" font-size: 8pt; }}"
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
        f"QCheckBox {{ color: {theme.NODE_TEXT.name()}; font-size: 9pt;"
        f" background: transparent; spacing: 6px; }}"
        # The box is drawn explicitly. Left to the platform style on a dark
        # card it comes out as a bare tick floating in space when checked and
        # nothing at all when unchecked — an empty box is what tells someone
        # there is something here to click.
        f"QCheckBox::indicator {{ width: 14px; height: 14px;"
        f" border-radius: 3px; border: 1px solid {theme.NODE_SUBTEXT.name()};"
        f" background: {theme.NODE_HEADER.name()}; }}"
        f"QCheckBox::indicator:hover {{ border-color: {CHECK_ON.name()}; }}"
        f"QCheckBox::indicator:checked {{ background: {CHECK_ON.name()};"
        f" border-color: {CHECK_ON.name()}; }}"
        f"QCheckBox::indicator:disabled {{ border-color:"
        f" {theme.NODE_BORDER.name()}; }}"
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

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._syncing = False
        self._params: dict = {}
        self._upstream: dict = {}
        self.setObjectName("control_root")
        self.setStyleSheet(_stylesheet())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(2)
        self._caption = QLabel("")
        self._caption.setObjectName("caption")
        self._caption.setWordWrap(True)
        self._caption.hide()
        layout.addWidget(self._caption)
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
        self._params = dict(params or {})
        self._syncing = True
        try:
            caption = str(self._params.get("caption", "") or "").strip()
            self._caption.setText(caption)
            self._caption.setVisible(bool(caption))
            self._apply(self._params)
        finally:
            self._syncing = False

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
        painter.setBrush(CHECK_ON)
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
            painter.setPen(QPen(CHECK_ON, 2) if focused
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
        self._spin.setValue(
            clamp(as_number(params.get("value"), low), low, high))

    def _read(self):
        value = self._spin.value()
        return value if self._spin.decimals() else int(round(value))

    def focus_editor(self) -> None:
        self._spin.setFocus()
        self._spin.selectAll()


class TextControl(ControlWidget):
    """Free text. `multiline` swaps the line edit for a text box."""

    def _build(self) -> None:
        self._edit = QLineEdit()
        self._edit.setObjectName("control_text")
        self._edit.setMaxLength(UNCAPPED_TEXT)  # a Text node may carry base64
        # editingFinished, not textEdited: one undo step per edit, not one
        # per keystroke, and no re-run of the whole flow per character
        self._edit.editingFinished.connect(self._commit)
        self._box = QPlainTextEdit()
        self._box.setObjectName("control_text_multiline")
        self._box.hide()
        self._box.focusOutEvent = self._box_focus_out
        self._layout.addWidget(self._edit)
        self._layout.addWidget(self._box, 1)

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
        self._layout.addWidget(self._edit)

    def _apply(self, params: dict) -> None:
        low = iso_to_qdate(self._wired("minimum", params.get("minimum")))
        high = iso_to_qdate(self._wired("maximum", params.get("maximum")))
        # set wide first: a new minimum above the old maximum is rejected
        self._edit.setDateRange(QDate(1752, 9, 14), QDate(7999, 12, 31))
        if low is not None:
            self._edit.setMinimumDate(low)
        if high is not None:
            self._edit.setMaximumDate(high)
        stored = iso_to_qdate(params.get("value"))
        self._edit.setDate(stored if stored is not None
                           else QDate.currentDate())

    def _read(self):
        return qdate_to_iso(self._edit.date())

    def focus_editor(self) -> None:
        self._edit.setFocus()


class ToggleControl(ControlWidget):
    """A single tick box reporting True/False."""

    def _build(self) -> None:
        self._check = _TickBox("")
        self._check.setObjectName("control_toggle")
        self._check.toggled.connect(self._commit)
        self._layout.addWidget(self._check)

    def _apply(self, params: dict) -> None:
        self._check.setText(
            str(self._wired("text", params.get("text", "")) or ""))
        self._check.setChecked(bool(params.get("value", False)))

    def _read(self):
        return self._check.isChecked()

    def focus_editor(self) -> None:
        self._check.setFocus()


class ChoiceControl(ControlWidget):
    """A dropdown. Options come from an upstream run when one is wired in,
    otherwise from the `items` param — so a choice can be a fixed list the
    dashboard's author typed, or the live values of a column."""

    def _build(self) -> None:
        self._combo = QComboBox()
        self._combo.setObjectName("control_choice")
        self._combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._combo.activated.connect(self._commit)  # user choice only
        self._layout.addWidget(self._combo)

    def _apply(self, params: dict) -> None:
        options = self._upstream.get("options")
        if options is None:
            options = option_list(params.get("items"))
        current = str(params.get("value", "") or "")
        self._combo.clear()
        self._combo.addItems(options)
        index = self._combo.findText(current)
        if index < 0 and current:
            # the stored pick is no longer offered (upstream changed, or the
            # author edited the list) — keep it visible rather than silently
            # switching the dashboard to a different value
            self._combo.addItem(f"{current}  (not in list)")
            self._combo.setItemData(self._combo.count() - 1, current,
                                    Qt.UserRole)
            index = self._combo.count() - 1
        self._combo.setCurrentIndex(max(0, index))

    def _read(self):
        stored = self._combo.currentData(Qt.UserRole)
        return stored if stored is not None else self._combo.currentText()

    def focus_editor(self) -> None:
        self._combo.setFocus()


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
