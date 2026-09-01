"""NodeItem and PortItem — how a node looks and feels on the canvas."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    QEvent, QPointF, QRect, QRectF, Qt, QTimer, QUrl, QVariantAnimation,
)
from PySide6.QtGui import (
    QAbstractTextDocumentLayout, QBrush, QColor, QDesktopServices, QFont,
    QFontMetrics, QPainter, QPainterPath, QPalette, QPen, QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QApplication, QGraphicsItem, QGraphicsObject, QGraphicsProxyWidget,
    QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QStyleOptionGraphicsItem,
    QTableView, QToolButton, QVBoxLayout, QWidget,
)

from flograph.core import NodeInstance, PortSpec, PortType
from flograph.core.links import link_label, source_id
from flograph.core.node import NodeStatus
from flograph.core.ports import FLOW_INPUT, FLOW_OUTPUT, is_flow

from .. import theme
from ..data_table import DataTableView
from ..slicer_list import SlicerListWidget, SlicerToolbar, selected_param_values
from . import marks
from .grid import EDGE_MARGIN, grid_step, snap, snap_point, snapping_active
from .stacking import NODE_Z, z_for

NODE_WIDTH = 170.0
HEADER_H = 26.0
ROW_H = 20.0
PAD_BOTTOM = 8.0
LED_RADIUS = 5.0

# Compact ("square") plain nodes — Settings > Canvas > Compact nodes, on by
# default. A node with no card kind is only ever a set of connections, so it
# is drawn the way most node-graph tools draw one: a fixed square carrying a
# mark, its name floating above, pins either side, status light below. The
# size never varies with port count the way the wide box's did, which is the
# whole point — the eye reads the shape of the graph instead of the shape of
# the boxes.
#
# The item's origin stays at the square's *top-left*, exactly where the wide
# node's header started. Everything downstream — link lines anchoring to
# (width, body_height/2), frames, align/distribute, fit, grid snap — keys off
# width/body_height and off the item position, so keeping the origin put is
# what lets an existing project file open with its nodes still where they
# were. The name above and the status row below live outside the body and
# show up in boundingRect alone.
COMPACT_W = 60.0
COMPACT_MIN_H = 60.0
COMPACT_NAME_H = 12.0          # one line of name above the square
COMPACT_NAME_GAP = 4.0
COMPACT_NAME_MAX_W = 120.0     # names may overhang the square on both sides
COMPACT_NAME_FONT_SIZE = 8.5
COMPACT_STATUS_H = 14.0
COMPACT_STATUS_GAP = 2.0
COMPACT_PORT_TOP = 10.0        # highest a pin stack may start; see _stack_ports
COMPACT_MARK_INSET = 16.0      # the mark gets the middle 28 x 28
COMPACT_IMAGE_INSET = 2.0      # a picture gets nearly the lot: 56 x 56
COMPACT_TEXT_FONT_SIZE = 13.0  # a mark_text override, drawn in the square

# The only QGraphicsItem changes NodeItem.itemChange acts on; see there.
_HANDLED_ITEM_CHANGES = frozenset({
    QGraphicsItem.ItemPositionChange,
    QGraphicsItem.ItemPositionHasChanged,
    QGraphicsItem.ItemSelectedHasChanged,
    # Rare — only a collapsing frame folding its contents away, or opening
    # again — but an animated card that is hidden rather than flattened
    # would otherwise carry on rendering frames nobody can see.
    QGraphicsItem.ItemVisibleHasChanged,
})
# A deactivated node is faded rather than hidden: it is still part of the
# graph, still wired, and still the thing you click to switch back on.
DEACTIVATED_OPACITY = 0.35
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
REPORT_MIN_W, REPORT_MAX_W = 240.0, 1600.0
REPORT_MIN_H, REPORT_MAX_H = 140.0, 2000.0
WIKI_MIN_W, WIKI_MAX_W = 260.0, 1600.0
WIKI_MIN_H, WIKI_MAX_H = 160.0, 2000.0
TABLE_VIEWER_MIN_W, TABLE_VIEWER_MAX_W = 260.0, 1600.0
TABLE_VIEWER_MIN_H, TABLE_VIEWER_MAX_H = 200.0, 2000.0

KPI_TYPE = "flograph.viz.card"
KPI_MIN_W, KPI_MAX_W = 140.0, 800.0
KPI_MIN_H, KPI_MAX_H = 80.0, 500.0

SLICER_TYPE = "flograph.viz.slicer"
SLICER_MIN_W, SLICER_MAX_W = 140.0, 600.0
SLICER_MIN_H, SLICER_MAX_H = 120.0, 2000.0

IMAGE_TYPE = "flograph.viz.image"
IMAGE_MIN_W, IMAGE_MAX_W = 60.0, 2400.0
IMAGE_MIN_H, IMAGE_MAX_H = 60.0, 2400.0

# Input controls (slider, toggle, date, ...). One card path for every shape:
# the widget comes from ui.controls, keyed on the node's NODE["control"].
CONTROL_MIN_W, CONTROL_MAX_W = 120.0, 800.0
CONTROL_MIN_H, CONTROL_MAX_H = 48.0, 600.0

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
    IMAGE_TYPE: "image",
}


def card_kind(node) -> Optional[str]:
    """The rich-card kind for a node: its explicit NODE['card'] marker, else a
    legacy fallback keyed on the built-in type_id. None = an ordinary node."""
    return node.spec.card or _LEGACY_CARD_BY_TYPE_ID.get(node.type_id)


# Card kinds that say what a node *is* without changing how it draws.
#
# NODE["card"] normally means "this node renders its own content", and the
# canvas reads it that way in three places: the compact square, the mark, and
# which sections the Appearance dialog offers. But the Variables node needs a
# marker only so core.varlinks can recognise it — one that survives forking
# and saving, exactly as core.links recognises "goto"/"from" — and it draws
# nothing of its own. Without this it would be the only Util node that cannot
# be a square, cannot take a mark and has half an Appearance dialog.
IDENTITY_CARDS = frozenset({"vars"})


def renders_plain(node) -> bool:
    """Does this node draw as an ordinary node — square-able, mark-able?

    True for a node with no card at all, and for the identity-only kinds
    above. Ask this rather than `card_kind(node) is None` wherever the
    question is about drawing rather than about a specific card.
    """
    kind = card_kind(node)
    return kind is None or kind in IDENTITY_CARDS


# Card kinds with a real, expensive embedded widget. Kept for the tests that
# still name it; the live gate on the canvas-preview toggle (idea #21) is now
# NodeItem.foldable() — switching the preview off folds the whole card down to
# an icon, and every card with a rendered body bar the KPI can do that. "grid"
# (the Table node) is user *input* rather than a computed preview, but folding
# it only hides the spreadsheet widget, never the node's stored data.
PREVIEW_TOGGLABLE_KINDS = {"figure", "webview", "table_viewer", "slicer", "grid"}


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

# Floating port-name pills (Settings > Canvas > Show port names). Deliberately
# the reroute label's dimensions: a small rounded pill of chrome-coloured text
# floating outside the node is already a thing flograph does, and reusing it
# means one visual language rather than two similar-but-different ones.
PORT_LABEL_FONT_SIZE = 7.5
PORT_LABEL_PAD_X = 5.0
PORT_LABEL_H = 14.0
PORT_LABEL_GAP = 7.0  # horizontal gap between the pin and its pill

# Clear air between a node's edge and its pins. Pins used to be centred on
# the edge, so half of every one was buried under the card — which read as
# the pin being part of the border rather than a thing to grab, and on a
# card whose body is a live widget it put the hit area over the content.
# Floating them wholly outside costs nothing and makes the wire ends read as
# terminals. Sized so the pin clears the border with a couple of px to spare.
PORT_EDGE_GAP = 2.5
#: How far outside its body a card's own children may reasonably reach —
#: pins, flow pins, name pills. Past this, boundingRect stops trusting Qt's
#: recursive answer and counts the children itself (see NodeItem.boundingRect).
CHILD_OVERHANG_MAX = 200.0


class NodeBadge(QGraphicsItem):
    """A small status glyph pinned above a node.

    Drawn, not typed. The obvious QGraphicsSimpleTextItem("\N{LOCK}")
    measures a perfectly sensible bounding rect and then paints nothing:
    colour-emoji fonts do not render through the path that item takes, so
    the glyph vanishes silently rather than falling back to tofu. A dozen
    lines of QPainterPath always draw, take the theme's colour, and stay
    sharp at any zoom.

    Badges sit *above* the header rather than inside it because the header
    is already crowded — the collapse chevron, the label, the status LED and
    the temp-edit dot all live there — and a badge has to appear on every
    card kind, including the ones that fill their header differently.
    """

    W, H = 9.0, 11.0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.colour = theme.NODE_SUBTEXT
        self.setVisible(False)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def boundingRect(self) -> QRectF:
        return QRectF(-1.0, -1.0, self.W + 2.0, self.H + 2.0)


class LockBadge(NodeBadge):
    """A padlock: this node cannot be edited or moved."""

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        # the shackle first, so the body's flat top covers where it lands
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(self.colour, 1.3))
        painter.drawArc(QRectF(1.9, 0.7, self.W - 3.8, 8.0), 0, 180 * 16)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self.colour))
        painter.drawRoundedRect(QRectF(0.0, self.H - 6.5, self.W, 6.5),
                                1.5, 1.5)


class HeavyBadge(NodeBadge):
    """A stack of discs: this step is holding a lot of the memory in use.

    Only shown while memory is actually short — a badge that is always there
    is furniture, and this one is meant to answer the question the status bar
    raises. "Which step is doing this" is the one thing a person can act on
    without knowing how any of this works: it is the node to give a Max rows
    to, or to filter earlier.
    """

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(self.colour, 1.1))
        painter.setBrush(Qt.NoBrush)
        # three ellipses stacked, drawn bottom-up so each hides the last's
        # lower arc and it reads as a pile rather than three separate rings
        for i in (2, 1, 0):
            painter.drawEllipse(
                QRectF(0.6, 0.8 + i * 3.3, self.W - 1.2, 3.6))


class ManualBadge(NodeBadge):
    """A hollow play triangle: this node runs only when somebody asks it to.

    Deliberately the same family as the freeze badge — one is the pause and
    one is the press — because the two flags are neighbours in meaning and a
    person who has met one should be able to guess the other. Hollow rather
    than filled so it cannot be mistaken for a status light: the LED says
    what the node is doing now, and this says what it will do next time Run
    All is pressed.
    """

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(Qt.NoBrush)
        pen = QPen(self.colour, 1.3)
        pen.setJoinStyle(Qt.MiterJoin)   # a sharp nose, not a rounded blob
        painter.setPen(pen)
        path = QPainterPath()
        path.moveTo(1.2, 0.9)
        path.lineTo(self.W - 1.0, self.H / 2.0)
        path.lineTo(1.2, self.H - 0.9)
        path.closeSubpath()
        painter.drawPath(path)


class FreezeBadge(NodeBadge):
    """A pause glyph: this node's output is pinned and it will not re-run.

    Pause rather than a snowflake because that is what it means to the
    person using it — the node is held, and pressing Run All will not
    disturb it.
    """

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(self.colour))
        bar = (self.W - 3.0) / 2.0
        for x in (0.0, bar + 3.0):
            painter.drawRoundedRect(QRectF(x, 0.5, bar, self.H - 1.0),
                                    1.0, 1.0)

CARD_SCALE_MIN, CARD_SCALE_MAX = 25.0, 400.0  # "scale" param, in percent

def _port_label_font() -> QFont:
    font = QFont()
    font.setPointSizeF(PORT_LABEL_FONT_SIZE)
    return font


def port_labels_on(node, scene) -> bool:
    """Whether `node` should float its port names.

    The node's own setting wins; `None` — which is every node until somebody
    right-clicks one — follows the canvas-wide preference. That is what lets
    the global toggle stay meaningful after a node has been singled out: the
    per-node choice is recorded as an *override*, not as a copy of whatever
    the global happened to be at the time.

    Holding the reveal key beats both, for as long as it is held. It is a
    look, not a setting: nothing is written down, and letting go puts every
    node back to whichever of the two above it was answering to.
    """
    if getattr(scene, "revealing_port_labels", False):
        return True
    own = getattr(node, "port_labels", None)
    if own is not None:
        return bool(own)
    return bool(getattr(scene, "port_labels_enabled", False))


def flow_pins_on(node, scene) -> bool:
    """Whether `node` should show its two flow pins.

    The same tri-state as `port_labels_on`, and revealed by the same held
    key — a flow pin is a thing you go looking for exactly when you are
    looking at what connects to what. It differs in one way: a drag from
    some *other* node's flow pin turns them on everywhere for the duration,
    because a wire you cannot see where to drop is a wire you cannot draw.

    Hidden by default, unlike a port name, which is merely off by default:
    the ordering these express is the exception in a flow, and two more pins
    on every node is a permanent cost to the great majority of canvases that
    never draw a single order edge. A pin that *has* an order edge on it is
    drawn whatever this returns — see NodeItem._apply_port_visibility.
    """
    if getattr(scene, "revealing_port_labels", False):
        return True
    if getattr(scene, "drawing_order_edge", False):
        return True
    own = getattr(node, "flow_pins", None)
    if own is not None:
        return bool(own)
    return bool(getattr(scene, "flow_pins_enabled", False))


def _led_corner(radius: float) -> float:
    """How rounded the status light's corners are, for a light of `radius`.

    The light is a rounded square rather than a circle so that it is never
    mistaken for a port pin, which is a circle and lives a few pixels away
    on the same node. That only works if it stays visibly square, so the
    corner is capped in absolute pixels rather than scaled all the way up:
    a bigger light reads as squarer, and only the tiny ones a collapsed
    frame packs into its matrix scale their corners down to stay drawable.
    """
    return min(2.0, radius * 0.4)


def paint_status_led(painter: QPainter, cx: float, cy: float, *,
                     status: NodeStatus, progress: float, pulse: float,
                     stale: bool, behind: QColor,
                     radius: float = LED_RADIUS) -> None:
    """The status light, centred on (cx, cy).

    Free-standing rather than a NodeItem method because a collapsed frame
    draws the same indicator twice over — once per contained node in its
    matrix, and once for its own aggregate — and two implementations of "what
    a status light looks like" would drift the moment either was touched.

    `behind` is whatever the LED is sitting on, and is only used to hollow
    out a stale-but-done node — in the wide node's header that is the header
    colour, but a square node's LED hangs below the body on bare canvas,
    where the header colour would read as a coloured pip rather than a hole.
    """
    led_color = QColor(theme.status_color(status))
    running = status == NodeStatus.RUNNING
    # A node that reports a fraction gets a light that fills; one that
    # never calls ctx.progress() keeps the pulse. Indeterminate and
    # determinate are the honest distinction — a progress bar here would be
    # new chrome to reconcile with the chevron, the temp-edit dot and every
    # collapsed card.
    fraction = progress if running else 0.0
    if running and not fraction:
        led_color.setAlphaF(0.35 + 0.65 * pulse)
    painter.setPen(QPen(theme.NODE_BORDER, 1))
    painter.setBrush(QBrush(led_color))
    led_rect = QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius)
    corner = _led_corner(radius)
    if fraction:
        track = QColor(led_color)
        track.setAlphaF(0.25)
        painter.setBrush(QBrush(track))
        painter.drawRoundedRect(led_rect, corner, corner)
        # Qt angles are sixteenths of a degree, zero at 3 o'clock and
        # rising anticlockwise, so filling clockwise from noon is a
        # negative span starting at 90. A pie is only ever an arc of an
        # ellipse, so the square is filled by clipping to its own outline
        # and swinging a pie big enough to reach past the corners.
        painter.save()
        clip = QPainterPath()
        clip.addRoundedRect(led_rect, corner, corner)
        painter.setClipPath(clip)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(led_color))
        reach = radius * 0.45
        painter.drawPie(led_rect.adjusted(-reach, -reach, reach, reach),
                        90 * 16, -int(fraction * 360 * 16))
        painter.restore()
        painter.setPen(QPen(theme.NODE_BORDER, 1))
        painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(led_rect, corner, corner)
    if stale and status == NodeStatus.DONE:
        # stale: hollow out the green LED
        hole = radius * 0.4
        hole_corner = _led_corner(hole)
        painter.setBrush(QBrush(behind))
        painter.drawRoundedRect(QRectF(cx - hole, cy - hole, 2 * hole, 2 * hole),
                                hole_corner, hole_corner)


def compact_on(node, scene) -> bool:
    """Whether `node` draws as the compact square.

    Same tri-state as port_labels_on: the node's own choice wins, None
    follows the canvas-wide preference. A card kind never draws as a square
    whatever either of them says — its size is its content's. An
    identity-only card has no content, so it still can.
    """
    if not renders_plain(node):
        return False
    own = getattr(node, "compact_view", None)
    if own is not None:
        return bool(own)
    return bool(getattr(scene, "compact_nodes", True))


class CardTextEditor(QPlainTextEdit):
    """The in-place markdown editor over a Note or Report card.

    A QPlainTextEdit apart from its context menu, which on a Report card
    carries an **Insert** submenu above the usual undo/cut/copy/paste. The
    embed syntax is the one thing about a report card you cannot guess, and
    right-clicking where you are typing is where you look for it — the
    equivalent menu on a report *page* is a toolbar button, which a card has
    no room for.
    """

    def __init__(self, text: str, item: "NodeItem") -> None:
        super().__init__(text)
        self._item = item

    def contextMenuEvent(self, event) -> None:
        # the standard menu's actions are already wired to this editor's
        # own slots, so exec() runs whichever the user picks; only the
        # inserts need handling here
        menu = self.createStandardContextMenu()
        inserts = self._item.add_insert_menu(menu)
        chosen = menu.exec(event.globalPos())
        if chosen in inserts:
            self.insert_embed(inserts[chosen])
        event.accept()

    def insert_embed(self, label: str) -> None:
        from ..report.render import embed_line
        cursor = self.textCursor()
        cursor.insertText(embed_line(label, cursor.atBlockStart()))
        self.setTextCursor(cursor)
        self.setFocus()


class PortItem(QGraphicsItem):
    """A circular pin. Wire drags start here and are managed by the scene."""

    RADIUS = 5.5
    # The flow pin is drawn smaller: it is on every node whether or not
    # anybody uses it, so it has to stay quieter than the pins that carry
    # the data. See NodeItem._layout_flow_ports.
    FLOW_RADIUS = 3.5

    def __init__(self, node_item: "NodeItem", spec: PortSpec) -> None:
        super().__init__(node_item)
        self.node_item = node_item
        self.spec = spec
        self._hover = False
        self._drag_tint: Optional[bool] = None  # None / valid / invalid
        # Filled or hollow. Held on the item rather than asked of the graph
        # in paint(): a pin is repainted on every pan, zoom and node update,
        # and there are four of these per node, so a model query here is
        # thousands of calls a frame for an answer that only changes when a
        # wire or a Goto/From link does. The scene refreshes it there.
        # Outputs never consult it — an output pin always draws filled.
        self._connected = False
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        # card-type nodes (figure/table/kpi/slicer) draw no port name text —
        # this is the only way to tell ports apart on those, so always set it
        self.setToolTip(spec.name)

    @property
    def node_id(self) -> str:
        return self.node_item.node.id

    @property
    def is_flow(self) -> bool:
        return self.spec.type == PortType.FLOW

    @property
    def base_radius(self) -> float:
        return self.FLOW_RADIUS if self.is_flow else self.RADIUS

    @property
    def has_edge(self) -> bool:
        """Whether a wire actually terminates on this pin.

        The same cached answer `paint` uses to draw an input filled or
        hollow, read for a second purpose: it is what keeps a flow pin on
        screen when the flow pins are otherwise hidden.
        """
        return self._connected

    def set_drag_tint(self, valid: Optional[bool]) -> None:
        if valid != self._drag_tint:
            self._drag_tint = valid
            self.update()

    def refresh_connected(self) -> None:
        """Re-read whether anything feeds this pin. Called wherever the edge
        set moves — a wire made or broken, a Goto/From link re-derived, a
        node's ports rebuilt — never from paint()."""
        scene = self.scene()
        connected = (scene.is_port_connected(self.node_id, self.spec)
                     if scene is not None else False)
        if connected != self._connected:
            self._connected = connected
            self.update()

    def _label_shown(self) -> bool:
        """Whether to float this port's name beside it.

        Off unless the scene says otherwise, and never while the canvas is
        flattened for zoom — the pins themselves aren't drawn at that
        distance, so their names would be labels for nothing.
        """
        if self.is_flow:
            # Never labelled: the name would be the same word on every node
            # on the canvas, and the pin's own tooltip already says what it
            # is for.
            return False
        return port_labels_on(self.node_item.node, self.scene()) \
            and not self.node_item._flat

    def label_text(self) -> str:
        """What the pill says.

        Normally the port's name. When this pin is the one left showing for
        a collapsed node, its own name would be a lie by omission — it reads
        as though that is the only port there is. It says how many are
        gathered behind it instead, matching the tooltip.
        """
        item = self.node_item
        siblings = (item.input_ports if self.spec.direction.value == "input"
                    else item.output_ports)
        if item.ports_collapsed and len(siblings) > 1:
            side = "inputs" if self.spec.direction.value == "input" \
                else "outputs"
            return f"{len(siblings)} {side}"
        return self.spec.name

    def _label_rect(self) -> Optional[QRectF]:
        """Local-coordinate rect of the name pill: outside the node on the
        port's own side, so an input's name reads leftwards away from the
        card and an output's rightwards, and neither covers the content."""
        if not self._label_shown():
            return None
        metrics = QFontMetrics(_port_label_font())
        width = metrics.horizontalAdvance(self.label_text()) + PORT_LABEL_PAD_X * 2
        outward = self.spec.direction.value == "output"
        x = PORT_LABEL_GAP if outward else -PORT_LABEL_GAP - width
        return QRectF(x, -PORT_LABEL_H / 2, width, PORT_LABEL_H)

    def boundingRect(self) -> QRectF:
        base = QRectF(-10, -10, 20, 20)
        label = self._label_rect()
        return base if label is None else base.united(label)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        label = self._label_rect()
        if label is not None:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(theme.NODE_BORDER, 1))
            painter.setBrush(QBrush(theme.NODE_HEADER))
            painter.drawRoundedRect(label, label.height() / 2,
                                    label.height() / 2)
            painter.setPen(QPen(theme.NODE_SUBTEXT))
            painter.setFont(_port_label_font())
            painter.drawText(label, Qt.AlignCenter, self.label_text())
        base = self.base_radius
        radius = base + (2 if self._hover else 0)
        color = theme.wire_color(self.spec.type)
        if self._drag_tint is True:
            color = theme.WIRE_VALID
            radius = base + 2.5
        elif self._drag_tint is False:
            color = theme.WIRE_INVALID
        painter.setPen(QPen(theme.NODE_BORDER, 1.2))
        if self._connected or self.spec.direction.value == "output":
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


