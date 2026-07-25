"""ideas.md items 5, 9, 10, 11 and 16: the Input node category and the
`card: "control"` foundation under it.

A control node has no rendered output — it *is* the input. One widget
serves both hosts, so most of what matters here is that a control behaves
identically on the canvas card and on a dashboard tile, that moving it is
one undoable step that re-runs what it feeds, and that what the widget
shows is what the node emits.

Settings kept off the real store (avoid polluting the developer's actual
flograph.conf) -- see test_lod_settings.py's fixture of the same name.
"""
import datetime
import json

import pandas as pd
import pytest
from PySide6.QtCore import QDate, QSettings, Qt
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry, NodeScriptError, Page, Tile
from flograph.core.controls import (choice_value, date_value, lines_to_values,
                                    selected_values, values_from_source)
from flograph.core.script import CONTROL_KINDS, parse_spec
from flograph.ui import mainwindow as mod
from flograph.ui.canvas import NodeGraphScene
from flograph.ui.commands import (AddPageCommand, AddTileCommand,
                                  SetCodeCommand)
from flograph.ui.controls import build_control, control_size, iso_to_qdate
from flograph.ui.mainwindow import MainWindow

CONTROL_TYPES = {
    "slider": "flograph.input.slider",
    "number": "flograph.input.number",
    "text": "flograph.input.text",
    "date": "flograph.input.date",
    "toggle": "flograph.input.toggle",
    "choice": "flograph.input.choice",
}
TEMPLATE = "flograph.scripting.control_template"
TODAY = datetime.date.today().isoformat()


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
def env(qtbot, registry):
    graph = Graph()
    stack = QUndoStack()
    scene = NodeGraphScene(graph, stack, registry=registry)
    return graph, stack, scene


@pytest.fixture
def window(qtbot, registry):
    win = MainWindow(registry)
    win.confirm_close = False
    qtbot.addWidget(win)
    return win


def add_control(target, kind, registry=None, **params):
    """A control node of `kind` on a graph, plus its params."""
    graph = getattr(target, "graph", target)
    registry = registry or target.registry
    node = graph.add_node(registry.instantiate(CONTROL_TYPES[kind]))
    for name, value in params.items():
        graph.set_param(node.id, name, value)
    return node


def run_all(qtbot, window):
    with qtbot.waitSignal(window.engine.run_finished, timeout=20000):
        window.engine.run_all()


def output(window, node, port="value"):
    entry = window.engine.cache.get(node.id)
    return entry.outputs.get(port) if entry else None


# --------------------------------------------------------------- the contract


class TestScriptContract:
    def test_every_control_kind_has_a_node(self, registry):
        declared = {s.control for s in registry.all() if s.card == "control"}
        assert declared == set(CONTROL_KINDS)

    def test_control_nodes_live_in_the_input_category(self, registry):
        """...except the write-your-own template, which belongs beside the
        other template in Scripting where people go looking for it."""
        categories = {s.category for s in registry.all()
                      if s.card == "control" and s.type_id != TEMPLATE}
        assert categories == {"Input"}
        assert registry.get(TEMPLATE).category == "Scripting"

    def test_a_control_card_must_name_its_shape(self):
        with pytest.raises(NodeScriptError, match="not a valid control kind"):
            parse_spec('NODE = {"label": "X", "category": "Input",'
                       ' "card": "control", "inputs": [], "outputs": []}\n'
                       'def run(ctx): return {}\n', "t.x")

    def test_an_unknown_shape_is_rejected(self):
        with pytest.raises(NodeScriptError, match="not a valid control kind"):
            parse_spec('NODE = {"label": "X", "category": "Input",'
                       ' "card": "control", "control": "dial",'
                       ' "inputs": [], "outputs": []}\n'
                       'def run(ctx): return {}\n', "t.x")

    def test_control_without_a_control_card_is_rejected(self):
        with pytest.raises(NodeScriptError, match="only applies"):
            parse_spec('NODE = {"label": "X", "category": "Input",'
                       ' "control": "slider", "inputs": [], "outputs": []}\n'
                       'def run(ctx): return {}\n', "t.x")

    def test_the_shape_survives_a_fork(self, registry):
        """`control` rides in the script text like `card` does, so editing a
        control's code in the editor doesn't turn it back into a plain
        node."""
        spec = registry.get(CONTROL_TYPES["slider"])
        assert parse_spec(spec.source, "user.mine").control == "slider"

    def test_every_shape_builds_a_widget(self, qtbot):
        for kind in CONTROL_KINDS:
            widget = build_control(kind)
            assert widget is not None, kind
            qtbot.addWidget(widget)

    def test_an_unknown_shape_yields_no_widget(self):
        """A project written by a newer flograph must still open."""
        assert build_control("dial") is None


class TestControlTemplate:
    """The write-your-own starting point has to actually work, or it teaches
    the contract wrong."""

    def test_it_is_a_working_control_out_of_the_box(self, env, registry):
        graph, _, scene = env
        node = graph.add_node(registry.instantiate(TEMPLATE))
        item = scene.node_items[node.id]
        assert item.control and item._control_widget is not None

    def test_it_demonstrates_reshaping_the_value(self, qtbot, window):
        """It emits a fraction from a percentage — the point being that a
        control node is a shape plus whatever run() makes of the value."""
        node = window.graph.add_node(window.registry.instantiate(TEMPLATE))
        window.graph.set_param(node.id, "value", 25.0)
        run_all(qtbot, window)
        assert output(window, node) == 0.25

    def test_its_wired_bound_works_as_documented(self, qtbot, window):
        node = window.graph.add_node(window.registry.instantiate(TEMPLATE))
        window.graph.set_param(node.id, "value", 90.0)
        driver = add_control(window, "number", value=40,
                             minimum=0, maximum=100)
        window.graph.connect(driver.id, "value", node.id, "maximum")
        run_all(qtbot, window)
        assert output(window, node) == 0.4  # clamped to the wired maximum

    def test_the_card_and_the_node_agree(self, qtbot, window):
        """The rule its comments make a point of: emit what the card shows.
        The card shows the percentage, the node emits the fraction."""
        node = window.graph.add_node(window.registry.instantiate(TEMPLATE))
        window.graph.set_param(node.id, "value", 35.0)
        run_all(qtbot, window)
        widget = window.scene.node_items[node.id]._control_widget
        assert output(window, node) == widget._read() / 100.0


