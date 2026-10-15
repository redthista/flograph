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
            "Done.",
            "Left unwired on purpose: there is no data yet."])
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
        # open the turn + 5 tool calls + the unwired check + close the turn
        assert len(calls) == 8

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
        box.execute(ToolCall("x", "add_node", {"type_id": "flograph.transform.sort"}))
        box.execute(ToolCall("x", "add_node", {"type_id": "flograph.transform.sort",
                                               "input_from": "n1"}))
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



class TestQualityAids:
    """What keeps a weaker model on the rails: wiring done for it, ports
    picked for it, a check before 'done', and the library in the prompt."""

    def test_add_node_wires_from_input_from(self, monkeypatch, registry, stack):
        box = _toolbox(registry, stack)
        reader = json.loads(box.execute(ToolCall("a", "add_node", {"type_id": CSV})))
        chart = json.loads(box.execute(ToolCall("b", "add_node", {
            "type_id": PLOTLY, "input_from": reader["node"]})))
        assert chart["wired"] == "n1.table -> n2.table"
        assert "unwired_inputs" not in chart
        conn = box.graph.input_connection(box._handles["n2"], "table")
        assert conn is not None

    def test_connect_picks_the_ports(self, registry, stack):
        box = _toolbox(registry, stack)
        box.execute(ToolCall("a", "add_node", {"type_id": CSV}))
        box.execute(ToolCall("b", "add_node", {"type_id": PLOTLY}))
        out = json.loads(box.execute(ToolCall("c", "connect", {
            "from_node": "n1", "to_node": "n2"})))
        assert out["connected"] == "n1.table -> n2.table"

    def test_a_named_port_that_does_not_exist_still_says_so(self, registry, stack):
        box = _toolbox(registry, stack)
        box.execute(ToolCall("a", "add_node", {"type_id": CSV}))
        box.execute(ToolCall("b", "add_node", {"type_id": PLOTLY}))
        out = json.loads(box.execute(ToolCall("c", "connect", {
            "from_node": "n1", "to_node": "n2", "to_port": "tabel"})))
        assert "no input 'tabel'" in out["error"]

    def test_unwired_inputs_are_reported(self, registry, stack):
        box = _toolbox(registry, stack)
        chart = json.loads(box.execute(ToolCall("a", "add_node", {"type_id": PLOTLY})))
        assert chart["unwired_inputs"] == ["table"]
        flow = json.loads(box.execute(ToolCall("b", "describe_flow", {})))
        assert flow["nodes"][0]["unwired_inputs"] == ["table"]

    def test_the_agent_checks_wiring_before_done(self, monkeypatch, registry, stack):
        model = ScriptedModel(monkeypatch, [
            [("add_node", {"type_id": CSV})],
            [("add_node", {"type_id": PLOTLY})],
            "Done!",
            [("connect", {"from_node": "n1", "to_node": "n2"})],
            "Done — wired now."])
        box = _toolbox(registry, stack)
        result = Conversation(wire.Connection(model="m"), box).send("chart")
        assert result.text == "Done — wired now."
        check = [m for m in model.bodies[3]["messages"]
                 if m["role"] == "user" and "Check from flograph" in str(m["content"])]
        assert check and "n2" in check[0]["content"]
        assert box.graph.input_connection(box._handles["n2"], "table") is not None

    def test_the_check_is_asked_once(self, monkeypatch, registry, stack):
        ScriptedModel(monkeypatch, [[("add_node", {"type_id": PLOTLY})],
                                    "Done.", "Still done."])
        result = Conversation(wire.Connection(model="m"),
                              _toolbox(registry, stack)).send("chart")
        assert result.text == "Still done."

    def test_advise_is_not_checked(self, monkeypatch, registry, stack):
        ScriptedModel(monkeypatch, ["Add a chart."])
        result = Conversation(wire.Connection(model="m"),
                              _toolbox(registry, stack, autonomy=ADVISE)).send("x")
        assert result.text == "Add a chart."

    def test_the_library_is_in_the_prompt(self, registry, stack):
        prompt = Conversation(wire.Connection(model="m"),
                              _toolbox(registry, stack)).system_prompt()
        assert "Show Plotly=viz.show_plotly" in prompt
        assert "Read CSV=io.read_csv" in prompt

    def test_short_type_ids_work(self, registry, stack):
        box = _toolbox(registry, stack)
        out = json.loads(box.execute(ToolCall("a", "add_node",
                                              {"type_id": "viz.show_plotly"})))
        assert out["node"] == "n1"

    def test_unknown_arguments_are_ignored_not_fatal(self, registry, stack):
        box = _toolbox(registry, stack)
        out = json.loads(box.execute(ToolCall("a", "describe_flow",
                                              {"timeout": "infinite"})))
        assert out["ignored_arguments"] == ["timeout"] and "error" not in out

    def test_get_output_picks_the_table(self, registry, stack):
        graph = Graph()
        node = registry.instantiate(PLOTLY, (0, 0))
        graph.add_node(node)
        cache = _Cache({node.id: {"table": pd.DataFrame({"a": [1]})}})
        box = _toolbox(registry, stack, graph=graph, cache=cache)
        box.handle(node.id)
        out = json.loads(box.execute(ToolCall("a", "get_output", {"node": "n1"})))
        assert out["port"] == "table" and out["columns"][0]["name"] == "a"

    def test_names_on_record_are_hidden_at_structure(self, registry, stack):
        class Spilled(_Cache):
            def get(self, node_id):
                class Entry:
                    column_names = {"table": ("patient_name",)}
                return Entry()
        graph = Graph()
        node = registry.instantiate(PLOTLY, (0, 0))
        node.params["x"] = "patient_name"
        graph.add_node(node)
        box = _toolbox(registry, stack, graph=graph, cache=Spilled(),
                       level=disc.STRUCTURE)
        flow = box.execute(ToolCall("a", "describe_flow", {}))
        assert "patient_name" not in flow

    def test_run_nodes_runs_on_the_worker_and_reports(self, monkeypatch, registry,
                                                      stack):
        ran = []
        model = ScriptedModel(monkeypatch, [
            [("add_node", {"type_id": CSV})],
            [("run_nodes", {"nodes": ["n1"]})],
            "Ran it."])
        box = _toolbox(registry, stack)
        box.runner = lambda ids, cancelled: ran.append(ids) or "done"
        Conversation(wire.Connection(model="m"), box).send("run it")
        assert ran == [[box._handles["n1"]]]
        result = json.loads(model.bodies[2]["messages"][-1]["content"])
        assert result["run"] == "done" and result["nodes"][0]["node"] == "n1"

    def test_run_nodes_only_when_acting_with_a_runner(self, registry, stack):
        box = _toolbox(registry, stack)
        assert "run_nodes" not in {t.name for t in box.specs()}
        box.runner = lambda ids, cancelled: "done"
        assert "run_nodes" in {t.name for t in box.specs()}
        box.autonomy = ADVISE
        assert "run_nodes" not in {t.name for t in box.specs()}



