"""The input controls' look-and-feel pass: required/help/accent on every
control, Text's pattern/mask/search-as-you-type, Choice's styles, (All) and
number output, Toggle as a switch, Date presets and "No date", Number's
thousands separator, Between's two-box editor, and type-to-filter in a
card dropdown.

What a node emits is asserted through the node's own run(); what the card
does through the widget, then the param it wrote.
"""
import datetime
import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QUndoStack

from flograph.core import Graph, NodeRegistry
from flograph.core import control_apply as ca
from flograph.core.controls import (ALL_LABEL, cast_choice, date_value,
                                    pattern_problem, preset_date)
from flograph.engine import ExecutionEngine
from flograph.ui.controls import accent_of, host_control


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def control(graph, registry, kind, **params):
    node = graph.add_node(registry.instantiate(f"flograph.input.{kind}"))
    for name, value in params.items():
        graph.set_param(node.id, name, value)
    return node


def run_once(qtbot, graph):
    engine = ExecutionEngine(graph)
    failures = {}
    engine.node_failed.connect(lambda nid, err: failures.update({nid: err.message}))
    with qtbot.waitSignal(engine.run_finished, timeout=8000):
        engine.run_all()
    return engine, failures


def widget_for(qtbot, node):
    widget = host_control(node)
    qtbot.addWidget(widget)
    return widget


class TestBehaviourParams:
    def test_required_blank_stops_the_run(self, qtbot, registry):
        graph = Graph()
        node = control(graph, registry, "text", required=True,
                       caption="Customer")
        engine, failures = run_once(qtbot, graph)
        assert "'Customer' is required" in failures[node.id]

    def test_required_filled_runs(self, qtbot, registry):
        graph = Graph()
        node = control(graph, registry, "text", required=True, value="ACME")
        engine, failures = run_once(qtbot, graph)
        assert not failures
        assert engine.cache.outputs_for(node.id)["value"] == "ACME"

    def test_required_never_applies_to_a_number(self, registry):
        graph = Graph()
        node = control(graph, registry, "number", required=True)
        assert ca.required_problem(node) is None

    def test_required_outlines_the_editor_and_marks_the_caption(
            self, qtbot, registry):
        graph = Graph()
        node = control(graph, registry, "text", required=True,
                       caption="Customer")
        widget = widget_for(qtbot, node)
        assert widget._edit.property("invalid") is True
        assert "*" in widget._caption.text()
        widget._edit.setText("ACME")
        assert widget._edit.property("invalid") is False

    def test_help_shows_a_mark_with_the_text(self, qtbot, registry):
        graph = Graph()
        node = control(graph, registry, "slider", help="Lowest price to show")
        widget = widget_for(qtbot, node)
        assert not widget._help.isHidden()
        assert widget._help.toolTip() == "Lowest price to show"

    def test_accent_is_read_and_a_bad_one_falls_back(self):
        assert accent_of({"accent": "#ff0000"}).name() == "#ff0000"
        assert accent_of({"accent": "nonsense"}).isValid()


class TestText:
    def test_pattern(self):
        assert pattern_problem("AB1234", r"[A-Z]{2}\d{4}") is None
        assert "does not match" in pattern_problem("ab", r"[A-Z]{2}\d{4}")
        assert pattern_problem("", r"\d+") is None
        assert pattern_problem("x", r"\d+", "digits only") == "digits only"
        assert "not a valid" in pattern_problem("x", "(")

    def test_a_mismatch_fails_the_node_saying_so(self, qtbot, registry):
        graph = Graph()
        node = control(graph, registry, "text", value="abc", pattern=r"\d+",
                       pattern_message="Digits only, please")
        _engine, failures = run_once(qtbot, graph)
        assert "Digits only, please" in failures[node.id]

    def test_mask_and_clear_button(self, qtbot, registry):
        from PySide6.QtWidgets import QLineEdit
        graph = Graph()
        node = control(graph, registry, "text", mask=True)
        widget = widget_for(qtbot, node)
        assert widget._edit.echoMode() == QLineEdit.Password
        assert widget._edit.isClearButtonEnabled()

    def test_search_as_you_type_commits_once_typing_pauses(
            self, qtbot, registry):
        graph = Graph()
        node = control(graph, registry, "text", live_typing=True)
        widget = widget_for(qtbot, node)
        seen = []
        widget.value_committed.connect(seen.append)
        widget._edit.setFocus()
        qtbot.keyClicks(widget._edit, "nor")
        assert seen == []
        qtbot.waitUntil(lambda: seen == ["nor"], timeout=2000)


