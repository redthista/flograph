"""Save Report: a node that writes a report page to a file when it runs.

Three halves. The derived report edges (core.reportlinks) that make the node
wait for, and re-run with, what its page embeds; the file naming
(engine.report_export) — tokens and the if-exists rule; and the round trip
through the window's exporter that does the render.
"""
from datetime import datetime

import pytest

from flograph.core import Graph, NodeInstance, parse_spec
from flograph.core.graph import Page
from flograph.core.node import NodeStatus
from flograph.core.reportlinks import link_id, report_problem
from flograph.engine import ExecutionEngine
from flograph.engine.cache_persistence import node_fingerprint
from flograph.engine.report_export import (
    ReportExportError, expand_name, target_path,
)

SAVE = "flograph.io.save_report"

ECHO = """
NODE = {"label": "Echo", "category": "Test", "inputs": [],
        "outputs": [("value", "any")]}
PARAMS = [{"name": "text", "type": "string", "default": ""}]
def run(ctx):
    return {"value": ctx.params["text"]}
"""


def echo(label, text=""):
    node = NodeInstance.create(parse_spec(ECHO, "test.echo"))
    node.label_override = label
    node.params["text"] = text
    return node


def wait_run(qtbot, engine, trigger, timeout=15000):
    with qtbot.waitSignal(engine.run_finished, timeout=timeout) as blocker:
        trigger()
    return blocker.args[0]


@pytest.fixture
def flow(registry):
    """An Echo called Headline, a report page embedding it, and a Save
    Report set to that page."""
    graph = Graph()
    headline = graph.add_node(echo("Headline", "Sales are **up**"))
    graph.add_page(Page(id="r1", title="Weekly", kind="report",
                        body="# Weekly\n\n![[Headline]]\n"))
    saver = graph.add_node(registry.instantiate(SAVE))
    graph.set_param(saver.id, "page", "r1")
    return graph, headline, saver


# ----------------------------------------------------------- the edges

class TestReportEdges:

    def test_an_embed_is_an_edge_into_the_saver(self, flow):
        graph, headline, saver = flow
        assert link_id(saver.id, headline.id) in graph.report_links
        assert graph.report_sources(saver.id) == [headline.id]
        assert saver.id in graph.downstream(headline.id)

    def test_no_page_no_edge_and_a_problem(self, registry):
        graph = Graph()
        saver = graph.add_node(registry.instantiate(SAVE))
        assert graph.report_links == {}
        assert "choose the report page" in report_problem(graph, saver.id)

    def test_editing_the_page_moves_the_edges_and_dirties_the_saver(self, flow):
        graph, headline, saver = flow
        other = graph.add_node(echo("Footer", "bye"))
        saver.dirty = False
        graph.set_page_body("r1", "![[Footer]]")
        assert graph.report_sources(saver.id) == [other.id]
        assert saver.dirty

    def test_renaming_a_node_follows_the_label(self, flow):
        graph, headline, saver = flow
        graph.set_label(headline.id, "Renamed")
        assert graph.report_sources(saver.id) == []
        graph.set_label(headline.id, "Headline")
        assert graph.report_sources(saver.id) == [headline.id]

    def test_a_page_embedding_something_downstream_is_a_loop(self, flow):
        graph, headline, saver = flow
        after = graph.add_node(echo("After"))
        graph.connect(saver.id, "flow", after.id, "flow")
        graph.set_page_body("r1", "![[After]]")
        assert graph.report_sources(saver.id) == []
        assert "loop" in report_problem(graph, saver.id)

    def test_the_page_text_is_in_the_fingerprint(self, flow):
        """Or a reopened project would restore the file path of a report
        whose text has since been rewritten, and not save it again."""
        graph, _headline, saver = flow
        before = node_fingerprint(graph, saver.id, {})
        graph.set_page_body("r1", "# Weekly\n\nnew words ![[Headline]]")
        assert node_fingerprint(graph, saver.id, {}) != before

    def test_a_dashboard_page_is_not_offered(self, registry):
        spec = registry.get(SAVE).param("page")
        assert spec.type == "page_ref" and spec.ref_kind == "report"


