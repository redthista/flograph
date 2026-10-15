"""flograph.llm: the shared wire code, connection profiles and key store.

No network: requests are caught at `wire._post`/`wire._get`, and the key
store runs against a temp file or a stand-in keyring module.
"""
import json
import os
import stat
import subprocess
import sys

import pytest

from flograph.llm import keys, profiles, wire
from flograph.llm.profiles import Profile, ProfileSet


class _Reply:
    def __init__(self, payload=None, status=200, text=""):
        self._payload = payload
        self.status_code = status
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _record(monkeypatch, replies):
    calls, queue = [], list(replies)

    def fake_post(url, headers, body, timeout, verify):
        calls.append({"url": url, "headers": headers, "body": body,
                      "timeout": timeout, "verify": verify})
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(wire, "_post", fake_post)
    return calls


OK_OPENAI = _Reply({"choices": [{"message": {"content": "ok"}}]})
OK_ANTHROPIC = _Reply({"content": [{"type": "text", "text": "ok"}]})


class TestCandidateUrls:
    def _urls(self, base, provider="openai", path=None):
        conn = wire.Connection(provider=provider, base_url=base)
        return wire.candidate_urls(
            conn, path or ("/messages" if provider == "anthropic"
                           else "/chat/completions"))

    def test_blank_is_the_official_endpoint(self):
        assert self._urls("", "anthropic") == [
            "https://api.anthropic.com/v1/messages"]
        assert self._urls("", "openai") == [
            "https://api.openai.com/v1/chat/completions"]

    def test_v1_root_is_used_directly(self):
        assert self._urls("http://localhost:11434/v1") == [
            "http://localhost:11434/v1/chat/completions"]

    def test_host_root_tries_v1_then_bare(self):
        assert self._urls("https://gw.corp/") == [
            "https://gw.corp/v1/chat/completions",
            "https://gw.corp/chat/completions"]

    def test_pasted_endpoint_is_used_as_is(self):
        url = "https://x.example.com/openai/deployments/gpt4/chat/completions"
        assert self._urls(url + "?api-version=1") == [url + "?api-version=1"]

    def test_chat_url_pasted_for_the_other_format_is_cut_back(self):
        assert self._urls("https://gw.corp/v1/chat/completions", "anthropic") == [
            "https://gw.corp/v1/messages"]

    def test_models_from_a_pasted_chat_url(self):
        assert self._urls("https://gw.corp/v1/chat/completions",
                          path="/models") == ["https://gw.corp/v1/models"]

    def test_openrouter_shape(self):
        assert self._urls("https://openrouter.ai/api/v1") == [
            "https://openrouter.ai/api/v1/chat/completions"]


class TestChatBody:
    def test_anthropic_system_is_top_level(self):
        conn = wire.Connection(provider="anthropic", model="m", max_tokens=99)
        body = wire.chat_body(conn, [{"role": "system", "content": "sys"},
                                     {"role": "user", "content": "hi"}])
        assert body == {"model": "m", "max_tokens": 99, "system": "sys",
                        "messages": [{"role": "user", "content": "hi"}]}

    def test_temperature_only_when_asked_for(self):
        conn = wire.Connection(model="m")
        assert "temperature" not in wire.chat_body(conn, [])
        conn.temperature = 0.2
        assert wire.chat_body(conn, [])["temperature"] == 0.2

    def test_extra_json_outranks_thinking(self):
        conn = wire.Connection(model="m", thinking="off",
                               extra={"reasoning": {"exclude": True}})
        assert wire.chat_body(conn, [])["reasoning"] == {"exclude": True}

    def test_thinking_dialects(self):
        assert wire.thinking_fields("openai", "off", 100) == {
            "reasoning": {"enabled": False}}
        assert wire.thinking_fields("anthropic", "off", 100) == {}
        assert wire.thinking_fields("anthropic", "low", 4096) == {
            "thinking": {"type": "enabled", "budget_tokens": 1024}}
        with pytest.raises(ValueError, match="room to think"):
            wire.thinking_fields("anthropic", "high", 1024)


