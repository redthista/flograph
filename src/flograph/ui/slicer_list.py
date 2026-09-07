"""The Slicer's card body — hosted by the canvas card and by dashboard
tiles. The widget only reflects and reports the selection; the host commits
the emitted param value and triggers the downstream re-run.

Three things live here:

* `_Selection` — what is ticked, as **paths** down the slicer's columns
  (see `flograph.core.slicer`). It owns every rule about ticking: a parent
  tick standing for its children, unticking one child of a ticked parent,
  and rolling a fully-ticked set of children back up into the parent so the
  saved param stays the size of what you meant rather than the size of the
  data.
* three views over it — a checkbox **tree** (a plain list when there is one
  column), **cards** you click, and a **dropdown**. They are views in the
  strict sense: none of them holds selection state, so switching layout
  cannot change what is selected, and two views of the same node (a canvas
  card and its dashboard tile) cannot drift apart.
* `SlicerPanel` — the whole assembly, and the only thing a host talks to.

A view never edits the selection *and* redraws itself: it asks the model to
change, then rebuilds from the model. A tick can flip an ancestor three
levels up from part-filled to filled, so redrawing only the row that was
clicked would be wrong more often than it was right.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QGridLayout, QLabel, QLineEdit, QMenu, QScrollArea,
    QSizePolicy, QStyle, QStyleOptionButton, QStyleOptionViewItem,
    QStyledItemDelegate, QToolButton, QTreeWidget, QTreeWidgetItem,
    QTreeWidgetItemIterator, QVBoxLayout, QWidget, QWidgetAction,
)

from flograph.core.slicer import (SlicerOptions, TreeNode, dump_paths,
                                  is_descendant, normalise, path_label,
                                  selected_paths)

from . import theme
from .flow_layout import FlowLayout

# How many rows to *build at once*. Not a cap on the slicer: the full value
# list is held in the model and every value is reachable through the search
# box, which re-renders to the matches. Qt builds one child per row, so
# materialising tens of thousands of them at once locks the UI up while it
# works and scrolls badly afterwards — this bounds that cost without
# bounding what the slicer can filter on. Ticks on values outside the
# rendered window are kept (they live in the selection, not in the rows) and
# reported, so nothing is lost by a value not currently having a row.
RENDER_BUDGET = 500
MODES = ("multi", "single")
LAYOUTS = ("list", "cards", "dropdown")

#: role carrying a row's path, so a view can go from a clicked widget back
#: to the model without keeping a parallel index
_PATH_ROLE = Qt.UserRole + 1

#: the label on a filled tile, once the accent is too light for white
_DARK_INK = "#111827"


def accent_colour(value: str) -> QColor:
    """The slicer's accent as a colour: what the node's "accent" param says,
    or the theme's own button accent when it says nothing.

    A garbled hex is treated as "nothing" rather than allowed through as
    QColor's invalid black, which would silently paint every tick the same
    colour as the card and read as the slicer having broken.
    """
    colour = QColor(value) if value else QColor()
    return colour if colour.isValid() else QColor(theme.BUTTON_ACCENT)


def ink_on(colour: QColor) -> str:
    """Near-black or white — whichever a label stays readable in on top of
    `colour`. A fixed white label disappears on a yellow or lime accent, and
    picking one of those is exactly the sort of thing a filter panel does."""
    luminance = (0.299 * colour.red() + 0.587 * colour.green()
                 + 0.114 * colour.blue()) / 255
    return _DARK_INK if luminance > 0.6 else "#ffffff"


# --------------------------------------------------------------- selection

class _Selection:
    """What is ticked, and every rule for changing it.

    Deliberately free of any widget: the three views and both hosts share
    one of these, and a rule that lived in a view would be a rule the other
    two layouts quietly did differently.
    """

    def __init__(self) -> None:
        self.options = SlicerOptions([], [])
        self.mode = "multi"
        self.show_counts = False
        # chrome and colour live here beside mode rather than on each view:
        # the dropdown builds a second toolbar and a second tree inside its
        # popup, and anything held per-view would have to be handed to both
        self.show_search = True
        self.show_buttons = True
        self.accent = ""
        self.filter_text = ""
        self.paths: list[tuple[str, ...]] = []
        self._roots: list[TreeNode] = []
        self._index: dict[tuple[str, ...], TreeNode] = {}

    # ---- what there is to pick from

    def set_options(self, options: SlicerOptions) -> None:
        self.options = options
        self._roots = options.tree()
        self._index = {node.path: node
                       for root in self._roots for node in root.walk()}
        # a tick on something the column no longer offers has nothing to
        # draw and nothing to filter; it is dropped from the view but not
        # committed back, so a momentary gap upstream can't wipe a selection
        self.paths = [p for p in self.paths if self._reachable(p)]

    def _reachable(self, path) -> bool:
        """Is `path` still a place in the tree? A path shallower than the
        full depth is a branch, which is as real as a leaf."""
        return tuple(path) in self._index

    @property
    def depth(self) -> int:
        return self.options.depth

    def node(self, path) -> Optional[TreeNode]:
        return self._index.get(tuple(path))

    # ---- reading the state

    def covered(self, path) -> bool:
        """Is this path inside something already ticked? True for the ticked
        path itself and for everything under it."""
        path = tuple(path)
        return any(sel == path or is_descendant(path, sel)
                   for sel in self.paths)

    def state(self, node: TreeNode) -> Qt.CheckState:
        """Filled / part-filled / empty for one row.

        Computed, never stored: a parent whose children are all ticked reads
        as ticked whether or not the parent itself is in the selection, so
        the two ways of arriving at "all of north" look identical.
        """
        if self.covered(node.path):
            return Qt.Checked
        if node.children:
            states = [self.state(child) for child in node.children]
            if all(s == Qt.Checked for s in states):
                return Qt.Checked
            if any(s != Qt.Unchecked for s in states):
                return Qt.PartiallyChecked
        return Qt.Unchecked

    def is_checked(self, path) -> bool:
        node = self.node(path)
        return node is not None and self.state(node) == Qt.Checked

    # ---- changing it

    def set_paths(self, paths) -> None:
        self.paths = self._compact(normalise(paths))

    def toggle(self, path) -> None:
        path = tuple(path)
        was_on = self.is_checked(path)
        if self.mode == "single":
            # radio behaviour: one at a time, and the ticked one clears
            self.paths = [] if was_on else [path]
            return
        if was_on:
            self._untick(path)
        else:
            kept = [p for p in self.paths if not is_descendant(p, path)]
            kept.append(path)
            self.paths = self._compact(normalise(kept))

    def _untick(self, path) -> None:
        """Clear `path`, including when what is ticked is an *ancestor* of
        it: "north" minus "north > store A" is the rest of north's stores,
        so the ancestor is replaced by the siblings it stood for, level by
        level down to the row that was clicked."""
        kept: list[tuple[str, ...]] = []
        for sel in self.paths:
            if sel == path or is_descendant(sel, path):
                continue                       # inside what is being cleared
            if is_descendant(path, sel):
                kept.extend(self._siblings_along(sel, path))
                continue
            kept.append(sel)
        self.paths = self._compact(normalise(kept))

    def _siblings_along(self, ancestor, path) -> list[tuple[str, ...]]:
        """Everything under `ancestor` that is *not* on the way down to
        `path` — the branches a broken-up parent tick leaves behind."""
        out: list[tuple[str, ...]] = []
        for depth in range(len(ancestor), len(path)):
            parent = self._index.get(tuple(path[:depth]))
            if parent is None:
                continue
            for child in parent.children:
                if child.path != tuple(path[:depth + 1]):
                    out.append(child.path)
        return out

    def _compact(self, paths) -> list[tuple[str, ...]]:
        """Roll a fully-ticked set of children up into their parent.

        Without this, Select All on a two-level slicer over a wide table
        writes every leaf path into the saved param — thousands of entries
        describing "everything". Purely a tidying step: `state()` already
        draws both forms the same and `matches()` already filters them the
        same.
        """
        chosen = {tuple(p) for p in paths}
        # deepest first, so a rolled-up level is available to the one above
        for node in sorted((n for root in self._roots for n in root.walk()
                            if n.children),
                           key=lambda n: -n.depth):
            if node.path in chosen:
                continue
            if all(child.path in chosen for child in node.children):
                for child in node.children:
                    chosen.discard(child.path)
                chosen.add(node.path)
        order = {node.path: i for i, node in
                 enumerate(n for root in self._roots for n in root.walk())}
        return sorted(chosen, key=lambda p: order.get(p, len(order)))

    def trim_to_single(self) -> bool:
        """Entering single mode with several ticks: keep the first, so the
        card and the param it commits never disagree about how many values
        are active. True when something was dropped."""
        if len(self.paths) <= 1:
            return False
        self.paths = self.paths[:1]
        return True

    def select_all(self) -> bool:
        """Tick everything the search currently matches — a no-op in single
        mode, where only one value can be picked."""
        if self.mode == "single":
            return False
        before = list(self.paths)
        self.set_paths(list(self.paths) + self.matching_paths())
        return self.paths != before

    def clear_all(self) -> bool:
        """Untick everything the search currently matches."""
        before = list(self.paths)
        for path in self.matching_paths():
            if self.is_checked(path):
                self._untick(path)
        return self.paths != before

    def matching_paths(self) -> list[tuple[str, ...]]:
        """The deepest rows the search matches — what All / None act on.
        Reaches matches with no row built, not just the ones on screen."""
        out: list[tuple[str, ...]] = []

        def visit(visible):
            for node, children in visible:
                if children:
                    visit(children)
                else:
                    out.append(node.path)
        visit(self.visible())
        return out

    # ---- what to draw

    def visible(self) -> list:
        """The tree the search leaves, as nested (node, children) pairs.

        A row survives if it matches, if an ancestor matched (its whole
        branch is relevant), if a descendant matched (you need the branch to
        reach it), or if it is ticked — a tick always keeps a row, so a
        search never hides what it would be undoing.
        """
        needle = self.filter_text.lower()

        def visit(node: TreeNode, ancestor_hit: bool):
            hit = ancestor_hit or not needle or needle in node.value.lower()
            children = [kid for kid in
                        (visit(child, hit) for child in node.children)
                        if kid is not None]
            if hit or children or self.state(node) != Qt.Unchecked:
                return (node, children)
            return None

        return [row for row in (visit(root, False) for root in self._roots)
                if row is not None]

    def flat_rows(self, budget: int = RENDER_BUDGET):
        """`visible()` flattened for a list-shaped view: (node, depth) in
        display order, plus how many rows were left unbuilt."""
        rows: list[tuple[TreeNode, int]] = []
        overflow = [0]

        def walk(entries, depth):
            for node, children in entries:
                if len(rows) >= budget:
                    overflow[0] += 1 + _count(children)
                    continue
                rows.append((node, depth))
                walk(children, depth + 1)

        def _count(entries) -> int:
            return sum(1 + _count(kids) for _n, kids in entries)

        walk(self.visible(), 0)
        return rows, overflow[0]

    # ---- reporting

    def committed_value(self) -> str:
        return dump_paths(self.paths)

    def selected_leaves(self) -> list[tuple[str, ...]]:
        """Every full-depth row currently ticked — the unit the summary
        counts, so "3/12" means three of twelve rows of data, not three of
        twelve entries in the param."""
        return [path for path in self.options.paths if self.covered(path)]

    def summary(self) -> str:
        total = len(self.options.paths)
        if not total:
            return ""
        return f"{len(self.selected_leaves())}/{total}"

    def button_label(self) -> str:
        """What a dropdown says when it is shut.

        Nothing ticked means the slicer passes everything, which reads as
        "All" — not "none". So does ticking *every* value, because it keeps
        exactly the same rows: a shut dropdown should say what comes
        through it, and "12 selected" over twelve values is a count of the
        clicking rather than an answer.
        """
        if not self.paths:
            return "All"
        total = len(self.options.paths)
        if total and len(self.selected_leaves()) == total:
            return "All"
        if len(self.paths) == 1:
            return path_label(self.paths[0])
        return f"{len(self.paths)} selected"

    def label_for(self, node: TreeNode) -> str:
        if self.show_counts and node.count is not None:
            return f"{node.value}  ({node.count:,})"
        return node.value


# ------------------------------------------------------------------- views

class _IndicatorDelegate(QStyledItemDelegate):
    """Draws each row's check indicator itself, when the default one will
    not do: as a radio button in single mode, and in the slicer's accent
    colour once one is set.

    Qt has no "exclusive" tree widget, so single mode is still checkboxes
    underneath — but a checkbox promises you can tick several, which single
    mode then silently undoes. Every tool this borrows from (Power BI,
    Excel) draws radios there, so the widget does too.

    The accent is painted rather than styled because a stylesheet cannot
    put a *tick* inside `QTreeWidget::indicator` — only a background and a
    border, or an image from a resource. Styling it at all also replaces
    the native indicator wholesale, so every state not written out renders
    blank. Painting keeps all three states in one place and costs a rect
    and a three-point path per row.

    Purely cosmetic either way: check state is still what the view stores
    and reports.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.radio = False
        #: None leaves the platform style to draw a normal checkbox
        self.accent: Optional[QColor] = None

    def paint(self, painter, option, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        has_check = bool(opt.features
                         & QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator)
        if not has_check or not (self.radio or self.accent is not None):
            super().paint(painter, option, index)
            return

        style = opt.widget.style() if opt.widget else QApplication.style()
        # both measured while the indicator is still declared: dropping it is
        # what lets the row draw without a checkbox, but it also collapses the
        # column the indicator occupied, sliding the label left over the radio
        rect = style.subElementRect(
            QStyle.SE_ItemViewItemCheckIndicator, opt, opt.widget)
        text_left = style.subElementRect(
            QStyle.SE_ItemViewItemText, opt, opt.widget).left()
        state = opt.checkState

        opt.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        opt.checkState = Qt.Unchecked
        # measured rather than assumed: the gap a style leaves around the
        # indicator is a style detail, and the text layout is linear in
        # rect.left, so re-indenting by the difference lands it exactly back
        collapsed_left = style.subElementRect(
            QStyle.SE_ItemViewItemText, opt, opt.widget).left()
        opt.rect = option.rect.adjusted(text_left - collapsed_left, 0, 0, 0)
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)

        if self.accent is None:
            button = QStyleOptionButton()
            button.rect = rect
            button.state = QStyle.State_Enabled | (
                QStyle.State_On if state == Qt.Checked else QStyle.State_Off)
            style.drawPrimitive(
                QStyle.PE_IndicatorRadioButton, button, painter, opt.widget)
            return
        _paint_indicator(painter, rect, state, self.accent, self.radio)


