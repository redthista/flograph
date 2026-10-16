"""Token counts on Flo's receipt: read from each reply in both formats,
streamed or not, asked for on an OpenAI-format stream (and asked again
without when a server refuses), added up per reply and per chat, and
priced only at prices the user typed into the connection."""
import pytest

from flograph.flo import receipt as receipts
from flograph.llm import profiles, toolcall, wire
from flograph.llm.profiles import Profile, ProfileSet
from flograph.ui.flo.sent_view import format_requests

from tests.test_flo import BUILD, ScriptedModel, _Reply
from tests.test_flo_panel import LOCAL, _panel, _turn, settings, user_dir  # noqa: F401
from tests.test_llm_stream import ANTHROPIC, OPENAI, TOOLS, _SSE, _chunks, _serve

USER = [{"role": "user", "content": "hi"}]


class TestUsageOf:
    def test_openai_words(self):
        data = {"usage": {"prompt_tokens": 120, "completion_tokens": 7}}
        assert wire.usage_of(data, "openai") == {"input": 120, "output": 7}

    def test_anthropic_words_count_cached_prompt_as_sent(self):
        data = {"usage": {"input_tokens": 10, "output_tokens": 5,
                          "cache_read_input_tokens": 300,
                          "cache_creation_input_tokens": 40}}
        assert wire.usage_of(data, "anthropic") == {"input": 350, "output": 5}

    def test_a_gateway_mixing_the_formats_words(self):
        data = {"usage": {"input_tokens": 9, "output_tokens": 2}}
        assert wire.usage_of(data, "openai") == {"input": 9, "output": 2}

    @pytest.mark.parametrize("data", [{}, {"usage": None}, {"usage": {}},
                                      {"usage": {"total": 4}}, "x"])
    def test_no_count_is_none_not_zero(self, data):
        assert wire.usage_of(data, "openai") is None


class TestStreamed:
    def test_openai_asks_for_the_count_and_reads_it(self, monkeypatch):
        events = _chunks({"content": "ok"})
        events.insert(-1, {"choices": [], "usage": {"prompt_tokens": 50,
                                                    "completion_tokens": 3}})
        sent = _serve(monkeypatch, _SSE(events))
        reply = toolcall.chat_with_tools(OPENAI, USER, TOOLS, on_text=lambda t: None)
        assert sent[0]["stream_options"] == {"include_usage": True}
        assert reply.usage == {"input": 50, "output": 3}

    def test_anthropic_running_output_total(self, monkeypatch):
        sent = _serve(monkeypatch, _SSE([
            {"type": "message_start", "message": {"usage": {
                "input_tokens": 80, "output_tokens": 1}}},
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "Hi"}},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
             "usage": {"output_tokens": 12}},
        ]))
        reply = toolcall.chat_with_tools(ANTHROPIC, USER, TOOLS,
                                         on_text=lambda t: None)
        assert "stream_options" not in sent[0]
        assert reply.usage == {"input": 80, "output": 12}

    def test_no_count_in_the_stream_is_none(self, monkeypatch):
        _serve(monkeypatch, _SSE(_chunks({"content": "ok"})))
        reply = toolcall.chat_with_tools(OPENAI, USER, TOOLS, on_text=lambda t: None)
        assert reply.usage is None

    @pytest.mark.parametrize("status, text", [
        (400, "Unrecognized request argument supplied: stream_options"),
        (422, "Extra inputs are not permitted"),
        (400, "bad request"),
    ])
    def test_a_server_refusing_it_is_asked_again_without(self, monkeypatch,
                                                         status, text):
        sent = _serve(monkeypatch, _SSE(status=status, text=text),
                      _SSE(_chunks({"content": "ok"})))
        reply = toolcall.chat_with_tools(OPENAI, USER, TOOLS, on_text=lambda t: None)
        assert reply.text == "ok" and reply.usage is None
        assert "stream_options" in sent[0]
        assert "stream_options" not in sent[1] and sent[1]["stream"] is True

    def test_a_tools_refusal_is_not_mistaken_for_it(self, monkeypatch):
        sent = _serve(monkeypatch,
                      _SSE(status=400, text="model does not support tools"),
                      _SSE(_chunks({"content": "plain"})))
        reply = toolcall.chat_with_tools(OPENAI, USER, TOOLS, on_text=lambda t: None)
        assert reply.mode == "json"
        assert "stream_options" in sent[1]      # the fallback still asks

    def test_extra_request_json_can_say_otherwise(self, monkeypatch):
        conn = wire.Connection(provider="openai", model="m",
                               base_url="http://localhost:1/v1",
                               extra={"stream_options": {"include_usage": False}})
        sent = _serve(monkeypatch, _SSE(_chunks({"content": "ok"})))
        toolcall.chat_with_tools(conn, USER, TOOLS, on_text=lambda t: None)
        assert sent[0]["stream_options"] == {"include_usage": False}

    def test_unstreamed_requests_are_unchanged(self, monkeypatch):
        bodies = []
        monkeypatch.setattr(wire, "_post", lambda url, h, body, t, v: bodies.append(
            body) or _Reply({"choices": [{"message": {"content": "ok"}}],
                             "usage": {"prompt_tokens": 4, "completion_tokens": 1}}))
        reply = toolcall.chat_with_tools(OPENAI, USER, TOOLS)
        assert "stream_options" not in bodies[0] and "stream" not in bodies[0]
        assert reply.usage == {"input": 4, "output": 1}


