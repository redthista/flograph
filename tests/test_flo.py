"""The Flo Assistant's tools and agent loop, end to end against a scripted
model: real registry, real graph, real undo stack, real wire code — only
the HTTP POST is replaced (wire._post), so each format's request and reply
shapes are exercised for real."""
import json

import pandas as pd
import pytest
from PySide6.QtGui import QUndoStack

from flograph.core import ai_disclosure as disc
from flograph.core.ai_disclosure import ColumnRule, Disclosure, Privacy
from flograph.core.graph import Graph
from flograph.flo import tools as tools_mod
from flograph.flo.agent import Conversation
from flograph.flo.tools import ACT, ADVISE, Toolbox
from flograph.llm import wire
from flograph.llm.toolcall import ToolCall

CSV = "flograph.io.read_csv"
PLOTLY = "flograph.viz.show_plotly"


class _Cache:
    """Just enough of OutputCache: peek() hands back what is in memory."""
    def __init__(self, outputs=None):
        self.outputs = outputs or {}

    def peek(self, node_id):
        return self.outputs.get(node_id, {})


class _Reply:
    def __init__(self, payload, status=200, text=""):
        self._payload, self.status_code, self.text = payload, status, text

    def json(self):
        return self._payload


class ScriptedModel:
    """Answers each POST with the next scripted step, in the format the
    request was made in. A step is a list of (tool, args) calls, or a str."""

    def __init__(self, monkeypatch, steps, refuse_tools=False):
        self.steps = list(steps)
        self.bodies = []
        self.refuse_tools = refuse_tools
        monkeypatch.setattr(wire, "_post", self.post)

    def post(self, url, headers, body, timeout, verify):
        self.bodies.append(body)
        if self.refuse_tools and "tools" in body:
            return _Reply(None, 400, "this model does not support tools")
        step = self.steps.pop(0)
        anthropic = url.endswith("/messages")
        native = "tools" in body
        if isinstance(step, str):
            if anthropic:
                return _Reply({"content": [{"type": "text", "text": step}]})
            return _Reply({"choices": [{"message": {"content": step}}]})
        if not native:   # JSON fallback: calls written into the text
            text = "```tool\n" + json.dumps({"calls": [
                {"name": n, "arguments": a} for n, a in step]}) + "\n```"
            if anthropic:
                return _Reply({"content": [{"type": "text", "text": text}]})
            return _Reply({"choices": [{"message": {"content": text}}]})
        if anthropic:
            return _Reply({"content": [
                {"type": "tool_use", "id": f"t{i}", "name": n, "input": a}
                for i, (n, a) in enumerate(step)], "stop_reason": "tool_use"})
        return _Reply({"choices": [{"message": {"content": None, "tool_calls": [
            {"id": f"c{i}", "type": "function",
             "function": {"name": n, "arguments": json.dumps(a)}}
            for i, (n, a) in enumerate(step)]}}]})


@pytest.fixture
def stack(qapp):
    return QUndoStack()


def _toolbox(registry, stack, graph=None, level=disc.PROFILE, privacy=None,
             cache=None, autonomy=ACT):
    return Toolbox(graph or Graph(), registry, stack,
                   disclosure=Disclosure(level, privacy), autonomy=autonomy,
                   cache=cache)


BUILD = [
    [("describe_flow", {})],
    [("find_node_types", {"query": "bar chart"})],
    [("add_node", {"type_id": CSV, "params": {"path": "/home/u/sales.csv"}})],
    [("add_node", {"type_id": PLOTLY, "near": "n1",
                   "params": {"kind": "bar", "x": "region", "y": "sales"}}),
     ("connect", {"from_node": "n1", "to_node": "n2", "to_port": "table"})],
    "I added a CSV reader and a bar chart of sales by region.",
]


