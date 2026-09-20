"""0.1.15 #1 and #2: a dropdown belonging to a widget drawn on a card.

Dan: "there are times when a dropdown doesn't display in the correct place?
it seems anchored to an area that isn't where you expect" and "drop down
menus also seem to be layered strange on the dashboard pages, the element
layers over the top of the dropdown".

Both come of a card being a `QGraphicsProxyWidget`: Qt embeds the popup back
into the scene as a child proxy of that card. It stacks with the card, so a
card in front covers it; it is clipped by the card; and it is sized and
flipped against coordinates belonging to an offscreen container rather than
to a screen. The stacking half is answered by lifting the card. The rest is
answered by not embedding the list at all — a combo on a card opens a window
of its own, parented to the view. See `ui/canvas/popup_lift`.
"""
import pathlib
import pytest
from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import (QGraphicsProxyWidget, QGraphicsRectItem,
                               QGraphicsScene, QGraphicsView, QWidget,
                               QVBoxLayout)

from flograph.core import Graph, NodeRegistry
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.canvas import popup_lift
from flograph.ui.canvas.stacking import POPUP_HOST_Z

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def _carded_combo(items=("north", "south", "east"), z=3.0):
    """A CardComboBox proxied into a card, the way a control node is."""
    scene = QGraphicsScene()
    card = QGraphicsRectItem(0, 0, 240, 120)
    card.setZValue(z)
    scene.addItem(card)
    host = QWidget()
    layout = QVBoxLayout(host)
    combo = popup_lift.CardComboBox()
    combo.addItems(list(items))
    layout.addWidget(combo)
    proxy = QGraphicsProxyWidget(card)
    proxy.setWidget(host)
    return scene, card, combo


def _in_a_view(qtbot, items=("north", "south", "east"), z=3.0):
    """The same card, in a view — which is what makes it a card that is
    actually being *drawn*, and so the only shape the popup work applies
    to."""
    scene, card, combo = _carded_combo(items, z)
    view = QGraphicsView(scene)
    view.resize(600, 400)
    qtbot.addWidget(view)
    view.show()
    view._scene = scene      # the view does not own it; nothing else holds it
    card.setPos(120.0, 80.0)
    return view, card, combo


class TestTheListIsAWindowOfItsOwn:
    """The rewrite. Every previous attempt corrected the embedded popup —
    its height, its clip, its parent — and each correction moved the fault
    somewhere else: the list came up cut off at the card's bottom edge, then
    (given the height its rows needed) flipped to open upwards through the
    card's own header, then, when its proxy was moved out of the clipping
    widget, opened somewhere else entirely on the second use because Qt
    reuses the popup. None of that can happen to a window.
    """

    def test_on_a_card_it_is_not_embedded_in_the_scene(self, qtbot):
        _view, _card, combo = _in_a_view(qtbot)
        combo.showPopup()
        popup = combo.card_list()
        assert popup is not None, "a card should get the card list"
        assert popup.isVisible()
        assert popup.graphicsProxyWidget() is None, "embedded after all"
        combo.hidePopup()

    def test_it_is_a_popup_of_the_view_not_of_the_combo(self, qtbot):
        """The parent is what decides it: Qt embeds a popup whose parent
        chain reaches a proxied widget, and leaves alone one whose parent is
        a real window."""
        view, _card, combo = _in_a_view(qtbot)
        combo.showPopup()
        assert combo.card_list().parent() is view.window()
        combo.hidePopup()

    def test_off_a_card_it_is_an_ordinary_combo(self, qtbot):
        """Everywhere but a canvas — the docks, the dialogs — Qt has a real
        screen to measure against and knows better than we do."""
        combo = popup_lift.CardComboBox()
        combo.addItems(["a", "b"])
        qtbot.addWidget(combo)
        combo.showPopup()
        assert combo.card_list() is None
        combo.hidePopup()

    def test_opening_it_again_lands_in_the_same_place(self, qtbot):
        """The bug that followed the reparenting attempt: the first list
        appeared correctly and every one after it came up somewhere else."""
        _view, _card, combo = _in_a_view(qtbot)
        combo.showPopup()
        first = combo.card_list().geometry()
        combo.card_list()._commit(1)            # pick a value, as a click does
        combo.showPopup()
        assert combo.card_list().geometry() == first
        combo.hidePopup()

    def test_the_card_is_not_lifted_for_it(self, qtbot):
        """Nothing in the scene has to move out of a window's way — which
        is the point. The lift stays for the popups that are still Qt's."""
        _view, card, combo = _in_a_view(qtbot)
        combo.showPopup()
        assert not popup_lift.is_lifted(card)
        assert card.zValue() == 3.0
        combo.hidePopup()