def _entry(spent=None, made=0):
    entry = {"messages": [{"role": "user", "content": "x"}]}
    if spent is not None:
        entry["usage"] = {"input": spent, "output": made}
    else:
        entry["usage"] = None
    return entry


def _receipt(entries, chat=(), prices=None):
    from flograph.core import ai_disclosure as disc
    return receipts.build(entries, [], disc.Disclosure(disc.SCHEMA, None),
                          destination="ai.example.com", local=False,
                          chat=chat or entries, prices=prices)


class TestReceipt:
    def test_the_line_ends_with_the_count(self):
        receipt = _receipt([_entry(4210, 90), _entry(14_300, 1120)])
        assert receipt.summary().endswith("no rows. 18.5k tokens in, 1,210 out.")
        assert "Tokens: 18,510 in, 1,210 out, over 2 requests." in receipt.details()

    def test_a_partial_count_says_at_least(self):
        receipt = _receipt([_entry(500, 10), _entry()])
        assert "At least 500 tokens in, 10 out." in receipt.summary()
        assert any("(1 of them gave a count)" in line for line in receipt.details())

    def test_no_count_is_said_not_guessed(self):
        receipt = _receipt([_entry(), _entry()])
        assert "tokens" not in receipt.summary()
        assert any("didn't say how many" in line for line in receipt.details())

    def test_cost_only_at_prices_typed_in(self):
        entries = [_entry(1_000_000, 100_000)]
        assert "≈" not in _receipt(entries).summary()
        receipt = _receipt(entries, prices=(3.0, 15.0, "$"))
        assert receipt.summary().endswith("(≈ $4.50).")
        assert any("$3 in, $15 out per million" in line
                   for line in receipt.details())
        assert "under £0.01" in _receipt([_entry(100, 10)],
                                         prices=(3.0, 15.0, "£")).summary()

    def test_the_chat_so_far(self):
        first, second = _entry(1000, 50), _entry(3000, 60)
        receipt = _receipt([second], chat=[first, second], prices=(1.0, 2.0, "€"))
        assert any(line.startswith("This chat so far: 4,000 tokens in, 110 out")
                   for line in receipt.details())
        alone = _receipt([second])
        assert not any("so far" in line for line in alone.details())

    def test_short_counts(self):
        assert [receipts._short(n) for n in (812, 4210, 18_400, 1_250_000)] == \
            ["812", "4,210", "18.4k", "1.2M"]


class TestSentView:
    def test_each_request_shows_its_count(self):
        text = format_requests([_entry(4210, 90), _entry()], "ai.example.com")
        assert "Tokens: 4,210 in, 90 out" in text
        assert "Tokens: not reported by the server" in text

    def test_a_request_not_answered_yet_shows_none(self):
        text = format_requests([{"messages": []}], "ai.example.com")
        assert "Tokens" not in text


