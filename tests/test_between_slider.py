"""The Between control: two handles on one track emitting a low/high pair.

Covers the parsing (core, Qt-free), the node's run(), and the painted
widget — including the two things a hand-drawn range control gets wrong if
nobody checks: that a handle dragged past the other swaps rather than jams,
and that one keystroke is one commit rather than two.
"""
import json

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from flograph.core import Graph, NodeRegistry
from flograph.core.controls import range_values
from flograph.core.script import CONTROL_KINDS
from flograph.ui import theme
from flograph.ui.controls import (CONTROL_SIZES, RangeControl, RangeSlider,
                                  build_control, control_size)

TYPE_ID = "flograph.input.between_slider"


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture(scope="module")
def node_run():
    source = open("src/flograph/nodes/input/between_slider.py").read()
    namespace: dict = {}
    exec(compile(source, "between_slider", "exec"), namespace)
    return namespace["run"]


class Ctx:
    def __init__(self, params=None):
        self.params = params or {}


@pytest.fixture
def control(qtbot):
    widget = build_control("range")
    qtbot.addWidget(widget)
    widget.resize(*(int(v) for v in control_size("range")))
    return widget


class TestRangeValues:
    def test_blank_is_the_whole_range(self):
        """An untouched Between spans its bounds — emitting a degenerate
        range would make a fresh node filter everything out."""
        assert range_values("", 0.0, 100.0) == (0.0, 100.0)

    def test_reads_a_json_pair(self):
        assert range_values("[10, 50]", 0.0, 100.0) == (10.0, 50.0)

    def test_puts_a_reversed_pair_back_in_order(self):
        assert range_values("[50, 10]", 0.0, 100.0) == (10.0, 50.0)

    def test_takes_a_hand_typed_pair(self):
        assert range_values("10, 50", 0.0, 100.0) == (10.0, 50.0)

    def test_takes_a_list_directly(self):
        assert range_values([5, 7], 0.0, 100.0) == (5.0, 7.0)

    def test_nonsense_falls_back_rather_than_raising(self):
        assert range_values("nonsense", 1.0, 9.0) == (1.0, 9.0)
        assert range_values("[1]", 1.0, 9.0) == (1.0, 9.0)
        assert range_values(None, 1.0, 9.0) == (1.0, 9.0)


class TestNode:
    def test_the_registry_knows_it(self, registry):
        spec = registry.get(TYPE_ID)
        assert spec.card == "control" and spec.control == "range"
        assert [p.name for p in spec.outputs] == ["low", "high"]

    def test_range_is_a_declarable_control_kind(self):
        """core validates NODE['control'] against this set, so a shape the
        UI can build but core rejects is a node that will not load."""
        assert "range" in CONTROL_KINDS

    def test_untouched_spans_the_bounds(self, node_run):
        assert node_run(Ctx()) == {"low": 0, "high": 100}

    def test_emits_the_stored_window(self, node_run):
        assert node_run(Ctx({"value": "[20, 60]"})) == {"low": 20, "high": 60}

    def test_clamps_into_the_bounds(self, node_run):
        assert node_run(Ctx({"value": "[-40, 400]"})) == {"low": 0, "high": 100}

    def test_decimals_give_floats(self, node_run):
        out = node_run(Ctx({"value": "[0.12, 0.87]", "minimum": 0,
                            "maximum": 1, "decimals": 2}))
        assert out == {"low": 0.12, "high": 0.87}

    def test_whole_numbers_without_decimals(self, node_run):
        out = node_run(Ctx({"value": "[1.6, 8.4]"}))
        assert out == {"low": 2, "high": 8}

    def test_bounds_come_from_a_wire(self, node_run):
        out = node_run(Ctx(), minimum=[3, 9, 5], maximum=[3, 9, 5])
        assert out == {"low": 3, "high": 9}

    def test_a_wired_bound_beats_the_typed_one(self, node_run):
        out = node_run(Ctx({"minimum": 0, "maximum": 100}),
                       minimum=[10, 20], maximum=[10, 20])
        assert out == {"low": 10, "high": 20}

    def test_inverted_bounds_do_not_explode(self, node_run):
        assert node_run(Ctx({"minimum": 100, "maximum": 0})) == \
            {"low": 100, "high": 100}