# ------------------------------------------------------------- shared helpers


class TestCoreHelpers:
    def test_lines_to_values_drops_blanks_and_duplicates(self):
        assert lines_to_values("a\n\n b \na\nc") == ["a", "b", "c"]

    def test_lines_to_values_also_splits_commas(self):
        assert lines_to_values("a, b ,c") == ["a", "b", "c"]

    def test_values_from_source_reads_a_named_column(self):
        frame = pd.DataFrame({"x": [1, 2], "region": ["s", "n"]})
        assert values_from_source(frame, "region") == ["n", "s"]

    def test_values_from_source_falls_back_to_the_first_column(self):
        frame = pd.DataFrame({"x": ["b", "a"], "y": ["q", "r"]})
        assert values_from_source(frame, "nope") == ["a", "b"]

    def test_values_from_source_handles_a_series_and_a_list(self):
        assert values_from_source(pd.Series(["b", "a", None])) == ["a", "b"]
        assert values_from_source(["b", "a", "b"]) == ["a", "b"]

    def test_values_from_source_of_nothing_is_none(self):
        assert values_from_source(None) is None

    def test_selected_values_reads_json_and_hand_edits(self):
        assert selected_values('["a", "b"]') == ["a", "b"]
        assert selected_values("a, b") == ["a", "b"]
        assert selected_values("") == []

    def test_a_blank_date_means_today(self):
        assert date_value("") == TODAY
        assert date_value("not a date") == TODAY
        assert date_value("2024-03-05") == "2024-03-05"

    def test_a_blank_choice_means_the_first_option(self):
        assert choice_value("", ["a", "b"]) == "a"
        assert choice_value("b", ["a", "b"]) == "b"
        assert choice_value("", []) == ""

    def test_a_choice_no_longer_offered_is_kept(self):
        """Silently swapping it would change someone's dashboard under
        them."""
        assert choice_value("gone", ["a", "b"]) == "gone"


# ------------------------------------------------------------ the canvas card


class TestControlCard:
    def test_each_control_builds_its_widget_on_the_card(self, env, registry):
        graph, _, scene = env
        for kind in CONTROL_TYPES:
            node = add_control(graph, kind, registry)
            item = scene.node_items[node.id]
            assert item.control, kind
            assert item._control_widget is not None, kind

    def test_the_card_lands_at_the_shape_s_natural_size(self, env, registry):
        graph, _, scene = env
        node = add_control(graph, "slider", registry)
        item = scene.node_items[node.id]
        assert (item.width, item.body_height) == control_size("slider")

    def test_moving_a_control_writes_the_value_param(self, env, registry):
        graph, _, scene = env
        node = add_control(graph, "slider", registry,
                           minimum=0, maximum=100, step=1, value=10)
        item = scene.node_items[node.id]
        item._control_widget._slider.setValue(42)
        assert node.params["value"] == 42

    def test_an_adjustment_is_one_undo_step(self, env, registry):
        graph, stack, scene = env
        node = add_control(graph, "number", registry, value=5)
        item = scene.node_items[node.id]
        before = stack.index()
        item._control_widget._spin.setValue(9)
        item._control_widget._spin.setValue(11)
        assert stack.index() == before + 2
        stack.undo()
        assert node.params["value"] == 9

    def test_undo_moves_the_widget_back(self, env, registry):
        graph, stack, scene = env
        node = add_control(graph, "toggle", registry, value=False)
        item = scene.node_items[node.id]
        item._control_widget._check.setChecked(True)
        stack.undo()
        assert node.params["value"] is False
        assert item._control_widget._read() is False

    def test_a_properties_edit_reaches_the_card(self, env, registry):
        graph, _, scene = env
        node = add_control(graph, "text", registry)
        item = scene.node_items[node.id]
        graph.set_param(node.id, "value", "from the panel")
        item.on_params_changed()
        assert item._control_widget._read() == "from the panel"

    def test_syncing_the_card_does_not_look_like_an_edit(self, env, registry):
        """sync() holds a guard: without it the value would bounce back out
        as a commit, and committing re-runs the node, which syncs again."""
        graph, _, scene = env
        node = add_control(graph, "slider", registry, value=10)
        item = scene.node_items[node.id]
        fired = []
        item._control_widget.value_committed.connect(fired.append)
        graph.set_param(node.id, "value", 80)
        item.on_params_changed()
        assert fired == []

    def test_the_caption_is_shown_when_set(self, env, registry):
        graph, _, scene = env
        node = add_control(graph, "slider", registry)
        widget = scene.node_items[node.id]._control_widget
        assert widget._caption.isHidden()
        graph.set_param(node.id, "caption", "Threshold")
        scene.node_items[node.id].on_params_changed()
        assert widget._caption.text() == "Threshold"
        assert not widget._caption.isHidden()

    def test_a_control_card_is_resizable(self, env, registry):
        graph, _, scene = env
        node = add_control(graph, "text", registry)
        assert scene.node_items[node.id]._resizable()

    def test_a_control_is_never_wired_from_a_port_row(self, env, registry):
        """Control cards use header ports like the other widget cards —
        stacked port rows would push the widget off the bottom."""
        graph, _, scene = env
        node = add_control(graph, "choice", registry)
        item = scene.node_items[node.id]
        assert item.input_ports["options"].pos().y() < item.body_height / 2


