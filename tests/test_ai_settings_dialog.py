"""AI Assistant settings: QSettings-backed load/save, kept off the real
settings store (avoid polluting the developer's actual flograph.conf)."""
import pytest
from PySide6.QtCore import QSettings

from flograph.ai import DEFAULT_BASE_URL, DEFAULT_MODEL
from flograph.ui import ai_settings_dialog as mod


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))


class TestLoadLlmConfig:
    def test_defaults_when_nothing_saved(self):
        config = mod.load_llm_config()
        assert config.base_url == DEFAULT_BASE_URL
        assert config.model == DEFAULT_MODEL
        assert config.api_key is None

    def test_reflects_saved_values(self):
        settings = mod.QSettings()
        settings.setValue("ai/base_url", "http://localhost:1234/v1")
        settings.setValue("ai/model", "qwen2.5-coder")
        settings.setValue("ai/api_key", "sk-test")

        config = mod.load_llm_config()
        assert config.base_url == "http://localhost:1234/v1"
        assert config.model == "qwen2.5-coder"
        assert config.api_key == "sk-test"

    def test_blank_api_key_is_none(self):
        settings = mod.QSettings()
        settings.setValue("ai/api_key", "")
        assert mod.load_llm_config().api_key is None


class TestAiSettingsDialog:
    def test_save_persists_fields(self, qtbot):
        dialog = mod.AiSettingsDialog()
        qtbot.addWidget(dialog)
        dialog._base_url.setText("http://localhost:1234/v1")
        dialog._model.setCurrentText("qwen2.5-coder")
        dialog._api_key.setText("sk-test")
        dialog._save()

        config = mod.load_llm_config()
        assert config.base_url == "http://localhost:1234/v1"
        assert config.model == "qwen2.5-coder"
        assert config.api_key == "sk-test"

    def test_blank_fields_fall_back_to_defaults_not_empty_strings(self, qtbot):
        dialog = mod.AiSettingsDialog()
        qtbot.addWidget(dialog)
        dialog._base_url.setText("   ")
        dialog._model.setCurrentText("")
        dialog._save()

        config = mod.load_llm_config()
        assert config.base_url == DEFAULT_BASE_URL
        assert config.model == DEFAULT_MODEL

    def test_cancel_does_not_persist(self, qtbot):
        dialog = mod.AiSettingsDialog()
        qtbot.addWidget(dialog)
        dialog._base_url.setText("http://localhost:1234/v1")
        dialog.reject()

        assert mod.load_llm_config().base_url == DEFAULT_BASE_URL

    def test_prefills_from_existing_settings(self, qtbot):
        settings = mod.QSettings()
        settings.setValue("ai/base_url", "http://localhost:1234/v1")
        settings.setValue("ai/model", "qwen2.5-coder")

        dialog = mod.AiSettingsDialog()
        qtbot.addWidget(dialog)
        assert dialog._base_url.text() == "http://localhost:1234/v1"
        assert dialog._model.currentText() == "qwen2.5-coder"


class TestInfoButton:
    def test_click_shows_info_message_box(self, qtbot, monkeypatch):
        dialog = mod.AiSettingsDialog()
        qtbot.addWidget(dialog)

        calls = []
        monkeypatch.setattr(
            mod.QMessageBox, "information",
            staticmethod(lambda *a, **k: calls.append(a)))

        dialog._info_btn.click()

        assert len(calls) == 1
        _parent, title, text = calls[0]
        assert title == "How the AI Assistant Works"
        assert "node's source code" in text
        assert "NOT sent" in text

    def test_info_button_labelled_for_what_it_does(self, qtbot):
        dialog = mod.AiSettingsDialog()
        qtbot.addWidget(dialog)
        assert dialog._info_btn.text() == "What data is sent?"


class TestFetchModelsButton:
    def _dialog(self, qtbot):
        dialog = mod.AiSettingsDialog()
        qtbot.addWidget(dialog)
        return dialog

    def test_fetch_success_populates_combo_and_keeps_current_selection(
            self, qtbot, monkeypatch):
        dialog = self._dialog(qtbot)
        dialog._model.setCurrentText("llama3.1")
        monkeypatch.setattr(
            mod.ai, "list_models",
            lambda config: ["llama3.1", "qwen2.5-coder"])

        dialog._fetch_models()

        items = [dialog._model.itemText(i) for i in range(dialog._model.count())]
        assert items == ["llama3.1", "qwen2.5-coder"]
        assert dialog._model.currentText() == "llama3.1"
        assert dialog._fetch_models_btn.isEnabled()

    def test_fetch_success_falls_back_to_first_when_current_not_listed(
            self, qtbot, monkeypatch):
        dialog = self._dialog(qtbot)
        dialog._model.setCurrentText("something-else")
        monkeypatch.setattr(
            mod.ai, "list_models",
            lambda config: ["llama3.1", "qwen2.5-coder"])

        dialog._fetch_models()

        assert dialog._model.currentText() == "llama3.1"

    def test_fetch_uses_currently_typed_fields_not_saved_settings(
            self, qtbot, monkeypatch):
        dialog = self._dialog(qtbot)
        dialog._base_url.setText("http://localhost:1234/v1")
        dialog._api_key.setText("sk-test")
        captured = {}

        def fake_list_models(config):
            captured["base_url"] = config.base_url
            captured["api_key"] = config.api_key
            return ["m"]

        monkeypatch.setattr(mod.ai, "list_models", fake_list_models)
        dialog._fetch_models()

        assert captured["base_url"] == "http://localhost:1234/v1"
        assert captured["api_key"] == "sk-test"

    def test_fetch_failure_shows_warning_and_keeps_current_selection(
            self, qtbot, monkeypatch):
        dialog = self._dialog(qtbot)
        dialog._model.setCurrentText("llama3.1")

        def boom(config):
            raise mod.ai.LLMError("could not reach local LLM")

        monkeypatch.setattr(mod.ai, "list_models", boom)
        warnings = []
        monkeypatch.setattr(
            mod.QMessageBox, "warning",
            staticmethod(lambda *a, **k: warnings.append(a)))

        dialog._fetch_models()

        assert warnings
        assert dialog._model.currentText() == "llama3.1"
        assert dialog._fetch_models_btn.isEnabled()
