"""Local-LLM node assistant (flograph.ai) — no real network calls."""
import sys

import pytest

from flograph import ai

VALID_NODE = '''"""Format Date

Reformat a date column."""
NODE = {
    "label": "Format Date",
    "category": "Transform",
    "inputs": [("table", "dataframe")],
    "outputs": [("result", "dataframe")],
}
PARAMS = [
    {"name": "column", "type": "string", "label": "Column", "default": "date"},
]


def run(ctx, table):
    return {"result": table}
'''


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


class TestChatCompletion:
    def test_posts_openai_shape_and_returns_content(self, monkeypatch):
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None, verify=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            captured["timeout"] = timeout
            captured["verify"] = verify
            return _FakeResponse(
                {"choices": [{"message": {"content": "hello"}}]}
            )

        import requests
        monkeypatch.setattr(requests, "post", fake_post)

        result = ai.chat_completion([{"role": "user", "content": "hi"}])

        assert result == "hello"
        assert captured["url"] == f"{ai.DEFAULT_BASE_URL}/chat/completions"
        assert captured["json"]["model"] == ai.DEFAULT_MODEL
        assert captured["json"]["messages"] == [{"role": "user", "content": "hi"}]
        assert "Authorization" not in captured["headers"]
        assert captured["verify"] is True

    def test_sends_api_key_when_configured(self, monkeypatch):
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None, verify=None):
            captured["headers"] = headers
            return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

        import requests
        monkeypatch.setattr(requests, "post", fake_post)

        config = ai.LLMConfig(api_key="secret")
        ai.chat_completion([{"role": "user", "content": "hi"}], config)

        assert captured["headers"]["Authorization"] == "Bearer secret"

    def test_verify_ssl_false_disables_verification(self, monkeypatch):
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None, verify=None):
            captured["verify"] = verify
            return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

        import requests
        monkeypatch.setattr(requests, "post", fake_post)

        config = ai.LLMConfig(verify_ssl=False)
        ai.chat_completion([{"role": "user", "content": "hi"}], config)

        assert captured["verify"] is False

    def test_missing_requests_raises_actionable_error(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "requests", None)

        with pytest.raises(ai.LLMError, match="requests"):
            ai.chat_completion([{"role": "user", "content": "hi"}])

    def test_connection_failure_raises_llm_error(self, monkeypatch):
        import requests

        def fake_post(*a, **k):
            raise requests.ConnectionError("refused")

        monkeypatch.setattr(requests, "post", fake_post)

        with pytest.raises(ai.LLMError, match="could not reach"):
            ai.chat_completion([{"role": "user", "content": "hi"}])

    def test_malformed_response_raises_llm_error(self, monkeypatch):
        import requests
        monkeypatch.setattr(
            requests, "post", lambda *a, **k: _FakeResponse({"nope": True})
        )

        with pytest.raises(ai.LLMError, match="unexpected response"):
            ai.chat_completion([{"role": "user", "content": "hi"}])


class TestListModels:
    def test_returns_sorted_model_ids(self, monkeypatch):
        captured = {}

        def fake_get(url, headers=None, timeout=None, verify=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["timeout"] = timeout
            captured["verify"] = verify
            return _FakeResponse(
                {"data": [{"id": "qwen2.5-coder"}, {"id": "llama3.1"}]}
            )

        import requests
        monkeypatch.setattr(requests, "get", fake_get)

        result = ai.list_models()

        assert result == ["llama3.1", "qwen2.5-coder"]
        assert captured["url"] == f"{ai.DEFAULT_BASE_URL}/models"
        assert captured["timeout"] == ai.MODELS_TIMEOUT
        assert "Authorization" not in captured["headers"]
        assert captured["verify"] is True

    def test_sends_api_key_when_configured(self, monkeypatch):
        captured = {}

        def fake_get(url, headers=None, timeout=None, verify=None):
            captured["headers"] = headers
            return _FakeResponse({"data": []})

        import requests
        monkeypatch.setattr(requests, "get", fake_get)

        ai.list_models(ai.LLMConfig(api_key="secret"))
        assert captured["headers"]["Authorization"] == "Bearer secret"

    def test_verify_ssl_false_disables_verification(self, monkeypatch):
        captured = {}

        def fake_get(url, headers=None, timeout=None, verify=None):
            captured["verify"] = verify
            return _FakeResponse({"data": []})

        import requests
        monkeypatch.setattr(requests, "get", fake_get)

        ai.list_models(ai.LLMConfig(verify_ssl=False))
        assert captured["verify"] is False

    def test_missing_requests_raises_actionable_error(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "requests", None)
        with pytest.raises(ai.LLMError, match="requests"):
            ai.list_models()

    def test_connection_failure_raises_llm_error(self, monkeypatch):
        import requests

        def fake_get(*a, **k):
            raise requests.ConnectionError("refused")

        monkeypatch.setattr(requests, "get", fake_get)
        with pytest.raises(ai.LLMError, match="could not reach"):
            ai.list_models()

    def test_malformed_response_raises_llm_error(self, monkeypatch):
        import requests
        monkeypatch.setattr(
            requests, "get", lambda *a, **k: _FakeResponse({"nope": True})
        )
        with pytest.raises(ai.LLMError, match="unexpected response"):
            ai.list_models()


class TestSuggestNodeUpdate:
    def _mock_reply(self, monkeypatch, content):
        import requests
        monkeypatch.setattr(
            requests, "post",
            lambda *a, **k: _FakeResponse(
                {"choices": [{"message": {"content": content}}]}
            ),
        )

    def test_returns_validated_source(self, monkeypatch):
        self._mock_reply(monkeypatch, VALID_NODE)
        result = ai.suggest_node_update(VALID_NODE, "no-op edit")
        assert "def run(ctx, table)" in result

    def test_strips_markdown_code_fence(self, monkeypatch):
        self._mock_reply(monkeypatch, f"```python\n{VALID_NODE}```")
        result = ai.suggest_node_update(VALID_NODE, "no-op edit")
        assert not result.startswith("```")
        assert "NODE = {" in result

    def test_empty_instruction_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            ai.suggest_node_update(VALID_NODE, "   ")

    def test_invalid_llm_code_raises_llm_error(self, monkeypatch):
        self._mock_reply(monkeypatch, "this is not a node script at all")
        with pytest.raises(ai.LLMError, match="node contract"):
            ai.suggest_node_update(VALID_NODE, "break it")