class DropHintOutline(QGraphicsItem):
    """The dashed ring drawn around a node while it is under a dragged one:
    letting go here will replace it. A child item rather than a pen choice
    inside every _paint_* — there are too many node kinds to repeat the
    rule in each, and a transient hint is not worth that kind of surface."""

    def __init__(self, parent: "NodeItem") -> None:
        super().__init__(parent)
        # a hint must never steal a click or a hover from what it rings
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setAcceptHoverEvents(False)

    def boundingRect(self) -> QRectF:
        item = self.parentItem()
        pad = 4.0
        return QRectF(-pad, -pad, item.width + 2 * pad, item.body_height + 2 * pad)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        item = self.parentItem()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(theme.WIRE_VALID, 1.8, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(-3.0, -3.0,
                                       item.width + 6.0, item.body_height + 6.0),
                                7.0, 7.0)


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
        self.report_card = kind == "report"
        # a Markdown Wiki card: a QTextBrowser in a proxy, same chrome,
        # geometry and resizing as the report card — it differs only in the
        # embedded widget (a WikiView) and that navigating it is a cosmetic
        # param edit, not a re-render of wired inputs.
        self.wiki_card = kind == "wiki"
        self.kpi_card = kind == "kpi"
        # painted straight onto the item like the KPI card, no proxy widget —
        # see ui.canvas.image_card for why that matters. A PDF card is the
        # same card with a rendered page where the artwork goes: identical
        # chrome, geometry, resizing and Appearance sections, so it rides the
        # image card's flag and differs only where the content is produced
        # (`_card_image`, `_sync_card_image`, the empty-state hint).
        self.pdf_card = kind == "pdf"
        self.image_card = kind == "image" or self.pdf_card
        self.slicer = kind == "slicer"
        self.control = kind == "control"
        # Goto/From: the two ends of a link the canvas doesn't draw
        self.goto_card = kind == "goto"
        self.from_card = kind == "from"
        self.link_card = self.goto_card or self.from_card
        self._link_partners: set[str] = set()  # highlighted with this node
        # the replace-target ring while a dragged node hovers over this one
        # (see DropHintOutline); built lazily, shown for the drag only
        self._drop_hint_frame: DropHintOutline | None = None
        self.broken = node.spec.broken
        # Draws as an ordinary node — no card kind at all, or an
        # identity-only one (see renders_plain). The only kind the compact
        # square applies to. Deliberately not called "compact": that name is
        # taken, a few lines up, by the reroute dot.
        self.plain = renders_plain(node)
        # Whether this node is drawing as a square right now. Held on the
        # item rather than asked of the scene from paint()/boundingRect(),
        # which Qt calls on every pan and zoom, for an answer that changes
        # only when the setting does. apply_compact (a plain node's shape)
        # and _set_folded (a card with its preview switched off) are the
        # writers; it starts matching the shipping defaults, so an item
        # built outside a scene (tests, previews) looks like the real thing.
        self._square = self.plain
        self._name_cache: tuple[str, ...] | None = None  # wrapped label
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
        elif self.report_card:
            self.width = min(REPORT_MAX_W, max(
                REPORT_MIN_W, float(node.params.get("width", 460))))
        elif self.wiki_card:
            self.width = min(WIKI_MAX_W, max(
                WIKI_MIN_W, float(node.params.get("width", 520))))
        elif self.kpi_card:
            self.width = min(KPI_MAX_W, max(
                KPI_MIN_W, float(node.params.get("width", 220))))
        elif self.image_card:
            self.width = min(IMAGE_MAX_W, max(
                IMAGE_MIN_W, float(node.params.get("width", 320))))
        elif self.slicer:
            self.width = min(SLICER_MAX_W, max(
                SLICER_MIN_W, float(node.params.get("width", 200))))
        elif self.control:
            self.width = min(CONTROL_MAX_W, max(
                CONTROL_MIN_W, float(node.params.get(
                    "width", self._control_default_size()[0]))))
        else:
            self.width = COMPACT_W if self._square else NODE_WIDTH
        # A card whose canvas preview is switched off folds down to a plain
        # icon — the same square a compact node draws — rather than sitting
        # on the canvas as a full-size empty frame. _expanded_width is the
        # width to grow back into; _folded drives the square geometry and is
        # kept in lockstep with node.canvas_preview_enabled (see
        # set_preview_enabled / _set_folded).
        self._expanded_width = self.width
        self._folded = self.foldable() and not node.canvas_preview_enabled
        if self._folded:
            self._square = True
            self.width = COMPACT_W
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
        self._note_link_press: QPointF | None = None  # link hit on press
        self._table_widget = None   # SpreadsheetView (grid cards only)
        self._table_model = None    # SheetModel (grid cards only)
        self._table_buttons: tuple = ()
        self._table_expand = None
        self._table_proxy: QGraphicsProxyWidget | None = None
        self._figure_view = None
        self._figure_proxy: QGraphicsProxyWidget | None = None
        self._figure_placeholder: QLabel | None = None
        self._plotly_widget = None  # shared PlotlyView, see _build_plotly_widget
        self._report_view = None      # QTextBrowser (report cards only)
        self._report_animator = None  # plays animated images inside it
        self._report_proxy: QGraphicsProxyWidget | None = None
        self._wiki_view = None        # WikiView (wiki cards only)
        self._wiki_proxy: QGraphicsProxyWidget | None = None
        self._table_viewer_view: "DataTableView | None" = None
        self._table_viewer_proxy: QGraphicsProxyWidget | None = None
        self._table_viewer_placeholder: QLabel | None = None
        self._kpi_value: object = None
        self._kpi_has_value = False
        self._image: "CardImage | None" = None  # built lazily, see _card_image
        # the compact square's picture-instead-of-a-mark, same deal
        self._mark_image: "CardImage | None" = None
        self._image_run_source: Optional[str] = None  # see _image_source
        # A PDF card's page chevrons: (prev, next) in item coordinates, set
        # by the paint that drew them and None when there are none on screen,
        # so a click can only ever hit a chevron the user can actually see.
        self._pager: Optional[tuple[QRectF, QRectF]] = None
        self._pager_hover = 0                        # -1 back, +1 forward
        self._slicer_list: SlicerListWidget | None = None
        self._slicer_toolbar: SlicerToolbar | None = None
        self._slicer_proxy: QGraphicsProxyWidget | None = None
        self._slicer_placeholder: QLabel | None = None
        self._control_widget = None  # ControlWidget (control cards only)
        self._control_proxy: QGraphicsProxyWidget | None = None
        # Output preview faded while a re-run for this node is queued or in
        # flight — see set_updating; the main window is the sole writer.
        self._updating = False
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

        # A child item rather than something paint() draws: paint() forks nine
        # ways by card kind, and a padlock has to appear on all nine. A child
        # sits above whatever the branch drew, including the proxy widgets a
        # painter cannot reach.
        self._lock_badge = LockBadge(self)
        self._freeze_badge = FreezeBadge(self)
        self._manual_badge = ManualBadge(self)
        self._heavy_badge = HeavyBadge(self)
        # The node's own two run flags, and the same two as the frames
        # around it are currently applying — kept apart so the node can be
        # drawn as the run will treat it without either overwriting the
        # other. See set_frame_flags.
        self._own_active = bool(node.active)
        self._own_manual = bool(node.manual)
        self._frame_manual = False
        self._frame_inactive = False
        # The same amber as a stale pin: one colour meaning "worth a look,
        # nothing is broken" across the whole app.
        self._heavy_badge.colour = theme.PIN_STALE
        # read by the minimap, which is too small for a badge and has to say
        # the same thing in colour
        self.pin_stale = False

        self.input_ports: dict[str, PortItem] = {}
        self.output_ports: dict[str, PortItem] = {}
        # The flow pins, keyed by direction. Kept out of the two dicts above
        # on purpose: those are the node's *data* ports, and the geometry,
        # the collapse, the labels and everything that counts ports all read
        # them. A pin that carries no value belongs in none of that.
        self.flow_ports: dict[str, PortItem] = {}
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
        if self.report_card:
            self._build_report_widget()
        if self.wiki_card:
            self._build_wiki_widget()
        if self.slicer:
            self._build_slicer_widget()
        if self.control:
            self._build_control_widget()
        if not node.canvas_preview_enabled:
            self._apply_proxy_visibility()  # honor a preview-disabled node loaded from disk
        self._refresh_tooltip()
        # Last: both read state the card kinds above have to have settled,
        # and set_locked refreshes the tooltip a second time on purpose.
        self.set_active(node.active)
        self.set_frozen(node.frozen)
        self.set_manual(node.manual)
        self.set_locked(node.locked)

    # ------------------------------------------------------------- geometry

    @property
    def body_height(self) -> float:
        if self._folded:
            return COMPACT_MIN_H
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
        if self.report_card:
            if self._live_height is not None:
                return self._live_height
            fixed = float(self.node.params.get("height", 340) or 340)
            return min(REPORT_MAX_H, max(REPORT_MIN_H, fixed))
        if self.wiki_card:
            if self._live_height is not None:
                return self._live_height
            fixed = float(self.node.params.get("height", 380) or 380)
            return min(WIKI_MAX_H, max(WIKI_MIN_H, fixed))
        if self.kpi_card:
            if self._live_height is not None:
                return self._live_height
            fixed = float(self.node.params.get("height", 120) or 120)
            return min(KPI_MAX_H, max(KPI_MIN_H, fixed))
        if self.image_card:
            if self._live_height is not None:
                return self._live_height
            fixed = float(self.node.params.get("height", 240) or 240)
            return min(IMAGE_MAX_H, max(IMAGE_MIN_H, fixed))
        if self.slicer:
            if self._live_height is not None:
                return self._live_height
            fixed = float(self.node.params.get("height", 240) or 240)
            return min(SLICER_MAX_H, max(SLICER_MIN_H, fixed))
        if self.control:
            if self._live_height is not None:
                return self._live_height
            default = self._control_default_size()[1]
            fixed = float(self.node.params.get("height", default) or default)
            return min(CONTROL_MAX_H, max(CONTROL_MIN_H, fixed))
        if self._square:
            # Fixed, whatever the port count. A square that grew with its
            # ports would be back to the wide box's problem — nodes of
            # different sizes in a row — for the sake of the handful of nodes
            # that have more than three of them. Those simply run their pins
            # out of the bottom onto the canvas, which _space_card_ports has
            # been doing for cards all along.
            return COMPACT_MIN_H
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

    def note_link_at(self, pos: QPointF) -> str:
        """The href of the Markdown link under `pos` (item coordinates), or
        "" if there is none. The document is painted inset by NOTE_PAD, so
        that offset comes back off before the layout hit-test."""
        if not self.note or self._note_editor is not None:
            return ""
        local = QPointF(pos.x() - NOTE_PAD, pos.y() - NOTE_PAD)
        return self._note_document().documentLayout().anchorAt(local)

    def _open_note_link(self, href: str) -> None:
        """Open a Note card's link in the system browser. Deferred past the
        double-click window by the caller, so a double-click that lands on a
        link edits the card instead of firing the browser."""
        if not href or self._note_editor is not None:
            return
        url = QUrl(href)
        if not url.scheme():
            url = QUrl.fromUserInput(href)  # bare "example.com", "./file.pdf"
        QDesktopServices.openUrl(url)

    def apply_stacking(self) -> None:
        """Take the node's place in the stacking order — its band sits above
        the wires, so a card always covers the wires that reach it."""
        self.setZValue(z_for(NODE_Z, self.node.z))

    def on_params_changed(self, name: Optional[str] = None) -> None:
        """Params drive geometry for notes (text/width) and tables
        (data/width/height); other node kinds ignore param edits.

        `name` is the param that changed, when the caller knows it — some
        cards need to tell one param from another, and None means "assume
        anything could have".
        """
        self._params_changed_impl(name)
        # A folded card holds its square whatever its width param says; the
        # per-kind branches above wrote the open width, which is exactly the
        # size to grow back into, so keep it and re-apply the square.
        if self.foldable():
            if self._folded:
                if self.width != COMPACT_W:
                    self._expanded_width = self.width
                    self.prepareGeometryChange()
                    self.width = COMPACT_W
                    self._ports_follow_width()
            else:
                self._expanded_width = self.width

    def _params_changed_impl(self, name: Optional[str]) -> None:
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
            # Columns/Rows/Fill are layout, not data: re-arrange now rather
            # than making the user re-run to see a grid change.
            self.relayout_figures()
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
        if self.report_card:
            # the text *is* a param, so an edit is both a re-render and
            # possibly a resize
            self.prepareGeometryChange()
            self.width = min(REPORT_MAX_W, max(
                REPORT_MIN_W, float(self.node.params.get("width", 460))))
            self.refresh_report()
            self._layout_report_proxy()
            self._ports_follow_width()
            self.update()
            return
        if self.wiki_card:
            self.prepareGeometryChange()
            self.width = min(WIKI_MAX_W, max(
                WIKI_MIN_W, float(self.node.params.get("width", 520))))
            self.refresh_wiki(name)
            self._layout_wiki_proxy()
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
        if self.image_card:
            # the file path *is* a param, so picking a different image is a
            # param edit — the card redraws without the graph being run
            self.prepareGeometryChange()
            self.width = min(IMAGE_MAX_W, max(
                IMAGE_MIN_W, float(self.node.params.get("width", 320))))
            # Picking a file by hand overrides whatever the last run
            # resolved; the next run puts a wired source back if there still
            # is one. Only the file param does that, though: turning a PDF's
            # page (or changing fit or scale) must not throw away a document
            # that arrived on a wire, or the card would empty out and only
            # come back by re-running the flow.
            if name in (None, "path"):
                self._image_run_source = None
            self._sync_card_image()
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
            return
        if self.control:
            # a control's params *are* its state — range, caption, options
            # and the value itself all live there, so any edit re-syncs it
            self.prepareGeometryChange()
            default = self._control_default_size()[0]
            self.width = min(CONTROL_MAX_W, max(
                CONTROL_MIN_W,
                float(self.node.params.get("width", default) or default)))
            self.sync_control()
            self._layout_control_proxy()
            self._ports_follow_width()
            self.update()

    def _handle_rect(self) -> QRectF:
        """Bottom-right resize grip, shown while a note/table is selected."""
        return QRectF(self.width - CARD_HANDLE,
                      self.body_height - CARD_HANDLE, CARD_HANDLE, CARD_HANDLE)

    def start_note_edit(self) -> None:
        """Open an in-place markdown editor over the card (Obsidian-style).
        Commits on focus-out or Ctrl+Enter; Escape cancels.

        Shared by Note and Report cards: both are markdown living in a
        "text" param, and both are quicker to edit where you are looking at
        them than in the properties panel.
        """
        if not (self.note or self.report_card) or self._note_editor is not None:
            return
        editor = CardTextEditor(str(self.node.params.get("text", "")), self)
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
        # a report card keeps its header visible so you can still see which
        # node you are typing into; a note has no header to keep
        top = HEADER_H if self.report_card else 0.0
        proxy.setGeometry(QRectF(0, top, max(self.width, 200.0),
                                 max(self.body_height - top, 120.0)))
        if self._report_proxy is not None:
            self._report_proxy.hide()   # don't render behind the editor
        self._note_editor = proxy
        self._note_editor_widget = editor
        editor.setFocus()

    def add_insert_menu(self, menu) -> dict:
        """Add "Insert" entries to a Report card editor's context menu.

        Returns {action: label to embed}; empty for a Note, which has no
        embeds. Two sections, in the order the node's own help recommends:
        the card's **inputs** first — the dependency the scheduler can see —
        then any node on the canvas that has produced something.

        Unwired inputs and duplicate labels are listed but disabled rather
        than hidden: seeing that `c` exists but has nothing in it, or that
        two nodes share a name, is the thing you need to know, and a menu
        that silently omitted them would leave you wondering.
        """
        if not self.report_card:
            return {}
        from ..report.render import duplicate_labels, embeddable_nodes
        scene = self.scene()
        graph = getattr(scene, "graph", None)
        cache = getattr(scene, "output_cache", None)
        if graph is None:
            return {}

        actions: dict = {}
        menu.addSeparator()
        # built with an explicit parent rather than menu.addMenu(str): that
        # returns a QMenu nothing on the Python side holds, and shiboken
        # will collect the wrapper out from under the menu that owns it
        submenu = QMenu("Insert", menu)
        menu.addMenu(submenu)

        wired = {c.dst_port for c in graph.connections.values()
                 if c.dst_node == self.node.id}
        for port in self.node.spec.inputs:
            entry = submenu.addAction(
                port.name if port.name in wired
                else f"{port.name}  — nothing wired in")
            entry.setEnabled(port.name in wired)
            if port.name in wired:
                actions[entry] = port.name

        nodes = [n for n in embeddable_nodes(graph, cache)
                 if n.id != self.node.id]
        if nodes:
            submenu.addSeparator()
            ambiguous = duplicate_labels(graph)
            for node in nodes:
                clashes = node.label.casefold() in ambiguous
                entry = submenu.addAction(
                    f"{node.label}  — duplicate name, rename one first"
                    if clashes else node.label)
                entry.setEnabled(not clashes)
                if not clashes:
                    actions[entry] = node.label
        elif not actions:
            submenu.addAction(
                "Wire something in, or run the flow first").setEnabled(False)
        return actions

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
        if self._report_proxy is not None:
            self._report_proxy.show()
        scene = self.scene()
        if commit and scene is not None \
                and text != self.node.params.get("text", ""):
            from ..commands import SetParamCommand
            scene.undo_stack.push(SetParamCommand(
                scene.graph, self.node.id, "text", text))
        elif self.report_card:
            # cancelled, or nothing changed: no param event is coming, so
            # put the rendered view back ourselves
            self.refresh_report()

    def eventFilter(self, obj, event) -> bool:
        if self._report_view is not None and obj in (
                self._report_view, self._report_view.viewport()):
            # The rendered view sits in a proxy widget over the card and
            # swallows mouse events, so NodeItem.mouseDoubleClickEvent never
            # fires on a report card. Catch it here instead — filtering
            # rather than making the widget mouse-transparent, which would
            # also cost scrolling and clickable links.
            if event.type() == QEvent.MouseButtonDblClick:
                self.start_note_edit()
                return True
        if obj is self._note_editor_widget:
            if event.type() == QEvent.FocusOut:
                # Commit when the user moves on *within the app* — not when
                # the window merely stops being the active one.
                #
                # A popup (a context menu, a completer) takes focus while it
                # is up, so committing on that closed the editor out from
                # under the menu the user had just opened: right-clicking
                # for the Insert submenu simply ended edit mode. Which
                # reason Qt reports for a menu depends on the platform —
                # here it raised three PopupFocusReason and then an
                # ActiveWindowFocusReason as the menu window took over — so
                # both are ignored. Alt-tabbing away therefore leaves the
                # editor open too, which is the right answer anyway: coming
                # back to a half-typed note beats finding it committed and
                # closed.
                if event.reason() not in (Qt.PopupFocusReason,
                                          Qt.ActiveWindowFocusReason):
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
        copy_headers = QToolButton(text="Copy")
        copy_headers.setToolTip(
            "Copy the selection to the clipboard with column headers on "
            "top — plain Ctrl+C leaves them out. Copies the whole table "
            "if nothing is selected")
        expand = QToolButton(text="⛶")
        expand.setToolTip("Open the full spreadsheet editor")
        for button in (add_row, del_row, add_col, del_col, fit, copy_headers):
            button.setAutoRaise(True)
            trow.addWidget(button)
        trow.addStretch(1)
        expand.setAutoRaise(True)
        trow.addWidget(expand)
        layout.addWidget(toolbar)

        grid = SpreadsheetView()
        # a canvas full of these fits its columns on first paint, not at load
        grid.set_defer_autosize(True)
        # parent the model to the view so C++ destruction stays ordered
        model = SheetModel(self.node.params.get("data"), parent=grid)
        grid.setModel(model)
        grid.verticalHeader().setFixedWidth(28)
        theme.style_scroll_area(grid, theme.grid_stylesheet())
        layout.addWidget(grid)

        add_row.clicked.connect(self._table_add_row)
        del_row.clicked.connect(self._table_remove_row)
        add_col.clicked.connect(self._table_add_column)
        del_col.clicked.connect(self._table_remove_column)
        fit.clicked.connect(lambda: grid.autosize_columns())
        copy_headers.clicked.connect(grid.copy_selection_with_headers)
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
        """Pull externally-changed data (undo/redo, a Properties edit, a
        resize writing width/height) into the grid; SheetModel skips the
        reset when nothing changed.

        While linked, the card shows the *merge* of the stored sheet with
        the cached upstream frame — so this re-derives that merge rather
        than reading the stored sheet, which holds only the user's own
        columns and would blank the grid until the next run."""
        if self._table_model is not None:
            self._table_model.set_sheet(
                self._linked_sheet() or self.node.params.get("data"))

    def _linked_sheet(self):
        """The merged sheet a linked table should be showing, or None when
        it isn't linked, nothing upstream has run, or there's no engine
        behind the scene to ask."""
        scene = self.scene()
        cache = getattr(scene, "output_cache", None)
        if scene is None or cache is None:
            return None
        from flograph.engine.introspect import merged_linked_sheet
        return merged_linked_sheet(scene.graph, cache, self.node.id)

    def _table_input_connected(self) -> bool:
        scene = self.scene()
        return (scene is not None
                and scene.graph.input_connection(self.node.id, "table")
                is not None)

    def refresh_table_link(self) -> None:
        """The table's input was connected or disconnected. The grid stays
        editable either way (a run refreshes input-owned columns; the
        user's own columns survive) — on disconnect, fall back to the
        stored cells, and on connect show the merge straight away if the
        upstream data is already cached."""
        if not self.table or self._table_model is None:
            return
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
        if self._image is not None and not self._flat:
            # An image re-decodes at the new zoom on its next paint; asking
            # for one here is what makes zooming in sharpen the picture.
            self.update()

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
        proxy.setOpacity(0.45 if self._updating else 1.0)
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
        # a list is laid out on the grid the node itself declares, so its
        # card, a tile of it and the PDF all arrange the charts alike
        from flograph.core.chart_grid import grid_settings
        self._figure_view.set_grid(*grid_settings(self.node.params))
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
        proxy.setOpacity(0.45 if self._updating else 1.0)
        self._layout_figure_proxy()

    def relayout_figures(self) -> None:
        """Re-arrange an already-shown list of figures against the node's
        current grid settings. No-op unless a list is being shown."""
        from flograph.core.chart_grid import grid_settings
        view = self._plotly_widget if self.plotly_card else self._figure_view
        if view is not None and hasattr(view, "set_grid"):
            view.set_grid(*grid_settings(self.node.params))

    def set_plotly_figure(self, figure) -> None:
        """Render a freshly computed plotly figure (or None) into the
        embedded webview — called from the GUI thread once the engine
        reports this node done."""
        if not self.plotly_card:
            return
        from flograph.core.chart_grid import grid_settings
        self._plotly_widget.set_grid(*grid_settings(self.node.params))
        self._plotly_widget.set_figure(figure)
        self._plotly_widget.set_zoom(self._card_scale())

    def clear_output(self) -> None:
        """Drop whatever this card is displaying that came from the cache.

        Called when caches are reset: the data itself is gone, so a chart or
        table still on show would be a stale lie — and it would pin the frame
        / figure (and, for webview cards, the rendered page held in a renderer
        process) that Reset Caches is supposed to release.
        """
        if self.plotly_card:
            self.set_plotly_figure(None)
        elif self.figure_card:
            self.set_figure(None)
        if self.table_viewer:
            self.set_table_data(None)

    # ----------------------------------------------------------- report card

    def _report_proxy_rect(self) -> QRectF:
        height = max(0.0, self.body_height - HEADER_H - CARD_HANDLE)
        return QRectF(0, HEADER_H, self.width, height)

    def _layout_report_proxy(self) -> None:
        if self._report_proxy is not None:
            self._scale_proxy_into(self._report_proxy,
                                   self._report_proxy_rect())

    def _build_report_widget(self) -> None:
        from PySide6.QtWidgets import QTextBrowser
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        view.setStyleSheet(
            f"QTextBrowser {{ background: {theme.NODE_BODY.name()};"
            f" color: {theme.NODE_TEXT.name()}; border: none;"
            f" padding: 4px; }}")
        self._report_view = view
        view.installEventFilter(self)
        view.viewport().installEventFilter(self)

        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(view)
        self._report_proxy = proxy
        proxy.setOpacity(0.45 if self._updating else 1.0)
        self._layout_report_proxy()
        self.refresh_report()

    def refresh_report(self) -> None:
        """Re-render the card's markdown against whatever is wired in.

        Called on a param edit and after any run — an embed's content lives
        upstream, so the text staying the same doesn't mean the card does.
        """
        if not self.report_card or self._report_view is None:
            return
        scene = self.scene()
        cache = getattr(scene, "output_cache", None) if scene else None
        body = str(self.node.params.get("text", "") or "")
        from ..report.render import render_card
        rendered = render_card(body, scene.graph, cache, self.node.id,
                               width=int(self.width) - 44) \
            if scene is not None else None
        # before the old document goes: a QMovie still writing frames into a
        # deleted document is a crash, not a stale picture
        self._stop_report_animations()
        if rendered is None:
            self._report_view.setMarkdown(body)
            return
        # colours come from the card, not the document: a report card is
        # part of the canvas and has to read against the dark body
        document = rendered.document
        document.setDefaultStyleSheet(
            document.defaultStyleSheet()
            + f"\nbody {{ color: {theme.NODE_TEXT.name()}; }}")
        self._report_view.setDocument(document)
        if rendered.animations:
            from ..report.animate import ReportAnimator
            self._report_animator = ReportAnimator(
                document, rendered.animations, rendered.image_widths,
                on_frame=self._report_view.viewport().update)
            self._report_animator.set_playing(self._report_should_animate())

    def _stop_report_animations(self) -> None:
        if self._report_animator is not None:
            self._report_animator.dispose()
            self._report_animator = None

    def _report_should_animate(self) -> bool:
        """Same three switches as an image card: flattened by LOD, preview
        turned off, or hidden inside a collapsed frame all mean nobody is
        looking at it."""
        return (not self._flat
                and self.node.canvas_preview_enabled
                and self.isVisible())

    # ------------------------------------------------------------- wiki card

    def _wiki_proxy_rect(self) -> QRectF:
        height = max(0.0, self.body_height - HEADER_H - CARD_HANDLE)
        return QRectF(0, HEADER_H, self.width, height)

    def _layout_wiki_proxy(self) -> None:
        if self._wiki_proxy is not None:
            self._scale_proxy_into(self._wiki_proxy, self._wiki_proxy_rect())

    def _wiki_folder(self) -> str:
        """The folder the card shows: a wired string beats the param, blank
        falls through to the bundled handbook (resolve_wiki_dir handles that)."""
        wired = self._wired_input_value("folder")
        if isinstance(wired, str) and wired.strip():
            return wired
        return str(self.node.params.get("folder", "") or "")

    def _wired_input_value(self, port: str):
        """The cached output feeding one of this node's input ports, or None
        if the port is unconnected or its source has no result yet. Mirrors
        report/render.by_wired_input's cache guard."""
        scene = self.scene()
        graph = getattr(scene, "graph", None)
        cache = getattr(scene, "output_cache", None)
        if graph is None or cache is None:
            return None
        for conn in graph.connections.values():
            if conn.dst_node != self.node.id or conn.dst_port != port:
                continue
            entry = cache.get(conn.src_node)
            if entry is None or conn.src_port not in entry.ports():
                return None
            return cache.outputs_for(conn.src_node).get(conn.src_port)
        return None

    def _build_wiki_widget(self) -> None:
        from ..wiki import WikiView
        view = WikiView(folder=self._wiki_folder(),
                        show_nav=bool(self.node.params.get("show_nav", True)))
        self._wiki_view = view
        page = str(self.node.params.get("page", "") or "")
        if page:
            view.show_page(page)
        # a navigation is a cosmetic param edit — undoable, no re-run, and the
        # dashboard tile of the same node follows through the same param
        view.page_changed.connect(self._wiki_page_changed)
        view.nav_visibility_changed.connect(self._wiki_nav_changed)

        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(view)
        self._wiki_proxy = proxy
        proxy.setOpacity(0.45 if self._updating else 1.0)
        self._layout_wiki_proxy()

    def refresh_wiki(self, name: str | None = None) -> None:
        view = self._wiki_view
        if view is None:
            return
        if name in (None, "folder"):
            view.set_folder(self._wiki_folder())
        if name in (None, "show_nav"):
            view.set_nav_visible(bool(self.node.params.get("show_nav", True)))
        if name in (None, "page"):
            page = str(self.node.params.get("page", "") or "")
            if page:
                view.show_page(page)

    def _wiki_page_changed(self, slug: str) -> None:
        if slug == str(self.node.params.get("page", "") or ""):
            return
        scene = self.scene()
        if scene is None or not hasattr(scene, "undo_stack"):
            return
        from ..commands import SetParamCommand
        scene.undo_stack.push(
            SetParamCommand(scene.graph, self.node.id, "page", slug))

    def _wiki_nav_changed(self, visible: bool) -> None:
        if bool(visible) == bool(self.node.params.get("show_nav", True)):
            return
        scene = self.scene()
        if scene is None or not hasattr(scene, "undo_stack"):
            return
        from ..commands import SetParamCommand
        scene.undo_stack.push(
            SetParamCommand(scene.graph, self.node.id, "show_nav", bool(visible)))

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

        view = DataTableView()
        theme.style_scroll_area(view, theme.grid_stylesheet())
        view.setSortingEnabled(True)
        view.hide()
        layout.addWidget(view, 1)
        self._table_viewer_view = view

        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(host)
        self._table_viewer_proxy = proxy
        proxy.setOpacity(0.45 if self._updating else 1.0)
        self._layout_table_viewer_proxy()

    def set_table_data(self, table) -> None:
        """Push a freshly computed DataFrame (or None) onto the embedded
        table view — called from the GUI thread once the engine reports this
        node done."""
        view = self._table_viewer_view
        if view is None:
            return
        previous = view.model()
        import sys
        pd = sys.modules.get("pandas")
        if table is None or pd is None or not isinstance(table, pd.DataFrame):
            view.setModel(None)
            view.hide()
            self._table_viewer_placeholder.show()
        else:
            self._table_viewer_placeholder.hide()
            from ..inspector.pandas_model import PandasModel
            view.setModel(PandasModel(table, parent=view))
            view.show()
        if previous is not None:
            # setModel swaps models without deleting the old one — Qt does
            # not take ownership of the model it replaces — so a card that
            # was re-fed every run was pinning every previous frame it had
            # ever shown until the card itself was destroyed.
            previous.deleteLater()

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

    # ----------------------------------------------------------- mark image

    def _mark_card_image(self) -> "CardImage":
        """The picture a compact node wears instead of a drawn mark, built on
        first use. A second CardImage alongside the Image card's own — the
        class already survives being hosted twice (dashboard tiles do it),
        and everything a 56px glyph needs from it, a 320px card needed
        first: decode-at-display-size, one-frame-at-a-time animation, and
        pausing when nobody is looking."""
        if self._mark_image is None:
            from .image_card import CardImage
            self._mark_image = CardImage(self.update)
            self._sync_mark_image()
        return self._mark_image

    def _sync_mark_image(self) -> None:
        if self._mark_image is None:
            return
        self._mark_image.set_source(self.node.mark_image, "Fit", True, 1.0)
        self._mark_image.set_playing(self._mark_should_play())

    def _mark_should_play(self) -> bool:
        """Animate only while the square can actually be seen — not
        flattened by LOD, not preview-disabled, not on a hidden tab. Exactly
        the Image card's rule; a canvas of animated marks must cost nothing
        while you are working somewhere else on it."""
        return (not self._flat
                and self.node.canvas_preview_enabled
                and self.isVisible())

    def refresh_mark_image(self) -> None:
        """The node's mark changed. Drops the old artwork rather than
        re-pointing it: a CardImage keys its decode cache on the source, and
        a mark swapped back and forth is not worth holding two of."""
        if self._mark_image is not None:
            self._mark_image.set_playing(False)
            self._mark_image = None
        if self.node.mark_image:
            self._mark_card_image()
        self.update()

    def dispose_mark_image(self) -> None:
        """Stop the animation before the item goes. A QMovie still delivering
        frames into a deleted item is a crash, which is why dashboard tiles
        have carried the same call since they grew images."""
        if self._mark_image is not None:
            self._mark_image.set_playing(False)
            self._mark_image = None

    def teardown(self) -> None:
        """Destroy the card's heavy widgets when the node is removed.

        Removing a node drops the item out of the scene, but the item itself
        is kept alive by its own reference cycles (a PortItem points back at
        its parent NodeItem, the proxies point at their widgets), so the
        memory a card was displaying would stay resident until the app
        closed — webviews keep their renderer process, table models keep the
        frame, figure canvases keep the chart. The widgets are QObjects, so
        deleteLater is deterministic: this frees the memory even if the
        item's Python wrapper is never collected."""
        self.dispose_mark_image()
        if self.plotly_card and self._plotly_widget is not None:
            # set_content(None) destroys the webview, releasing the renderer
            self._plotly_widget.set_content(None)
            self._plotly_widget.deleteLater()
            self._plotly_widget = None
        if self._table_viewer_view is not None:
            # drops the model, releasing the frame it was displaying
            self.set_table_data(None)
            self._table_viewer_view.deleteLater()
            self._table_viewer_view = None
        if self._figure_view is not None:
            self._figure_view.clear()
            self._figure_view.deleteLater()
            self._figure_view = None
        if self._wiki_view is not None:
            self._wiki_view.deleteLater()
            self._wiki_view = None

    # ----------------------------------------------------------- image card

    def _card_image(self) -> "CardImage":
        """The card's artwork, built on first use.

        Lazy rather than built in __init__ because loading is driven by
        paint(): a project full of image nodes that opens zoomed out (so
        every card is flattened by LOD) never decodes a single pixel.
        """
        if self._image is None:
            if self.pdf_card:
                from .pdf_card import CardPdf
                self._image = CardPdf(self.update)
            else:
                from .image_card import CardImage
                self._image = CardImage(self.update)
            self._sync_card_image()
        return self._image

    def _sync_card_image(self) -> None:
        """Re-point the artwork at whatever the node's params now say."""
        if self._image is None:
            return
        params = self.node.params
        fit = str(params.get("fit", "Fit") or "Fit")
        if self.pdf_card:
            # A page rather than a picture: which page and the password
            # replace the animation flag, and there is nothing to play.
            self._image.set_source(
                self._image_source(), fit, self._card_scale(),
                int(params.get("page", 1) or 1),
                str(params.get("password", "") or ""),
            )
            return
        self._image.set_source(
            self._image_source(), fit,
            bool(params.get("animate", True)),
            self._card_scale(),
        )
        self._image.set_playing(self._image_should_play())

    def _image_source(self) -> str:
        """What the card should draw — a path, a data: URI or base64.

        Normally the node's own param, so a dropped or pasted image shows up
        without the graph ever being run. But the node also takes a *wired*
        source, and that one only exists once the node has run — so a source
        reported by the engine wins while it lasts.
        """
        return self._image_run_source or str(
            self.node.params.get("path", "") or "")

    def set_image_result(self, source: Optional[str]) -> None:
        """Show what this node's last run actually resolved."""
        source = str(source or "") or None
        if source == self._image_run_source:
            return
        self._image_run_source = source
        self._sync_card_image()
        self.update()

    def _image_should_play(self) -> bool:
        """Animate only when the card is genuinely being looked at — not
        flattened by LOD, not preview-disabled, not on a hidden tab."""
        return (not self._flat
                and self.node.canvas_preview_enabled
                and self.isVisible())

    def refresh_card_image(self) -> None:
        """Re-read the file from disk (a re-run may have rewritten it)."""
        if self._image is not None:
            self._image.reload()
            self._sync_card_image()
            self.update()

    def _paint_image(self, painter: QPainter) -> None:
        """The image card: chrome, then the artwork painted straight in."""
        if self.node.params.get("background", True):
            self._paint_widget_card(painter)
        else:
            # "Card background" off: just the header and the selection
            # outline, so a cut-out PNG sits on the canvas without a slab
            # of card behind it.
            self._paint_header(painter, self.width)
            if self.isSelected():
                painter.setPen(QPen(theme.SELECTION_OUTLINE, 2.0))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(
                    QRectF(0, 0, self.width, self.body_height), 7, 7)

        rect = QRectF(2, HEADER_H, self.width - 4,
                      max(0.0, self.body_height - HEADER_H - 2))
        if rect.isEmpty():
            return
        image = self._card_image()
        self._pager = None    # re-established below if chevrons get drawn
        painter.save()
        # Keep a Fill/Stretch/Original-size picture inside the card's rounded
        # outline instead of squaring off its bottom corners.
        rounded = QPainterPath()
        rounded.addRoundedRect(QRectF(0, 0, self.width, self.body_height), 7, 7)
        painter.setClipPath(rounded)
        painter.setOpacity(0.45 if self._updating else 1.0)
        image.paint(painter, rect, self._image_render_ratio())
        painter.restore()

        if image.has_content() and not image.error:
            if self.pdf_card and self.node.params.get("show_page_number", True):
                self._paint_page_number(painter, rect, image.page_caption(),
                                        image.shown_page(), image.page_count())
            return
        painter.setPen(QPen(theme.NODE_SUBTEXT))
        font = painter.font()
        font.setBold(False)
        font.setPointSizeF(8.5)
        painter.setFont(font)
        if self.pdf_card:
            from .pdf_card import EMPTY_HINT
            hint = EMPTY_HINT
        else:
            hint = ("Drop an image file here, paste one from the\n"
                    "clipboard, or pick a file in the properties panel.")
        painter.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap,
                         image.error or hint)

    def _paint_page_number(self, painter: QPainter, rect: QRectF,
                           caption: str, page: int, pages: int) -> None:
        """The page pill and its chevrons, drawn by the shared painter so the
        canvas card and the dashboard tile cannot drift apart. It hands back
        where it put the chevrons; that is what a click is tested against."""
        from .pdf_card import paint_pager
        self._pager = paint_pager(painter, rect, caption, page, pages,
                                  self._pager_hover)

    def _pager_at(self, pos: QPointF) -> int:
        """-1 or +1 if `pos` is on a page chevron, 0 if it is not."""
        if self._flat:
            return 0    # flattened by LOD: nothing is drawn, so nothing hits
        from .pdf_card import chevron_at
        return chevron_at(self._pager, pos)

    def _step_page(self, step: int) -> None:
        """Turn a PDF card's page by a chevron click.

        "page" is a cosmetic param, so this repaints the card and runs
        nothing - the same edit the properties panel makes, pushed onto the
        undo stack the same way, which is what keeps the spinner there in
        step with the card here.
        """
        scene = self.scene()
        image = self._image
        if scene is None or image is None:
            return
        from .pdf_card import stepped_page
        page = stepped_page(image, step)
        if page == self.node.params.get("page"):
            return
        from ..commands import SetParamCommand
        scene.undo_stack.push(
            SetParamCommand(scene.graph, self.node.id, "page", page))

    def _image_render_ratio(self) -> float:
        """Device pixels per logical pixel for the artwork: screen DPR times
        canvas zoom, so a card inspected close up decodes sharp rather than
        being upscaled from a card-sized buffer."""
        ratio = 1.0
        scene = self.scene()
        views = scene.views() if scene is not None else []
        if views:
            view = views[0]
            ratio *= (view.viewport().devicePixelRatioF() or 1.0)
            ratio *= view.transform().m11()
        return min(4.0, max(1.0, ratio))

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

    # -------------------------------------------------------------- controls

    def _control_default_size(self) -> tuple[float, float]:
        from ..controls import control_size
        return control_size(self.node.spec.control or "")

    def _control_proxy_rect(self) -> QRectF:
        height = max(0.0, self.body_height - HEADER_H - CARD_HANDLE)
        return QRectF(0, HEADER_H, self.width, height)

    def _layout_control_proxy(self) -> None:
        if self._control_proxy is not None:
            self._control_proxy.setGeometry(self._control_proxy_rect())

    def _build_control_widget(self) -> None:
        """One card path for every control shape — the widget knows what it
        is, this only hosts it. An unknown shape (a project from a newer
        flograph) leaves the card empty rather than refusing to load."""
        from ..controls import build_control

        widget = build_control(self.node.spec.control or "")
        if widget is None:
            return
        widget.sync(self.node.params)
        widget.value_committed.connect(self._on_control_committed)
        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(widget)
        self._control_widget = widget
        self._control_proxy = proxy
        self._layout_control_proxy()

    def set_control_upstream(self, values: dict) -> None:
        """Settings this control's own input ports supplied on the last run
        — bounds, options, labels. Called once the engine reports it done."""
        if self._control_widget is not None:
            self._control_widget.set_upstream(values)

    def sync_control(self) -> None:
        """Re-read the widget from this node's params — keeps the card
        honest when they change elsewhere (properties panel, undo)."""
        if self._control_widget is not None:
            self._control_widget.sync(self.node.params)

    def _on_control_committed(self, value) -> None:
        """The user moved the control: commit its new value (which dirties
        this node and everything downstream) and ask the window to re-run
        from here, so the visuals follow live. Same contract as a slicer
        tick — a control you have to leave to go press Run is not a
        control."""
        scene = self.scene()
        if scene is None:
            return
        if value != self.node.params.get("value"):
            from ..commands import SetParamCommand
            # merge=False: one Ctrl+Z undoes one adjustment, not the session
            scene.undo_stack.push(SetParamCommand(
                scene.graph, self.node.id, "value", value, merge=False))
        scene.control_changed.emit(self.node.id)

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
        # Three things can hang outside the body, none of them at once: the
        # reroute's floating label, and a square node's name above and status
        # row below.
        for extra in (self._reroute_label_rect(), self._name_rect(),
                      self._status_rect()):
            if extra is not None:
                base = base.united(extra.adjusted(-2, -2, 2, 2))
        # The pins hang outside the body on purpose (PORT_EDGE_GAP), the
        # flow pins above the corners, the name pills further out still.
        # This rect is what a *move* damages: children sticking out of it
        # kept their old pixels behind on every drag — faint circles
        # skidding across the canvas until a zoom or pan repainted them.
        kids = self.childrenBoundingRect()
        if not kids.isNull():
            # Qt's rect is recursive, and cached, which is what makes it
            # cheap enough to ask for on every paint. Recursive also means
            # descendants nobody here created count towards it: an embedded
            # widget that owns a popup gets a proxy *panel* from Qt, parked
            # thousands of pixels away where it waits invisibly to be shown.
            # One of those — the overflow menu of the toolbar inside a plot
            # card — gave a 440x300 card bounds of 1450x3276. Since a card's
            # shape() falls back to its bounding rect, that was a giant
            # invisible square in the minimap and half the canvas dragging a
            # plot that looked perfectly normal. So: take the cheap answer
            # while it is plausible, and count the real children when it is
            # not.
            room = base.adjusted(-CHILD_OVERHANG_MAX, -CHILD_OVERHANG_MAX,
                                 CHILD_OVERHANG_MAX, CHILD_OVERHANG_MAX)
            if not room.contains(kids):
                kids = self._own_children_rect()
            base = base.united(kids)
        return base

    def _own_children_rect(self) -> QRectF:
        """The extent of the children this card actually put on the canvas.

        Each direct child by its *own* rect rather than the recursive one,
        and no panels — which is exactly the set of things this node draws
        and moves, and excludes anything an embedded widget's popups leave
        parked in the scene.
        """
        rect = QRectF()
        for child in self.childItems():
            if child.flags() & QGraphicsItem.ItemIsPanel:
                continue
            rect = rect.united(child.mapRectToParent(child.boundingRect()))
        return rect

    def shape(self) -> QPainterPath:
        """What a click and a rubber band actually catch.

        Qt's default is the whole bounding rect, which on a square node would
        hand it the empty air between the name and the box, and the status
        row under it — a node twice as clickable as it looks, and a rubber
        band that picks up nodes it only grazed. The name is worth catching
        (it renames, and it drags), the gap is not.
        """
        if not self._square:
            return super().shape()
        path = QPainterPath()
        path.addRect(QRectF(0, 0, self.width, self.body_height))
        name = self._name_rect()
        if name is not None:
            path.addRect(name)
        return path

    # -------------------------------------------------- compact node chrome

    @staticmethod
    def _name_font() -> QFont:
        font = QFont()
        font.setPointSizeF(COMPACT_NAME_FONT_SIZE)
        font.setBold(True)
        return font

    def invalidate_label(self) -> None:
        """The node's name changed, so a square node's wrap of it is stale.
        Callers pair this with prepareGeometryChange — the wrap decides how
        tall the name is, and so how far the bounding rect reaches up."""
        self._name_cache = None

    def _name_layout(self) -> tuple[str, ...]:
        """The label wrapped for the space above the square: one line when it
        fits, otherwise two with the second elided.

        Cached, because boundingRect calls it and Qt calls boundingRect
        constantly — measuring text on every one of those would be a font
        query per node per frame.
        """
        if self._name_cache is not None:
            return self._name_cache
        text = f"⚠ {self.node.label}" if self.broken else self.node.label
        metrics = QFontMetrics(self._name_font())
        limit = int(COMPACT_NAME_MAX_W)
        if metrics.horizontalAdvance(text) <= COMPACT_NAME_MAX_W:
            lines: tuple[str, ...] = (text,)
        else:
            # Break at the last word that still fits, so "String
            # Manipulation" splits between its words rather than mid-word.
            words = text.split()
            head = ""
            tail = text
            for i in range(len(words) - 1, 0, -1):
                candidate = " ".join(words[:i])
                if metrics.horizontalAdvance(candidate) <= COMPACT_NAME_MAX_W:
                    head, tail = candidate, " ".join(words[i:])
                    break
            if head:
                lines = (head, metrics.elidedText(tail, Qt.ElideRight, limit))
            else:
                # one word too long for the line: no break point exists
                lines = (metrics.elidedText(text, Qt.ElideRight, limit),)
        self._name_cache = lines
        return lines

    def _name_rect(self) -> Optional[QRectF]:
        """Local-coordinate rect of the name above a square node, centred on
        it and free to overhang either side. None for anything else."""
        if not self._square:
            return None
        lines = self._name_layout()
        metrics = QFontMetrics(self._name_font())
        width = max(metrics.horizontalAdvance(line) for line in lines)
        height = COMPACT_NAME_H * len(lines)
        return QRectF(self.width / 2 - width / 2,
                      -COMPACT_NAME_GAP - height, width, height)

    def _status_rect(self) -> Optional[QRectF]:
        """Local-coordinate rect of the strip under a square node: the status
        LED, the lock/freeze badges and the temp-edit dot. They used to share
        the header and the air above it, both of which the square spends on
        the mark and the name instead."""
        if not self._square:
            return None
        return QRectF(0, self.body_height + COMPACT_STATUS_GAP,
                      self.width, COMPACT_STATUS_H)

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

    def set_drop_hint(self, on: bool) -> None:
        """Ring the body while this node sits under a dragged one: letting
        go here will replace it. The ring survives LOD flattening — the
        question "which box would I land on" is asked hardest zoomed out."""
        if on and self._drop_hint_frame is None:
            self._drop_hint_frame = DropHintOutline(self)
        if self._drop_hint_frame is not None:
            self._drop_hint_frame.setVisible(on)

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

    def refresh_port_connections(self) -> None:
        """Re-read every input pin's filled/hollow state. Inputs only —
        an output always draws filled, so it never asks.

        Both flow pins ask, including the output, because for those the
        answer decides something an output pin has never had to care about:
        whether the pin is on screen at all.
        """
        for port in self.input_ports.values():
            port.refresh_connected()
        for pin in self.flow_ports.values():
            pin.refresh_connected()
        # ...which may have just been the last order edge off this node, or
        # its first
        self._apply_port_visibility()

    def rebuild_ports(self) -> None:
        """(Re)create port items from the current spec — called at build time
        and again whenever the node's code changes its ports."""
        # every pin child, not just the ones the dicts still point at: two
        # ports sharing a name collapse into one dict entry, and the loser
        # would otherwise stay parented here forever, unlaid-out at the
        # node's origin and invisible to every later rebuild
        for item in [c for c in self.childItems() if isinstance(c, PortItem)]:
            if item.scene() is not None:
                item.scene().removeItem(item)
            item.setParentItem(None)
        self.input_ports.clear()
        self.output_ports.clear()
        self.flow_ports.clear()
        self.prepareGeometryChange()
        # Every node has these, whatever its script says, and a code edit
        # cannot take them away — so they are rebuilt first and independently
        # of every rule below. The one exception is a reroute, which is a
        # bend in a wire drawn as a dot: two pins on top of one would be
        # bigger than the node.
        for spec in () if self.compact else (FLOW_INPUT, FLOW_OUTPUT):
            pin = PortItem(self, spec)
            pin.setToolTip(
                ("Flow pin — run this node after another.\nDrag to another "
                 "node's flow pin; no data passes. Right-click the dashed "
                 "line for what these do."
                 if spec is FLOW_INPUT else
                 "Flow pin — run another node after this one.\nDrag to "
                 "another node's flow pin; no data passes. Right-click the "
                 "dashed line for what these do."))
            self.flow_ports[spec.direction.value] = pin
        for spec in self.node.spec.inputs:
            if self.from_card:
                continue  # the link end: real in the spec, never on the canvas
            self.input_ports[spec.name] = PortItem(self, spec)
        for spec in self.node.spec.outputs:
            if self.goto_card:
                continue
            self.output_ports[spec.name] = PortItem(self, spec)
        self._layout_ports()
        self.refresh_port_connections()
        # fresh pins are born visible; whatever hid the old ones (LOD
        # flattening, collapsed ports, flow-pin preference) has to be
        # re-derived or a rebuild while zoomed out leaves dots behind
        self._apply_port_visibility()
        self.update()

    def _port_x(self) -> tuple[float, float]:
        """(input x, output x): pins float clear of the node's edges rather
        than being centred on them — see PORT_EDGE_GAP. A reroute is the
        exception: it *is* a pin, so its ports stay at its own centre line
        and nudging them outward would only smear the dot."""
        if self.compact:
            return 0.0, self.width
        out = PortItem.RADIUS + PORT_EDGE_GAP
        return -out, self.width + out

    def _layout_ports(self) -> None:
        """Pin port items to the current geometry. Cards resize at runtime,
        so this runs again on every width change — output ports (and the
        wires on them) must ride the right edge, not stay where they were."""
        # pins moving change childrenBoundingRect, which boundingRect now
        # unions — the old extent must be registered before they move
        self.prepareGeometryChange()
        self._layout_flow_ports()
        left, right = self._port_x()
        if self.compact or self.link_card:
            for port in self.input_ports.values():
                port.setPos(left, self.body_height / 2)
            for port in self.output_ports.values():
                port.setPos(right, self.body_height / 2)
            return
        if self._card_ports():
            self._space_card_ports(self.input_ports.values(), left)
            self._space_card_ports(self.output_ports.values(), right)
            return
        if self._square:
            self._stack_ports(self.input_ports.values(), left)
            self._stack_ports(self.output_ports.values(), right)
            return
        for i, spec in enumerate(self.node.spec.inputs):
            self.input_ports[spec.name].setPos(
                left, HEADER_H + ROW_H * (i + 0.5))
        for i, spec in enumerate(self.node.spec.outputs):
            self.output_ports[spec.name].setPos(
                right, HEADER_H + ROW_H * (i + 0.5))

    def _layout_flow_ports(self) -> None:
        """The flow pins sit off the node's two upper corners, diagonally: in
        at the top left, out at the top right.

        The corners are the only real estate every node has spare. The left
        and right edges are where the data pins run — as far down as a node
        with twenty of them needs — the top edge above a square node is
        where its name goes, the strip below it is the status row, and the
        air above a wide node's header belongs to its badges. A corner is
        outside all four, on every node kind, at every port count.

        Their being *above* the node is also why `order_path` arcs upward:
        both ends of an order edge leave through the top.
        """
        if not self.flow_ports:
            return
        out = PortItem.FLOW_RADIUS + PORT_EDGE_GAP
        # A square node's name is centred above it and free to overhang both
        # sides, so on a long label it runs straight through where the
        # corners are. The pins clear it by sitting above the name instead —
        # still the corners, just the corners of everything the node draws.
        name = self._name_rect()
        y = -out if name is None else name.top() - out
        self.flow_ports["input"].setPos(-out, y)
        self.flow_ports["output"].setPos(self.width + out, y)

    def _stack_ports(self, ports, x: float) -> None:
        """Lay a square node's pins down its edge, ROW_H apart.

        Centred on the body while they fit — a lone pin belongs on the centre
        line, and a wire entering along the top edge of every node in a chain
        reads as a mistake — but never starting higher than COMPACT_PORT_TOP.
        That clamp is what makes a node with more pins than the square has
        room for spill *downward only*, past the bottom edge and onto the
        canvas, rather than creeping up into the node's name.

        Three fit; the fourth and beyond hang out below, which is the same
        honest overflow `_space_card_ports` gives a card and for the same
        reason: the alternative is compressing the spacing until the pins are
        an unpickable blob. At exactly three the two rules agree, so there is
        no visible step where one takes over from the other.
        """
        items = list(ports)
        if not items:
            return
        top = max(COMPACT_PORT_TOP,
                  self.body_height / 2 - ROW_H * (len(items) - 1) / 2)
        for i, port in enumerate(items):
            port.setPos(x, top + ROW_H * i)

    @property
    def ports_collapsed(self) -> bool:
        return bool(self.node.ports_collapsed)

    def _has_card_body(self) -> bool:
        """The card kinds with a real embedded body — a chart, a grid, a
        rendered document, a KPI. The set that can fold down to an icon,
        and (while open) the set that runs its ports along its edge."""
        return bool(self.table or self.figure_card or self.table_viewer
                    or self.kpi_card or self.image_card or self.slicer
                    or self.control or self.report_card or self.wiki_card)

    def foldable(self) -> bool:
        """Whether this node can fold down to a plain icon when its canvas
        preview is switched off — see _set_folded.

        Every card with a real rendered body, bar the KPI: that one is a
        painted number already close to icon size, with nothing heavy to
        put away, so folding it buys nothing.
        """
        return bool(self._has_card_body() and not self.kpi_card)

    def _card_ports(self) -> bool:
        """Whether this node lays its ports out along a card edge rather
        than in labelled rows. Only these can outgrow their node — an
        ordinary node's height is derived from its port count. A folded
        card is a square, and stacks its pins down the edge like one."""
        return self._has_card_body() and not self._folded

    def collapsible(self) -> bool:
        """Whether offering to collapse this node's ports means anything.
        One pin a side is already as gathered as it gets."""
        return self._card_ports() and (len(self.input_ports) > 1
                                       or len(self.output_ports) > 1)

    def _apply_port_visibility(self) -> None:
        """The single place port visibility is decided.

        Two independent reasons to hide a pin — the canvas is flattened for
        zoom, or the node's ports are collapsed — and they used to be set
        from two places, so un-flattening would happily un-collapse a node
        as a side effect. Both are re-derived here together.
        """
        collapsed = self.ports_collapsed
        # Collapsing has no say here — it gathers a *stack* of pins behind
        # its first one, and there is only ever one of these per side. The
        # LOD flattening and the show/hide rule do.
        shown = flow_pins_on(self.node, self.scene())
        for pin in self.flow_ports.values():
            # A pin with an order edge on it is always drawn: the wire has to
            # terminate somewhere, and hiding the pin under it would leave a
            # dashed line running into the side of a node.
            pin.setVisible(not self._flat and (shown or pin.has_edge))
        for ports in (self.input_ports, self.output_ports):
            items = list(ports.values())
            for i, port in enumerate(items):
                gathered = collapsed and len(items) > 1 and i > 0
                port.setVisible(not self._flat and not gathered)
            if not items:
                continue
            # The one pin left showing has to admit what it is: a wire
            # dropped on it lands on that port, not on some notional bundle,
            # and its name alone would imply the others aren't there.
            lead = items[0]
            if collapsed and len(items) > 1:
                side = "inputs" if ports is self.input_ports else "outputs"
                lead.setToolTip(
                    f"{len(items)} {side}, collapsed — dropping a wire here "
                    f"connects “{lead.spec.name}”. Expand to reach the rest.")
            else:
                lead.setToolTip(lead.spec.name)

    def _space_card_ports(self, ports, x: float) -> None:
        """Lay a card's ports down its edge, starting in the header.

        Always from the header, whether there is one port or twenty: the
        first pin lands where a single-port card has always put it, and the
        rest follow at ROW_H — the same rhythm an ordinary node's port rows
        use. That is what makes a card with two inputs look like the same
        node as a card with one, rather than the pins jumping into the body
        the moment a second appears.

        The spacing never compresses. A node with twenty inputs simply runs
        its pins past the bottom of the card and onto the canvas, which is
        the honest thing to do: squeezing them back into the available
        height recreates exactly the overlapping-blob problem this layout
        exists to fix, and at twenty ports it would be far worse. Collapsing
        is the answer to a node that has outgrown its card (see
        ports_collapsed), not silently shrinking the gaps.
        """
        items = list(ports)
        if self.ports_collapsed and len(items) > 1:
            for port in items:
                port.setPos(x, HEADER_H / 2)
            return
        for i, port in enumerate(items):
            port.setPos(x, HEADER_H / 2 + ROW_H * i)

    def toggle_ports_collapsed(self) -> None:
        """Push the collapse through the undo stack like any other edit —
        it is saved with the project, so it is a graph change, not a view
        state the canvas can quietly own."""
        scene = self.scene()
        if scene is None:
            return
        from ..commands import SetPortsCollapsedCommand
        scene.undo_stack.push(SetPortsCollapsedCommand(
            scene.graph, self.node.id, not self.ports_collapsed))

    def _refresh_ports_collapsed(self) -> None:
        self.prepareGeometryChange()
        self._layout_ports()
        self._apply_port_visibility()
        for port in (*self.input_ports.values(), *self.output_ports.values()):
            # the label pill's text (and so its width) changes with the
            # collapse, which is a real bounding-rect change
            port.prepareGeometryChange()
            port.update()
        self.update()
        scene = self.scene()
        if scene is not None:
            scene.node_item_moved(self.node.id)   # wires follow the pins

    def refresh_compact(self) -> None:
        """Re-derive whether this node is a square from its own setting and
        the canvas-wide one. The single entry point: callers should not have
        to know which of the two won."""
        self.apply_compact(compact_on(self.node, self.scene()))

    def apply_compact(self, enabled: bool) -> None:
        """Switch a plain node between the compact square and the wide box.

        Every card kind ignores this — their size is their content's, and a
        Show Plot squeezed into 60px would be a chart of nothing. Called once
        when the item joins a scene (an item's scene() is None throughout
        __init__, so the setting cannot be read there) and again whenever
        either the canvas-wide setting or the node's own override changes.
        """
        if not self.plain:
            return  # a card's square is _set_folded's business, not this
        enabled = bool(enabled)
        if enabled == self._square:
            return
        self.prepareGeometryChange()
        self._square = enabled
        self.width = COMPACT_W if enabled else NODE_WIDTH
        self._name_cache = None
        self._layout_ports()
        self._layout_badges()
        self.update()
        scene = self.scene()
        if scene is not None:
            scene.node_item_moved(self.node.id)  # wires follow the pins

    def _set_folded(self, folded: bool) -> None:
        """Fold a card down to its icon, or open it back to full size — the
        mirror of apply_compact for card kinds. _apply_proxy_visibility has
        already hidden (or is about to show) the embedded widget; this is
        purely the geometry and the port layout."""
        folded = bool(folded) and self.foldable()
        if folded == self._folded:
            return
        self.prepareGeometryChange()
        self._folded = folded
        self._square = folded
        self.width = COMPACT_W if folded else self._expanded_width
        self._name_cache = None
        self._layout_ports()
        self._layout_flow_ports()
        self._layout_badges()
        self.update()
        scene = self.scene()
        if scene is not None:
            scene.node_item_moved(self.node.id)  # wires follow the pins

    def toggle_folded(self) -> None:
        """The header/corner chevron: fold the card to an icon, or open it.
        Routed through the per-node canvas-preview flag the Appearance
        dialog also writes, so there is one switch and one undo entry."""
        scene = self.scene()
        if scene is None:
            return
        from ..commands import SetPreviewEnabledCommand
        scene.undo_stack.push(SetPreviewEnabledCommand(
            scene.graph, self.node.id, not self.node.canvas_preview_enabled))

    def _ports_follow_width(self) -> None:
        """Re-anchor ports after a width change and re-route their wires."""
        self._layout_ports()
        scene = self.scene()
        if scene is not None:
            scene.node_item_moved(self.node.id)

    def port_item(self, name: str, direction: str) -> Optional[PortItem]:
        if is_flow(name):
            return self.flow_ports.get(direction)
        table = self.input_ports if direction == "input" else self.output_ports
        return table.get(name)

    def _apply_proxy_visibility(self) -> None:
        """Content-proxy visibility is gated by two independent switches: LOD
        flattening (zoomed out, transient) and the canvas-preview toggle
        (persisted, per-node). Either one hides the proxy; ports stay
        visible through both (see set_lod / _set_folded), since a folded
        node is still wireable — it has just shrunk to its icon."""
        visible = not self._flat and self.node.canvas_preview_enabled
        for proxy in (self._note_editor, self._table_proxy, self._figure_proxy,
                      self._table_viewer_proxy, self._slicer_proxy,
                      self._control_proxy, self._report_proxy, self._wiki_proxy):
            if proxy is not None:
                proxy.setVisible(visible)
        # The image card has no proxy to hide, but the same two switches say
        # whether anyone can see it — which is exactly when an animation is
        # worth spending frames on.
        if self._image is not None:
            self._image.set_playing(self._image_should_play())
        # and a compact node's mark picture, if it has one
        if self._mark_image is not None:
            self._mark_image.set_playing(self._mark_should_play())
        # a report card's animated embeds answer to the same two switches
        if self._report_animator is not None:
            self._report_animator.set_playing(self._report_should_animate())

    def set_lod(self, flat: bool) -> None:
        """Called by the scene whenever the decision changes (zoom crossing
        lod_threshold, or lod_enabled toggling): hide ports/embedded widgets
        and switch to the cheap flat paint, or restore them. A reroute dot is
        already minimal and stays as-is regardless."""
        flat = flat and not self.compact
        if flat == self._flat:
            return
        self._flat = flat
        self._apply_port_visibility()
        self._apply_proxy_visibility()
        self.update()

    def set_active(self, active: bool) -> None:
        """Fade a deactivated node back instead of repainting it.

        Opacity is the one signal that reaches every card kind at once. A
        painted overlay would have to be added to each branch of paint() and
        would still miss the embedded widgets, which are real QWidgets drawn
        by Qt, not by us; item opacity dims those too.
        """
        self._own_active = bool(active)
        self._apply_run_flags()

    def set_manual(self, manual: bool) -> None:
        """Show the play triangle: this node sits out every run that did not
        name it."""
        self._own_manual = bool(manual)
        self._apply_run_flags()

    def set_frame_flags(self, manual: bool, inactive: bool) -> None:
        """What the frames around this node are doing to it.

        A frame carries `active` and `manual` on behalf of whatever is
        inside it, and the node has no say in that and stores none of it —
        it is simply drawn as what it will be treated as on the next run.
        Which is why this is a separate pair of flags rather than a write to
        the node's own: drag the node out of the frame and it goes back to
        answering for itself, with nothing to undo.
        """
        manual, inactive = bool(manual), bool(inactive)
        if (manual, inactive) == (self._frame_manual, self._frame_inactive):
            return
        self._frame_manual = manual
        self._frame_inactive = inactive
        self._apply_run_flags()

    def held_by_frame(self) -> bool:
        """True when a frame — not the node's own flag — is holding it back."""
        return self._frame_manual and not self._own_manual

    def _apply_run_flags(self) -> None:
        """Draw the node as the next run will treat it: its own two flags,
        and whatever the frames around it add on top."""
        self._manual_badge.setVisible(self._own_manual or self._frame_manual)
        self.setOpacity(1.0 if self._own_active and not self._frame_inactive
                        else DEACTIVATED_OPACITY)
        self._layout_badges()
        self._refresh_tooltip()
        self.update()

    def set_locked(self, locked: bool) -> None:
        """Show the padlock. Refusing the move itself is itemChange's job —
        clearing ItemIsMovable is not enough, because a button node toggles
        that flag as it enters and leaves edit mode."""
        self._lock_badge.setVisible(locked)
        self._layout_badges()
        self._refresh_tooltip()
        self.update()

    def refresh_updating(self) -> None:
        """Re-decide whether this card's output is being recomputed: it is
        if the node is in a running plan, or if a reactive re-run covering
        it is queued behind whatever is running now."""
        scene = self.scene()
        requested = getattr(scene, "requested_nodes", frozenset())
        self.set_updating(
            self.node.status in (NodeStatus.QUEUED, NodeStatus.RUNNING)
            or self.node.id in requested)

    def set_updating(self, updating: bool) -> None:
        """Fade this card's *output* preview while it is being recomputed.

        The status LED already says a node is queued or running, which is
        enough when the card is a box with a label on it. A card carrying a
        chart, a rendered report or a table of numbers is different: the
        content reads as current whatever the LED beside it is doing, and on
        a flow slow enough to notice, those are the numbers being read.
        Fading them says wait without taking them away — the previous run is
        usually what the new one is being compared against.

        Only output previews fade. A Table card's grid, a slicer and a
        control are things being typed into, and dimming the user's own
        input while the flow catches up would be backwards. The main window
        drives this: the engine knows which nodes are queued, the card
        doesn't need to.
        """
        updating = bool(updating)
        if updating == self._updating:
            return
        self._updating = updating
        proxy = self._output_preview_proxy()
        if proxy is not None:
            proxy.setOpacity(0.45 if updating else 1.0)
        if self.kpi_card:   # painted, not proxied — see _paint_kpi
            self.update()

    def _output_preview_proxy(self):
        """The proxy showing computed output, or None for a card whose
        widget is an input (a Table's grid, a slicer, a control)."""
        return self._figure_proxy or self._report_proxy \
            or self._table_viewer_proxy

    def set_frozen(self, frozen: bool, stale: bool = False) -> None:
        """Show the pause glyph, ambered when the pin has been overtaken."""
        self.pin_stale = bool(frozen and stale)
        self._freeze_badge.setVisible(frozen)
        self._freeze_badge.colour = (theme.PIN_STALE if stale
                                     else theme.NODE_SUBTEXT)
        self._freeze_badge.update()
        self._layout_badges()
        self._refresh_tooltip()
        self.update()

    def set_heavy(self, heavy: bool) -> None:
        """Mark (or unmark) this node as one of the ones holding the memory.

        Driven by the resource monitor's pressure state, so it appears only
        while memory is actually short and clears when it is not. A tooltip
        would be the obvious place for the byte count, but the node's tooltip
        already belongs to its own status message; the monitor's tooltip
        carries the figures.
        """
        if self._heavy_badge.isVisible() == bool(heavy):
            return
        self._heavy_badge.setVisible(bool(heavy))
        self._layout_badges()

    def _layout_badges(self) -> None:
        """Pack the visible badges so a node showing one of them never leaves
        the other's slot empty.

        Above the header on a wide node, left to right. A square node has no
        room up there — that is where its name goes — so they move into the
        status row instead, packing leftwards from the LED.
        """
        if self._square:
            status = self._status_rect()
            y = status.center().y() - NodeBadge.H / 2
            x = self.width / 2 - LED_RADIUS - 6.0 - NodeBadge.W
            for badge in (self._heavy_badge, self._freeze_badge,
                          self._manual_badge, self._lock_badge):
                if badge.isVisible():
                    badge.setPos(x, y)
                    x -= NodeBadge.W + 3.0
            return
        x = 1.0
        for badge in (self._heavy_badge, self._freeze_badge,
                      self._manual_badge, self._lock_badge):
            if badge.isVisible():
                badge.setPos(x, -(NodeBadge.H + 3.0))
                x += NodeBadge.W + 4.0

    def set_preview_enabled(self, enabled: bool) -> None:
        """Fold this card down to an icon, or open it back to full size, per
        the canvas-preview toggle. Ports stay visible either way. On fold,
        also clears the widget's held content (matplotlib Figure / table
        model / slicer options) to actually free memory, not just skip
        future pushes; the last-known data lives in engine.cache regardless,
        so opening it again repopulates it without forcing a re-run (see
        mainwindow._on_preview_enabled_changed)."""
        if self.foldable():
            self._set_folded(not enabled)
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
        user's custom colour, which wins over the theme default.

        The custom colour is tinted over the theme header rather than used
        raw, so it stays the lighter shade of the body the theme intends and
        picker colours arrive muted — the treatment frames and page tabs use."""
        if self.broken:
            return theme.NODE_HEADER_BROKEN
        if self.node.color:
            return theme.tint(theme.NODE_HEADER, self.node.color,
                              theme.TINT_STRONG)
        return theme.NODE_HEADER

    def _body_color(self) -> QColor:
        """Effective card-body colour: the user's custom colour tinted over
        the theme body, or the theme default. Broken nodes keep the plain
        body — header/border signal it."""
        if self.node.color:
            return theme.tint(theme.NODE_BODY, self.node.color,
                              theme.TINT_SOFT)
        return theme.NODE_BODY

    def _paint_flat(self, painter: QPainter) -> None:
        """Cheap stand-in for the simplified state: one fill, no path/gradient/text —
        the per-node cost that dominates when many nodes are visible at once."""
        rect = QRectF(0, 0, self.width, self.body_height)
        painter.setPen(QPen(theme.SELECTION_OUTLINE, 1.5) if self.isSelected()
                       else Qt.NoPen)
        fill = (theme.NODE_HEADER_BROKEN if self.broken
                else self._body_color())
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
        if self._folded:
            # canvas preview off: draw the card as a plain icon, chevron and
            # all — the same square a compact node uses
            self._paint_compact(painter)
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
        if self.figure_card or self.table_viewer or self.slicer \
                or self.control or self.report_card or self.wiki_card:
            self._paint_widget_card(painter)
            return
        if self.kpi_card:
            self._paint_kpi(painter)
            return
        if self.image_card:
            self._paint_image(painter)
            return
        if self._square:
            self._paint_compact(painter)
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

    def _fold_toggle_rect(self) -> Optional[QRectF]:
        """The disclosure control that folds a card down to its icon and
        opens it again, or None when this node has no card to fold.

        In the header bar while the card is open; tucked into the icon's
        top-left corner once folded, the way a collapsed frame carries its
        own re-open control.
        """
        if not self.foldable() or self._flat:
            return None
        if self._folded:
            return QRectF(4, 4, 11, 10)
        return QRectF(7, HEADER_H / 2 - 5, 11, 10)

    def _collapse_toggle_rect(self) -> Optional[QRectF]:
        """The chevron in the header that gathers the pins up, or None when
        this node has nothing worth gathering.

        Sits just inside the header's left edge — after the fold chevron
        when the card has one, since every gatherable node is also a card
        that can fold.
        """
        if not self.collapsible():
            return None
        x = 22.0 if self._fold_toggle_rect() is not None else 7.0
        return QRectF(x, HEADER_H / 2 - 5, 11, 10)

    def _paint_collapse_toggle(self, painter: QPainter,
                               rect: QRectF) -> None:
        """A disclosure triangle: pointing down when the pins run down the
        edge, right when they are gathered into the header — it shows which
        way the ports lie, the way a tree view's does."""
        self._draw_disclosure(painter, rect, pointing_right=self.ports_collapsed)

    def _paint_fold_toggle(self, painter: QPainter, rect: QRectF) -> None:
        """A disclosure triangle: pointing down while the card is open,
        right once it has folded to an icon — the same language the ports
        chevron and a frame's use."""
        self._draw_disclosure(painter, rect, pointing_right=self._folded)

    @staticmethod
    def _draw_disclosure(painter: QPainter, rect: QRectF,
                         *, pointing_right: bool) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(theme.NODE_SUBTEXT))
        path = QPainterPath()
        if pointing_right:
            path.moveTo(rect.left() + 1, rect.top())
            path.lineTo(rect.right() - 2, rect.center().y())
            path.lineTo(rect.left() + 1, rect.bottom())
        else:
            path.moveTo(rect.left(), rect.top() + 1)
            path.lineTo(rect.right(), rect.top() + 1)
            path.lineTo(rect.center().x(), rect.bottom() - 1)
        path.closeSubpath()
        painter.drawPath(path)
        painter.restore()

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
        fold = self._fold_toggle_rect()
        if fold is not None:
            self._paint_fold_toggle(painter, fold)
        toggle = self._collapse_toggle_rect()
        if toggle is not None:
            self._paint_collapse_toggle(painter, toggle)
        left = 10.0
        for chevron in (fold, toggle):
            if chevron is not None:
                left = max(left, chevron.right() + 5)
        label_rect = QRectF(left, 0, width - left - 20, HEADER_H)
        label_text = f"⚠ {self.node.label}" if self.broken else self.node.label
        label = painter.fontMetrics().elidedText(
            label_text, Qt.ElideRight, int(label_rect.width()))
        painter.drawText(label_rect, Qt.AlignVCenter | Qt.AlignLeft, label)

        led_center_x = width - 13
        self._paint_status_led(painter, led_center_x, HEADER_H / 2,
                               self._header_color())
        self._paint_temp_edit_dot(painter, led_center_x - LED_RADIUS - 10,
                                  HEADER_H / 2)

    def _paint_status_led(self, painter: QPainter, cx: float, cy: float,
                          behind: QColor) -> None:
        """This node's status light, centred on (cx, cy)."""
        paint_status_led(painter, cx, cy,
                         status=self.node.status,
                         progress=self.node.progress,
                         pulse=self._pulse,
                         stale=self.node.dirty,
                         behind=behind)

    def _paint_temp_edit_dot(self, painter: QPainter,
                             cx: float, cy: float) -> None:
        """Unsaved temp-edit indicator — small amber dot beside status LED."""
        if not self.node._temp_edit:
            return
        radius = 3.0
        painter.setPen(QPen(theme.NODE_BORDER, 0.5))
        painter.setBrush(QBrush("#eab308"))
        painter.drawEllipse(
            QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius))

    def _paint_compact(self, painter: QPainter) -> None:
        """A plain node as a square: mark inside, name above, status below.

        No header strip, so nothing here elides the label into 150px of
        chrome — the name gets its own air above the box and is allowed to
        overhang it, which is what makes a 60px node still readable.
        """
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(0, 0, self.width, self.body_height)
        body = QPainterPath()
        body.addRoundedRect(rect, 7, 7)
        painter.fillPath(body, theme.NODE_HEADER_BROKEN if self.broken
                         else self._body_color())
        if self.isSelected():
            outline = QPen(theme.SELECTION_OUTLINE, 2.0)
        elif self.broken:
            outline = QPen(theme.NODE_BORDER_BROKEN, 1.4)
        else:
            outline = QPen(theme.NODE_BORDER, 1.2)
        painter.setPen(outline)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(body)

        self._paint_mark(painter, rect)

        # name, above the square
        painter.setPen(QPen(theme.NODE_TEXT))
        painter.setFont(self._name_font())
        name_rect = self._name_rect()
        for i, line in enumerate(self._name_layout()):
            painter.drawText(
                QRectF(name_rect.left(), name_rect.top() + i * COMPACT_NAME_H,
                       name_rect.width(), COMPACT_NAME_H),
                Qt.AlignCenter, line)

        # status row, below it
        status = self._status_rect()
        mid_y = status.center().y()
        self._paint_status_led(painter, self.width / 2, mid_y, theme.CANVAS_BG)
        self._paint_temp_edit_dot(
            painter, self.width / 2 + LED_RADIUS + 8, mid_y)

        # a folded card keeps its unfold chevron in the corner
        fold = self._fold_toggle_rect()
        if fold is not None:
            self._paint_fold_toggle(painter, fold)

    def _paint_mark(self, painter: QPainter, rect: QRectF) -> None:
        """Whatever the square carries, most specific first: a picture the
        user gave it, else their own short text, else the drawn mark its
        category maps to (or the one they picked instead). See
        ui.canvas.marks."""
        color = QColor(theme.NODE_TEXT)
        inner = rect.adjusted(COMPACT_MARK_INSET, COMPACT_MARK_INSET,
                              -COMPACT_MARK_INSET, -COMPACT_MARK_INSET)
        if self.node.mark_image:
            image = self._mark_card_image()
            if image.has_content() and not image.error:
                # A picture gets nearly the whole square rather than the
                # glyph's inset: a logo reads as the node at 56px and is a
                # smudge at 28.
                image.paint(painter,
                            rect.adjusted(COMPACT_IMAGE_INSET,
                                          COMPACT_IMAGE_INSET,
                                          -COMPACT_IMAGE_INSET,
                                          -COMPACT_IMAGE_INSET),
                            self._image_render_ratio())
                return
            # unreadable: fall through to the drawn mark rather than an
            # empty square that says nothing about which node this is
        text = self.node.mark_text.strip()
        if text:
            painter.save()
            painter.setPen(QPen(color))
            font = QFont()
            font.setPointSizeF(COMPACT_TEXT_FONT_SIZE)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, QFontMetrics(font).elidedText(
                text, Qt.ElideRight, int(rect.width() - 8)))
            painter.restore()
            return
        marks.draw(marks.mark_for(self.node), painter, inner, color)

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
        painter.fillPath(body, theme.tint(theme.BUTTON_ACCENT, self.node.color,
                                          theme.TINT_STRONG)
                         if self.node.color else theme.BUTTON_ACCENT)
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
        painter.setOpacity(0.45 if self._updating else 1.0)
        # size to fit: capped by height, with a rough width estimate to start
        # (~0.62 em average glyph width), then the real advance is measured and
        # the font shrunk until the value fits — bold digits and commas run
        # wider than the estimate, and that was clipping at the sides
        size = min(avail.height() * 0.62,
                   avail.width() / (0.62 * max(1, len(text))))
        font = painter.font()
        font.setBold(True)
        font.setPointSizeF(max(9.0, size))
        painter.setFont(font)
        advance = painter.fontMetrics().horizontalAdvance(text)
        while advance > avail.width() and font.pointSizeF() > 9.0:
            font.setPointSizeF(
                max(9.0, font.pointSizeF() * avail.width() * 0.99 / advance))
            painter.setFont(font)
            advance = painter.fontMetrics().horizontalAdvance(text)
        painter.setPen(QPen(theme.NODE_TEXT))
        painter.drawText(avail, Qt.AlignCenter, text)
        painter.setOpacity(1.0)

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

    def _paint_note(self, painter: QPainter) -> None:
        rect = QRectF(0, 0, self.width, self.body_height)
        painter.setRenderHint(QPainter.Antialiasing)
        body = QColor(self._body_color())
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
        context.palette.setColor(QPalette.Link, theme.SELECTION_OUTLINE)
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
        if self.report_card:
            return REPORT_MIN_W, REPORT_MAX_W, REPORT_MIN_H, REPORT_MAX_H
        if self.wiki_card:
            return WIKI_MIN_W, WIKI_MAX_W, WIKI_MIN_H, WIKI_MAX_H
        if self.kpi_card:
            return KPI_MIN_W, KPI_MAX_W, KPI_MIN_H, KPI_MAX_H
        if self.image_card:
            return IMAGE_MIN_W, IMAGE_MAX_W, IMAGE_MIN_H, IMAGE_MAX_H
        if self.slicer:
            return SLICER_MIN_W, SLICER_MAX_W, SLICER_MIN_H, SLICER_MAX_H
        if self.control:
            return (CONTROL_MIN_W, CONTROL_MAX_W,
                    CONTROL_MIN_H, CONTROL_MAX_H)
        if self.button:
            return BUTTON_MIN_W, BUTTON_MAX_W, BUTTON_MIN_H, BUTTON_MAX_H
        return NOTE_MIN_W, NOTE_MAX_W, NOTE_MIN_H, NOTE_MAX_H

    def _resizable(self) -> bool:
        """Whether this card offers a resize grip.

        A card kind is not enough: the size is *stored* as the node's own
        `width`/`height` params, so a node that doesn't declare them has
        nowhere to put it. Committing a drag on one used to raise straight
        out of the mouse handler ("node 'Control Template' has no param
        'width'"), which is what happens to any forked card whose author
        left the size params out — an easy thing to do, since they are
        optional in every other respect.
        """
        if self.button:
            return bool(self._button_edit)
        if self._folded:
            return False  # a folded card is its fixed icon until it opens
        card = bool(self.note or self.table or self.figure_card
                    or self.table_viewer or self.kpi_card or self.image_card
                    or self.slicer
                    or self.control or self.report_card or self.wiki_card)
        return card and all(self.node.spec.param(name) is not None
                            for name in ("width", "height"))

    def _header_h(self) -> float:
        """Height of the drag bar — the only region a move can start from.
        Headerless kinds (reroute, button, the compact square) drag by their
        whole body, having nothing else to grab; notes get a thin top strip.

        A square node's name sits at negative y, so it comes in under this
        too and drags the node along with it — which is what you expect of a
        label attached to a box."""
        if self.compact or self.button or self._square:
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
        # A resize edge wins: the grip and the pill do not overlap, but the
        # answer should not depend on that staying true.
        step = self._pager_at(event.pos()) if edge is None else 0
        if step != self._pager_hover:
            self._pager_hover = step
            self.update()
        if step:
            self.setCursor(Qt.PointingHandCursor)
        elif edge == "corner":
            self.setCursor(Qt.SizeFDiagCursor)
        elif edge == "right":
            self.setCursor(Qt.SizeHorCursor)
        elif edge == "bottom":
            self.setCursor(Qt.SizeVerCursor)
        elif self._hovering_a_chevron(event.pos()):
            # the fold / gather-ports triangles are click targets, not drag
            # bars — say so, even on a folded node whose whole body drags
            self.setCursor(Qt.PointingHandCursor)
        elif self.note and self.note_link_at(event.pos()):
            self.setCursor(Qt.PointingHandCursor)  # a clickable Markdown link
        elif self.button and self._button_edit:
            self.setCursor(Qt.SizeAllCursor)  # whole face drags in edit mode
        elif (not self.compact and not self.button
                and event.pos().y() < self._header_h()):
            self.setCursor(Qt.SizeAllCursor)  # the header drag bar
        else:
            self.unsetCursor()
        super().hoverMoveEvent(event)

    def _hovering_a_chevron(self, pos: QPointF) -> bool:
        """Is the cursor over the fold or the gather-ports disclosure
        triangle — the two header/corner glyphs a click toggles. Same
        forgiving hit boxes mousePressEvent uses."""
        fold = self._fold_toggle_rect()
        if fold is not None and fold.adjusted(-4, -4, 4, 4).contains(pos):
            return True
        ports = self._collapse_toggle_rect()
        return (ports is not None and not self._flat
                and ports.adjusted(-3, -4, 3, 4).contains(pos))

    def hoverLeaveEvent(self, event) -> None:
        self.unsetCursor()
        if self._pager_hover:
            self._pager_hover = 0
            self.update()
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
        # Qt calls this for every kind of change — children added, scene
        # assigned, transform, visibility — and only three are acted on. The
        # rest used to fall through four comparisons each; there are tens of
        # thousands of them while a project loads and a steady stream of them
        # while anything is dragged.
        if change not in _HANDLED_ITEM_CHANGES:
            return super().itemChange(change, value)
        if change == QGraphicsItem.ItemPositionChange and self.node.locked:
            # Refused here rather than by clearing ItemIsMovable: a group
            # drag moves items the mouse never touched, and a button node
            # sets that flag itself when it enters edit mode.
            return self.pos()
        if change == QGraphicsItem.ItemPositionChange and self._dragging \
                and snapping_active(self.scene()):
            step = grid_step(self.scene())
            x, y = snap_point(value.x(), value.y(), step)
            return QPointF(x, y)
        if change == QGraphicsItem.ItemPositionHasChanged:
            scene = self.scene()
            if scene is not None:
                scene.node_item_moved(self.node.id)
        if change == QGraphicsItem.ItemVisibleHasChanged:
            # re-derives every "is anyone looking at this" answer, which is
            # where the QMovie playback decisions live
            self._apply_proxy_visibility()
        if change == QGraphicsItem.ItemSelectedHasChanged \
                and self._button_edit and not value:
            # Clicking the canvas or another node drops the selection, which
            # leaves button edit mode and restores fire-on-click.
            self._exit_button_edit()
        return super().itemChange(change, value)

    def mousePressEvent(self, event) -> None:
        fold = self._fold_toggle_rect()
        if (event.button() == Qt.LeftButton and fold is not None
                # generous: an 11x10 glyph is a small target, and a mistaken
                # fold costs one Ctrl+Z
                and fold.adjusted(-4, -4, 4, 4).contains(event.pos())):
            self.toggle_folded()
            event.accept()
            return
        if (self.note and event.button() == Qt.LeftButton
                and not event.modifiers()
                and self.note_link_at(event.pos())):
            # A link on a Note card: swallow the press so it neither selects
            # nor drags the card; mouseReleaseEvent opens it if the cursor
            # did not travel (and it was not a double-click to edit).
            self._note_link_press = QPointF(event.pos())
            event.accept()
            return
        toggle = self._collapse_toggle_rect()
        if (event.button() == Qt.LeftButton and toggle is not None
                and not self._flat
                # generous: an 11x10 glyph is a small target, and hitting it
                # by accident only ever costs one Ctrl+Z
                and toggle.adjusted(-3, -4, 3, 4).contains(event.pos())):
            self.toggle_ports_collapsed()
            event.accept()
            return
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
            # A PDF card's chevrons. Accepted rather than passed on, so
            # paging a card does not also select or drag the node.
            step = self._pager_at(event.pos())
            if step:
                self._step_page(step)
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
                elif self.report_card:
                    self._layout_report_proxy()
                elif self.wiki_card:
                    self._layout_wiki_proxy()
                elif self.slicer:
                    self._layout_slicer_proxy()
                elif self.control:
                    self._layout_control_proxy()
                self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        scene = self.scene()
        if event.modifiers() & Qt.ControlModifier:
            # Ctrl beats every special case below — including a note's and a
            # report's in-place editors, which are exactly the nodes with no
            # other way to reach their code.
            if scene is not None:
                scene.node_window_requested.emit(self.node.id)
            event.accept()
            return
        if self.note:
            self.start_note_edit()
            event.accept()
            return
        if self.report_card and not self._folded and event.pos().y() >= HEADER_H:
            # body: edit the text in place. The header still renames, and
            # Edit Code is still on the context menu.
            self.start_note_edit()
            event.accept()
            return
        if self.compact:
            # A reroute is all dot and no header, so there is no header to
            # aim at — the whole thing renames. Its label is the floating
            # pill above it, which is the only thing about a reroute worth
            # editing; opening its code (what this used to do) is useless.
            if scene is not None:
                scene.node_rename_requested.emit(self.node.id)
            event.accept()
            return
        if self._square:
            # The header/body split, relocated: the name renames, the square
            # opens the node's code, same as clicking a header vs. a body.
            name = self._name_rect()
            if scene is not None:
                if name is not None and name.contains(event.pos()):
                    scene.node_rename_requested.emit(self.node.id)
                else:
                    scene.node_double_clicked.emit(self.node.id)
            event.accept()
            return
        if not self.button and event.pos().y() < HEADER_H:
            if scene is not None:
                scene.node_rename_requested.emit(self.node.id)
            event.accept()
            return
        if scene is not None:
            scene.node_double_clicked.emit(self.node.id)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._note_link_press is not None:
            press, self._note_link_press = self._note_link_press, None
            href = self.note_link_at(event.pos())
            if href and (event.pos() - press).manhattanLength() <= 4:
                # Defer past the double-click window: a double-click on a
                # link should edit the card, not also launch the browser.
                # _open_note_link bails if the editor opened in between.
                QTimer.singleShot(
                    QApplication.doubleClickInterval(),
                    lambda h=href: self._open_note_link(h))
            event.accept()
            return
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
            elif self.report_card:
                self._layout_report_proxy()
            elif self.wiki_card:
                self._layout_wiki_proxy()
            elif self.slicer:
                self._layout_slicer_proxy()
            elif self.control:
                self._layout_control_proxy()
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
        if self.node.status == NodeStatus.RUNNING and not self.node.progress:
            self._start_pulse()
        else:
            self._stop_pulse()
        self.refresh_updating()
        self._refresh_tooltip()
        self.update()

    def on_progress_changed(self) -> None:
        """The pulse and the ring are alternatives, not layers: a node that
        has started reporting a fraction has no use for an animation running
        at frame rate behind it, and one that drops back to none should not
        be left sitting on a dead LED."""
        if self.node.status == NodeStatus.RUNNING:
            if self.node.progress:
                self._stop_pulse()
            else:
                self._start_pulse()
        self.update()

    def _refresh_tooltip(self) -> None:
        """Error status wins the tooltip slot over the frame-state and manual
        notes (a padlock or a frozen badge still speaks first, since those
        stop the node from running at all); otherwise fall back to the node's
        own description (currently only surfaced for reroutes)."""
        if self.node.locked:
            # The padlock says *that* it is locked; only a tooltip has room
            # to say what that means and how to undo it.
            self.setToolTip("Locked — params, code and position are "
                            "read-only. Right-click > Unlock to edit.")
        elif self.node.frozen:
            self.setToolTip("Frozen — serving its last output and skipped by "
                            "every run. Right-click > Unfreeze to run it "
                            "again.")
        elif self.node.status == NodeStatus.ERROR:
            # Ahead of the frame-hold / manual notes below: a node that ran
            # and errored has one thing worth saying, and "held by its frame"
            # over the top of it hides exactly why the last run stopped.
            self.setToolTip(self.node.status_message)
        elif self._frame_inactive and self.node.active:
            self.setToolTip("Disabled by its frame — nothing in that frame "
                            "runs, nor anything below it. Right-click the "
                            "frame > Enable frame.")
        elif self.held_by_frame():
            self.setToolTip("Held by its frame — Run All walks past this "
                            "one. Run the frame, or drag the node out of it.")
        elif self.node.manual:
            self.setToolTip("Manual — Run All walks past this one. Run it "
                            "from the right-click menu, or from an Action "
                            "Button that names it.")
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
