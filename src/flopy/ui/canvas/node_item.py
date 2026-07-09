"""NodeItem and PortItem — how a node looks and feels on the canvas."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import (
    QAbstractTextDocumentLayout, QBrush, QColor, QFont, QPainter,
    QPainterPath, QPalette, QPen, QTextCursor, QTextDocument,
)
from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsObject, QGraphicsProxyWidget, QHBoxLayout,
    QInputDialog, QLabel, QPlainTextEdit, QStyleOptionGraphicsItem,
    QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from flopy.core import NodeInstance, PortSpec
from flopy.core.node import NodeStatus

from .. import theme

NODE_WIDTH = 170.0
HEADER_H = 26.0
ROW_H = 20.0
PAD_BOTTOM = 8.0
LED_RADIUS = 5.0
LABEL_LOD = 0.5  # hide port names below this zoom

NOTE_TYPE = "flopy.util.note"
NOTE_PAD = 12.0
NOTE_MIN_W, NOTE_MAX_W = 120.0, 1600.0
NOTE_MIN_H, NOTE_MAX_H = 60.0, 2000.0

TABLE_TYPE = "flopy.io.table"
TABLE_MIN_W, TABLE_MAX_W = 220.0, 1600.0
TABLE_MIN_H, TABLE_MAX_H = 140.0, 2000.0

BUTTON_TYPE = "flopy.util.action_button"
BUTTON_W, BUTTON_H = 150.0, 50.0

FIGURE_TYPE = "flopy.viz.show_figure"
FIGURE_MIN_W, FIGURE_MAX_W = 260.0, 1600.0
FIGURE_MIN_H, FIGURE_MAX_H = 200.0, 2000.0

CARD_HANDLE = 14.0  # bottom-right resize grip, shared by notes and tables


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
        self.compact = node.type_id == "flopy.util.reroute"
        self.note = node.type_id == NOTE_TYPE
        self.table = node.type_id == TABLE_TYPE
        self.button = node.type_id == BUTTON_TYPE
        self.figure_card = node.type_id == FIGURE_TYPE
        if self.compact:
            self.width = 28.0
        elif self.note:
            self.width = float(node.params.get("width", 280))
        elif self.table:
            self.width = min(TABLE_MAX_W, max(
                TABLE_MIN_W, float(node.params.get("width", 320))))
        elif self.button:
            self.width = BUTTON_W
        elif self.figure_card:
            self.width = min(FIGURE_MAX_W, max(
                FIGURE_MIN_W, float(node.params.get("width", 420))))
        else:
            self.width = NODE_WIDTH
        self._note_doc: QTextDocument | None = None
        self._resizing_card = False
        self._resize_start = (0.0, 0.0, 0.0, 0.0)  # scene x/y, width/height
        self._live_height: float | None = None  # transient, while drag-resizing
        self._note_editor: QGraphicsProxyWidget | None = None
        self._note_editor_widget: QPlainTextEdit | None = None
        self._closing_note_edit = False
        self._table_widget: QTableWidget | None = None
        self._table_proxy: QGraphicsProxyWidget | None = None
        self._syncing_table = False
        self._figure_view = None
        self._figure_proxy: QGraphicsProxyWidget | None = None
        self._figure_placeholder: QLabel | None = None
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        self.setPos(*node.pos)

        self.input_ports: dict[str, PortItem] = {}
        self.output_ports: dict[str, PortItem] = {}
        self._drag_start_positions: dict[str, tuple[float, float]] = {}
        self._pulse = 0.0
        self._pulse_anim: Optional[QVariantAnimation] = None
        self.rebuild_ports()
        if self.table:
            self._build_table_widget()
        if self.figure_card:
            self._build_figure_widget()

    # ------------------------------------------------------------- geometry

    @property
    def body_height(self) -> float:
        if self.compact:
            return 24.0
        if self.button:
            return BUTTON_H
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
            self.update()
            return
        if self.figure_card:
            self.prepareGeometryChange()
            self.width = min(FIGURE_MAX_W, max(
                FIGURE_MIN_W, float(self.node.params.get("width", 420))))
            self._layout_figure_proxy()
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

    def _table_data(self) -> dict:
        """The grid as {"columns": [...], "rows": [[...], ...]}, tolerant of
        hand-edited JSON (dropped/short rows, missing keys)."""
        import json
        raw = self.node.params.get("data", "")
        try:
            parsed = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            parsed = {}
        columns = [str(c) for c in (parsed.get("columns") or ["A", "B"])]
        raw_rows = parsed.get("rows") or [["" for _ in columns]]
        rows = []
        for row in raw_rows:
            row = [str(v) if v is not None else "" for v in row][:len(columns)]
            row += [""] * (len(columns) - len(row))
            rows.append(row)
        return {"columns": columns, "rows": rows}

    def _build_table_widget(self) -> None:
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
        for button in (add_row, del_row, add_col, del_col):
            button.setAutoRaise(True)
            trow.addWidget(button)
        trow.addStretch(1)
        layout.addWidget(toolbar)

        grid = QTableWidget()
        grid.horizontalHeader().setDefaultSectionSize(72)
        grid.verticalHeader().setDefaultSectionSize(22)
        grid.verticalHeader().setFixedWidth(28)
        grid.setStyleSheet(
            f"QTableWidget {{ background: {theme.NODE_BODY.name()};"
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
        grid.itemChanged.connect(self._on_table_item_changed)
        grid.horizontalHeader().sectionDoubleClicked.connect(
            self._table_rename_column)

        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(host)
        self._table_proxy = proxy
        self._table_widget = grid
        self._sync_table_widget()
        self._layout_table_proxy()

    def _sync_table_widget(self) -> None:
        grid = self._table_widget
        if grid is None:
            return
        self._syncing_table = True
        try:
            data = self._table_data()
            columns, rows = data["columns"], data["rows"]
            grid.setRowCount(len(rows))
            grid.setColumnCount(len(columns))
            grid.setHorizontalHeaderLabels(columns)
            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    item = grid.item(r, c)
                    if item is None:
                        item = QTableWidgetItem()
                        grid.setItem(r, c, item)
                    if item.text() != value:
                        item.setText(value)
        finally:
            self._syncing_table = False

    def _current_grid(self) -> dict:
        grid = self._table_widget
        columns = [
            grid.horizontalHeaderItem(c).text()
            if grid.horizontalHeaderItem(c) is not None else f"col{c}"
            for c in range(grid.columnCount())
        ]
        rows = []
        for r in range(grid.rowCount()):
            row = []
            for c in range(grid.columnCount()):
                item = grid.item(r, c)
                row.append(item.text() if item is not None else "")
            rows.append(row)
        return {"columns": columns, "rows": rows}

    def _commit_table_data(self, data: dict) -> None:
        import json
        scene = self.scene()
        if scene is None:
            return
        from ..commands import SetParamCommand
        new_json = json.dumps(data)
        if new_json == self.node.params.get("data"):
            return
        scene.undo_stack.push(SetParamCommand(
            scene.graph, self.node.id, "data", new_json))

    def _on_table_item_changed(self, _item) -> None:
        if self._syncing_table:
            return
        self._commit_table_data(self._current_grid())

    def _table_add_row(self) -> None:
        data = self._table_data()
        data["rows"].append(["" for _ in data["columns"]])
        self._commit_table_data(data)

    def _table_remove_row(self) -> None:
        data = self._table_data()
        if len(data["rows"]) > 1:
            data["rows"].pop()
        self._commit_table_data(data)

    def _table_add_column(self) -> None:
        data = self._table_data()
        data["columns"].append(self._next_column_name(data["columns"]))
        for row in data["rows"]:
            row.append("")
        self._commit_table_data(data)

    def _table_remove_column(self) -> None:
        data = self._table_data()
        if len(data["columns"]) > 1:
            data["columns"].pop()
            for row in data["rows"]:
                row.pop()
        self._commit_table_data(data)

    def _table_rename_column(self, index: int) -> None:
        data = self._table_data()
        if index >= len(data["columns"]):
            return
        current = data["columns"][index]
        name, ok = QInputDialog.getText(
            None, "Rename column", "Column name", text=current)
        if ok and name and name != current:
            data["columns"][index] = name
            self._commit_table_data(data)

    # -------------------------------------------------------------- figure

    def _figure_proxy_rect(self) -> QRectF:
        height = max(0.0, self.body_height - HEADER_H - CARD_HANDLE)
        return QRectF(0, HEADER_H, self.width, height)

    def _layout_figure_proxy(self) -> None:
        if self._figure_proxy is not None:
            self._figure_proxy.setGeometry(self._figure_proxy_rect())

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

        self._figure_view = FigureView()
        self._figure_view.hide()
        layout.addWidget(self._figure_view, 1)

        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(host)
        self._figure_proxy = proxy
        self._layout_figure_proxy()

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
        self._figure_view.set_figure(figure)
        self._figure_view.show()

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
        return QRectF(-2, -2, self.width + 4, self.body_height + 4)

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
        if self.compact:
            for spec in self.node.spec.inputs:
                port = PortItem(self, spec)
                port.setPos(0, self.body_height / 2)
                self.input_ports[spec.name] = port
            for spec in self.node.spec.outputs:
                port = PortItem(self, spec)
                port.setPos(self.width, self.body_height / 2)
                self.output_ports[spec.name] = port
            self.update()
            return
        if self.table or self.figure_card:
            for spec in self.node.spec.inputs:
                port = PortItem(self, spec)
                port.setPos(0, HEADER_H / 2)
                self.input_ports[spec.name] = port
            for spec in self.node.spec.outputs:
                port = PortItem(self, spec)
                port.setPos(self.width, HEADER_H / 2)
                self.output_ports[spec.name] = port
            self.update()
            return
        for i, spec in enumerate(self.node.spec.inputs):
            port = PortItem(self, spec)
            port.setPos(0, HEADER_H + ROW_H * (i + 0.5))
            self.input_ports[spec.name] = port
        for i, spec in enumerate(self.node.spec.outputs):
            port = PortItem(self, spec)
            port.setPos(self.width, HEADER_H + ROW_H * (i + 0.5))
            self.output_ports[spec.name] = port
        self.update()

    def port_item(self, name: str, direction: str) -> Optional[PortItem]:
        table = self.input_ports if direction == "input" else self.output_ports
        return table.get(name)

    # ------------------------------------------------------------- painting

    def paint(self, painter: QPainter,
              option: QStyleOptionGraphicsItem, widget=None) -> None:
        lod = option.levelOfDetailFromTransform(painter.worldTransform())
        if self.compact:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(theme.SELECTION_OUTLINE if self.isSelected()
                                else theme.NODE_BORDER, 1.5))
            painter.setBrush(QBrush(theme.NODE_HEADER))
            painter.drawRoundedRect(
                QRectF(0, 0, self.width, self.body_height), 10, 10)
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
        if self.figure_card:
            self._paint_figure_card(painter)
            return
        rect = QRectF(0, 0, self.width, self.body_height)

        body = QPainterPath()
        body.addRoundedRect(rect, 7, 7)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillPath(body, theme.NODE_BODY)
        outline = QPen(theme.SELECTION_OUTLINE if self.isSelected()
                       else theme.NODE_BORDER,
                       2.0 if self.isSelected() else 1.2)
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
        painter.fillPath(header.simplified(), theme.NODE_HEADER)

        painter.setPen(QPen(theme.NODE_TEXT))
        font = painter.font()
        font.setPointSizeF(9.0)
        font.setBold(True)
        painter.setFont(font)
        label_rect = QRectF(10, 0, width - 30, HEADER_H)
        label = painter.fontMetrics().elidedText(
            self.node.label, Qt.ElideRight, int(label_rect.width()))
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
            painter.setBrush(QBrush(theme.NODE_HEADER))
            painter.drawEllipse(
                QRectF(led_center_x - 2, HEADER_H / 2 - 2, 4, 4))

    def _paint_table(self, painter: QPainter) -> None:
        rect = QRectF(0, 0, self.width, self.body_height)
        painter.setRenderHint(QPainter.Antialiasing)
        body = QPainterPath()
        body.addRoundedRect(rect, 7, 7)
        painter.fillPath(body, theme.NODE_BODY)
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
                         f"▶  {self.node.label}")

    def _paint_figure_card(self, painter: QPainter) -> None:
        rect = QRectF(0, 0, self.width, self.body_height)
        painter.setRenderHint(QPainter.Antialiasing)
        body = QPainterPath()
        body.addRoundedRect(rect, 7, 7)
        painter.fillPath(body, theme.NODE_BODY)
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

    def _paint_note(self, painter: QPainter) -> None:
        rect = QRectF(0, 0, self.width, self.body_height)
        painter.setRenderHint(QPainter.Antialiasing)
        body = QColor(theme.NODE_BODY)
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
        return NOTE_MIN_W, NOTE_MAX_W, NOTE_MIN_H, NOTE_MAX_H

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            scene = self.scene()
            if scene is not None:
                scene.node_item_moved(self.node.id)
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:
        if self.button and event.button() == Qt.LeftButton \
                and not self.isSelected():
            # unselected: a plain left-click fires the action instead of
            # selecting/dragging. Right-click (context menu) still selects it
            # per the usual flow; once selected, left-click/drag moves it.
            scene = self.scene()
            if scene is not None:
                scene.button_fired.emit(self.node.id)
            event.accept()
            return
        if (self.note or self.table or self.figure_card) and self.isSelected() \
                and self._handle_rect().contains(event.pos()):
            self._resizing_card = True
            self._resize_start = (event.scenePos().x(), event.scenePos().y(),
                                  self.width, self.body_height)
            self._live_height = self.body_height
            event.accept()
            return
        super().mousePressEvent(event)
        scene = self.scene()
        if scene is not None:
            self._drag_start_positions = {
                item.node.id: (item.pos().x(), item.pos().y())
                for item in scene.selected_node_items() + [self]
            }

    def mouseMoveEvent(self, event) -> None:
        if self._resizing_card:
            min_w, max_w, min_h, max_h = self._resize_bounds()
            start_x, start_y, start_w, start_h = self._resize_start
            new_width = min(max_w, max(
                min_w, start_w + event.scenePos().x() - start_x))
            new_height = min(max_h, max(
                min_h, start_h + event.scenePos().y() - start_y))
            if new_width != self.width or new_height != self._live_height:
                self.prepareGeometryChange()
                if new_width != self.width:
                    self.width = new_width
                    self._note_doc = None
                self._live_height = new_height
                if self.table:
                    self._layout_table_proxy()
                elif self.figure_card:
                    self._layout_figure_proxy()
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
            event.accept()
            return
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if scene is None or not self._drag_start_positions:
            return
        moves = {}
        for node_id, old in self._drag_start_positions.items():
            item = scene.node_items.get(node_id)
            if item is None:
                continue
            new = (item.pos().x(), item.pos().y())
            if new != old:
                moves[node_id] = (old, new)
        self._drag_start_positions = {}
        if moves:
            scene.push_move_command(moves)

    # -------------------------------------------------------------- updates

    def on_status_changed(self) -> None:
        if self.node.status == NodeStatus.RUNNING:
            self._start_pulse()
        else:
            self._stop_pulse()
        self.update()

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