class TestRangeSlider:
    def test_values_are_kept_in_order(self, qtbot):
        slider = RangeSlider()
        qtbot.addWidget(slider)
        slider.setMaximum(100)
        slider.setValues(70, 30)
        assert slider.values() == (30, 70)

    def test_values_are_clamped_to_the_track(self, qtbot):
        slider = RangeSlider()
        qtbot.addWidget(slider)
        slider.setMaximum(50)
        slider.setValues(-10, 900)
        assert slider.values() == (0, 50)

    def test_shrinking_the_track_brings_the_handles_in(self, qtbot):
        slider = RangeSlider()
        qtbot.addWidget(slider)
        slider.setMaximum(100)
        slider.setValues(20, 90)
        slider.setMaximum(50)
        assert slider.values() == (20, 50)

    def test_a_zero_length_track_does_not_divide_by_zero(self, qtbot):
        slider = RangeSlider()
        qtbot.addWidget(slider)
        slider.setMaximum(0)
        slider.resize(200, 20)
        assert slider.values() == (0, 0)
        slider.grab()

    def test_it_actually_draws(self, qtbot):
        slider = RangeSlider()
        qtbot.addWidget(slider)
        slider.resize(200, 20)
        slider.setMaximum(100)
        slider.setValues(20, 80)
        image = slider.grab().toImage()
        inked = sum(1 for y in range(image.height())
                    for x in range(image.width())
                    if image.pixel(x, y) & 0x00FFFFFF)
        assert inked > 200

    def test_the_span_between_the_handles_is_filled(self, qtbot):
        """The fill is why a range reads at a glance rather than as two
        numbers that happen to sit near each other."""
        slider = RangeSlider()
        qtbot.addWidget(slider)
        slider.resize(200, 20)
        slider.setMaximum(100)
        slider.setValues(30, 70)
        image = slider.grab().toImage()
        from flograph.ui.controls import CHECK_ON
        target = CHECK_ON.rgb() & 0x00FFFFFF
        row = image.height() // 2
        filled = sum(1 for x in range(image.width())
                     if (image.pixel(x, row) & 0x00FFFFFF) == target)
        assert filled > 40

    def _drag(self, app_slider, from_x, to_x):
        for kind, x in ((QEvent.MouseButtonPress, from_x),
                        (QEvent.MouseMove, to_x),
                        (QEvent.MouseButtonRelease, to_x)):
            point = QPointF(x, app_slider.height() / 2)
            app_slider.event(QMouseEvent(kind, point, point, Qt.LeftButton,
                                         Qt.LeftButton, Qt.NoModifier))

    def test_a_handle_dragged_past_the_other_swaps(self, qtbot):
        """Blocking would stop the drag dead and leave the pointer walking
        away from a handle that is no longer under it."""
        slider = RangeSlider()
        qtbot.addWidget(slider)
        slider.resize(200, 20)
        slider.setMaximum(100)
        slider.setValues(40, 60)
        low_x, high_x = slider.handle_centres()
        self._drag(slider, high_x, low_x - 30)
        low, high = slider.values()
        assert low <= high
        assert low < 40                    # the grabbed handle went left

    def test_a_drag_reports_moves_and_one_release(self, qtbot):
        slider = RangeSlider()
        qtbot.addWidget(slider)
        slider.resize(200, 20)
        slider.setMaximum(100)
        slider.setValues(40, 60)
        moves, releases = [], []
        slider.moved.connect(lambda: moves.append(1))
        slider.released.connect(lambda: releases.append(1))
        _, high_x = slider.handle_centres()
        self._drag(slider, high_x, high_x + 40)
        assert moves and len(releases) == 1

    def test_arrows_move_the_active_handle(self, qtbot):
        slider = RangeSlider()
        qtbot.addWidget(slider)
        slider.setMaximum(100)
        slider.setValues(40, 60)
        slider.event(QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))
        assert slider.values() == (40, 61)

    def test_space_swaps_which_handle_the_keyboard_drives(self, qtbot):
        slider = RangeSlider()
        qtbot.addWidget(slider)
        slider.setMaximum(100)
        slider.setValues(40, 60)
        slider.event(QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier))
        slider.event(QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))
        assert slider.values() == (41, 60)

    def test_the_keyboard_cannot_cross_the_handles(self, qtbot):
        slider = RangeSlider()
        qtbot.addWidget(slider)
        slider.setMaximum(100)
        slider.setValues(50, 50)
        slider.event(QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier))
        slider.event(QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))
        slider.event(QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))
        low, high = slider.values()
        assert low <= high

    def test_end_and_home_jump_to_the_ends(self, qtbot):
        slider = RangeSlider()
        qtbot.addWidget(slider)
        slider.setMaximum(100)
        slider.setValues(40, 60)
        slider.event(QKeyEvent(QEvent.KeyPress, Qt.Key_End, Qt.NoModifier))
        assert slider.values()[1] == 100