class TestAppearance:
    @pytest.mark.parametrize("kind", sorted(CONTROL_TYPES))
    def test_a_control_paints_on_the_card_not_the_desktop(self, qtbot, kind):
        """A control sits on a node card, so it has to take the card's dark
        body — left to the OS palette it comes out as a white slab with a
        near-invisible caption on it."""
        from PySide6.QtGui import QPixmap

        from flograph.ui import theme
        widget = build_control(kind)
        qtbot.addWidget(widget)
        widget.sync({"caption": "Cap", "items": "a\nb"})
        widget.resize(*[int(v) for v in control_size(kind)])
        widget.show()
        qtbot.waitExposed(widget)
        pixmap = QPixmap(widget.size())
        widget.render(pixmap)
        image = pixmap.toImage()
        # bottom-left: below the caption, left of any editor — plain backdrop
        corner = image.pixelColor(3, image.height() - 4)
        assert corner == theme.NODE_BODY, f"{kind}: {corner.name()}"

    def test_the_caption_does_not_paint_its_own_slab(self, qtbot):
        from PySide6.QtGui import QPixmap

        from flograph.ui import theme
        widget = build_control("toggle")
        qtbot.addWidget(widget)
        widget.sync({"caption": "Heading", "text": "Tick"})
        widget.resize(200, 76)
        widget.show()
        qtbot.waitExposed(widget)
        pixmap = QPixmap(widget.size())
        widget.render(pixmap)
        # to the right of the caption text, still on the caption's row
        assert pixmap.toImage().pixelColor(190, 8) == theme.NODE_BODY


# ------------------------------------------------------------ each shape


