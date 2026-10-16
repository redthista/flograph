"""The Flo Assistant dock: real turns on the worker thread against the
scripted model from test_flo, with the dials, the fresh-chat rules, undo,
the outbox, the send log and confirm-every-send."""
import json
import os
import stat
import threading

import pandas as pd
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QUndoStack

from flograph.core import ai_disclosure as disc
from flograph.core.graph import Graph
from flograph.llm import profiles, wire
from flograph.llm.profiles import Profile, ProfileSet
from flograph.ui.commands import SetAiPrivacyCommand
from flograph.ui.flo import FloPanel
from flograph.ui.flo.privacy_dialog import ColumnsDialog, known_columns
from flograph.ui.flo.sent_view import format_requests

from tests.test_flo import BUILD, CSV, ScriptedModel, _Cache, _Reply

LOCAL = Profile(id="loc", name="Local Ollama", provider="openai",
                base_url="http://localhost:1/v1", model="m")
ONLINE = Profile(id="web", name="Work gateway", provider="anthropic",
                 base_url="https://ai.example.com/v1", model="m")


@pytest.fixture
def user_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path))
    monkeypatch.setenv("FLOGRAPH_KEYS", "file")
    return tmp_path


@pytest.fixture
def settings(tmp_path):
    s = QSettings(str(tmp_path / "flo.ini"), QSettings.IniFormat)
    yield s
    s.clear()


def _panel(qtbot, registry, settings, active=LOCAL, graph=None, cache=None):
    profiles.save(ProfileSet([LOCAL, ONLINE], active.id))
    graph = graph or Graph()
    stack = QUndoStack()
    panel = FloPanel(graph, registry, stack, cache, settings=settings)
    qtbot.addWidget(panel)
    return panel


def _turn(qtbot, panel, text="Bar chart of sales by region"):
    assert panel.send(text)
    qtbot.waitUntil(lambda: not panel._busy, timeout=5000)


class TestDials:
    """One level, the flow's: Column names unless the flow says otherwise —
    the same for a local and an online connection."""

    def test_column_names_by_default_local_or_online(self, qtbot, registry,
                                                     settings, user_dir):
        local = _panel(qtbot, registry, settings)
        assert local.where.text() == "Local — nothing leaves this PC"
        assert local.level() == disc.SCHEMA
        assert local.sees_btn.text().startswith("Flo can see: Column names")
        online = _panel(qtbot, registry, settings, active=ONLINE)
        assert online.where.text() == "Online — sent to ai.example.com"
        assert online.level() == disc.SCHEMA
        assert all(a.isEnabled() for a in online.level_actions.values())

    def test_the_level_is_the_flows(self, qtbot, registry, settings, user_dir):
        graph = Graph()
        graph.ai_privacy = {"level": 0}
        panel = _panel(qtbot, registry, settings, graph=graph)
        assert panel.level() == disc.STRUCTURE
        assert "nothing from your data" in panel.sees_line.text()

    def test_choosing_a_level_is_an_undoable_edit_of_the_flow(
            self, qtbot, registry, settings, user_dir):
        panel = _panel(qtbot, registry, settings, active=ONLINE)
        panel.choose_level(disc.PROFILE)
        assert panel.graph.ai_privacy == {"level": disc.PROFILE}
        assert panel.level() == disc.PROFILE
        panel.undo_stack.undo()
        assert panel.level() == disc.SCHEMA

    def test_the_card_counts_hidden_and_shared_columns(self, qtbot, registry,
                                                       settings, user_dir):
        graph = Graph()
        graph.ai_privacy = {"columns": {"a": "hidden", "b": "hidden",
                                        "Test_Name": "values"}}
        panel = _panel(qtbot, registry, settings, graph=graph)
        text = panel.sees_line.text()
        assert "2 columns hidden" in text and "Values shared: Test_Name" in text


