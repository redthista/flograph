"""The hover preview beside the visuals list: a small picture of what a
visual will look like once it is on the page.

The picture is not a sketch of the tile — it *is* one. The node is given a
real TileItem in a scene of its own, rendered to a pixmap, and thrown away.
That costs a widget build per hover (which is why it waits for the cursor
to settle), and buys a preview that can never drift from what dropping the
visual actually produces: same title bar, same chrome, same "Run the flow
to populate this tile" when nothing has run yet.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGraphicsScene, QLabel, QVBoxLayout, QWidget,
)

from flograph.core import Tile

#: How long the cursor has to rest on a row before the preview is built.
#: Long enough that running down the list with the mouse renders nothing.
HOVER_DELAY_MS = 550

#: The box the preview is drawn into, in logical pixels. Tiles are scaled
#: down to fit it and never up — a slider tile is small, and blowing it up
#: would only make it blurry.
MAX_SIZE = QSize(300, 240)

#: Shown while a Plotly chart is having its picture taken — see
#: `slow_to_draw`. The first snapshot of a session parses plotly.js, which
#: is not instant, and a popup that appears empty reads as a bug.
DRAWING = "Drawing the chart…"

_RUN_FIRST = "Run the flow to see this chart."
_NOT_A_CHART = "Web page — drag it onto the page to see it."
_NO_PICTURE = "This chart could not be drawn."
_NO_PREVIEW = "No preview available for this visual."


def slow_to_draw(node) -> bool:
    """Whether this node's preview is worth putting a "drawing…" note up
    for first. Only Plotly: its picture is taken by a real browser (the
    same one the reports use), and the first one of a session has 5 MB of
    JavaScript to parse before it can draw anything."""
    from ..canvas.node_item import card_kind
    return card_kind(node) == "webview"


def preview(graph, engine, node, max_size: QSize = MAX_SIZE,
            ratio: float = 1.0) -> "tuple[Optional[QPixmap], str]":
    """What to show for `node`: a picture, or a line of text saying why
    there isn't one. Never raises — a hover is not worth an exception.
    """
    from ..canvas.node_item import card_kind
    try:
        if card_kind(node) == "webview":
            return _plotly_pixmap(engine, node, max_size, ratio)
        pixmap = tile_pixmap(graph, engine, node, max_size, ratio)
        return (pixmap, "") if pixmap is not None else (None, _NO_PREVIEW)
    except Exception:
        return None, _NO_PREVIEW


def _plotly_pixmap(engine, node, max_size: QSize,
                   ratio: float) -> "tuple[Optional[QPixmap], str]":
    """A Plotly card's chart, drawn the way a report draws it.

    A webview tile is a Chromium page, so unlike every other kind this one
    cannot be previewed by building the tile: the widget paints
    asynchronously and a hover would get an empty white box. It goes
    through the report renderer's snapshot instead — the app's own embedded
    browser, asked for a PNG — which is the same picture the report pages
    put on paper, and is cached, so hovering the same chart twice draws it
    once.
    """
    from .tile_item import default_tile_port
    from ..report.render import plotly_image
    entry = engine.cache.get(node.id) if engine is not None else None
    port = default_tile_port(node)
    value = entry.outputs.get(port) if entry is not None and port else None
    # a Chart per Value node emits a list — its card shows the stack, and
    # one chart is enough to say what the stack looks like
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None:
        return None, _RUN_FIRST
    data = plotly_image(value, max_size.width(), False)
    if not isinstance(data, bytes):
        # None = not a Plotly figure at all (a Web View node's HTML); a
        # string = the renderer's own explanation, which is markdown meant
        # for a page rather than a line for a popup
        return None, _NOT_A_CHART if data is None else _NO_PICTURE
    image = QImage()
    if not image.loadFromData(data, "PNG") or image.isNull():
        return None, _NO_PICTURE
    ratio = max(1.0, min(4.0, ratio))
    box = max_size * ratio
    if image.width() > box.width() or image.height() > box.height():
        image = image.scaled(box, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(ratio)
    return pixmap, ""


def tile_pixmap(graph, engine, node, max_size: QSize = MAX_SIZE,
                ratio: float = 1.0) -> Optional[QPixmap]:
    """`node` as it would look placed on a dashboard page, or None if it
    cannot be drawn (anything that raises — a hover preview is never worth
    an exception reaching the user).

    `ratio` is the device pixel ratio to render at, so the preview is as
    sharp on a HiDPI screen as the tile it stands for.
    """
    from .tile_item import TileItem, default_tile_port, default_tile_size
    scene = QGraphicsScene()
    item = None
    try:
        width, height = default_tile_size(node)
        item = TileItem(Tile(id="preview", node_id=node.id,
                             port=default_tile_port(node),
                             rect=(0.0, 0.0, width, height)),
                        graph, engine)
        scene.addItem(item)
        source = item.boundingRect()
        if source.isEmpty():
            return None
        scale = min(max_size.width() / source.width(),
                    max_size.height() / source.height(), 1.0)
        ratio = max(1.0, min(4.0, ratio))
        pixmap = QPixmap(max(1, round(source.width() * scale * ratio)),
                         max(1, round(source.height() * scale * ratio)))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.TextAntialiasing)
        # Rendered through the scene rather than blitted: the tile is drawn
        # at the reduced size, so its text stays crisp instead of being a
        # shrunk bitmap of itself.
        scene.render(painter, QRectF(pixmap.rect()), source)
        painter.end()
        return pixmap
    except Exception:
        return None
    finally:
        if item is not None:
            # stop the timers first — a QMovie still delivering frames into
            # an item that is about to go is a crash, not a stale picture
            item.dispose()
            scene.removeItem(item)


class VisualPreviewPopup(QFrame):
    """The little window the picture appears in.

    A Qt.ToolTip window, so it floats over everything without taking focus
    away from the list the cursor is on and never turns up in the task
    switcher.
    """

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(
            "VisualPreviewPopup { background: #1e2024;"
            " border: 1px solid #3a3d46; border-radius: 4px; }"
            "QLabel { color: #e5e7eb; background: transparent; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(0)
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(MAX_SIZE.width())
        layout.addWidget(self._label)

    def show_pixmap(self, pixmap: QPixmap) -> None:
        self._label.setPixmap(pixmap)
        self.adjustSize()

    def show_message(self, text: str) -> None:
        self._label.setPixmap(QPixmap())
        self._label.setText(text)
        self.adjustSize()

    def move_onto_screen(self, top_left) -> None:
        """Place the popup at `top_left`, nudged back on screen if that
        would hang it off an edge — the visuals panel sits at the left of
        the page, but a narrow window can still leave no room to the right.
        """
        from PySide6.QtGui import QGuiApplication
        self.adjustSize()
        screen = (QGuiApplication.screenAt(top_left)
                  or QGuiApplication.primaryScreen())
        if screen is not None:
            area = screen.availableGeometry()
            size = self.size()
            x = min(top_left.x(), area.right() - size.width())
            x = max(area.left(), x)
            y = min(top_left.y(), area.bottom() - size.height())
            y = max(area.top(), y)
            top_left.setX(int(x))
            top_left.setY(int(y))
        self.move(top_left)