class TestShapes:
    def test_slider_reports_its_position_in_real_units(self, qtbot):
        widget = build_control("slider")
        qtbot.addWidget(widget)
        widget.sync({"minimum": 10, "maximum": 20, "step": 2, "value": 10})
        widget._slider.setValue(3)          # 3 notches of 2 above 10
        assert widget._read() == 16

    def test_slider_does_float_steps(self, qtbot):
        widget = build_control("slider")
        qtbot.addWidget(widget)
        widget.sync({"minimum": 0, "maximum": 1, "step": 0.05,
                     "decimals": 2, "value": 0})
        assert widget._slider.maximum() == 20
        widget._slider.setValue(3)
        assert widget._read() == 0.15

    def test_a_drag_commits_once_on_release(self, qtbot):
        """Committing per tick would re-run the whole downstream flow — and
        push an undo step — for every pixel of travel."""
        widget = build_control("slider")
        qtbot.addWidget(widget)
        widget.sync({"minimum": 0, "maximum": 100, "step": 1, "value": 0})
        fired = []
        widget.value_committed.connect(fired.append)

        widget._slider.setSliderDown(True)
        for value in (10, 20, 30, 40):
            widget._slider.setValue(value)
        assert fired == []                       # still dragging
        assert widget._readout.text() == "40"    # but the card keeps up
        widget._slider.setSliderDown(False)      # emits sliderReleased
        assert fired == [40]

    def test_a_discrete_change_commits_at_once(self, qtbot):
        """An arrow key or the wheel has no later moment to wait for."""
        widget = build_control("slider")
        qtbot.addWidget(widget)
        widget.sync({"minimum": 0, "maximum": 100, "step": 1, "value": 0})
        fired = []
        widget.value_committed.connect(fired.append)
        widget._slider.setValue(7)
        assert fired == [7]

    def test_the_readout_tracks_the_handle_mid_drag(self, qtbot):
        widget = build_control("slider")
        qtbot.addWidget(widget)
        widget.sync({"minimum": 0, "maximum": 100, "step": 1, "value": 0})
        widget.resize(240, 70)
        widget.show()
        qtbot.waitExposed(widget)
        widget._slider.setSliderDown(True)
        start = widget._readout.x()
        widget._slider.setValue(80)
        assert widget._readout.text() == "80"
        assert widget._readout.x() > start

    def test_a_run_mid_drag_does_not_snap_the_handle(self, qtbot):
        """The handle belongs to the user's finger until they let go."""
        widget = build_control("slider")
        qtbot.addWidget(widget)
        widget.sync({"minimum": 0, "maximum": 100, "step": 1, "value": 10})
        widget._slider.setSliderDown(True)
        widget._slider.setValue(80)
        widget.sync({"minimum": 0, "maximum": 100, "step": 1, "value": 10})
        assert widget._read() == 80

    def test_a_card_drag_is_one_undo_step(self, env, registry):
        graph, stack, scene = env
        node = add_control(graph, "slider", registry,
                           minimum=0, maximum=100, step=1, value=0)
        slider = scene.node_items[node.id]._control_widget._slider
        before = stack.index()
        slider.setSliderDown(True)
        for value in (5, 15, 25, 35):
            slider.setValue(value)
        assert stack.index() == before        # nothing committed yet
        slider.setSliderDown(False)
        assert stack.index() == before + 1
        assert node.params["value"] == 35

    def test_a_card_drag_reruns_once(self, qtbot, window):
        control = add_control(window, "slider", minimum=0, maximum=100,
                              step=1, value=0)
        slider = window.scene.node_items[control.id]._control_widget._slider
        runs = []
        window.engine.run_started.connect(lambda: runs.append(1))
        slider.setSliderDown(True)
        for value in (10, 20, 30):
            slider.setValue(value)
        assert runs == []
        with qtbot.waitSignal(window.engine.run_finished, timeout=20000):
            slider.setSliderDown(False)
        assert len(runs) == 1
        assert output(window, control) == 30

    def test_slider_labels_both_ends_of_its_range(self, qtbot):
        """The scale has to be readable off the card — especially once the
        bounds are wired from data and nobody typed them."""
        widget = build_control("slider")
        qtbot.addWidget(widget)
        widget.sync({"minimum": 1200, "maximum": 98500, "step": 100,
                     "value": 43000})
        assert widget._low_label.text() == "1,200"
        assert widget._high_label.text() == "98,500"
        assert widget._readout.text() == "43,000"

    def test_slider_bound_labels_follow_a_wired_range(self, qtbot):
        widget = build_control("slider")
        qtbot.addWidget(widget)
        widget.sync({"minimum": 0, "maximum": 100, "step": 1, "value": 0})
        widget.set_upstream({"minimum": 5, "maximum": 250})
        assert (widget._low_label.text(), widget._high_label.text()) \
            == ("5", "250")

    def test_slider_bound_labels_use_the_value_format(self, qtbot):
        widget = build_control("slider")
        qtbot.addWidget(widget)
        widget.sync({"minimum": 0, "maximum": 1, "step": 0.05,
                     "decimals": 2, "value": 0.35})
        assert (widget._low_label.text(), widget._high_label.text()) \
            == ("0.00", "1.00")

    def test_the_readout_rides_under_the_handle(self, qtbot):
        widget = build_control("slider")
        qtbot.addWidget(widget)
        widget.sync({"minimum": 0, "maximum": 100, "step": 1, "value": 0})
        widget.resize(240, 70)
        widget.show()
        qtbot.waitExposed(widget)

        def readout_centre():
            return widget._readout.x() + widget._readout.width() / 2

        widget._slider.setValue(0)
        at_low = readout_centre()
        widget._slider.setValue(50)
        at_mid = readout_centre()
        widget._slider.setValue(100)
        at_high = readout_centre()
        assert at_low < at_mid < at_high

    def test_the_readout_is_kept_inside_its_strip(self, qtbot):
        """Centred on the handle, but never hanging off either end. Not
        currently reachable through the widget — the bound labels either
        side inset the track enough — so the placement is checked directly
        rather than through a scenario that can't fail."""
        from flograph.ui.controls import SliderControl
        place = SliderControl._readout_left
        assert place(centre=100, label_width=40, row_width=200) == 80
        assert place(centre=2, label_width=40, row_width=200) == 0
        assert place(centre=198, label_width=40, row_width=200) == 160

    def test_the_readout_is_inside_the_strip_across_the_range(self, qtbot):
        widget = build_control("slider")
        qtbot.addWidget(widget)
        widget.sync({"minimum": 0, "maximum": 1000000, "step": 1,
                     "value": 0})
        widget.resize(200, 70)
        widget.show()
        qtbot.waitExposed(widget)
        for value in (0, widget._slider.maximum() // 2,
                      widget._slider.maximum()):
            widget._slider.setValue(value)
            assert widget._readout.x() >= 0
            assert (widget._readout.x() + widget._readout.width()
                    <= widget._readout_row.width())

    def test_number_is_an_integer_until_decimals_are_asked_for(self, qtbot):
        widget = build_control("number")
        qtbot.addWidget(widget)
        widget.sync({"minimum": 0, "maximum": 10, "value": 3})
        assert widget._read() == 3 and isinstance(widget._read(), int)
        widget.sync({"minimum": 0, "maximum": 10, "value": 3, "decimals": 2})
        assert isinstance(widget._read(), float)

    def test_number_prefix_and_suffix_are_display_only(self, qtbot):
        widget = build_control("number")
        qtbot.addWidget(widget)
        widget.sync({"minimum": 0, "maximum": 100, "value": 40,
                     "prefix": "£", "suffix": "k"})
        assert widget._read() == 40

    def test_text_commits_on_leaving_the_box_not_per_keystroke(self, qtbot):
        widget = build_control("text")
        qtbot.addWidget(widget)
        widget.sync({"value": ""})
        fired = []
        widget.value_committed.connect(fired.append)
        qtbot.keyClicks(widget._edit, "abc")
        assert fired == []                   # still typing
        widget._edit.editingFinished.emit()
        assert fired == ["abc"]

    def test_text_swaps_to_a_box_when_multiline(self, qtbot):
        widget = build_control("text")
        qtbot.addWidget(widget)
        widget.sync({"value": "one", "multiline": True})
        assert widget._edit.isHidden() and not widget._box.isHidden()
        widget._box.setPlainText("two\nlines")
        assert widget._read() == "two\nlines"

    def test_date_shows_today_when_nothing_is_stored(self, qtbot):
        widget = build_control("date")
        qtbot.addWidget(widget)
        widget.sync({"value": ""})
        assert widget._read() == TODAY

    def test_date_honours_its_bounds(self, qtbot):
        widget = build_control("date")
        qtbot.addWidget(widget)
        widget.sync({"value": "2024-06-01", "minimum": "2024-01-01",
                     "maximum": "2024-12-31"})
        assert widget._edit.minimumDate() == QDate(2024, 1, 1)
        assert widget._edit.maximumDate() == QDate(2024, 12, 31)
        assert widget._read() == "2024-06-01"

    def test_widening_a_range_is_not_blocked_by_the_old_one(self, qtbot):
        """Qt rejects a minimum above the current maximum, so the range has
        to be opened up before the new bounds go in."""
        widget = build_control("date")
        qtbot.addWidget(widget)
        widget.sync({"minimum": "2020-01-01", "maximum": "2020-12-31"})
        widget.sync({"minimum": "2030-01-01", "maximum": "2030-12-31"})
        assert widget._edit.minimumDate() == QDate(2030, 1, 1)
        assert widget._edit.maximumDate() == QDate(2030, 12, 31)

    def test_a_junk_date_falls_back_rather_than_breaking(self, qtbot):
        widget = build_control("date")
        qtbot.addWidget(widget)
        widget.sync({"value": "yesterday-ish"})
        assert widget._read() == TODAY
        assert iso_to_qdate("yesterday-ish") is None

    def test_toggle_carries_its_own_label(self, qtbot):
        widget = build_control("toggle")
        qtbot.addWidget(widget)
        widget.sync({"text": "Include returns", "value": True})
        assert widget._check.text() == "Include returns"
        assert widget._read() is True

    def test_choice_lists_the_typed_options(self, qtbot):
        widget = build_control("choice")
        qtbot.addWidget(widget)
        widget.sync({"items": "north\nsouth", "value": "south"})
        assert widget._read() == "south"
        assert widget._combo.count() == 2

    def test_choice_prefers_upstream_options_over_the_typed_list(self, qtbot):
        widget = build_control("choice")
        qtbot.addWidget(widget)
        widget.sync({"items": "typed", "value": ""})
        widget.set_upstream({"options": ["live-a", "live-b"]})
        assert [widget._combo.itemText(i)
                for i in range(widget._combo.count())] == ["live-a", "live-b"]

    def test_choice_keeps_a_pick_that_left_the_list(self, qtbot):
        widget = build_control("choice")
        qtbot.addWidget(widget)
        widget.sync({"items": "a\nb", "value": "gone"})
        assert widget._read() == "gone"
        assert "not in list" in widget._combo.currentText()

    def test_choice_falls_back_to_the_typed_list_when_unwired(self, qtbot):
        widget = build_control("choice")
        qtbot.addWidget(widget)
        widget.sync({"items": "a\nb", "value": ""})
        widget.set_upstream({"options": ["live"]})
        widget.set_upstream({})
        assert [widget._combo.itemText(i)
                for i in range(widget._combo.count())] == ["a", "b"]


