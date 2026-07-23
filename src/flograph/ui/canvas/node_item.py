"""NodeItem and PortItem — how a node looks and feels on the canvas."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import (
    QAbstractTextDocumentLayout, QBrush, QColor, QFont, QFontMetrics, QPainter,
    QPainterPath, QPalette, QPen, QTextCursor, QTextDocument,
)
from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsObject, QGraphicsProxyWidget, QHBoxLayout,
    QLabel, QPlainTextEdit, QStyleOptionGraphicsItem, QTableView,
    QToolButton, QVBoxLayout, QWidget,
)

from flograph.core import NodeInstance, PortSpec
from flograph.core.links import link_label, source_id
from flograph.core.node import NodeStatus

from .. import theme
from ..slicer_list import SlicerListWidget, SlicerToolbar, selected_param_values
from .grid import EDGE_MARGIN, grid_step, snap, snap_point, snapping_active

NODE_WIDTH = 170.0
HEADER_H = 26.0
ROW_H = 20.0
PAD_BOTTOM = 8.0
LED_RADIUS = 5.0
LABEL_LOD = 0.5  # hide port names below this zoom
# Below this zoom, nodes paint as a flat rect (no path/text/LED) and hide
# their ports and embedded widgets — the per-item cost that makes a large
# graph sluggish scales with how many nodes are visible, so cutting it here
# is what keeps zoomed-out canvases snappy regardless of node count. This is
# just the out-of-the-box default: NodeGraphScene.lod_enabled/lod_threshold
# (user-configurable via Settings > Canvas) are the actual source of truth —
# see NodeGraphScene._flat_state.
DEFAULT_LOD_THRESHOLD = 0.35

NOTE_TYPE = "flograph.util.note"
NOTE_PAD = 12.0
NOTE_MIN_W, NOTE_MAX_W = 120.0, 1600.0
NOTE_MIN_H, NOTE_MAX_H = 60.0, 2000.0

TABLE_TYPE = "flograph.io.table"
TABLE_MIN_W, TABLE_MAX_W = 220.0, 1600.0
TABLE_MIN_H, TABLE_MAX_H = 140.0, 2000.0

REROUTE_LABEL_FONT_SIZE = 8.0
REROUTE_LABEL_PAD_X = 6.0
REROUTE_LABEL_H = 16.0
REROUTE_LABEL_GAP = 4.0  # vertical gap between the dot and its label pill

# Goto/From link cards: a name tag with one visible port. The other port
# exists in the spec (it carries the invisible link) but is never drawn.
LINK_CARD_H = 26.0
LINK_CARD_FONT_SIZE = 8.5
LINK_CARD_PAD_X = 10.0
LINK_CARD_MIN_W, LINK_CARD_MAX_W = 70.0, 240.0

BUTTON_TYPE = "flograph.util.action_button"
BUTTON_W, BUTTON_H = 150.0, 50.0
BUTTON_MIN_W, BUTTON_MAX_W = 90.0, 400.0
BUTTON_MIN_H, BUTTON_MAX_H = 36.0, 160.0

FIGURE_TYPES = {"flograph.viz.show_plot"}
FIGURE_MIN_W, FIGURE_MAX_W = 260.0, 1600.0
FIGURE_MIN_H, FIGURE_MAX_H = 200.0, 2000.0

PLOTLY_TYPE = "flograph.viz.show_plotly"

# Show Table and Table Spec share the whole table-viewer card path; only the
# DataFrame pushed into them differs (the data itself vs. its spec).
TABLE_VIEWER_TYPES = {"flograph.viz.show_table", "flograph.viz.table_spec"}
TABLE_VIEWER_MIN_W, TABLE_VIEWER_MAX_W = 260.0, 1600.0
TABLE_VIEWER_MIN_H, TABLE_VIEWER_MAX_H = 200.0, 2000.0

KPI_TYPE = "flograph.viz.card"
KPI_MIN_W, KPI_MAX_W = 140.0, 800.0
KPI_MIN_H, KPI_MAX_H = 80.0, 500.0

SLICER_TYPE = "flograph.viz.slicer"
SLICER_MIN_W, SLICER_MAX_W = 140.0, 600.0
SLICER_MIN_H, SLICER_MAX_H = 120.0, 2000.0

# Rich cards are chosen by a node's declared NODE["card"] kind (carried in its
# source, so it survives fork/save). This legacy map covers nodes whose source
# predates the marker — already-forked instances and old project files still
# carrying a built-in type_id but no `card` field.
_LEGACY_CARD_BY_TYPE_ID = {
    "flograph.util.reroute": "reroute",
    NOTE_TYPE: "note",
    TABLE_TYPE: "grid",
    BUTTON_TYPE: "button",
    PLOTLY_TYPE: "webview",
    "flograph.viz.show_plot": "figure",
    "flograph.viz.show_table": "table_viewer",
    "flograph.viz.table_spec": "table_viewer",
    KPI_TYPE: "kpi",
    SLICER_TYPE: "slicer",
}


def card_kind(node) -> Optional[str]:
    """The rich-card kind for a node: its explicit NODE['card'] marker, else a
    legacy fallback keyed on the built-in type_id. None = an ordinary node."""
    return node.spec.card or _LEGACY_CARD_BY_TYPE_ID.get(node.type_id)


# Card kinds with a real, expensive embedded output-preview widget — the ones
# the canvas-preview toggle (idea #21) applies to. "kpi" is painted directly
# with no widget, so it's excluded; "grid" is user *input*, not a computed
# preview, so it's excluded too.
PREVIEW_TOGGLABLE_KINDS = {"figure", "webview", "table_viewer", "slicer"}


def kpi_text(value, fmt: str) -> str:
    """A KPI value rendered for display: the node's format spec when it
    applies, otherwise sensible number formatting. Shared with dashboard
    tiles."""
    if fmt:
        try:
            return format(value, fmt)
        except (TypeError, ValueError):
            pass
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    return format(value, ",") if isinstance(value, int) \
        else format(value, ",.6g")


def kpi_caption(params: dict) -> str:
    """The caption under a KPI value: the "label" param, falling back to
    "<Aggregation> of <column>". Shared with dashboard tiles."""
    label = str(params.get("label", "") or "").strip()
    if label:
        return label
    aggregation = params.get("aggregation", "Sum")
    column = str(params.get("column", "") or "").strip()
    return f"{aggregation} of {column}" if column else str(aggregation)

CARD_HANDLE = 14.0  # bottom-right resize grip, shared by notes and tables

CARD_SCALE_MIN, CARD_SCALE_MAX = 25.0, 400.0  # "scale" param, in percent

class PortItem(QGraphicsItem):
    """A circular pin. Wire drags start here and are managed by the scene."""

    RADIUS = 5.5

    def __init__(self, node_item: "NodeItem", spec: PortSpec) -> None:
        super().__init__(node_item)
        self.node_item = node_item
        self.spec = spec
        self._hover = False
        self._drag_tint: Optional[bool] = None  # None / valid / invalid
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        # card-type nodes (figure/table/kpi/slicer) draw no port name text —
        # this is the only way to tell ports apart on those, so always set it
        self.setToolTip(spec.name)

    @property
    def node_id(self) -> str:
        return self.node_item.node.id

    def set_drag_tint(self, valid: Optional[bool]) -> None:
        if valid != self._drag_tint:
            self._drag_tint = valid
            self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(-10, -10, 20, 20)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        radius = self.RADIUS + (2 if self._hover else 0)
        color = theme.wire_color(self.spec.type)
        if self._drag_tint is True:
            color = theme.WIRE_VALID
            radius = self.RADIUS + 2.5
        elif self._drag_tint is False:
            color = theme.WIRE_INVALID
        painter.setPen(QPen(theme.NODE_BORDER, 1.2))
        scene = self.scene()
        connected = scene.is_port_connected(self.node_id, self.spec) if scene else False
        if connected or self.spec.direction.value == "output":
            painter.setBrush(QBrush(color))
        else:
            painter.setBrush(QBrush(theme.NODE_BODY))
            painter.setPen(QPen(color, 1.6))
        painter.drawEllipse(QRectF(-radius, -radius, 2 * radius, 2 * radius))

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self.update()

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        self.update()

    def mousePressEvent(self, event) -> None:
        self.scene().begin_wire_drag(self)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        self.scene().update_wire_drag(event.scenePos())

    def mouseReleaseEvent(self, event) -> None:
        self.scene().finish_wire_drag(event.scenePos())


class NodeItem(QGraphicsObject):
    def __init__(self, node: NodeInstance) -> None:
        super().__init__()
        self.node = node
        kind = card_kind(node)
        self.compact = kind == "reroute"
        self.note = kind == "note"
        self.table = kind == "grid"
        self.button = kind == "button"
        # a "webview" card embeds the HTML webview; the attribute keeps its
        # historical name since all the downstream chrome/render code reads it
        self.plotly_card = kind == "webview"
        # webview cards share the figure card's chrome (resize, paint, ports);
        # only the embedded widget differs (webview vs. matplotlib canvas)
        self.figure_card = kind == "figure" or self.plotly_card
        self.table_viewer = kind == "table_viewer"
        self.kpi_card = kind == "kpi"
        self.slicer = kind == "slicer"
        # Goto/From: the two ends of a link the canvas doesn't draw
        self.goto_card = kind == "goto"
        self.from_card = kind == "from"
        self.link_card = self.goto_card or self.from_card
        self._link_partners: set[str] = set()  # highlighted with this node
        self.broken = node.spec.broken
        if self.link_card:
            self.width = self._link_card_width()
        elif self.compact:
            self.width = 28.0
        elif self.note:
            self.width = float(node.params.get("width", 280))
        elif self.table:
            self.width = min(TABLE_MAX_W, max(
                TABLE_MIN_W, float(node.params.get("width", 320))))
        elif self.button:
            self.width = min(BUTTON_MAX_W, max(
                BUTTON_MIN_W, float(node.params.get("width", BUTTON_W))))
        elif self.figure_card:
            self.width = min(FIGURE_MAX_W, max(
                FIGURE_MIN_W, float(node.params.get("width", 420))))
        elif self.table_viewer:
            self.width = min(TABLE_VIEWER_MAX_W, max(
                TABLE_VIEWER_MIN_W, float(node.params.get("width", 420))))
        elif self.kpi_card:
            self.width = min(KPI_MAX_W, max(
                KPI_MIN_W, float(node.params.get("width", 220))))
        elif self.slicer:
            self.width = min(SLICER_MAX_W, max(
                SLICER_MIN_W, float(node.params.get("width", 200))))
        else:
            self.width = NODE_WIDTH
        self._note_doc: QTextDocument | None = None
        self._resizing_card = False
        self._resize_edge = "corner"  # which edge/corner the drag grabbed
        self._resize_start = (0.0, 0.0, 0.0, 0.0)  # scene x/y, width/height
        self._live_height: float | None = None  # transient, while drag-resizing
        self._dragging = False  # a header-bar move is in progress (snap gate)
        self._move_suppressed = False  # body press cleared ItemIsMovable
        self._button_edit = False  # button in edit mode (right-click to enter)
        self._flat = False  # painting as a flat rect with ports/widgets hidden (see set_lod)
        self._note_editor: QGraphicsProxyWidget | None = None
        self._note_editor_widget: QPlainTextEdit | None = None
        self._closing_note_edit = False
        self._table_widget = None   # SpreadsheetView (grid cards only)
        self._table_model = None    # SheetModel (grid cards only)
        self._table_buttons: tuple = ()
        self._table_expand = None
        self._table_proxy: QGraphicsProxyWidget | None = None
        self._figure_view = None
        self._figure_proxy: QGraphicsProxyWidget | None = None
        self._figure_placeholder: QLabel | None = None
        self._plotly_widget = None  # shared PlotlyView, see _build_plotly_widget
        self._table_viewer_view: QTableView | None = None
        self._table_viewer_proxy: QGraphicsProxyWidget | None = None
        self._table_viewer_placeholder: QLabel | None = None
        self._kpi_value: object = None
        self._kpi_has_value = False
        self._slicer_list: SlicerListWidget | None = None
        self._slicer_toolbar: SlicerToolbar | None = None
        self._slicer_proxy: QGraphicsProxyWidget | None = None
        self._slicer_placeholder: QLabel | None = None
        self.setFlags(
            QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        # Buttons stay put until right-click puts them in edit mode; every
        # other node drags freely. Keeping buttons non-movable is what stops a
        # button caught in a multi-selection from being dragged with the group.
        if not self.button:
            self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        self.setAcceptHoverEvents(True)  # drives the move/resize cursors
        self.setPos(*node.pos)

        self.input_ports: dict[str, PortItem] = {}
        self.output_ports: dict[str, PortItem] = {}
        self._group_starts: dict | None = None  # group-drag snapshot
        self._pulse = 0.0
        self._pulse_anim: Optional[QVariantAnimation] = None
        self.rebuild_ports()
        if self.table:
            self._build_table_widget()
        if self.plotly_card:
            self._build_plotly_widget()
        elif self.figure_card:
            self._build_figure_widget()
        if self.table_viewer:
            self._build_table_viewer_widget()
        if self.slicer:
            self._build_slicer_widget()
        if not node.canvas_preview_enabled:
            self._apply_proxy_visibility()  # honor a preview-disabled node loaded from disk
        self._refresh_tooltip()

    # ------------------------------------------------------------- geometry

    @property
    def body_height(self) -> float:
        if self.link_card:
            return LINK_CARD_H
        if self.compact:
            return 24.0
        if self.button:
            if self._live_height is not None:
                return self._live_height
            fixed = float(self.node.params.get("height", BUTTON_H) or BUTTON_H)
            return min(BUTTON_MAX_H, max(BUTTON_MIN_H, fixed))
        if self.note:
            if self._live_height is not None:
                return self._live_height
            fixed = float(self.node.params.get("height", 0) or 0)
            if fixed > 0:
                return min(NOTE_MAX_H, max(NOTE_MIN_H, fixed))
            return self._note_document().size().height() + 2 * NOTE_PAD
        if self.table:
            if self._live_height is not None:
                return self._live_height
            fixed = float(self.node.params.get("height", 220) or 220)
            return min(TABLE_MAX_H, max(TABLE_MIN_H, fixed))
        if self.figure_card:
            if self._live_height is not None:
                return self._live_height
            fixed = float(self.node.params.get("height", 320) or 320)
            return min(FIGURE_MAX_H, max(FIGURE_MIN_H, fixed))
        if self.table_viewer:
            if self._live_height is not None:
                return self._live_height
            fixed = float(self.node.params.get("height", 320) or 320)
            return min(TABLE_VIEWER_MAX_H, max(TABLE_VIEWER_MIN_H, fixed))
        if self.kpi_card:
            if self._live_height is not None:
                return self._live_height
            fixed = float(self.node.params.get("height", 120) or 120)
            return min(KPI_MAX_H, max(KPI_MIN_H, fixed))
        if self.slicer:
            if self._live_height is not None:
                return self._live_height
            fixed = float(self.node.params.get("height", 240) or 240)
            return min(SLICER_MAX_H, max(SLICER_MIN_H, fixed))
        rows = max(len(self.node.spec.inputs), len(self.node.spec.outputs), 1)
        return HEADER_H + rows * ROW_H + PAD_BOTTOM

    # ---------------------------------------------------------------- notes

    def _note_document(self) -> QTextDocument:
        if self._note_doc is None:
            doc = QTextDocument()
            font = QFont()
            font.setPointSizeF(9.5)
            doc.setDefaultFont(font)
            doc.setMarkdown(str(self.node.params.get("text", "")))
            doc.setTextWidth(self.width - 2 * NOTE_PAD)
            self._note_doc = doc
        return self._note_doc

    def on_params_changed(self) -> None:
        """Params drive geometry for notes (text/width) and tables
        (data/width/height); other node kinds ignore param edits."""
        if self.note:
            self.prepareGeometryChange()
            self.width = min(NOTE_MAX_W, max(
                NOTE_MIN_W, float(self.node.params.get("width", 280))))
            self._note_doc = None
            self.update()
            return
        if self.table:
            self.prepareGeometryChange()
            self.width = min(TABLE_MAX_W, max(
                TABLE_MIN_W, float(self.node.params.get("width", 320))))
            self._sync_table_widget()
            self._layout_table_proxy()
            self._ports_follow_width()
            self.update()
            return
        if self.figure_card:
            self.prepareGeometryChange()
            self.width = min(FIGURE_MAX_W, max(
                FIGURE_MIN_W, float(self.node.params.get("width", 420))))
            self._layout_figure_proxy()
            self._ports_follow_width()
            self.update()
            return
        if self.table_viewer:
            self.prepareGeometryChange()
            self.width = min(TABLE_VIEWER_MAX_W, max(
                TABLE_VIEWER_MIN_W, float(self.node.params.get("width", 420))))
            self._layout_table_viewer_proxy()
            self._ports_follow_width()
            self.update()
            return
        if self.kpi_card:
            # label/format edits repaint the value too, not just geometry
            self.prepareGeometryChange()
            self.width = min(KPI_MAX_W, max(
                KPI_MIN_W, float(self.node.params.get("width", 220))))
            self._ports_follow_width()
            self.update()
            return
        if self.slicer:
            self.prepareGeometryChange()
            self.width = min(SLICER_MAX_W, max(
                SLICER_MIN_W, float(self.node.params.get("width", 200))))
            self._sync_slicer_checks()
            self._layout_slicer_proxy()
            self._ports_follow_width()
            self.update()

    def _handle_rect(self) -> QRectF:
        """Bottom-right resize grip, shown while a note/table is selected."""
        return QRectF(self.width - CARD_HANDLE,
                      self.body_height - CARD_HANDLE, CARD_HANDLE, CARD_HANDLE)

    def start_note_edit(self) -> None:
        """Open an in-place markdown editor over the card (Obsidian-style).
        Commits on focus-out or Ctrl+Enter; Escape cancels."""
        if not self.note or self._note_editor is not None:
            return
        editor = QPlainTextEdit(str(self.node.params.get("text", "")))
        editor.setStyleSheet(
            f"QPlainTextEdit {{"
            f" background: {theme.NODE_BODY.name()};"
            f" color: {theme.NODE_TEXT.name()};"
            f" border: 1.4px solid {theme.SELECTION_OUTLINE.name()};"
            f" border-radius: 8px; padding: 4px; font-size: 9.5pt; }}")
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.End)
        editor.setTextCursor(cursor)
        editor.installEventFilter(self)
        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(editor)
        proxy.setGeometry(QRectF(0, 0, max(self.width, 200.0),
                                 max(self.body_height, 120.0)))
        self._note_editor = proxy
        self._note_editor_widget = editor
        editor.setFocus()

    def _finish_note_edit(self, commit: bool) -> None:
        if self._note_editor is None or self._closing_note_edit:
            return
        self._closing_note_edit = True
        try:
            editor = self._note_editor_widget
            proxy = self._note_editor
            text = editor.toPlainText()
            self._note_editor = None
            self._note_editor_widget = None
            editor.removeEventFilter(self)
            if proxy.scene() is not None:
                proxy.scene().removeItem(proxy)
            proxy.deleteLater()
        finally:
            self._closing_note_edit = False
        scene = self.scene()
        if commit and scene is not None \
                and text != self.node.params.get("text", ""):
            from ..commands import SetParamCommand
            scene.undo_stack.push(SetParamCommand(
                scene.graph, self.node.id, "text", text))

    def eventFilter(self, obj, event) -> bool:
        if obj is self._note_editor_widget:
            if event.type() == QEvent.FocusOut:
                self._finish_note_edit(commit=True)
            elif event.type() == QEvent.KeyPress:
                if event.key() == Qt.Key_Escape:
                    self._finish_note_edit(commit=False)
                    return True
                if (event.key() in (Qt.Key_Return, Qt.Key_Enter)
                        and event.modifiers() & Qt.ControlModifier):
                    self._finish_note_edit(commit=True)
                    return True
        return super().eventFilter(obj, event)

    # ---------------------------------------------------------------- table

    def _table_proxy_rect(self) -> QRectF:
        height = max(0.0, self.body_height - HEADER_H - CARD_HANDLE)
        return QRectF(0, HEADER_H, self.width, height)

    def _layout_table_proxy(self) -> None:
        if self._table_proxy is not None:
            self._table_proxy.setGeometry(self._table_proxy_rect())

    def _build_table_widget(self) -> None:
        from ..spreadsheet import SheetModel, SpreadsheetView

        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)

        toolbar = QWidget()
        trow = QHBoxLayout(toolbar)
        trow.setContentsMargins(0, 0, 0, 0)
        trow.setSpacing(3)
        add_row = QToolButton(text="+Row")
        del_row = QToolButton(text="-Row")
        add_col = QToolButton(text="+Col")
        del_col = QToolButton(text="-Col")
        fit = QToolButton(text="Fit")
        fit.setToolTip("Auto-size columns to their content")
        expand = QToolButton(text="⛶")
        expand.setToolTip("Open the full spreadsheet editor")
        for button in (add_row, del_row, add_col, del_col, fit):
            button.setAutoRaise(True)
            trow.addWidget(button)
        trow.addStretch(1)
        expand.setAutoRaise(True)
        trow.addWidget(expand)
        layout.addWidget(toolbar)

        grid = SpreadsheetView()
        # parent the model to the view so C++ destruction stays ordered
        model = SheetModel(self.node.params.get("data"), parent=grid)
        grid.setModel(model)
        grid.verticalHeader().setFixedWidth(28)
        grid.setStyleSheet(
            f"QTableView {{ background: {theme.NODE_BODY.name()};"
            f" color: {theme.NODE_TEXT.name()}; border: none;"
            f" gridline-color: {theme.NODE_BORDER.name()}; font-size: 8.5pt; }}"
            f"QHeaderView::section {{ background: {theme.NODE_HEADER.name()};"
            f" color: {theme.NODE_SUBTEXT.name()};"
            f" border: 1px solid {theme.NODE_BORDER.name()}; padding: 2px; }}")
        layout.addWidget(grid)

        add_row.clicked.connect(self._table_add_row)
        del_row.clicked.connect(self._table_remove_row)
        add_col.clicked.connect(self._table_add_column)
        del_col.clicked.connect(self._table_remove_column)
        fit.clicked.connect(lambda: grid.autosize_columns())
        expand.clicked.connect(self._open_table_editor)
        model.sheet_edited.connect(self._commit_table_data)

        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(host)
        self._table_proxy = proxy
        self._table_widget = grid
        self._table_model = model
        self._table_buttons = (add_row, del_row, add_col, del_col)
        self._table_expand = expand
        self._layout_table_proxy()

    def _sync_table_widget(self) -> None:
        """Pull externally-changed data (undo/redo, Properties edit) into
        the grid; SheetModel skips the reset when nothing changed."""
        if self._table_model is not None:
            self._table_model.set_sheet(self.node.params.get("data"))

    def _table_input_connected(self) -> bool:
        scene = self.scene()
        return (scene is not None
                and scene.graph.input_connection(self.node.id, "table")
                is not None)

    def refresh_table_link(self) -> None:
        """The table's input was connected or disconnected. The grid stays
        editable either way (a run refreshes input-owned columns; the
        user's own columns survive) — on disconnect, fall back to the
        stored cells."""
        if not self.table or self._table_model is None:
            return
        if not self._table_input_connected():
            self._sync_table_widget()

    def show_linked_sheet(self, sheet_dict: dict) -> None:
        """Display the merged result of a linked run (input columns
        refreshed, user columns carried over) — editable; the first edit
        commits this merged state to the node."""
        if self._table_model is not None and sheet_dict:
            self._table_model.set_sheet(sheet_dict)

    def _commit_table_data(self, data: dict) -> None:
        import json
        scene = self.scene()
        if scene is None:
            return
        from ..commands import SetParamCommand
        new_json = json.dumps(data)
        if new_json == self.node.params.get("data"):
            return
        # merge=False: every cell edit/paste/structural op is its own undo
        # step — one Ctrl+Z reverts one edit, not the whole session
        scene.undo_stack.push(SetParamCommand(
            scene.graph, self.node.id, "data", new_json, merge=False))

    def _table_add_row(self) -> None:
        model = self._table_model
        model.insert_rows_at(model.rowCount())

    def _table_remove_row(self) -> None:
        model = self._table_model
        model.remove_rows_at([model.rowCount() - 1])

    def _table_add_column(self) -> None:
        model = self._table_model
        model.insert_columns_at(model.columnCount())

    def _table_remove_column(self) -> None:
        model = self._table_model
        model.remove_columns_at([model.columnCount() - 1])

    def _open_table_editor(self) -> None:
        from ..spreadsheet import SheetEditorDialog

        proxy = self._table_proxy
        if proxy is not None:
            proxy.setEnabled(False)   # no concurrent card edits underneath
        try:
            dialog = SheetEditorDialog(
                self.node.params.get("data"),
                title=f"Edit Table — {self.node.label}")
            dialog.on_apply = self._commit_table_data
            if dialog.exec():
                self._commit_table_data(dialog.sheet_dict())
        finally:
            if proxy is not None:
                proxy.setEnabled(True)
            self._sync_table_widget()

    # -------------------------------------------------------------- figure

    def _card_scale(self) -> float:
        """Content zoom for show-cards, from the node's "scale" param (%)."""
        try:
            pct = float(self.node.params.get("scale", 100) or 100)
        except (TypeError, ValueError):
            pct = 100.0
        return min(CARD_SCALE_MAX, max(CARD_SCALE_MIN, pct)) / 100.0

    def _scale_proxy_into(self, proxy: QGraphicsProxyWidget,
                          rect: QRectF) -> None:
        """Fit a proxied widget into rect at the card's content scale: the
        widget gets rect/scale logical pixels and a transform maps it back,
        so a bigger scale shows less content drawn larger (and vice versa)."""
        scale = self._card_scale()
        proxy.setScale(scale)
        proxy.setPos(rect.topLeft())
        proxy.resize(rect.width() / scale, rect.height() / scale)

    def _figure_proxy_rect(self) -> QRectF:
        height = max(0.0, self.body_height - HEADER_H - CARD_HANDLE)
        return QRectF(0, HEADER_H, self.width, height)

    def _layout_figure_proxy(self) -> None:
        if self._figure_proxy is None:
            return
        if self.plotly_card:
            # Chromium zooms natively (and stays crisp) — keep the proxy
            # unscaled and drive the webview's zoom factor instead.
            self._figure_proxy.setGeometry(self._figure_proxy_rect())
            if self._plotly_widget is not None:
                self._plotly_widget.set_zoom(self._card_scale())
            return
        self._scale_proxy_into(self._figure_proxy, self._figure_proxy_rect())
        self.refresh_render_ratio()

    def _figure_render_ratio(self) -> float:
        """Device pixels per logical pixel of the embedded figure: screen
        DPR × view zoom × card scale. The Agg buffer must match what lands
        on screen or the compounded transforms stretch a 1× raster."""
        ratio = self._card_scale()
        scene = self.scene()
        views = scene.views() if scene is not None else []
        if views:
            view = views[0]
            ratio *= (view.viewport().devicePixelRatioF() or 1.0)
            ratio *= view.transform().m11()
        return min(8.0, max(1.0, ratio))

    def refresh_render_ratio(self) -> None:
        """Re-target the figure's render resolution — called on card scale
        changes and (debounced, via the scene) after the view zoom settles."""
        if self._figure_view is not None and not self.plotly_card:
            self._figure_view.set_render_ratio(self._figure_render_ratio())

    def _build_figure_widget(self) -> None:
        from ..inspector.figure_view import FigureView
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        placeholder = QLabel("Run the graph to see a figure here.")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("color: #6b7280;")
        layout.addWidget(placeholder, 1)
        self._figure_placeholder = placeholder

        self._figure_view = FigureView(dialog_parent=self._dialog_parent_widget)
        self._figure_view.hide()
        layout.addWidget(self._figure_view, 1)

        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(host)
        self._figure_proxy = proxy
        self._layout_figure_proxy()

    def _dialog_parent_widget(self) -> Optional[QWidget]:
        """The real top-level window for this node's embedded figure to
        anchor its save-file dialog to — see FigureView/_AnchoredToolbar for
        why self.canvas.parent() alone isn't safe here."""
        scene = self.scene()
        if scene is None:
            return None
        views = scene.views()
        return views[0].window() if views else None

    def set_figure(self, figure) -> None:
        """Push a freshly computed figure (or None) onto the embedded canvas —
        called from the GUI thread once the engine reports this node done."""
        if self._figure_view is None:
            return
        if figure is None:
            self._figure_view.clear()
            self._figure_view.hide()
            self._figure_placeholder.show()
            return
        self._figure_placeholder.hide()
        self.refresh_render_ratio()  # card may have been built before the view
        self._figure_view.set_figure(figure)
        self._figure_view.show()

    # -------------------------------------------------------------- plotly

    def _build_plotly_widget(self) -> None:
        """Card chrome identical to the figure card, but the body hosts a
        shared PlotlyView (webview created lazily on the first figure)."""
        from ..inspector.plotly_view import PlotlyView
        widget = PlotlyView()
        widget.setContentsMargins(2, 2, 2, 2)
        self._plotly_widget = widget
        self._figure_placeholder = widget.placeholder

        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(widget)
        self._figure_proxy = proxy  # reuses the figure card's resize plumbing
        self._layout_figure_proxy()

    def set_plotly_figure(self, figure) -> None:
        """Render a freshly computed plotly figure (or None) into the
        embedded webview — called from the GUI thread once the engine
        reports this node done."""
        if not self.plotly_card:
            return
        self._plotly_widget.set_figure(figure)
        self._plotly_widget.set_zoom(self._card_scale())

    # --------------------------------------------------------- table viewer

    def _table_viewer_proxy_rect(self) -> QRectF:
        height = max(0.0, self.body_height - HEADER_H - CARD_HANDLE)
        return QRectF(0, HEADER_H, self.width, height)

    def _layout_table_viewer_proxy(self) -> None:
        if self._table_viewer_proxy is not None:
            self._scale_proxy_into(self._table_viewer_proxy,
                                   self._table_viewer_proxy_rect())

    def _build_table_viewer_widget(self) -> None:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        placeholder = QLabel("Run the graph to see a table here.")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("color: #6b7280;")
        layout.addWidget(placeholder, 1)
        self._table_viewer_placeholder = placeholder

        view = QTableView()
        view.setStyleSheet(
            f"QTableView {{ background: {theme.NODE_BODY.name()};"
            f" color: {theme.NODE_TEXT.name()}; border: none;"
            f" gridline-color: {theme.NODE_BORDER.name()}; font-size: 8.5pt; }}"
            f"QHeaderView::section {{ background: {theme.NODE_HEADER.name()};"
            f" color: {theme.NODE_SUBTEXT.name()};"
            f" border: 1px solid {theme.NODE_BORDER.name()}; padding: 2px; }}")
        view.setSortingEnabled(True)
        view.hide()
        layout.addWidget(view, 1)
        self._table_viewer_view = view

        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(host)
        self._table_viewer_proxy = proxy
        self._layout_table_viewer_proxy()

    def set_table_data(self, table) -> None:
        """Push a freshly computed DataFrame (or None) onto the embedded
        table view — called from the GUI thread once the engine reports this
        node done."""
        view = self._table_viewer_view
        if view is None:
            return
        import sys
        pd = sys.modules.get("pandas")
        if table is None or pd is None or not isinstance(table, pd.DataFrame):
            view.setModel(None)
            view.hide()
            self._table_viewer_placeholder.show()
            return
        self._table_viewer_placeholder.hide()
        from ..inspector.pandas_model import PandasModel
        view.setModel(PandasModel(table, parent=view))
        view.show()

    # ------------------------------------------------------------- kpi card

    def set_card_value(self, value, has_value: bool = True) -> None:
        """Push a freshly computed KPI value onto the card — called from the
        GUI thread once the engine reports this node done. has_value=False
        reverts to the run-me placeholder (the value itself may be None)."""
        self._kpi_value = value
        self._kpi_has_value = has_value
        self.update()

    def _kpi_text(self) -> str:
        return kpi_text(self._kpi_value,
                        str(self.node.params.get("format", "") or ""))

    def _kpi_label(self) -> str:
        return kpi_caption(self.node.params)

    # --------------------------------------------------------------- slicer

    def _slicer_proxy_rect(self) -> QRectF:
        height = max(0.0, self.body_height - HEADER_H - CARD_HANDLE)
        return QRectF(0, HEADER_H, self.width, height)

    def _layout_slicer_proxy(self) -> None:
        if self._slicer_proxy is not None:
            self._slicer_proxy.setGeometry(self._slicer_proxy_rect())

    def _build_slicer_widget(self) -> None:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        placeholder = QLabel("Run the graph to load slicer values.")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setWordWrap(True)
        placeholder.setStyleSheet("color: #6b7280;")
        layout.addWidget(placeholder, 1)
        self._slicer_placeholder = placeholder

        values = SlicerListWidget()
        values.selection_committed.connect(self._on_slicer_committed)
        values.hide()

        toolbar = SlicerToolbar(values)
        toolbar.hide()
        layout.addWidget(toolbar)
        layout.addWidget(values, 1)
        self._slicer_toolbar = toolbar
        self._slicer_list = values

        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(host)
        self._slicer_proxy = proxy
        self._layout_slicer_proxy()

    def set_slicer_options(self, values: Optional[list[str]]) -> None:
        """Rebuild the checkbox list from the column's unique values (from
        the upstream cache), ticking those in the "selected" param — called
        from the GUI thread once the engine reports this node done. None
        reverts to the run-me placeholder."""
        widget = self._slicer_list
        if widget is None:
            return
        if values is None:
            widget.clear()
            widget.hide()
            if self._slicer_toolbar is not None:
                self._slicer_toolbar.hide()
            self._slicer_placeholder.show()
            return
        widget.set_mode(self._slicer_mode())
        widget.set_options(values, set(self._slicer_selected_param()))
        self._slicer_placeholder.hide()
        widget.show()
        if self._slicer_toolbar is not None:
            self._slicer_toolbar.set_mode(self._slicer_mode())
            self._slicer_toolbar.refresh_summary()
            self._slicer_toolbar.show()

    def _sync_slicer_checks(self) -> None:
        """Re-apply check states and selection mode from this node's params
        — keeps the card honest when they change elsewhere (properties
        panel, undo)."""
        widget = self._slicer_list
        if widget is not None and not widget.isHidden():
            widget.set_mode(self._slicer_mode())
            if self._slicer_toolbar is not None:
                self._slicer_toolbar.set_mode(self._slicer_mode())
            widget.sync_checks(set(self._slicer_selected_param()))
            if self._slicer_toolbar is not None:
                self._slicer_toolbar.refresh_summary()

    def _slicer_selected_param(self) -> list[str]:
        return selected_param_values(self.node.params.get("selected", ""))

    def _slicer_mode(self) -> str:
        return str(self.node.params.get("mode", "multi") or "multi")

    def _on_slicer_committed(self, new_value: str) -> None:
        """A tick changed: commit the selection (dirties this node and
        everything downstream) and ask the window to re-run the flow from
        here, so downstream visuals follow the slicer live."""
        scene = self.scene()
        if scene is None:
            return
        if new_value != self.node.params.get("selected", ""):
            from ..commands import SetParamCommand
            scene.undo_stack.push(SetParamCommand(
                scene.graph, self.node.id, "selected", new_value))
        scene.slicer_changed.emit(self.node.id)

    @staticmethod
    def _next_column_name(columns: list[str]) -> str:
        import string
        for letter in string.ascii_uppercase:
            if letter not in columns:
                return letter
        i = 1
        while f"C{i}" in columns:
            i += 1
        return f"C{i}"

    def boundingRect(self) -> QRectF:
        base = QRectF(-2, -2, self.width + 4, self.body_height + 4)
        label_rect = self._reroute_label_rect()
        if label_rect is not None:
            return base.united(label_rect.adjusted(-2, -2, 2, 2))
        return base

    def _reroute_label_rect(self) -> Optional[QRectF]:
        """Local-coordinate rect of the reroute's label pill, centered between
        its input/output ports and sitting above the dot — or None when the
        reroute is unlabeled (the default, labelless look)."""
        if not (self.compact and self.node.label_override):
            return None
        metrics = QFontMetrics(self._reroute_label_font())
        pill_w = metrics.horizontalAdvance(self.node.label_override) + REROUTE_LABEL_PAD_X * 2
        x = self.width / 2 - pill_w / 2
        y = -REROUTE_LABEL_GAP - REROUTE_LABEL_H
        return QRectF(x, y, pill_w, REROUTE_LABEL_H)

    @staticmethod
    def _reroute_label_font() -> QFont:
        font = QFont()
        font.setPointSizeF(REROUTE_LABEL_FONT_SIZE)
        return font

    # ------------------------------------------------------------ link cards

    @staticmethod
    def _link_card_font() -> QFont:
        font = QFont()
        font.setPointSizeF(LINK_CARD_FONT_SIZE)
        return font

    def _link_card_text(self) -> str:
        """What a Goto/From card shows: the link's name. A From reads it from
        the Goto it points at, so renaming one end renames both."""
        if self.goto_card:
            return link_label(self.node)
        graph = getattr(self.scene(), "graph", None)
        if graph is None:
            return link_label(self.node)
        if not source_id(self.node):
            return "pick a Goto"
        target = graph.nodes.get(source_id(self.node))
        return link_label(target) if target is not None else "missing Goto"

    def _link_card_width(self) -> float:
        text = self._link_card_text()
        width = QFontMetrics(self._link_card_font()).horizontalAdvance(text)
        return min(LINK_CARD_MAX_W,
                   max(LINK_CARD_MIN_W, width + LINK_CARD_PAD_X * 2 + 12.0))

    def refresh_link_card(self) -> None:
        """Re-measure and repaint after the link name, or the link itself,
        changed. Cheap enough to call for every link card on the canvas."""
        if not self.link_card:
            return
        width = self._link_card_width()
        if width != self.width:
            self.prepareGeometryChange()
            self.width = width
            self._ports_follow_width()
        self._refresh_tooltip()
        self.update()

    def set_link_highlight(self, on: bool) -> None:
        """Glow this card while its partner at the other end is selected —
        with no wire drawn, this is the only way to see a link on the canvas."""
        if self.link_card and on != bool(self._link_partners):
            self._link_partners = {"on"} if on else set()
            self.update()

    def _paint_link_card(self, painter: QPainter) -> None:
        rect = QRectF(0, 0, self.width, self.body_height)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.isSelected():
            pen = QPen(theme.SELECTION_OUTLINE, 2.0)
        elif self._link_partners:
            pen = QPen(theme.SELECTION_OUTLINE, 1.4, Qt.DashLine)
        elif self.node.status == NodeStatus.ERROR:
            # a broken link has no wire to look wrong: say it on the card
            pen = QPen(theme.status_color(NodeStatus.ERROR), 1.6)
        elif self.broken:
            pen = QPen(theme.NODE_BORDER_BROKEN, 1.4)
        else:
            pen = QPen(theme.NODE_BORDER, 1.2)
        painter.setPen(pen)
        painter.setBrush(QBrush(self._header_color()))
        radius = self.body_height / 2
        painter.drawRoundedRect(rect, radius, radius)

        # chevron on the side the invisible link leaves/enters from
        painter.setFont(self._link_card_font())
        painter.setPen(QPen(theme.NODE_SUBTEXT))
        chevron = QRectF(self.width - 14.0, 0, 12.0, self.body_height) \
            if self.goto_card else QRectF(2.0, 0, 12.0, self.body_height)
        painter.drawText(chevron, Qt.AlignCenter, "»")

        text_rect = rect.adjusted(LINK_CARD_PAD_X + (0 if self.goto_card else 6),
                                  0,
                                  -LINK_CARD_PAD_X - (6 if self.goto_card else 0),
                                  0)
        painter.setPen(QPen(theme.NODE_TEXT))
        metrics = QFontMetrics(self._link_card_font())
        painter.drawText(text_rect, Qt.AlignCenter,
                         metrics.elidedText(self._link_card_text(), Qt.ElideRight,
                                            int(text_rect.width())))

    def rebuild_ports(self) -> None:
        """(Re)create port items from the current spec — called at build time
        and again whenever the node's code changes its ports."""
        for item in (*self.input_ports.values(), *self.output_ports.values()):
            if item.scene() is not None:
                item.scene().removeItem(item)
            item.setParentItem(None)
        self.input_ports.clear()
        self.output_ports.clear()
        self.prepareGeometryChange()
        for spec in self.node.spec.inputs:
            if self.from_card:
                continue  # the link end: real in the spec, never on the canvas
            self.input_ports[spec.name] = PortItem(self, spec)
        for spec in self.node.spec.outputs:
            if self.goto_card:
                continue
            self.output_ports[spec.name] = PortItem(self, spec)
        if self._flat:
            for port in (*self.input_ports.values(), *self.output_ports.values()):
                port.setVisible(False)
        self._layout_ports()
        self.update()

    def _layout_ports(self) -> None:
        """Pin port items to the current geometry. Cards resize at runtime,
        so this runs again on every width change — output ports (and the
        wires on them) must ride the right edge, not stay where they were."""
        if self.compact or self.link_card:
            for port in self.input_ports.values():
                port.setPos(0, self.body_height / 2)
            for port in self.output_ports.values():
                port.setPos(self.width, self.body_height / 2)
            return
        if self.table or self.figure_card or self.table_viewer \
                or self.kpi_card or self.slicer:
            self._space_header_ports(self.input_ports.values(), 0)
            self._space_header_ports(self.output_ports.values(), self.width)
            return
        for i, spec in enumerate(self.node.spec.inputs):
            self.input_ports[spec.name].setPos(0, HEADER_H + ROW_H * (i + 0.5))
        for i, spec in enumerate(self.node.spec.outputs):
            self.output_ports[spec.name].setPos(
                self.width, HEADER_H + ROW_H * (i + 0.5))

    @staticmethod
    def _space_header_ports(ports, x: float) -> None:
        """Card-type nodes usually have one port per side, centered in the
        header; when a forked/custom card declares more, spread them evenly
        so their pins (and wires) don't collapse into one indistinguishable
        dot. A single port still lands dead center — unchanged from before."""
        items = list(ports)
        n = len(items)
        if n <= 1:
            for port in items:
                port.setPos(x, HEADER_H / 2)
            return
        spacing = min(14.0, (HEADER_H - 8.0) / (n - 1))
        start = HEADER_H / 2 - spacing * (n - 1) / 2
        for i, port in enumerate(items):
            port.setPos(x, start + spacing * i)

    def _ports_follow_width(self) -> None:
        """Re-anchor ports after a width change and re-route their wires."""
        self._layout_ports()
        scene = self.scene()
        if scene is not None:
            scene.node_item_moved(self.node.id)

    def port_item(self, name: str, direction: str) -> Optional[PortItem]:
        table = self.input_ports if direction == "input" else self.output_ports
        return table.get(name)

    def _apply_proxy_visibility(self) -> None:
        """Content-proxy visibility is gated by two independent switches: LOD
        flattening (zoomed out, transient) and the canvas-preview toggle
        (persisted, per-node). Either one hides the proxy; ports/header are
        driven by LOD alone (see set_lod), since a preview-disabled node
        stays full-size and wireable."""
        visible = not self._flat and self.node.canvas_preview_enabled
        for proxy in (self._note_editor, self._table_proxy, self._figure_proxy,
                      self._table_viewer_proxy, self._slicer_proxy):
            if proxy is not None:
                proxy.setVisible(visible)

    def set_lod(self, flat: bool) -> None:
        """Called by the scene whenever the decision changes (zoom crossing
        lod_threshold, or lod_enabled toggling): hide ports/embedded widgets
        and switch to the cheap flat paint, or restore them. A reroute dot is
        already minimal and stays as-is regardless."""
        flat = flat and not self.compact
        if flat == self._flat:
            return
        self._flat = flat
        for port in (*self.input_ports.values(), *self.output_ports.values()):
            port.setVisible(not flat)
        self._apply_proxy_visibility()
        self.update()

    def set_preview_enabled(self, enabled: bool) -> None:
        """Show/hide this card's embedded proxy per the canvas-preview
        toggle. Ports stay visible — only the widget hides. On disable, also
        clears the widget's held content (matplotlib Figure / table model /
        slicer options) to actually free memory, not just skip future
        pushes; the last-known data lives in engine.cache regardless, so
        re-enabling repopulates it without forcing a re-run (see
        mainwindow._on_preview_enabled_changed)."""
        self._apply_proxy_visibility()
        if not enabled:
            if self.plotly_card:
                self.set_plotly_figure(None)
            elif self.figure_card:
                self.set_figure(None)
            elif self.table_viewer:
                self.set_table_data(None)
            elif self.slicer:
                self.set_slicer_options(None)
        self.update()

    # ------------------------------------------------------------- painting

    def _header_color(self) -> QColor:
        """Effective header-strip colour: the broken warning red wins over the
        user's custom colour (lightened a touch — the theme's header is a
        lighter shade of its body too), which wins over the theme default."""
        if self.broken:
            return theme.NODE_HEADER_BROKEN
        if self.node.color:
            return QColor(self.node.color).lighter(120)
        return theme.NODE_HEADER

    def _body_color(self) -> QColor:
        """Effective card-body colour: the user's custom colour, or the theme
        default. Broken nodes keep the plain body — header/border signal it."""
        if self.node.color:
            return QColor(self.node.color)
        return theme.NODE_BODY

    def _paint_flat(self, painter: QPainter) -> None:
        """Cheap stand-in for the simplified state: one fill, no path/gradient/text —
        the per-node cost that dominates when many nodes are visible at once."""
        rect = QRectF(0, 0, self.width, self.body_height)
        painter.setPen(QPen(theme.SELECTION_OUTLINE, 1.5) if self.isSelected()
                       else Qt.NoPen)
        fill = (theme.NODE_HEADER_BROKEN if self.broken
                else QColor(self.node.color) if self.node.color
                else theme.NODE_BODY)
        painter.setBrush(QBrush(fill))
        painter.drawRect(rect)

    def paint(self, painter: QPainter,
              option: QStyleOptionGraphicsItem, widget=None) -> None:
        lod = option.levelOfDetailFromTransform(painter.worldTransform())
        if self.link_card:
            if self._flat:
                self._paint_flat(painter)
            else:
                self._paint_link_card(painter)
            return
        if self.compact:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(theme.SELECTION_OUTLINE if self.isSelected()
                                else theme.NODE_BORDER, 1.5))
            painter.setBrush(QBrush(self._header_color()))
            painter.drawRoundedRect(
                QRectF(0, 0, self.width, self.body_height), 10, 10)
            label_rect = self._reroute_label_rect()
            if label_rect is not None:
                painter.setPen(QPen(theme.NODE_BORDER, 1))
                painter.setBrush(QBrush(theme.NODE_HEADER))
                painter.drawRoundedRect(label_rect, label_rect.height() / 2,
                                        label_rect.height() / 2)
                painter.setPen(QPen(theme.NODE_TEXT))
                painter.setFont(self._reroute_label_font())
                painter.drawText(label_rect, Qt.AlignCenter, self.node.label_override)
            return
        if self._flat:
            self._paint_flat(painter)
            return
        if self.note:
            self._paint_note(painter)
            return
        if self.table:
            self._paint_table(painter)
            return
        if self.button:
            self._paint_button(painter)
            return
        if self.figure_card or self.table_viewer or self.slicer:
            self._paint_widget_card(painter)
            if not self.node.canvas_preview_enabled:
                self._paint_preview_disabled_hint(painter)
            return
        if self.kpi_card:
            self._paint_kpi(painter)
            return
        rect = QRectF(0, 0, self.width, self.body_height)

        body = QPainterPath()
        body.addRoundedRect(rect, 7, 7)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillPath(body, self._body_color())
        if self.isSelected():
            outline = QPen(theme.SELECTION_OUTLINE, 2.0)
        elif self.broken:
            outline = QPen(theme.NODE_BORDER_BROKEN, 1.4)
        else:
            outline = QPen(theme.NODE_BORDER, 1.2)
        painter.setPen(outline)
        painter.drawPath(body)

        self._paint_header(painter, NODE_WIDTH)

        # port names (LOD-gated)
        if lod >= LABEL_LOD:
            font = painter.font()
            font.setBold(False)
            font.setPointSizeF(8.0)
            painter.setFont(font)
            painter.setPen(QPen(theme.NODE_SUBTEXT))
            for i, spec in enumerate(self.node.spec.inputs):
                y = HEADER_H + ROW_H * i
                painter.drawText(QRectF(12, y, NODE_WIDTH / 2, ROW_H),
                                 Qt.AlignVCenter | Qt.AlignLeft, spec.name)
            for i, spec in enumerate(self.node.spec.outputs):
                y = HEADER_H + ROW_H * i
                painter.drawText(
                    QRectF(NODE_WIDTH / 2 - 12, y, NODE_WIDTH / 2, ROW_H),
                    Qt.AlignVCenter | Qt.AlignRight, spec.name)

    def _paint_header(self, painter: QPainter, width: float) -> None:
        """Rounded header strip: label + status LED. Shared by the default
        node body and the table card, whose widths differ (fixed vs. resizable)."""
        header = QPainterPath()
        header.addRoundedRect(QRectF(0, 0, width, HEADER_H), 7, 7)
        header.addRect(QRectF(0, HEADER_H / 2, width, HEADER_H / 2))
        painter.fillPath(header.simplified(), self._header_color())

        painter.setPen(QPen(theme.NODE_TEXT))
        font = painter.font()
        font.setPointSizeF(9.0)
        font.setBold(True)
        painter.setFont(font)
        label_rect = QRectF(10, 0, width - 30, HEADER_H)
        label_text = f"⚠ {self.node.label}" if self.broken else self.node.label
        label = painter.fontMetrics().elidedText(
            label_text, Qt.ElideRight, int(label_rect.width()))
        painter.drawText(label_rect, Qt.AlignVCenter | Qt.AlignLeft, label)

        led_color = QColor(theme.status_color(self.node.status))
        if self.node.status == NodeStatus.RUNNING:
            led_color.setAlphaF(0.35 + 0.65 * self._pulse)
        painter.setPen(QPen(theme.NODE_BORDER, 1))
        painter.setBrush(QBrush(led_color))
        led_center_x = width - 13
        painter.drawEllipse(
            QRectF(led_center_x - LED_RADIUS, HEADER_H / 2 - LED_RADIUS,
                   2 * LED_RADIUS, 2 * LED_RADIUS))
        if self.node.dirty and self.node.status == NodeStatus.DONE:
            # stale: hollow out the green LED
            painter.setBrush(QBrush(self._header_color()))
            painter.drawEllipse(
                QRectF(led_center_x - 2, HEADER_H / 2 - 2, 4, 4))

        # Unsaved temp-edit indicator — small amber dot beside status LED.
        if self.node._temp_edit:
            INDICATOR_R = 3.0
            indicator_x = led_center_x - LED_RADIUS - 10
            painter.setPen(QPen(theme.NODE_BORDER, 0.5))
            painter.setBrush(QBrush("#eab308"))
            painter.drawEllipse(
                QRectF(indicator_x - INDICATOR_R, HEADER_H / 2 - INDICATOR_R,
                       2 * INDICATOR_R, 2 * INDICATOR_R))

    def _paint_table(self, painter: QPainter) -> None:
        rect = QRectF(0, 0, self.width, self.body_height)
        painter.setRenderHint(QPainter.Antialiasing)
        body = QPainterPath()
        body.addRoundedRect(rect, 7, 7)
        painter.fillPath(body, self._body_color())
        outline = QPen(theme.SELECTION_OUTLINE if self.isSelected()
                       else theme.NODE_BORDER,
                       2.0 if self.isSelected() else 1.2)
        painter.setPen(outline)
        painter.drawPath(body)

        self._paint_header(painter, self.width)

        if self.isSelected():
            painter.setPen(QPen(theme.NODE_SUBTEXT, 1.2))
            handle = self._handle_rect()
            for i in (4.0, 8.0):
                painter.drawLine(
                    QPointF(handle.right() - i, handle.bottom() - 2),
                    QPointF(handle.right() - 2, handle.bottom() - i))

    def _paint_button(self, painter: QPainter) -> None:
        rect = QRectF(0, 0, self.width, self.body_height)
        painter.setRenderHint(QPainter.Antialiasing)
        body = QPainterPath()
        body.addRoundedRect(rect, 10, 10)
        painter.fillPath(body, QColor(self.node.color) if self.node.color
                         else theme.BUTTON_ACCENT)
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
                         f"▶  {self.node.label}")

        if self._button_edit:
            # A dashed overlay plus a corner grip signals "editable" — this is
            # the only cue that the button now moves/resizes instead of firing.
            painter.setPen(QPen(theme.SELECTION_OUTLINE, 1.2, Qt.DashLine))
            painter.drawPath(body)
            painter.setPen(QPen(QColor("#ffffff"), 1.4))
            handle = self._handle_rect()
            for i in (4.0, 8.0):
                painter.drawLine(
                    QPointF(handle.right() - i, handle.bottom() - 2),
                    QPointF(handle.right() - 2, handle.bottom() - i))

    def _paint_kpi(self, painter: QPainter) -> None:
        """The KPI card: the widget-card chrome with a big painted value —
        vector text stays crisp at every zoom, no proxy widget needed."""
        self._paint_widget_card(painter)

        avail = QRectF(8, HEADER_H + 2, self.width - 16,
                       self.body_height - HEADER_H - 22)
        if not self._kpi_has_value:
            painter.setPen(QPen(theme.NODE_SUBTEXT))
            font = painter.font()
            font.setBold(False)
            font.setPointSizeF(8.5)
            painter.setFont(font)
            painter.drawText(avail, Qt.AlignCenter | Qt.TextWordWrap,
                             "Run the graph to compute the value.")
            return

        text = self._kpi_text()
        # size to fit: capped by height, shrunk for long values (~0.62 em
        # average glyph width), never below a readable floor
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
            self._kpi_label(), Qt.ElideRight, int(self.width - 16))
        painter.drawText(
            QRectF(8, self.body_height - 20, self.width - 16, 16),
            Qt.AlignHCenter | Qt.AlignVCenter, caption)

    def _paint_widget_card(self, painter: QPainter) -> None:
        """Shared chrome for cards that embed a proxied widget (figure/table
        viewers): rounded body, header strip, resize handle when selected."""
        rect = QRectF(0, 0, self.width, self.body_height)
        painter.setRenderHint(QPainter.Antialiasing)
        body = QPainterPath()
        body.addRoundedRect(rect, 7, 7)
        painter.fillPath(body, self._body_color())
        outline = QPen(theme.SELECTION_OUTLINE if self.isSelected()
                       else theme.NODE_BORDER,
                       2.0 if self.isSelected() else 1.2)
        painter.setPen(outline)
        painter.drawPath(body)

        self._paint_header(painter, self.width)

        if self.isSelected():
            painter.setPen(QPen(theme.NODE_SUBTEXT, 1.2))
            handle = self._handle_rect()
            for i in (4.0, 8.0):
                painter.drawLine(
                    QPointF(handle.right() - i, handle.bottom() - 2),
                    QPointF(handle.right() - 2, handle.bottom() - i))

    def _paint_preview_disabled_hint(self, painter: QPainter) -> None:
        """Overlay drawn where the (hidden) content proxy would otherwise
        show through, so a preview-disabled card reads distinctly from one
        that's merely zoomed out (see set_lod/_flat, painted separately)."""
        rect = QRectF(4, HEADER_H + 4, self.width - 8,
                      self.body_height - HEADER_H - 8)
        painter.setPen(QPen(theme.NODE_SUBTEXT))
        font = painter.font()
        font.setBold(False)
        font.setPointSizeF(8.0)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap,
                         "Preview off — right-click to enable")

    def _paint_note(self, painter: QPainter) -> None:
        rect = QRectF(0, 0, self.width, self.body_height)
        painter.setRenderHint(QPainter.Antialiasing)
        body = QColor(self.node.color) if self.node.color else QColor(theme.NODE_BODY)
        body.setAlphaF(0.75)
        painter.setBrush(QBrush(body))
        painter.setPen(QPen(theme.SELECTION_OUTLINE if self.isSelected()
                            else theme.GRID_COARSE, 1.4))
        painter.drawRoundedRect(rect, 8, 8)

        painter.save()
        painter.translate(NOTE_PAD, NOTE_PAD)
        painter.setClipRect(QRectF(0, 0, self.width - 2 * NOTE_PAD,
                                   self.body_height - 2 * NOTE_PAD))
        context = QAbstractTextDocumentLayout.PaintContext()
        context.palette.setColor(QPalette.Text, theme.NODE_TEXT)
        self._note_document().documentLayout().draw(painter, context)
        painter.restore()

        if self.isSelected():
            painter.setPen(QPen(theme.NODE_SUBTEXT, 1.2))
            handle = self._handle_rect()
            for i in (4.0, 8.0):
                painter.drawLine(
                    QPointF(handle.right() - i, handle.bottom() - 2),
                    QPointF(handle.right() - 2, handle.bottom() - i))

    # ------------------------------------------------------------ behaviour

    def _resize_bounds(self) -> tuple[float, float, float, float]:
        """(min_w, max_w, min_h, max_h) for whichever card is being resized."""
        if self.table:
            return TABLE_MIN_W, TABLE_MAX_W, TABLE_MIN_H, TABLE_MAX_H
        if self.figure_card:
            return FIGURE_MIN_W, FIGURE_MAX_W, FIGURE_MIN_H, FIGURE_MAX_H
        if self.table_viewer:
            return (TABLE_VIEWER_MIN_W, TABLE_VIEWER_MAX_W,
                    TABLE_VIEWER_MIN_H, TABLE_VIEWER_MAX_H)
        if self.kpi_card:
            return KPI_MIN_W, KPI_MAX_W, KPI_MIN_H, KPI_MAX_H
        if self.slicer:
            return SLICER_MIN_W, SLICER_MAX_W, SLICER_MIN_H, SLICER_MAX_H
        if self.button:
            return BUTTON_MIN_W, BUTTON_MAX_W, BUTTON_MIN_H, BUTTON_MAX_H
        return NOTE_MIN_W, NOTE_MAX_W, NOTE_MIN_H, NOTE_MAX_H

    def _resizable(self) -> bool:
        return bool(self.note or self.table or self.figure_card
                    or self.table_viewer or self.kpi_card or self.slicer
                    or (self.button and self._button_edit))

    def _header_h(self) -> float:
        """Height of the drag bar — the only region a move can start from.
        Headerless kinds (reroute, button) drag by their whole body, having
        nothing else to grab; notes get a thin top strip."""
        if self.compact or self.button:
            return self.body_height
        return HEADER_H

    def _edge_at(self, pos: QPointF) -> Optional[str]:
        """Which resize edge/corner (if any) a point grabs: "right", "bottom",
        "corner", or None. Only resizable cards, and only when selected."""
        if not (self._resizable() and self.isSelected()):
            return None
        w, h = self.width, self.body_height
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

    def hoverMoveEvent(self, event) -> None:
        edge = self._edge_at(event.pos())
        if edge == "corner":
            self.setCursor(Qt.SizeFDiagCursor)
        elif edge == "right":
            self.setCursor(Qt.SizeHorCursor)
        elif edge == "bottom":
            self.setCursor(Qt.SizeVerCursor)
        elif self.button and self._button_edit:
            self.setCursor(Qt.SizeAllCursor)  # whole face drags in edit mode
        elif (not self.compact and not self.button
                and event.pos().y() < self._header_h()):
            self.setCursor(Qt.SizeAllCursor)  # the header drag bar
        else:
            self.unsetCursor()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def enter_button_edit(self) -> None:
        """Put this Action Button into edit mode: right-click entry point. The
        button becomes selectable/movable/resizable and stops firing on click.
        Selecting it alone (clearing other selections) is what keeps a later
        drag from carrying any previously-selected nodes along."""
        if not self.button:
            return
        scene = self.scene()
        if scene is not None:
            scene.clearSelection()
        self._button_edit = True
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setSelected(True)
        self.update()

    def _exit_button_edit(self) -> None:
        self._button_edit = False
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self._dragging \
                and snapping_active(self.scene()):
            step = grid_step(self.scene())
            x, y = snap_point(value.x(), value.y(), step)
            return QPointF(x, y)
        if change == QGraphicsItem.ItemPositionHasChanged:
            scene = self.scene()
            if scene is not None:
                scene.node_item_moved(self.node.id)
        if change == QGraphicsItem.ItemSelectedHasChanged \
                and self._button_edit and not value:
            # Clicking the canvas or another node drops the selection, which
            # leaves button edit mode and restores fire-on-click.
            self._exit_button_edit()
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:
        if self.button and event.button() == Qt.LeftButton \
                and not self._button_edit:
            # Default state: a left-click fires the action. Editing (move and
            # resize) is only reachable via right-click, which enters edit mode.
            scene = self.scene()
            if scene is not None:
                scene.button_fired.emit(self.node.id)
            event.accept()
            return
        if self.button and self._button_edit \
                and event.button() == Qt.LeftButton:
            # In edit mode the whole face drags; an edge/corner grip resizes.
            edge = self._edge_at(event.pos())
            if edge is not None:
                self._resizing_card = True
                self._resize_edge = edge
                self._resize_start = (event.scenePos().x(),
                                      event.scenePos().y(),
                                      self.width, self.body_height)
                self._live_height = self.body_height
                event.accept()
                return
            self._dragging = True
            super().mousePressEvent(event)
            scene = self.scene()
            if scene is not None:
                # Arm the group-drag snapshot so the release handler commits
                # the move to the model — without this the button slides on
                # screen but node.pos is never updated, so it reloads at its
                # old spot.
                self._group_starts = scene.begin_group_drag()
            return
        edge = (self._edge_at(event.pos())
                if event.button() == Qt.LeftButton else None)
        if edge is not None:
            self._resizing_card = True
            self._resize_edge = edge
            self._resize_start = (event.scenePos().x(), event.scenePos().y(),
                                  self.width, self.body_height)
            self._live_height = self.body_height
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            # Only the header drag bar starts a move; a press on the body just
            # selects (clear ItemIsMovable for this gesture so it can't drag).
            if event.pos().y() < self._header_h():
                self._dragging = True
            else:
                self._move_suppressed = True
                self.setFlag(QGraphicsItem.ItemIsMovable, False)
        super().mousePressEvent(event)
        scene = self.scene()
        if scene is not None and self._dragging:
            # A real header drag: arm the whole selection so every selected
            # node/frame snaps, not just this one, and snapshot for the commit.
            self._group_starts = scene.begin_group_drag()

    def mouseMoveEvent(self, event) -> None:
        if self._resizing_card:
            min_w, max_w, min_h, max_h = self._resize_bounds()
            start_x, start_y, start_w, start_h = self._resize_start
            edge = self._resize_edge
            new_width = self.width
            new_height = self._live_height
            snapping = snapping_active(self.scene(), event.modifiers())
            step = grid_step(self.scene())
            if edge in ("right", "corner"):
                new_width = start_w + event.scenePos().x() - start_x
                if snapping:
                    new_width = snap(new_width, step)
                new_width = min(max_w, max(min_w, new_width))
            if edge in ("bottom", "corner"):
                new_height = start_h + event.scenePos().y() - start_y
                if snapping:
                    new_height = snap(new_height, step)
                new_height = min(max_h, max(min_h, new_height))
            if new_width != self.width or new_height != self._live_height:
                self.prepareGeometryChange()
                if new_width != self.width:
                    self.width = new_width
                    self._note_doc = None
                    self._ports_follow_width()
                self._live_height = new_height
                if self.table:
                    self._layout_table_proxy()
                elif self.figure_card:
                    self._layout_figure_proxy()
                elif self.table_viewer:
                    self._layout_table_viewer_proxy()
                elif self.slicer:
                    self._layout_slicer_proxy()
                self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self.note:
            self.start_note_edit()
            event.accept()
            return
        scene = self.scene()
        if (not self.compact and not self.button
                and event.pos().y() < HEADER_H):
            if scene is not None:
                scene.node_rename_requested.emit(self.node.id)
            event.accept()
            return
        if scene is not None:
            scene.node_double_clicked.emit(self.node.id)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._resizing_card:
            self._resizing_card = False
            width = int(self.width)
            height = int(self._live_height or self.body_height)
            self._live_height = None
            scene = self.scene()
            if scene is not None:
                from ..commands import SetParamCommand
                scene.undo_stack.beginMacro("resize card")
                scene.undo_stack.push(SetParamCommand(
                    scene.graph, self.node.id, "width", width))
                scene.undo_stack.push(SetParamCommand(
                    scene.graph, self.node.id, "height", height))
                scene.undo_stack.endMacro()
            if self.table:
                self._layout_table_proxy()
            elif self.figure_card:
                self._layout_figure_proxy()
            elif self.table_viewer:
                self._layout_table_viewer_proxy()
            elif self.slicer:
                self._layout_slicer_proxy()
            event.accept()
            return
        if self._move_suppressed:
            self._move_suppressed = False
            self.setFlag(QGraphicsItem.ItemIsMovable, True)
        was_dragging = self._dragging
        self._dragging = False
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if scene is not None and was_dragging and self._group_starts:
            scene.commit_group_move(self._group_starts)
        self._group_starts = None

    # -------------------------------------------------------------- updates

    def on_status_changed(self) -> None:
        if self.node.status == NodeStatus.RUNNING:
            self._start_pulse()
        else:
            self._stop_pulse()
        self._refresh_tooltip()
        self.update()

    def _refresh_tooltip(self) -> None:
        """Error status always wins the tooltip slot; otherwise fall back to
        the node's own description (currently only surfaced for reroutes)."""
        if self.node.status == NodeStatus.ERROR:
            self.setToolTip(self.node.status_message)
        elif self.link_card and not self.node.description:
            kind = "Goto" if self.goto_card else "From"
            self.setToolTip(f"{kind}: {self._link_card_text()}")
        else:
            self.setToolTip(self.node.description)

    def _start_pulse(self) -> None:
        if self._pulse_anim is not None:
            return
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(700)
        anim.setLoopCount(-1)

        def apply(value: float) -> None:
            # ping-pong
            self._pulse = value * 2 if value <= 0.5 else (1 - value) * 2
            self.update()

        anim.valueChanged.connect(apply)
        anim.start()
        self._pulse_anim = anim

    def _stop_pulse(self) -> None:
        if self._pulse_anim is not None:
            self._pulse_anim.stop()
            self._pulse_anim.deleteLater()
            self._pulse_anim = None
        self._pulse = 0.0
