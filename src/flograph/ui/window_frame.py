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
import math
import re
import time
from pathlib import Path

from PySide6.QtCore import (
    QEvent, QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal,
)
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
from .resource_monitor import format_bytes

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


def _star_path(r: QRectF) -> QPainterPath:
    cx, cy = r.center().x(), r.center().y()
    outer = min(r.width(), r.height()) * 0.46
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = outer if i % 2 == 0 else outer * 0.40
        pts.append(QPointF(cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    path = QPainterPath(pts[0])
    for pt in pts[1:]:
        path.lineTo(pt)
    path.closeSubpath()
    return path


def _star(p: QPainter, r: QRectF, color: QColor) -> None:
    """A hollow five-point star — 'not a favourite, click to add'."""
    p.setPen(_pen(color, max(1.1, r.width() * 0.09)))
    p.setBrush(Qt.NoBrush)
    p.drawPath(_star_path(r))


def _star_filled(p: QPainter, r: QRectF, color: QColor) -> None:
    """The same star, filled — a starred workflow."""
    p.setPen(_pen(color, max(1.0, r.width() * 0.06)))
    p.setBrush(color)
    p.drawPath(_star_path(r))


def _save_as(p: QPainter, r: QRectF, color: QColor) -> None:
    """The floppy outline with an ellipsis where its label patch would be —
    "save, but somewhere else"."""
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
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    for fx in (0.35, 0.5, 0.65):
        p.drawEllipse(QPointF(r.left() + w * fx, r.top() + h * 0.60),
                      w * 0.045, w * 0.045)


def _export(p: QPainter, r: QRectF, color: QColor) -> None:
    """A tray with a document lifting out of it — File ▸ Export Workflow."""
    w, h = r.width(), r.height()
    p.setPen(_pen(color, max(1.3, w * 0.085)))
    p.setBrush(Qt.NoBrush)
    tray = QPainterPath(QPointF(r.left() + w * 0.18, r.top() + h * 0.54))
    tray.lineTo(r.left() + w * 0.18, r.top() + h * 0.82)
    tray.lineTo(r.left() + w * 0.82, r.top() + h * 0.82)
    tray.lineTo(r.left() + w * 0.82, r.top() + h * 0.54)
    p.drawPath(tray)
    cx = r.center().x()
    p.drawLine(QPointF(cx, r.top() + h * 0.14), QPointF(cx, r.top() + h * 0.58))
    head = QPainterPath(QPointF(cx - w * 0.15, r.top() + h * 0.30))
    head.lineTo(cx, r.top() + h * 0.13)
    head.lineTo(cx + w * 0.15, r.top() + h * 0.30)
    p.drawPath(head)


def _new_doc(p: QPainter, r: QRectF, color: QColor) -> None:
    """A page with a folded corner and a plus — a fresh workflow."""
    w, h = r.width(), r.height()
    p.setPen(_pen(color, max(1.3, w * 0.085)))
    p.setBrush(Qt.NoBrush)
    page = QPainterPath(QPointF(r.left() + w * 0.24, r.top() + h * 0.13))
    page.lineTo(r.left() + w * 0.60, r.top() + h * 0.13)
    page.lineTo(r.left() + w * 0.77, r.top() + h * 0.30)
    page.lineTo(r.left() + w * 0.77, r.top() + h * 0.87)
    page.lineTo(r.left() + w * 0.24, r.top() + h * 0.87)
    page.closeSubpath()
    p.drawPath(page)
    cx, cy, s = r.center().x(), r.top() + h * 0.56, w * 0.13
    p.drawLine(QPointF(cx - s, cy), QPointF(cx + s, cy))
    p.drawLine(QPointF(cx, cy - s), QPointF(cx, cy + s))


def _folder(p: QPainter, r: QRectF, color: QColor) -> None:
    """A folder — open another workflow."""
    w, h = r.width(), r.height()
    p.setPen(_pen(color, max(1.3, w * 0.085)))
    p.setBrush(Qt.NoBrush)
    body = QPainterPath(QPointF(r.left() + w * 0.13, r.top() + h * 0.30))
    body.lineTo(r.left() + w * 0.40, r.top() + h * 0.30)
    body.lineTo(r.left() + w * 0.48, r.top() + h * 0.38)
    body.lineTo(r.left() + w * 0.87, r.top() + h * 0.38)
    body.lineTo(r.left() + w * 0.87, r.top() + h * 0.79)
    body.lineTo(r.left() + w * 0.13, r.top() + h * 0.79)
    body.closeSubpath()
    p.drawPath(body)


_GLYPHS = {
    "logo": _logo, "hamburger": _hamburger, "chevron": _chevron, "save": _save,
    "clear_cache": _clear_cache, "star": _star, "star_filled": _star_filled,
    "save_as": _save_as, "export": _export, "new_doc": _new_doc,
    "folder": _folder,
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


def paint_app_mark(p: QPainter, r: QRectF) -> None:
    """The flograph mark — the linked-nodes logo on a rounded dark tile.

    The one place the app icon is drawn: the window / taskbar icon
    (`app_icon`) and the desktop-shortcut icon both render through here so
    they stay the same picture.
    """
    side = min(r.width(), r.height())
    tile = QPainterPath()
    tile.addRoundedRect(r.adjusted(side * 0.06, side * 0.06,
                                   -side * 0.06, -side * 0.06),
                        side * 0.18, side * 0.18)
    p.fillPath(tile, theme.CANVAS_BG.lighter(115))
    p.setPen(_pen(theme.GRID_COARSE, side * 0.012))
    p.drawPath(tile)
    _logo(p, r.adjusted(side * 0.18, side * 0.18,
                        -side * 0.18, -side * 0.18), _FG)


def app_icon() -> QIcon:
    """The window / taskbar icon — the mark on a rounded dark tile."""
    icon = QIcon()
    for size in (32, 64, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        paint_app_mark(p, QRectF(0, 0, size, size))
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
QToolButton#star_btn { background: transparent; border: none;
                       border-radius: 4px; padding: 3px; }
QToolButton#star_btn:hover { background: #3d404a; }
"""

_STAR_OFF = QColor("#7f838d")


class _RecentRow(QWidget):
    """One workflow in the project switcher: its initials tile, its name, and
    the folder it lives in — the shape PyCharm's recent-projects list uses.
    When ``on_toggle_fav`` is given it also carries a star that adds or
    removes the workflow from the Favourites section."""

    def __init__(self, path: str, on_open, *, is_fav: bool = False,
                 on_toggle_fav=None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("recent_row")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_RECENT_QSS)
        self.setCursor(Qt.PointingHandCursor)
        self._path = path
        self._on_open = on_open
        self._on_toggle_fav = on_toggle_fav
        self._fav = bool(is_fav)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 5, 8, 5)
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

        if on_toggle_fav is not None:
            self._star_btn = QToolButton(self)
            self._star_btn.setObjectName("star_btn")
            self._star_btn.setCursor(Qt.PointingHandCursor)
            self._star_btn.setIconSize(QSize(16, 16))
            self._star_btn.clicked.connect(self._toggle_star)
            self._sync_star()
            row.addWidget(self._star_btn, 0, Qt.AlignVCenter)

    def _sync_star(self) -> None:
        self._star_btn.setIcon(frame_icon(
            "star_filled" if self._fav else "star",
            theme.BUTTON_ACCENT if self._fav else _STAR_OFF))
        self._star_btn.setToolTip(
            "Remove from favourites" if self._fav else "Add to favourites")

    def _toggle_star(self) -> None:
        self._fav = bool(self._on_toggle_fav(self._path))
        self._sync_star()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self._on_open(self._path)
        super().mouseReleaseEvent(event)


def _smaller(font: QFont) -> QFont:
    f = QFont(font)
    f.setPointSizeF(max(6.5, font.pointSizeF() - 1.5))
    return f


# ------------------------------------------------ project panel (menu header)

# The node-state palette, borrowed from the canvas' status colours so the
# little bar reads the same way a node does.
_STATE_COLOURS = {
    "cached": QColor(toolbar_style.RUN),      # green — has a fresh result
    "clean": QColor("#4b5563"),               # grey  — fine, nothing cached
    "stale": QColor(toolbar_style.RESET),     # amber — needs a re-run
    "frozen": QColor("#5b8def"),              # blue  — pinned, won't re-run
}

_PANEL_QSS = """
QWidget#project_panel { background: #2b2d36; border-radius: 8px; }
QLabel#pp_name { color: #f3f4f6; font-size: 11pt; font-weight: 600; }
QLabel#pp_folder { color: #8b8f99; }
QLabel#pp_stat { color: #c7cad2; }
QLabel#pp_meta { color: #8b8f99; }
QToolButton#pp_act { background: transparent; border: 1px solid #3a3d47;
                     border-radius: 6px; padding: 6px; }
QToolButton#pp_act:hover { background: #3a3d47; }
QToolButton#pp_act:pressed { background: #43464f; }
"""

_PANEL_WIDTH = 322


def _folder_line(path) -> str:
    if not path:
        return "Not saved yet"
    folder = str(Path(path).parent)
    home = str(Path.home())
    if folder.startswith(home):
        folder = "~" + folder[len(home):]
    return folder


def _humanize_age(seconds: float) -> str:
    minutes = seconds / 60
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{int(minutes)} min ago"
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)} h ago"
    days = hours / 24
    if days < 7:
        return f"{int(days)} d ago"
    if days < 30:
        return f"{int(days / 7)} wk ago"
    if days < 365:
        return f"{int(days / 30)} mo ago"
    return f"{int(days / 365)} yr ago"


def _flow_stats(window) -> dict:
    """A snapshot of the open project — counts for the panel and the meter.
    Node state is partitioned (frozen ▸ stale ▸ cached ▸ clean) so the four
    numbers add up to the node count and the meter segments tile a full bar."""
    engine = window.engine
    graph, cache = engine.graph, engine.cache
    nodes = list(graph.nodes.values())
    frozen = stale = cached = clean = 0
    for n in nodes:
        if n.frozen:
            frozen += 1
        elif n.dirty:
            stale += 1
        elif cache.has(n.id):
            cached += 1
        else:
            clean += 1
    return {
        "nodes": len(nodes), "wires": len(graph.connections),
        "links": len(graph.links), "frames": len(graph.frames),
        "cached": cached, "stale": stale, "frozen": frozen, "clean": clean,
        "memory": cache.total_bytes(),
    }


class _FlowMeter(QWidget):
    """A 6px rounded bar whose segments are the project's nodes by state —
    green cached, grey clean, amber stale, blue frozen. Empty track when
    there are no nodes."""

    _ORDER = ("cached", "clean", "stale", "frozen")

    def __init__(self, stats: dict, parent=None) -> None:
        super().__init__(parent)
        self._stats = stats
        self.setFixedHeight(6)
        self.setMinimumWidth(120)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(0, 0, self.width(), self.height())
        radius = r.height() / 2
        track = QPainterPath()
        track.addRoundedRect(r, radius, radius)
        p.fillPath(track, QColor("#1c1d23"))
        total = sum(self._stats.get(k, 0) for k in self._ORDER)
        if total <= 0:
            return
        p.setClipPath(track)
        x = 0.0
        for key in self._ORDER:
            value = self._stats.get(key, 0)
            if not value:
                continue
            seg = r.width() * value / total
            p.fillRect(QRectF(x, 0, seg + 0.6, r.height()), _STATE_COLOURS[key])
            x += seg


class _ProjectPanel(QWidget):
    """The header of the project switcher: the open workflow's tile and path,
    a row of icon buttons for Save / Save As / Export / New / Open, and a
    compact readout of the flow — node and wire counts, what is cached or
    stale, the file's size on disk and when it was last saved."""

    def __init__(self, window, on_action, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("project_panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_PANEL_QSS)
        # No fixed width: QMenu stretches an action widget to the menu's own
        # width, which the recent-workflow rows below make wider than this
        # card's natural size — so it should follow, not sit short of the edge.
        self.setMinimumWidth(_PANEL_WIDTH)
        self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)

        path = getattr(window, "_project_path", None)
        name = project_display_name(path)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(13, 12, 13, 13)
        outer.setSpacing(11)

        # -- identity ------------------------------------------------
        ident = QHBoxLayout()
        ident.setSpacing(10)
        tile = QLabel()
        tile.setPixmap(initials_pixmap(name, 38))
        ident.addWidget(tile, 0, Qt.AlignVCenter)
        id_col = QVBoxLayout()
        id_col.setSpacing(1)
        name_lbl = QLabel(name)
        name_lbl.setObjectName("pp_name")
        id_col.addWidget(name_lbl)
        self._folder_lbl = QLabel()
        self._folder_lbl.setObjectName("pp_folder")
        self._folder_lbl.setFont(_smaller(self._folder_lbl.font()))
        self._folder_lbl.setMinimumWidth(1)
        self._folder_text = _folder_line(path)
        self._elide_folder()
        id_col.addWidget(self._folder_lbl)
        ident.addLayout(id_col, 1)
        outer.addLayout(ident)

        # -- action buttons ----------------------------------------
        acts = QHBoxLayout()
        acts.setSpacing(6)
        for glyph, tip, action in (
                ("save", "Save", window.action_save),
                ("save_as", "Save As…", window.action_save_as),
                ("export", "Export Workflow…", window.action_export_workflow),
                ("new_doc", "New", window.action_new),
                ("folder", "Open…", window.action_open)):
            btn = QToolButton()
            btn.setObjectName("pp_act")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setIcon(frame_icon(glyph))
            btn.setIconSize(QSize(17, 17))
            key = action.shortcut().toString(QKeySequence.NativeText)
            btn.setToolTip(f"{tip}  ({key})" if key else tip)
            btn.clicked.connect(lambda _=False, a=action: on_action(a))
            acts.addWidget(btn)
        acts.addStretch(1)
        outer.addLayout(acts)

        # -- flow readout -----------------------------------------
        stats = _flow_stats(window)
        block = QVBoxLayout()
        block.setSpacing(4)
        block.addWidget(_FlowMeter(stats))

        counts = QLabel(self._counts_line(stats))
        counts.setObjectName("pp_stat")
        block.addWidget(counts)

        state = QLabel(self._state_line(stats))
        state.setObjectName("pp_stat")
        block.addWidget(state)

        meta = QLabel(self._meta_line(path, stats))
        meta.setObjectName("pp_meta")
        meta.setFont(_smaller(meta.font()))
        block.addWidget(meta)
        outer.addLayout(block)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide_folder()

    def _elide_folder(self) -> None:
        fm = QFontMetrics(self._folder_lbl.font())
        # panel margins (13+13) + tile (38) + row spacing (10) + a little slack
        avail = max(60, self.width() - 74)
        self._folder_lbl.setText(
            fm.elidedText(self._folder_text, Qt.ElideMiddle, avail))

    @staticmethod
    def _counts_line(s: dict) -> str:
        parts = [f"<b>{s['nodes']}</b> node{'' if s['nodes'] == 1 else 's'}",
                 f"{s['wires']} wire{'' if s['wires'] == 1 else 's'}"]
        if s["frames"]:
            parts.append(f"{s['frames']} frame{'' if s['frames'] == 1 else 's'}")
        if s["links"]:
            parts.append(f"{s['links']} link{'' if s['links'] == 1 else 's'}")
        return "  ·  ".join(parts)

    @staticmethod
    def _state_line(s: dict) -> str:
        def chip(key: str, label: str) -> str:
            return (f"<span style='color:{_STATE_COLOURS[key].name()}'>●</span> "
                    f"{s[key]} {label}")
        bits = [chip("cached", "cached")]
        if s["stale"]:
            bits.append(chip("stale", "stale"))
        if s["frozen"]:
            bits.append(chip("frozen", "frozen"))
        if s["clean"] and not s["stale"] and not s["frozen"]:
            bits.append(chip("clean", "uncached"))
        return "&nbsp;&nbsp; ".join(bits)

    @staticmethod
    def _meta_line(path, s: dict) -> str:
        parts = []
        if path and Path(path).exists():
            st = Path(path).stat()
            parts.append(f"{format_bytes(st.st_size)} on disk")
            parts.append(f"saved {_humanize_age(time.time() - st.st_mtime)}")
        else:
            parts.append("not saved yet")
        if s["memory"]:
            parts.append(f"{format_bytes(s['memory'])} in memory")
        return "  ·  ".join(parts)


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
        w = self._window
        panel = QWidgetAction(m)
        panel.setDefaultWidget(_ProjectPanel(w, self._panel_action))
        m.addAction(panel)

        favs = w._favorite_workflows_existing()
        if favs:
            self._add_workflow_section(m, "Favourites", favs)

        recent = [p for p in w._recent_files_existing() if p not in favs]
        if recent:
            self._add_workflow_section(m, "Recent workflows", recent)

    def _add_workflow_section(self, m: QMenu, title: str,
                              paths: list[str]) -> None:
        m.addSeparator()
        header = m.addAction(title)
        header.setEnabled(False)
        for p in paths:
            item = QWidgetAction(m)
            item.setDefaultWidget(_RecentRow(
                p, self._open_recent,
                is_fav=self._window.is_favorite_workflow(p),
                on_toggle_fav=self._toggle_favorite))
            m.addAction(item)

    def _toggle_favorite(self, path: str) -> bool:
        now = self._window.toggle_favorite_workflow(path)
        # Re-pop the menu so the row jumps between Favourites and Recent right
        # away — deferred, because clearing the menu deletes the very row whose
        # click handler we are inside.
        m = self._project_menu
        if m.isVisible():
            pos = m.pos()
            QTimer.singleShot(0, lambda: (m.hide(), m.popup(pos)))
        return now

    def _panel_action(self, action: QAction) -> None:
        self._project_menu.close()
        action.trigger()

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
