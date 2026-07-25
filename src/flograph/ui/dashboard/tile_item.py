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

from flograph.core import Tile

from .. import theme
from ..canvas.grid import (
    EDGE_MARGIN, grid_step, snap, snap_point, snapping_active,
)
from ..canvas.node_item import (
    BUTTON_H, BUTTON_W, card_kind, kpi_caption, kpi_text,
)
from ..slicer_list import SlicerListWidget, SlicerToolbar, selected_param_values

# card kinds that can be placed on a dashboard page
TILE_ABLE_KINDS = frozenset({
    "webview", "figure", "table_viewer", "kpi", "slicer", "button", "grid"})


def is_tile_able(node) -> bool:
    """Whether a node can be placed on a dashboard page as a tile."""
    return card_kind(node) in TILE_ABLE_KINDS

TITLE_H = 24.0
HANDLE = 14.0
MIN_W, MIN_H = 160.0, 90.0
FS_BTN = 16.0  # the maximize/restore glyph box at the right of the title bar

# Kinds with nothing to enlarge: an Action Button is a fixed-size trigger,
# and a tile whose node was deleted only has the placeholder to show.
NO_FULLSCREEN_KINDS = frozenset({"button", "missing"})

RUN_PROMPT = "Run the flow to populate this tile."
MISSING_NODE = ("The node behind this tile was deleted.\n"
                "Select the tile and press Delete to remove it.")


def default_tile_port(node) -> Optional[str]:
    """The output port a tile of this node renders — its first declared output
    ("figure"/"table"/"spec"/"value"/"view", per the node's own ports)."""
    if card_kind(node) in ("webview", "figure", "table_viewer", "kpi", "grid"):
        return node.spec.outputs[0].name if node.spec.outputs else None
    # action buttons have no ports; slicer tiles show upstream options,
    # not their own (already filtered) output
    return None


def default_tile_size(node) -> tuple[float, float]:
    """Buttons land at their canvas size; everything else gets a card."""
    kind = card_kind(node)
    if kind == "button":
        return (BUTTON_W, BUTTON_H)
    if kind == "kpi":
        return (220.0, 120.0)
    if kind == "slicer":
        return (200.0, 260.0)
    return (420.0, 320.0)