class TestTurns:
    def test_a_turn_builds_the_flow_as_one_undo_step(self, qtbot, monkeypatch,
                                                     registry, settings, user_dir):
        ScriptedModel(monkeypatch, BUILD)
        panel = _panel(qtbot, registry, settings)
        _turn(qtbot, panel)
        assert len(panel.graph.nodes) == 2
        assert panel.undo_stack.count() == 1
        record = panel._turns[0]
        assert "undo:0" in record["footer"].text()
        assert "sent:0" in record["footer"].text()
        panel._on_link("undo:0")
        assert not panel.graph.nodes
        assert "Undone" in record["footer"].text()

    def test_undo_link_refuses_when_something_came_after(self, qtbot, monkeypatch,
                                                         registry, settings, user_dir):
        ScriptedModel(monkeypatch, BUILD)
        panel = _panel(qtbot, registry, settings)
        _turn(qtbot, panel)
        panel.undo_stack.push(SetAiPrivacyCommand(panel.graph, {"columns": {
            "x": "hidden"}}))
        panel._on_link("undo:0")
        assert len(panel.graph.nodes) == 2      # nothing undone behind its back

    def test_what_was_sent_shows_the_requests(self, qtbot, monkeypatch,
                                              registry, settings, user_dir):
        ScriptedModel(monkeypatch, BUILD)
        panel = _panel(qtbot, registry, settings)
        _turn(qtbot, panel)
        record = panel._turns[0]
        text = format_requests(panel.chat.outbox[record["start"]:record["end"]],
                               record["to"], before=record["before"])
        assert text.startswith("REQUEST 1 → this PC")
        assert "INSTRUCTIONS (system prompt)" in text
        assert "Bar chart of sales by region" in text
        assert "TOOL RESULT — describe_flow" in text
        # the system prompt is shown once, not on every request
        assert text.count("INSTRUCTIONS") == 1

    def test_send_log_has_a_line_per_request_owner_only(self, qtbot, monkeypatch,
                                                        registry, settings, user_dir):
        ScriptedModel(monkeypatch, BUILD)
        panel = _panel(qtbot, registry, settings)
        _turn(qtbot, panel)
        files = list((user_dir / "ai_log").glob("*.jsonl"))
        assert len(files) == 1
        lines = [json.loads(line) for line in files[0].read_text().splitlines()]
        assert len(lines) == len(panel.chat.outbox)
        assert lines[0]["connection"] == "Local Ollama" and lines[0]["sees"] == "schema"
        assert lines[0]["messages"][0]["role"] == "system"
        # later lines carry only what is new
        assert all(m["role"] != "system" for line in lines[1:] for m in line["messages"])
        if os.name == "posix":
            assert stat.S_IMODE(files[0].stat().st_mode) == 0o600

    def test_confirm_every_send_can_refuse(self, qtbot, monkeypatch,
                                           registry, settings, user_dir):
        model = ScriptedModel(monkeypatch, ["hello"])
        panel = _panel(qtbot, registry, settings)
        panel.action_confirm.setChecked(True)
        asked = []
        monkeypatch.setattr(panel, "_confirm",
                            lambda entry, turn: asked.append(entry) and False)
        _turn(qtbot, panel, "hi")
        assert len(asked) == 1 and not model.bodies
        assert not (user_dir / "ai_log").exists()

    def test_advise_offers_no_write_tools(self, qtbot, monkeypatch,
                                          registry, settings, user_dir):
        model = ScriptedModel(monkeypatch, ["You could add a chart."])
        panel = _panel(qtbot, registry, settings)
        panel.choose_autonomy("advise")
        _turn(qtbot, panel, "what should I do?")
        names = {t["function"]["name"] for t in model.bodies[0]["tools"]}
        assert "describe_flow" in names and "add_node" not in names

    def test_server_error_shows_in_the_chat(self, qtbot, monkeypatch,
                                            registry, settings, user_dir):
        monkeypatch.setattr(wire, "_post", lambda *a: _Reply(None, 500, "down"))
        panel = _panel(qtbot, registry, settings)
        _turn(qtbot, panel, "hi")
        assert "settings:" in panel._turns[0]["footer"].text()

    def test_stop_waits_for_the_answer_then_runs_nothing(self, qtbot, monkeypatch,
                                                         registry, settings, user_dir):
        gate = threading.Event()
        model = ScriptedModel(monkeypatch, BUILD)
        scripted = model.post

        def slow(*args):
            gate.wait(5)
            return scripted(*args)

        monkeypatch.setattr(wire, "_post", slow)
        panel = _panel(qtbot, registry, settings)
        assert panel.send("go")
        panel.stop()
        gate.set()
        qtbot.waitUntil(lambda: not panel._busy, timeout=5000)
        assert not panel.graph.nodes and panel.undo_stack.count() == 0


