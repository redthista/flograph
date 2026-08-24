"""The Gantt Chart node: its spec, and which parts of the picture each
param actually turns on."""
import re

import pandas as pd
import pytest

from flograph.core import NodeRegistry
from flograph.core.datatypes import PortType
from flograph.core.script import compile_run

from tests.conftest import FakeContext

pytest.importorskip("plotly")

TYPE_ID = "flograph.viz.gantt"


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def tasks():
    return pd.DataFrame({
        "id": ["A", "B", "M", "C"],
        "task": ["Kickoff", "Build", "Signed off", "Ship"],
        "phase": ["Discovery", "Delivery", "Delivery", "Delivery"],
        "owner": ["Ada", "Ada", "Grace", "Grace"],
        "days": [2, 5, 0, 3],
        "after": ["", "A", "B", "M"],
        "pct": [100, 40, 0, 0],
        "bs": ["2026-03-02", "2026-03-04", "2026-03-09", "2026-03-09"],
        "bf": ["2026-03-04", "2026-03-09", "2026-03-09", "2026-03-11"],
    })


def gantt(registry, tasks, **params):
    spec = registry.get(TYPE_ID)
    values = spec.default_params()
    values.update({"task": "task", "task_id": "id", "duration": "days",
                   "depends_on": "after", "project_start": "2026-03-02"})
    values.update(params)
    run = compile_run(spec.source, "test-gantt")
    ctx = FakeContext(params=values)
    return run(ctx, table=tasks), ctx


def names(figure):
    return [trace.name for trace in figure.data]


class TestSpec:
    def test_it_is_registered_with_a_table_in_and_a_figure_and_schedule_out(
            self, registry):
        spec = registry.get(TYPE_ID)
        assert [p.name for p in spec.inputs] == ["table"]
        assert [p.name for p in spec.outputs] == ["figure", "schedule",
                                                  "html"]
        # An "object" port, not a "figure" one: "figure" means matplotlib.
        assert spec.outputs[0].type == PortType.OBJECT
        assert spec.outputs[1].type == PortType.DATAFRAME
        assert spec.outputs[2].type == PortType.STRING
        assert spec.inputs[0].type == PortType.DATAFRAME

    def test_it_carries_the_webview_card_so_the_chart_can_be_panned(
            self, registry):
        assert registry.get(TYPE_ID).card == "webview"
        assert registry.get(TYPE_ID).exclusive is False

    def test_every_param_the_node_reads_exists(self, registry):
        spec = registry.get(TYPE_ID)
        for name in ("task", "task_id", "duration", "duration_unit",
                     "depends_on", "start", "finish", "project_start",
                     "calendar", "group", "color", "progress",
                     "show_baseline", "baseline_start", "baseline_finish",
                     "sort", "show_dependencies", "show_today", "emit_html",
                     "title", "width", "height", "scale"):
            assert spec.param(name) is not None, name

    def test_the_zoom_is_cosmetic_so_it_never_replots(self, registry):
        assert registry.get(TYPE_ID).param("scale").cosmetic

    def test_the_baseline_columns_only_show_once_baselines_are_on(
            self, registry):
        spec = registry.get(TYPE_ID)
        off = {"show_baseline": False}
        assert not spec.param("baseline_start").visible_for(off)
        on = {"show_baseline": True}
        assert spec.param("baseline_start").visible_for(on)


class TestOutputs:
    def test_it_returns_both_a_figure_and_the_schedule_it_computed(
            self, registry, tasks):
        out, _ = gantt(registry, tasks)
        assert out["figure"].__class__.__module__.startswith("plotly")
        schedule = out["schedule"]
        assert list(schedule["task"]) == list(tasks["task"])
        assert [str(d.date()) for d in schedule["start"]] == [
            "2026-03-02", "2026-03-04", "2026-03-09", "2026-03-09"]

    def test_the_colour_key_does_not_leak_into_the_schedule(
            self, registry, tasks):
        out, _ = gantt(registry, tasks, group="phase")
        assert not [c for c in out["schedule"].columns if c.startswith("_")]

    def test_it_logs_the_span_it_charted(self, registry, tasks):
        _, ctx = gantt(registry, tasks)
        assert ctx.logs == ["4 task(s), 02 Mar 2026 to 12 Mar 2026"]


