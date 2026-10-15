"""AI Assistant settings: named connections in the user folder, keys in a
key store, the pre-profile QSettings connection migrated on first use — all
kept off the real settings, profiles and keychain."""
import pytest
from PySide6.QtCore import QSettings

from flograph.ai import DEFAULT_BASE_URL, DEFAULT_MODEL
from flograph.llm import keys, profiles
from flograph.ui import ai_settings_dialog as mod


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")
    monkeypatch.setattr(
        mod, "QSettings",
        lambda *a, **k: QSettings(ini_path, QSettings.IniFormat))
    monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path / "user"))
    monkeypatch.setenv("FLOGRAPH_KEYS", "file")


class TestLoadLlmConfig:
    def test_defaults_when_nothing_saved(self):
        config = mod.load_llm_config()
        assert config.base_url == DEFAULT_BASE_URL
        assert config.model == DEFAULT_MODEL
        assert config.api_key is None
        assert config.verify_ssl is True

    def test_reflects_saved_values(self):
        settings = mod.QSettings()
        settings.setValue("ai/base_url", "http://localhost:1234/v1")
        settings.setValue("ai/model", "qwen2.5-coder")
        settings.setValue("ai/api_key", "sk-test")
        settings.setValue("ai/verify_ssl", False)

        config = mod.load_llm_config()
        assert config.base_url == "http://localhost:1234/v1"
        assert config.model == "qwen2.5-coder"
        assert config.api_key == "sk-test"
        assert config.verify_ssl is False

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
        dialog._verify_ssl.setChecked(False)
        dialog._save()

        config = mod.load_llm_config()
        assert config.base_url == "http://localhost:1234/v1"
        assert config.model == "qwen2.5-coder"
        assert config.api_key == "sk-test"
        assert config.verify_ssl is False

    def test_verify_ssl_defaults_checked(self, qtbot):
        dialog = mod.AiSettingsDialog()
        qtbot.addWidget(dialog)
        assert dialog._verify_ssl.isChecked()

    def test_blank_base_url_means_the_official_endpoint(self, qtbot):
        """Blank is a real choice now — an Anthropic connection needs no
        address typed — so it is kept blank, not replaced by Ollama's."""
        dialog = mod.AiSettingsDialog()
        qtbot.addWidget(dialog)
        dialog._base_url.setText("   ")
        dialog._model.setCurrentText("")
        dialog._save()

        config = mod.load_llm_config()
        assert config.base_url == ""
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
        dialog._verify_ssl.setChecked(False)
        captured = {}

        def fake_list_models(config):
            captured["base_url"] = config.base_url
            captured["api_key"] = config.api_key
            captured["verify_ssl"] = config.verify_ssl
            return ["m"]

        monkeypatch.setattr(mod.ai, "list_models", fake_list_models)
        dialog._fetch_models()

        assert captured["base_url"] == "http://localhost:1234/v1"
        assert captured["api_key"] == "sk-test"
        assert captured["verify_ssl"] is False

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


class TestApiFormat:
    """Which wire format the server speaks is the one thing fetching models
    can't tell you — both formats answer GET /models the same way."""

    def test_defaults_to_openai_compatible(self, qtbot):
        assert mod.load_llm_config().provider == "openai"

    def test_save_persists_selected_format(self, qtbot):
        dialog = mod.AiSettingsDialog()
        qtbot.addWidget(dialog)
        dialog._provider.setCurrentIndex(
            dialog._provider.findData("anthropic"))
        dialog._save()

        assert mod.load_llm_config().provider == "anthropic"

    def test_prefills_from_existing_settings(self, qtbot):
        mod.QSettings().setValue("ai/provider", "anthropic")

        dialog = mod.AiSettingsDialog()
        qtbot.addWidget(dialog)
        assert dialog._provider.currentData() == "anthropic"

    def test_unknown_saved_format_falls_back_to_first(self, qtbot):
        mod.QSettings().setValue("ai/provider", "martian")

        dialog = mod.AiSettingsDialog()
        qtbot.addWidget(dialog)
        assert dialog._provider.currentData() == "openai"