class TestFreshChats:
    def test_lowering_the_level_starts_a_fresh_chat(self, qtbot, monkeypatch,
                                                    registry, settings, user_dir):
        ScriptedModel(monkeypatch, ["hello"])
        panel = _panel(qtbot, registry, settings)
        _turn(qtbot, panel, "hi")
        assert panel.chat is not None
        panel.undo_stack.push(SetAiPrivacyCommand(panel.graph, {"level": 0}))
        assert panel.chat is None

    def test_raising_it_keeps_the_chat(self, qtbot, monkeypatch,
                                       registry, settings, user_dir):
        ScriptedModel(monkeypatch, ["hello"])
        panel = _panel(qtbot, registry, settings)
        _turn(qtbot, panel, "hi")
        panel.choose_level(disc.PROFILE)
        assert panel.chat is not None

    def test_switching_connection_starts_a_fresh_chat(self, qtbot, monkeypatch,
                                                      registry, settings, user_dir):
        ScriptedModel(monkeypatch, ["hello"])
        panel = _panel(qtbot, registry, settings)
        _turn(qtbot, panel, "hi")
        panel.choose_profile("web")
        assert panel.chat is None
        assert profiles.load().active_id == "web"

    def test_reopening_settings_unchanged_keeps_the_chat(self, qtbot, monkeypatch,
                                                         registry, settings, user_dir):
        ScriptedModel(monkeypatch, ["hello"])
        panel = _panel(qtbot, registry, settings)
        _turn(qtbot, panel, "hi")
        panel.reload_profiles()
        assert panel.chat is not None

    def test_new_flow_mid_turn_writes_nothing(self, qtbot, monkeypatch,
                                              registry, settings, user_dir):
        gate = threading.Event()
        model = ScriptedModel(monkeypatch, BUILD)
        scripted = model.post
        monkeypatch.setattr(wire, "_post",
                            lambda *a: (gate.wait(5), scripted(*a))[1])
        panel = _panel(qtbot, registry, settings)
        assert panel.send("go")
        panel.graph_replaced()
        assert not panel._busy
        gate.set()
        qtbot.wait(300)
        assert not panel.graph.nodes and panel.undo_stack.count() == 0


class TestColumnsDialog:
    def test_columns_come_from_cached_outputs(self, qtbot, registry):
        graph = Graph()
        node = registry.instantiate(CSV, (0, 0))
        graph.add_node(node)
        cache = _Cache({node.id: {"table": pd.DataFrame({"name": [1], "sales": [2]})}})
        assert known_columns(graph, cache) == {"name": [node.label],
                                               "sales": [node.label]}

    def test_one_choice_per_column_and_the_level_is_kept(self, qtbot, registry):
        graph = Graph()
        graph.ai_privacy = {"level": 2, "columns": {"name": "hidden"}}
        dialog = ColumnsDialog(graph, None)
        qtbot.addWidget(dialog)
        assert dialog.privacy() == graph.ai_privacy
        dialog.set_mode("name", disc.VALUES)
        assert dialog.privacy() == {"level": 2, "columns": {"name": "values"}}
        dialog.set_mode("name", disc.NAME)
        assert dialog.privacy() == {"level": 2}           # the default says nothing

    def test_older_rules_show_as_their_new_choice(self, qtbot, registry):
        graph = Graph()
        graph.ai_privacy = {"columns": {"a": {"alias": "x"},
                                        "b": {"share_values": True}}}
        dialog = ColumnsDialog(graph, None)
        qtbot.addWidget(dialog)
        assert [c.currentData() for c in dialog.modes] == [disc.HIDDEN, disc.VALUES]

    def test_the_command_undoes(self, qapp):
        graph = Graph()
        stack = QUndoStack()
        stack.push(SetAiPrivacyCommand(graph, {"level": 0}))
        assert graph.ai_privacy == {"level": 0}
        stack.undo()
        assert graph.ai_privacy == {}