class TestStayingOnTrack:
    """What stops a model losing its place: its own changes handed back,
    repeats called out, duplicates refused, column settings checked."""

    def test_changes_come_back_with_every_change(self, registry, stack):
        box = _toolbox(registry, stack)
        box.execute(ToolCall("a", "add_node", {"type_id": CSV}))
        out = json.loads(box.execute(ToolCall("b", "add_node", {
            "type_id": PLOTLY, "input_from": "n1"})))
        assert out["this_turn_so_far"][0].startswith("Added Read CSV (n1)")
        assert len(out["this_turn_so_far"]) == 3     # add, add, connect

    def test_a_repeated_read_is_called_out(self, registry, stack):
        box = _toolbox(registry, stack)
        box.execute(ToolCall("a", "describe_flow", {}))
        again = json.loads(box.execute(ToolCall("b", "describe_flow", {})))
        assert "already made this exact call" in again["note"]
        box.execute(ToolCall("c", "add_node", {"type_id": CSV}))
        fresh = json.loads(box.execute(ToolCall("d", "describe_flow", {})))
        assert "note" not in fresh or "already" not in fresh["note"]

    def test_a_duplicate_node_is_refused(self, registry, stack):
        box = _toolbox(registry, stack)
        box.execute(ToolCall("a", "add_node", {"type_id": CSV}))
        box.execute(ToolCall("b", "add_node", {"type_id": "flograph.transform.sort",
                                               "input_from": "n1"}))
        out = json.loads(box.execute(ToolCall("c", "add_node", {
            "type_id": "flograph.transform.sort", "input_from": "n1"})))
        assert "n2 is already that node" in out["error"]
        assert len(box.graph.nodes) == 2

    def test_a_repeated_run_is_not_run_again(self, registry, stack):
        box = _toolbox(registry, stack)
        runs = []
        box.runner = lambda ids, cancelled: runs.append(ids) or "done"
        box.execute(ToolCall("a", "add_node", {"type_id": CSV}))
        call = ToolCall("r", "run_nodes", {"nodes": ["n1"]})
        box.execute_run(call, lambda fn: fn(), lambda: False)
        again = json.loads(box.execute_run(call, lambda fn: fn(), lambda: False))
        assert len(runs) == 1 and "already ran these" in again["note"]

    def test_column_settings_are_checked_against_the_input(self, registry, stack):
        graph = Graph()
        reader = registry.instantiate(CSV, (0, 0))
        graph.add_node(reader)
        cache = _Cache({reader.id: {"table": pd.DataFrame(
            {"Test_Name": ["a"], "Result_Value": ["1.5"]})}})
        box = _toolbox(registry, stack, graph=graph, cache=cache)
        box.handle(reader.id)
        out = json.loads(box.execute(ToolCall("a", "add_node", {
            "type_id": PLOTLY, "input_from": "n1",
            "params": {"x": "Test_Nme", "y": "Result_Value"}})))
        text = " ".join(out["warnings"])
        assert "no column 'Test_Nme'" in text and "Test_Name" in text
        assert "'Result_Value' is text here" in text

    def test_no_column_warnings_at_structure(self, registry, stack):
        graph = Graph()
        reader = registry.instantiate(CSV, (0, 0))
        graph.add_node(reader)
        cache = _Cache({reader.id: {"table": pd.DataFrame({"secret": [1]})}})
        box = _toolbox(registry, stack, graph=graph, cache=cache,
                       level=disc.STRUCTURE)
        box.handle(reader.id)
        out = box.execute(ToolCall("a", "add_node", {
            "type_id": PLOTLY, "input_from": "n1", "params": {"x": "nope"}}))
        assert "secret" not in out and "warnings" not in out

    def test_the_prompt_asks_for_a_question_when_unclear(self, registry, stack):
        prompt = Conversation(wire.Connection(model="m"),
                              _toolbox(registry, stack)).system_prompt()
        assert "ask one short question" in prompt
        assert "this_turn_so_far" in prompt



def test_the_receipt_names_shared_values(registry, stack):
    from flograph.flo import receipt
    graph = Graph()
    node = registry.instantiate(CSV, (0, 0))
    graph.add_node(node)
    cache = _Cache({node.id: {"table": pd.DataFrame({"Test_Name": ["TSH"]})}})
    box = _toolbox(registry, stack, graph=graph, cache=cache, level=disc.SCHEMA,
                   privacy=Privacy(columns={"Test_Name": ColumnRule(share_values=True)}))
    box.handle(node.id)
    result = box.execute(ToolCall("a", "get_output", {"node": "n1"}))
    entry = {"messages": [{"role": "system", "content": "s"},
                          {"role": "tool", "name": "get_output", "content": result}]}
    made = receipt.build([entry], [], box.disclosure, destination="x", local=False)
    assert made.values == ["Test_Name"]
    assert "the values of 1 column you share" in made.summary()


def test_the_prompt_says_how_to_get_values(registry, stack):
    prompt = Conversation(wire.Connection(model="m"),
                          _toolbox(registry, stack, level=disc.SCHEMA)).system_prompt()
    assert "Share values" in prompt and "never say what a value is" in prompt
