"""The new input shapes: Date Range, Multi Choice, Time, Date & Time, Colour
and File. For each: the rules (core.controls), what the node emits, and that
the card writes what it shows."""
import datetime
import json

import pandas as pd
import pytest

from flograph.core import Graph, NodeRegistry, varlinks
from flograph.core.controls import (colour_value, date_range_values,
                                    datetime_value, multi_values, time_value)
from flograph.core.script import CONTROL_KINDS
from flograph.engine import ExecutionEngine
from flograph.ui.controls import CONTROL_SIZES, _CONTROLS, host_control

DAY = datetime.date(2026, 10, 14)


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def control(graph, registry, stem, **params):
    node = graph.add_node(registry.instantiate(f"flograph.input.{stem}"))
    for name, value in params.items():
        graph.set_param(node.id, name, value)
    return node


def outputs(qtbot, graph, node):
    engine = ExecutionEngine(graph)
    failures = {}
    engine.node_failed.connect(lambda nid, e: failures.update({nid: e.message}))
    with qtbot.waitSignal(engine.run_finished, timeout=8000):
        engine.run_all()
    return engine.cache.outputs_for(node.id), failures


def widget_for(qtbot, node):
    widget = host_control(node)
    qtbot.addWidget(widget)
    return widget


def test_every_kind_has_a_widget_and_a_size():
    assert set(_CONTROLS) == set(CONTROL_KINDS)
    assert set(CONTROL_SIZES) == set(CONTROL_KINDS)


class TestDateRange:
    def test_windows(self):
        assert date_range_values("last 7 days", today=DAY)[1:] == (
            "2026-10-08", "2026-10-14")
        assert date_range_values("last month", today=DAY)[1:] == (
            "2026-09-01", "2026-09-30")
        assert date_range_values("year to date", today=DAY)[1:] == (
            "2026-01-01", "2026-10-14")
        assert date_range_values(
            "whole range", "2025-01-01", "2025-06-30", today=DAY)[1:] == (
            "2025-01-01", "2025-06-30")

    def test_a_pair_is_custom_and_clamped(self):
        preset, start, end = date_range_values(
            '["2026-03-31", "2026-01-01"]', low="2026-02-01")
        assert (preset, start, end) == ("custom", "2026-02-01", "2026-03-31")

    def test_blank_is_the_last_30_days(self):
        assert date_range_values("", today=DAY)[0] == "last 30 days"

    def test_node_and_variables(self, qtbot, registry):
        graph = Graph()
        node = control(graph, registry, "date_range",
                       value='["2026-01-01", "2026-01-31"]', variable="period")
        out, _ = outputs(qtbot, graph, node)
        assert (out["start"], out["end"]) == ("2026-01-01", "2026-01-31")
        assert set(varlinks.provided_names(node)) == {
            "period", "period_start", "period_end"}

    def test_card_picks_a_window_or_pins_dates(self, qtbot, registry):
        graph = Graph()
        node = control(graph, registry, "date_range", value="this month")
        widget = widget_for(qtbot, node)
        seen = []
        widget.value_committed.connect(seen.append)
        widget._start.setDate(widget._start.date().addDays(-3))
        pair = json.loads(seen[-1])
        assert len(pair) == 2 and pair[0] <= pair[1]
        index = widget._preset.findData("year to date")
        widget._preset.setCurrentIndex(index)
        widget._preset.activated.emit(index)
        assert seen[-1] == "year to date"


