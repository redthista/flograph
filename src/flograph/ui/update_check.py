"""Update check — a read-only "is there a newer flograph?" probe and the
small notice it can raise.

Design constraints, straight from the request:
  * **Informative only.** It never installs anything and never runs pip on
    the user's behalf — the most it shows is a command to copy.
  * **Off by default.** The once-a-day check on startup runs only when the
    user has ticked Settings ▸ General ▸ Updates.
  * **Never in the way.** The startup notice is a non-modal toast in the
    corner of the window that dismisses itself; it appears at most once per
    new version, never twice for the same one.
  * **Safe in a locked-down environment.** Every failure path is silent — an
    air-gapped machine, or one pinned to a private mirror that has no route
    to pypi.org, simply sees nothing.

The manual "Check for updates" button in Settings ▸ About calls the same
probe with the throttle bypassed and shows its result inline, not as a toast.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from PySide6.QtCore import (
    QObject, QRunnable, Qt, QThreadPool, QTimer, Signal,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget,
)

from flograph import packages

CHECK_INTERVAL_HOURS = 24
SETTINGS_ENABLED = "updates/notify"
SETTINGS_LAST_CHECK = "updates/last_check"
SETTINGS_LAST_NOTIFIED = "updates/last_notified_version"


def due_for_check(last_iso: "str | None", now: datetime,
                  min_hours: float = CHECK_INTERVAL_HOURS) -> bool:
    """Whether a startup check should run: never checked before, an
    unreadable timestamp, or more than `min_hours` since the last one."""
    if not last_iso:
        return True
    try:
        last = datetime.fromisoformat(last_iso)
        if last.tzinfo is None:              # older / hand-set stamps
            last = last.replace(tzinfo=timezone.utc)
        return now - last >= timedelta(hours=min_hours)
    except (ValueError, TypeError):
        return True


class _ProbeSignals(QObject):
    done = Signal(str, object, bool)      # current, latest | None, newer


class _Probe(QRunnable):
    """Runs `packages.update_status()` off the UI thread. The status call
    swallows its own exceptions, but the belt-and-braces guard here means a
    probe can never take the event loop down with it."""

    def __init__(self) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self.signals = _ProbeSignals()

    def run(self) -> None:
        try:
            current, latest, newer = packages.update_status()
        except Exception:
            current, latest, newer = packages.installed_version(), None, False
        self.signals.done.emit(current, latest, newer)


#: probes in flight — a queued result can arrive after the local reference
#: is gone, so the runnable and its signals are pinned here until it does.
_live_probes: "set[_Probe]" = set()


def run_probe(on_done) -> None:
    """Start a background probe. `on_done(current, latest, newer)` is called
    on the UI thread when it finishes — `latest` is None when the check
    could not reach any index."""
    probe = _Probe()
    _live_probes.add(probe)

    def _finished(current: str, latest, newer: bool) -> None:
        _live_probes.discard(probe)
        on_done(current, latest, newer)

    probe.signals.done.connect(_finished, Qt.QueuedConnection)
    QThreadPool.globalInstance().start(probe)


class UpdateToast(QFrame):
    """A small, non-modal "new version available" notice in the corner of
    the main window. It closes itself after a while, or when the user
    clicks it away; clicking the body opens Settings ▸ About for the how-to.

    Deliberately not a QMessageBox: a modal dialog on startup is exactly the
    "bugs the user" behaviour this feature is meant to avoid.
    """

    DISMISS_MS = 20_000

    def __init__(self, window: QWidget, latest: str) -> None:
        super().__init__(window)
        self._window = window
        self.setObjectName("update_toast")
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "#update_toast { background: palette(window); "
            "border: 1px solid palette(mid); border-radius: 8px; }"
            "#update_toast QLabel { border: none; background: transparent; }")

        headline = QLabel(f"flograph {latest} is available")
        sub = QLabel("Click for how to update")
        font = sub.font()
        font.setPointSizeF(font.pointSizeF() * 0.9)
        sub.setFont(font)
        sub.setEnabled(False)

        close = QToolButton()
        close.setText("×")
        close.setAutoRaise(True)
        close.setCursor(Qt.ArrowCursor)
        close.setToolTip("Dismiss")
        close.clicked.connect(self.close)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(1)
        column.addWidget(headline)
        column.addWidget(sub)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 8, 8)
        row.setSpacing(10)
        row.addLayout(column, 1)
        row.addWidget(close, 0, Qt.AlignTop)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.close)

    def show_in_corner(self) -> None:
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()
        self._timer.start(self.DISMISS_MS)

    def _reposition(self) -> None:
        margin = 18
        parent = self.parentWidget()
        if parent is None:
            return
        lift = 0
        status = getattr(self._window, "statusBar", None)
        if callable(status):
            try:
                lift = status().height()
            except Exception:
                lift = 0
        x = parent.width() - self.width() - margin
        y = parent.height() - self.height() - margin - lift
        self.move(max(margin, x), max(margin, y))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            opener = getattr(self._window, "show_update_details", None)
            if callable(opener):
                opener()
            self.close()
        else:
            super().mouseReleaseEvent(event)


def maybe_check_on_startup(window) -> None:
    """Run the once-a-day check, if the user opted in and a day has passed.

    Called once, when the main window is first shown. Stamps the last-check
    time whatever the outcome — a machine that is offline at launch waits
    until tomorrow rather than probing on every window show.
    """
    settings = window.settings
    if not settings.value(SETTINGS_ENABLED, False, type=bool):
        return
    last = settings.value(SETTINGS_LAST_CHECK, "", type=str)
    if not due_for_check(last, datetime.now(timezone.utc)):
        return

    def handle(_current: str, latest, newer: bool) -> None:
        settings.setValue(SETTINGS_LAST_CHECK,
                          datetime.now(timezone.utc).isoformat())
        if not newer or latest is None:
            return
        if settings.value(SETTINGS_LAST_NOTIFIED, "", type=str) == latest:
            return                       # already told them about this one
        settings.setValue(SETTINGS_LAST_NOTIFIED, latest)
        if window.isVisible():
            UpdateToast(window, latest).show_in_corner()

    run_probe(handle)