class TestWindow:
    @pytest.fixture
    def window(self, qtbot, registry, user_dir):
        from flograph.ui.mainwindow import MainWindow
        s = QSettings("flograph", "flograph")
        saved = {k: s.value(k) for k in ("dock_state", "window_geometry")}
        s.remove("dock_state")
        s.remove("window_geometry")
        try:
            win = MainWindow(registry)
            win.confirm_close = False
            win._save_window_state = lambda: None
            qtbot.addWidget(win)
            win.show()
            qtbot.waitExposed(win)
            yield win
        finally:
            for k, v in saved.items():
                s.setValue(k, v) if v is not None else s.remove(k)

    def test_pages_flo_makes_open_as_pages(self, window, registry):
        """The window builds the pages from graph events alone, so a page
        made by Flo is the same as one made from the + menu — and goes with
        Ctrl+Z."""
        import json
        from flograph.flo.tools import Toolbox
        from flograph.llm.toolcall import ToolCall
        chart = registry.instantiate("flograph.viz.show_plotly", (0, 0))
        window.graph.add_node(chart)
        box = Toolbox(window.graph, registry, window.undo_stack,
                      disclosure=disc.Disclosure(disc.SCHEMA))
        box.handle(chart.id)
        box.begin_turn("pages")
        made = [json.loads(box.execute(ToolCall("a", "add_page", args)))["page"]
                for args in ({"kind": "dashboard", "title": "Board", "nodes": ["n1"]},
                             {"kind": "report", "title": "Paper", "nodes": ["n1"]})]
        box.end_turn()
        ids = [box._page_handles[h] for h in made]
        assert all(i in window._dashboard_pages for i in ids)
        window.undo_stack.undo()
        assert not any(i in window._dashboard_pages for i in ids)

    def test_a_message_says_which_page_is_on_screen(self, window, registry):
        """"Make this report look like…" has to land on the report on
        screen, not on the charts behind it."""
        from flograph.core.graph import Page
        from flograph.flo.tools import Toolbox
        from flograph.ui.commands import AddPageCommand
        window.undo_stack.push(AddPageCommand(window.graph, Page(
            id="rep", title="Monthly", kind="report", preview_mode="web")))
        window.page_bar.select_page("rep")
        panel = window.flo_panel
        panel.toolbox = Toolbox(window.graph, registry, window.undo_stack,
                                disclosure=disc.Disclosure(disc.SCHEMA))
        title, line = panel._screen_context()
        assert title == "Monthly"
        assert 'report page p1 "Monthly", Web preview' in line
        assert "write_report_css" in line
        panel.on_screen = lambda: ""          # the canvas
        assert panel._screen_context() == ("", "")

    def test_closed_by_default_and_opened_by_its_shortcut(self, window, qtbot):
        assert window.flo_dock.isHidden()
        assert window.flo_dock not in window._docks_open_on_model_page
        assert window.action_flo.shortcut().toString() == "Ctrl+Shift+A"
        window.toggle_flo()
        qtbot.wait(10)
        assert window.flo_dock.isVisible()
        group = window._dock_host.tabifiedDockWidgets(window.properties_dock)
        assert window.flo_dock in group

    def test_title_bar_has_the_button(self, window):
        bar = getattr(window, "_title_bar", None)
        if bar is None:
            pytest.skip("native frame")
        assert bar._flo_btn.text() == "Flo"

    def test_opening_a_flow_keeps_its_privacy(self, window):
        loaded = Graph()
        loaded.ai_privacy = {"level": 0, "columns": {"name": "hidden"}}
        window._replace_graph(loaded)
        assert window.graph.ai_privacy == loaded.ai_privacy
        assert window.flo_panel.level() == disc.STRUCTURE

    def test_flo_applies_its_code_unless_told_not_to(self, window):
        """Can ▸ Apply Code It Writes: on by default (Dan, 2026-10-16), and
        what the toolbox is given with each message."""
        panel = window.flo_panel
        assert panel.action_apply_code.isChecked()
        panel.action_apply_code.setChecked(False)
        try:
            from PySide6.QtCore import QSettings
            assert QSettings("flograph", "flograph").value(
                "flo/apply_code", True, type=bool) is False
        finally:
            panel.action_apply_code.setChecked(True)

    def test_flos_code_waits_in_the_editor_for_review(self, window, registry):
        """write_node_code reaches the window's own code editor, unapplied,
        and Review code opens the editor on that node."""
        import json
        from flograph.flo.tools import Toolbox
        from flograph.llm.toolcall import ToolCall
        node = registry.instantiate("flograph.scripting.python_script", (0, 0))
        window.graph.add_node(node)
        before = node.source
        box = Toolbox(window.graph, registry, window.undo_stack,
                      disclosure=disc.Disclosure(disc.SCHEMA),
                      suggest_code=window.flo_panel.suggest_code)
        handle = box.handle(node.id)
        code = before.replace('ctx.log(f"received: {in1!r}")', 'ctx.log("hi")')
        out = json.loads(box.execute(ToolCall("a", "write_node_code",
                                              {"node": handle, "code": code})))
        assert "error" not in out and node.source == before
        window.flo_panel.review_code_requested.emit(node.id)
        assert window.editor_panel._node_id == node.id
        assert window.editor_panel.editor.toPlainText() == code
        assert window.editor_dock.isVisible()