# ---------------------------------------------------------------- the flow


class TestRunning:
    def test_each_control_emits_what_its_widget_shows(self, qtbot, window):
        nodes = {kind: add_control(window, kind) for kind in CONTROL_TYPES}
        window.graph.set_param(nodes["text"].id, "value", "hello")
        window.graph.set_param(nodes["toggle"].id, "value", True)
        window.graph.set_param(nodes["choice"].id, "items", "north\nsouth")
        run_all(qtbot, window)
        assert output(window, nodes["slider"]) == 50
        assert output(window, nodes["text"]) == "hello"
        assert output(window, nodes["toggle"]) is True
        assert output(window, nodes["date"]) == TODAY
        assert output(window, nodes["choice"]) == "north"

    def test_the_emitted_value_matches_the_card(self, qtbot, window):
        """A dashboard that shows one number and sends another is worse than
        no dashboard."""
        for kind in CONTROL_TYPES:
            node = add_control(window, kind)
            if kind == "choice":
                window.graph.set_param(node.id, "items", "north\nsouth")
            run_all(qtbot, window)
            widget = window.scene.node_items[node.id]._control_widget
            assert output(window, node) == widget._read(), kind

    def test_moving_a_control_reruns_what_it_feeds(self, qtbot, window):
        control = add_control(window, "number", value=2,
                              minimum=0, maximum=10)
        downstream = window.graph.add_node(window.registry.instantiate(
            "flograph.scripting.python_script"))
        window.undo_stack.push(SetCodeCommand(
            window.graph, downstream.id,
            'NODE = {"label": "Double", "category": "Test",\n'
            '        "inputs": [("in1", "any")],\n'
            '        "outputs": [("out1", "any")]}\n'
            "def run(ctx, in1):\n    return in1 * 2\n"))
        window.graph.connect(control.id, "value", downstream.id, "in1")
        run_all(qtbot, window)
        assert output(window, downstream, "out1") == 4

        item = window.scene.node_items[control.id]
        with qtbot.waitSignal(window.engine.run_finished, timeout=20000):
            item._control_widget._spin.setValue(5)
        assert output(window, downstream, "out1") == 10

    def test_a_control_that_did_not_change_still_settles(self, qtbot, window):
        """Re-committing the same value must not push an undo step, but must
        still leave the graph runnable."""
        control = add_control(window, "toggle", value=True)
        item = window.scene.node_items[control.id]
        before = window.undo_stack.index()
        item._on_control_committed(True)
        assert window.undo_stack.index() == before


# ------------------------------------------------------------- chaining


