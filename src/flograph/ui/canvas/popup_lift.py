"""Popups belonging to a widget drawn on a card.

A card — a canvas node's body, a dashboard tile — is a `QGraphicsProxyWidget`
holding a real widget. That widget has no window of its own, and Qt deals
with its popups by **embedding them back into the scene**: a popup child of
an embedded widget becomes a second proxy, parented to the card's. That
design keeps a popup following its card, and costs two things.

**It stacks the popup with the card.** An embedded popup can only be as high
as the card it belongs to, so any card in front is drawn over the open list
(AA7). Two widgets already worked around this with a private copy each, and
both snapshotted the card's z and put it back afterwards — so a restack
while the popup was open (a tile maximized, a page re-laid-out, anything
calling `apply_stacking`) overwrote the lift and then had a stale value
written back over it. The lift is a *flag* here instead: `apply_stacking`
asks for it, so it survives a restack, and dropping it re-derives the
resting z rather than restoring a remembered one. That part works.

**It leaves the popup subject to the card.** An embedded list is clipped by
the card that owns it and sized and flipped against coordinates that are the
offscreen container's, not the screen's — so a combo's list came up cut off
at the card's bottom edge, and then, when it was given the height its rows
needed, flipped to open *upwards* through the card's own header. Each of
those has an obvious local fix and each local fix moved the fault somewhere
else, because they are all the same fault: the list is inside the scene, and
a dropdown does not belong inside the scene.

So a combo on a card does not use Qt's popup at all. `CardComboBox` opens
`CardPopupList` — a window of its own, parented to the **view**, which is a
real window — positioned where the combo actually appears on screen. Nothing
embeds it, so nothing clips it, nothing stacks under it and nothing has to be
lifted for it. The lift stays for the popups that are still Qt's: a slicer's
menu and the Report card's completer.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (QElapsedTimer, QEvent, QPoint, QRect, QRectF,
                            QSize, Qt, Signal)
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox,
                               QFrame, QGraphicsItem, QListView, QStyle,
                               QWidget)

from .. import theme
from .stacking import POPUP_HOST_Z

#: Set on a graphics item while one of its widget's popups is open. An
#: attribute rather than a subclass hook so a tile and a node — which share
#: no base class — can both answer for it.
_LIFT_FLAG = "_popup_lift_count"


def alive(obj) -> bool:
    """Whether Qt still has the C++ side of a Python object.

    A popup belongs to the window it was parented to, and that window can
    be destroyed with the popup still open — a project closed, a page
    thrown away, a test harness torn down. The Python reference outlives
    it, and touching it raises inside whatever event Qt was delivering.
    """
    import shiboken6
    return obj is not None and shiboken6.isValid(obj)


def card_proxy(widget: QWidget):
    """The proxy holding the card `widget` is drawn in, or None."""
    window = widget.window() if widget is not None else None
    return window.graphicsProxyWidget() if window is not None else None


def host_item(widget: QWidget) -> Optional[QGraphicsItem]:
    """The card or tile this widget is drawn in, or None when it is not on
    a canvas at all (a dock, a dialog, a test harness)."""
    proxy = card_proxy(widget)
    return proxy.topLevelItem() if proxy is not None else None


def is_lifted(item) -> bool:
    return bool(getattr(item, _LIFT_FLAG, 0))


def stacked_z(item, resting: float) -> float:
    """The z value `item` should take: its place in the stacking order, or
    the popup band while one of its popups is open.

    `max`, not the band outright, because a maximized tile already sits
    higher than the popup band and must not be brought *down* by opening a
    dropdown inside it.
    """
    return max(resting, POPUP_HOST_Z) if is_lifted(item) else resting


#: Where a host with no stacking order of its own was sitting before it was
#: lifted. Only that kind of host needs it — see `_restack`.
_RESTING_Z = "_popup_lift_resting_z"


def _restack(item) -> None:
    """Put the item at the z its stacking order gives it, lift included.

    A node or a tile derives that z from the project (`apply_stacking`), so
    the lift is re-applied on top of whatever the item's place is *now* —
    which is the point of holding it as a flag rather than as a saved
    number. Anything else — a plain item in a harness, or a host some later
    surface introduces — has no order to derive, so its z before the lift
    is remembered and handed back. There is nothing for that to go stale
    against, because nothing else is deciding where it sits.
    """
    apply_stacking = getattr(item, "apply_stacking", None)
    if callable(apply_stacking):
        apply_stacking()
        return
    if is_lifted(item):
        if getattr(item, _RESTING_Z, None) is None:
            setattr(item, _RESTING_Z, item.zValue())
        item.setZValue(max(item.zValue(), POPUP_HOST_Z))
    elif getattr(item, _RESTING_Z, None) is not None:
        item.setZValue(getattr(item, _RESTING_Z))
        setattr(item, _RESTING_Z, None)


def lift(item) -> None:
    """Hold `item` above its neighbours until the matching `drop`.

    Counted, not a bool: one card can hold two widgets with popups, and a
    combo box opened over an already-open completer must not put the card
    back down when only it has closed.
    """
    if item is None:
        return
    setattr(item, _LIFT_FLAG, getattr(item, _LIFT_FLAG, 0) + 1)
    _restack(item)


def drop(item) -> None:
    if item is None:
        return
    import shiboken6
    if not shiboken6.isValid(item):
        return      # the card went away while its popup was open
    remaining = max(0, getattr(item, _LIFT_FLAG, 0) - 1)
    setattr(item, _LIFT_FLAG, remaining)
    _restack(item)


# ------------------------------------------------------- where it looks


def where_it_looks(widget: QWidget) -> Optional[tuple]:
    """`(view, rect)` — the view drawing this widget's card, and where the
    widget appears **on screen**, or None when it is not on a card.

    The widget's own coordinates say nothing: an embedded widget lives in an
    offscreen container and `mapToGlobal` reports that container's idea of
    where it is. The view is a real window and knows where the card it draws
    has ended up, so the walk is card → scene → view → screen — the same one
    `data_table.tooltip_host` makes for tooltips (AA3). The rect comes back
    at the zoom the card is drawn at, which is what a list has to line up
    with.
    """
    proxy = card_proxy(widget)
    scene = proxy.scene() if proxy is not None else None
    if scene is None:
        return None
    window = widget.window()
    on_card = QRectF(QRect(widget.mapTo(window, QPoint(0, 0)), widget.size()))
    in_scene = proxy.mapToScene(on_card)
    best = None
    for view in scene.views():
        viewport = view.viewport()
        in_view = view.mapFromScene(in_scene).boundingRect()
        seen = in_view.intersected(viewport.rect())
        if seen.isEmpty():
            continue        # another view of the same scene, or the minimap
        area = seen.width() * seen.height()
        if best is None or area > best[0]:
            best = (area, view, in_view)
    if best is None:
        return None
    _, view, in_view = best
    on_screen = QRect(view.viewport().mapToGlobal(in_view.topLeft()),
                      in_view.size())
    return view, on_screen


def popup_geometry(anchor: QRect, size: QSize, screen: QRect) -> QRect:
    """Where a popup of `size` goes when it hangs off `anchor` on `screen`.

    Below the anchor by preference, above it when there is no room below,
    and never off the side. Plain arithmetic and no Qt state, so the rule a
    dropdown follows can be read and tested without a screen at all — which
    matters here, because the offscreen platform the suite runs on is
    exactly where the old code's measurements agreed with themselves and
    disagreed with the user's machine.
    """
    width = min(size.width(), screen.width())
    height = min(size.height(), screen.height())
    x = max(screen.left(), min(anchor.left(), screen.right() - width + 1))
    below, above = anchor.bottom() + 1, anchor.top() - height
    if below + height - 1 <= screen.bottom():
        y = below
    elif above >= screen.top():
        y = above
    else:
        # taller than either side: keep it on screen and let it scroll
        y = max(screen.top(), screen.bottom() - height + 1)
    return QRect(x, y, width, height)


def _screen_for(point: QPoint) -> QRect:
    screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
    return screen.availableGeometry() if screen is not None else QRect()


def _popup_stylesheet() -> str:
    """A card's chrome, not the desktop's: the list belongs to a control
    drawn on a dark card even though it is a window of its own now."""
    return (f"QListView {{ background: {theme.NODE_BODY.name()};"
            f" color: {theme.NODE_TEXT.name()};"
            f" border: 1px solid {theme.NODE_BORDER.name()};"
            f" outline: none; font-size: 9pt; }}"
            f"QListView::item {{ padding: 3px 6px;"
            f" border: none; }}"
            f"QListView::item:hover {{"
            f" background: {theme.NODE_HEADER.name()}; }}"
            f"QListView::item:selected {{"
            f" background: {theme.SELECTION_OUTLINE.name()};"
            f" color: {theme.NODE_BORDER.name()}; }}")


class DismissedByAClickElsewhere:
    """Close when a click lands outside, and on Escape.

    A `Qt.Popup` window is supposed to get both from the platform: it takes
    a grab, so a press anywhere else comes to it and Qt closes it. That is
    how every menu in the app behaves, and it is how the slicer's list
    behaves — but a **combo's** list, opened from inside the press that
    asked for it, came up without one on Wayland, so a click on the canvas
    went to the canvas and the list stayed up with no way out but picking a
    value. Dan: "when i click anywhere off the menu it doesnt remove the
    menu, so it forces me to click an item".

    Rather than work out which popups the platform grabs and which it does
    not, the dismissal is said outright: while the popup is up it watches
    the application for a press that is not inside it. Where the grab does
    work this sees the same press and agrees with it, so there is one
    behaviour rather than two. Meant to be mixed in *before* the widget
    class, so these overrides are found first.
    """

    _watching = False

    def _watch(self, on: bool) -> None:
        app = QApplication.instance()
        if app is None or on == self._watching:
            return
        if on:
            app.installEventFilter(self)
        else:
            app.removeEventFilter(self)
        self._watching = on

    def eventFilter(self, watched, event) -> bool:
        if (event.type() == QEvent.MouseButtonPress and self.isVisible()
                and not self.geometry().contains(
                    event.globalPosition().toPoint())):
            self.hide()
        return False        # never eaten: the click still does its own job

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._watch(True)

    def hideEvent(self, event) -> None:
        self._watch(False)
        super().hideEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)


def anchor_for(widget: QWidget) -> Optional[tuple]:
    """`(window, rect)` — the real window a popup for `widget` belongs to,
    and the rect on screen it should hang from.

    On a card that is the view and where the view draws the widget; off one
    it is the widget's own window and its own global position, which is what
    Qt would have used anyway. Having both go down the same path is what
    lets a control keep one popup rather than one per surface it might be
    shown on.
    """
    if widget is None:
        return None
    seen = where_it_looks(widget)
    if seen is not None:
        view, rect = seen
        return view.window(), rect
    window = widget.window()
    if window is None:
        return None
    return window, QRect(widget.mapToGlobal(QPoint(0, 0)), widget.size())


class CardPopup(DismissedByAClickElsewhere, QFrame):
    """A popup **window** for a widget drawn on a card: hold whatever the
    popup shows, and `open_against` the widget it belongs to.

    Qt would otherwise embed the popup into the canvas as part of the card —
    see this module's heading. Two things follow from that which are easy to
    miss until somebody uses the app: an embedded popup is clipped by the
    card, so its lower rows are half-drawn under the card's own frame; and
    nothing outside the scene knows it is open, so **clicking elsewhere does
    not close it** and there is no way out but picking something. A window
    gets both for nothing, from the same popup handling every menu in the
    app uses.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("card_popup")
        self.setWindowFlags(Qt.Popup)
        self.setFrameShape(QFrame.StyledPanel)
        # by object name: a bare QFrame rule would cascade into the tree and
        # the scroll areas inside, which are QFrames themselves
        self.setStyleSheet(
            f"QFrame#card_popup {{ background: {theme.NODE_BODY.name()};"
            f" border: 1px solid {theme.NODE_BORDER.name()}; }}")

    def open_against(self, widget: QWidget, size: Optional[QSize] = None,
                     ) -> bool:
        """Show this popup under `widget`, wherever that widget looks like
        it is. Returns whether there was anywhere to show it."""
        found = anchor_for(widget)
        if found is None or not alive(self):
            return False
        window, anchor = found
        if self.parent() is not window:
            self.setParent(window, Qt.Popup)
        wanted = size if size is not None else self.sizeHint()
        wanted = QSize(max(wanted.width(), anchor.width(),
                           self.minimumWidth()),
                       max(wanted.height(), self.minimumHeight()))
        self.setGeometry(popup_geometry(anchor, wanted,
                                        _screen_for(anchor.center())))
        self.show()
        return True