class TestReceipt:
    def test_it_says_what_went_and_where(self, qtbot, monkeypatch, registry,
                                         settings, user_dir):
        from flograph.core.graph import Graph as G
        graph = G()
        node = registry.instantiate(CSV, (0, 0))
        graph.add_node(node)
        cache = _Cache({node.id: {"table": pd.DataFrame(
            {"region": ["a", "b"], "sales": [1, 5], "secret": [1, 2]})}})
        graph.ai_privacy = {"level": 2, "columns": {"secret": "hidden"}}
        ScriptedModel(monkeypatch, [[("get_output", {"node": "n1"})], "done"])
        panel = _panel(qtbot, registry, settings, graph=graph, cache=cache)
        panel.toolbox = None
        # n1 has to exist as a handle: describe first in a real chat
        assert panel._ensure_chat()
        panel.toolbox.handle(node.id)
        _turn(qtbot, panel, "what's in it?")
        receipt = panel._turns[0]["receipt"]
        assert receipt.local and receipt.message
        assert receipt.columns == ["region", "sales"]      # never "secret"
        assert receipt.ranges == ["sales"]
        assert receipt.summary().startswith("Stayed on this PC: your message")
        assert "no rows" in receipt.summary()
        assert any("Smallest and largest" in line for line in receipt.details())

    def test_structure_level_sends_no_names(self, qtbot, monkeypatch, registry,
                                            settings, user_dir):
        from flograph.core.graph import Graph as G
        graph = G()
        node = registry.instantiate(CSV, (0, 0))
        graph.add_node(node)
        graph.ai_privacy = {"level": 0}
        cache = _Cache({node.id: {"table": pd.DataFrame({"region": ["a"]})}})
        ScriptedModel(monkeypatch, [[("describe_flow", {})], "ok"])
        panel = _panel(qtbot, registry, settings, graph=graph, cache=cache)
        _turn(qtbot, panel, "chart region please")
        receipt = panel._turns[0]["receipt"]
        assert receipt.columns == [] and receipt.nodes == 1
        assert "column name" not in receipt.summary()