def _paint_indicator(painter, rect: QRect, state, accent: QColor,
                     radio: bool) -> None:
    """One tick box (or radio) in the accent colour.

    Kept square and centred in whatever rect the style measured out, so the
    row's text still lines up with a natively-drawn one beside it — the
    label position is the style's business, not ours.
    """
    size = min(rect.width(), rect.height())
    box = QRectF(rect.x() + (rect.width() - size) / 2.0,
                 rect.y() + (rect.height() - size) / 2.0, size, size)
    box = box.adjusted(1.5, 1.5, -1.5, -1.5)
    on = state == Qt.Checked
    partial = state == Qt.PartiallyChecked

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(QPen(accent if (on or partial)
                        else QColor(theme.NODE_BORDER), 1.4))
    painter.setBrush(accent if on else Qt.NoBrush)
    if radio:
        painter.drawEllipse(box)
        if on:
            # the dot is punched out of the fill rather than drawn over it,
            # so a light accent keeps a visible centre
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(ink_on(accent)))
            painter.drawEllipse(box.adjusted(3, 3, -3, -3))
        painter.restore()
        return

    painter.drawRoundedRect(box, 2.5, 2.5)
    if on:
        tick = QPainterPath()
        tick.moveTo(box.left() + size * 0.22, box.top() + size * 0.46)
        tick.lineTo(box.left() + size * 0.40, box.top() + size * 0.66)
        tick.lineTo(box.left() + size * 0.76, box.top() + size * 0.24)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(ink_on(accent)), 1.8, Qt.SolidLine,
                            Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(tick)
    elif partial:
        # a bar, not a half-fill: "some of what is under this" reads as one
        # mark, and it stays legible at the 12px a dense tree draws at
        painter.setPen(Qt.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(box.adjusted(3, size * 0.36, -3,
                                             -size * 0.36), 1.0, 1.0)
    painter.restore()


class SlicerTreeWidget(QTreeWidget):
    """The checkbox layout: a flat list on one column, a hierarchy on
    several. One widget for both, because a tree with the branch decoration
    off *is* the list — keeping two would be two places for a bug in how a
    row ticks."""

    selection_changed = Signal()

    def __init__(self, model: _Selection, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self._syncing = False
        # true while a tick of ours is still being delivered by Qt — see
        # rebuild(), which must not free rows underneath that delivery
        self._in_change = False
        self._built: list = []
        self.setHeaderHidden(True)
        self.setColumnCount(1)
        self.setUniformRowHeights(True)
        self.setExpandsOnDoubleClick(False)
        self.setIndentation(12)
        self._styled_for = None
        self._apply_style()
        self._delegate = _IndicatorDelegate(self)
        self.setItemDelegate(self._delegate)
        self.itemChanged.connect(self._on_item_changed)

    def _apply_style(self) -> None:
        """Restyle for the current accent. Guarded by `_styled_for` because
        setting a stylesheet re-polishes every row, and rebuild() runs on
        every tick — re-applying an identical sheet would be a full repaint
        per click."""
        accent = self._model.accent
        if accent == self._styled_for:
            return
        self._styled_for = accent
        highlight = accent_colour(accent)
        highlight.setAlpha(60)
        self.setStyleSheet(
            f"QTreeWidget {{ background: {theme.NODE_BODY.name()};"
            f" color: {theme.NODE_TEXT.name()}; border: none;"
            f" font-size: 9pt; }}"
            f"QTreeWidget::item {{ padding: 1px 2px; }}"
            f"QTreeWidget::item:selected {{ background: rgba("
            f"{highlight.red()}, {highlight.green()}, {highlight.blue()},"
            f" {highlight.alpha()}); color: {theme.NODE_TEXT.name()}; }}")

    # ---- building

    def rebuild(self) -> None:
        rows, hidden = self._model.flat_rows()
        signature = [(node.path, depth) for node, depth in rows] + \
            ([("\u2026", hidden)] if hidden else [])
        self._delegate.radio = self._model.mode == "single"
        # None (not the theme colour) when nothing was chosen, so the rows
        # keep the platform's own checkbox rather than a hand-drawn
        # look-alike of it
        self._delegate.accent = (accent_colour(self._model.accent)
                                 if self._model.accent else None)
        self._apply_style()
        self.setRootIsDecorated(self._model.depth > 1)
        self.viewport().update()
        if signature == self._built:
            # the same rows, drawn differently — a tick, a mode flip, counts
            # switched on. Rebuilding would throw away the scroll position
            # and the open branches to end up looking identical.
            self.refresh_states()
            return
        if self._in_change:
            # Qt is still delivering the change that led here, and the item
            # it is holding is one of the rows about to be freed. Redraw what
            # is there and do the real rebuild once the stack has unwound.
            self.refresh_states()
            QTimer.singleShot(0, self.rebuild)
            return
        expanded = self._expanded_paths()
        self._built = signature
        self._syncing = True
        try:
            self.clear()
            stack: list[tuple[int, QTreeWidgetItem]] = []
            for node, depth in rows:
                item = QTreeWidgetItem([self._model.label_for(node)])
                item.setData(0, _PATH_ROLE, node.path)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                item.setCheckState(0, self._model.state(node))
                if len(node.path) > 1:
                    item.setToolTip(0, path_label(node.path))
                while stack and stack[-1][0] >= depth:
                    stack.pop()
                if stack:
                    stack[-1][1].addChild(item)
                else:
                    self.addTopLevelItem(item)
                stack.append((depth, item))
                # a branch opens by default — a hierarchy that arrives shut
                # looks like a one-column slicer that lost its values
                item.setExpanded(not expanded or node.path in expanded)
            if hidden:
                note = QTreeWidgetItem(
                    [f"… {hidden:,} more — search to narrow the list"
                     if not self._model.filter_text
                     else f"… {hidden:,} more match — refine the search"])
                note.setFlags(Qt.NoItemFlags)
                self.addTopLevelItem(note)
        finally:
            self._syncing = False

    def _expanded_paths(self) -> set:
        """Which branches are open right now, so a rebuild (every tick
        rebuilds) doesn't collapse the tree under the hand that ticked."""
        out = set()
        it = QTreeWidgetItemIterator(self)
        while it.value():
            item = it.value()
            path = item.data(0, _PATH_ROLE)
            if path is not None and item.isExpanded():
                out.add(tuple(path))
            it += 1
        return out

    # ---- interaction

    def _indicator_rect(self, item: QTreeWidgetItem) -> QRect:
        """Where this row's tick box is drawn, in viewport coordinates."""
        option = QStyleOptionViewItem()
        self.initViewItemOption(option)
        option.rect = self.visualItemRect(item)
        option.features |= \
            QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        return self.style().subElementRect(
            QStyle.SE_ItemViewItemCheckIndicator, option, self)

    def mouseReleaseEvent(self, event) -> None:
        """Clicking anywhere on a row ticks it, not just the tick box. A
        slicer row reads as one target — Power BI and Excel both treat it
        that way — and hitting a 14px box is needless precision. The tick box
        itself and the expander arrow are left to the base class, which
        already handles both; doing it here too would toggle twice."""
        position = event.position().toPoint()
        item = self.itemAt(position)
        rect = self.visualItemRect(item) if item is not None else QRect()
        if item is not None and item.flags() & Qt.ItemIsUserCheckable \
                and position.x() >= rect.left() \
                and not self._indicator_rect(item).contains(position):
            self._toggle(item)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _on_item_changed(self, item, _column) -> None:
        if self._syncing:
            return
        self._toggle(item)

    def _toggle(self, item) -> None:
        path = item.data(0, _PATH_ROLE)
        if path is None:
            return
        self._model.toggle(tuple(path))
        self._in_change = True
        try:
            self.refresh_states()
            self.selection_changed.emit()
        finally:
            self._in_change = False

    def refresh_states(self) -> None:
        """Re-read every built row's tick from the model, without touching
        which rows exist.

        A tick can never change the row *set* — only how the rows are drawn,
        and it can redraw rows far from the one clicked (an ancestor filling
        in, a sibling emptying). Rebuilding here instead would destroy, from
        inside Qt's own mouse handling, the very item Qt is still holding —
        which is a segfault, not a repaint.
        """
        self._syncing = True
        try:
            walker = QTreeWidgetItemIterator(self)
            while walker.value():
                item = walker.value()
                path = item.data(0, _PATH_ROLE)
                node = self._model.node(path) if path is not None else None
                if node is not None:
                    item.setCheckState(0, self._model.state(node))
                    item.setText(0, self._model.label_for(node))
                walker += 1
        finally:
            self._syncing = False


class _CardsView(QScrollArea):
    """The tile layout: every value a button you click, wrapping to as many
    rows as the card is wide — Power BI's "tile" slicer. A hierarchy keeps
    its shape: a branch is a button of its own (click it for the whole
    branch) with its children indented underneath."""

    selection_changed = Signal()

    #: how far each level of a hierarchy is indented
    INDENT = 10

    def __init__(self, model: _Selection, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet(
            f"QScrollArea {{ background: {theme.NODE_BODY.name()};"
            f" border: none; }}")
        self._host = QWidget()
        self._host.setStyleSheet(f"background: {theme.NODE_BODY.name()};")
        self._column = QVBoxLayout(self._host)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._column.setSpacing(2)
        self.setWidget(self._host)
        self._buttons: dict[tuple[str, ...], QToolButton] = {}
        self._built: list = []
        self._in_change = False
        self._style_for: Optional[str] = None
        self._style = ""
        self._ensure_style()

    def _ensure_style(self) -> bool:
        """Recompute the tile stylesheet if the accent moved. Returns
        whether it did, so a caller knows to push it onto the tiles that
        already exist."""
        if self._style_for == self._model.accent:
            return False
        self._style_for = self._model.accent
        self._style = card_style(self._model.accent)
        return True

    def rebuild(self) -> None:
        restyle = self._ensure_style()
        signature = [node.path for node, _kids in
                     _flatten(self._model.visible())]
        if restyle:
            # every tile carries its own copy of the sheet, so a colour
            # change has to reach each of them; the rows themselves are
            # unchanged, so this is not a reason to rebuild
            for button in self._buttons.values():
                button.setStyleSheet(self._style)
        if signature == self._built and self._buttons:
            self.refresh_states()
            return
        if self._in_change:
            # the tile whose click we are inside is one of these — see the
            # tree's rebuild for why that cannot be freed here
            self.refresh_states()
            QTimer.singleShot(0, self.rebuild)
            return
        self._built = signature
        _clear_layout(self._column)
        self._buttons = {}
        built = self._render(self._model.visible(), 0, RENDER_BUDGET)
        if built < 0:
            note = QLabel("… more values — search to narrow the list")
            note.setStyleSheet(
                f"color: {theme.NODE_SUBTEXT.name()}; font-size: 8pt;")
            self._column.addWidget(note)
        self._column.addStretch(1)

    def _render(self, entries, depth: int, budget: int) -> int:
        """Cards for one level, then a block per branch. Returns how much of
        the budget is left, or -1 once it ran out."""
        leaves = [(node, kids) for node, kids in entries if not kids]
        branches = [(node, kids) for node, kids in entries if kids]
        if leaves:
            flow = FlowLayout(margin=0, spacing=3)
            for node, _kids in leaves:
                if budget <= 0:
                    return -1
                flow.addWidget(self._card(node))
                budget -= 1
            self._column.addLayout(_indented(flow, depth * self.INDENT))
        for node, kids in branches:
            if budget <= 0:
                return -1
            row = FlowLayout(margin=0, spacing=3)
            row.addWidget(self._card(node, branch=True))
            self._column.addLayout(_indented(row, depth * self.INDENT))
            budget = self._render(kids, depth + 1, budget - 1)
            if budget < 0:
                return -1
        return budget

    def _card(self, node: TreeNode, branch: bool = False) -> QToolButton:
        state = self._model.state(node)
        button = QToolButton()
        button.setText(self._model.label_for(node))
        button.setCheckable(True)
        button.setChecked(state == Qt.Checked)
        button.setToolTip(path_label(node.path))
        button.setCursor(Qt.PointingHandCursor)
        button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        # a part-filled branch has no checkbox to draw the third state in,
        # so it is drawn as the accent outline without the accent fill
        button.setProperty("slicerState",
                           "partial" if state == Qt.PartiallyChecked
                           else "on" if state == Qt.Checked else "off")
        button.setProperty("slicerBranch", branch)
        button.setStyleSheet(self._style)
        button.clicked.connect(lambda _c=False, p=node.path: self._pick(p))
        self._buttons[node.path] = button
        return button

    def _pick(self, path) -> None:
        self._model.toggle(path)
        self._in_change = True
        try:
            self.refresh_states()
            self.selection_changed.emit()
        finally:
            self._in_change = False

    def refresh_states(self) -> None:
        """Repaint the tiles from the model without rebuilding them — the
        same reason the tree refreshes in place: the button whose click we
        are inside must outlive the click."""
        for path, button in self._buttons.items():
            node = self._model.node(path)
            if node is None:
                continue
            state = self._model.state(node)
            button.setChecked(state == Qt.Checked)
            button.setText(self._model.label_for(node))
            button.setProperty("slicerState",
                               "partial" if state == Qt.PartiallyChecked
                               else "on" if state == Qt.Checked else "off")
            # a property-driven stylesheet only re-reads the property on a
            # re-polish; without this the tile keeps its old colours
            button.style().unpolish(button)
            button.style().polish(button)


def card_style(accent: str = "") -> str:
    """The tile stylesheet for one accent colour.

    A function rather than a constant because the accent is per-node: two
    slicers on the same dashboard can be different colours, and a shared
    constant would hand whichever was built last to both.
    """
    colour = accent_colour(accent)
    return f"""
QToolButton {{
    background: {theme.NODE_HEADER.name()};
    color: {theme.NODE_TEXT.name()};
    border: 1px solid {theme.NODE_BORDER.name()};
    border-radius: 4px; padding: 3px 8px; font-size: 8pt;
}}
QToolButton:hover {{ border-color: {colour.name()}; }}
QToolButton[slicerState="on"] {{
    background: {colour.name()};
    border-color: {colour.name()};
    color: {ink_on(colour)};
}}
QToolButton[slicerState="partial"] {{
    border: 1px solid {colour.name()};
    color: {theme.NODE_TEXT.name()};
}}
QToolButton[slicerBranch="true"] {{ font-weight: 600; }}
"""


class _DropdownView(QWidget):
    """The compact layout: one button saying what is picked, with the whole
    tree — search, All / None and all — inside its popup. For a dashboard
    where a slicer should cost a line rather than a panel."""

    selection_changed = Signal()

    def __init__(self, model: _Selection, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        self._button = QToolButton()
        self._button.setPopupMode(QToolButton.InstantPopup)
        self._button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._styled_for: Optional[str] = None
        self._apply_style()
        column.addWidget(self._button)
        column.addStretch(1)

        # the popup is built once and reused: rebuilding a QMenu on every
        # open would drop the search text the moment a tick reopened it
        self._popup = QMenu(self._button)
        holder = QWidget()
        inner = QVBoxLayout(holder)
        inner.setContentsMargins(4, 4, 4, 4)
        inner.setSpacing(3)
        self.tree = SlicerTreeWidget(model)
        self.toolbar = SlicerToolbar(model)
        self.toolbar.filter_changed.connect(self.tree.rebuild)
        self.toolbar.selection_changed.connect(self._refresh_after_toolbar)
        inner.addWidget(self.toolbar)
        inner.addWidget(self.tree, 1)
        holder.setMinimumSize(QSize(240, 260))
        action = QWidgetAction(self._popup)
        action.setDefaultWidget(holder)
        self._popup.addAction(action)
        self._button.setMenu(self._popup)
        self.tree.selection_changed.connect(self._on_changed)

    def _apply_style(self) -> None:
        """The button borrows the accent for its border and its open-state
        highlight — with the values hidden behind a popup it is the only
        part of a dropdown slicer that can carry the colour at all."""
        if self._model.accent == self._styled_for:
            return
        self._styled_for = self._model.accent
        colour = accent_colour(self._model.accent)
        border = (colour.name() if self._model.accent
                  else theme.NODE_BORDER.name())
        self._button.setStyleSheet(
            f"QToolButton {{ background: {theme.NODE_HEADER.name()};"
            f" color: {theme.NODE_TEXT.name()};"
            f" border: 1px solid {border};"
            f" border-radius: 3px; padding: 3px 6px; font-size: 9pt;"
            f" text-align: left; }}"
            f"QToolButton:hover {{ border-color: {colour.name()}; }}"
            f"QToolButton::menu-indicator {{ subcontrol-position: right"
            f" center; }}")

    def _refresh_after_toolbar(self) -> None:
        self.tree.rebuild()
        self._on_changed()

    def _on_changed(self) -> None:
        self._button.setText(self._model.button_label())
        self.toolbar.refresh_summary()
        self.selection_changed.emit()

    def rebuild(self) -> None:
        self._apply_style()
        self.tree.rebuild()
        # the popup's own toolbar answers to the same two toggles; hiding
        # both leaves the popup as a bare list of values
        self.toolbar.setVisible(self.toolbar.refresh_chrome())
        self.toolbar.refresh_summary()
        self._button.setText(self._model.button_label())


# ----------------------------------------------------------------- toolbar

class SlicerToolbar(QWidget):
    """Compact search box + Select All / None row driving a `_Selection` —
    a separate widget so every host and the dropdown's popup can lay it out
    above their view without the view itself changing shape."""

    #: below this widget width the All/None/count row drops under the search
    #: box instead of sitting beside it — so the card can be made narrow
    #: without the buttons clipping off the edge
    WRAP_BELOW = 190

    #: the *filter* changed: the view must rebuild, but nothing was ticked,
    #: so nothing downstream needs re-running
    filter_changed = Signal()
    #: All / None actually changed what is ticked — commit and re-run
    selection_changed = Signal()

    def __init__(self, model: _Selection, parent=None) -> None:
        super().__init__(parent)
        self._model = model
        # A grid rather than a box: the same four widgets are re-placed into
        # one row or two by _relayout as the card is resized.
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 2)
        self._grid.setHorizontalSpacing(2)
        self._grid.setVerticalSpacing(2)
        self._wrapped: bool | None = None

        search = QLineEdit()
        search.setPlaceholderText("Search…")
        search.setClearButtonEnabled(True)
        search.setMinimumWidth(0)
        search.textChanged.connect(self._on_search)
        self._search = search

        select_all = QToolButton()
        select_all.setText("All")
        select_all.setToolTip("Select every visible value")
        select_all.clicked.connect(self._on_all)
        self._select_all = select_all

        clear = QToolButton()
        clear.setText("None")
        clear.setToolTip("Clear the selection")
        clear.clicked.connect(self._on_none)
        self._clear = clear

        count = QLabel("")
        count.setToolTip("Values ticked, of the total on this column")
        self._count = count

        self._relayout(wrapped=False)
        self._styled_for: Optional[str] = None
        self._apply_style()

    def _apply_style(self) -> None:
        if self._model.accent == self._styled_for:
            return
        self._styled_for = self._model.accent
        colour = accent_colour(self._model.accent)
        self.setStyleSheet(
            f"QLineEdit {{ background: {theme.NODE_BODY.name()};"
            f" color: {theme.NODE_TEXT.name()};"
            f" border: 1px solid {theme.NODE_BORDER.name()};"
            f" border-radius: 3px; padding: 1px 3px; font-size: 8pt; }}"
            f"QLineEdit:focus {{ border-color: {colour.name()}; }}"
            f"QToolButton {{ font-size: 8pt; padding: 1px 4px; }}"
            f"QToolButton:hover {{ color: {colour.name()}; }}"
            f"QLabel {{ color: {theme.NODE_SUBTEXT.name()}; font-size: 8pt; }}")

    def refresh_chrome(self) -> bool:
        """Show or hide the search box and the All / None / count group, and
        say whether anything is left — the host hides the whole strip when
        nothing is, rather than leaving an empty two-pixel band above the
        values.

        Hiding the search also *clears* it. A filter with no box to see it
        in leaves the slicer showing a fraction of its values with nothing
        on screen explaining why, and no way back.
        """
        self._apply_style()
        model = self._model
        self._search.setVisible(model.show_search)
        if not model.show_search and model.filter_text:
            model.filter_text = ""
            self._search.blockSignals(True)
            self._search.clear()
            self._search.blockSignals(False)
        # Select All is meaningless once only one value can be picked
        self._select_all.setVisible(model.show_buttons
                                    and model.mode != "single")
        self._clear.setVisible(model.show_buttons)
        self._count.setVisible(model.show_buttons)
        # _relayout only re-stretches when the *wrap* changes, and hiding
        # the search is not that
        self._apply_stretch()
        return bool(model.show_search or model.show_buttons)

    def _relayout(self, wrapped: bool) -> None:
        """Place the four widgets in one row (wide) or two (narrow)."""
        if wrapped == self._wrapped:
            return
        self._wrapped = wrapped
        for w in (self._search, self._select_all, self._clear, self._count):
            self._grid.removeWidget(w)
        if wrapped:
            self._grid.addWidget(self._search, 0, 0, 1, 3)
            self._grid.addWidget(self._select_all, 1, 0)
            self._grid.addWidget(self._clear, 1, 1)
            self._grid.addWidget(self._count, 1, 2)
            self._tail_column = 2
        else:
            self._grid.addWidget(self._search, 0, 0)
            self._grid.addWidget(self._select_all, 0, 1)
            self._grid.addWidget(self._clear, 0, 2)
            self._grid.addWidget(self._count, 0, 3)
            self._tail_column = 3
        self._apply_stretch()

    def _apply_stretch(self) -> None:
        """Give the spare width to the search box, or — when it is hidden —
        to the column after the buttons, so All / None stay on the left with
        the values they act on rather than drifting to the right edge."""
        search = self._search.isVisibleTo(self)
        self._grid.setColumnStretch(0, 1 if search else 0)
        self._grid.setColumnStretch(self._tail_column, 0 if search else 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout(wrapped=event.size().width() < self.WRAP_BELOW)

    def _on_search(self, text: str) -> None:
        """Typing narrows the list and nothing else. It is emphatically not
        a selection change: routing it through the commit path would ask the
        engine to re-run everything downstream once per keystroke, for a
        filter the flow cannot even see."""
        self._model.filter_text = text.strip()
        self.filter_changed.emit()

    def _on_all(self) -> None:
        self._emit(self._model.select_all())

    def _on_none(self) -> None:
        self._emit(self._model.clear_all())

    def _emit(self, changed: bool) -> None:
        (self.selection_changed if changed else self.filter_changed).emit()

    def refresh_summary(self) -> None:
        """Re-read the "N/M" count off the model — hosts call this after
        repopulating it."""
        self._count.setText(self._model.summary())


# ------------------------------------------------------------------- panel

class SlicerPanel(QWidget):
    """A Slicer's whole card body: the run-me placeholder, the toolbar and
    whichever layout the node asks for. The only thing a host talks to."""

    #: the new "selected" param value: JSON, or "" for nothing ticked
    selection_committed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.model = _Selection()
        self._layout_name = "list"
        self._has_options = False

        # the card's own ground: the tree and the cards paint their own, but
        # a dropdown is one button with empty card below it, and an unpainted
        # widget there borrows the OS palette and reads as a light hole
        self.setAutoFillBackground(True)
        self.setStyleSheet(
            f"SlicerPanel {{ background: {theme.NODE_BODY.name()}; }}")

        column = QVBoxLayout(self)
        column.setContentsMargins(2, 2, 2, 2)
        column.setSpacing(0)
        self._column = column

        self._placeholder = QLabel("Run the graph to load slicer values.")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._placeholder.setStyleSheet("color: #6b7280;")
        column.addWidget(self._placeholder, 1)

        self.toolbar = SlicerToolbar(self.model)
        self.toolbar.filter_changed.connect(self._after_filter)
        self.toolbar.selection_changed.connect(self._after_toolbar)
        self.toolbar.hide()
        column.addWidget(self.toolbar)

        self._views: dict[str, QWidget] = {}
        self.view: QWidget | None = None
        self._install_view("list")

    # ---- views

    def _install_view(self, name: str) -> QWidget:
        view = self._views.get(name)
        if view is None:
            factory = {"list": SlicerTreeWidget, "cards": _CardsView,
                       "dropdown": _DropdownView}[name]
            view = factory(self.model)
            view.selection_changed.connect(self._commit)
            view.hide()
            self._column.addWidget(view, 1)
            self._views[name] = view
        return view

    def set_layout_name(self, name: str) -> None:
        """"list" (checkboxes, a tree on several columns), "cards" (tiles)
        or "dropdown". Purely how the same selection is drawn."""
        name = name if name in LAYOUTS else "list"
        if name == self._layout_name and self.view is not None:
            return
        self._layout_name = name
        if self.view is not None:
            self.view.hide()
        self.view = self._install_view(name)
        self._apply_chrome()
        if self._has_options:
            self.view.rebuild()
            self.view.show()

    # ---- the host's four calls

    def set_options(self, options: Optional[SlicerOptions],
                    params: dict) -> None:
        """Rebuild from the column's values (from the upstream cache),
        ticking what the "selected" param holds — called once the engine
        reports this node done. None reverts to the run-me placeholder."""
        if options is None:
            self._has_options = False
            if self.view is not None:
                self.view.hide()
            self.toolbar.hide()
            self._placeholder.show()
            return
        self._has_options = True
        self._read_params(params)
        self.model.set_options(options)
        self.model.set_paths(selected_paths(params.get("selected", "")))
        self._placeholder.hide()
        self.set_layout_name(str(params.get("layout", "list") or "list"))
        self._apply_chrome()
        self.view.rebuild()
        self.view.show()
        self.toolbar.refresh_summary()

    def sync_params(self, params: dict) -> None:
        """Re-apply mode, layout and the ticked set from the node's params
        without re-reading the data — for when they change elsewhere
        (properties panel, undo)."""
        if not self._has_options:
            return
        entering_single = (str(params.get("mode", "multi") or "multi")
                           == "single" and self.model.mode != "single")
        self._read_params(params)
        self.model.set_paths(selected_paths(params.get("selected", "")))
        self.set_layout_name(str(params.get("layout", "list") or "list"))
        self._apply_chrome()
        # flipping to single with several ticked trims to the first, so the
        # card and the param it commits never disagree about how many are on
        if entering_single and self.model.trim_to_single():
            self.view.rebuild()
            self.toolbar.refresh_summary()
            self._commit()
            return
        self.view.rebuild()
        self.toolbar.refresh_summary()

    def _read_params(self, params: dict) -> None:
        mode = str(params.get("mode", "multi") or "multi")
        self.model.mode = mode if mode in MODES else "multi"
        self.model.show_counts = bool(params.get("show_counts", False))
        # default True: a slicer saved before these existed had both,
        # and must not lose them on load
        self.model.show_search = bool(params.get("show_search", True))
        self.model.show_buttons = bool(params.get("show_buttons", True))
        self.model.accent = str(params.get("accent", "") or "")

    def _apply_chrome(self) -> None:
        """Show the toolbar only when it has something left on it, and
        only where it belongs — the dropdown carries its own copy inside
        the popup, and a second one above a single button would be most
        of the card."""
        wanted = self.toolbar.refresh_chrome()
        self.toolbar.setVisible(self._has_options and wanted
                                and self._layout_name != "dropdown")

    # ---- reporting

    def has_options(self) -> bool:
        return self._has_options

    def selected_paths(self) -> list[tuple[str, ...]]:
        return list(self.model.paths)

    def selected_values(self) -> list[str]:
        """The ticked rows as flat strings — the deepest value of each."""
        from flograph.core.slicer import leaf_values
        return leaf_values(self.model.paths)

    def selection_summary(self) -> str:
        return self.model.summary()

    def _after_filter(self) -> None:
        """A search narrowed the list: redraw it, and stop there."""
        self.view.rebuild()

    def _after_toolbar(self) -> None:
        self.view.rebuild()
        self.toolbar.refresh_summary()
        self._commit()

    def _commit(self) -> None:
        self.toolbar.refresh_summary()
        self.selection_committed.emit(self.model.committed_value())


# ------------------------------------------------------------------ helpers

def _flatten(entries) -> list:
    """A nested (node, children) tree as a flat list, parents first."""
    out = []
    for node, children in entries:
        out.append((node, children))
        out.extend(_flatten(children))
    return out


def _indented(layout, left: int):
    """Wrap a layout in one that pads it from the left, for a hierarchy's
    levels. Qt has no per-layout margin on an already-built layout."""
    holder = QVBoxLayout()
    holder.setContentsMargins(left, 0, 0, 0)
    holder.addLayout(layout)
    return holder


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        child = item.layout()
        if child is not None:
            _clear_layout(child)