class CardPopupList(DismissedByAClickElsewhere, QListView):
    """The list a `CardComboBox` opens: a window of its own.

    Parented to the view rather than to the combo, because a popup child of
    a proxied widget is what Qt embeds back into the scene. This one is a
    real popup window — it is drawn over everything, it is clipped by the
    screen rather than by the card, and it closes on a click outside or on
    Escape the way every other popup in the app does.
    """

    picked = Signal(int)

    #: A release this soon after opening is the tail of the click that
    #: opened the list, not a choice. Qt's own combo container does the
    #: same, or a plain click on the box would pick whatever the list put
    #: under the pointer.
    CLICK_THROUGH_MS = 250

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.Popup)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.setStyleSheet(_popup_stylesheet())
        self._opened = QElapsedTimer()
        self._pressed_inside = False

    # ---- size and place

    def wanted_size(self, least_wide: int, rows_at_once: int) -> QSize:
        """The size the list needs for its rows, said outright.

        Qt sizes an embedded popup against the space it believes is
        available, and for a widget on a card that space is worked out from
        the card. Ours is a window on a screen and can simply ask its own
        rows how tall they are.
        """
        rows = self.model().rowCount(self.rootIndex()) if self.model() else 0
        frame = 2 * self.frameWidth()
        row = max(1, self.sizeHintForRow(0)) if rows else 1
        shown = min(rows, max(1, rows_at_once)) if rows else 0
        width = max(least_wide, self.sizeHintForColumn(0) + frame if rows
                    else least_wide)
        if shown < rows:
            width += self.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        return QSize(width, shown * row + frame)

    def open_against(self, anchor: QRect, window: QWidget,
                     rows_at_once: int) -> None:
        """Show the list under `anchor`, as a popup of `window`."""
        if self.parent() is not window:
            # re-parented per open: the card may be shown in a different
            # view than it was last time (a frame opened in its own tab, a
            # page moved), and a popup's window has to be the one on screen
            self.setParent(window, Qt.Popup)
            self.setStyleSheet(_popup_stylesheet())
        size = self.wanted_size(anchor.width(), rows_at_once)
        self.setGeometry(popup_geometry(anchor, size,
                                        _screen_for(anchor.center())))
        self.show()
        self.setFocus(Qt.PopupFocusReason)
        self.scrollTo(self.currentIndex())
        self._pressed_inside = False
        self._opened.start()

    # ---- picking

    def _commit(self, row: int) -> None:
        self.hide()
        self.picked.emit(row)

    def mousePressEvent(self, event) -> None:
        self._pressed_inside = True
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if (not self._pressed_inside
                and self._opened.isValid()
                and self._opened.elapsed() < self.CLICK_THROUGH_MS):
            return          # the release that opened the list
        index = self.indexAt(event.position().toPoint())
        if index.isValid():
            self._commit(index.row())

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            index = self.currentIndex()
            if index.isValid():
                self._commit(index.row())
                return
        super().keyPressEvent(event)