# -------------------------------------------------------- file names

NOW = datetime(2026, 9, 24, 14, 5, 9)


class TestNames:

    def test_tokens(self):
        assert (expand_name("out/{page} {date} {time}.html", "Q3: Sales", NOW)
                == "out/Q3- Sales 2026-09-24 14-05-09.html")
        assert expand_name("{datetime}", "", NOW) == "2026-09-24 14-05-09"

    def test_an_unknown_token_is_an_error(self):
        with pytest.raises(ReportExportError, match="{dte}"):
            expand_name("{dte}.html", "x", NOW)

    def test_the_extension_is_added(self, tmp_path):
        assert target_path(str(tmp_path / "r"), "PDF", "", "Overwrite",
                           NOW).endswith("r.pdf")
        assert target_path(str(tmp_path / "r.htm"), "HTML", "", "Overwrite",
                           NOW).endswith("r.htm")

    def test_if_exists(self, tmp_path):
        (tmp_path / "r.html").write_text("old")
        (tmp_path / "r (2).html").write_text("old")
        name = str(tmp_path / "r.html")
        assert target_path(name, "HTML", "", "Overwrite", NOW) == name
        assert target_path(name, "HTML", "", "Add a number",
                           NOW) == str(tmp_path / "r (3).html")
        with pytest.raises(ReportExportError, match="already exists"):
            target_path(name, "HTML", "", "Fail", NOW)

    def test_empty(self):
        with pytest.raises(ReportExportError, match="no file set"):
            target_path("  ", "HTML", "", "Overwrite", NOW)


# ------------------------------------------------------- the round trip

@pytest.fixture
def exporting(qapp, flow):
    from flograph.ui.report.node_export import ReportNodeExporter
    graph, headline, saver = flow
    engine = ExecutionEngine(graph)
    exporter = ReportNodeExporter(engine)
    yield graph, engine, headline, saver
    exporter.close()


class TestSaving:

    def test_saves_html_and_hands_it_on(self, qtbot, exporting, tmp_path):
        graph, engine, _headline, saver = exporting
        graph.set_param(saver.id, "path", str(tmp_path / "out" / "{page}"))
        graph.set_param(saver.id, "output_html", True)
        assert wait_run(qtbot, engine, engine.run_all)
        written = tmp_path / "out" / "Weekly.html"
        outputs = engine.cache.outputs_for(saver.id)
        assert outputs["path"] == str(written)
        text = written.read_text(encoding="utf-8")
        assert "Sales are" in text and "<title>Weekly</title>" in text
        assert outputs["html"] == text

    def test_saves_a_pdf(self, qtbot, exporting, tmp_path):
        graph, engine, _headline, saver = exporting
        graph.set_param(saver.id, "format", "PDF")
        graph.set_param(saver.id, "path", str(tmp_path / "weekly"))
        assert wait_run(qtbot, engine, engine.run_all)
        assert (tmp_path / "weekly.pdf").read_bytes()[:5] == b"%PDF-"
        assert engine.cache.outputs_for(saver.id)["html"] == ""

    def test_html_only_writes_nothing(self, qtbot, exporting, tmp_path):
        graph, engine, _headline, saver = exporting
        graph.set_param(saver.id, "output_html", True)
        assert wait_run(qtbot, engine, engine.run_all)
        outputs = engine.cache.outputs_for(saver.id)
        assert outputs["path"] == "" and "Sales are" in outputs["html"]

    def test_fail_if_it_exists(self, qtbot, exporting, tmp_path):
        graph, engine, _headline, saver = exporting
        (tmp_path / "r.html").write_text("keep me")
        graph.set_param(saver.id, "path", str(tmp_path / "r.html"))
        graph.set_param(saver.id, "if_exists", "Fail")
        assert not wait_run(qtbot, engine, engine.run_all)
        assert (tmp_path / "r.html").read_text() == "keep me"
        assert "already exists" in saver.status_message

    def test_a_changed_embed_saves_again(self, qtbot, exporting, tmp_path):
        graph, engine, headline, saver = exporting
        target = tmp_path / "r.html"
        graph.set_param(saver.id, "path", str(target))
        assert wait_run(qtbot, engine, engine.run_all)
        graph.set_param(headline.id, "text", "Sales are flat")
        assert saver.dirty
        assert wait_run(qtbot, engine, engine.run_all)
        assert "flat" in target.read_text(encoding="utf-8")