class TestConsent:
    def test_online_asks_once_and_cancel_sends_nothing(self, qtbot, monkeypatch,
                                                       registry, settings, user_dir):
        model = ScriptedModel(monkeypatch, ["hi", "again"])
        panel = _panel(qtbot, registry, settings, active=ONLINE)
        asked = []
        monkeypatch.setattr(panel, "_ask_consent",
                            lambda p, level: asked.append(level) or (False, False))
        panel.input.setPlainText("hello")
        assert not panel.send()
        assert not model.bodies and panel.input.toPlainText() == "hello"
        monkeypatch.setattr(panel, "_ask_consent",
                            lambda p, level: asked.append(level) or (True, False))
        _turn(qtbot, panel, "hello")
        _turn(qtbot, panel, "and again")
        assert asked == [disc.SCHEMA, disc.SCHEMA]   # not asked a third time

    def test_remembered_per_connection_and_level(self, qtbot, monkeypatch,
                                                 registry, settings, user_dir):
        ScriptedModel(monkeypatch, ["hi"])
        panel = _panel(qtbot, registry, settings, active=ONLINE)
        monkeypatch.setattr(panel, "_ask_consent", lambda p, level: (True, True))
        _turn(qtbot, panel, "hello")
        assert settings.value("flo/agreed/web", type=int) == disc.SCHEMA
        assert panel._agreed_to(ONLINE, disc.STRUCTURE)
        assert not panel._agreed_to(ONLINE, disc.PROFILE)

    def test_local_never_asks(self, qtbot, monkeypatch, registry, settings, user_dir):
        ScriptedModel(monkeypatch, ["hi"])
        panel = _panel(qtbot, registry, settings)
        monkeypatch.setattr(panel, "_ask_consent",
                            lambda *a: pytest.fail("asked for a local server"))
        _turn(qtbot, panel, "hello")

    def test_the_lists_follow_the_rules(self):
        from flograph.ui.flo.consent import never_sees, will_see
        privacy = disc.Privacy(columns={"a": disc.ColumnRule(disc.HIDDEN),
                                        "t": disc.ColumnRule(disc.VALUES)})
        seen = " ".join(will_see(disc.PROFILE, privacy))
        assert "except 1 hidden column" in seen and "lowest and highest" in seen
        assert "values of the columns you chose to share: t" in seen
        assert "no text typed" in " ".join(will_see(disc.STRUCTURE, privacy))
        assert "Column names" in " ".join(never_sees(disc.STRUCTURE))
        assert "Column names" not in " ".join(never_sees(disc.SCHEMA))


def test_the_reply_shows_while_it_streams(qtbot, monkeypatch, registry, settings,
                                          user_dir):
    from tests.test_llm_stream import _SSE
    gate = threading.Event()

    class Held(_SSE):
        def iter_lines(self):
            for index, line in enumerate(self._lines):
                if index == 2:
                    gate.wait(5)     # hold the reply half-written
                yield line

    response = Held([{"choices": [{"delta": {"content": "Building "}}]},
                     {"choices": [{"delta": {"content": "your chart."},
                                   "finish_reason": "stop"}]}])
    monkeypatch.setattr(wire, "_post_stream", lambda *a: response)
    panel = _panel(qtbot, registry, settings)
    assert panel.send("chart please")
    qtbot.waitUntil(lambda: panel._live is not None
                    and panel._live.text() == "Building", timeout=3000)
    gate.set()
    qtbot.waitUntil(lambda: not panel._busy, timeout=3000)
    assert panel._live is None          # the finished reply took its place
    assert response.closed