class CardComboBox(QComboBox):
    """A combo box that behaves when it is drawn on a card.

    Ordinary everywhere else: off a canvas it is Qt's own popup, which is
    right there and has a real screen to measure against. On a card it opens
    `CardPopupList` instead — see this module's heading for why that is a
    different list rather than a corrected one.
    """

    #: A class attribute, not something `__init__` sets: Qt can call
    #: `hidePopup` on a combo before Python has finished with it — during
    #: teardown, and once on the way through the base constructor — and an
    #: override that trips over a missing attribute there is an exception
    #: raised inside the event loop.
    _card_list: Optional["CardPopupList"] = None

    def card_list(self) -> Optional["CardPopupList"]:
        """The list this combo opens on a card, once it has opened one."""
        return self._card_list

    def showPopup(self) -> None:
        where = where_it_looks(self)
        if where is None:
            super().showPopup()     # a dock, a dialog, a test harness
            return
        view, anchor = where
        if not alive(self._card_list):
            # None the first time, and a dead one when the window it was
            # parented to has since been destroyed
            self._card_list = CardPopupList()
            self._card_list.picked.connect(self._pick)
        popup = self._card_list
        popup.setModel(self.model())
        popup.setModelColumn(self.modelColumn())
        popup.setRootIndex(self.rootModelIndex())
        current = self.model().index(max(0, self.currentIndex()),
                                     self.modelColumn(),
                                     self.rootModelIndex())
        if current.isValid():
            popup.setCurrentIndex(current)
        popup.open_against(anchor, view.window(), self.maxVisibleItems())

    def hidePopup(self) -> None:
        if alive(self._card_list):
            self._card_list.hide()
        super().hidePopup()

    def _pick(self, row: int) -> None:
        self.setCurrentIndex(row)
        # `activated` is the one that means a person chose: a control commits
        # on it so that a re-run rewriting the options does not look like a
        # choice (ChoiceControl._build)
        self.activated.emit(row)