class TestRangeControl:
    def test_it_is_the_shape_registered_for_range(self, control):
        assert isinstance(control, RangeControl)
        assert "range" in CONTROL_SIZES

    def test_reads_back_what_it_was_given(self, control):
        control.sync({"minimum": 0, "maximum": 100, "value": "[20, 60]"})
        assert json.loads(control._read()) == [20, 60]

    def test_an_untouched_control_spans_its_bounds(self, control):
        control.sync({"minimum": 5, "maximum": 25})
        assert json.loads(control._read()) == [5, 25]

    def test_the_readout_names_both_ends(self, control):
        control.sync({"minimum": 0, "maximum": 100, "value": "[20, 60]"})
        assert control._readout.text() == "20 – 60"

    def test_the_bounds_are_labelled_either_side(self, control):
        control.sync({"minimum": 5, "maximum": 25, "value": "[10, 20]"})
        assert control._low_label.text() == "5"
        assert control._high_label.text() == "25"

    def test_float_steps_round_trip(self, control):
        control.sync({"minimum": 0, "maximum": 1, "step": 0.05,
                      "decimals": 2, "value": "[0.15, 0.85]"})
        assert json.loads(control._read()) == [0.15, 0.85]

    def test_a_wired_bound_moves_the_track(self, control):
        control.sync({"minimum": 0, "maximum": 100})
        control.set_upstream({"minimum": 10, "maximum": 20})
        assert control._low_label.text() == "10"
        assert json.loads(control._read()) == [10, 20]

    def test_syncing_does_not_look_like_a_user_edit(self, control):
        """The guard that stops a params refresh looping: committing re-runs
        the node, and the run pushes the value straight back down here."""
        seen = []
        control.value_committed.connect(seen.append)
        control.sync({"minimum": 0, "maximum": 100, "value": "[20, 60]"})
        assert seen == []

    def test_one_keystroke_is_one_commit(self, control):
        """`moved` already commits when the handle is not being dragged, so
        also emitting `released` would push two undo steps and queue two
        runs for a single arrow key."""
        control.sync({"minimum": 0, "maximum": 100, "value": "[20, 60]"})
        seen = []
        control.value_committed.connect(seen.append)
        control._slider.event(
            QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier))
        assert len(seen) == 1
        assert json.loads(seen[0]) == [20, 61]

    def test_a_drag_commits_once_on_release(self, control):
        control.sync({"minimum": 0, "maximum": 100, "value": "[20, 60]"})
        control.show()
        seen = []
        control.value_committed.connect(seen.append)
        slider = control._slider
        _, high_x = slider.handle_centres()
        for kind, x in ((QEvent.MouseButtonPress, high_x),
                        (QEvent.MouseMove, high_x + 10),
                        (QEvent.MouseMove, high_x + 20),
                        (QEvent.MouseButtonRelease, high_x + 20)):
            point = QPointF(x, slider.height() / 2)
            slider.event(QMouseEvent(kind, point, point, Qt.LeftButton,
                                     Qt.LeftButton, Qt.NoModifier))
        assert len(seen) == 1

    def test_focus_editor_reaches_the_slider(self, control, monkeypatch):
        """Hosts call this so a card is usable in one click, not two. The
        offscreen platform never grants real focus to an inactive window, so
        this checks the call lands on the slider rather than the outcome."""
        focused = []
        monkeypatch.setattr(control._slider, "setFocus",
                            lambda *a: focused.append(True))
        control.focus_editor()
        assert focused == [True]


class TestInGraph:
    def test_a_between_node_runs_in_a_graph(self, qtbot, registry):
        from flograph.engine.scheduler import ExecutionEngine

        graph = Graph()
        node = graph.add_node(registry.instantiate(TYPE_ID))
        graph.set_param(node.id, "value", "[25, 75]")
        engine = ExecutionEngine(graph)
        with qtbot.waitSignal(engine.run_finished, timeout=20000):
            engine.run_all()
        assert engine.cache.outputs_for(node.id) == {"low": 25, "high": 75}
