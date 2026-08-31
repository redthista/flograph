"""What a drag-select catches: anything the band touches (Qt's default), or
only what it fully contains — the setting in Settings > Canvas > Drag-select,
the modifier that flips it for one drag, and MainWindow's wiring of both onto
every canvas view.

The point of "fully inside" is frames. A band drawn across the middle of a
frame to pick up two of the nodes in it also picks the frame up while
touching, and the frame then drags the whole block along; contain leaves it
where it is unless the band goes round the outside of it.

No real MainWindow.show() here — see tests/test_gpu_viewport_setting.py's
module docstring for why that is unsafe under this offscreen harness.
Settings kept off the real store (avoid polluting the developer's actual
flograph.conf), like tests/test_lod_settings.py.
"""
import pytest
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QComboBox, QGraphicsView

from flograph.core import Frame, NodeRegistry
from flograph.ui import mainwindow as mod
from flograph.ui.canvas import base_view
from flograph.ui.settings_dialog import SettingsDialog

CONST = "flograph.util.constant"


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def window(qtbot, registry):
    win = mod.MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


def _mouse(view, kind, pos: QPoint, buttons, modifier=Qt.NoModifier) -> None:
    """One synthetic mouse event straight at the view's handler. Hand-built
    rather than qtbot.mouseMove, which cannot carry a held button on the
    offscreen platform — and a rubber band is nothing without one."""
    local = QPointF(pos)
    event = QMouseEvent(kind, local, local, Qt.LeftButton, buttons, modifier)
    if kind == QMouseEvent.Type.MouseButtonPress:
        view.mousePressEvent(event)
    elif kind == QMouseEvent.Type.MouseMove:
        view.mouseMoveEvent(event)
    else:
        view.mouseReleaseEvent(event)