class TestAgentBuildsAFlow:
    @pytest.mark.parametrize("provider", ["openai", "anthropic"])
    def test_native_tools(self, monkeypatch, registry, stack, provider):
        model = ScriptedModel(monkeypatch, BUILD)
        box = _toolbox(registry, stack)
        conn = wire.Connection(provider=provider, model="m",
                               base_url="http://localhost:1/v1")
        result = Conversation(conn, box).send("Bar chart of sales by region")

        assert result.text.startswith("I added")
        assert result.stopped == "" and result.steps == 5
        graph = box.graph
        csv, chart = sorted(graph.nodes.values(), key=lambda n: n.pos[0])
        assert csv.type_id == CSV and chart.type_id == PLOTLY
        assert chart.params["kind"] == "bar" and chart.params["x"] == "region"
        assert graph.input_connection(chart.id, "table").src_node == csv.id
        assert chart.pos[0] > csv.pos[0]
        assert [a.tool for a in result.actions] == ["add_node", "add_node", "connect"]
        assert all("tools" in b for b in model.bodies)

    def test_the_whole_turn_is_one_undo(self, monkeypatch, registry, stack):
        ScriptedModel(monkeypatch, BUILD)
        box = _toolbox(registry, stack)
        Conversation(wire.Connection(model="m"), box).send("go")
        assert stack.count() == 1
        assert stack.text(0).startswith("Flo Assistant: go")
        stack.undo()
        assert not box.graph.nodes and not box.graph.connections
        stack.redo()
        assert len(box.graph.nodes) == 2 and len(box.graph.connections) == 1

    def test_a_reading_turn_leaves_no_undo_step(self, monkeypatch, registry, stack):
        ScriptedModel(monkeypatch, [[("describe_flow", {})], "It is empty."])
        Conversation(wire.Connection(model="m"), _toolbox(registry, stack)).send("?")
        assert stack.count() == 0

    def test_json_fallback_end_to_end_and_it_sticks(self, monkeypatch, registry, stack):
        model = ScriptedModel(monkeypatch, BUILD + [[("describe_flow", {})], "ok"],
                              refuse_tools=True)
        box = _toolbox(registry, stack)
        chat = Conversation(wire.Connection(model="m"), box)
        chat.send("Bar chart")
        assert len(box.graph.nodes) == 2 and chat.tool_mode == "json"
        refused = sum(1 for b in model.bodies if "tools" in b)
        chat.send("again")
        # the second turn never asks natively again
        assert sum(1 for b in model.bodies if "tools" in b) == refused

    def test_errors_go_back_to_the_model_which_corrects_itself(
            self, monkeypatch, registry, stack):
        model = ScriptedModel(monkeypatch, [
            [("add_node", {"type_id": "flograph.viz.bar_chart"})],
            [("add_node", {"type_id": PLOTLY, "params": {"knd": "bar"}})],
            [("add_node", {"type_id": PLOTLY, "params": {"kind": "bar"}})],
            "Done."])
        box = _toolbox(registry, stack)
        Conversation(wire.Connection(model="m"), box).send("chart")
        results = [m["content"] for m in model.bodies[-1]["messages"]
                   if m.get("role") == "tool"]
        assert "no node type 'flograph.viz.bar_chart'" in results[0]
        assert "has no setting 'knd'" in results[1] and "'kind'" in results[1]
        assert len(box.graph.nodes) == 1

    def test_step_limit(self, monkeypatch, registry, stack):
        ScriptedModel(monkeypatch, [[("describe_flow", {})]] * 5)
        chat = Conversation(wire.Connection(model="m"), _toolbox(registry, stack),
                            max_steps=3)
        result = chat.send("loop forever")
        assert result.stopped == "step limit" and result.steps == 3

    def test_cancel_between_steps_keeps_what_was_done(self, monkeypatch, registry, stack):
        ScriptedModel(monkeypatch, BUILD)
        box = _toolbox(registry, stack)
        steps = []
        chat = Conversation(wire.Connection(model="m"), box)
        # Stop pressed while the fourth request was out: its answer arrives,
        # but the calls in it are not run — only the third step's node stays
        result = chat.send(
            "go", cancelled=lambda: len(steps) >= 4,
            on_event=lambda e: steps.append(e) if e.kind == "thinking" else None)
        assert result.stopped == "cancelled"
        assert len(box.graph.nodes) == 1 and stack.count() == 1
        assert "one Undo" in result.text
        # each skipped call still has its answer, so the next request is valid
        skipped = [m for m in chat.messages if m["role"] == "tool"][-2:]
        assert all("not run" in m["content"] for m in skipped)

    def test_before_send_can_refuse(self, monkeypatch, registry, stack):
        model = ScriptedModel(monkeypatch, ["hello"])
        seen = []
        chat = Conversation(wire.Connection(model="m"), _toolbox(registry, stack),
                            before_send=lambda entry: seen.append(entry) and False)
        result = chat.send("hi")
        assert result.stopped == "declined" and result.text == "Not sent."
        assert len(seen) == 1 and not chat.outbox and not model.bodies

    def test_tools_run_through_on_ui(self, monkeypatch, registry, stack):
        ScriptedModel(monkeypatch, BUILD)
        calls = []

        def on_ui(fn):
            calls.append(fn)
            return fn()

        Conversation(wire.Connection(model="m"), _toolbox(registry, stack),
                     on_ui=on_ui).send("go")
        # open the turn + 5 tool calls + close the turn
        assert len(calls) == 7

    def test_server_failure_mid_turn(self, monkeypatch, registry, stack):
        replies = iter([_Reply({"choices": [{"message": {"tool_calls": [{
            "id": "a", "function": {"name": "add_node",
                                    "arguments": json.dumps({"type_id": CSV})}}]}}]}),
            _Reply(None, 500, "gateway exploded")])
        monkeypatch.setattr(wire, "_post", lambda *a: next(replies))
        box = _toolbox(registry, stack)
        result = Conversation(wire.Connection(model="m"), box).send("go")
        assert result.stopped == "error" and "gateway exploded" in result.text
        assert len(box.graph.nodes) == 1 and stack.count() == 1

    def test_outbox_holds_exactly_what_was_sent(self, monkeypatch, registry, stack):
        ScriptedModel(monkeypatch, ["hello"])
        chat = Conversation(wire.Connection(model="m"), _toolbox(registry, stack))
        chat.send("hi there")
        assert chat.outbox[0]["messages"][-1] == {"role": "user", "content": "hi there"}
        assert "add_node" in chat.outbox[0]["tools"]