class TestAskAbout:
    def test_the_message_names_the_nodes_it_points_at(self, qtbot, monkeypatch,
                                                      registry, settings, user_dir):
        model = ScriptedModel(monkeypatch, ["It reads a CSV file."])
        graph = Graph()
        node = registry.instantiate(CSV, (0, 0))
        graph.add_node(node)
        panel = _panel(qtbot, registry, settings, graph=graph)
        panel.ask_about([node.id], f'the node "{node.label}"',
                        "Explain this")
        qtbot.waitUntil(lambda: not panel._busy, timeout=5000)
        sent = model.bodies[0]["messages"][-1]["content"]
        assert sent.startswith(f'[I\'m pointing at the node "{node.label}": n1')
        assert sent.endswith("Explain this")
        assert not panel.about_row.isVisibleTo(panel)   # used up by the send

    def test_without_a_prompt_it_waits_for_your_words(self, qtbot, registry,
                                                      settings, user_dir):
        graph = Graph()
        node = registry.instantiate(CSV, (0, 0))
        graph.add_node(node)
        panel = _panel(qtbot, registry, settings, graph=graph)
        panel.ask_about([node.id], "the node")
        assert panel.about_row.isVisibleTo(panel) and not panel._busy
        panel.clear_about()
        assert not panel.about_row.isVisibleTo(panel)

    def test_window_menu_offers_it(self, qtbot, registry, user_dir):
        from flograph.ui.mainwindow import MainWindow
        win = MainWindow(registry)
        win.confirm_close = False
        win._save_window_state = lambda: None
        qtbot.addWidget(win)
        from PySide6.QtWidgets import QMenu
        menu = QMenu()
        win._add_flo_menu(menu, ["x"], "the node")
        sub = menu.findChildren(QMenu)[0]
        labels = [a.text() for a in sub.actions() if a.text()]
        assert labels[0] == "Ask About This…" and "Explain This" in labels
        assert "Why Did It Fail?" not in labels


def test_user_messages_use_the_width(qtbot, monkeypatch, registry, settings, user_dir):
    ScriptedModel(monkeypatch, ["ok", "ok"])
    panel = _panel(qtbot, registry, settings)
    panel.resize(500, 700)
    panel.show()
    qtbot.waitExposed(panel)
    _turn(qtbot, panel, "a long request " * 12)
    _turn(qtbot, panel, "hi")
    long_one, short_one = panel._user_bubbles
    room = panel.scroll.viewport().width()
    assert long_one.width() >= int(room * 0.8)       # not a thin column
    assert short_one.width() < room // 3             # a short one stays short
    panel.resize(800, 700)
    qtbot.wait(20)
    assert long_one.width() > int(room * 0.85)       # follows the dock


def test_a_long_build_pauses_and_continues(qtbot, monkeypatch, registry,
                                           settings, user_dir):
    from tests.test_flo import BUILD
    settings.setValue("flo/max_steps", 2)
    ScriptedModel(monkeypatch, BUILD)
    panel = _panel(qtbot, registry, settings)
    _turn(qtbot, panel, "build it")
    first = panel._turns[0]
    assert "continue:0" in first["footer"].text()
    assert panel.chat.max_steps == 2
    panel._on_link("continue:0")
    qtbot.waitUntil(lambda: not panel._busy, timeout=5000)
    # 2 more steps, then the scripted answer after one more continue
    panel._on_link("continue:1")
    qtbot.waitUntil(lambda: not panel._busy, timeout=5000)
    assert len(panel.graph.nodes) == 2
    assert "continue:" not in panel._turns[-1]["footer"].text()
    # the stretch that made changes is an undo step of its own; the ones
    # that only looked (steps 1-2) or only answered leave none
    assert panel.undo_stack.count() == 1
    assert "undo:1" in panel._turns[1]["footer"].text()
    # a stale Continue does nothing
    panel._on_link("continue:0")
    assert not panel._busy


def test_run_nodes_runs_the_real_engine(qtbot, monkeypatch, registry, settings,
                                        user_dir):
    from flograph.engine import ExecutionEngine
    graph = Graph()
    table = registry.instantiate("flograph.io.table", (0, 0))
    graph.add_node(table)
    engine = ExecutionEngine(graph)
    model = ScriptedModel(monkeypatch, [
        [("describe_flow", {})],
        [("run_nodes", {"nodes": ["n1"]})],
        "It ran."])
    profiles.save(ProfileSet([LOCAL, ONLINE], LOCAL.id))
    panel = FloPanel(graph, registry, QUndoStack(), engine.cache,
                     settings=settings, engine=engine)
    qtbot.addWidget(panel)
    _turn(qtbot, panel, "run the table")
    result = json.loads(model.bodies[2]["messages"][-1]["content"])
    assert result["run"] == "done"
    assert result["nodes"][0]["status"] == "up to date"
    assert "outputs" in result["nodes"][0]
    assert not engine.active