class TestChaining:
    def _standalone_slicer(self, window, values, selected):
        node = window.graph.add_node(
            window.registry.instantiate("flograph.viz.slicer"))
        window.graph.set_param(node.id, "values", values)
        window.graph.set_param(node.id, "selected", selected)
        return node

    def test_a_slicer_with_no_table_is_a_value_picker(self, qtbot, window):
        """ideas.md 16: the table input is optional, so a slicer can stand
        on its own typed-in list with no data behind it."""
        slicer = self._standalone_slicer(
            window, "alpha\nbeta\ngamma", '["beta"]')
        run_all(qtbot, window)
        table = output(window, slicer, "table")
        assert list(table["value"]) == ["beta"]
        assert output(window, slicer, "selected") == ["beta"]

    def test_a_standalone_slicer_needs_no_run_to_show_its_values(
            self, window):
        """It holds its own list, so demanding a run first would be asking
        for data it doesn't have."""
        slicer = self._standalone_slicer(window, "alpha\nbeta", "")
        from flograph.engine.introspect import slicer_options
        assert slicer_options(window.graph, window.engine.cache,
                              slicer.id) == ["alpha", "beta"]

    def test_nothing_ticked_passes_every_value(self, qtbot, window):
        slicer = self._standalone_slicer(window, "alpha\nbeta", "")
        run_all(qtbot, window)
        assert list(output(window, slicer, "table")["value"]) \
            == ["alpha", "beta"]

    def test_the_standalone_column_is_named_after_the_column_param(
            self, qtbot, window):
        slicer = self._standalone_slicer(window, "alpha", "")
        window.graph.set_param(slicer.id, "column", "region")
        run_all(qtbot, window)
        assert list(output(window, slicer, "table").columns) == ["region"]

    def test_a_slicer_selection_can_drive_a_choice_s_options(
            self, qtbot, window):
        """ideas.md 5 + 16: one picker feeding the next is the whole point
        of the selected output."""
        slicer = self._standalone_slicer(
            window, "alpha\nbeta\ngamma", '["beta", "gamma"]')
        choice = add_control(window, "choice", items="ignored")
        window.graph.connect(slicer.id, "selected", choice.id, "options")
        run_all(qtbot, window)
        combo = window.scene.node_items[choice.id]._control_widget._combo
        assert [combo.itemText(i) for i in range(combo.count())] \
            == ["beta", "gamma"]
        assert output(window, choice) == "beta"

    def test_a_connected_slicer_still_filters_and_reports(self, qtbot,
                                                          window):
        table = window.graph.add_node(
            window.registry.instantiate("flograph.io.table"))
        window.graph.set_param(table.id, "data", json.dumps({
            "version": 2,
            "columns": [{"name": "region", "type": "auto"}],
            "rows": [["north"], ["south"], ["north"]]}))
        slicer = window.graph.add_node(
            window.registry.instantiate("flograph.viz.slicer"))
        window.graph.set_param(slicer.id, "column", "region")
        window.graph.set_param(slicer.id, "selected", '["north"]')
        window.graph.connect(table.id, "table", slicer.id, "table")
        run_all(qtbot, window)
        assert len(output(window, slicer, "table")) == 2
        assert output(window, slicer, "selected") == ["north"]

    def test_a_choice_can_be_fed_a_column_of_a_table(self, qtbot, window):
        table = window.graph.add_node(
            window.registry.instantiate("flograph.io.table"))
        window.graph.set_param(table.id, "data", json.dumps({
            "version": 2,
            "columns": [{"name": "x", "type": "auto"},
                        {"name": "region", "type": "auto"}],
            "rows": [["1", "north"], ["2", "south"]]}))
        choice = add_control(window, "choice", column="region")
        window.graph.connect(table.id, "table", choice.id, "options")
        run_all(qtbot, window)
        combo = window.scene.node_items[choice.id]._control_widget._combo
        assert [combo.itemText(i) for i in range(combo.count())] \
            == ["north", "south"]


