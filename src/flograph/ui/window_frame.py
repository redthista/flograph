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

import hashlib
import re
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QAction, QColor, QFont, QFontMetrics, QGuiApplication, QIcon, QKeySequence,
    QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMenu, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
    QWidgetAction,
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
    a = QPointF(r.left() + w * 0.30, r.top() + h * 0.32)
    b = QPointF(r.left() + w * 0.70, r.top() + h * 0.68)
    p.setPen(_pen(theme.BUTTON_ACCENT, max(1.2, w * 0.10)))
    p.drawLine(a, b)
    p.setPen(Qt.NoPen)
    p.setBrush(theme.BUTTON_ACCENT)
    radius = w * 0.17
    for c in (a, b):
        p.drawEllipse(c, radius, radius)


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


def _clear_cache(p: QPainter, r: QRectF, color: QColor) -> None:
    """The reset circular-arrow wrapped around one node — 'recompute just
    this', vs the empty ring of the whole-flow Reset Caches."""
    w, h = r.width(), r.height()
    ring = QRectF(r.left() + w * 0.16, r.top() + h * 0.16, w * 0.68, h * 0.68)
    p.setPen(_pen(color, max(1.3, w * 0.11)))
    p.setBrush(Qt.NoBrush)
    p.drawArc(ring, 70 * 16, 300 * 16)
    head = QPainterPath(QPointF(r.left() + w * 0.62, r.top() + h * 0.06))
    head.lineTo(r.left() + w * 0.84, r.top() + h * 0.20)
    head.lineTo(r.left() + w * 0.58, r.top() + h * 0.34)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawPath(head)
    node = QRectF(0, 0, w * 0.30, h * 0.30)
    node.moveCenter(r.center())
    p.drawRoundedRect(node, w * 0.07, w * 0.07)


_GLYPHS = {
    "logo": _logo, "hamburger": _hamburger, "chevron": _chevron, "save": _save,
    "clear_cache": _clear_cache,
    "min": _min, "max": _max, "restore": _restore, "close": _close,
}

_UNSAVED = theme.BUTTON_ACCENT
# transparent px baked onto the right of the switcher's initials tile, since
# a QToolButton has no icon-text spacing setting of its own
_SWITCHER_GAP = 5


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


# --------------------------------------------------------- initials tile

def initials_for(name: str) -> str:
    """PyCharm's rule: one letter per word for the first two words, else the
    first two letters of the single word."""
    parts = [p for p in re.split(r"[\s._\-]+", name.strip()) if p]
    if len(parts) >= 2:
        return (parts[0][:1] + parts[1][:1]).upper()
    if parts:
        return parts[0][:2].upper()
    return "?"


def initials_pixmap(name: str, size: int, ratio: float = 1.0,
                    pad_right: int = 0) -> QPixmap:
    """The tile is always ``size`` square; ``pad_right`` adds transparent
    canvas after it, which is how the title-bar switcher buys a gap between
    the tile and the workflow name (a QToolButton has no icon-text spacing
    knob)."""
    text = initials_for(name)
    digest = int(hashlib.md5(name.encode("utf-8")).hexdigest()[:8], 16)
    base = QColor.fromHsv(digest % 360, 105, 165)
    pm = QPixmap(max(1, round((size + pad_right) * ratio)),
                 max(1, round(size * ratio)))
    pm.fill(Qt.transparent)
    pm.setDevicePixelRatio(ratio)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    r = QRectF(0.5, 0.5, size - 1, size - 1)
    path = QPainterPath()
    path.addRoundedRect(r, size * 0.22, size * 0.22)
    p.fillPath(path, base)
    font = QFont()
    font.setPixelSize(max(6, round(size * 0.44)))
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor("#f4f5f7"))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, text)
    p.end()
    return pm


def initials_icon(name: str, size: int = 18, pad_right: int = 0) -> QIcon:
    icon = QIcon()
    for ratio in (1, 2, 3):
        icon.addPixmap(initials_pixmap(name, size, ratio, pad_right))
    return icon


def project_display_name(path) -> str:
    """The workflow's name with no folder and no .flograph extension."""
    return Path(path).stem if path else "untitled"


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


_RECENT_QSS = """
QWidget#recent_row { background: transparent; }
QWidget#recent_row:hover { background: #34363f; }
QLabel#recent_name { color: #e5e7eb; }
QLabel#recent_path { color: #8b8f99; }
"""


