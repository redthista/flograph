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
        dialog._model.setText("qwen2.5-coder")
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
        dialog._model.setText("")
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
        assert dialog._model.text() == "qwen2.5-coder"
