"""Flo writes a Report node's text the way the card reads it.

A Report node (`viz/report_card.py`) finds an embed by its own input names
first and by a node's label after; a report page knows only labels. The
model writes ![[n3]] in both, so set_params on a Report's text turns a
handle into the input it is wired to, or failing that into the label — and
says when a label embed is no wire.
"""
import json

import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import ai_disclosure as disc
from flograph.core.ai_disclosure import Disclosure
from flograph.core.graph import Graph
from flograph.flo.agent import SYSTEM_PROMPT
from flograph.flo.tools import ACT, Toolbox
from flograph.llm.toolcall import ToolCall

REPORT = "flograph.viz.report_card"
CHART = "flograph.viz.show_plotly"
CSV = "flograph.io.read_csv"


@pytest.fixture
def stack(qapp):
    return QUndoStack()


def _box(registry, stack):
    graph = Graph()
    report = registry.instantiate(REPORT, (0, 0))
    chart = registry.instantiate(CHART, (0, 0))
    chart.label_override = "Sales Chart"
    table = registry.instantiate(CSV, (0, 0))
    table.label_override = "Sales"
    for node in (report, chart, table):
        graph.add_node(node)
    graph.connect(chart.id, "figure", report.id, "b")
    box = Toolbox(graph, registry, stack,
                  disclosure=Disclosure(disc.SCHEMA), autonomy=ACT)
    for node in (report, chart, table):      # n1, n2, n3
        box.handle(node.id)
    return box, report


def _set_text(box, text):
    box.begin_turn("describe it")
    out = json.loads(box.execute(ToolCall("a", "set_params", {
        "node": "n1", "params": {"text": text}})))
    box.end_turn()
    return out


def test_a_wired_node_is_embedded_by_its_input(registry, stack):
    box, report = _box(registry, stack)
    out = _set_text(box, "# Sales\n\n![[n2|height=300]]\n")
    assert report.params["text"] == "# Sales\n\n![[b|height=300]]\n"
    assert out["embeds"] == [{"embed": "![[b|height=300]]", "input": "b",
                              "node": "n2"}]
    assert "warnings" not in out


def test_an_unwired_node_is_embedded_by_label_and_that_is_said(registry, stack):
    box, report = _box(registry, stack)
    out = _set_text(box, "![[n3]] and ![[n3]]")
    assert report.params["text"] == "![[Sales]] and ![[Sales]]"
    assert [e.get("node") for e in out["embeds"]] == ["n3", "n3"]
    [warning] = out["warnings"]
    assert warning.startswith("n3 not wired into this Report")
    assert "(a, c, d)" in warning


def test_an_input_with_nothing_wired_is_a_problem(registry, stack):
    box, _ = _box(registry, stack)
    out = _set_text(box, "![[a]]")
    assert out["embeds"][0]["problem"].startswith("nothing is wired into input a")
    assert any("nothing is wired into input a" in w for w in out["warnings"])


def test_a_label_no_node_has_is_a_problem(registry, stack):
    box, _ = _box(registry, stack)
    out = _set_text(box, "![[Nowhere]]")
    assert out["embeds"][0]["problem"] == "no node has this label"


def test_one_undo_takes_the_text_back(registry, stack):
    box, report = _box(registry, stack)
    before = report.params["text"]
    _set_text(box, "![[n2]]")
    stack.undo()
    assert report.params["text"] == before


def test_other_nodes_text_is_left_as_written(registry, stack):
    """Only a Report card's text is an embed language — a Note's setting
    of the same name is just words."""
    box, _ = _box(registry, stack)
    note = registry.instantiate("flograph.util.note", (0, 0))
    assert note.spec.card != "report" and "text" in note.params
    box.graph.add_node(note)
    handle = box.handle(note.id)
    box.begin_turn("x")
    out = json.loads(box.execute(ToolCall("a", "set_params", {
        "node": handle, "params": {"text": "![[n2]]"}})))
    box.end_turn()
    assert note.params["text"] == "![[n2]]" and "embeds" not in out


def test_the_prompt_tells_a_report_node_from_a_page():
    assert "flograph.viz.report_card" in SYSTEM_PROMPT
    assert "inputs a, b, c and d" in SYSTEM_PROMPT


# -- the embed language: |live and its neighbours --------------------------------
# Dan, testing: asked for "live" charts, Flo kept |height and never wrote
# |live — no tool had ever said the flag exists.

def _page(box, markdown):
    box.begin_turn("a page")
    out = json.loads(box.execute(ToolCall("a", "add_page", {
        "kind": "report", "title": "About", "markdown": markdown})))
    box.end_turn()
    return out


def test_the_report_tools_say_what_live_is(registry, stack):
    box, _ = _box(registry, stack)
    for name in ("write_report", "add_page"):
        spec = next(t for t in box.specs() if t.name == name)
        assert "live" in spec.description and "interactive" in spec.description
        assert "search" in spec.description and "fit" in spec.description


def test_live_is_a_flag_not_a_problem(registry, stack):
    box, _ = _box(registry, stack)
    out = _page(box, "![[n2|live|height=400]]")
    assert out["embeds"] == [{"embed": "![[Sales Chart|live|height=400]]",
                              "node": "n2"}]
    assert "warnings" not in out


def test_a_guessed_flag_is_said_rather_than_read_as_a_port(registry, stack):
    """`|interactive` would be taken as an output name and fail quietly."""
    box, _ = _box(registry, stack)
    out = _page(box, "![[n2|interactive]] ![[n2|hover=on]]")
    first, second = (e["problem"] for e in out["embeds"])
    assert "'interactive' is not an output of n2" in first
    assert "flags are fit, live, search" in first
    assert second.startswith("unknown option hover=on")
    assert len(out["warnings"]) == 2


def test_a_real_port_after_the_bar_is_fine(registry, stack):
    box, _ = _box(registry, stack)
    out = _page(box, "![[n2|figure|live]]")
    assert "problem" not in out["embeds"][0]


def test_a_report_nodes_input_embed_is_checked_too(registry, stack):
    box, _ = _box(registry, stack)
    out = _set_text(box, "![[n2|live]] ![[n2|wobble=1]]")
    ok, bad = out["embeds"]
    assert "problem" not in ok
    assert bad["problem"].startswith("unknown option wobble=1")


def test_the_prompt_says_a_report_node_is_live_only_as_a_web_page():
    assert "|live makes them interactive when it is saved as a web page" \
        in SYSTEM_PROMPT