class _RecentRow(QWidget):
    """One workflow in the project switcher: its initials tile, its name, and
    the folder it lives in — the shape PyCharm's recent-projects list uses."""

    def __init__(self, path: str, on_open, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("recent_row")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_RECENT_QSS)
        self.setCursor(Qt.PointingHandCursor)
        self._path = path
        self._on_open = on_open

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 5, 16, 5)
        row.setSpacing(9)

        tile = QLabel()
        tile.setPixmap(initials_pixmap(project_display_name(path), 30))
        row.addWidget(tile, 0, Qt.AlignVCenter)

        text = QVBoxLayout()
        text.setSpacing(0)
        name = QLabel(project_display_name(path))
        name.setObjectName("recent_name")
        folder = str(Path(path).parent)
        home = str(Path.home())
        if folder.startswith(home):
            folder = "~" + folder[len(home):]
        path_label = QLabel()
        path_label.setObjectName("recent_path")
        path_label.setFont(_smaller(path_label.font()))
        path_label.setText(QFontMetrics(path_label.font()).elidedText(
            folder, Qt.ElideMiddle, 340))
        text.addWidget(name)
        text.addWidget(path_label)
        row.addLayout(text, 1)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self._on_open(self._path)
        super().mouseReleaseEvent(event)


def _smaller(font: QFont) -> QFont:
    f = QFont(font)
    f.setPointSizeF(max(6.5, font.pointSizeF() - 1.5))
    return f