class TestMultiChoice:
    def test_rules(self):
        options = ["north", "south", "east"]
        assert multi_values('["east", "north"]', options) == ["north", "east"]
        assert multi_values("", options) == options
        assert multi_values("", options, "nothing") == []

    def test_options_from_a_table(self, qtbot, registry):
        from flograph.core import NodeInstance, parse_spec
        source = NodeInstance.create(parse_spec(
            'NODE = {"label": "T", "category": "Test", "inputs": [],'
            ' "outputs": [("t", "dataframe")]}\n'
            "def run(ctx):\n"
            "    import pandas as pd\n"
            "    return {'t': pd.DataFrame({'r': ['b', 'a', 'b']})}\n",
            "test.t"))
        graph = Graph()
        graph.add_node(source)
        node = control(graph, registry, "multi_choice", value='["a"]')
        graph.connect(source.id, "t", node.id, "options")
        out, _ = outputs(qtbot, graph, node)
        assert out["value"] == ["a"]

    def test_chips_all_none(self, qtbot, registry):
        graph = Graph()
        node = control(graph, registry, "multi_choice", items="a\nb\nc",
                       value='["b"]')
        widget = widget_for(qtbot, node)
        assert [b.isChecked() for b in widget._buttons] == [False, True, False]
        seen = []
        widget.value_committed.connect(seen.append)
        widget._buttons[0].click()
        assert json.loads(seen[-1]) == ["a", "b"]
        widget._all.click()
        assert json.loads(seen[-1]) == ["a", "b", "c"]
        widget._none.click()
        assert json.loads(seen[-1]) == []

    def test_required_needs_a_tick(self, qtbot, registry):
        graph = Graph()
        node = control(graph, registry, "multi_choice", items="a", required=True)
        _out, failures = outputs(qtbot, graph, node)
        assert "required" in failures[node.id]


class TestTimeDateTimeColour:
    def test_time(self, qtbot, registry):
        assert time_value("9:5") == "09:05"
        assert time_value("25:00") == "00:00"
        graph = Graph()
        node = control(graph, registry, "time", value="17:30")
        widget = widget_for(qtbot, node)
        assert widget._read() == "17:30"

    def test_datetime(self, qtbot, registry):
        assert datetime_value("2026-10-14 08:15") == "2026-10-14T08:15"
        assert datetime_value("").endswith("T00:00")
        graph = Graph()
        node = control(graph, registry, "date_time", value="2026-10-14T08:15")
        widget = widget_for(qtbot, node)
        assert widget._read() == "2026-10-14T08:15"
        out, _ = outputs(qtbot, graph, node)
        assert pd.Timestamp(out["value"]) == pd.Timestamp("2026-10-14 08:15")

    def test_colour(self, qtbot, registry):
        assert colour_value("ABC") == "#aabbcc"
        assert colour_value("nope") == "#3b82f6"
        graph = Graph()
        node = control(graph, registry, "colour", swatches="#ff0000, #00ff00")
        widget = widget_for(qtbot, node)
        assert len(widget._preset_buttons) == 2
        seen = []
        widget.value_committed.connect(seen.append)
        widget._preset_buttons[1].click()
        assert seen == ["#00ff00"]


class TestFile:
    def test_must_exist(self, qtbot, registry, tmp_path):
        graph = Graph()
        node = control(graph, registry, "file_pick",
                       value=str(tmp_path / "missing.csv"))
        _out, failures = outputs(qtbot, graph, node)
        assert "does not exist" in failures[node.id]

    def test_an_existing_file_flows(self, qtbot, registry, tmp_path):
        path = tmp_path / "data.csv"
        path.write_text("a\n1\n")
        graph = Graph()
        node = control(graph, registry, "file_pick", value=str(path))
        out, _ = outputs(qtbot, graph, node)
        assert out["value"] == str(path)
        widget = widget_for(qtbot, node)
        assert widget._name.text() == "data.csv"

    def test_picking_commits(self, qtbot, registry, tmp_path, monkeypatch):
        from PySide6.QtWidgets import QFileDialog
        path = str(tmp_path / "x.csv")
        monkeypatch.setattr(QFileDialog, "getOpenFileName",
                            staticmethod(lambda *a, **k: (path, "")))
        graph = Graph()
        node = control(graph, registry, "file_pick")
        widget = widget_for(qtbot, node)
        seen = []
        widget.value_committed.connect(seen.append)
        widget._button.click()
        assert seen == [path]