def _band(view, top_left, bottom_right, modifier=Qt.NoModifier) -> list:
    """Drag a rubber band between two *scene* points; return what it caught."""
    start = view.mapFromScene(QPointF(*top_left))
    end = view.mapFromScene(QPointF(*bottom_right))
    middle = QPoint((start.x() + end.x()) // 2, (start.y() + end.y()) // 2)

    _mouse(view, QMouseEvent.Type.MouseButtonPress, start, Qt.LeftButton,
           modifier)
    _mouse(view, QMouseEvent.Type.MouseMove, middle, Qt.LeftButton, modifier)
    _mouse(view, QMouseEvent.Type.MouseMove, end, Qt.LeftButton, modifier)
    _mouse(view, QMouseEvent.Type.MouseButtonRelease, end, Qt.NoButton,
           modifier)
    return list(view.scene().selectedItems())


def _drag_band(view, top_left, bottom_right, modifier=Qt.NoModifier):
    """Draw a band and *leave the button down*, so a test can then press or
    release a key over a drag that is still in progress. Returns the end
    point in viewport coordinates, for the release."""
    start = view.mapFromScene(QPointF(*top_left))
    end = view.mapFromScene(QPointF(*bottom_right))
    _mouse(view, QMouseEvent.Type.MouseButtonPress, start, Qt.LeftButton,
           modifier)
    _mouse(view, QMouseEvent.Type.MouseMove, end, Qt.LeftButton, modifier)
    return end


def _key(view, key, pressed: bool, modifier=Qt.NoModifier) -> None:
    """A bare modifier key going down or coming up over the view."""
    kind = (QKeyEvent.Type.KeyPress if pressed
            else QKeyEvent.Type.KeyRelease)
    view.keyPressEvent(QKeyEvent(kind, key, modifier)) if pressed \
        else view.keyReleaseEvent(QKeyEvent(kind, key, modifier))


def _press(view, modifier=Qt.NoModifier) -> None:
    _mouse(view, QMouseEvent.Type.MouseButtonPress, QPoint(5, 5),
           Qt.LeftButton, modifier)


def _release(view, modifier=Qt.NoModifier) -> None:
    _mouse(view, QMouseEvent.Type.MouseButtonRelease, QPoint(5, 5),
           Qt.NoButton, modifier)


class TestTheSettingOnTheView:
    def test_frames_only_is_the_default(self, window):
        assert window.rubber_band_mode == "frames"
        # it rides on Qt's touch rule and takes the frames back afterwards
        assert window.view.rubberBandSelectionMode() == Qt.IntersectsItemShape

    def test_touch_reaches_the_view(self, window):
        window.set_rubber_band_mode("touch")
        assert window.view.rubberBandSelectionMode() == Qt.IntersectsItemShape

    def test_contain_reaches_the_view(self, window):
        window.set_rubber_band_mode("contain")
        assert window.view.rubberBandSelectionMode() == Qt.ContainsItemShape

    def test_it_persists(self, window):
        window.set_rubber_band_mode("contain")
        assert window.settings.value("canvas/rubber_band_mode") == "contain"

    def test_back_to_touch(self, window):
        window.set_rubber_band_mode("contain")
        window.set_rubber_band_mode("touch")
        assert window.view.rubberBandSelectionMode() == Qt.IntersectsItemShape

    def test_a_name_it_does_not_know_falls_back(self, window):
        window.view.set_rubber_band_mode("sideways")
        assert (window.view.effective_rubber_band_mode()
                == base_view.DEFAULT_RUBBER_BAND_MODE)

    def test_the_invert_key_persists(self, window):
        window.set_rubber_band_invert_key("shift")
        assert (window.settings.value("canvas/rubber_band_invert_key")
                == "shift")


class TestTheDialog:
    def test_the_mode_combo_starts_where_the_window_is(self, window, qtbot):
        window.set_rubber_band_mode("contain")
        dialog = SettingsDialog(window)
        qtbot.addWidget(dialog)
        combo = dialog.findChild(QComboBox, "rubber_band_mode_combo")
        assert combo.currentData() == "contain"

    def test_picking_fully_inside_pushes_it(self, window, qtbot):
        dialog = SettingsDialog(window)
        qtbot.addWidget(dialog)
        combo = dialog.findChild(QComboBox, "rubber_band_mode_combo")
        combo.setCurrentIndex(combo.findData("contain"))
        assert window.rubber_band_mode == "contain"
        assert window.view.rubberBandSelectionMode() == Qt.ContainsItemShape

    def test_picking_a_hold_key_pushes_it(self, window, qtbot):
        dialog = SettingsDialog(window)
        qtbot.addWidget(dialog)
        combo = dialog.findChild(QComboBox, "rubber_band_invert_key_combo")
        combo.setCurrentIndex(combo.findData("ctrl"))
        assert window.rubber_band_invert_key == "ctrl"

    def test_a_reset_pulls_both_combos_back(self, window, qtbot):
        dialog = SettingsDialog(window)
        qtbot.addWidget(dialog)
        window.set_rubber_band_mode("contain")
        window.set_rubber_band_invert_key("shift")
        dialog.refresh_from(window)
        mode = dialog.findChild(QComboBox, "rubber_band_mode_combo")
        key = dialog.findChild(QComboBox, "rubber_band_invert_key_combo")
        assert mode.currentData() == "contain"
        assert key.currentData() == "shift"

    def test_reset_settings_puts_the_defaults_back(self, window):
        window.set_rubber_band_mode("contain")
        window.set_rubber_band_invert_key("none")
        window.reset_settings()
        assert window.rubber_band_mode == base_view.DEFAULT_RUBBER_BAND_MODE
        assert (window.rubber_band_invert_key
                == base_view.DEFAULT_RUBBER_BAND_INVERT_KEY)


class TestTheHeldModifier:
    def test_ctrl_is_the_default_hold_key(self, window):
        assert window.rubber_band_invert_key == "ctrl"

    def test_holding_it_gets_the_band_that_crosses(self, window):
        """What the default setting is for: Ctrl gives back the band the
        canvas has always had, catching everything it crosses."""
        _press(window.view, Qt.ControlModifier)
        assert window.view.effective_rubber_band_mode() == "touch"
        assert window.view.rubberBandSelectionMode() == Qt.IntersectsItemShape

    def test_touch_flips_to_contain(self, window):
        window.set_rubber_band_mode("touch")
        _press(window.view, Qt.ControlModifier)
        assert window.view.effective_rubber_band_mode() == "contain"
        assert window.view.rubberBandSelectionMode() == Qt.ContainsItemShape

    def test_either_stricter_setting_flips_to_touch(self, window):
        for mode in ("frames", "contain"):
            window.set_rubber_band_mode(mode)
            _press(window.view, Qt.ControlModifier)
            assert window.view.effective_rubber_band_mode() == "touch"
            assert (window.view.rubberBandSelectionMode()
                    == Qt.IntersectsItemShape)
            _release(window.view)

    def test_the_release_puts_the_setting_back(self, window):
        window.set_rubber_band_mode("contain")
        _press(window.view, Qt.ControlModifier)
        _release(window.view)
        assert window.view.effective_rubber_band_mode() == "contain"
        assert window.view.rubberBandSelectionMode() == Qt.ContainsItemShape

    def test_nothing_held_leaves_the_setting_alone(self, window):
        window.set_rubber_band_mode("contain")
        _press(window.view)
        assert window.view.effective_rubber_band_mode() == "contain"

    def test_a_different_key_can_be_chosen(self, window):
        window.set_rubber_band_invert_key("alt")
        _press(window.view, Qt.ControlModifier)
        assert window.view.effective_rubber_band_mode() == "frames"
        _release(window.view)
        _press(window.view, Qt.AltModifier)
        assert window.view.effective_rubber_band_mode() == "touch"

    def test_none_turns_the_override_off(self, window):
        window.set_rubber_band_invert_key("none")
        _press(window.view, Qt.ControlModifier)
        assert window.view.effective_rubber_band_mode() == "frames"

    def test_a_locked_page_has_no_band_to_flip(self, window):
        view = window.view
        view.set_navigation_locked(True)
        assert view.dragMode() == QGraphicsView.NoDrag
        _press(view, Qt.ControlModifier)
        assert view.effective_rubber_band_mode() == "frames"


class TestWhatABandOverAFrameCatches:
    """The behaviour the setting exists for, dragged for real."""

    @pytest.fixture
    def framed(self, window):
        """A frame, a node well inside it, a second node left straddling the
        band's right edge, and the two scene corners of a band drawn round
        the first without reaching the frame's edges — the awkward drag the
        setting is about. All measured off the items rather than written
        down, so a change to how big a node is doesn't quietly turn these
        into tests of something else."""
        window.graph.add_frame(
            Frame(id="f1", title="Stage", rect=(0.0, 0.0, 600.0, 400.0)))
        inside = window.registry.instantiate(CONST, pos=(200.0, 180.0))
        window.graph.add_node(inside)
        straddling = window.registry.instantiate(CONST, pos=(400.0, 180.0))
        window.graph.add_node(straddling)
        window.view.resize(1000, 800)
        window.view.set_zoom(1.0)
        window.view.centerOn(300.0, 200.0)

        inside_item = window.scene.node_items[inside.id]
        straddler = window.scene.node_items[straddling.id]
        around = inside_item.sceneBoundingRect()
        around.adjust(-30, -30, 30, 30)
        # half in, half out: the case the middle setting keeps and the
        # strictest one drops
        straddler.setPos(around.right() - straddler.boundingRect().width() / 2,
                         around.top() + 10)
        frame_rect = window.scene.frame_items["f1"].sceneBoundingRect()
        assert frame_rect.contains(around), "the band must stay inside"
        band = ((around.left(), around.top()),
                (around.right(), around.bottom()))
        return window, inside_item, straddler, band

    def test_touching_takes_the_frame_too(self, framed):
        window, inside_item, straddler, band = framed
        window.set_rubber_band_mode("touch")
        selected = _band(window.view, *band)
        assert window.scene.frame_items["f1"] in selected
        assert inside_item in selected
        assert straddler in selected

    def test_by_default_the_frame_is_left_behind(self, framed):
        """The default: nodes on a graze, the frame only if you go round it."""
        window, inside_item, straddler, band = framed
        assert window.rubber_band_mode == "frames"
        selected = _band(window.view, *band)
        assert window.scene.frame_items["f1"] not in selected
        assert inside_item in selected
        assert straddler in selected

    def test_fully_inside_drops_the_half_caught_node_as_well(self, framed):
        window, inside_item, straddler, band = framed
        window.set_rubber_band_mode("contain")
        selected = _band(window.view, *band)
        assert window.scene.frame_items["f1"] not in selected
        assert inside_item in selected
        assert straddler not in selected

    def test_round_the_outside_still_takes_the_frame(self, framed):
        window, _inside, _straddler, _band_corners = framed
        for mode in ("frames", "contain"):
            window.set_rubber_band_mode(mode)
            selected = _band(window.view, (-60.0, -60.0), (680.0, 480.0))
            assert window.scene.frame_items["f1"] in selected, mode

    def test_the_held_key_gets_the_other_rule(self, framed):
        """Ctrl over a band inside the frame: the old rule back for one
        drag, so the frame comes with it."""
        window, _inside, _straddler, band = framed
        selected = _band(window.view, *band, modifier=Qt.ControlModifier)
        assert window.scene.frame_items["f1"] in selected

    def test_a_frame_picked_by_hand_survives_a_band_beside_it(self, framed):
        """Ctrl-dragging adds to a selection. Taking the frame back off it
        because this band did not enclose it would be a deselect nobody
        asked for — the band only ever adds.

        The hold key is moved off Ctrl here so the frame's survival can only
        be the protection under test, and not the touch rule Ctrl otherwise
        brings with it."""
        window, inside_item, _straddler, band = framed
        window.set_rubber_band_invert_key("none")
        frame_item = window.scene.frame_items["f1"]
        frame_item.setSelected(True)
        selected = _band(window.view, *band, modifier=Qt.ControlModifier)
        assert frame_item in selected
        assert inside_item in selected

    def test_pressing_the_key_mid_drag_brings_the_frame_in(self, framed):
        """Reported: "when i drag to select nodes inside a frame and then
        push ctrl i expect to see the frame also then selected". The mouse
        does not move between the band and the key, so nothing but the key
        can prompt the change."""
        window, inside_item, _straddler, band = framed
        end = _drag_band(window.view, *band)
        assert window.scene.frame_items["f1"] not in window.scene.selectedItems()

        _key(window.view, Qt.Key_Control, pressed=True)
        selected = window.scene.selectedItems()
        assert window.scene.frame_items["f1"] in selected
        assert inside_item in selected
        _mouse(window.view, QMouseEvent.Type.MouseButtonRelease, end,
               Qt.NoButton)

    def test_and_letting_go_of_it_drops_the_frame_again(self, framed):
        """"and if i release ctrl then un selected"."""
        window, inside_item, _straddler, band = framed
        end = _drag_band(window.view, *band)
        _key(window.view, Qt.Key_Control, pressed=True)
        _key(window.view, Qt.Key_Control, pressed=False)

        selected = window.scene.selectedItems()
        assert window.scene.frame_items["f1"] not in selected
        assert inside_item in selected, "the nodes it did catch stay caught"
        _mouse(window.view, QMouseEvent.Type.MouseButtonRelease, end,
               Qt.NoButton)

    def test_the_selection_it_ends_on_is_the_one_you_keep(self, framed):
        """Releasing the mouse with the key still down keeps the frame."""
        window, _inside, _straddler, band = framed
        end = _drag_band(window.view, *band)
        _key(window.view, Qt.Key_Control, pressed=True)
        _mouse(window.view, QMouseEvent.Type.MouseButtonRelease, end,
               Qt.NoButton, Qt.ControlModifier)
        assert window.scene.frame_items["f1"] in window.scene.selectedItems()

    def test_a_key_that_is_not_the_invert_key_changes_nothing(self, framed):
        window, _inside, _straddler, band = framed
        end = _drag_band(window.view, *band)
        _key(window.view, Qt.Key_Shift, pressed=True)
        assert window.scene.frame_items["f1"] not in window.scene.selectedItems()
        _mouse(window.view, QMouseEvent.Type.MouseButtonRelease, end,
               Qt.NoButton)

    def test_a_key_with_no_band_in_progress_changes_nothing(self, window):
        """Ctrl over an idle canvas is somebody reaching for a shortcut."""
        frame_id = "f2"
        window.graph.add_frame(
            Frame(id=frame_id, title="Idle", rect=(0.0, 0.0, 200.0, 150.0)))
        _key(window.view, Qt.Key_Control, pressed=True)
        assert window.scene.selectedItems() == []
        assert window.view.effective_rubber_band_mode() == "frames"

    def test_a_frame_grazed_from_outside_is_still_left_behind(self, framed):
        """Not just bands drawn inside it: clipping a corner is a graze too."""
        window, _inside, _straddler, _band_corners = framed
        selected = _band(window.view, (-100.0, -100.0), (120.0, 120.0))
        assert window.scene.frame_items["f1"] not in selected