class TestWiredSettings:
    """A control configures itself from the data, not just from constants
    somebody typed: bounds, options and labels can all come down a wire."""

    def _column(self, window, rows, name="n"):
        """A Table node emitting one column, to wire into a control."""
        node = window.graph.add_node(
            window.registry.instantiate("flograph.io.table"))
        window.graph.set_param(node.id, "data", json.dumps({
            "version": 2,
            "columns": [{"name": name, "type": "auto"}],
            "rows": [[str(v)] for v in rows]}))
        return node

    def test_reduce_bound_takes_the_right_end(self):
        from flograph.core.controls import reduce_bound
        series = pd.Series([5, 1, 9, None])
        assert reduce_bound(series, high=False) == 1
        assert reduce_bound(series, high=True) == 9
        assert reduce_bound(pd.DataFrame({"a": [3, 7]}), high=True) == 7
        assert reduce_bound([2, 8], high=False) == 2
        assert reduce_bound(4, high=True) == 4
        assert reduce_bound(None, high=True) is None

    def test_reduce_bound_of_nothing_usable_is_none(self):
        from flograph.core.controls import reduce_bound
        assert reduce_bound(pd.Series([], dtype=float), high=True) is None
        assert reduce_bound(pd.DataFrame(), high=True) is None

    def test_as_iso_date_takes_what_a_date_column_yields(self):
        from flograph.core.controls import as_iso_date
        assert as_iso_date(pd.Timestamp("2024-02-03")) == "2024-02-03"
        assert as_iso_date(datetime.date(2024, 2, 3)) == "2024-02-03"
        assert as_iso_date("2024-02-03") == "2024-02-03"
        assert as_iso_date("rubbish") == ""
        assert as_iso_date(None) == ""

    def test_clamp_keeps_a_value_in_range(self):
        from flograph.core.controls import clamp
        assert clamp(5, 0, 10) == 5
        assert clamp(-3, 0, 10) == 0
        assert clamp(30, 0, 10) == 10
        assert clamp(5, 10, 0) == 10   # inverted bounds don't explode

    def test_a_wired_bound_beats_the_typed_one(self, qtbot):
        widget = build_control("slider")
        qtbot.addWidget(widget)
        widget.sync({"minimum": 0, "maximum": 100, "step": 1, "value": 50})
        widget.set_upstream({"minimum": 200, "maximum": 300})
        widget._slider.setValue(0)
        assert widget._read() == 200

    def test_unwiring_a_bound_restores_the_typed_one(self, qtbot):
        widget = build_control("slider")
        qtbot.addWidget(widget)
        widget.sync({"minimum": 0, "maximum": 100, "step": 1, "value": 50})
        widget.set_upstream({"minimum": 200, "maximum": 300})
        widget.set_upstream({})
        widget._slider.setValue(0)
        assert widget._read() == 0

    def test_the_value_is_pulled_inside_new_bounds(self, qtbot):
        """What makes a wired bound double as a default: an untouched
        control lands somewhere the data actually reaches."""
        widget = build_control("slider")
        qtbot.addWidget(widget)
        widget.sync({"minimum": 0, "maximum": 100, "step": 1, "value": 5})
        widget.set_upstream({"minimum": 40, "maximum": 60})
        assert widget._read() == 40

    def test_a_date_picker_takes_its_calendar_from_a_column(self, qtbot):
        widget = build_control("date")
        qtbot.addWidget(widget)
        widget.sync({"value": ""})
        widget.set_upstream({"minimum": "2021-01-01",
                             "maximum": "2021-12-31"})
        assert widget._edit.minimumDate() == QDate(2021, 1, 1)
        assert widget._edit.maximumDate() == QDate(2021, 12, 31)
        # today is outside 2021, so it lands on the latest date there is
        assert widget._read() == "2021-12-31"

    def test_a_wired_placeholder_and_label(self, qtbot):
        text = build_control("text")
        qtbot.addWidget(text)
        text.sync({"placeholder": "typed"})
        text.set_upstream({"placeholder": "from the wire"})
        assert text._edit.placeholderText() == "from the wire"

        toggle = build_control("toggle")
        qtbot.addWidget(toggle)
        toggle.sync({"text": "typed"})
        toggle.set_upstream({"text": "from the wire"})
        assert toggle._check.text() == "from the wire"

    def test_bounds_reach_the_card_after_a_run(self, qtbot, window):
        control = add_control(window, "slider", minimum=0, maximum=10,
                              value=0)
        column = self._column(window, [100, 250, 175])
        window.graph.connect(column.id, "table", control.id, "maximum")
        run_all(qtbot, window)
        widget = window.scene.node_items[control.id]._control_widget
        assert widget._slider.maximum() == 250   # 0..250 in steps of 1

    def test_the_node_clamps_the_same_way_the_card_does(self, qtbot, window):
        control = add_control(window, "slider", minimum=0, maximum=1000,
                              value=900)
        column = self._column(window, [10, 40, 25])
        window.graph.connect(column.id, "table", control.id, "maximum")
        run_all(qtbot, window)
        widget = window.scene.node_items[control.id]._control_widget
        assert output(window, control) == 40
        assert output(window, control) == widget._read()

    def test_a_date_control_clamps_to_its_wired_range(self, qtbot, window):
        control = add_control(window, "date", value="2019-01-01")
        column = self._column(window, ["2021-06-01", "2021-08-01"], name="d")
        window.graph.connect(column.id, "table", control.id, "minimum")
        run_all(qtbot, window)
        assert output(window, control) == "2021-06-01"

    def test_an_unreadable_bound_leaves_the_control_usable(self, qtbot,
                                                           window):
        """A bound that can't be read is not a reason to break the card."""
        control = add_control(window, "slider", minimum=0, maximum=10,
                              value=5)
        column = self._column(window, ["not", "numbers"], name="junk")
        window.graph.connect(column.id, "table", control.id, "maximum")
        run_all(qtbot, window)
        assert output(window, control) == 5

    def test_a_slider_can_drive_another_control_s_bound(self, qtbot, window):
        """Controls chain on their settings, not only on their values."""
        driver = add_control(window, "number", value=42,
                             minimum=0, maximum=100)
        driven = add_control(window, "slider", minimum=0, maximum=10, value=0)
        window.graph.connect(driver.id, "value", driven.id, "maximum")
        run_all(qtbot, window)
        widget = window.scene.node_items[driven.id]._control_widget
        assert widget._slider.maximum() == 42

    def test_a_control_tile_gets_wired_settings_too(self, qtbot, window):
        from flograph.ui.dashboard.tile_item import default_tile_size
        control = add_control(window, "slider", minimum=0, maximum=10,
                              value=0)
        column = self._column(window, [5, 500])
        window.graph.connect(column.id, "table", control.id, "maximum")
        window.undo_stack.push(
            AddPageCommand(window.graph, Page(id="p1", title="Board")))
        width, height = default_tile_size(control)
        window.undo_stack.push(AddTileCommand(window.graph, "p1", Tile(
            id="t1", node_id=control.id, port=None,
            rect=(0.0, 0.0, width, height))))
        run_all(qtbot, window)
        item = window._dashboard_pages["p1"].scene.tile_items["t1"]
        item.refresh_content()
        assert item._control_widget._slider.maximum() == 500


# ------------------------------------------------------ on a dashboard page


