"""A sliding on/off switch — the pill with a knob that moves.

Drawn, never a stylesheet trick or an image: the chrome's rule (see the
flograph-chrome design notes) is that controls paint themselves from a
few QPainterPath lines, so they are crisp at any scale and look the same
on every platform style. A checkable QToolButton had the style's own
look — on KDE it read "Live | Live", a pressed and an unpressed label
side by side — and said nothing at a glance about which way it was set.

It speaks the canvas status language: on is the green of run / go, the
colour a running node already wears; off is a quiet track in the theme's
own colours, so it suits the light chrome as well as the dark. The knob
slides rather than jumps, over about the time a click takes.

A QAbstractButton underneath, checkable, so `toggled`, `setChecked`,
`isChecked`, keyboard focus and Space all behave as any button's do.
"""
from __future__ import annotations

from PySide6.QtCore import (Property, QEasingCurve, QPointF, QRectF, QSize,
                            Qt, QVariantAnimation)
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QAbstractButton

#: run / go — the canvas green (toolbar.RUN)
ON = QColor("#22c55e")
#: the knob: near-white on both themes, a light that sits on either track
KNOB = QColor("#f4f5f7")

TRACK_W, TRACK_H = 30, 16
GAP = 6                 # between the track and its label
SLIDE_MS = 150


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(round(a.red() + (b.red() - a.red()) * t),
                  round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


class Switch(QAbstractButton):
    """A labelled sliding switch. `Switch("Live")`."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAttribute(Qt.WA_Hover, True)
        # 0 = off, 1 = on; animated between — where the knob is, and how far
        # the track has turned green
        self._pos = 0.0
        self._slide = QVariantAnimation(self)
        self._slide.setDuration(SLIDE_MS)
        self._slide.setEasingCurve(QEasingCurve.OutCubic)
        self._slide.valueChanged.connect(self._moved)
        self.toggled.connect(self._toggled_to)

    # ------------------------------------------------------------ the knob

    def _moved(self, value) -> None:
        self._pos = float(value)
        self.update()

    def _toggled_to(self, on: bool) -> None:
        target = 1.0 if on else 0.0
        if not self.isVisible():
            # set before it is shown (a page loading its saved state): no
            # slide nobody could see
            self._slide.stop()
            self._moved(target)
            return
        self._slide.stop()
        self._slide.setStartValue(self._pos)
        self._slide.setEndValue(target)
        self._slide.start()

    def position(self) -> float:
        """Where the knob is, 0 (off) to 1 (on) — for tests."""
        return self._pos

    knob = Property(float, position, _moved)

    # ----------------------------------------------------------- geometry

    def sizeHint(self) -> QSize:
        text = self.fontMetrics().horizontalAdvance(self.text()) if self.text() else 0
        width = TRACK_W + (GAP + text if text else 0) + 4
        height = max(TRACK_H + 6, self.fontMetrics().height() + 4)
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)     # the label is clickable too

    # ------------------------------------------------------------ drawing

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        palette = self.palette()
        window = palette.color(QPalette.Window)
        ink = palette.color(QPalette.WindowText)
        hovered = self.underMouse() and self.isEnabled()

        top = (self.height() - TRACK_H) / 2
        track = QRectF(2, top, TRACK_W, TRACK_H)
        radius = TRACK_H / 2

        # off: a track in the theme's own colours; on: the run green
        off = _mix(window, ink, 0.38 if hovered else 0.30)
        on = ON.lighter(112) if hovered else ON
        fill = _mix(off, on, self._pos)
        if not self.isEnabled():
            fill = _mix(window, fill, 0.45)
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(track, radius, radius)

        # the knob, with a whisper of shadow so it sits on the track
        margin = 2
        diameter = TRACK_H - 2 * margin
        travel = TRACK_W - 2 * margin - diameter
        cx = track.left() + margin + diameter / 2 + travel * self._pos
        cy = track.center().y()
        painter.setBrush(QColor(0, 0, 0, 55))
        painter.drawEllipse(QPointF(cx, cy + 0.8), diameter / 2, diameter / 2)
        knob = KNOB if self.isEnabled() else _mix(window, KNOB, 0.6)
        painter.setBrush(knob)
        # a hairline edge: on the light theme's pale track a near-white knob
        # otherwise melted into it
        painter.setPen(QColor(0, 0, 0, 45))
        painter.drawEllipse(QPointF(cx, cy), diameter / 2, diameter / 2)
        painter.setPen(Qt.NoPen)

        if self.hasFocus():
            from flograph.ui.theme import BUTTON_ACCENT
            ring = QColor(BUTTON_ACCENT)
            ring.setAlpha(200)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(ring)
            painter.drawRoundedRect(track.adjusted(-1.5, -1.5, 1.5, 1.5),
                                    radius + 1.5, radius + 1.5)

        if self.text():
            painter.setPen(ink if self.isEnabled()
                           else palette.color(QPalette.Disabled,
                                              QPalette.WindowText))
            label = QRectF(track.right() + GAP, 0,
                           self.width() - track.right() - GAP, self.height())
            painter.drawText(label, Qt.AlignVCenter | Qt.AlignLeft,
                             self.text())
        painter.end()