class TestChat:
    def test_anthropic_headers(self, monkeypatch):
        calls = _record(monkeypatch, [OK_ANTHROPIC])
        wire.chat(wire.Connection(provider="anthropic", model="m",
                                  api_key="k"), [{"role": "user", "content": "x"}])
        headers = calls[0]["headers"]
        assert headers["x-api-key"] == "k"
        assert headers["anthropic-version"] == wire.ANTHROPIC_VERSION
        assert "Authorization" not in headers

    def test_bearer_for_openai(self, monkeypatch):
        calls = _record(monkeypatch, [OK_OPENAI])
        wire.chat(wire.Connection(model="m", api_key="k", verify_ssl=False),
                  [{"role": "user", "content": "x"}])
        assert calls[0]["headers"]["Authorization"] == "Bearer k"
        assert calls[0]["verify"] is False

    def test_400_climb_down_then_success(self, monkeypatch):
        calls = _record(monkeypatch, [
            _Reply(status=400, text="'temperature' is not supported"),
            OK_OPENAI])
        conn = wire.Connection(model="m", temperature=0.2)
        assert wire.chat(conn, []) == "ok"
        assert "temperature" not in calls[1]["body"]

    def test_401_is_not_retried_at_another_url(self, monkeypatch):
        calls = _record(monkeypatch, [_Reply(status=401, text="bad key")])
        with pytest.raises(wire.LLMError, match="API key"):
            wire.chat(wire.Connection(base_url="https://gw.corp", model="m"), [])
        assert len(calls) == 1

    def test_llm_error_is_a_runtime_error(self):
        """The LLM nodes have always raised RuntimeError for API failures."""
        assert issubclass(wire.LLMError, RuntimeError)


class TestReplyText:
    def test_reasoning_content_when_content_is_empty(self):
        data = {"choices": [{"message": {"content": "",
                                         "reasoning_content": "thought"}}]}
        assert wire.reply_text(data, "openai") == "thought"

    def test_refusal_says_so(self):
        data = {"choices": [{"message": {"content": None,
                                         "refusal": "can't help"}}]}
        with pytest.raises(wire.LLMError, match="refused"):
            wire.reply_text(data, "openai")

    def test_wrong_format_hint(self):
        with pytest.raises(wire.LLMError, match="API format"):
            wire.reply_text({"content": [{"type": "text", "text": "x"}]}, "openai")

    def test_anthropic_empty_names_stop_reason(self):
        with pytest.raises(wire.LLMError, match="max_tokens"):
            wire.reply_text({"content": [], "stop_reason": "max_tokens"},
                            "anthropic")


class TestLocality:
    @pytest.mark.parametrize("url, local", [
        ("http://localhost:11434/v1", True),
        ("http://127.0.0.1:1234", True),
        ("http://127.0.0.2", True),
        ("http://[::1]:8080/v1", True),
        ("localhost:1234", True),
        ("http://box.localhost", True),
        ("http://192.168.1.20:11434", False),   # another machine
        ("http://10.0.0.5/v1", False),
        ("https://api.anthropic.com", False),
        ("", False),                            # blank = official, online
    ])
    def test_only_loopback_is_this_pc(self, url, local):
        assert profiles.is_loopback_url(url) is local

    def test_ceiling_defaults_follow_location(self):
        assert Profile(base_url="http://localhost:1/v1").effective_ceiling() == 5
        assert Profile(base_url="https://gw.corp").effective_ceiling() == 1
        assert Profile(base_url="https://gw.corp",
                       location="local").effective_ceiling() == 5
        assert Profile(base_url="http://localhost",
                       location="online").effective_ceiling() == 1

    def test_explicit_ceiling_wins(self):
        assert Profile(base_url="https://gw.corp", ceiling=3).effective_ceiling() == 3

    def test_where_label(self):
        assert Profile(base_url="http://localhost").where_label() == \
            "Local — nothing leaves this PC"
        assert Profile(base_url="", provider="anthropic").where_label() == \
            "Online — api.anthropic.com"