class TestWhatEachParamDraws:
    def test_a_plain_chart_is_bars_milestones_and_links(self, registry, tasks):
        out, _ = gantt(registry, tasks)
        assert names(out["figure"]) == ["task", "milestone", "depends on",
                                        "depends on"]

    def test_grouping_gives_one_trace_per_phase_and_header_rows(
            self, registry, tasks):
        out, _ = gantt(registry, tasks, group="phase")
        figure = out["figure"]
        assert "Discovery" in names(figure) and "Delivery" in names(figure)
        ticks = list(figure.layout.yaxis.ticktext)
        assert "<b>Discovery</b>" in ticks
        assert any(t.endswith("Kickoff") and t != "Kickoff" for t in ticks)

    def test_colour_by_can_use_a_column_the_schedule_does_not_carry(
            self, registry, tasks):
        out, _ = gantt(registry, tasks, color="owner")
        assert "Ada" in names(out["figure"])
        assert "Grace" in names(out["figure"])

    def test_progress_adds_the_shaded_bar_only_when_asked_for(
            self, registry, tasks):
        assert "complete" not in names(gantt(registry, tasks)[0]["figure"])
        out, _ = gantt(registry, tasks, progress="pct")
        assert "complete" in names(out["figure"])

    def test_baselines_appear_only_when_the_switch_is_on(self, registry,
                                                         tasks):
        off, _ = gantt(registry, tasks, baseline_start="bs",
                       baseline_finish="bf")
        assert "baseline" not in names(off["figure"])
        assert "baseline_start" not in off["schedule"].columns
        on, _ = gantt(registry, tasks, show_baseline=True,
                      baseline_start="bs", baseline_finish="bf")
        assert "baseline" in names(on["figure"])

    def test_a_milestone_baseline_is_a_marker_a_zero_width_bar_would_vanish(
            self, registry, tasks):
        out, _ = gantt(registry, tasks, show_baseline=True,
                       baseline_start="bs", baseline_finish="bf")
        marks = [t for t in out["figure"].data
                 if t.name == "baseline" and t.type == "scatter"]
        assert len(marks) == 1 and len(marks[0].x) == 1
        bars = [t for t in out["figure"].data
                if t.name == "baseline" and t.type == "bar"]
        assert len(bars[0].y) == 3

    def test_dependencies_can_be_turned_off(self, registry, tasks):
        out, _ = gantt(registry, tasks, show_dependencies=False)
        assert "depends on" not in names(out["figure"])

    def test_a_zero_duration_row_is_a_diamond_not_a_bar(self, registry, tasks):
        out, _ = gantt(registry, tasks)
        milestone = [t for t in out["figure"].data if t.name == "milestone"][0]
        assert len(milestone.x) == 1
        bars = [t for t in out["figure"].data if t.type == "bar"]
        assert sum(len(t.y) for t in bars) == 3

    def test_the_today_line_is_a_shape_that_can_be_turned_off(
            self, registry, tasks):
        today = pd.Timestamp.now().normalize()
        tasks = tasks.assign(days=[2, 5, 0, 3])
        yesterday = str((today - pd.Timedelta(days=1)).date())
        out, _ = gantt(registry, tasks, project_start=yesterday)
        assert any(s.line.dash == "dash" for s in out["figure"].layout.shapes)
        off, _ = gantt(registry, tasks, show_today=False,
                       project_start=yesterday)
        assert not [s for s in off["figure"].layout.shapes
                    if s.line.dash == "dash"]

    def test_sorting_by_start_reorders_the_rows(self, registry, tasks):
        shuffled = tasks.iloc[[3, 1, 2, 0]].reset_index(drop=True)
        assert list(gantt(registry, shuffled)[0]["schedule"]["task"]) == [
            "Ship", "Build", "Signed off", "Kickoff"]
        out, _ = gantt(registry, shuffled, sort="start date")
        starts = list(out["schedule"]["start"])
        assert starts == sorted(starts)
        assert list(out["schedule"]["task"])[:2] == ["Kickoff", "Build"]

    def test_grouping_blocks_its_phases_whatever_the_sort(self, registry,
                                                          tasks):
        shuffled = tasks.iloc[[3, 0, 1, 2]].reset_index(drop=True)
        out, _ = gantt(registry, shuffled, group="phase", sort="start date")
        # Discovery holds only Kickoff, and it stays whole rather than being
        # broken up by the tasks that happen to start around it.
        assert list(out["schedule"]["group"]) == [
            "Delivery", "Delivery", "Delivery", "Discovery"]


class TestHtmlOutput:
    def test_it_is_empty_until_asked_for(self, registry, tasks):
        # ~4.5 MB a run, cached and saved to the side-car: not something to
        # produce for a chart nobody is exporting.
        out, ctx = gantt(registry, tasks)
        assert out["html"] == ""
        assert not [line for line in ctx.logs if "HTML" in line]

    def test_it_is_a_whole_page_with_plotly_js_inside_it(self, registry,
                                                         tasks):
        out, ctx = gantt(registry, tasks, emit_html=True,
                         title="Website Rebuild")
        html = out["html"]
        assert html.lstrip().startswith("<html>")
        assert "Website Rebuild" in html
        assert "Plotly.newPlot" in html
        assert any("MB, self-contained" in line for line in ctx.logs)

    def test_nothing_in_the_page_is_fetched_from_the_network(self, registry,
                                                             tasks):
        # The point of embedding plotly.js: the saved file has to open on a
        # machine with no internet, so no tag may reach out for anything.
        out, _ = gantt(registry, tasks, emit_html=True)
        assert not re.findall(r"<script[^>]*\ssrc=", out["html"])
        assert not re.findall(r"<link[^>]*\shref=", out["html"])


class TestErrors:
    def test_an_empty_table_says_there_is_nothing_to_chart(self, registry):
        empty = pd.DataFrame({"task": [], "days": [], "after": [],
                              "id": []})
        with pytest.raises(ValueError, match="no tasks to chart"):
            gantt(registry, empty)

    def test_a_colour_column_that_is_not_there_names_it(self, registry, tasks):
        with pytest.raises(ValueError, match="Color by column 'nope'"):
            gantt(registry, tasks, color="nope")