class TestWhatTheModelSees:
    def _flow(self, registry, stack):
        graph = Graph()
        csv = graph.add_node(registry.instantiate(CSV))
        graph.set_param(csv.id, "path", "/home/dan/payroll/salaries.csv")
        chart = graph.add_node(registry.instantiate(PLOTLY, (300, 0)))
        graph.set_param(chart.id, "x", "salary")
        graph.connect(csv.id, "table", chart.id, "table")
        cache = _Cache({csv.id: {"table": pd.DataFrame({
            "salary": [50123.0, 61000.0], "name": ["Alice Smith", "Bob Jones"]})}})
        return graph, cache

    def _all_text(self, box, calls):
        return " ".join(box.execute(ToolCall("x", n, a)) for n, a in calls)

    def test_structure_level_leaks_no_column_names_paths_or_values(
            self, registry, stack):
        graph, cache = self._flow(registry, stack)
        box = _toolbox(registry, stack, graph, disc.STRUCTURE, cache=cache)
        assert "get_output" not in [t.name for t in box.specs()]
        text = self._all_text(box, [("describe_flow", {}), ("get_node", {"node": "n1"}),
                                    ("get_node", {"node": "n2"})])
        for leak in ("salary", "Alice", "50123", "/home/dan", "payroll"):
            assert leak not in text
        assert "<column>" in text and "salaries.csv" in text

    def test_profile_level_shows_ranges_never_rows(self, registry, stack):
        graph, cache = self._flow(registry, stack)
        box = _toolbox(registry, stack, graph, disc.PROFILE, cache=cache)
        box.execute(ToolCall("x", "describe_flow", {}))
        out = json.loads(box.execute(ToolCall("x", "get_output", {"node": "n1"})))
        cols = {c["name"]: c for c in out["columns"]}
        assert cols["salary"]["max"] == 61000.0
        assert "Alice" not in json.dumps(out)

    def test_aliases_both_ways(self, registry, stack):
        graph, cache = self._flow(registry, stack)
        privacy = Privacy(columns={"salary": ColumnRule(alias="col_1",
                                                        hint="pay in GBP")})
        box = _toolbox(registry, stack, graph, disc.SCHEMA, privacy, cache)
        text = self._all_text(box, [("describe_flow", {}),
                                    ("get_output", {"node": "n1"})])
        assert "salary" not in text and "col_1" in text and "pay in GBP" in text
        box.execute(ToolCall("x", "set_params",
                             {"node": "n2", "params": {"y": "col_1"}}))
        chart = next(n for n in graph.nodes.values() if n.type_id == PLOTLY)
        assert chart.params["y"] == "salary"

    def test_the_users_own_words_are_scrubbed_too(self, monkeypatch, registry, stack):
        model = ScriptedModel(monkeypatch, ["ok"])
        privacy = Privacy(columns={"salary": ColumnRule(alias="col_1")})
        box = _toolbox(registry, stack, privacy=privacy)
        Conversation(wire.Connection(model="m"), box).send("chart salary by month")
        assert model.bodies[0]["messages"][-1]["content"] == "chart col_1 by month"

    def test_password_params_never_go_out(self, registry, stack):
        spec = next(s for s in registry.all()
                    if any(p.type == "password" for p in s.params))
        name = next(p.name for p in spec.params if p.type == "password")
        graph = Graph()
        node = graph.add_node(registry.instantiate(spec.type_id))
        graph.set_param(node.id, name, "sk-super-secret")
        box = _toolbox(registry, stack, graph)
        text = self._all_text(box, [("describe_flow", {}), ("get_node", {"node": "n1"})])
        assert "sk-super-secret" not in text


