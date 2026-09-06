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


class _Reply:
    """A response with a body, so error paths can be checked too."""

    def __init__(self, payload=None, status=200, text=""):
        self._payload = payload
        self.status_code = status
        self.text = text or ""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _record_posts(monkeypatch, replies):
    """Patch requests.post with a scripted list of replies; return the log."""
    import requests

    calls = []
    queue = list(replies)

    def fake_post(url, headers=None, json=None, timeout=None, verify=None):
        calls.append({"url": url, "headers": headers, "json": json})
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(requests, "post", fake_post)
    return calls


class TestAnthropicFormat:
    """A work gateway may speak /messages, and GET /models looks identical
    either way — so listing models can succeed while chat 404s."""

    def _config(self):
        return ai.LLMConfig(
            base_url="https://gw.corp/v1", model="claude-x",
            api_key="secret", provider="anthropic")

    def test_posts_messages_endpoint_with_api_key_header(self, monkeypatch):
        calls = _record_posts(
            monkeypatch, [_Reply({"content": [{"type": "text", "text": "hi"}]})])

        result = ai.chat_completion(
            [{"role": "system", "content": "sys"},
             {"role": "user", "content": "ask"}], self._config())

        assert result == "hi"
        assert calls[0]["url"] == "https://gw.corp/v1/messages"
        assert calls[0]["headers"]["x-api-key"] == "secret"
        assert "Authorization" not in calls[0]["headers"]
        assert calls[0]["headers"]["anthropic-version"]
        # system prompt is a top-level field, not a message, in this format
        assert calls[0]["json"]["system"] == "sys"
        assert calls[0]["json"]["messages"] == [{"role": "user", "content": "ask"}]
        assert calls[0]["json"]["max_tokens"] == ai.DEFAULT_MAX_TOKENS


class TestEndpointShapes:
    def test_full_chat_url_in_base_is_not_doubled(self, monkeypatch):
        calls = _record_posts(
            monkeypatch, [_Reply({"choices": [{"message": {"content": "ok"}}]})])

        ai.chat_completion(
            [{"role": "user", "content": "hi"}],
            ai.LLMConfig(base_url="https://gw.corp/v1/chat/completions"))

        assert calls[0]["url"] == "https://gw.corp/v1/chat/completions"

    def test_query_string_stays_at_the_end(self, monkeypatch):
        """Some gateways require ?api-version= on every call; it must not
        end up in the middle of the path."""
        calls = _record_posts(
            monkeypatch, [_Reply({"choices": [{"message": {"content": "ok"}}]})])

        ai.chat_completion(
            [{"role": "user", "content": "hi"}],
            ai.LLMConfig(base_url="https://x.example.com/openai/deployments/"
                                  "gpt4/chat/completions?api-version=2026-01-01"))

        assert calls[0]["url"] == (
            "https://x.example.com/openai/deployments/gpt4/chat/completions"
            "?api-version=2026-01-01")

    def test_404_falls_back_to_versioned_path(self, monkeypatch):
        calls = _record_posts(monkeypatch, [
            _Reply(status=404, text="not found"),
            _Reply({"choices": [{"message": {"content": "ok"}}]}),
        ])

        result = ai.chat_completion(
            [{"role": "user", "content": "hi"}],
            ai.LLMConfig(base_url="https://gw.corp"))

        assert result == "ok"
        assert [call["url"] for call in calls] == [
            "https://gw.corp/chat/completions",
            "https://gw.corp/v1/chat/completions",
        ]


class TestErrorReporting:
    def test_server_explanation_is_in_the_message(self, monkeypatch):
        _record_posts(monkeypatch, [_Reply(
            status=400,
            text='{"error": {"message": "model not deployed here"}}')])

        with pytest.raises(ai.LLMError) as excinfo:
            ai.chat_completion([{"role": "user", "content": "hi"}])

        message = str(excinfo.value)
        assert "400" in message
        assert "model not deployed here" in message

    def test_401_suggests_key_and_format(self, monkeypatch):
        _record_posts(monkeypatch, [_Reply(status=401, text="unauthorized")])

        with pytest.raises(ai.LLMError, match="API key"):
            ai.chat_completion([{"role": "user", "content": "hi"}])

    def test_400_is_not_retried_at_the_other_url(self, monkeypatch):
        calls = _record_posts(monkeypatch, [_Reply(status=400, text="bad")])

        with pytest.raises(ai.LLMError):
            ai.chat_completion([{"role": "user", "content": "hi"}],
                               ai.LLMConfig(base_url="https://gw.corp"))

        assert len(calls) == 1


class TestParameterClimbDown:
    """Hosted models reject parts of the request other servers require;
    the server names the parameter, so drop that one and retry."""

    def test_rejected_temperature_is_dropped(self, monkeypatch):
        calls = _record_posts(monkeypatch, [
            _Reply(status=400, text="Unsupported value: 'temperature' "
                                    "does not support 0.2"),
            _Reply({"choices": [{"message": {"content": "ok"}}]}),
        ])

        assert ai.chat_completion([{"role": "user", "content": "hi"}]) == "ok"
        assert "temperature" in calls[0]["json"]
        assert "temperature" not in calls[1]["json"]

    def test_max_tokens_is_renamed_when_asked(self, monkeypatch):
        calls = _record_posts(monkeypatch, [
            _Reply(status=400, text="Use 'max_completion_tokens' instead"),
            _Reply({"choices": [{"message": {"content": "ok"}}]}),
        ])

        assert ai.chat_completion([{"role": "user", "content": "hi"}]) == "ok"
        assert calls[1]["json"]["max_completion_tokens"] == ai.DEFAULT_MAX_TOKENS
        assert "max_tokens" not in calls[1]["json"]

    def test_unrelated_400_is_not_retried_forever(self, monkeypatch):
        calls = _record_posts(
            monkeypatch, [_Reply(status=400, text="model does not exist")])

        with pytest.raises(ai.LLMError, match="model does not exist"):
            ai.chat_completion([{"role": "user", "content": "hi"}])

        assert len(calls) == 1


class TestReplyShapes:
    def test_content_parts_list_is_joined(self, monkeypatch):
        _record_posts(monkeypatch, [_Reply(
            {"choices": [{"message": {"content": [
                {"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}}]})])

        assert ai.chat_completion([{"role": "user", "content": "hi"}]) == "ab"

    def test_empty_reply_names_the_finish_reason(self, monkeypatch):
        _record_posts(monkeypatch, [_Reply(
            {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]})])

        with pytest.raises(ai.LLMError, match="length"):
            ai.chat_completion([{"role": "user", "content": "hi"}])


class TestCodeExtraction:
    def _reply(self, monkeypatch, content):
        _record_posts(
            monkeypatch, [_Reply({"choices": [{"message": {"content": content}}]})])

    def test_prose_around_the_fence_is_dropped(self, monkeypatch):
        self._reply(monkeypatch,
                    f"Sure! Here you go:\n\n```python\n{VALID_NODE}```\n\nHope that helps.")

        code = ai.suggest_node_update("old", "do it")

        assert code.startswith('"""Format Date')
        assert "Hope that helps" not in code

    def test_reasoning_block_is_dropped(self, monkeypatch):
        self._reply(monkeypatch,
                    f"<think>The user wants ```python fenced``` code</think>\n{VALID_NODE}")

        code = ai.suggest_node_update("old", "do it")

        assert code.startswith('"""Format Date')
        assert "<think>" not in code