class TestItClosesTheWayEveryOtherPopupDoes:
    """Dan: "when i click anywhere else after opening a drop down it doesnt
    collapse the selection window. so im stuck untill i click a value on the
    list."

    That is the other half of being embedded, and the half that is easiest
    to miss from the outside: a list inside the canvas is not on Qt's popup
    stack, so nothing tells it a click landed elsewhere. Being a popup
    *window* is what puts it back on that stack — one flag, and dismissal,
    Escape and the keyboard all come with it.
    """

    def _press_somewhere_else(self, popup):
        """A press at a point the popup does not cover, delivered the way
        the application sees one."""
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        away = QPointF(popup.geometry().right() + 200.0,
                       popup.geometry().bottom() + 200.0)
        QApplication.instance().sendEvent(popup, QMouseEvent(
            QEvent.MouseButtonPress, QPointF(0.0, 0.0), away,
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))

    def test_the_combo_s_list_is_a_popup_window(self, qtbot):
        from PySide6.QtCore import Qt
        _view, _card, combo = _in_a_view(qtbot)
        combo.showPopup()
        assert combo.card_list().windowType() == Qt.Popup
        combo.hidePopup()

    def test_a_press_elsewhere_shuts_the_combo_s_list(self, qtbot):
        _view, _card, combo = _in_a_view(qtbot)
        combo.setCurrentIndex(0)
        combo.showPopup()
        popup = combo.card_list()
        self._press_somewhere_else(popup)
        assert not popup.isVisible()
        assert combo.currentIndex() == 0, "it picked something on the way out"

    def test_a_press_inside_it_is_left_alone(self, qtbot):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        _view, _card, combo = _in_a_view(qtbot)
        combo.showPopup()
        popup = combo.card_list()
        inside = QPointF(popup.geometry().center())
        QApplication.instance().sendEvent(popup, QMouseEvent(
            QEvent.MouseButtonPress, QPointF(2.0, 2.0), inside,
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        assert popup.isVisible()
        combo.hidePopup()

    def test_it_stops_watching_once_it_is_shut(self, qtbot):
        """The filter is on the whole application while the list is up, so
        it has to come off again — every open would otherwise leave one
        behind on every press in the app for the rest of the session."""
        _view, _card, combo = _in_a_view(qtbot)
        combo.showPopup()
        popup = combo.card_list()
        assert popup._watching
        combo.hidePopup()
        assert not popup._watching

    def test_the_slicer_s_list_is_a_popup_window(self, qtbot):
        from PySide6.QtCore import Qt
        from flograph.core.slicer import SlicerOptions
        from flograph.ui.slicer_list import SlicerPanel
        panel = SlicerPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.set_options(SlicerOptions(["region"], [("north",)]),
                          {"selected": "", "mode": "multi",
                           "layout": "dropdown", "show_counts": False})
        panel.view.open_popup()
        assert panel.view._popup.windowType() == Qt.Popup
        self._press_somewhere_else(panel.view._popup)
        assert not panel.view._popup.isVisible()

    def test_escape_shuts_the_slicer_s_list(self, qtbot):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent
        from flograph.core.slicer import SlicerOptions
        from flograph.ui.slicer_list import SlicerPanel
        panel = SlicerPanel()
        qtbot.addWidget(panel)
        panel.show()
        panel.set_options(SlicerOptions(["region"], [("north",)]),
                          {"selected": "", "mode": "multi",
                           "layout": "dropdown", "show_counts": False})
        panel.view.open_popup()
        panel.view._popup.keyPressEvent(
            QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        assert not panel.view._popup.isVisible()


class TestTheWindowGoingAwayUnderneathIt:
    """A popup belongs to the window it was parented to, and that window can
    be destroyed with the list still open — a project closed, a page thrown
    away. The Python reference outlives the C++ object, and touching it
    raises inside whatever event Qt was delivering, which is an exception
    with no stack anybody can act on."""

    def test_a_dead_list_is_replaced_rather_than_touched(self, qtbot):
        import shiboken6
        view, _card, combo = _in_a_view(qtbot)
        combo.showPopup()
        first = combo.card_list()
        shiboken6.delete(view)                  # takes the popup with it
        assert not popup_lift.alive(first)
        combo.hidePopup()                       # must not raise
        assert combo.card_list() is first       # nothing to replace it with

    def test_alive_is_honest_about_none(self):
        assert popup_lift.alive(None) is False


class TestWhereTheComboActuallyIs:
    """#1. A proxied widget's own coordinates belong to an offscreen
    container, so the list has to be placed by asking the view that draws
    the card — the same walk `data_table.tooltip_host` makes for tooltips.
    """

    def test_it_is_where_the_view_draws_the_card(self, qtbot):
        view, _card, combo = _in_a_view(qtbot)
        found = popup_lift.where_it_looks(combo)
        assert found is not None
        seen_in, rect = found
        assert seen_in is view
        proxy = combo.window().graphicsProxyWidget()
        in_scene = proxy.mapToScene(
            combo.mapTo(combo.window(), QPoint(0, 0)))
        expected = view.viewport().mapToGlobal(view.mapFromScene(in_scene))
        assert rect.topLeft() == expected

    def test_a_zoomed_out_card_reports_a_smaller_combo(self, qtbot):
        """The rect comes back at the zoom the card is drawn at, because a
        list that lines up with the box at 100% does not at 50%."""
        view, _card, combo = _in_a_view(qtbot)
        full = popup_lift.where_it_looks(combo)[1]
        view.scale(0.5, 0.5)
        half = popup_lift.where_it_looks(combo)[1]
        assert half.width() < full.width()

    def test_off_a_canvas_there_is_nothing_to_ask(self, qtbot):
        combo = popup_lift.CardComboBox()
        qtbot.addWidget(combo)
        assert popup_lift.where_it_looks(combo) is None

    def test_a_card_in_no_view_has_nowhere_to_look(self):
        _scene, _card, combo = _carded_combo()
        assert popup_lift.where_it_looks(combo) is None


class TestWhereAListGoes:
    """Plain arithmetic, on purpose: this is the rule a dropdown follows,
    and it can be read and tested without a screen — which matters, because
    the offscreen platform the suite runs on is exactly where the old code's
    measurements agreed with themselves and disagreed with Dan's machine.
    """

    SCREEN = QRect(0, 0, 1000, 800)

    def test_it_hangs_under_the_box(self):
        at = popup_lift.popup_geometry(QRect(100, 200, 160, 24),
                                       QSize(160, 90), self.SCREEN)
        assert at == QRect(100, 224, 160, 90)

    def test_no_room_below_flips_it_above(self):
        """What a short card near the bottom of the screen gets, instead of
        a list cut off at the edge."""
        at = popup_lift.popup_geometry(QRect(100, 700, 160, 24),
                                       QSize(160, 200), self.SCREEN)
        assert at == QRect(100, 500, 160, 200)
        assert at.bottom() < 700, "it must not cover the box it came from"

    def test_it_never_runs_off_the_side(self):
        at = popup_lift.popup_geometry(QRect(950, 100, 40, 24),
                                       QSize(300, 90), self.SCREEN)
        assert at.right() <= self.SCREEN.right()
        assert at.left() >= self.SCREEN.left()

    def test_taller_than_the_screen_is_kept_on_it(self):
        at = popup_lift.popup_geometry(QRect(100, 400, 160, 24),
                                       QSize(160, 2000), self.SCREEN)
        assert self.SCREEN.contains(at)

    def test_it_lines_up_with_the_box(self):
        at = popup_lift.popup_geometry(QRect(300, 100, 160, 24),
                                       QSize(160, 90), self.SCREEN)
        assert at.left() == 300


class TestTheListIsTallEnoughForItsRows:
    """What went wrong first: four values in the list and you could read
    three, the fourth half-drawn under the card's frame."""

    def _opened(self, qtbot, items):
        view, _card, combo = _in_a_view(qtbot, items)
        combo.showPopup()
        combo._view_kept_alive = view       # or the card goes with it
        return combo, combo.card_list()

    def test_every_value_fits(self, qtbot):
        combo, popup = self._opened(qtbot, ["north", "south", "east", "west"])
        row = popup.sizeHintForRow(0)
        assert popup.height() >= 4 * row
        combo.hidePopup()

    def test_a_long_list_stops_at_its_limit(self, qtbot):
        """`maxVisibleItems` is respected, so a long list scrolls at the
        length it is meant to rather than covering the screen."""
        combo, popup = self._opened(qtbot, [f"v{n}" for n in range(60)])
        combo.setMaxVisibleItems(10)
        combo.hidePopup()
        combo.showPopup()
        popup = combo.card_list()
        row = popup.sizeHintForRow(0)
        assert popup.height() <= 12 * row
        combo.hidePopup()

    def test_it_is_at_least_as_wide_as_the_box(self, qtbot):
        combo, popup = self._opened(qtbot, ["a", "b"])
        anchor = popup_lift.where_it_looks(combo)[1]
        assert popup.width() >= anchor.width()
        combo.hidePopup()


class TestPickingAValue:
    def test_a_pick_is_a_choice_the_control_commits_on(self, qtbot):
        """`activated`, not `currentIndexChanged`: a control commits on the
        first so that a re-run rewriting the options is not mistaken for
        somebody choosing."""
        _view, _card, combo = _in_a_view(qtbot)
        combo.showPopup()
        with qtbot.waitSignal(combo.activated, timeout=500) as caught:
            combo.card_list()._commit(2)
        assert caught.args == [2]
        assert combo.currentText() == "east"

    def test_picking_closes_the_list(self, qtbot):
        _view, _card, combo = _in_a_view(qtbot)
        combo.showPopup()
        popup = combo.card_list()
        popup._commit(0)
        assert not popup.isVisible()

    def test_escape_closes_it_without_picking(self, qtbot):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent, QKeySequence
        _view, _card, combo = _in_a_view(qtbot)
        combo.setCurrentIndex(0)
        combo.showPopup()
        popup = combo.card_list()
        popup.setCurrentIndex(popup.model().index(2, 0))
        popup.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape,
                                      Qt.NoModifier))
        assert not popup.isVisible()
        assert combo.currentIndex() == 0

    def test_the_release_that_opened_it_is_not_a_choice(self, qtbot):
        """A click on the box is press, popup, release — and the release
        lands on whatever the list has just put under the pointer."""
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        _view, _card, combo = _in_a_view(qtbot)
        combo.setCurrentIndex(0)
        combo.showPopup()
        popup = combo.card_list()
        release = QMouseEvent(QEvent.MouseButtonRelease, QPointF(10.0, 5.0),
                              QPointF(10.0, 5.0), Qt.LeftButton,
                              Qt.NoButton, Qt.NoModifier)
        popup.mouseReleaseEvent(release)
        assert popup.isVisible(), "a stray release closed the list"
        assert combo.currentIndex() == 0
        combo.hidePopup()


class TestARestackDoesNotDropTheCard:
    """The lift, which stays: it is what keeps a slicer's menu and the
    Report card's completer — both still Qt's own embedded popups — out
    from under the card in front.

    It is a flag rather than a saved number because the two private copies
    it replaced saved one: anything that restacked while a popup was open —
    a tile maximized, a page re-laid-out, a node brought to front — used to
    overwrite the lift, and closing the popup then wrote a stale z back over
    the top of it.
    """

    def _node_card(self, registry):
        graph = Graph()
        scene = NodeGraphScene(graph, QUndoStack(), registry=registry)
        node = registry.instantiate("flograph.input.choice", pos=(0.0, 0.0))
        graph.add_node(node)
        return graph, scene, scene.node_items[node.id]

    def test_restacking_mid_popup_keeps_the_lift(self, registry):
        _graph, _scene, item = self._node_card(registry)
        popup_lift.lift(item)
        assert item.zValue() == POPUP_HOST_Z
        item.apply_stacking()                 # what a restack does
        assert item.zValue() == POPUP_HOST_Z, "the restack dropped the card"
        popup_lift.drop(item)
        assert item.zValue() < POPUP_HOST_Z

    def test_closing_lands_on_where_it_belongs_now(self, registry):
        """Not on where it was when the popup opened. The node's place in
        the order can change while the list is up, and the card has to come
        back to the new one."""
        graph, _scene, item = self._node_card(registry)
        popup_lift.lift(item)
        graph.nodes[item.node.id].z = 7       # restacked underneath it
        item.apply_stacking()
        popup_lift.drop(item)
        assert item.zValue() == 7.0

    def test_two_popups_hold_it_up_until_both_are_shut(self, registry):
        """One card can carry two widgets with popups — a slicer beside a
        completer — and the first to close must not put it down."""
        _graph, _scene, item = self._node_card(registry)
        popup_lift.lift(item)
        popup_lift.lift(item)
        popup_lift.drop(item)
        assert item.zValue() == POPUP_HOST_Z
        popup_lift.drop(item)
        assert item.zValue() < POPUP_HOST_Z

    def test_dropping_more_than_it_was_lifted_does_not_go_negative(
            self, registry):
        _graph, _scene, item = self._node_card(registry)
        popup_lift.drop(item)
        popup_lift.drop(item)
        assert not popup_lift.is_lifted(item)
        popup_lift.lift(item)
        assert item.zValue() == POPUP_HOST_Z


class TestWhatStillNeedsTheLift:
    """A slicer's dropdown and a Choice control both open windows of their
    own now, so neither has to move its card. The Report card's suggestion
    list is still Qt's own popup, embedded in the canvas, and the lift is
    what keeps it out from under the card in front — through `popup_lift`,
    so it inherits the restack fix rather than keeping its own copy.
    """

    def test_the_slicer_opens_a_window_rather_than_lifting(self):
        from flograph.core.slicer import SlicerOptions
        from flograph.ui.slicer_list import SlicerPanel
        scene = QGraphicsScene()
        card = QGraphicsRectItem(0, 0, 240, 200)
        card.setZValue(3.0)
        scene.addItem(card)
        panel = SlicerPanel()
        panel.set_options(SlicerOptions(["region"], [("north",)]),
                          {"selected": "", "mode": "multi",
                           "layout": "dropdown", "show_counts": False})
        proxy = QGraphicsProxyWidget(card)
        proxy.setWidget(panel)
        view = QGraphicsView(scene)
        view.resize(600, 400)
        view.show()
        panel.view.open_popup()
        assert panel.view._popup.isWindow()
        assert panel.view._popup.graphicsProxyWidget() is None
        assert not popup_lift.is_lifted(card)
        assert card.zValue() == 3.0
        panel.view._popup.close()

    def test_neither_keeps_a_private_copy_of_the_lift(self):
        """A source check, because the next widget with a popup is the one
        that will write its own again."""
        from flograph.ui import slicer_list
        from flograph.ui.canvas import node_item
        for module in (slicer_list, node_item):
            text = pathlib.Path(module.__file__).read_text()
            assert "POPUP_HOST_Z" not in text, module.__name__


class TestHostItem:
    def test_it_finds_the_card_a_widget_sits_in(self):
        _scene, card, combo = _carded_combo()
        assert popup_lift.host_item(combo) is card

    def test_a_loose_widget_has_none(self, qtbot):
        widget = QWidget()
        qtbot.addWidget(widget)
        assert popup_lift.host_item(widget) is None

    def test_none_is_harmless(self):
        assert popup_lift.host_item(None) is None
        popup_lift.lift(None)
        popup_lift.drop(None)
