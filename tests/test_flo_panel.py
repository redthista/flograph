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
from flograph.ui.flo.privacy_dialog import PrivacyDialog, known_columns
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
    def test_local_connection_may_see_profile(self, qtbot, registry, settings, user_dir):
        panel = _panel(qtbot, registry, settings)
        assert panel.badge.text() == "Local"
        assert panel.level() == disc.PROFILE
        assert "nothing leaves this PC" in panel.limit_note.text()

    def test_online_connection_defaults_to_schema(self, qtbot, registry, settings, user_dir):
        panel = _panel(qtbot, registry, settings, active=ONLINE)
        assert panel.badge.text() == "Online"
        assert panel.level() == disc.SCHEMA
        assert not panel.level_combo.model().item(disc.PROFILE).isEnabled()
        assert "ai.example.com" in panel.limit_note.text()

    def test_the_flow_can_lower_it(self, qtbot, registry, settings, user_dir):
        graph = Graph()
        graph.ai_privacy = {"level": 0}
        panel = _panel(qtbot, registry, settings, graph=graph)
        assert panel.level() == disc.STRUCTURE
        assert "This flow allows up to Structure" in panel.limit_note.text()

    def test_the_chat_choice_is_remembered_but_clamped(self, qtbot, registry, settings, user_dir):
        settings.setValue("flo/level", disc.SCHEMA)
        panel = _panel(qtbot, registry, settings)
        assert panel.level() == disc.SCHEMA
        settings.setValue("flo/level", disc.PROFILE)
        panel = _panel(qtbot, registry, settings, active=ONLINE)
        assert panel.level() == disc.SCHEMA


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
        assert "4 requests" in record["footer"].text() or \
            "5 requests" in record["footer"].text()
        panel._on_link("undo:0")
        assert not panel.graph.nodes
        assert "Undone" in record["footer"].text()

    def test_undo_link_refuses_when_something_came_after(self, qtbot, monkeypatch,
                                                         registry, settings, user_dir):
        ScriptedModel(monkeypatch, BUILD)
        panel = _panel(qtbot, registry, settings)
        _turn(qtbot, panel)
        panel.undo_stack.push(SetAiPrivacyCommand(panel.graph, {"columns": {
            "x": {"sensitive": True}}}))
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
        assert lines[0]["connection"] == "Local Ollama" and lines[0]["sees"] == "profile"
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
        panel.autonomy_combo.setCurrentIndex(0)      # Advise
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
        settings.setValue("flo/level", disc.SCHEMA)
        panel = _panel(qtbot, registry, settings)
        _turn(qtbot, panel, "hi")
        panel._on_level_chosen(disc.PROFILE)
        assert panel.chat is not None

    def test_switching_connection_starts_a_fresh_chat(self, qtbot, monkeypatch,
                                                      registry, settings, user_dir):
        ScriptedModel(monkeypatch, ["hello"])
        panel = _panel(qtbot, registry, settings)
        _turn(qtbot, panel, "hi")
        panel._on_profile_chosen(panel.profile_combo.findData("web"))
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


class TestPrivacyDialog:
    def test_columns_come_from_cached_outputs(self, qtbot, registry):
        graph = Graph()
        node = registry.instantiate(CSV, (0, 0))
        graph.add_node(node)
        cache = _Cache({node.id: {"table": pd.DataFrame({"name": [1], "sales": [2]})}})
        assert known_columns(graph, cache) == {"name": [node.label],
                                               "sales": [node.label]}

    def test_rules_round_trip(self, qtbot, registry):
        graph = Graph()
        graph.ai_privacy = {"level": 1, "columns": {"name": {"alias": "who"}}}
        dialog = PrivacyDialog(graph, None)
        qtbot.addWidget(dialog)
        assert dialog.privacy() == graph.ai_privacy
        dialog._sensitive[0].setChecked(True)
        assert dialog.privacy()["columns"]["name"] == {"sensitive": True,
                                                       "alias": "who"}

    def test_an_alias_may_not_be_another_columns_name(self, qtbot, registry):
        graph = Graph()
        graph.ai_privacy = {"columns": {"a": {"alias": "b"},
                                        "b": {"sensitive": True}}}
        dialog = PrivacyDialog(graph, None)
        qtbot.addWidget(dialog)
        assert "real name of another column" in dialog.alias_problem()
        dialog.table.item(0, 3).setText("c")
        assert dialog.alias_problem() == ""
        dialog.table.item(1, 3).setText("c")
        assert "both shown as 'c'" in dialog.alias_problem()

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
        loaded.ai_privacy = {"level": 0, "columns": {"name": {"sensitive": True}}}
        window._replace_graph(loaded)
        assert window.graph.ai_privacy == loaded.ai_privacy
        assert window.flo_panel.level() == disc.STRUCTURE