class TestSendTestMessage:
    def _dialog(self, qtbot):
        dialog = mod.AiSettingsDialog()
        qtbot.addWidget(dialog)
        return dialog

    def test_sends_with_the_values_currently_typed(self, qtbot, monkeypatch):
        dialog = self._dialog(qtbot)
        dialog._base_url.setText("https://gw.corp/v1")
        dialog._model.setCurrentText("gpt-x")
        dialog._provider.setCurrentIndex(
            dialog._provider.findData("anthropic"))

        captured = {}

        def fake_chat(messages, config):
            captured["messages"] = messages
            captured["config"] = config
            return "OK"

        monkeypatch.setattr(mod.ai, "chat_completion", fake_chat)
        monkeypatch.setattr(
            mod.QMessageBox, "information", staticmethod(lambda *a, **k: None))

        dialog._test_chat()

        # what is about to be saved, not what was saved last time
        assert captured["config"].base_url == "https://gw.corp/v1"
        assert captured["config"].model == "gpt-x"
        assert captured["config"].provider == "anthropic"
        assert captured["messages"][0]["role"] == "user"
        assert dialog._test_btn.isEnabled()

    def test_failure_shows_the_servers_own_words(self, qtbot, monkeypatch):
        dialog = self._dialog(qtbot)

        def fail(messages, config):
            raise mod.ai.LLMError("HTTP 400: model not deployed here")

        monkeypatch.setattr(mod.ai, "chat_completion", fail)
        warnings = []
        monkeypatch.setattr(
            mod.QMessageBox, "warning",
            staticmethod(lambda *a, **k: warnings.append(a)))

        dialog._test_chat()

        assert "model not deployed here" in warnings[0][2]
        assert dialog._test_btn.isEnabled()


def _keys():
    return keys.default_store()


class TestMigration:
    """A machine set up before profiles had one connection in QSettings."""

    def test_old_connection_becomes_the_first_profile(self):
        settings = mod.QSettings()
        settings.setValue("ai/base_url", "https://gw.corp/v1")
        settings.setValue("ai/model", "gpt-x")
        settings.setValue("ai/provider", "anthropic")

        loaded = mod.load_profiles()
        assert len(loaded.profiles) == 1
        profile = loaded.active()
        assert (profile.base_url, profile.model, profile.provider) == (
            "https://gw.corp/v1", "gpt-x", "anthropic")
        assert profile.name == "gw.corp"
        assert profiles.exists()

    def test_the_key_moves_out_of_qsettings(self):
        mod.QSettings().setValue("ai/api_key", "sk-old")

        profile = mod.load_profiles().active()
        assert _keys().get(profile.key_name) == "sk-old"
        assert not mod.QSettings().contains("ai/api_key")
        assert mod.load_llm_config().api_key == "sk-old"

    def test_a_refused_key_stays_where_it_was(self, monkeypatch):
        mod.QSettings().setValue("ai/api_key", "sk-old")

        def refuse(self, name, value):
            raise keys.KeyStoreError("locked")

        monkeypatch.setattr(keys.KeyStore, "set", refuse)
        mod.load_profiles()
        assert mod.QSettings().value("ai/api_key") == "sk-old"
        assert mod.load_llm_config().api_key == "sk-old"

    def test_a_refused_key_is_moved_by_the_next_save(self, qtbot, monkeypatch):
        mod.QSettings().setValue("ai/api_key", "sk-old")
        real_set = keys.KeyStore.set
        monkeypatch.setattr(keys.KeyStore, "set",
                            lambda self, n, v: (_ for _ in ()).throw(
                                keys.KeyStoreError("locked")))
        mod.load_profiles()
        monkeypatch.setattr(keys.KeyStore, "set", real_set)

        dialog = mod.AiSettingsDialog()
        qtbot.addWidget(dialog)
        assert dialog._api_key.text() == "sk-old"
        dialog._save()
        assert not mod.QSettings().contains("ai/api_key")
        assert _keys().get(profiles.load().active().key_name) == "sk-old"

    def test_migrates_once(self):
        mod.QSettings().setValue("ai/model", "first")
        mod.load_profiles()
        mod.QSettings().setValue("ai/model", "second")
        assert mod.load_profiles().active().model == "first"