class TileItem(QGraphicsObject):
    def __init__(self, tile: Tile, graph, engine) -> None:
        super().__init__()
        self.tile = tile
        self._graph = graph
        self._engine = engine
        self.setFlags(QGraphicsItem.ItemIsMovable
                      | QGraphicsItem.ItemIsSelectable
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        # set before setPos — ItemSendsGeometryChanges makes setPos fire
        # itemChange, which reads _dragging
        self._resizing = False
        self._resize_edge = "corner"  # which edge/corner the drag grabbed
        self._dragging = False  # a title-bar move is in progress (snap gate)
        self._move_suppressed = False  # body press cleared ItemIsMovable
        # Maximized over the whole page: geometry comes from the view, not
        # from the model, and no move/resize is possible until it's cleared.
        self._fullscreen = False
        self._fs_hover = False  # cursor is over the maximize/restore glyph
        # A press that toggled fullscreen owns the rest of its gesture. The
        # toggle moves and resizes the tile out from under the cursor, so the
        # move/release that follow must not be read as a drag of it.
        self._fs_gesture = False
        x, y, w, h = tile.rect
        self.setPos(x, y)
        self._size = (w, h)
        self._press_scene_pos = QPointF()
        self._press_pos = QPointF()
        self._press_size = self._size

        # persistent content widgets — at most one of these exists, by kind
        # (button tiles have none: the button face is painted, like on the
        # modeling canvas)
        self._figure_view = None
        self._plotly_widget = None
        self._table_view = None
        self._slicer_widget: Optional[SlicerListWidget] = None
        self._slicer_toolbar: Optional[SlicerToolbar] = None
        self._generic_host: Optional[QWidget] = None
        self._generic_child: Optional[QWidget] = None
        self._kpi_value: object = None  # kpi tiles paint, they hold no widget
        self._kpi_has_value = False

        self._build_host()
        self.refresh_content()

    # ------------------------------------------------------------- geometry

    def sync_from_model(self) -> None:
        if self._fullscreen:
            # the view owns the geometry while maximized; the stored rect is
            # picked back up on the way out
            return
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

    def _fs_button_rect(self) -> QRectF:
        w, _ = self._size
        return QRectF(w - FS_BTN - 6.0, (TITLE_H - FS_BTN) / 2.0,
                      FS_BTN, FS_BTN)

    def _content_rect(self) -> QRectF:
        w, h = self._size
        return QRectF(1, TITLE_H, w - 2,
                      max(0.0, h - TITLE_H - HANDLE / 2 - 1))

    def _layout_proxy(self) -> None:
        self._proxy.setGeometry(self._content_rect())

    # ----------------------------------------------------------- fullscreen

    @property
    def is_fullscreen(self) -> bool:
        return self._fullscreen

    def can_fullscreen(self) -> bool:
        # already maximized always counts: deleting the node behind a
        # maximized tile must not strand it without a restore button
        return self._fullscreen or self._kind() not in NO_FULLSCREEN_KINDS

    def set_fullscreen_rect(self, rect: QRectF) -> None:
        """Pin the tile to an exact scene rect — the view calls this on the
        way into fullscreen and on every resize after, so the embedded chart
        or table grows with the window. Never touches the stored rect: this
        is view state, not something to save or undo."""
        self._fullscreen = True
        self._move_suppressed = False
        self._dragging = False
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.prepareGeometryChange()
        self.setPos(rect.topLeft())
        self._size = (max(MIN_W, rect.width()), max(MIN_H, rect.height()))
        self._layout_proxy()
        self.refresh_render_ratio()
        self.update()

    def clear_fullscreen(self) -> None:
        """Drop back to the geometry the model holds."""
        if not self._fullscreen:
            return
        self._fullscreen = False
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.sync_from_model()
        self.refresh_render_ratio()

    def _request_fullscreen(self) -> None:
        scene = self.scene()
        if scene is not None and self.can_fullscreen():
            scene.toggle_fullscreen(self.tile.id)

    # -------------------------------------------------------------- content

    def _node(self):
        return self._graph.nodes.get(self.tile.node_id)

    def _kind(self) -> str:
        node = self._node()
        if node is None:
            return "missing"
        # map the node's card kind to this tile's internal widget names
        return {
            "webview": "plotly",
            "figure": "figure",
            "table_viewer": "table",
            "grid": "table",
            "button": "button",
            "kpi": "kpi",
            "slicer": "slicer",
        }.get(card_kind(node), "generic")

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
                       self._table_view, self._slicer_widget,
                       self._generic_host):
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
        elif kind == "slicer":
            widget = SlicerListWidget()
            widget.selection_committed.connect(self._commit_slicer_selection)
            self._slicer_widget = widget
            toolbar = SlicerToolbar(widget)
            toolbar.hide()
            self._host_layout.addWidget(toolbar)
            self._slicer_toolbar = toolbar
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

    def _commit_slicer_selection(self, new_value: str) -> None:
        """A tick changed on a slicer tile: commit the selection (dirties
        the subgraph) and ask the window to re-run the visuals downstream —
        same flow as the slicer's canvas card."""
        scene = self.scene()
        node = self._node()
        if scene is None or node is None:
            return
        if new_value != node.params.get("selected", ""):
            from ..commands import SetParamCommand
            scene.undo_stack.push(SetParamCommand(
                self._graph, node.id, "selected", new_value))
        scene.slicer_changed.emit(node.id)

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

        if kind == "kpi":
            # painted like the button face: crisp vector text, no widget
            entry = self._engine.cache.get(self.tile.node_id)
            self._kpi_has_value = entry is not None
            self._kpi_value = entry.outputs.get("value") if entry else None
            if self._kpi_has_value:
                self._proxy.hide()
            else:
                self._proxy.show()
                self._placeholder.setText(RUN_PROMPT)
                self._placeholder.show()
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
        elif kind == "slicer":
            from flograph.engine.introspect import slicer_options
            options = slicer_options(self._graph, self._engine.cache,
                                     self.tile.node_id)
            if options is None:
                widget.hide()
                if self._slicer_toolbar is not None:
                    self._slicer_toolbar.hide()
                self._placeholder.setText(RUN_PROMPT)
                self._placeholder.show()
            else:
                mode = str(node.params.get("mode", "multi") or "multi")
                self._slicer_widget.set_mode(mode)
                self._slicer_widget.set_options(
                    options,
                    set(selected_param_values(
                        node.params.get("selected", ""))))
                if self._slicer_toolbar is not None:
                    self._slicer_toolbar.set_mode(mode)
                    self._slicer_toolbar.refresh_summary()
                    self._slicer_toolbar.show()
                self._placeholder.hide()
                widget.show()
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

    def on_param_changed(self) -> None:
        """Params drive the painted caption/format of kpi tiles and the tick
        states of slicer tiles (properties panel edits, undo) — keep those
        live without rebuilding anything. Other tile kinds only re-render on
        runs."""
        kind = self._kind()
        node = self._node()
        if kind == "kpi":
            self.update()
        elif kind == "slicer" and self._slicer_widget is not None \
                and not self._slicer_widget.isHidden() and node is not None:
            mode = str(node.params.get("mode", "multi") or "multi")
            self._slicer_widget.set_mode(mode)
            if self._slicer_toolbar is not None:
                self._slicer_toolbar.set_mode(mode)
            self._slicer_widget.sync_checks(
                set(selected_param_values(node.params.get("selected", ""))))
            if self._slicer_toolbar is not None:
                self._slicer_toolbar.refresh_summary()

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
        if self._kind() == "kpi":  # painted, not widget-backed
            return self._kpi_has_value
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
        glyph_w = FS_BTN + 8.0 if self.can_fullscreen() else 0.0
        painter.drawText(QRectF(10, 0, w - 20 - stale_w - glyph_w, TITLE_H),
                         Qt.AlignVCenter | Qt.AlignLeft, self._title())
        if stale:
            painter.setPen(QPen(QColor("#eab308")))
            small = painter.font()
            small.setPointSizeF(7.5)
            painter.setFont(small)
            painter.drawText(
                QRectF(0, 0, w - 10 - glyph_w, TITLE_H),
                Qt.AlignVCenter | Qt.AlignRight, "STALE")
        if self.can_fullscreen():
            self._paint_fullscreen_glyph(painter)

        painter.setPen(QPen(theme.NODE_SUBTEXT, 1.2))
        hr = self._handle_rect()
        for i in (4.0, 8.0, 12.0):
            painter.drawLine(QPointF(hr.right() - i, hr.bottom() - 2),
                             QPointF(hr.right() - 2, hr.bottom() - i))

        if self._kind() == "kpi" and self._kpi_has_value:
            self._paint_kpi_value(painter)

    def _paint_fullscreen_glyph(self, painter: QPainter) -> None:
        """Four corner brackets, like a video player's fullscreen toggle:
        drawn on the outer box to maximize, on a smaller inner one to
        restore."""
        box = self._fs_button_rect().adjusted(2, 2, -2, -2)
        if self._fullscreen:
            box = box.adjusted(2, 2, -2, -2)
        # shorter arms on the smaller box, or the four brackets close up
        # into a plain square
        arm = box.width() / (3.6 if self._fullscreen else 2.6)
        painter.setPen(QPen(theme.NODE_TEXT if self._fs_hover
                            else theme.NODE_SUBTEXT, 1.3))
        for corner, sx, sy in ((box.topLeft(), 1, 1),
                               (box.topRight(), -1, 1),
                               (box.bottomRight(), -1, -1),
                               (box.bottomLeft(), 1, -1)):
            painter.drawLine(corner,
                             QPointF(corner.x() + sx * arm, corner.y()))
            painter.drawLine(corner,
                             QPointF(corner.x(), corner.y() + sy * arm))

    def _paint_kpi_value(self, painter: QPainter) -> None:
        """The KPI number and caption, painted like the canvas Card body —
        vector text stays crisp at every zoom, no proxy widget needed."""
        node = self._node()
        rect = self._content_rect()
        avail = rect.adjusted(8, 2, -8, -20)
        text = kpi_text(self._kpi_value,
                        str(node.params.get("format", "") or ""))
        size = min(avail.height() * 0.62,
                   avail.width() / (0.62 * max(1, len(text))))
        font = painter.font()
        font.setBold(True)
        font.setPointSizeF(max(9.0, size))
        painter.setFont(font)
        painter.setPen(QPen(theme.NODE_TEXT))
        painter.drawText(avail, Qt.AlignCenter, text)

        painter.setPen(QPen(theme.NODE_SUBTEXT))
        font = painter.font()
        font.setBold(False)
        font.setPointSizeF(8.0)
        painter.setFont(font)
        caption = painter.fontMetrics().elidedText(
            kpi_caption(node.params), Qt.ElideRight, int(rect.width() - 16))
        painter.drawText(
            QRectF(rect.left() + 8, rect.bottom() - 18,
                   rect.width() - 16, 16),
            Qt.AlignHCenter | Qt.AlignVCenter, caption)

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

    def _edge_at(self, pos: QPointF) -> Optional[str]:
        """Which resize edge/corner (if any) a point grabs: "right", "bottom",
        "corner", or None. Buttons are fixed-size and never resize; a
        maximized tile is sized by the viewport, not by dragging."""
        if self._kind() == "button" or self._fullscreen:
            return None
        w, h = self._size
        near_right = w - EDGE_MARGIN <= pos.x() <= w + EDGE_MARGIN
        near_bottom = h - EDGE_MARGIN <= pos.y() <= h + EDGE_MARGIN
        within_h = -EDGE_MARGIN <= pos.y() <= h + EDGE_MARGIN
        within_w = -EDGE_MARGIN <= pos.x() <= w + EDGE_MARGIN
        if self._handle_rect().contains(pos) or (near_right and near_bottom):
            return "corner"
        if near_right and within_h:
            return "right"
        if near_bottom and within_w:
            return "bottom"
        return None

    def _over_fs_button(self, pos: QPointF) -> bool:
        return self.can_fullscreen() and self._fs_button_rect().contains(pos)

    def _apply_edge_cursor(self, pos: QPointF) -> None:
        edge = self._edge_at(pos)
        if self._over_fs_button(pos):
            self.setCursor(Qt.PointingHandCursor)
        elif edge == "corner":
            self.setCursor(Qt.SizeFDiagCursor)
        elif edge == "right":
            self.setCursor(Qt.SizeHorCursor)
        elif edge == "bottom":
            self.setCursor(Qt.SizeVerCursor)
        elif pos.y() < TITLE_H and not self._fullscreen:
            self.setCursor(Qt.SizeAllCursor)  # the title drag bar
        else:
            self.setCursor(Qt.ArrowCursor)

    def hoverMoveEvent(self, event) -> None:
        if self._kind() == "button":
            super().hoverMoveEvent(event)
            return
        self._set_fs_hover(self._over_fs_button(event.pos()))
        self._apply_edge_cursor(event.pos())
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._set_fs_hover(False)
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def _set_fs_hover(self, hovered: bool) -> None:
        if hovered == self._fs_hover:
            return
        self._fs_hover = hovered
        self.setToolTip(("Restore (Esc)" if self._fullscreen
                         else "Maximize to fill the page") if hovered else "")
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self._dragging \
                and snapping_active(self.scene()):
            step = grid_step(self.scene())
            x, y = snap_point(value.x(), value.y(), step)
            return QPointF(x, y)
        return super().itemChange(change, value)

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
        if event.button() == Qt.LeftButton and self._over_fs_button(event.pos()):
            self._fs_gesture = True
            self._press_pos = self.pos()
            self._press_size = self._size
            self._request_fullscreen()
            event.accept()
            return
        self._press_scene_pos = event.scenePos()
        self._press_pos = self.pos()
        self._press_size = self._size
        edge = (self._edge_at(event.pos())
                if event.button() == Qt.LeftButton else None)
        if edge is not None:  # buttons return None (fixed-size, like on canvas)
            self._resizing = True
            self._resize_edge = edge
            event.accept()
            return
        if event.button() == Qt.LeftButton and not self._fullscreen:
            # Only the title bar starts a move; a press on the body just
            # selects. Buttons have no title bar, so they drag whole-body.
            if self._kind() != "button" and event.pos().y() >= TITLE_H:
                self._move_suppressed = True
                self.setFlag(QGraphicsItem.ItemIsMovable, False)
            else:
                self._dragging = True
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._fs_gesture:
            # the toggle already re-enabled ItemIsMovable; without this, hand
            # drift before the button comes back up drags the restored tile
            event.accept()
            return
        if self._resizing:
            edge = self._resize_edge
            width, height = self._size
            delta = event.scenePos() - self._press_scene_pos
            snapping = snapping_active(self.scene(), event.modifiers())
            step = grid_step(self.scene())
            if edge in ("right", "corner"):
                width = self._press_size[0] + delta.x()
                if snapping:
                    width = snap(width, step)
                width = max(MIN_W, width)
            if edge in ("bottom", "corner"):
                height = self._press_size[1] + delta.y()
                if snapping:
                    height = snap(height, step)
                height = max(MIN_H, height)
            self.prepareGeometryChange()
            self._size = (width, height)
            self._layout_proxy()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        """Double-clicking the title bar maximizes/restores, the way a window
        title bar does. The body belongs to the embedded widget (the proxy
        sits on top of it), so its double-clicks never reach us."""
        if event.button() == Qt.LeftButton and self.can_fullscreen() \
                and event.pos().y() < TITLE_H:
            # same gesture ownership as the button: the release that follows
            # a double-click must not push the toggled geometry as a move
            self._fs_gesture = True
            self._press_pos = self.pos()
            self._press_size = self._size
            self._request_fullscreen()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        scene = self.scene()
        if self._fs_gesture:
            # ends the toggle gesture, pushing nothing: the geometry either
            # side of it is the view's doing, not a drag
            self._fs_gesture = False
            self._resizing = False
            self._dragging = False
            event.accept()
            return
        if self._fullscreen:
            # geometry is view-owned while maximized — never push a rect
            self._resizing = False
            super().mouseReleaseEvent(event)
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
        if self._move_suppressed:
            self._move_suppressed = False
            self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self._dragging = False
        super().mouseReleaseEvent(event)
        if self.pos() != self._press_pos and scene is not None:
            scene.push_tile_rect(
                self.tile.id,
                (self._press_pos.x(), self._press_pos.y(), *self._press_size),
                (self.pos().x(), self.pos().y(), *self._size))