class TitleBar(QWidget):
    """The one bar. Owns nothing but layout and the window buttons; the run
    actions and the menu tree are the window's, shown here."""

    def __init__(self, window, menu: QMenu) -> None:
        super().__init__(window)
        self._window = window
        self._press_pos = None
        self._compact = False
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
        logo.setPixmap(frame_icon("logo", pt=32).pixmap(18, 18))
        logo.setContentsMargins(2, 0, 4, 0)
        logo.setToolTip("flograph")
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
        self._project_btn.setIconSize(QSize(18 + _SWITCHER_GAP, 18))
        self._project_btn.setToolTip("Current workflow — switch or open another")
        self._project_menu = QMenu(self._project_btn)
        self._project_menu.aboutToShow.connect(self._rebuild_project_menu)
        self._project_btn.setMenu(self._project_menu)
        row.addSpacing(4)
        row.addWidget(self._project_btn)

        # Only on screen when it matters: no button while everything is
        # saved, and its own label ("Unsaved changes") once it appears.
        self._save_btn = QToolButton()
        self._save_btn.setObjectName("save_btn")
        self._save_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._save_btn.setIcon(frame_icon("save", _UNSAVED))
        self._save_btn.setText("Unsaved changes")
        self._save_btn.setToolTip("Save the workflow  (Ctrl+S)")
        self._save_btn.clicked.connect(window._save)
        self._save_btn.hide()
        row.addSpacing(4)
        row.addWidget(self._save_btn)

        row.addStretch(1)

        # Whether the run buttons carry their shortcut in brackets — View ▸
        # Shortcuts on Title-Bar Buttons, applied via set_show_shortcuts.
        self._show_shortcuts = True

        # Run All doubles as Stop while a run is on — clicking it again, or
        # Escape, cancels. There is no separate Cancel button.
        self._run_btn = QToolButton()
        self._run_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._run_btn.clicked.connect(self._on_run_clicked)

        # Run Selected and Reset Selected Caches are a pair — both only on the
        # bar while at least one node is selected (see on_selection). None of
        # these four are setDefaultAction buttons: their labels carry the
        # shortcut suffix, which the action's own text can't (see
        # _refresh_run_labels).
        self._run_sel_btn = QToolButton()
        self._run_sel_btn.setIcon(toolbar_style.toolbar_icon("run_selected"))
        self._run_sel_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._run_sel_btn.setToolTip("Run the selected nodes")
        self._run_sel_btn.clicked.connect(window.action_run_selected.trigger)

        self._clear_cache_btn = QToolButton()
        self._clear_cache_btn.setIcon(
            frame_icon("clear_cache", toolbar_style.RESET))
        self._clear_cache_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._clear_cache_btn.setToolTip(
            "Discard the cached results for the selected nodes only")
        self._clear_cache_btn.clicked.connect(
            window.action_reset_selected_caches.trigger)

        self._reset_btn = QToolButton()
        self._reset_btn.setIcon(toolbar_style.toolbar_icon("reset_caches"))
        self._reset_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._reset_btn.setToolTip(
            "Discard every cached result — the flow re-runs from scratch")
        self._reset_btn.clicked.connect(window.action_reset_caches.trigger)

        self._labelled = [self._run_btn, self._run_sel_btn, self._clear_cache_btn,
                          self._reset_btn, self._save_btn]
        for btn in (self._run_btn, self._run_sel_btn, self._clear_cache_btn,
                    self._reset_btn):
            row.addWidget(btn)
        self._set_running(False)
        self.on_selection(0)
        window.engine.run_started.connect(lambda: self._set_running(True))
        window.engine.run_finished.connect(lambda ok: self._set_running(False))

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
        self._btn_max.setToolTip(
            "Restore the window" if maxed else "Maximise the window")

    # -- run / stop -------------------------------------------------

    def _on_run_clicked(self) -> None:
        if self._window.engine.active:
            self._window.engine.cancel()
        else:
            self._window.action_run.trigger()

    def _set_running(self, running: bool) -> None:
        self._running = running
        if running:
            self._run_btn.setIcon(toolbar_style.toolbar_icon("cancel"))
            self._run_btn.setToolTip("Stop the running flow  (Esc)")
        else:
            self._run_btn.setIcon(toolbar_style.toolbar_icon("run_all"))
            self._run_btn.setToolTip("Run the whole flow  (F5)")
        self._run_sel_btn.setEnabled(not running)
        self._refresh_run_labels()

    def set_show_shortcuts(self, show: bool) -> None:
        """Whether the run / cache buttons show their key in brackets
        (View ▸ Shortcuts on Title-Bar Buttons)."""
        self._show_shortcuts = bool(show)
        self._refresh_run_labels()

    def _refresh_run_labels(self) -> None:
        w = self._window

        def label(text: str, action) -> str:
            key = action.shortcut().toString(QKeySequence.NativeText)
            return f"{text}  ({key})" if self._show_shortcuts and key else text

        if getattr(self, "_running", False):
            self._run_btn.setText(label("Stop", w.action_cancel))
        else:
            self._run_btn.setText(label("Run All", w.action_run))
        self._run_sel_btn.setText(label("Run Selected", w.action_run_selected))
        self._clear_cache_btn.setText(
            label("Reset Selected Caches", w.action_reset_selected_caches))
        self._reset_btn.setText(label("Reset Caches", w.action_reset_caches))

    def on_selection(self, count: int) -> None:
        """Run Selected and Reset Selected Caches are only on the bar while
        something is selected."""
        has = count >= 1
        self._run_sel_btn.setVisible(has)
        self._clear_cache_btn.setVisible(has)

    # -- compact ---------------------------------------------------

    def set_compact(self, compact: bool) -> None:
        """Icon-only run/save buttons (their tooltips still explain them);
        the workflow name always stays."""
        self._compact = bool(compact)
        style = (Qt.ToolButtonIconOnly if compact
                 else Qt.ToolButtonTextBesideIcon)
        for btn in self._labelled:
            btn.setToolButtonStyle(style)

    # -- right-click menu -----------------------------------------

    def context_menu(self) -> QMenu:
        menu = QMenu(self)
        hide_text = menu.addAction("Hide Button Text")
        hide_text.setCheckable(True)
        hide_text.setChecked(self._compact)
        hide_text.toggled.connect(self._window.set_titlebar_compact)
        hide_keys = menu.addAction("Hide Shortcut Keys")
        hide_keys.setCheckable(True)
        hide_keys.setChecked(not self._show_shortcuts)
        hide_keys.toggled.connect(
            lambda hide: self._window._set_titlebar_shortcuts(not hide))
        return menu

    def contextMenuEvent(self, event) -> None:
        self.context_menu().exec(event.globalPos())

    # -- project switcher --------------------------------------------

    def refresh_title(self) -> None:
        path = getattr(self._window, "_project_path", None)
        name = project_display_name(path)
        self._project_btn.setText(name)
        self._project_btn.setIcon(initials_icon(name, pad_right=_SWITCHER_GAP))
        self._save_btn.setVisible(not self._window.undo_stack.isClean())

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
            header = m.addAction("Recent workflows")
            header.setEnabled(False)
            for p in recent:
                item = QWidgetAction(m)
                item.setDefaultWidget(_RecentRow(p, self._open_recent))
                m.addAction(item)

    def _open_recent(self, path: str) -> None:
        self._project_menu.close()
        self._window.open_path(path)

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
