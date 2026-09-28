"""The "preview is catching up" signal over a report page's preview.

Painted, not a QProgressBar. A 3px busy bar came out as nothing at all
under the app's style — the report updated a couple of seconds after the
typing stopped with no sign it was on its way. This floats over the top of
the preview instead, so showing it moves nothing: a stripe of accent colour
running across the top edge, and a small "Updating preview…" in the corner.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from ..theme import BUTTON_ACCENT

STRIPE_PX = 3
#: how far along the stripe the moving segment gets per frame, as a
#: fraction of the width
STEP = 0.018
FRAME_MS = 30
LABEL = "Updating preview…"


class BusyOverlay(QWidget):
    """Floats over `host`, following its size; clicks go straight through."""

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.setObjectName("report_preview_loading")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setToolTip(LABEL)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        host.installEventFilter(self)
        self._fit()
        self.hide()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() == QEvent.Resize:
            self._fit()
        return False

    def _fit(self) -> None:
        host = self.parentWidget()
        height = self.fontMetrics().height() + 16
        self.setGeometry(0, 0, host.width(), height)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit()
        self.raise_()
        self._timer.start()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def _tick(self) -> None:
        self._phase = (self._phase + STEP) % 1.0
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width = self.width()

        # the stripe: a faint track, and a segment sliding along it
        track = QColor(BUTTON_ACCENT)
        track.setAlpha(60)
        painter.fillRect(QRectF(0, 0, width, STRIPE_PX), track)
        segment = width * 0.3
        left = -segment + (width + segment) * self._phase
        painter.fillRect(QRectF(left, 0, segment, STRIPE_PX), BUTTON_ACCENT)

        # the words, on a pill so they read over paper or desk alike
        metrics = self.fontMetrics()
        text_w = metrics.horizontalAdvance(LABEL)
        pill = QRectF(width - text_w - 28, STRIPE_PX + 4,
                      text_w + 18, metrics.height() + 6)
        path = QPainterPath()
        path.addRoundedRect(pill, pill.height() / 2, pill.height() / 2)
        painter.fillPath(path, QColor(30, 30, 34, 215))
        painter.setPen(QColor("#ffffff"))
        painter.drawText(pill, Qt.AlignCenter, LABEL)
        painter.end()