class TestControlTiles:
    def _tile(self, window, node, page_id="p1", tile_id="t1"):
        from flograph.ui.dashboard.tile_item import default_tile_size
        window.undo_stack.push(
            AddPageCommand(window.graph, Page(id=page_id, title="Board")))
        width, height = default_tile_size(node)
        tile = Tile(id=tile_id, node_id=node.id, port=None,
                    rect=(0.0, 0.0, width, height))
        window.undo_stack.push(AddTileCommand(window.graph, page_id, tile))
        page = window._dashboard_pages[page_id]
        return page, page.scene.tile_items[tile_id]

    def test_every_control_can_be_placed_on_a_page(self, window):
        from flograph.ui.dashboard.tile_item import is_tile_able
        for kind in CONTROL_TYPES:
            assert is_tile_able(add_control(window, kind)), kind

    def test_a_control_tile_builds_the_same_widget(self, window):
        node = add_control(window, "slider", value=25)
        _page, item = self._tile(window, node)
        assert item._control_widget is not None
        assert item._control_widget._read() == 25

    def test_a_tile_lands_big_enough_for_its_shape(self, window):
        from flograph.ui.dashboard.tile_item import TITLE_H, default_tile_size
        node = add_control(window, "toggle")
        width, height = default_tile_size(node)
        assert (width, height) == (control_size("toggle")[0],
                                   control_size("toggle")[1] + TITLE_H)

    def test_moving_a_tile_control_writes_the_param(self, window):
        node = add_control(window, "slider", minimum=0, maximum=100, value=0)
        _page, item = self._tile(window, node)
        item._control_widget._slider.setValue(60)
        assert node.params["value"] == 60

    def test_a_tile_edit_is_one_undo_step(self, window):
        node = add_control(window, "number", value=1, minimum=0, maximum=9)
        _page, item = self._tile(window, node)
        before = window.undo_stack.index()
        item._control_widget._spin.setValue(4)
        assert window.undo_stack.index() == before + 1
        window.undo_stack.undo()
        assert node.params["value"] == 1

    def test_a_tile_edit_reruns_the_page(self, qtbot, window):
        node = add_control(window, "toggle", value=False)
        _page, item = self._tile(window, node)
        with qtbot.waitSignal(window.engine.run_finished, timeout=20000):
            item._control_widget._check.setChecked(True)
        assert output(window, node) is True

    def test_the_card_and_the_tile_stay_in_step(self, window):
        """Same node, two hosts: an edit in one has to show in the other."""
        node = add_control(window, "text", value="start")
        _page, tile = self._tile(window, node)
        card = window.scene.node_items[node.id]
        tile._control_widget._edit.setText("typed on the dashboard")
        tile._control_widget._edit.editingFinished.emit()
        card.on_params_changed()
        assert card._control_widget._read() == "typed on the dashboard"

    def test_a_control_tile_is_never_marked_stale(self, window):
        """It shows the value being set, not a rendered output."""
        node = add_control(window, "slider")
        _page, item = self._tile(window, node)
        assert node.dirty and not item._is_stale()

    def test_a_control_tile_shows_no_run_prompt(self, window):
        node = add_control(window, "date")
        _page, item = self._tile(window, node)
        assert item._placeholder.isHidden()

    def test_a_choice_tile_picks_up_upstream_options(self, qtbot, window):
        slicer = window.graph.add_node(
            window.registry.instantiate("flograph.viz.slicer"))
        window.graph.set_param(slicer.id, "values", "one\ntwo\nthree")
        choice = add_control(window, "choice")
        window.graph.connect(slicer.id, "selected", choice.id, "options")
        _page, item = self._tile(window, choice)
        run_all(qtbot, window)
        item.refresh_content()
        combo = item._control_widget._combo
        assert [combo.itemText(i) for i in range(combo.count())] \
            == ["one", "three", "two"]

    def test_a_control_tile_can_be_maximized(self, window):
        node = add_control(window, "slider")
        _page, item = self._tile(window, node)
        assert item.can_fullscreen()


# --------------------------------------------------------------- persistence


class TestPersistence:
    def test_a_control_value_saves_and_reloads(self, tmp_path, window,
                                               registry):
        from flograph.core import serialization
        node = add_control(window, "slider", value=77)
        path = tmp_path / "p.flograph"
        serialization.save(window.graph, path)
        reloaded = serialization.load(path, registry)
        assert reloaded.nodes[node.id].params["value"] == 77

    def test_a_reloaded_control_still_knows_its_shape(self, tmp_path, window,
                                                      registry):
        from flograph.core import serialization
        node = add_control(window, "date")
        graph = serialization.graph_from_dict(
            serialization.graph_to_dict(window.graph), registry)
        assert graph.nodes[node.id].spec.control == "date"


class TestDateParam:
    def test_the_properties_panel_offers_a_calendar(self, qtbot, env,
                                                    registry):
        from PySide6.QtWidgets import QDateEdit

        from flograph.ui.properties.params_panel import ParamsPanel
        graph, stack, _ = env
        node = add_control(graph, "date", registry, value="2024-05-06")
        panel = ParamsPanel(graph, stack)
        qtbot.addWidget(panel)
        panel.set_node(node.id)
        edit = panel.findChild(QDateEdit, "param_value")
        assert edit is not None
        assert edit.date() == QDate(2024, 5, 6)

    def test_picking_a_date_commits_it_as_iso(self, qtbot, env, registry):
        from PySide6.QtWidgets import QDateEdit

        from flograph.ui.properties.params_panel import ParamsPanel
        graph, stack, _ = env
        node = add_control(graph, "date", registry)
        panel = ParamsPanel(graph, stack)
        qtbot.addWidget(panel)
        panel.set_node(node.id)
        panel.findChild(QDateEdit, "param_value").setDate(QDate(2031, 2, 3))
        assert node.params["value"] == "2031-02-03"