class TestProfilePrices:
    def test_unset_by_default(self):
        assert Profile().prices() is None

    def test_one_price_is_enough(self):
        assert Profile(price_out=15.0).prices() == (0.0, 15.0, "$")

    def test_bad_saved_values_are_dropped(self):
        profile = Profile.from_dict({"price_in": "abc", "price_out": -2,
                                     "currency": "GBP-long-name"})
        assert profile.prices() is None and profile.currency == "GBP-long"

    def test_prices_are_not_part_of_what_a_chat_depends_on(self):
        assert Profile(id="a", price_in=3.0).chat_dict() == \
            Profile(id="a").chat_dict()


class _Counted(ScriptedModel):
    """The scripted model, with a token count on every reply."""

    def post(self, url, headers, body, timeout, verify):
        reply = super().post(url, headers, body, timeout, verify)
        if reply.status_code == 200:
            reply._payload["usage"] = {"prompt_tokens": 1000,
                                       "completion_tokens": 20}
        return reply


class TestPanel:
    def test_a_reply_counts_its_requests(self, qtbot, monkeypatch, registry,
                                         settings, user_dir):
        _Counted(monkeypatch, BUILD)
        panel = _panel(qtbot, registry, settings)
        _turn(qtbot, panel)
        receipt = panel._turns[0]["receipt"]
        assert receipt.requests == 5 and receipt.counted == 5
        assert receipt.summary().endswith("5,000 tokens in, 100 out.")
        label = panel._turns[0]["receipt_label"]
        assert "5,000 tokens in" in label.text()

    def test_cost_from_the_connection(self, qtbot, monkeypatch, registry,
                                      settings, user_dir):
        _Counted(monkeypatch, ["hello"])
        panel = _panel(qtbot, registry, settings)
        priced = LOCAL.copy(price_in=2.0, price_out=10.0, currency="$")
        profiles.save(ProfileSet([priced], priced.id))
        panel.reload_profiles()
        _turn(qtbot, panel, "hi")
        assert panel._turns[0]["receipt"].summary().endswith(
            "1,000 tokens in, 20 out (under $0.01).")

    def test_editing_prices_keeps_the_chat(self, qtbot, monkeypatch, registry,
                                           settings, user_dir):
        _Counted(monkeypatch, ["hello", "again"])
        panel = _panel(qtbot, registry, settings)
        _turn(qtbot, panel, "hi")
        priced = LOCAL.copy(price_in=2.0, price_out=10.0)
        profiles.save(ProfileSet([priced, profiles.load().get("web")], priced.id))
        panel.reload_profiles()
        assert panel.chat is not None
        _turn(qtbot, panel, "and?")
        details = panel._turns[1]["receipt"].details()
        assert any(line.startswith("This chat so far: 2,000 tokens in, 40 out")
                   for line in details)


class TestSettingsDialog:
    @pytest.fixture(autouse=True)
    def _isolated(self, tmp_path, monkeypatch):
        from PySide6.QtCore import QSettings
        from flograph.ui import ai_settings_dialog as mod
        ini = str(tmp_path / "s.ini")
        monkeypatch.setattr(mod, "QSettings",
                            lambda *a, **k: QSettings(ini, QSettings.IniFormat))
        monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path / "user"))
        monkeypatch.setenv("FLOGRAPH_KEYS", "file")

    def test_prices_save_and_show(self, qtbot):
        from flograph.ui import ai_settings_dialog as mod
        dialog = mod.AiSettingsDialog()
        qtbot.addWidget(dialog)
        dialog._price_in.setText("$3")
        dialog._price_out.setText("15,5")
        dialog._currency.setText("£")
        dialog._save()
        saved = profiles.load().active()
        assert saved.prices() == (3.0, 15.5, "£")
        again = mod.AiSettingsDialog()
        qtbot.addWidget(again)
        assert again._price_in.text() == "3" and again._price_out.text() == "15.5"

    def test_blank_is_no_price(self, qtbot):
        from flograph.ui import ai_settings_dialog as mod
        assert mod._price_value("") is None and mod._price_value("free") is None
        assert mod._price_value("1,000.50") == 1000.5
