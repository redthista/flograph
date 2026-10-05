"""App facts in a report: `![[flograph.status]]`, `![[flograph.last_run]]`
and the rest — what a report can say about the app itself (core.app_facts).
"""
import time
from datetime import datetime

import pytest

from flograph.core import Graph, NodeRegistry, app_facts
from flograph.core.app_facts import (FACTS, AppState, LastRun, duration,
                                     fact_name, file_size, status, value)
from flograph.core.report_assist import Vocabulary, suggest
from flograph.core.report_lint import lint_report
from flograph.engine.cache import OutputCache
from flograph.ui.report.render import render_report


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


@pytest.fixture
def graph(registry):
    graph = Graph()
    for label in ("Source", "Chart"):
        node = graph.add_node(registry.instantiate("flograph.util.constant"))
        graph.set_label(node.id, label)
    return graph


def _clean(graph):
    for node in graph.nodes.values():
        graph.mark_clean(node.id)


NOW = datetime(2026, 10, 5, 14, 30).timestamp()
RUN = LastRun(finished=datetime(2026, 10, 5, 10, 42).timestamp(),
              seconds=3.24)


class TestTheName:
    def test_the_prefix(self):
        assert fact_name("flograph.status") == "status"
        assert fact_name("  Flograph.Last_Run ") == "last_run"
        assert fact_name("Sales") is None


class TestStatus:
    def test_never_run(self, graph):
        assert status(graph, AppState()).kind == "never"

    def test_up_to_date_says_when_and_how_long(self, graph):
        _clean(graph)
        got = status(graph, AppState(last_run=RUN), now=NOW)
        assert got.kind == "ok"
        assert got.text == "Up to date · last run 10:42 · took 3.2 s"

    def test_out_of_date(self, graph):
        _clean(graph)
        graph.mark_dirty(next(iter(graph.nodes)))
        got = status(graph, AppState(last_run=RUN), now=NOW)
        assert got.kind == "stale"
        assert got.text.startswith("1 node out of date")

    def test_running_wins(self, graph):
        assert status(graph, AppState(running=True)).kind == "running"

    def test_a_failed_node(self, graph):
        from flograph.core.node import NodeStatus
        graph.set_status(next(iter(graph.nodes)), NodeStatus.ERROR, "boom")
        assert status(graph, AppState(last_run=RUN)).text.startswith(
            "1 node failed")

    def test_a_button_is_never_out_of_date(self, graph, registry):
        graph.add_node(registry.instantiate("flograph.util.action_button"))
        _clean(graph)
        for node in graph.nodes.values():
            if not node.spec.outputs:
                graph.mark_dirty(node.id)
        assert status(graph, AppState(last_run=RUN)).kind == "ok"


class TestValues:
    def test_every_fact_answers(self, graph):
        for name in FACTS:
            assert value(name, graph, AppState(last_run=RUN), now=NOW)

    def test_an_unknown_fact_is_none(self, graph):
        assert value("nonsense", graph) is None

    def test_clock_and_date(self, graph):
        assert value("date", graph, now=NOW) == "5 October 2026"
        assert value("time", graph, now=NOW) == "14:30"
        assert value("last_run", graph, AppState(last_run=RUN),
                     now=NOW) == "10:42"
        yesterday = LastRun(finished=NOW - 86400, seconds=1)
        assert value("last_run", graph, AppState(last_run=yesterday),
                     now=NOW) == "4 Oct 14:30"

    def test_the_file(self, graph, tmp_path):
        path = tmp_path / "q3_final.flograph"
        path.write_bytes(b"x" * 2048)
        state = AppState(file_path=str(path))
        assert value("file", graph, state) == "q3_final.flograph"
        assert value("file_size", graph, state) == "2.0 KB"
        assert value("file", graph) == "not saved yet"

    def test_counts(self, graph):
        assert value("nodes", graph) == "2"
        assert value("out_of_date", graph) == "2"

    def test_no_graph_is_no_answer_not_a_crash(self):
        assert value("nodes", None) == app_facts.UNKNOWN
        assert status(None).text == app_facts.UNKNOWN

    @pytest.mark.parametrize("seconds, words", [
        (0.4, "0.4 s"), (42, "42 s"), (125, "2 min 5 s"), (3600, "1 h")])
    def test_durations(self, seconds, words):
        assert duration(seconds) == words

    def test_sizes(self):
        assert file_size(512) == "512 bytes"
        assert file_size(1.5 * 1024 * 1024) == "1.5 MB"


