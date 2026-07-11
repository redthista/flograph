"""TileItem: one visual element placed on a dashboard page — a live view of
a node's cached output (figure, table, plotly chart) or an Action Button.

The content widget is persistent: refresh_content() pushes new data into it
rather than rebuilding, so re-runs never recreate webviews or table views.
A tile whose node was deleted shows a placeholder instead of vanishing —
undoing the delete brings the content back."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsObject, QGraphicsProxyWidget, QLabel,
    QTableView, QVBoxLayout, QWidget,
)

from flopy.core import Tile

from .. import theme
from ..canvas.node_item import (
    BUTTON_H, BUTTON_W, FIGURE_TYPES, PLOTLY_TYPE, TABLE_VIEWER_TYPES,
)

BUTTON_TYPE = "flopy.util.action_button"
TILE_ABLE_TYPES = FIGURE_TYPES | TABLE_VIEWER_TYPES | {PLOTLY_TYPE,
                                                       BUTTON_TYPE}

TITLE_H = 24.0
HANDLE = 14.0
CLOSE_BTN = 16.0
MIN_W, MIN_H = 160.0, 90.0

RUN_PROMPT = "Run the flow to populate this tile."
MISSING_NODE = ("The node behind this tile was deleted.\n"
                "Select the tile and press Delete to remove it.")


def default_tile_port(type_id: str) -> Optional[str]:
    """The output port a tile of this node type renders."""
    if type_id in FIGURE_TYPES or type_id == PLOTLY_TYPE:
        return "figure"
    if type_id == "flopy.viz.table_spec":
        return "spec"
    if type_id in TABLE_VIEWER_TYPES:
        return "table"
    return None  # action buttons have no ports


def default_tile_size(type_id: str) -> tuple[float, float]:
    """Buttons land at their canvas size; everything else gets a card."""
    if type_id == BUTTON_TYPE:
        return (BUTTON_W, BUTTON_H)
    return (420.0, 320.0)


class TileItem(QGraphicsObject):
    def __init__(self, tile: Tile, graph, engine) -> None:
        super().__init__()
        self.tile = tile
        self._graph = graph
        self._engine = engine
        self.setFlags(QGraphicsItem.ItemIsMovable
                      | QGraphicsItem.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        x, y, w, h = tile.rect
        self.setPos(x, y)
        self._size = (w, h)
        self._resizing = False
        self._press_scene_pos = QPointF()
        self._press_pos = QPointF()
        self._press_size = self._size
        self._close_pressed = False
        self._hover_close = False

        # persistent content widgets — at most one of these exists, by kind
        # (button tiles have none: the button face is painted, like on the
        # modeling canvas)
        self._figure_view = None
        self._plotly_widget = None
        self._table_view = None
        self._generic_host: Optional[QWidget] = None
        self._generic_child: Optional[QWidget] = None

        self._build_host()
        self.refresh_content()

    # ------------------------------------------------------------- geometry

    def sync_from_model(self) -> None:
        x, y, w, h = self.tile.rect
        self.prepareGeometryChange()
        if (self.pos().x(), self.pos().y()) != (x, y):
            self.setPos(x, y)
        self._size = (w, h)
        self._layout_proxy()
        self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(-1, -1, self._size[0] + 2, self._size[1] + 2)

    def _handle_rect(self) -> QRectF:
        w, h = self._size
        return QRectF(w - HANDLE, h - HANDLE, HANDLE, HANDLE)

    def _close_rect(self) -> QRectF:
        w, _h = self._size
        return QRectF(w - CLOSE_BTN - 5.0, (TITLE_H - CLOSE_BTN) / 2,
                      CLOSE_BTN, CLOSE_BTN)

    def _content_rect(self) -> QRectF:
        w, h = self._size
        return QRectF(1, TITLE_H, w - 2,
                      max(0.0, h - TITLE_H - HANDLE / 2 - 1))

    def _layout_proxy(self) -> None:
        self._proxy.setGeometry(self._content_rect())

    # -------------------------------------------------------------- content

    def _node(self):
        return self._graph.nodes.get(self.tile.node_id)

    def _kind(self) -> str:
        node = self._node()
        if node is None:
            return "missing"
        type_id = node.type_id
        if type_id in FIGURE_TYPES:
            return "figure"
        if type_id == PLOTLY_TYPE:
            return "plotly"
        if type_id in TABLE_VIEWER_TYPES:
            return "table"
        if type_id == BUTTON_TYPE:
            return "button"
        return "generic"

    def _build_host(self) -> None:
        host = QWidget()
        host.setStyleSheet(f"background: {theme.NODE_BODY.name()};")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        placeholder = QLabel(RUN_PROMPT)
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setWordWrap(True)
        placeholder.setStyleSheet("color: #6b7280;")
        layout.addWidget(placeholder, 1)
        self._placeholder = placeholder
        self._host_layout = layout

        self._proxy = QGraphicsProxyWidget(self)
        self._proxy.setWidget(host)
        self._layout_proxy()

    def _content_widget(self) -> Optional[QWidget]:
        for widget in (self._figure_view, self._plotly_widget,
                       self._table_view, self._generic_host):
            if widget is not None:
                return widget
        return None

    def _ensure_content_widget(self, kind: str) -> Optional[QWidget]:
        existing = self._content_widget()
        if existing is not None:
            return existing
        if kind == "figure":
            from ..inspector.figure_view import FigureView
            widget = FigureView(dialog_parent=self._dialog_parent_widget)
            self._figure_view = widget
        elif kind == "plotly":
            from ..inspector.plotly_view import PlotlyView
            widget = PlotlyView()
            self._plotly_widget = widget
        elif kind == "table":
            widget = QTableView()
            widget.setStyleSheet(
                f"QTableView {{ background: {theme.NODE_BODY.name()};"
                f" color: {theme.NODE_TEXT.name()}; border: none;"
                f" gridline-color: {theme.NODE_BORDER.name()};"
                f" font-size: 8.5pt; }}"
                f"QHeaderView::section {{"
                f" background: {theme.NODE_HEADER.name()};"
                f" color: {theme.NODE_SUBTEXT.name()};"
                f" border: 1px solid {theme.NODE_BORDER.name()};"
                f" padding: 2px; }}")
            widget.setSortingEnabled(True)
            self._table_view = widget
        elif kind == "generic":
            widget = QWidget()
            QVBoxLayout(widget).setContentsMargins(0, 0, 0, 0)
            self._generic_host = widget
        else:
            return None
        widget.hide()
        self._host_layout.addWidget(widget, 1)
        return widget

    def _dialog_parent_widget(self) -> Optional[QWidget]:
        scene = self.scene()
        views = scene.views() if scene is not None else []
        return views[0].window() if views else None

    def _fire_button(self) -> None:
        scene = self.scene()
        if scene is not None:
            scene.button_fired.emit(self.tile.node_id)

    def refresh_content(self) -> None:
        """Pull the node's cached output into the content widget — called on
        build, on node success/failure, and when the node is (un)deleted."""
        kind = self._kind()
        node = self._node()
        if kind == "missing":
            widget = self._content_widget()
            if widget is not None:
                widget.hide()
            self._proxy.show()  # a deleted button tile needs its placeholder
            self._placeholder.setText(MISSING_NODE)
            self._placeholder.show()
            self.update()
            return

        if kind == "button":
            # no widget at all: the button face is painted in paint(), and
            # clicks fire in mousePressEvent — exactly like the canvas node
            self._proxy.hide()
            self.setToolTip("Click to run · right-click to select, then "
                            "drag to move or press Delete to remove")
            self.update()
            return

        self._proxy.show()
        widget = self._ensure_content_widget(kind)

        entry = self._engine.cache.get(self.tile.node_id)
        value = None
        if entry is not None and self.tile.port:
            value = entry.outputs.get(self.tile.port)

        if kind == "figure":
            if value is None:
                self._figure_view.clear()
                widget.hide()
                self._placeholder.setText(RUN_PROMPT)
                self._placeholder.show()
            else:
                self._placeholder.hide()
                self.refresh_render_ratio()
                self._figure_view.set_figure(value)
                widget.show()
        elif kind == "plotly":
            self._placeholder.hide()
            widget.show()
            self._plotly_widget.set_figure(value)
        elif kind == "table":
            import sys
            pd = sys.modules.get("pandas")
            if value is None or pd is None or not isinstance(value, pd.DataFrame):
                self._table_view.setModel(None)
                widget.hide()
                self._placeholder.setText(RUN_PROMPT)
                self._placeholder.show()
            else:
                from ..inspector.pandas_model import PandasModel
                self._table_view.setModel(
                    PandasModel(value, parent=self._table_view))
                self._placeholder.hide()
                widget.show()
        else:  # generic: rebuild via the inspector's dispatcher
            if self._generic_child is not None:
                self._generic_child.setParent(None)
                self._generic_child.deleteLater()
                self._generic_child = None
            if entry is None:
                widget.hide()
                self._placeholder.setText(RUN_PROMPT)
                self._placeholder.show()
            else:
                from ..inspector.view_for import view_for
                child = view_for(value)
                self._generic_host.layout().addWidget(child)
                self._generic_child = child
                self._placeholder.hide()
                widget.show()
        self.update()

    def refresh_render_ratio(self) -> None:
        """Keep embedded matplotlib figures crisp under view zoom and DPR —
        called by the scene when the view's zoom settles."""
        if self._figure_view is None:
            return
        ratio = 1.0
        scene = self.scene()
        views = scene.views() if scene is not None else []
        if views:
            ratio *= (views[0].viewport().devicePixelRatioF() or 1.0)
            ratio *= views[0].transform().m11()
        self._figure_view.set_render_ratio(min(8.0, max(1.0, ratio)))

    # ------------------------------------------------------------- painting

    def _is_stale(self) -> bool:
        """Dirty node while the tile still shows the previous output — the
        engine evicts the cache on dirtying, but our content widgets hold
        the last-rendered data by reference until the next run."""
        node = self._node()
        if node is None or not node.dirty or self._kind() == "button":
            return False
        widget = self._content_widget()
        return widget is not None and not widget.isHidden()

    def _title(self) -> str:
        node = self._node()
        return node.label if node is not None else "(deleted node)"

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if self._kind() == "button":
            self._paint_button(painter)
            return
        w, h = self._size
        body = QRectF(0, 0, w, h)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(theme.NODE_BODY))
        painter.setPen(QPen(theme.SELECTION_OUTLINE if self.isSelected()
                            else theme.NODE_BORDER, 1.5))
        painter.drawRoundedRect(body, 6, 6)

        painter.setBrush(QBrush(theme.NODE_HEADER))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(0, 0, w, TITLE_H), 6, 6)

        painter.setPen(QPen(theme.NODE_TEXT))
        font = painter.font()
        font.setBold(True)
        font.setPointSizeF(9.0)
        painter.setFont(font)
        stale = self._is_stale()
        stale_w = 44.0 if stale else 0.0
        painter.drawText(QRectF(10, 0, w - 20 - CLOSE_BTN - stale_w, TITLE_H),
                         Qt.AlignVCenter | Qt.AlignLeft, self._title())
        if stale:
            painter.setPen(QPen(QColor("#eab308")))
            small = painter.font()
            small.setPointSizeF(7.5)
            painter.setFont(small)
            painter.drawText(
                QRectF(0, 0, w - CLOSE_BTN - 10, TITLE_H),
                Qt.AlignVCenter | Qt.AlignRight, "STALE")

        btn = self._close_rect()
        chip = QColor(theme.NODE_BORDER)
        chip.setAlphaF(0.9 if self._hover_close else 0.4)
        painter.setBrush(QBrush(chip))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(btn, 4, 4)
        painter.setPen(QPen(theme.NODE_SUBTEXT, 1.6))
        cx, cy = btn.center().x(), btn.center().y()
        painter.drawLine(QPointF(cx - 3.5, cy - 3.5), QPointF(cx + 3.5, cy + 3.5))
        painter.drawLine(QPointF(cx - 3.5, cy + 3.5), QPointF(cx + 3.5, cy - 3.5))

        painter.setPen(QPen(theme.NODE_SUBTEXT, 1.2))
        hr = self._handle_rect()
        for i in (4.0, 8.0, 12.0):
            painter.drawLine(QPointF(hr.right() - i, hr.bottom() - 2),
                             QPointF(hr.right() - 2, hr.bottom() - i))

    def _paint_button(self, painter: QPainter) -> None:
        """The Action Button face, identical to NodeItem._paint_button — a
        button tile IS the button, not a card around one."""
        w, h = self._size
        rect = QRectF(0, 0, w, h)
        painter.setRenderHint(QPainter.Antialiasing)
        body = QPainterPath()
        body.addRoundedRect(rect, 10, 10)
        painter.fillPath(body, theme.BUTTON_ACCENT)
        outline = QPen(theme.SELECTION_OUTLINE if self.isSelected()
                       else theme.NODE_BORDER,
                       2.0 if self.isSelected() else 1.2)
        painter.setPen(outline)
        painter.drawPath(body)

        painter.setPen(QPen(QColor("#ffffff")))
        font = painter.font()
        font.setBold(True)
        font.setPointSizeF(9.5)
        painter.setFont(font)
        painter.drawText(rect.adjusted(8, 4, -8, -4),
                         Qt.AlignCenter | Qt.TextWordWrap,
                         f"▶  {self._title()}")

    # ------------------------------------------------------------ behaviour

    def hoverMoveEvent(self, event) -> None:
        if self._kind() == "button":
            super().hoverMoveEvent(event)
            return
        hovering = self._close_rect().contains(event.pos())
        if hovering != self._hover_close:
            self._hover_close = hovering
            self.setCursor(Qt.PointingHandCursor if hovering
                           else Qt.ArrowCursor)
            self.setToolTip("Remove this tile" if hovering else "")
            self.update()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        if self._hover_close:
            self._hover_close = False
            self.unsetCursor()
            self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if self._kind() == "button":
            if event.button() == Qt.LeftButton and not self.isSelected():
                # unselected: a plain left-click fires the action instead of
                # selecting/dragging — same semantics as the canvas button
                self._fire_button()
                event.accept()
                return
            if event.button() == Qt.RightButton:
                # no context menu on dashboards: right-click selects, after
                # which left-drag moves and Delete removes
                self.setSelected(True)
                event.accept()
                return
        elif self._close_rect().contains(event.pos()):
            # button semantics: swallow the drag, act on release-inside
            self._close_pressed = True
            event.accept()
            return
        self._press_scene_pos = event.scenePos()
        self._press_pos = self.pos()
        self._press_size = self._size
        if (self._kind() != "button"  # buttons are fixed-size, like on canvas
                and self._handle_rect().contains(event.pos())):
            self._resizing = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._close_pressed:
            event.accept()
            return
        if self._resizing:
            delta = event.scenePos() - self._press_scene_pos
            self.prepareGeometryChange()
            self._size = (max(MIN_W, self._press_size[0] + delta.x()),
                          max(MIN_H, self._press_size[1] + delta.y()))
            self._layout_proxy()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        scene = self.scene()
        if self._close_pressed:
            self._close_pressed = False
            if self._close_rect().contains(event.pos()) and scene is not None:
                scene.remove_tile(self.tile.id)
            event.accept()
            return
        if self._resizing:
            self._resizing = False
            if scene is not None and self._size != self._press_size:
                scene.push_tile_rect(
                    self.tile.id,
                    (self._press_pos.x(), self._press_pos.y(),
                     *self._press_size),
                    (self.pos().x(), self.pos().y(), *self._size))
            event.accept()
            return
        super().mouseReleaseEvent(event)
        if self.pos() != self._press_pos and scene is not None:
            scene.push_tile_rect(
                self.tile.id,
                (self._press_pos.x(), self._press_pos.y(), *self._press_size),
                (self.pos().x(), self.pos().y(), *self._size))