def test_headless_says_why(qtbot, flow, tmp_path):
    """No window, nothing registered: the node fails at once and says so,
    rather than waiting for a render nobody will do."""
    graph, _headline, saver = flow
    graph.set_param(saver.id, "path", str(tmp_path / "r.html"))
    engine = ExecutionEngine(graph)
    assert not wait_run(qtbot, engine, engine.run_all)
    assert "needs the flograph window" in saver.status_message


# ---------------------------------------------------- a report with errors

BOOM = """
NODE = {"label": "Boom", "category": "Test", "inputs": [],
        "outputs": [("value", "any")]}
PARAMS = [{"name": "fail", "type": "bool", "default": True}]
def run(ctx):
    if ctx.params["fail"]:
        raise RuntimeError("no data today")
    return {"value": "the chart"}
"""


def boom(label):
    node = NodeInstance.create(parse_spec(BOOM, "test.boom"))
    node.label_override = label
    return node


class TestErrors:

    def test_a_failed_embed_is_not_saved(self, qtbot, exporting, tmp_path):
        graph, engine, _headline, saver = exporting
        graph.add_node(boom("Chart"))
        graph.set_page_body("r1", "![[Headline]]\n\n![[Chart]]")
        graph.set_param(saver.id, "path", str(tmp_path / "r.html"))
        assert not wait_run(qtbot, engine, engine.run_all)
        assert not (tmp_path / "r.html").exists()
        # taken down quietly with it, like anything below a failure
        assert saver.status == NodeStatus.IDLE and saver.dirty

    def test_an_embed_of_nothing_is_not_saved(self, qtbot, exporting,
                                              tmp_path):
        graph, engine, _headline, saver = exporting
        graph.set_page_body("r1", "![[Headline]]\n\n![[Typo]]")
        graph.set_param(saver.id, "path", str(tmp_path / "r.html"))
        assert not wait_run(qtbot, engine, engine.run_all)
        assert not (tmp_path / "r.html").exists()
        assert "Typo" in saver.status_message
        assert "Save anyway" in saver.status_message

    def test_save_anyway_saves_round_a_failure(self, qtbot, exporting,
                                               tmp_path):
        """The chart fails in the same run: the saver is not taken down
        with it, and the file has everything else in it."""
        graph, engine, _headline, saver = exporting
        graph.add_node(boom("Chart"))
        graph.set_page_body("r1", "![[Headline]]\n\n![[Chart]]")
        graph.set_param(saver.id, "path", str(tmp_path / "r.html"))
        graph.set_param(saver.id, "if_errors", "Save anyway")
        wait_run(qtbot, engine, engine.run_all)
        assert "Sales are" in (tmp_path / "r.html").read_text(encoding="utf-8")
        assert engine.cache.outputs_for(saver.id)["path"]

    def test_a_failure_with_an_old_output_is_not_saved(self, qtbot,
                                                        exporting, tmp_path):
        """It ran once, then failed: its old chart is still cached, which
        must not pass for this run's."""
        graph, engine, _headline, saver = exporting
        chart = graph.add_node(boom("Chart"))
        graph.set_param(chart.id, "fail", False)
        graph.set_page_body("r1", "![[Chart]]")
        target = tmp_path / "r.html"
        graph.set_param(saver.id, "path", str(target))
        assert wait_run(qtbot, engine, engine.run_all)
        target.unlink()
        graph.set_param(chart.id, "fail", True)
        assert not wait_run(qtbot, engine, engine.run_all)
        assert not target.exists()