class TestTheProvider:
    def test_a_window_s_graph_reads_its_window(self, graph):
        app_facts.set_provider(graph, lambda: AppState(file_path="/x/a.flograph"))
        assert app_facts.state_for(graph).file_path == "/x/a.flograph"
        assert app_facts.state_for(Graph()).file_path == ""

    def test_a_provider_that_raises_is_no_provider(self, graph):
        def broken():
            raise RuntimeError("window closing")
        app_facts.set_provider(graph, broken)
        assert app_facts.state_for(graph) == AppState()


class TestRendering:
    def test_a_fact_renders_as_its_words(self, graph):
        app_facts.set_provider(graph, lambda: AppState(
            file_path="/tmp/my_flow_v2.flograph"))
        text = render_report("File: ![[flograph.file]]", graph,
                             OutputCache()).document.toPlainText()
        # the underscores are the name, not italics
        assert "File: my_flow_v2.flograph" in text

    def test_the_status_is_a_pill(self, graph):
        _clean(graph)
        app_facts.set_provider(graph, lambda: AppState(last_run=LastRun(
            finished=time.time(), seconds=1.0)))
        rendered = render_report("![[flograph.status]]", graph,
                                 OutputCache())
        assert "Up to date" in rendered.document.toPlainText()
        assert "#dcfce7" in rendered.document.toHtml()
        assert not rendered.problems

    def test_facts_print_too(self, graph):
        """The date a report was printed is worth printing — facts are not
        app-only; `apponly::` is how to make one so."""
        text = render_report("![[flograph.nodes]] nodes", graph,
                             OutputCache()).document.toPlainText()
        assert "2 nodes" in text

    def test_an_unknown_fact_says_so(self, graph):
        rendered = render_report("![[flograph.nope]]", graph, OutputCache())
        assert "No app fact called" in rendered.document.toPlainText()
        assert rendered.problems


class TestTheEditor:
    def test_lint_knows_the_facts(self):
        assert lint_report("![[flograph.status]]", labels={}) == []
        bad = lint_report("![[flograph.stauts]]", labels={})
        assert bad and "no app fact" in bad[0].message

    def test_autocomplete_offers_the_facts(self, graph):
        from flograph.ui.report.completion import page_vocabulary
        got = suggest("![[flograph.st", "", page_vocabulary(graph,
                                                             OutputCache()))
        assert [item.text for item in got.items][:1] == ["flograph.status"]
        got = suggest("![[flo", "", page_vocabulary(graph, OutputCache()))
        assert {item.text for item in got.items} >= {
            "flograph." + key for key in FACTS}

    def test_autocomplete_offers_apponly_at_a_line_start(self):
        got = suggest("app", "", Vocabulary())
        assert [item.text for item in got.items] == ["apponly:: "]
        assert not got.eager
        assert suggest("some app", "", Vocabulary()) is None
        assert suggest("ap", "", Vocabulary()) is None


class TestTheWindow:
    def test_the_window_tells_its_reports_about_itself(self, qtbot,
                                                       registry):
        from flograph.ui.mainwindow import MainWindow
        win = MainWindow(registry)
        win.confirm_close = False
        qtbot.addWidget(win)
        state = app_facts.state_for(win.graph)
        assert state.running is False and state.last_run is None
        win._project_path = "/somewhere/flow.flograph"
        assert app_facts.state_for(win.graph).file_path.endswith(
            "flow.flograph")