class TestAutonomy:
    def test_advise_offers_no_write_tools(self, registry, stack):
        names = {t.name for t in _toolbox(registry, stack, autonomy=ADVISE).specs()}
        assert "add_node" not in names and "describe_flow" in names

    def test_a_write_call_in_advise_mode_is_refused(self, registry, stack):
        box = _toolbox(registry, stack, autonomy=ADVISE)
        out = json.loads(box.execute(ToolCall("x", "add_node", {"type_id": CSV})))
        assert "no tool 'add_node'" in out["error"]
        assert not box.graph.nodes and stack.count() == 0

    def test_advise_prompt_says_so(self, registry, stack):
        chat = Conversation(wire.Connection(model="m"),
                            _toolbox(registry, stack, autonomy=ADVISE))
        assert "cannot change the flow" in chat.messages[0]["content"]


class TestTools:
    def test_bad_json_arguments_are_explained(self, registry, stack):
        box = _toolbox(registry, stack)
        out = json.loads(box.execute(ToolCall("x", "add_node", {}, "{type: x")))
        assert "not valid JSON" in out["error"]

    def test_unknown_node_lists_the_real_ones(self, registry, stack):
        box = _toolbox(registry, stack)
        box.execute(ToolCall("x", "add_node", {"type_id": CSV}))
        out = json.loads(box.execute(ToolCall("x", "get_node", {"node": "n9"})))
        assert "n1" in out["error"]

    def test_connect_names_the_ports_when_ambiguous(self, registry, stack):
        box = _toolbox(registry, stack)
        box.execute(ToolCall("x", "add_node", {"type_id": CSV}))
        box.execute(ToolCall("x", "add_node", {"type_id": PLOTLY}))
        out = json.loads(box.execute(ToolCall(
            "x", "connect", {"from_node": "n2", "to_node": "n1"})))
        assert "outputs" in out["error"] and "figure" in out["error"]

    def test_connect_refuses_a_loop(self, registry, stack):
        box = _toolbox(registry, stack)
        for _ in range(2):
            box.execute(ToolCall("x", "add_node", {"type_id": "flograph.transform.sort"}))
        box.execute(ToolCall("x", "connect", {"from_node": "n1", "to_node": "n2"}))
        out = json.loads(box.execute(ToolCall(
            "x", "connect", {"from_node": "n2", "to_node": "n1"})))
        assert "loop" in out["error"]

    def test_choice_values_are_checked(self, registry, stack):
        box = _toolbox(registry, stack)
        out = json.loads(box.execute(ToolCall("x", "add_node", {
            "type_id": PLOTLY, "params": {"kind": "barchart"}})))
        assert "must be one of" in out["error"] and not box.graph.nodes

    def test_delete_and_rename(self, registry, stack):
        box = _toolbox(registry, stack)
        box.execute(ToolCall("x", "add_node", {"type_id": CSV}))
        box.execute(ToolCall("x", "rename_node", {"node": "n1", "label": "Sales"}))
        assert next(iter(box.graph.nodes.values())).label == "Sales"
        box.execute(ToolCall("x", "delete_nodes", {"nodes": ["n1"]}))
        assert not box.graph.nodes

    def test_search_finds_what_people_ask_for(self, registry):
        def first(q):
            return tools_mod.search_types(registry, q)[0]
        assert first("bar chart")["type_id"] == PLOTLY
        assert first("bar chart")["set"]["kind"] == "bar"
        assert first("join two tables")["type_id"] == "flograph.transform.join"
        assert first("group by sum")["type_id"] == "flograph.transform.group_by"
        assert first("read excel")["label"] == "Read Excel"

    def test_usual_nodes_exist(self, registry):
        for type_id in set(tools_mod.USUAL_NODE.values()):
            assert registry.maybe_get(type_id) is not None, type_id
