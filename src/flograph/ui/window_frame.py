"""A client-side window frame: our own title bar, no OS decorations.

Switched on by ``window/custom_frame`` (default on). The window loses
``Qt.FramelessWindowHint``'s decorations and this draws the replacement —
one bar carrying, left to right: the app mark, a hamburger holding the
File/Edit/Run/… menus, a project switcher, then right-aligned the run
actions and the minimise / maximise / close buttons.

Move and resize are handed back to the compositor via
``QWindow.startSystemMove`` / ``startSystemResize`` — native on Wayland
(xdg-toplevel) and Windows, so snapping, tiling and keyboard-move keep
working. The 6px resize border is eight thin child widgets rather than
hit-testing in an event filter, so they never fight a child widget's own
cursor. Everything is drawn with ``QPainterPath`` for the same reasons
``toolbar.py`` and ``canvas/marks.py`` give.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor, QGuiApplication, QIcon, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMenu, QSizePolicy, QToolButton, QWidget,
)

from . import theme
from . import toolbar as toolbar_style

BAR_HEIGHT = 34
RESIZE_MARGIN = 6
_ICON_PT = 16

_FG = QColor("#c8cbd2")
_CLOSE_HOVER = QColor("#e5484d")


# --------------------------------------------------------------- glyphs

def _pen(color: QColor, w: float) -> QPen:
    pen = QPen(color, w)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _logo(p: QPainter, r: QRectF, color: QColor) -> None:
    """Two nodes and the wire between them — the app's own visual language,
    the same mark the desktop-shortcut icon uses. Kept blunt: at 18px the
    detail of the real node card just turns to mud."""
    w, h = r.width(), r.height()
    a = QPointF(r.left() + w * 0.28, r.top() + h * 0.28)
    b = QPointF(r.left() + w * 0.72, r.top() + h * 0.72)
    p.setPen(_pen(theme.BUTTON_ACCENT, max(1.3, w * 0.085)))
    p.drawLine(a, b)
    p.setPen(Qt.NoPen)
    p.setBrush(theme.BUTTON_ACCENT)
    for c in (a, b):
        node = QRectF(0, 0, w * 0.42, h * 0.42)
        node.moveCenter(c)
        p.drawRoundedRect(node, w * 0.10, w * 0.10)


def _hamburger(p: QPainter, r: QRectF, color: QColor) -> None:
    p.setPen(_pen(color, max(1.4, r.width() * 0.09)))
    for f in (0.30, 0.5, 0.70):
        y = r.top() + r.height() * f
        p.drawLine(QPointF(r.left() + r.width() * 0.22, y),
                   QPointF(r.left() + r.width() * 0.78, y))


def _chevron(p: QPainter, r: QRectF, color: QColor) -> None:
    p.setPen(_pen(color, max(1.2, r.width() * 0.10)))
    w, h = r.width(), r.height()
    p.drawPolyline([QPointF(r.left() + w * 0.32, r.top() + h * 0.42),
                    QPointF(r.left() + w * 0.5, r.top() + h * 0.60),
                    QPointF(r.left() + w * 0.68, r.top() + h * 0.42)])


def _min(p: QPainter, r: QRectF, color: QColor) -> None:
    p.setPen(_pen(color, max(1.3, r.width() * 0.07)))
    y = r.center().y() + r.height() * 0.12
    p.drawLine(QPointF(r.left() + r.width() * 0.28, y),
               QPointF(r.left() + r.width() * 0.72, y))


def _max(p: QPainter, r: QRectF, color: QColor) -> None:
    p.setPen(_pen(color, max(1.3, r.width() * 0.07)))
    p.setBrush(Qt.NoBrush)
    s = r.width() * 0.42
    box = QRectF(0, 0, s, s)
    box.moveCenter(r.center())
    p.drawRect(box)


def _restore(p: QPainter, r: QRectF, color: QColor) -> None:
    p.setPen(_pen(color, max(1.2, r.width() * 0.065)))
    p.setBrush(Qt.NoBrush)
    s = r.width() * 0.36
    back = QRectF(r.center().x() - s * 0.35, r.center().y() - s * 0.65, s, s)
    front = QRectF(r.center().x() - s * 0.65, r.center().y() - s * 0.35, s, s)
    p.drawRect(back)
    p.fillRect(front, theme.NODE_HEADER)
    p.drawRect(front)


def _save(p: QPainter, r: QRectF, color: QColor) -> None:
    """A floppy disk. Blunt on purpose — at 16px the shutter and hub of a
    real one are noise."""
    w, h = r.width(), r.height()
    o = QPainterPath(QPointF(r.left() + w * 0.17, r.top() + h * 0.19))
    o.lineTo(r.left() + w * 0.70, r.top() + h * 0.19)
    o.lineTo(r.left() + w * 0.83, r.top() + h * 0.32)
    o.lineTo(r.left() + w * 0.83, r.top() + h * 0.83)
    o.lineTo(r.left() + w * 0.17, r.top() + h * 0.83)
    o.closeSubpath()
    p.setPen(_pen(color, max(1.3, w * 0.085)))
    p.setBrush(Qt.NoBrush)
    p.drawPath(o)
    # the label patch across the lower half
    label = QRectF(r.left() + w * 0.30, r.top() + h * 0.53,
                   w * 0.40, h * 0.30)
    p.fillRect(label, color)


def _close(p: QPainter, r: QRectF, color: QColor) -> None:
    p.setPen(_pen(color, max(1.3, r.width() * 0.075)))
    w, h = r.width(), r.height()
    p.drawLine(QPointF(r.left() + w * 0.30, r.top() + h * 0.30),
               QPointF(r.left() + w * 0.70, r.top() + h * 0.70))
    p.drawLine(QPointF(r.left() + w * 0.70, r.top() + h * 0.30),
               QPointF(r.left() + w * 0.30, r.top() + h * 0.70))


_GLYPHS = {
    "logo": _logo, "hamburger": _hamburger, "chevron": _chevron, "save": _save,
    "min": _min, "max": _max, "restore": _restore, "close": _close,
}

_SAVED = QColor("#5f636d")
_UNSAVED = theme.BUTTON_ACCENT


def frame_icon(kind: str, color: QColor = _FG, pt: int = _ICON_PT) -> QIcon:
    fn = _GLYPHS[kind]
    icon = QIcon()
    for ratio in (1, 2, 3):
        pm = QPixmap(pt * ratio, pt * ratio)
        pm.fill(Qt.transparent)
        pm.setDevicePixelRatio(ratio)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        fn(p, QRectF(0, 0, pt, pt), color)
        p.end()
        icon.addPixmap(pm)
    return icon


def app_icon() -> QIcon:
    """The window / taskbar icon — the mark on a rounded dark tile."""
    icon = QIcon()
    for size in (32, 64, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(0, 0, size, size)
        tile = QPainterPath()
        tile.addRoundedRect(r.adjusted(size * 0.06, size * 0.06,
                                       -size * 0.06, -size * 0.06),
                            size * 0.18, size * 0.18)
        p.fillPath(tile, theme.CANVAS_BG.lighter(115))
        p.setPen(_pen(theme.GRID_COARSE, size * 0.012))
        p.drawPath(tile)
        _logo(p, r.adjusted(size * 0.18, size * 0.18,
                            -size * 0.18, -size * 0.18), _FG)
        p.end()
        icon.addPixmap(pm)
    return icon


# --------------------------------------------------------------- widgets

_BTN_QSS = f"""
QToolButton {{
    background: transparent; border: 1px solid transparent;
    border-radius: 4px; padding: 3px 6px; color: {_FG.name()};
    font-size: 9pt;
}}
QToolButton:hover {{ background: #34363f; color: #f3f4f6; }}
QToolButton:pressed {{ background: #3d404a; }}
QToolButton:disabled {{ color: #5f636d; }}
QToolButton::menu-indicator {{ image: none; }}
"""

_WINBTN_QSS = f"""
QToolButton {{ background: transparent; border: none; border-radius: 0;
               padding: 0; }}
QToolButton:hover {{ background: #34363f; }}
QToolButton:pressed {{ background: #3d404a; }}
QToolButton#close_btn:hover {{ background: {_CLOSE_HOVER.name()}; }}
"""


class TitleBar(QWidget):
    """The one bar. Owns nothing but layout and the window buttons; the run
    actions and the menu tree are the window's, shown here."""

    def __init__(self, window, menu: QMenu) -> None:
        super().__init__(window)
        self._window = window
        self._press_pos = None
        self.setObjectName("title_bar")
        self.setFixedHeight(BAR_HEIGHT)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QWidget#title_bar {{ background: {theme.CANVAS_BG.darker(108).name()};"
            f" border-bottom: 1px solid #14151a; }}" + _BTN_QSS)

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 0, 0, 0)
        row.setSpacing(2)

        logo = QLabel()
        logo.setPixmap(frame_icon("logo", pt=20).pixmap(19, 19))
        logo.setContentsMargins(2, 0, 4, 0)
        row.addWidget(logo)

        self._menu_btn = QToolButton()
        self._menu_btn.setObjectName("menu_btn")
        self._menu_btn.setIcon(frame_icon("hamburger"))
        self._menu_btn.setPopupMode(QToolButton.InstantPopup)
        self._menu_btn.setMenu(menu)
        self._menu_btn.setToolTip("Menu")
        row.addWidget(self._menu_btn)

        self._project_btn = QToolButton()
        self._project_btn.setObjectName("project_btn")
        self._project_btn.setPopupMode(QToolButton.InstantPopup)
        self._project_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._project_btn.setLayoutDirection(Qt.RightToLeft)  # chevron after text
        self._project_btn.setIcon(frame_icon("chevron"))
        self._project_menu = QMenu(self._project_btn)
        self._project_menu.aboutToShow.connect(self._rebuild_project_menu)
        self._project_btn.setMenu(self._project_menu)
        row.addSpacing(4)
        row.addWidget(self._project_btn)

        self._save_btn = QToolButton()
        self._save_btn.setObjectName("save_btn")
        self._save_btn.setIconSize(QSize(_ICON_PT, _ICON_PT))
        self._save_btn.clicked.connect(window._save)
        row.addWidget(self._save_btn)

        row.addStretch(1)

        self._run_btns: list[QToolButton] = []
        for action in (window.action_run, window.action_run_selected,
                       window.action_cancel, window.action_reset_caches):
            btn = QToolButton()
            btn.setDefaultAction(action)
            btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            row.addWidget(btn)
            self._run_btns.append(btn)

        row.addSpacing(6)

        self._win_btns = QWidget()
        self._win_btns.setStyleSheet(_WINBTN_QSS)
        wb = QHBoxLayout(self._win_btns)
        wb.setContentsMargins(0, 0, 0, 0)
        wb.setSpacing(0)
        self._btn_min = self._win_button("min", self._window.showMinimized,
                                         "Minimise")
        self._btn_max = self._win_button("max", self._toggle_max, "Maximise")
        self._btn_close = self._win_button("close", self._window.close, "Close")
        self._btn_close.setObjectName("close_btn")
        for b in (self._btn_min, self._btn_max, self._btn_close):
            wb.addWidget(b)
        row.addWidget(self._win_btns)

        self._sync_max_button()

    # -- window buttons ------------------------------------------------

    def _win_button(self, kind: str, slot, tip: str) -> QToolButton:
        btn = QToolButton()
        btn.setIcon(frame_icon(kind))
        btn.setIconSize(QSize(_ICON_PT, _ICON_PT))
        btn.setFixedSize(46, BAR_HEIGHT)
        btn.setToolTip(tip)
        btn.clicked.connect(slot)
        return btn

    def _toggle_max(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def _sync_max_button(self) -> None:
        maxed = self._window.isMaximized()
        self._btn_max.setIcon(frame_icon("restore" if maxed else "max"))
        self._btn_max.setToolTip("Restore" if maxed else "Maximise")

    # -- project switcher --------------------------------------------

    def refresh_title(self) -> None:
        from pathlib import Path
        path = getattr(self._window, "_project_path", None)
        self._project_btn.setText(Path(path).name if path else "untitled")
        dirty = not self._window.undo_stack.isClean()
        self._save_btn.setIcon(frame_icon("save", _UNSAVED if dirty else _SAVED))
        self._save_btn.setToolTip(
            "Save  (Ctrl+S)" if dirty else "All changes saved")

    def _rebuild_project_menu(self) -> None:
        m = self._project_menu
        m.clear()
        m.addAction(self._window.action_save)
        m.addAction(self._window.action_save_as)
        m.addSeparator()
        m.addAction(self._window.action_new)
        m.addAction(self._window.action_open)
        recent = self._window._recent_files_existing()
        if recent:
            m.addSeparator()
            for p in recent:
                from pathlib import Path
                act = m.addAction(Path(p).name)
                act.setToolTip(p)
                act.triggered.connect(
                    lambda checked=False, path=p: self._window.open_path(path))

    # -- drag / double-click ---------------------------------------

    def _on_bare_bar(self, pos) -> bool:
        """True where the bar itself shows through — not over a button."""
        return self.childAt(pos) is None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._on_bare_bar(
                event.position().toPoint()):
            self._press_pos = event.position().toPoint()
        else:
            self._press_pos = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        # A press that turns into a drag hands off to the compositor; a press
        # that stays put is left alone, so a plain click never grabs the
        # window and the double-click below still fires.
        if (self._press_pos is not None
                and event.buttons() & Qt.LeftButton
                and (event.position().toPoint() - self._press_pos
                     ).manhattanLength() >= QGuiApplication.styleHints(
                     ).startDragDistance()):
            self._press_pos = None
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemMove()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._on_bare_bar(
                event.position().toPoint()):
            self._toggle_max()
            return
        super().mouseDoubleClickEvent(event)


class _Grip(QWidget):
    """A thin invisible strip along one window edge or corner. Its whole job
    is to own a resize cursor and hand a press to the compositor."""

    def __init__(self, window, edges: Qt.Edges, cursor: Qt.CursorShape) -> None:
        super().__init__(window)
        self._window = window
        self._edges = edges
        self.setCursor(cursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None and not self._window.isMaximized():
                handle.startSystemResize(self._edges)
                return
        super().mousePressEvent(event)


class FramelessResizer(QObject):
    """Lays the eight resize grips over the window and keeps the title bar's
    maximise button and the grips in step with the window state."""

    def __init__(self, window, title_bar: TitleBar) -> None:
        super().__init__(window)
        self._window = window
        self._title_bar = title_bar
        m = RESIZE_MARGIN
        E = Qt.Edge
        self._grips = [
            _Grip(window, E.TopEdge, Qt.SizeVerCursor),
            _Grip(window, E.BottomEdge, Qt.SizeVerCursor),
            _Grip(window, E.LeftEdge, Qt.SizeHorCursor),
            _Grip(window, E.RightEdge, Qt.SizeHorCursor),
            _Grip(window, E.TopEdge | E.LeftEdge, Qt.SizeFDiagCursor),
            _Grip(window, E.BottomEdge | E.RightEdge, Qt.SizeFDiagCursor),
            _Grip(window, E.TopEdge | E.RightEdge, Qt.SizeBDiagCursor),
            _Grip(window, E.BottomEdge | E.LeftEdge, Qt.SizeBDiagCursor),
        ]
        self._margin = m
        window.installEventFilter(self)
        self._reposition()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._window:
            et = event.type()
            if et in (QEvent.Resize, QEvent.Show):
                self._reposition()
            elif et == QEvent.WindowStateChange:
                self._reposition()
                self._title_bar._sync_max_button()
        return False

    def _reposition(self) -> None:
        w, h, m = self._window.width(), self._window.height(), self._margin
        hide = self._window.isMaximized() or self._window.isFullScreen()
        c = m * 2
        rects = [
            (c, 0, w - 2 * c, m), (c, h - m, w - 2 * c, m),
            (0, c, m, h - 2 * c), (w - m, c, m, h - 2 * c),
            (0, 0, c, c), (w - c, h - c, c, c),
            (w - c, 0, c, c), (0, h - c, c, c),
        ]
        for grip, rect in zip(self._grips, rects):
            grip.setGeometry(*rect)
            grip.setVisible(not hide)
            grip.raise_()

    def raise_grips(self) -> None:
        for grip in self._grips:
            grip.raise_()