class TestChoice:
    def test_all_option_emits_blank_and_comes_first(self, qtbot, registry):
        graph = Graph()
        node = control(graph, registry, "choice", items="north\nsouth",
                       all_option=True)
        engine, _ = run_once(qtbot, graph)
        assert engine.cache.outputs_for(node.id)["value"] == ""
        widget = widget_for(qtbot, node)
        assert widget._combo.itemText(0) == ALL_LABEL
        assert widget._read() == ""

    def test_number_output(self, qtbot, registry):
        assert cast_choice("2024", "number") == 2024
        assert cast_choice("0.5", "number") == 0.5
        assert cast_choice("north", "number") == "north"
        graph = Graph()
        node = control(graph, registry, "choice", items="2023\n2024",
                       value="2024", value_type="number")
        engine, _ = run_once(qtbot, graph)
        assert engine.cache.outputs_for(node.id)["value"] == 2024

    @pytest.mark.parametrize("style", ["buttons", "radio"])
    def test_buttons_and_radio_show_every_option_and_commit(
            self, qtbot, registry, style):
        graph = Graph()
        node = control(graph, registry, "choice", items="a\nb\nc",
                       value="b", style=style)
        widget = widget_for(qtbot, node)
        buttons = widget._group.buttons()
        assert [b.text() for b in buttons] == ["a", "b", "c"]
        assert buttons[1].isChecked() and widget._combo.isHidden()
        seen = []
        widget.value_committed.connect(seen.append)
        buttons[2].click()
        assert seen == ["c"]

    def test_type_to_filter_in_the_card_list(self, qtbot):
        from PySide6.QtGui import QStandardItem, QStandardItemModel
        from flograph.ui.canvas.popup_lift import CardPopupList
        model = QStandardItemModel()
        for name in ("North", "South", "Northeast", "West"):
            model.appendRow(QStandardItem(name))
        popup = CardPopupList()
        qtbot.addWidget(popup)
        popup.setModel(model)
        qtbot.keyClicks(popup, "nor")
        shown = [r for r in range(4) if not popup.isRowHidden(r)]
        assert shown == [0, 2]
        assert popup.currentIndex().row() == 0
        qtbot.keyClick(popup, Qt.Key_Backspace)
        assert popup.filter_text() == "no"
        qtbot.keyClick(popup, Qt.Key_Escape)
        assert popup.filter_text() == ""
        assert not any(popup.isRowHidden(r) for r in range(4))


class TestToggle:
    def test_switch_style(self, qtbot, registry):
        graph = Graph()
        node = control(graph, registry, "toggle", style="switch", value=False)
        widget = widget_for(qtbot, node)
        assert widget._check.isHidden() and not widget._switch.isHidden()
        seen = []
        widget.value_committed.connect(seen.append)
        widget._switch.click()
        assert seen == [True]


class TestDate:
    def test_presets(self):
        day = datetime.date(2026, 10, 14)       # a Wednesday
        assert preset_date("start of week", today=day) == "2026-10-12"
        assert preset_date("start of month", today=day) == "2026-10-01"
        assert preset_date("start of year", today=day) == "2026-01-01"
        assert preset_date("days ago", 30, today=day) == "2026-09-14"
        assert preset_date("fixed", today=day) == ""

    def test_a_picked_day_beats_the_preset(self):
        assert date_value("2025-05-05", "start of month") == "2025-05-05"
        assert date_value("", "start of month") == \
            datetime.date.today().replace(day=1).isoformat()

    def test_allow_blank(self, qtbot, registry):
        assert date_value("", allow_blank=True) == ""
        graph = Graph()
        node = control(graph, registry, "date", allow_blank=True)
        engine, _ = run_once(qtbot, graph)
        assert engine.cache.outputs_for(node.id)["value"] == ""
        widget = widget_for(qtbot, node)
        assert widget._read() == ""
        assert widget._edit.text() == "No date"

    def test_the_card_shows_the_preset_day(self, qtbot, registry):
        graph = Graph()
        node = control(graph, registry, "date", preset="start of year")
        widget = widget_for(qtbot, node)
        assert widget._read() == datetime.date.today().replace(
            month=1, day=1).isoformat()


class TestNumberAndBetween:
    def test_thousands_separator_is_display_only(self, qtbot, registry):
        graph = Graph()
        node = control(graph, registry, "number", thousands=True,
                       value=250000)
        widget = widget_for(qtbot, node)
        assert widget._spin.isGroupSeparatorShown()
        assert widget._read() == 250000

    def test_between_is_edited_as_two_boxes(self, qtbot, registry):
        from flograph.ui.properties.params_panel import ParamsPanel
        graph = Graph()
        node = control(graph, registry, "between_slider")
        panel = ParamsPanel(graph, QUndoStack())
        qtbot.addWidget(panel)
        panel.set_node(node.id)
        box = panel.tree.itemWidget(panel.rows()["Range"], 1)
        from PySide6.QtWidgets import QLineEdit
        low = box.findChild(QLineEdit, "param_value_low")
        high = box.findChild(QLineEdit, "param_value_high")
        low.setText("10")
        low.editingFinished.emit()
        assert json.loads(node.params["value"]) == [10, 100]
        high.setText("50")
        high.editingFinished.emit()
        assert json.loads(node.params["value"]) == [10, 50]
        low.setText("")
        high.setText("")
        high.editingFinished.emit()
        assert node.params["value"] == ""