class TestProfiles:
    def _dialog(self, qtbot):
        dialog = mod.AiSettingsDialog()
        qtbot.addWidget(dialog)
        return dialog

    def test_key_is_never_in_the_profiles_file(self, qtbot):
        dialog = self._dialog(qtbot)
        dialog._api_key.setText("sk-secret-123")
        dialog._save()

        assert "sk-secret-123" not in profiles.profiles_path().read_text()
        assert mod.load_llm_config().api_key == "sk-secret-123"

    def test_new_connection_is_the_one_in_use_after_save(self, qtbot):
        dialog = self._dialog(qtbot)
        dialog._new_btn.click()
        dialog._name.setText("Work gateway")
        dialog._rename_current("Work gateway")
        dialog._base_url.setText("https://gw.corp/v1")
        dialog._api_key.setText("sk-work")
        dialog._save()

        loaded = profiles.load()
        assert [p.name for p in loaded.profiles] == ["Local server", "Work gateway"]
        assert loaded.active().name == "Work gateway"
        config = mod.load_llm_config()
        assert config.base_url == "https://gw.corp/v1"
        assert config.api_key == "sk-work"

    def test_switching_keeps_each_profiles_edits(self, qtbot):
        dialog = self._dialog(qtbot)
        dialog._api_key.setText("sk-local")
        dialog._new_btn.click()
        dialog._base_url.setText("https://gw.corp/v1")
        dialog._profile_combo.setCurrentIndex(0)

        assert dialog._base_url.text() == DEFAULT_BASE_URL
        assert dialog._api_key.text() == "sk-local"
        dialog._profile_combo.setCurrentIndex(1)
        assert dialog._base_url.text() == "https://gw.corp/v1"

    def test_duplicate_copies_settings_and_key(self, qtbot):
        dialog = self._dialog(qtbot)
        dialog._model.setCurrentText("qwen3")
        dialog._api_key.setText("sk-dup")
        dialog._dup_btn.click()
        assert dialog._name.text() == "Local server copy"
        assert dialog._model.currentText() == "qwen3"
        assert dialog._api_key.text() == "sk-dup"
        dialog._save()
        assert mod.load_llm_config().api_key == "sk-dup"

    def test_delete_removes_profile_and_its_key(self, qtbot):
        dialog = self._dialog(qtbot)
        dialog._new_btn.click()
        dialog._api_key.setText("sk-gone")
        dialog._save()
        gone = profiles.load().active()
        assert _keys().get(gone.key_name) == "sk-gone"

        dialog = self._dialog(qtbot)
        dialog._del_btn.click()
        dialog._save()
        assert len(profiles.load().profiles) == 1
        assert _keys().get(gone.key_name) == ""

    def test_last_connection_cannot_be_deleted(self, qtbot):
        dialog = self._dialog(qtbot)
        assert not dialog._del_btn.isEnabled()

    def test_cancel_after_delete_keeps_everything(self, qtbot):
        dialog = self._dialog(qtbot)
        dialog._new_btn.click()
        dialog._save()
        dialog = self._dialog(qtbot)
        dialog._del_btn.click()
        dialog.reject()
        assert len(profiles.load().profiles) == 2

    def test_bad_extra_json_is_refused_on_save(self, qtbot, monkeypatch):
        dialog = self._dialog(qtbot)
        dialog._extra.setPlainText("{not json")
        warnings = []
        monkeypatch.setattr(
            mod.QMessageBox, "warning",
            staticmethod(lambda *a, **k: warnings.append(a)))
        dialog._save()
        assert warnings and "Extra request JSON" in warnings[0][2]
        assert not profiles.exists() or profiles.load().active().extra_json == ""

    def test_request_options_reach_ask_ai(self, qtbot):
        dialog = self._dialog(qtbot)
        dialog._thinking.setCurrentText("off")
        dialog._max_tokens.setValue(2048)
        dialog._extra.setPlainText('{"top_p": 0.5}')
        dialog._save()
        config = mod.load_llm_config()
        assert (config.thinking, config.max_tokens, config.extra) == (
            "off", 2048, {"top_p": 0.5})


class TestWhereTheDataGoes:
    def _dialog(self, qtbot):
        dialog = mod.AiSettingsDialog()
        qtbot.addWidget(dialog)
        return dialog

    def test_localhost_is_local_and_defaults_to_anything(self, qtbot):
        dialog = self._dialog(qtbot)
        dialog._base_url.setText("http://127.0.0.1:1234/v1")
        assert "nothing leaves this PC" in dialog._where.text()
        assert "Analyse" in dialog._ceiling.itemText(0)

    def test_online_defaults_to_schema(self, qtbot):
        dialog = self._dialog(qtbot)
        dialog._base_url.setText("https://gw.corp/v1")
        assert "Online — gw.corp" in dialog._where.text()
        assert "Schema" in dialog._ceiling.itemText(0)

    def test_claiming_local_for_a_remote_address_warns(self, qtbot):
        dialog = self._dialog(qtbot)
        dialog.show()
        dialog._base_url.setText("https://gw.corp/v1")
        dialog._location.setCurrentIndex(dialog._location.findData("local"))
        assert dialog._where_warning.isVisible()
        assert "gw.corp" in dialog._where_warning.text()

    def test_ceiling_saves(self, qtbot):
        dialog = self._dialog(qtbot)
        dialog._ceiling.setCurrentIndex(3)   # Default, then levels 0..5
        dialog._location.setCurrentIndex(dialog._location.findData("online"))
        dialog._save()
        profile = profiles.load().active()
        assert profile.ceiling == 2
        assert profile.location == "online"
        assert profile.effective_ceiling() == 2

    def test_ceiling_survives_a_location_change(self, qtbot):
        dialog = self._dialog(qtbot)
        dialog._ceiling.setCurrentIndex(5)
        dialog._base_url.setText("https://gw.corp/v1")
        assert dialog._ceiling.currentData() == 4

    def test_key_store_is_named(self, qtbot):
        dialog = self._dialog(qtbot)
        assert "No system keychain" in dialog._key_where.text()