class TestProfileStore:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "p.json"
        work = Profile(name="Work", base_url="https://gw.corp/v1",
                       provider="anthropic", ceiling=2, extra_json='{"a": 1}')
        profiles.save(ProfileSet([Profile(), work], work.id), path)
        loaded = profiles.load(path)
        assert loaded.active().to_dict() == work.to_dict()
        assert len(loaded.profiles) == 2

    def test_missing_file_gives_one_local_profile(self, tmp_path):
        loaded = profiles.load(tmp_path / "none.json")
        assert len(loaded.profiles) == 1
        assert loaded.active().is_local()

    def test_tolerates_unknown_fields_and_bad_values(self, tmp_path):
        path = tmp_path / "p.json"
        path.write_text(json.dumps({"active": "x", "profiles": [
            {"id": "x", "name": "N", "from_the_future": 1, "ceiling": 99,
             "location": "mars"}]}))
        profile = profiles.load(path).active()
        assert profile.ceiling == len(profiles.LEVELS) - 1
        assert profile.location == "auto"

    def test_connection_carries_everything(self):
        profile = Profile(provider="anthropic", base_url=" https://gw/v1 ",
                          model="m", max_tokens=100, thinking="off",
                          extra_json='{"top_k": 3}', verify_ssl=False)
        conn = profile.connection("key", temperature=0.2)
        assert (conn.base_url, conn.api_key, conn.extra, conn.verify_ssl,
                conn.temperature) == ("https://gw/v1", "key", {"top_k": 3},
                                      False, 0.2)

    def test_bad_extra_json_names_the_connection(self):
        with pytest.raises(wire.LLMError, match="Work"):
            Profile(name="Work", extra_json="[1]").extra()


class _FakeKeyring:
    def __init__(self, priority=5, fail=False):
        self.store = {}
        self._fail = fail
        backend = type("Keyring", (), {"priority": priority})
        backend.__module__ = "keyring.backends.SecretService"
        self._backend = backend()

    def get_keyring(self):
        return self._backend

    def get_password(self, service, name):
        return self.store.get((service, name))

    def set_password(self, service, name, value):
        if self._fail:
            raise RuntimeError("the keyring is locked")
        self.store[(service, name)] = value

    def delete_password(self, service, name):
        del self.store[(service, name)]


class TestKeyStore:
    def test_file_store_is_owner_only(self, tmp_path):
        store = keys.KeyStore(file_path=tmp_path / "k.json")
        store.set("a", "secret")
        assert store.get("a") == "secret"
        assert not store.secure
        if os.name == "posix":
            mode = stat.S_IMODE((tmp_path / "k.json").stat().st_mode)
            assert mode == 0o600

    def test_empty_value_deletes(self, tmp_path):
        store = keys.KeyStore(file_path=tmp_path / "k.json")
        store.set("a", "secret")
        store.set("a", "  ")
        assert store.get("a") == ""
        store.delete("never-there")  # no error

    def test_keyring_used_when_present(self):
        ring = _FakeKeyring()
        store = keys.KeyStore(ring)
        store.set("a", "secret")
        assert ring.store[(keys.SERVICE, "a")] == "secret"
        assert store.secure
        assert "Secret Service" in store.where
        store.delete("a")
        store.delete("a")  # already gone is fine
        assert store.get("a") == ""

    def test_refused_write_is_an_error_not_a_quiet_file(self, tmp_path):
        store = keys.KeyStore(_FakeKeyring(fail=True), tmp_path / "k.json")
        with pytest.raises(keys.KeyStoreError, match="locked"):
            store.set("a", "secret")
        assert not (tmp_path / "k.json").exists()

    def test_no_real_keychain_means_the_file(self, monkeypatch):
        monkeypatch.delenv("FLOGRAPH_KEYS", raising=False)
        monkeypatch.setitem(sys.modules, "keyring", _FakeKeyring(priority=0))
        assert keys._keyring_backend() is None
        monkeypatch.setitem(sys.modules, "keyring", None)
        assert keys._keyring_backend() is None

    def test_env_forces_the_file(self, monkeypatch):
        monkeypatch.setenv("FLOGRAPH_KEYS", "file")
        monkeypatch.setitem(sys.modules, "keyring", _FakeKeyring())
        assert keys._keyring_backend() is None


def test_llm_package_is_qt_free():
    """Node scripts and the headless runner import this; it must not drag
    in Qt, pandas or an HTTP library just by being imported."""
    code = ("import sys, flograph.llm.wire, flograph.llm.profiles, "
            "flograph.llm.keys; "
            "bad = [m for m in ('PySide6', 'pandas', 'httpx', 'keyring') "
            "if m in sys.modules]; print(','.join(bad))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, check=True).stdout.strip()
    assert out == ""
